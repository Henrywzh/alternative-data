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
import urllib.request
from pathlib import Path

import pandas as pd

STORES_URL = "https://www.fairwood.com.hk/en/stores"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _fetch_stores() -> list[dict]:
    """Fetch all Fairwood stores from the Next.js __NEXT_DATA__ blob."""
    req = urllib.request.Request(STORES_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8")

    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if not match:
        raise RuntimeError("Could not find __NEXT_DATA__ in Fairwood stores page")

    data = json.loads(match.group(1))
    stores = data.get("props", {}).get("pageProps", {}).get("data", {}).get("stores", [])
    if not stores:
        raise RuntimeError("No stores found in Fairwood __NEXT_DATA__")
    return stores


def collect_counts(snapshot_date: str) -> pd.DataFrame:
    """Group stores by category (HK island / Kowloon / New Territories) and count."""
    stores = _fetch_stores()

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


def append_snapshot(df: pd.DataFrame, out_path: Path) -> pd.DataFrame:
    existing = pd.read_parquet(out_path) if out_path.exists() else None
    combined = df if existing is None else pd.concat([existing, df], ignore_index=True)
    combined = (
        combined.drop_duplicates(subset=["date", "category"], keep="last")
        .sort_values(["date", "category"])
        .reset_index(drop=True)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(out_path, index=False)
    return combined


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Fairwood store counts.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    out_path = Path(args.data_dir) / "processed" / "fairwood_stores" / "store_counts.parquet"

    print(f"Fairwood store-count snapshot for {args.date}")
    print("=" * 50)

    df = collect_counts(args.date)
    total = int(df[df["category"] == "TOTAL"]["store_count"].iloc[0])

    print(f"Total stores: {total}")
    for _, row in df[df["category"] != "TOTAL"].iterrows():
        print(f"  {row['category']}: {row['store_count']}")

    combined = append_snapshot(df, out_path)
    print(f"Wrote {out_path} ({len(combined)} rows, {combined['date'].nunique()} snapshots)")


if __name__ == "__main__":
    main()
