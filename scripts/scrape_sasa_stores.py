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
import urllib.request
from pathlib import Path

import pandas as pd

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
    req = urllib.request.Request(STORE_API_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("Data", {}).get("List", [])


def collect_counts(snapshot_date: str) -> pd.DataFrame:
    stores = _fetch_stores()
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


def append_snapshot(df: pd.DataFrame, out_path: Path) -> pd.DataFrame:
    existing = pd.read_parquet(out_path) if out_path.exists() else None
    if df.empty:
        return existing if existing is not None else df
    combined = df if existing is None else pd.concat([existing, df], ignore_index=True)
    combined = (
        combined.drop_duplicates(subset=["date", "district"], keep="last")
        .sort_values(["date", "district"])
        .reset_index(drop=True)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(out_path, index=False)
    return combined


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Sa Sa store counts.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    out_path = Path(args.data_dir) / "processed" / "sasa_stores" / "store_counts.parquet"

    print(f"Sa Sa store-count snapshot for {args.date}")
    print("=" * 50)

    df = collect_counts(args.date)
    total_row = df[df["district"] == "TOTAL"].iloc[0] if not df.empty else {}
    total = int(total_row.get("store_count", 0))

    print(f"Total stores: {total}")
    for _, row in df[df["district"] != "TOTAL"].iterrows():
        print(f"  {row['district']}: {row['store_count']}")

    combined = append_snapshot(df, out_path)
    print(f"Wrote {out_path} ({len(combined)} rows, {combined['date'].nunique()} snapshots)")


if __name__ == "__main__":
    main()
