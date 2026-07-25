"""Weekly store-count scraper for Café de Coral (大家乐, 00341.HK).

Café de Coral's official website (cafedecoral.com) is behind Cloudflare WAF.
However, its e-commerce platform at eatcdc.com hosts a branch address page
that lists all Café de Coral restaurant locations with phone numbers and
operating hours.

This scraper parses the HTML page to extract branch information.

Output: data/processed/cafedecoral_stores/store_counts.parquet
    columns: date, area, store_count

Run:
    python scripts/scrape_cafedecoral_stores.py
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

BRANCH_URL = (
    "https://www.eatcdc.com/tch/main/terms.jsp"
    "?id=B2D0P2M0R0Y891E8L1D18188M4G0A802"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _fetch_html() -> str:
    body = fetch_url(BRANCH_URL, headers=HEADERS, timeout=30)
    if body is None:
        return ""
    return body.decode("utf-8", errors="ignore")


def _extract_branches(html: str) -> list[dict]:
    """Parse branch data from the HTML page."""
    # Remove script and style content
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '\n', text)
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    branches = []
    current_area = None
    i = 0

    while i < len(lines):
        line = lines[i]

        # Area heading
        if line in ['香港', '九龍', '新界']:
            current_area = line
            i += 1
            continue

        # Look for branch name (line with address-like content)
        if current_area and any(kw in line for kw in ['號', '舖', '廣場', '中心', '大廈', '商場']):
            name = line
            addr = ''
            phone = ''
            hours = ''

            # Check next lines for address, phone, hours
            j = i + 1
            while j < len(lines) and j < i + 8:
                l = lines[j]
                if not addr and len(l) > 10 and any(kw in l for kw in ['號', '舖', '廣場', '中心']):
                    addr = l
                elif '電話' in l:
                    phone = re.sub(r'電話[：:]?\s*', '', l)
                elif '營業時間' in l:
                    hours = re.sub(r'營業時間[：:]?\s*', '', l)
                elif not addr and l in ['香港', '九龍', '新界']:
                    break
                j += 1

            branches.append({
                'area': current_area,
                'name': name,
                'address': addr,
                'phone': phone,
                'hours': hours,
            })
            i = j
            continue

        i += 1

    return branches


def collect_counts(snapshot_date: str) -> pd.DataFrame:
    html = _fetch_html()
    branches = _extract_branches(html) if html else []
    if not branches:
        return pd.DataFrame()

    # Count by area
    by_area: dict[str, int] = {}
    for b in branches:
        area = b.get('area', 'Unknown')
        by_area[area] = by_area.get(area, 0) + 1

    rows = [
        {"date": snapshot_date, "area": a, "store_count": c}
        for a, c in sorted(by_area.items(), key=lambda x: -x[1])
    ]
    total = sum(by_area.values())
    if rows:
        rows.insert(0, {"date": snapshot_date, "area": "TOTAL", "store_count": total})
    else:
        rows = [{"date": snapshot_date, "area": "TOTAL", "store_count": total}]
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Café de Coral store counts.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    out_path = Path(args.data_dir) / "processed" / "cafedecoral_stores" / "store_counts.parquet"

    print(f"Café de Coral store-count snapshot for {args.date}")
    print("=" * 50)

    df = collect_counts(args.date)
    if not df.empty:
        total = int(df[df["area"] == "TOTAL"]["store_count"].iloc[0])
        print(f"Total branches: {total}")
        for _, row in df[df["area"] != "TOTAL"].iterrows():
            print(f"  {row['area']}: {row['store_count']}")
    else:
        print("  Café de Coral: could not extract branch data.")

    combined = append_snapshot(df, out_path, key_column="area")
    if combined is not None and not combined.empty:
        print(f"Wrote {out_path} ({len(combined)} rows)")
    else:
        print(f"No snapshot written to {out_path} (no prior history, no new data).")


if __name__ == "__main__":
    main()
