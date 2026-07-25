"""Weekly store-count scraper for Chow Tai Fook (周大福, 01929.HK).

Uses the Demandware (Salesforce Commerce Cloud) Stores-SearchStores API
which returns a complete list of all Chow Tai Fook store locations with
IDs, names, addresses, and coordinates.

The endpoint is discovered from the store locator page at
/en-hk/stores. The number of returned store records *is* the store count,
so no per-store page fetches are needed.

Output: data/processed/ctf_stores/store_counts.parquet
    columns: date, region, store_count

Run:
    python scripts/scrape_ctf_stores.py
    python scripts/scrape_ctf_stores.py --data-dir data --date 2026-06-24
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.request
import urllib.error
from pathlib import Path

import pandas as pd

STORES_API_URL = (
    "https://www.chowtaifook.com/on/demandware.store/Sites-ctfeshop-hk-Site/en_HK/"
    "Stores-SearchStores?format=ajax"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}


def _fetch_stores() -> list[dict]:
    """Fetch all CTF stores from the Demandware API."""
    req = urllib.request.Request(STORES_API_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("stores", [])


def collect_counts(snapshot_date: str) -> pd.DataFrame:
    """Scrape and return store counts grouped by region/state."""
    stores = _fetch_stores()
    total = len(stores)

    # Count by region (stateCode = HK district / China province)
    by_region: dict[str, int] = {}
    for s in stores:
        region = (s.get("stateCode") or s.get("city") or "Unknown").strip()
        by_region[region] = by_region.get(region, 0) + 1

    rows = [
        {
            "date": snapshot_date,
            "region": region,
            "store_count": count,
        }
        for region, count in sorted(by_region.items(), key=lambda x: -x[1])
    ]
    rows.append({
        "date": snapshot_date,
        "region": "TOTAL",
        "store_count": total,
    })
    return pd.DataFrame(rows)


def append_snapshot(df: pd.DataFrame, out_path: Path) -> pd.DataFrame:
    """Append snapshot to existing parquet file, deduplicated on (date, region)."""
    existing = pd.read_parquet(out_path) if out_path.exists() else None
    combined = df if existing is None else pd.concat([existing, df], ignore_index=True)
    combined = (
        combined.drop_duplicates(subset=["date", "region"], keep="last")
        .sort_values(["date", "region"])
        .reset_index(drop=True)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(out_path, index=False)
    return combined


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Chow Tai Fook store counts.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    out_path = Path(args.data_dir) / "processed" / "ctf_stores" / "store_counts.parquet"

    print(f"Chow Tai Fook store-count snapshot for {args.date}")
    print("=" * 50)

    df = collect_counts(args.date)
    total = int(df[df["region"] == "TOTAL"]["store_count"].iloc[0])
    n_regions = len(df) - 1

    print(f"Total stores: {total} across {n_regions} regions")
    print(f"Top 5 regions:")
    for _, row in df[df["region"] != "TOTAL"].head(5).iterrows():
        print(f"  {row['region']}: {row['store_count']}")

    combined = append_snapshot(df, out_path)
    print(f"Wrote {out_path} ({len(combined)} rows, {combined['date'].nunique()} snapshots)")


if __name__ == "__main__":
    main()
