"""Higher-frequency global object-launch counts from the public CelesTrak SATCAT.

This is deliberately a separate contract from the UNOOSA/OWID annual benchmark.
SATCAT is a current catalogue of known objects with historical launch dates; it
can support monthly aggregation, but it is not a complete registration count
and includes rocket bodies, debris and unknown objects unless filtered.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timezone
import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, CELESTRAK_SATCAT_URL, NORMALIZED_DIR
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SATCAT_COLUMNS = [
    "object_name",
    "object_id",
    "norad_cat_id",
    "object_type",
    "owner",
    "launch_date",
    "launch_site",
    "decay_date",
]
MONTHLY_COLUMNS = ["month", "object_type", "object_count", "fetched_at"]
OBJECT_TYPE_LABELS = {
    "PAY": "Payload",
    "R/B": "Rocket body",
    "DEB": "Debris",
    "UNK": "Unknown",
}

MONTHLY_PATH = NORMALIZED_DIR / "global_cataloged_objects_monthly.jsonl"
MANIFEST_PATH = NORMALIZED_DIR / "global_cataloged_objects_manifest.json"


def _empty_satcat_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=SATCAT_COLUMNS)


def fetch_celestrak_satcat() -> pd.DataFrame:
    """Fetch the public SATCAT CSV and retain launch-date-bearing objects."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        response = requests.get(
            CELESTRAK_SATCAT_URL,
            headers=DEFAULT_HEADERS,
            timeout=DEFAULT_TIMEOUT * 4,
        )
        response.raise_for_status()
        raw = response.content
        save_raw_snapshot(
            "celestrak_satcat",
            raw,
            file_ext="csv",
            source_url=CELESTRAK_SATCAT_URL,
        )
        frame = pd.read_csv(io.BytesIO(raw), dtype={"OBJECT_ID": "string"})
        required = {"OBJECT_NAME", "OBJECT_ID", "NORAD_CAT_ID", "OBJECT_TYPE", "OWNER", "LAUNCH_DATE", "LAUNCH_SITE", "DECAY_DATE"}
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"SATCAT missing columns: {sorted(missing)}")

        frame = frame.rename(columns={
            "OBJECT_NAME": "object_name",
            "OBJECT_ID": "object_id",
            "NORAD_CAT_ID": "norad_cat_id",
            "OBJECT_TYPE": "object_type",
            "OWNER": "owner",
            "LAUNCH_DATE": "launch_date",
            "LAUNCH_SITE": "launch_site",
            "DECAY_DATE": "decay_date",
        })
        frame = frame[SATCAT_COLUMNS].copy()
        frame["launch_date"] = pd.to_datetime(frame["launch_date"], errors="coerce", utc=True)
        frame = frame.dropna(subset=["object_id", "launch_date"]).copy()
        frame["object_type"] = frame["object_type"].fillna("UNK").astype(str).str.strip()
        frame["object_type"] = frame["object_type"].replace({"": "UNK"})
        frame["norad_cat_id"] = pd.to_numeric(frame["norad_cat_id"], errors="coerce").astype("Int64")
        frame["launch_date"] = frame["launch_date"].dt.strftime("%Y-%m-%d")
        frame["decay_date"] = pd.to_datetime(frame["decay_date"], errors="coerce", utc=True).dt.strftime("%Y-%m-%d")
        frame = frame.sort_values(["launch_date", "object_id"], kind="stable").reset_index(drop=True)
        frame.attrs["source"] = "live"
        frame.attrs["fetched_at"] = fetched_at
        frame.attrs["source_url"] = CELESTRAK_SATCAT_URL
        frame.attrs["raw_records"] = len(frame)
        return frame
    except Exception as exc:
        logger.warning("Failed to fetch CelesTrak SATCAT: %s", exc)
        empty = _empty_satcat_frame()
        empty.attrs["source"] = "unavailable"
        empty.attrs["fetched_at"] = fetched_at
        empty.attrs["source_url"] = CELESTRAK_SATCAT_URL
        return empty


def build_monthly_catalog_summary(
    frame: pd.DataFrame,
    *,
    lookback_months: int | None = 120,
) -> pd.DataFrame:
    """Aggregate SATCAT objects by launch month and catalog object type.

    The full object-level source is retained in the raw snapshot. The returned
    dashboard frame is zero-filled and optionally limited to the latest
    ``lookback_months`` to stay compact for the portable renderer.
    """
    if frame.empty:
        return pd.DataFrame(columns=MONTHLY_COLUMNS)

    work = frame.copy()
    work["launch_date"] = pd.to_datetime(work["launch_date"], errors="coerce", utc=True)
    work = work.dropna(subset=["launch_date"]).copy()
    work["month"] = work["launch_date"].dt.tz_convert(None).dt.to_period("M").astype(str)
    work["object_type"] = work["object_type"].fillna("UNK").astype(str).str.strip().replace({"": "UNK"})
    observed_types = sorted(set(work["object_type"]).union(OBJECT_TYPE_LABELS))
    grouped = (
        work.groupby(["month", "object_type"], as_index=False)
        .size()
        .rename(columns={"size": "object_count"})
    )
    first_month = pd.Period(work["month"].min(), freq="M")
    last_month = pd.Period(work["month"].max(), freq="M")
    if lookback_months is not None:
        first_month = max(first_month, last_month - (lookback_months - 1))
    months = pd.period_range(first_month, last_month, freq="M").astype(str).tolist()
    grid = pd.MultiIndex.from_product([months, observed_types], names=["month", "object_type"]).to_frame(index=False)
    summary = grid.merge(grouped, on=["month", "object_type"], how="left")
    summary["object_count"] = summary["object_count"].fillna(0).astype(int)
    summary["object_type"] = summary["object_type"].map(lambda value: OBJECT_TYPE_LABELS.get(value, value))
    fetched_at = frame.attrs.get("fetched_at")
    summary["fetched_at"] = fetched_at
    return summary[MONTHLY_COLUMNS].sort_values(["month", "object_type"], kind="stable").reset_index(drop=True)


def persist_monthly_summary(summary: pd.DataFrame, *, fetched_at: str | None = None) -> None:
    """Persist the compact monthly contract and its source manifest."""
    if summary.empty:
        return
    MONTHLY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MONTHLY_PATH.open("w", encoding="utf-8") as handle:
        for row in summary.to_dict(orient="records"):
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    manifest = {
        "dataset": "global_cataloged_objects_monthly",
        "source": "CelesTrak SATCAT",
        "source_url": CELESTRAK_SATCAT_URL,
        "fetched_at": fetched_at or summary["fetched_at"].dropna().iloc[0],
        "grain": "launch-month × CelesTrak object type",
        "lookback_months": 120,
        "caveat": "Cataloged objects with known launch dates; not equivalent to UNOOSA registered objects and includes rocket bodies, debris and unknown objects.",
        "records": int(len(summary)),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_monthly_summary() -> pd.DataFrame:
    """Load the persisted compact monthly SATCAT contract if present."""
    if not MONTHLY_PATH.exists():
        return pd.DataFrame(columns=MONTHLY_COLUMNS)
    rows = []
    for line in MONTHLY_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("Skipping malformed SATCAT monthly row")
    return pd.DataFrame(rows, columns=MONTHLY_COLUMNS)
