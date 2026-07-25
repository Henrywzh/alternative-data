"""Store-count tracker for Luk Fook (六福珠宝, 00590.HK).

Queries internal JSON endpoints hosted on www1.lukfook.com.hk:
1. /LF-AMap/home/getprovince: returns list of 31 mainland China provinces with IDs.
2. /LF-AMap/home/getshop?pid={pid}: returns store list for a given mainland province.
3. /LF-AMap/home/GetShopAbroad?region={region}: returns store list for HK, Macao, and overseas regions.

Output: data/processed/lukfook_stores/store_counts.parquet
    columns: date, region, store_count
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.parse
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from store_scraper_common import append_snapshot, fetch_url  # noqa: E402

MAINLAND_PROVINCES_URL = "https://www1.lukfook.com.hk/LF-AMap/home/getprovince"
MAINLAND_SHOPS_URL = "https://www1.lukfook.com.hk/LF-AMap/home/getshop"
ABROAD_SHOPS_URL = "https://www1.lukfook.com.hk/LF-AMap/home/GetShopAbroad"

ABROAD_REGIONS = [
    "香港特別行政區",
    "澳門特別行政區",
    "Malaysia",
    "Singapore",
    "Cambodia",
    "The Philippines",
    "Thailand",
    "Vietnam",
    "Laos",
    "The United States",
    "Canada",
    "Australia",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}


def _make_request(url: str) -> bytes | None:
    """Make an HTTP GET request with retries (GitHub Actions' network path to
    this site has shown occasional per-request read timeouts across the ~43
    sequential calls this scraper makes; a couple of retries recovers most
    of them rather than losing that region's stores for the day)."""
    return fetch_url(url, headers=HEADERS, timeout=30, attempts=3, backoff_seconds=2.0)


def _fetch_all_stores() -> list[dict]:
    """Fetch all stores (Mainland China + HK/Macao/Overseas) from Lukfook internal APIs."""
    all_stores: list[dict] = []
    seen_ids: set[int] = set()

    # 1. Fetch Mainland China provinces
    try:
        raw_prov = _make_request(MAINLAND_PROVINCES_URL)
        provinces = json.loads(raw_prov.decode("utf-8", errors="ignore"))
    except Exception as err:
        print(f"  Error fetching province list: {err}")
        provinces = []

    # 2. Fetch stores for each Mainland province
    for p in provinces:
        pid = p.get("ID")
        pname = p.get("Name_CN", f"Province_{pid}")
        if not pid:
            continue
        url = f"{MAINLAND_SHOPS_URL}?pid={pid}&keyword="
        try:
            raw_shops = _make_request(url)
            shops = json.loads(raw_shops.decode("utf-8", errors="ignore"))
            if isinstance(shops, list):
                for s in shops:
                    sid = s.get("ID")
                    if sid and sid not in seen_ids:
                        seen_ids.add(sid)
                        s["_region_group"] = pname
                        all_stores.append(s)
        except Exception as err:
            print(f"  Error fetching stores for mainland province {pname}: {err}")
        time.sleep(0.1)

    # 3. Fetch stores for HK, Macao, and Overseas regions
    for r in ABROAD_REGIONS:
        url = f"{ABROAD_SHOPS_URL}?region={urllib.parse.quote(r)}&keyword="
        try:
            raw_shops = _make_request(url)
            shops = json.loads(raw_shops.decode("utf-8", errors="ignore"))
            if isinstance(shops, list):
                for s in shops:
                    sid = s.get("ID")
                    if sid and sid not in seen_ids:
                        seen_ids.add(sid)
                        region_group = s.get("P_CN") or s.get("P") or r
                        s["_region_group"] = region_group.strip()
                        all_stores.append(s)
        except Exception as err:
            print(f"  Error fetching stores for abroad region {r}: {err}")
        time.sleep(0.1)

    return all_stores


def collect_counts(snapshot_date: str) -> pd.DataFrame:
    """Scrape and return store counts grouped by region."""
    stores = _fetch_all_stores()
    if not stores:
        print("  Luk Fook: Could not extract store data from APIs.")
        return pd.DataFrame()

    by_region: dict[str, int] = {}
    for s in stores:
        region = s.get("_region_group") or s.get("P_CN") or "Unknown"
        by_region[region] = by_region.get(region, 0) + 1

    rows = [
        {"date": snapshot_date, "region": r, "store_count": c}
        for r, c in sorted(by_region.items(), key=lambda x: -x[1])
    ]
    rows.append({"date": snapshot_date, "region": "TOTAL", "store_count": len(stores)})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Luk Fook store counts.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    out_path = Path(args.data_dir) / "processed" / "lukfook_stores" / "store_counts.parquet"

    print(f"Luk Fook store-count snapshot for {args.date}")
    print("=" * 50)

    df = collect_counts(args.date)
    if not df.empty:
        total = int(df[df["region"] == "TOTAL"]["store_count"].iloc[0])
        n_regions = len(df) - 1
        print(f"Total stores: {total} across {n_regions} regions")
        print("Top 5 regions:")
        for _, row in df[df["region"] != "TOTAL"].head(5).iterrows():
            print(f"  {row['region']}: {row['store_count']}")
    else:
        print("No store data extracted.")

    combined = append_snapshot(df, out_path)
    print(f"Wrote {out_path} ({len(combined)} rows)")


if __name__ == "__main__":
    main()
