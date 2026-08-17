"""Persist a read-only audit of legacy HKEX PIT timestamp recovery.

This sidecar proves that legacy date-only filing rows were matched to an
official HKEX title-search payload.  It deliberately does not promote rows
into the event study or modify the sibling financial-data database.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd


HKEX_BASE_URL = "https://www1.hkexnews.hk"
RECOVERY_BASIS = "source_timestamp_proxy"
RECOVERY_STATUS = "official_datetime_verified"
EXCLUSION_REASON = (
    "PIT recovery audit only; promotion requires candidate taxonomy, market "
    "coverage, cluster and signal gates"
)


def _json_object(value: object) -> dict[str, object]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_hkt(value: object) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    parsed = pd.to_datetime(str(value), errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None
    timestamp = pd.Timestamp(parsed)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("Asia/Hong_Kong")
    else:
        timestamp = timestamp.tz_convert("Asia/Hong_Kong")
    return timestamp.tz_convert("UTC")


def _normalise_url(value: object) -> str:
    return str(value or "").strip().split("?", 1)[0]


def build_sidecar(legacy: pd.DataFrame, recovered: pd.DataFrame) -> pd.DataFrame:
    """Build one row per legacy filing recovered in the corrected run."""
    required_legacy = {"filing_id", "document_url", "ticker", "announcement_date"}
    required_recovered = {
        "filing_id", "ticker", "announcement_date", "document_url",
        "announcement_at", "available_at", "collected_at",
        "availability_basis", "source_item_json",
    }
    missing_legacy = sorted(required_legacy - set(legacy.columns))
    missing_recovered = sorted(required_recovered - set(recovered.columns))
    if missing_legacy or missing_recovered:
        raise ValueError(
            f"missing columns: legacy={missing_legacy}, recovered={missing_recovered}"
        )

    legacy_ids = set(legacy["filing_id"].dropna().astype(str))
    selected = recovered[recovered["filing_id"].astype(str).isin(legacy_ids)].copy()
    if selected["filing_id"].duplicated().any():
        raise ValueError("recovered input contains duplicate filing_id values")

    legacy_url_by_id = (
        legacy.assign(filing_id=legacy["filing_id"].astype(str))
        .drop_duplicates("filing_id")
        .set_index("filing_id")["document_url"]
        .to_dict()
    )
    rows: list[dict[str, object]] = []
    for source in selected.to_dict(orient="records"):
        payload = _json_object(source.get("source_item_json"))
        official_raw = payload.get("DATE_TIME")
        official_at = _parse_hkt(official_raw)
        announcement_at = pd.to_datetime(source.get("announcement_at"), utc=True, errors="coerce")
        available_at = pd.to_datetime(source.get("available_at"), utc=True, errors="coerce")
        collected_at = pd.to_datetime(source.get("collected_at"), utc=True, errors="coerce")
        expected_url = urljoin(HKEX_BASE_URL, str(payload.get("FILE_LINK") or ""))
        url_ok = bool(expected_url and _normalise_url(expected_url) == _normalise_url(source.get("document_url")))
        timestamp_ok = bool(pd.notna(official_at) and pd.notna(announcement_at) and official_at == announcement_at)
        delta_minutes = None if pd.isna(announcement_at) or pd.isna(available_at) else float((available_at - announcement_at).total_seconds() / 60)
        availability_ok = delta_minutes == 10.0
        retrospective_delay_minutes = None if pd.isna(collected_at) or pd.isna(available_at) else float((collected_at - available_at).total_seconds() / 60)
        retrospective_ok = bool(
            retrospective_delay_minutes is not None
            and retrospective_delay_minutes >= 24 * 60
        )
        basis_ok = source.get("availability_basis") == RECOVERY_BASIS
        verified = bool(url_ok and timestamp_ok and availability_ok and retrospective_ok and basis_ok)
        rows.append(
            {
                "filing_id": str(source["filing_id"]),
                "ticker": source.get("ticker"),
                "announcement_date": source.get("announcement_date"),
                "document_url": source.get("document_url"),
                "legacy_document_url": legacy_url_by_id.get(str(source["filing_id"])),
                "hkex_news_id": payload.get("NEWS_ID"),
                "hkex_file_link": payload.get("FILE_LINK"),
                "hkex_stock_code": payload.get("STOCK_CODE"),
                "hkex_title": payload.get("TITLE"),
                "official_hkt_datetime": official_raw,
                "announcement_at": announcement_at,
                "available_at": available_at,
                "collected_at": collected_at,
                "availability_basis": source.get("availability_basis"),
                "availability_delta_minutes": delta_minutes,
                "retrospective_delay_minutes": retrospective_delay_minutes,
                "url_continuity_ok": url_ok,
                "official_timestamp_ok": timestamp_ok,
                "availability_delta_ok": availability_ok,
                "retrospective_collection_ok": retrospective_ok,
                "availability_basis_ok": basis_ok,
                "pit_recovery_status": RECOVERY_STATUS if verified else "verification_failed",
                "event_study_eligible": False,
                "event_study_exclusion_reason": EXCLUSION_REASON,
            }
        )
    return pd.DataFrame(rows)


def run(
    *,
    legacy_paths: list[Path],
    recovered_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    legacy = pd.concat([pd.read_parquet(path) for path in legacy_paths], ignore_index=True)
    legacy = legacy.drop_duplicates("filing_id").reset_index(drop=True)
    recovered = pd.read_parquet(recovered_path)
    sidecar = build_sidecar(legacy, recovered)
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / "pit_recovered_filings.parquet"
    csv_path = output_dir / "pit_recovered_filings.csv"
    sidecar.to_parquet(parquet_path, index=False)
    sidecar.to_csv(csv_path, index=False)
    errors: list[str] = []
    if len(sidecar) != 162:
        errors.append(f"expected 162 legacy recoveries, found {len(sidecar)}")
    for column in (
        "url_continuity_ok", "official_timestamp_ok", "availability_delta_ok",
        "retrospective_collection_ok", "availability_basis_ok",
    ):
        if not bool(sidecar[column].all()):
            errors.append(f"recovery invariant failed: {column}")
    if bool(sidecar["event_study_eligible"].any()):
        errors.append("PIT recovery sidecar contains event-study-eligible rows")
    manifest = {
        "version": "hkex_pit_recovery_sidecar.v1",
        "status": "failed" if errors else "ok",
        "source": "official HKEX title-search DATE_TIME matched by filing_id/document_url",
        "legacy_input_paths": [str(path) for path in legacy_paths],
        "recovered_input_path": str(recovered_path),
        "legacy_unique_rows": int(len(legacy)),
        "recovered_input_rows": int(len(recovered)),
        "recovered_legacy_rows": int(len(sidecar)),
        "official_datetime_verified_rows": int(sidecar["pit_recovery_status"].eq(RECOVERY_STATUS).sum()),
        "event_study_eligible_rows": int(sidecar["event_study_eligible"].sum()),
        "availability_basis_counts": sidecar["availability_basis"].value_counts(dropna=False).to_dict(),
        "production_database_modified": False,
        "errors": errors,
        "artifacts": {"parquet": str(parquet_path), "csv": str(csv_path)},
    }
    manifest_path = output_dir / "pit_recovery_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--financial-data-root", type=Path, default=Path(__file__).resolve().parents[2] / "financial-data")
    parser.add_argument("--recovered-path", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/hkex_pit_recovery_sidecar"))
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    filing_root = args.financial_data_root / "data/processed/hk_financials/hkex_filings/source=hkex"
    legacy_paths = [
        filing_root / "snapshot_date=2026-07-26/hkex-hkex-20260726T173614Z.parquet",
        filing_root / "snapshot_date=2026-07-27/hkex-hkex-20260727T081536Z.parquet",
    ]
    recovered_path = args.recovered_path or (
        filing_root / "snapshot_date=2026-08-08/hkex-hkex-20260808T113518Z.parquet"
    )
    print(json.dumps(run(legacy_paths=legacy_paths, recovered_path=recovered_path, output_dir=args.output_dir), indent=2, ensure_ascii=False, default=str))
