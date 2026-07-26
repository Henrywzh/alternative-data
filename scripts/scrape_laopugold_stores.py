"""Weekly store-count scraper for Lao Pu Gold (老铺黄金, 06181.HK).

Counts boutique stores per city from Lao Pu Gold's official store-listing
pages (one page per city, selected via a `catid` query parameter):
https://www.lphj.com/index.php?m=content&c=index&a=lists&catid={catid}

Each listing page only exposes a store photo per boutique (no name/address/
coordinates are present in the markup), so the granularity here is a
per-city store count -- matching the other scrapers in this directory, not
individual store locations.

Output: data/processed/laopugold_stores/store_counts.parquet
    columns: date, region, store_count
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from store_scraper_common import append_snapshot, fetch_url  # noqa: E402

BASE_URL = "http://www.lphj.com/index.php?m=content&c=index&a=lists&catid={catid}"

# city_cn (used as the region label, consistent with the Chinese-region
# convention used elsewhere in this directory) -> catid on lphj.com.
CITIES = {
    "北京": 12,
    "上海": 59,
    "天津": 72,
    "广州": 68,
    "深圳": 14,
    "杭州": 15,
    "南京": 16,
    "成都": 53,
    "西安": 17,
    "郑州": 75,
    "沈阳": 18,
    "武汉": 19,
    "厦门": 20,
    "香港": 70,
    "澳门": 55,
    "新加坡": 77,
}

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _count_stores_for_city(catid: int) -> int | None:
    """Return the store count for one city, or None if the fetch failed."""
    url = BASE_URL.format(catid=catid)
    body = fetch_url(url, headers=HEADERS, timeout=15)
    if body is None:
        return None
    html = body.decode("utf-8", errors="ignore")
    m = re.search(r'<ul class="shop-list-new">(.*?)</ul>', html, re.DOTALL | re.I)
    if not m:
        return 0
    return len(re.findall(r"<img[^>]+src=", m.group(1)))


def collect_counts(snapshot_date: str) -> pd.DataFrame:
    """Scrape all cities and return a long-format counts frame for one date."""
    rows: list[dict] = []
    for city_cn, catid in CITIES.items():
        count = _count_stores_for_city(catid)
        if count is None:
            print(f"  {city_cn}: fetch failed, skipping")
            continue
        print(f"  {city_cn}: {count} boutique stores")
        rows.append({"date": snapshot_date, "region": city_cn, "store_count": count})

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    total = int(df["store_count"].sum())
    df = pd.concat(
        [df, pd.DataFrame([{"date": snapshot_date, "region": "TOTAL", "store_count": total}])],
        ignore_index=True,
    )
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Lao Pu Gold store counts.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    out_path = Path(args.data_dir) / "processed" / "laopugold_stores" / "store_counts.parquet"

    print(f"Lao Pu Gold store-count snapshot for {args.date}")
    print("=" * 50)

    df = collect_counts(args.date)
    if not df.empty:
        total = int(df[df["region"] == "TOTAL"]["store_count"].iloc[0])
        n_regions = len(df) - 1
        print(f"Total stores: {total} across {n_regions} cities")
    else:
        print("No store data extracted.")

    combined = append_snapshot(df, out_path)
    print(f"Wrote {out_path} ({len(combined)} rows)")


if __name__ == "__main__":
    main()
