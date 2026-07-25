"""Weekly store-count scraper for Fairwood (大快活, 00052.HK).

Fairwood's website is built with Next.js. The store locator page at
/en/stores embeds the complete store list in its __NEXT_DATA__ script tag
under pageProps.data.stores.

Output: data/processed/fairwood_stores/store_counts.parquet
    columns: date, category, store_count

Run:
    python scripts/scrape_fairwood_stores.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from store_scraper_common import append_snapshot, fetch_url  # noqa: E402

STORES_URL = "https://www.fairwood.com.hk/en/stores"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _fetch_stores() -> list[dict]:
    """Fetch all Fairwood stores from the Next.js __NEXT_DATA__ blob."""
    body = fetch_url(STORES_URL, headers=HEADERS, timeout=30)
    if body is None:
        return []
    html = body.decode("utf-8")

    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if not match:
        print("  Fairwood: could not find __NEXT_DATA__ in stores page.")
        return []

    data = json.loads(match.group(1))
    return data.get("props", {}).get("pageProps", {}).get("data", {}).get("stores", [])


def collect_counts(snapshot_date: str) -> pd.DataFrame:
    """Group stores by category (HK island / Kowloon / New Territories) and count."""
    stores = _fetch_stores()
    if not stores:
        return pd.DataFrame()

    by_category: dict[str, int] = {}
    for s in stores:
        cat = s.get("category", "Unknown").replace("_", " ").title()
        by_category[cat] = by_category.get(cat, 0) + 1

    rows = [
        {"date": snapshot_date, "category": cat, "store_count": cnt}
        for cat, cnt in sorted(by_category.items(), key=lambda x: -x[1])
    ]
    rows.append({
        "date": snapshot_date,
        "category": "TOTAL",
        "store_count": len(stores),
    })
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Fairwood store counts.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    out_path = Path(args.data_dir) / "processed" / "fairwood_stores" / "store_counts.parquet"

    print(f"Fairwood store-count snapshot for {args.date}")
    print("=" * 50)

    df = collect_counts(args.date)
    if df.empty:
        print("  Fairwood: could not extract store data.")
    else:
        total = int(df[df["category"] == "TOTAL"]["store_count"].iloc[0])
        print(f"Total stores: {total}")
        for _, row in df[df["category"] != "TOTAL"].iterrows():
            print(f"  {row['category']}: {row['store_count']}")

    combined = append_snapshot(df, out_path, key_column="category")
    if combined is not None and not combined.empty:
        print(f"Wrote {out_path} ({len(combined)} rows, {combined['date'].nunique()} snapshots)")
    else:
        print(f"No snapshot written to {out_path} (no prior history, no new data).")


if __name__ == "__main__":
    main()
