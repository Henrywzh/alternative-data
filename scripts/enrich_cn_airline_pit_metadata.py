"""Backfill Cninfo publication metadata onto the cached airline KPI layers.

The numeric monthly parquet is already parsed from issuer PDFs. This utility
uses the official Cninfo announcement index to attach publication dates and
source URLs without re-parsing every historical PDF.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import scrape_cn_airline_traffic as scraper  # noqa: E402


MONTHLY_PATH = ROOT / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"
EVENT_PATH = ROOT / "data" / "processed" / "airline_traffic" / "china_airlines_operating_events.parquet"
REGISTRY_PATH = ROOT / "data" / "normalized" / "hk_transport" / "airline_operating_release_registry.csv"


def discover_release_registry(*, start_year: str = "2016-01-01") -> pd.DataFrame:
    retrieved_at = dt.datetime.now(dt.timezone.utc).isoformat()
    rows: list[dict] = []
    for info in scraper.AIRLINES:
        by_month: dict[str, dict] = {}
        for searchkey in info["searchkey"]:
            for announcement in scraper.fetch_announcements(
                info["code"], info["org_id"], searchkey, start_year=start_year
            ):
                by_month.setdefault(announcement["month"], announcement)
        for announcement in sorted(by_month.values(), key=lambda item: item["month"]):
            rows.append({
                "month": announcement["month"],
                "airline_code": info["code"],
                "airline_name": info["name"],
                **scraper._announcement_metadata(announcement, retrieved_at=retrieved_at),
            })
    registry = pd.DataFrame(rows, columns=scraper.RELEASE_REGISTRY_COLUMNS)
    registry = registry.drop_duplicates(["month", "airline_code"], keep="last")
    return registry.sort_values(["month", "airline_code"]).reset_index(drop=True)


def _merge_metadata(frame: pd.DataFrame, registry: pd.DataFrame, *, label: str) -> pd.DataFrame:
    metadata = registry[
        ["month", "airline_code", *scraper.PIT_METADATA_COLUMNS]
    ].drop_duplicates(["month", "airline_code"])
    result = frame.merge(metadata, on=["month", "airline_code"], how="left", validate="many_to_one")
    missing = result["announcement_date"].isna()
    if missing.any():
        examples = result.loc[missing, ["month", "airline_code"]].drop_duplicates().head(10)
        raise RuntimeError(f"{label} has {int(missing.sum())} rows without Cninfo metadata: {examples.to_dict('records')}")
    return result


def main() -> None:
    registry = discover_release_registry()
    registry_path = REGISTRY_PATH
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry.to_csv(registry_path, index=False)

    monthly = pd.read_parquet(MONTHLY_PATH)
    monthly = _merge_metadata(monthly, registry, label="monthly KPI layer")
    monthly.to_parquet(MONTHLY_PATH, index=False)

    if EVENT_PATH.exists():
        events = pd.read_parquet(EVENT_PATH)
        events = _merge_metadata(events, registry, label="operating event layer")
        events = events[[*scraper.AIRLINE_EVENT_COLUMNS, *scraper.PIT_METADATA_COLUMNS]]
        events.to_parquet(EVENT_PATH, index=False)

    print(f"Wrote release registry: {registry_path} ({len(registry)} rows)")
    print(f"Wrote monthly KPI layer: {MONTHLY_PATH} ({len(monthly)} rows)")
    if EVENT_PATH.exists():
        print(f"Wrote operating events: {EVENT_PATH} ({len(events)} rows)")
    print("Announcement-date coverage:", float(monthly["announcement_date"].notna().mean()))


if __name__ == "__main__":
    main()
