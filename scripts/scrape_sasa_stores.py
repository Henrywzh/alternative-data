"""Weekly store-count scraper for Sa Sa International (莎莎, 00178.HK).

Uses the 91app web API (the e-commerce platform behind sasa.com.hk) to
retrieve all Sa Sa physical store locations in Hong Kong.

The API returns stores near a given lat/lon coordinate. Since all HK stores
are within range of a central coordinate, a single query covers all locations.

Output: data/processed/sasa_stores/store_counts.parquet
    columns: date, district, store_count

Run:
    python scripts/scrape_sasa_stores.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from store_scraper_common import append_snapshot, fetch_url  # noqa: E402

STORE_API_URL = (
    "https://webapi.91app.hk/webapi/LocationV2/GetLocationList"
    "?lat=22.3193&lon=114.1694&startIndex=0&count=200&shopId=17&lang=zh-HK"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _fetch_stores() -> list[dict]:
    body = fetch_url(STORE_API_URL, headers=HEADERS, timeout=30)
    if body is None:
        return []
    data = json.loads(body.decode("utf-8"))
    return data.get("Data", {}).get("List", [])


def collect_counts(snapshot_date: str) -> pd.DataFrame:
    stores = _fetch_stores()
    if not stores:
        return pd.DataFrame()
    total = len(stores)

    # Count by district (CityName)
    by_district: dict[str, int] = {}
    for s in stores:
        district = s.get("CityName") or s.get("AreaName") or "Unknown"
        by_district[district] = by_district.get(district, 0) + 1

    rows = [
        {"date": snapshot_date, "district": d, "store_count": c}
        for d, c in sorted(by_district.items(), key=lambda x: -x[1])
    ]
    total_entry = {"date": snapshot_date, "district": "TOTAL", "store_count": total}
    if rows:
        # Insert total at top
        rows.insert(0, total_entry)
    else:
        rows = [total_entry]
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Sa Sa store counts.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    out_path = Path(args.data_dir) / "processed" / "sasa_stores" / "store_counts.parquet"

    print(f"Sa Sa store-count snapshot for {args.date}")
    print("=" * 50)

    df = collect_counts(args.date)
    if df.empty:
        print("  Sa Sa: could not extract store data from API.")
    else:
        total_row = df[df["district"] == "TOTAL"].iloc[0]
        total = int(total_row.get("store_count", 0))
        print(f"Total stores: {total}")
        for _, row in df[df["district"] != "TOTAL"].iterrows():
            print(f"  {row['district']}: {row['store_count']}")

    combined = append_snapshot(df, out_path, key_column="district")
    if combined is not None and not combined.empty:
        print(f"Wrote {out_path} ({len(combined)} rows, {combined['date'].nunique()} snapshots)")
    else:
        print(f"No snapshot written to {out_path} (no prior history, no new data).")


if __name__ == "__main__":
    main()
