"""Weekly store-count scraper for Bossini (堡狮龙, 00592.HK).

Scrapes store locations from Bossini's shop address page:
https://www.bossini.com/pages/shop-address?locale=zh-hant

Output: data/processed/bossini_stores/store_counts.parquet
    columns: date, region, store_count
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import ssl
import urllib.request
from pathlib import Path

import pandas as pd

SHOP_ADDRESS_URL = "https://www.bossini.com/pages/shop-address?locale=zh-hant"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-HK,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _fetch_stores() -> list[dict]:
    """Fetch and parse all Bossini stores from the shop-address page."""
    ctx = ssl._create_unverified_context()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    req = urllib.request.Request(SHOP_ADDRESS_URL, headers=HEADERS)

    try:
        with opener.open(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        print(f"  Error fetching Bossini shop page: {exc}")
        return []

    # Clean text conversion
    text = re.sub(r'<br\s*/?>', '\n', html, flags=re.I)
    text = re.sub(r'</?(p|div|li|tr|td|h1|h2|h3|h4|h5|h6)[^>]*>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    stores: list[dict] = []
    seen: set[str] = set()

    for i, line in enumerate(lines):
        if any(kw in line for kw in ["電話：", "電話 :", "(852)", "(853)"]):
            phone = line
            addr = lines[i - 1] if i > 0 else ""
            name = lines[i - 2] if i > 1 else ""
            
            # Simple region inference from address/name
            region = "香港"
            if "澳門" in name or "澳門" in addr:
                region = "澳門"
            elif "九龍" in addr or "九龍" in name:
                region = "九龍"
            elif "新界" in addr or "新界" in name:
                region = "新界"
            elif "香港" in addr or "香港" in name:
                region = "香港島"

            key = f"{name}_{phone}"
            if key not in seen:
                seen.add(key)
                stores.append({
                    "name": name,
                    "address": addr,
                    "phone": phone,
                    "region": region,
                })

    return stores


def collect_counts(snapshot_date: str) -> pd.DataFrame:
    """Scrape and return store counts grouped by region."""
    stores = _fetch_stores()
    if not stores:
        print("  Bossini: Could not extract store data from HTML.")
        return pd.DataFrame()

    by_region: dict[str, int] = {}
    for s in stores:
        region = s.get("region", "Unknown")
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
    parser = argparse.ArgumentParser(description="Scrape Bossini store counts.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    out_path = Path(args.data_dir) / "processed" / "bossini_stores" / "store_counts.parquet"

    print(f"Bossini store-count snapshot for {args.date}")
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
