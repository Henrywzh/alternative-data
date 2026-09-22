"""Replay retained FactSet raw snapshots into the normalized article lanes."""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import json
from pathlib import Path
from typing import Any

from .client import FactsetEarningsClient
from .models import FactsetArticleRecord, FactsetEarningsObservation
from .storage import FactsetEarningsStorage


@dataclass(frozen=True)
class FactsetReplayResult:
    raw_run_id: str
    observations: list[FactsetEarningsObservation]
    catalog: list[FactsetArticleRecord]
    stats: dict[str, int]


def _read_payload(root: Path, entry: dict[str, Any]) -> str:
    path = root / str(entry["path"])
    if entry.get("gzip_payload") or path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    return path.read_text(encoding="utf-8", errors="replace")


def _manifest_for_run(raw_root: Path, run_id: str) -> dict[str, Any]:
    path = raw_root / run_id / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"FactSet manifest is not an object: {path}")
    return manifest


def _is_expected_topic_boundary_error(key: object, value: object) -> bool:
    """Recognize the known 404 that terminates FactSet topic pagination."""
    return (
        str(key).startswith("topic_page_")
        and "404" in str(value).lower()
        and "/topic/earnings/page/" in str(value).lower()
    )


def _is_replayable_manifest(manifest: dict[str, Any]) -> bool:
    """Return whether a manifest is complete enough for default replay.

    The topic endpoint currently signals the end of pagination with a 404 on
    the first page after the archive.  That expected boundary is harmless;
    article fetch, OCR, or DNS errors are not.  Explicitly selected partial
    runs remain available through ``allow_partial=True`` for forensic work.
    """
    status = str(manifest.get("status") or "").strip().lower()
    if status == "ok":
        return True
    errors = manifest.get("errors")
    return bool(
        status == "partial"
        and isinstance(errors, dict)
        and errors
        and all(_is_expected_topic_boundary_error(key, value) for key, value in errors.items())
    )


def latest_raw_run_id(base_dir: Path) -> str:
    """Return the newest replayable raw run that contains article HTML."""
    raw_root = base_dir / "data" / "raw" / "factset_earnings"
    candidates: list[tuple[str, str]] = []
    for manifest_path in raw_root.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict) or not _is_replayable_manifest(manifest):
            continue
        entries = manifest.get("entries", []) if isinstance(manifest, dict) else []
        has_articles = any(
            "/articles/" in str(entry.get("path", ""))
            and str(entry.get("path", "")).endswith(".html.gz")
            for entry in entries
            if isinstance(entry, dict)
        )
        if has_articles:
            candidates.append((str(manifest.get("finished_at_utc") or ""), manifest_path.parent.name))
    if not candidates:
        raise FileNotFoundError(f"No full FactSet raw snapshot found under {raw_root}")
    return max(candidates)[1]


def replay_raw_run(
    base_dir: Path,
    run_id: str | None = None,
    *,
    allow_partial: bool = False,
) -> FactsetReplayResult:
    """Parse one retained raw run using exactly the current client logic.

    Default selection refuses partial manifests so a failed collection cannot
    silently become a replacement normalized dataset. ``allow_partial`` is an
    explicit escape hatch for investigating an incomplete raw capture.
    """
    storage = FactsetEarningsStorage(base_dir)
    selected_run_id = run_id or latest_raw_run_id(base_dir)
    manifest = _manifest_for_run(storage.raw_root, selected_run_id)
    if not allow_partial and not _is_replayable_manifest(manifest):
        raise ValueError(
            f"FactSet raw run {selected_run_id!r} is partial or invalid; "
            "pass allow_partial=True only for forensic replay"
        )
    entries = [entry for entry in manifest.get("entries", []) if isinstance(entry, dict)]
    article_entries = [
        entry
        for entry in entries
        if "/articles/" in str(entry.get("path", ""))
        and str(entry.get("path", "")).endswith(".html.gz")
        and entry.get("metadata", {}).get("article_url")
    ]
    ocr_by_article: dict[str, list[str]] = {}
    for entry in entries:
        path = str(entry.get("path", ""))
        article_url = str(entry.get("metadata", {}).get("article_url") or "").strip()
        if "/ocr/" not in path or not path.endswith(".txt") or not article_url:
            continue
        ocr_by_article.setdefault(article_url, []).append(_read_payload(storage.raw_root, entry))

    client = FactsetEarningsClient(timeout_seconds=1.0)
    observations: list[FactsetEarningsObservation] = []
    catalog: list[FactsetArticleRecord] = []
    unsupported = 0
    invalid_dates = 0
    missing_quarters = 0
    ocr_images = 0
    for entry in article_entries:
        article_url = str(entry["metadata"]["article_url"])
        html = _read_payload(storage.raw_root, entry)
        metadata = client.extract_article_metadata(html)
        title = str(metadata.get("title") or "").strip()
        body_text = str(metadata.get("text") or "")
        if not client.is_relevant_article(title, body_text, article_url):
            continue
        ocr_texts = ocr_by_article.get(article_url, [])
        ocr_images += len(ocr_texts)
        combined_text = "\n".join(part for part in [title, body_text, *ocr_texts] if part)
        report_date = client.report_date_from_url(article_url) or str(metadata.get("report_date") or "")
        ref_quarter = client.infer_reference_quarter(combined_text, title, report_date)
        observation = client.parse_summary_metrics(
            combined_text,
            report_date,
            ref_quarter,
            source_url=article_url,
            fetched_at=str(entry.get("captured_at_utc") or manifest.get("finished_at_utc") or ""),
        )
        supported_count = client.supported_field_count(observation)
        if not report_date:
            extraction_status = "invalid_report_date"
            invalid_dates += 1
        elif not ref_quarter:
            extraction_status = "no_reference_quarter"
            missing_quarters += 1
        elif supported_count:
            extraction_status = "supported_observation"
            observations.append(observation)
        else:
            extraction_status = "no_supported_metrics"
            unsupported += 1
        catalog.append(
            FactsetArticleRecord(
                article_url=article_url,
                title=title,
                report_date=report_date,
                reference_quarter=ref_quarter,
                article_type=client.classify_article(title, combined_text, article_url),
                raw_run_id=selected_run_id,
                ocr_image_count=len(ocr_texts),
                body_char_count=len(body_text),
                supported_field_count=supported_count,
                extraction_status=extraction_status,
                fetched_at=str(entry.get("captured_at_utc") or manifest.get("finished_at_utc") or ""),
            )
        )

    stats = {
        "article_entries": len(article_entries),
        "relevant_articles": len(catalog),
        "supported_observations": len(observations),
        "unsupported_articles": unsupported,
        "invalid_dates": invalid_dates,
        "missing_reference_quarters": missing_quarters,
        "ocr_images": ocr_images,
    }
    return FactsetReplayResult(
        raw_run_id=selected_run_id,
        observations=observations,
        catalog=catalog,
        stats=stats,
    )
