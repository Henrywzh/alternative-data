"""Weekly store-count scraper for Giordano (佐丹奴, 00709.HK).

Queries Giordano's REST WCF API:
https://giordanoappsite.giordano.com/SVC/AppsFunc.svc/rest/GetShopsMap?market={market}

Active markets covered:
HK (Hong Kong & Macau), TW (Taiwan), SG (Singapore), MY (Malaysia),
TH (Thailand), ID (Indonesia), PH (Philippines), VN (Vietnam), AU (Australia), GB (UK/Global).

Output: data/processed/giordano_stores/store_counts.parquet
    columns: date, region, store_count
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import ssl
import time
import urllib.request
from pathlib import Path

import pandas as pd

API_ENDPOINT = "https://giordanoappsite.giordano.com/SVC/AppsFunc.svc/rest/GetShopsMap"

MARKETS = {
    "HK": "Hong Kong & Macau",
    "TW": "Taiwan",
    "TH": "Thailand",
    "ID": "Indonesia",
    "PH": "Philippines",
    "MY": "Malaysia",
    "VN": "Vietnam",
    "SG": "Singapore",
    "GB": "United Kingdom",
    "AU": "Australia",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _fetch_market_stores(market_code: str) -> list[dict]:
    """Fetch stores for a specific market code from the WCF REST API."""
    url = f"{API_ENDPOINT}?shopID=&style=&market={market_code}&langid=EN&longitude=0&latitude=0"
    ctx = ssl._create_unverified_context()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    req = urllib.request.Request(url, headers=HEADERS)

    try:
        with opener.open(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(content)
            return data.get("GetShopsMapResult", [])
    except Exception as exc:
        print(f"  Error fetching market '{market_code}': {exc}")
        return []


def _fetch_all_stores() -> list[dict]:
    """Fetch all stores across all active Giordano markets."""
    all_stores: list[dict] = []
    seen_ids: set[str] = set()

    for code, market_name in MARKETS.items():
        shops = _fetch_market_stores(code)
        for s in shops:
            sid = s.get("ShopID") or s.get("Name")
            if sid and sid not in seen_ids:
                seen_ids.add(sid)
                s["_market_name"] = market_name
                all_stores.append(s)
        time.sleep(0.1)

    return all_stores


def collect_counts(snapshot_date: str) -> pd.DataFrame:
    """Scrape and return store counts grouped by market region."""
    stores = _fetch_all_stores()
    if not stores:
        print("  Giordano: Could not extract store data from API.")
        return pd.DataFrame()

    by_region: dict[str, int] = {}
    for s in stores:
        region = s.get("_market_name", "Unknown")
        by_region[region] = by_region.get(region, 0) + 1

    rows = [
        {"date": snapshot_date, "region": r, "store_count": c}
        for r, c in sorted(by_region.items(), key=lambda x: -x[1])
    ]
    rows.append({"date": snapshot_date, "region": "TOTAL", "store_count": len(stores)})
    return pd.DataFrame(rows)


def append_snapshot(df: pd.DataFrame, out_path: Path) -> pd.DataFrame:
    """Append snapshot to existing parquet file, deduplicated on (date, region)."""
    existing = pd.read_parquet(out_path) if out_path.exists() else None
    if df.empty:
        return existing if existing is not None else df
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
    parser = argparse.ArgumentParser(description="Scrape Giordano store counts.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    out_path = Path(args.data_dir) / "processed" / "giordano_stores" / "store_counts.parquet"

    print(f"Giordano store-count snapshot for {args.date}")
    print("=" * 50)

    df = collect_counts(args.date)
    if not df.empty:
        total = int(df[df["region"] == "TOTAL"]["store_count"].iloc[0])
        n_regions = len(df) - 1
        print(f"Total stores: {total} across {n_regions} markets")
        print("Top 5 markets:")
        for _, row in df[df["region"] != "TOTAL"].head(5).iterrows():
            print(f"  {row['region']}: {row['store_count']}")
    else:
        print("No store data extracted.")

    combined = append_snapshot(df, out_path)
    print(f"Wrote {out_path} ({len(combined)} rows)")


if __name__ == "__main__":
    main()
