"""First-party Chinese Long March/Jielong launch records.

The official CALT/CASC tables are the inclusion authority for the national
launch baseline. Launch Library 2 is joined later as an enrichment source; an
LL2-only row is never counted as an official event by this module.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, NORMALIZED_DIR, RAW_DIR, ROOT_DIR
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

CASC_LONG_MARCH_URL = "https://www.spacechina.com/n25/n142/n152/n657792/c3556658/content.html"
CALT_LAUNCH_RECORD_URL = "http://calt.spacechina.com/n482/n505/index.html"
CALT_PAGE_PREFIX = "index_3805_"

HISTORY_PATH = NORMALIZED_DIR / "china_launch_events.jsonl"
PAYLOAD_HISTORY_PATH = NORMALIZED_DIR / "china_launch_payloads.jsonl"
MANIFEST_PATH = NORMALIZED_DIR / "china_launch_manifest.json"

EVENT_COLUMNS = [
    "event_id",
    "official_source_id",
    "official_sequence",
    "launch_date",
    "launch_time",
    "launch_time_precision",
    "rocket_name",
    "rocket_family",
    "rocket_variant",
    "mission_name",
    "launch_site",
    "launch_pad",
    "target_orbit",
    "mission_type",
    "outcome",
    "outcome_normalized",
    "program_class",
    "classification_status",
    "payload_summary",
    "payload_count",
    "official_source_url",
    "official_source_kind",
    "ll2_launch_id",
    "ll2_match_status",
    "ll2_match_confidence",
    "ll2_provider_name",
    "source_snapshot",
    "fetched_at",
    "parser_version",
]

PAYLOAD_COLUMNS = [
    "event_id",
    "payload_index",
    "payload_name",
    "payload_type",
    "source_url",
    "source_snapshot",
    "fetched_at",
]

PARSER_VERSION = "china-launch-records-v1"


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _decode_html(content: bytes, fallback_text: str = "") -> str:
    """Decode the legacy official pages without trusting bad HTTP headers."""
    for encoding in ("utf-8-sig", "gb18030", "big5"):
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "发射" in text or "运载火箭" in text or encoding == "utf-8-sig":
            return text
    return fallback_text or content.decode("utf-8", errors="replace")


def _parse_date(value: str) -> str | None:
    text = _clean_text(value)
    match = re.search(r"(\d{4})\s*(?:年|[./-])\s*(\d{1,2})\s*(?:月|[./-])\s*(\d{1,2})", text)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return f"{year:04d}-{month:02d}-{day:02d}"
    except ValueError:
        return None


_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _chinese_number(value: str) -> int | None:
    text = _clean_text(value)
    if text.isdigit():
        return int(text)
    if not text or any(char not in _CHINESE_DIGITS and char not in "十百千" for char in text):
        return None
    if text == "十":
        return 10
    if "百" in text or "千" in text:
        # The launch pages use small counts. Keep the parser conservative for
        # larger grammatical forms rather than emitting a guessed count.
        return None
    if "十" in text:
        left, right = text.split("十", 1)
        tens = _CHINESE_DIGITS.get(left, 1) if left else 1
        ones = _CHINESE_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    if len(text) == 1:
        return _CHINESE_DIGITS.get(text)
    return None


def parse_payload_count(summary: str) -> int | None:
    """Extract only counts explicitly expressed by the official text."""
    text = _clean_text(summary)
    patterns = [
        r"一箭\s*([零〇一二两三四五六七八九十百千\d]+)\s*[颗枚]?星",
        r"一箭\s*([零〇一二两三四五六七八九十百千\d]+)\s*颗",
        r"等\s*([零〇一二两三四五六七八九十百千\d]+)\s*颗[^，。]{0,8}卫星",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _chinese_number(match.group(1))
    return None


def _normalize_outcome(value: str) -> str:
    text = _clean_text(value).lower()
    if any(token in text for token in ("成功", "success", "successful")):
        return "Success"
    if any(token in text for token in ("失利", "失败", "failure", "failed")):
        return "Failure"
    return "Unknown"


def _rocket_family(rocket_name: str) -> str:
    text = _clean_text(rocket_name)
    if "捷龙" in text:
        return "捷龙"
    if "长征" in text:
        return "长征"
    return text or "未知"


def _rocket_signature(value: object) -> str:
    """Create a conservative cross-source rocket signature."""
    text = _clean_text(value).lower()
    text = text.replace("运载火箭", "").replace("rocket", "").replace("型", "")
    text = re.sub(r"[\s\-_—–号]+", "", text)
    if "长征" in text:
        model = re.search(r"长征([零〇一二两三四五六七八九十百千]+号?)([a-z甲乙丙丁改]?)", text)
        if model:
            number = _chinese_number(model.group(1).replace("号", ""))
            suffix = model.group(2)
            suffix = {"甲": "a", "乙": "b", "丙": "c", "丁": "d", "改": "a"}.get(suffix, suffix)
            if number is not None:
                return f"longmarch{number}{suffix}"
        model = re.search(r"(?:longmarch|longmarch)(\d+)([a-z]?)", text)
        if model:
            return f"longmarch{model.group(1)}{model.group(2)}"
    if "smartdragon" in text or "jielong" in text or "捷龙" in text:
        prefix = "jielong"
    elif "longmarch" in text or "changzheng" in text or "长征" in text:
        prefix = "longmarch"
    else:
        prefix = text
    for char, digit in _CHINESE_DIGITS.items():
        text = text.replace(char, str(digit))
    text = text.replace("改", "a").replace("甲", "a")
    text = text.replace("长征", "").replace("捷龙", "")
    text = text.replace("smartdragon", "").replace("jielong", "")
    text = text.replace("longmarch", "").replace("changzheng", "")
    return re.sub(r"[^a-z0-9]+", "", prefix + text)


def _normalize_site(value: object) -> str:
    text = _clean_text(value).lower()
    aliases = {
        "文昌": "wenchang",
        "中国文昌航天发射场": "wenchang",
        "海南商发": "hainancommercial",
        "海南商业航天发射场": "hainancommercial",
        "酒泉": "jiuquan",
        "酒泉卫星发射中心": "jiuquan",
        "西昌": "xichang",
        "西昌卫星发射中心": "xichang",
        "太原": "taiyuan",
        "太原卫星发射中心": "taiyuan",
        "广东阳江附近海域": "yangjiang",
        "山东海阳附近海域": "haiyang",
    }
    for source, target in aliases.items():
        if source in text:
            return target
    return re.sub(r"[^a-z0-9]+", "", text)


def _official_event_id(source_kind: str, sequence: str, launch_date: str, rocket_name: str) -> str:
    sequence_token = re.sub(r"[^0-9a-z]+", "-", sequence.lower()).strip("-")
    if sequence_token:
        return f"{source_kind}-{sequence_token}"
    digest = hashlib.sha1(f"{launch_date}|{rocket_name}".encode("utf-8")).hexdigest()[:12]
    return f"{source_kind}-{digest}"


def _build_event(
    *,
    source_kind: str,
    source_url: str,
    source_snapshot: str,
    launch_date: str,
    rocket_name: str,
    payload_summary: str,
    launch_site: str,
    sequence: str,
    outcome: str,
    fetched_at: str,
) -> dict:
    family = _rocket_family(rocket_name)
    is_jielong = "捷龙" in rocket_name or "jielong" in rocket_name.lower() or "smart dragon" in rocket_name.lower()
    return {
        "event_id": _official_event_id(source_kind, sequence, launch_date, rocket_name),
        "official_source_id": f"{source_kind}:{sequence or launch_date}",
        "official_sequence": sequence or None,
        "launch_date": launch_date,
        "launch_time": None,
        "launch_time_precision": "date",
        "rocket_name": _clean_text(rocket_name),
        "rocket_family": family,
        "rocket_variant": _clean_text(rocket_name),
        "mission_name": _clean_text(payload_summary) or None,
        "launch_site": _clean_text(launch_site) or None,
        "launch_pad": None,
        "target_orbit": None,
        "mission_type": None,
        "outcome": _clean_text(outcome) or None,
        "outcome_normalized": _normalize_outcome(outcome),
        "program_class": "state_owned_commercial" if is_jielong else "national_program",
        "classification_status": "verified",
        "payload_summary": _clean_text(payload_summary) or None,
        "payload_count": parse_payload_count(payload_summary),
        "official_source_url": source_url,
        "official_source_kind": source_kind,
        "ll2_launch_id": None,
        "ll2_match_status": "not_checked",
        "ll2_match_confidence": None,
        "ll2_provider_name": None,
        "source_snapshot": source_snapshot,
        "fetched_at": fetched_at,
        "parser_version": PARSER_VERSION,
    }


def _parse_casc_rows(html: str, source_url: str, source_snapshot: str, fetched_at: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    events = []
    for tr in soup.find_all("tr"):
        cells = [_clean_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["td", "th"])]
        if len(cells) < 5 or not cells[0].isdigit():
            continue
        launch_date = _parse_date(cells[2])
        if not launch_date or "长征" not in cells[1]:
            continue
        events.append(_build_event(
            source_kind="casc-long-march",
            source_url=source_url,
            source_snapshot=source_snapshot,
            launch_date=launch_date,
            rocket_name=cells[1],
            payload_summary=cells[3],
            launch_site=cells[4],
            sequence=f"long-march-{cells[0]}",
            outcome="成功",
            fetched_at=fetched_at,
        ))
    return events


def _parse_calt_rows(html: str, source_url: str, source_snapshot: str, fetched_at: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    events = []
    for tr in soup.find_all("tr"):
        cells = [_clean_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["td", "th"])]
        if len(cells) < 6 or not re.search(r"第\s*\d+\s*次", cells[4]):
            continue
        launch_date = _parse_date(cells[0])
        if not launch_date or ("捷龙" not in cells[1] and "长征" not in cells[1]):
            continue
        source_kind = "calt-jielong" if "捷龙" in cells[1] else "calt-long-march"
        events.append(_build_event(
            source_kind=source_kind,
            source_url=source_url,
            source_snapshot=source_snapshot,
            launch_date=launch_date,
            rocket_name=cells[1],
            payload_summary=cells[2],
            launch_site=cells[3],
            sequence=re.sub(r"\s+", "", cells[4]),
            outcome=cells[5],
            fetched_at=fetched_at,
        ))
    return events


def _save_html_snapshot(dataset_name: str, content: bytes, source_url: str) -> str:
    raw_path = save_raw_snapshot(dataset_name, content, file_ext="html", source_url=source_url)
    fetched_at = datetime.now(timezone.utc).isoformat()
    metadata_path = raw_path.with_suffix(raw_path.suffix + ".meta.json")
    metadata_path.write_text(json.dumps({
        "dataset": dataset_name,
        "source_url": source_url,
        "fetched_at": fetched_at,
        "sha256": hashlib.sha256(content).hexdigest(),
        "raw_path": str(raw_path),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    # Portable artifacts must not expose this machine's absolute filesystem
    # path. The normalized record keeps a repository-relative lineage token;
    # the sidecar retains the full local path for the build environment.
    return str(raw_path.relative_to(ROOT_DIR))


def _fetch_html(url: str, dataset_name: str) -> tuple[str, str] | None:
    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        raw_path = _save_html_snapshot(dataset_name, response.content, url)
        return _decode_html(response.content, response.text), raw_path
    except Exception as exc:
        logger.warning("Failed to fetch official launch records from %s: %s", url, exc)
        return None


def _discover_calt_pages(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    pages = {CALT_LAUNCH_RECORD_URL}
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if CALT_PAGE_PREFIX in href:
            pages.add(urljoin(CALT_LAUNCH_RECORD_URL, href))
    def page_number(url: str) -> int:
        match = re.search(r"index_3805_(\d+)\.html", url)
        return int(match.group(1)) if match else 0
    return sorted(pages, key=page_number)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed launch-history row in %s", path)
            continue
        if row.get("event_id"):
            rows.append(row)
    return rows


def _portable_snapshot_path(value: object) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        candidate = Path(text)
        if candidate.is_absolute():
            return str(candidate.resolve().relative_to(ROOT_DIR.resolve()))
    except (OSError, ValueError):
        pass
    return text


def _dedupe_events(rows: Iterable[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for row in rows:
        if not row.get("event_id"):
            continue
        normalized = {column: row.get(column) for column in EVENT_COLUMNS}
        for column, value in normalized.items():
            if isinstance(value, float) and math.isnan(value):
                normalized[column] = None
        normalized["source_snapshot"] = _portable_snapshot_path(row.get("source_snapshot"))
        previous = by_id.get(row["event_id"])
        if previous is None or str(row.get("fetched_at", "")) >= str(previous.get("fetched_at", "")):
            by_id[row["event_id"]] = normalized
    # CALT and CASC both publish some Long March events. Collapse those
    # observations into one canonical event while retaining the raw snapshots
    # from both pages. Prefer the CASC sequence when both first-party rows
    # agree on date, rocket and site.
    by_event_key: dict[tuple[str, str, str], dict] = {}
    source_priority = {"casc-long-march": 0, "calt-long-march": 1, "calt-jielong": 2}
    for row in by_id.values():
        key = (
            str(row.get("launch_date") or ""),
            _rocket_signature(row.get("rocket_name")),
            _normalize_site(row.get("launch_site")),
        )
        previous = by_event_key.get(key)
        if previous is None or source_priority.get(row.get("official_source_kind"), 9) < source_priority.get(previous.get("official_source_kind"), 9):
            by_event_key[key] = row
    return sorted(by_event_key.values(), key=lambda row: (str(row.get("launch_date") or ""), str(row.get("event_id"))))


def _payload_rows(events: Iterable[dict]) -> list[dict]:
    rows = []
    for event in events:
        summary = _clean_text(event.get("payload_summary"))
        if not summary:
            continue
        parts = [part.strip(" \"“”") for part in re.split(r"[、,，;；]", summary) if part.strip()]
        # A combined phrase is retained at event level. Only split text when
        # the source itself supplied separable names.
        if len(parts) == 1 and event.get("payload_count") not in (1, None):
            continue
        for index, name in enumerate(parts, start=1):
            rows.append({
                "event_id": event["event_id"],
                "payload_index": index,
                "payload_name": name,
                "payload_type": "satellite_or_spacecraft",
                "source_url": event.get("official_source_url"),
                "source_snapshot": event.get("source_snapshot"),
                "fetched_at": event.get("fetched_at"),
            })
    return rows


def _write_history(events: list[dict]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("w", encoding="utf-8") as handle:
        for row in events:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    payloads = _payload_rows(events)
    with PAYLOAD_HISTORY_PATH.open("w", encoding="utf-8") as handle:
        for row in payloads:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    dates = [row.get("launch_date") for row in events if row.get("launch_date")]
    MANIFEST_PATH.write_text(json.dumps({
        "parser_version": PARSER_VERSION,
        "event_count": len(events),
        "payload_row_count": len(payloads),
        "first_launch_date": min(dates) if dates else None,
        "last_launch_date": max(dates) if dates else None,
        "official_sources": [CASC_LONG_MARCH_URL, CALT_LAUNCH_RECORD_URL],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def load_china_launch_history() -> pd.DataFrame:
    rows = _read_jsonl(HISTORY_PATH)
    return pd.DataFrame(rows, columns=EVENT_COLUMNS) if rows else pd.DataFrame(columns=EVENT_COLUMNS)


def persist_china_launch_history(events: pd.DataFrame) -> None:
    """Persist the canonical event table after optional LL2 enrichment."""
    if events.empty:
        return
    _write_history(_dedupe_events(events.to_dict(orient="records")))


def fetch_official_china_launches(*, backfill: bool = False) -> pd.DataFrame:
    """Fetch the official baseline and merge it with local normalized history.

    The first run automatically performs the complete CALT pagination backfill.
    Later routine runs refresh the current CALT page and the complete CASC table;
    callers can pass ``backfill=True`` to explicitly refresh all CALT pages.
    """
    existing = _read_jsonl(HISTORY_PATH)
    fetched_at = datetime.now(timezone.utc).isoformat()
    fresh: list[dict] = []
    any_live = False

    casc_result = _fetch_html(CASC_LONG_MARCH_URL, "official_casc_long_march")
    if casc_result:
        html, raw_path = casc_result
        fresh.extend(_parse_casc_rows(html, CASC_LONG_MARCH_URL, raw_path, fetched_at))
        any_live = True

    calt_result = _fetch_html(CALT_LAUNCH_RECORD_URL, "official_calt_launch_records")
    if calt_result:
        html, raw_path = calt_result
        has_calt_long_march = any(row.get("official_source_kind") == "calt-long-march" for row in existing)
        urls = _discover_calt_pages(html) if (backfill or not existing or not has_calt_long_march) else [CALT_LAUNCH_RECORD_URL]
        # Re-use the already fetched base page and fetch only archive pages.
        for url in urls:
            if url == CALT_LAUNCH_RECORD_URL:
                page_html, page_raw = html, raw_path
            else:
                result = _fetch_html(url, "official_calt_launch_records")
                if not result:
                    continue
                page_html, page_raw = result
            fresh.extend(_parse_calt_rows(page_html, url, page_raw, fetched_at))
            any_live = True

    merged = _dedupe_events([*existing, *fresh])
    if merged and (any_live or not HISTORY_PATH.exists()):
        _write_history(merged)

    frame = pd.DataFrame(merged, columns=EVENT_COLUMNS) if merged else pd.DataFrame(columns=EVENT_COLUMNS)
    frame.attrs["source"] = "live" if any_live else "history" if merged else "unavailable"
    frame.attrs["backfill"] = bool(backfill or not existing)
    frame.attrs["official_event_count"] = len(frame)
    return frame


def _match_site(official_site: object, ll2_pad: object) -> bool:
    left = _normalize_site(official_site)
    right = _normalize_site(ll2_pad)
    if not left or not right:
        return True
    return left in right or right in left or (left == "hainancommercial" and "commercial" in right)


def enrich_with_ll2(events: pd.DataFrame, ll2_rows: pd.DataFrame) -> pd.DataFrame:
    """Join LL2 fields only to official events with a conservative match."""
    if events.empty or ll2_rows.empty:
        return events.copy()
    output = events.copy()
    if "launch_date" not in output:
        return output
    ll2 = ll2_rows.copy()
    ll2["ll2_date"] = pd.to_datetime(ll2["net_time"], errors="coerce", utc=True).dt.strftime("%Y-%m-%d")
    ll2["rocket_signature"] = ll2["rocket_name"].map(_rocket_signature)
    output["rocket_signature"] = output["rocket_name"].map(_rocket_signature)
    for index, event in output.iterrows():
        candidates = ll2[
            ll2["ll2_date"].eq(event.get("launch_date"))
            & ll2["rocket_signature"].eq(event.get("rocket_signature"))
        ]
        if len(candidates) > 1:
            site_matches = candidates[candidates["pad_name"].map(lambda value: _match_site(event.get("launch_site"), value))]
            if len(site_matches) == 1:
                candidates = site_matches
        if len(candidates) != 1:
            output.at[index, "ll2_match_status"] = "unmatched" if len(candidates) == 0 else "ambiguous"
            output.at[index, "ll2_match_confidence"] = None
            continue
        match = candidates.iloc[0]
        output.at[index, "launch_time"] = match.get("net_time") or event.get("launch_time")
        output.at[index, "launch_time_precision"] = "timestamp"
        output.at[index, "launch_pad"] = match.get("pad_name") or event.get("launch_pad")
        output.at[index, "target_orbit"] = match.get("orbit_abbrev") or event.get("target_orbit")
        output.at[index, "mission_type"] = match.get("mission_type") or event.get("mission_type")
        output.at[index, "ll2_launch_id"] = match.get("launch_id")
        output.at[index, "ll2_match_status"] = "matched"
        output.at[index, "ll2_match_confidence"] = "high" if _match_site(event.get("launch_site"), match.get("pad_name")) else "medium"
        output.at[index, "ll2_provider_name"] = match.get("provider_name")
        if not event.get("mission_name") or event.get("mission_name") in {"卫星", "Unknown Payload"}:
            output.at[index, "mission_name"] = match.get("name") or event.get("mission_name")
    return output.drop(columns=["rocket_signature"], errors="ignore").reindex(columns=EVENT_COLUMNS)


def build_china_launch_monthly(events: pd.DataFrame) -> pd.DataFrame:
    """Build a zero-filled class comparison series from canonical events."""
    columns = [
        "month",
        "program_class",
        "launch_count",
        "successful_launch_count",
        "failed_launch_count",
        "unknown_outcome_count",
        "verified_event_count",
        "source_coverage_note",
    ]
    if events.empty:
        return pd.DataFrame(columns=columns)
    frame = events.copy()
    frame["launch_date"] = pd.to_datetime(frame["launch_date"], errors="coerce")
    frame = frame[frame["launch_date"].notna()].drop_duplicates("event_id")
    frame = frame[frame["classification_status"].eq("verified")]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    frame["month"] = frame["launch_date"].dt.to_period("M").astype(str)
    grouped = frame.groupby(["month", "program_class"], dropna=False).agg(
        launch_count=("event_id", "nunique"),
        successful_launch_count=("outcome_normalized", lambda values: int((values == "Success").sum())),
        failed_launch_count=("outcome_normalized", lambda values: int((values == "Failure").sum())),
        unknown_outcome_count=("outcome_normalized", lambda values: int((values == "Unknown").sum())),
        verified_event_count=("event_id", "nunique"),
    ).reset_index()
    months = pd.period_range(frame["launch_date"].min(), frame["launch_date"].max(), freq="M").astype(str)
    classes = ["national_program", "state_owned_commercial", "commercial_provider"]
    grid = pd.MultiIndex.from_product([months, classes], names=["month", "program_class"]).to_frame(index=False)
    result = grid.merge(grouped, on=["month", "program_class"], how="left").fillna(0)
    for column in columns[2:]:
        if column == "source_coverage_note":
            continue
        result[column] = result[column].astype(int)
    result["source_coverage_note"] = "verified canonical events; artifact chart uses latest ten-year display window"
    return result[columns]


def build_rocket_family_summary(events: pd.DataFrame) -> pd.DataFrame:
    columns = ["program_class", "rocket_family", "launch_count"]
    if events.empty:
        return pd.DataFrame(columns=columns)
    frame = events[events["classification_status"].eq("verified")].drop_duplicates("event_id")
    if frame.empty:
        return pd.DataFrame(columns=columns)
    return (
        frame.groupby(["program_class", "rocket_family"], dropna=False)
        .size()
        .reset_index(name="launch_count")
        .sort_values(["program_class", "launch_count", "rocket_family"], ascending=[True, False, True])
        .reset_index(drop=True)
    )
