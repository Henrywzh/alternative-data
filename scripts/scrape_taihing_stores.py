"""Weekly store-count scraper for Tai Hing Group (太興集團, 06811.HK).

Tai Hing Group operates ~30 restaurant sub-brands (Tai Hing, Men Wah Bing
Teng, TeaWood, etc.), each with its own branch-locator page:
https://www.taihing.com/?route=brands-detail&id={brand_id}&lang=3

Each branch is one `<li class='location-N'>` block containing a district
name (`<h4>`) and two contact rows (phone, then address) tagged by icon
(`icon-tel.png` / `icon-location.png`). An earlier version of this script
flattened all `<p class="purple">` tags (phone AND address, alternating)
into one page-wide list and zipped it index-for-index against a separate
page-wide district list -- since there are 2 `<p>` tags per branch but only
1 district `<h4>`, this both double-counted every branch (phone numbers
counted as extra "addresses") and misaligned most district/address pairs
across branches. This version parses each branch's own `<li>` block so the
district, phone, and address stay scoped to the same branch.

Output: data/processed/taihing_stores/store_counts.parquet
    columns: date, region, store_count   (region = sub-brand name)
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

BRAND_URL = "https://www.taihing.com/?route=brands-detail&id={brand_id}&lang=3"

# Known sub-brand IDs -> display name. IDs are probed up to MAX_BRAND_ID so a
# newly added brand still gets picked up (as "Brand #N") even before this
# dict is updated.
BRAND_NAMES = {
    1: "Tai Hing (太興)",
    2: "TeaWood (茶木)",
    3: "Trusty Congee King (靠得住)",
    4: "Phở Lệ (錦麗)",
    5: "Men Wah Bing Teng (敏華冰廳)",
    6: "Torshin",
    7: "Dao Cheng",
    8: "Rice Rule",
    10: "Boulangerie Poppins",
    11: "King Fong Bing Teng (瓊芳冰廳)",
    12: "Asam Chicken Rice (亞參雞飯)",
    13: "Corner",
    14: "Tse Noodle",
    15: "Fisherman's Wharf",
    16: "Pot Luck",
    17: "Dumpling City (餃子県)",
    20: "Grandma's Noodle",
    21: "Hotpot",
    22: "Chuan Town",
    23: "Dim Sum Bar",
    24: "Noodle Bar",
    25: "Grill",
    26: "Tommy Yummy",
    28: "Tori Yoichi (鳥宵)",
    29: "Sing Kee Seafood Restaurant (勝記海鮮酒家)",
    30: "Szechuan Restaurant",
    32: "Bakery",
    33: "ManShan Taipei (滿山台北)",
    34: "Bashi Ramen (八市拉麵)",
    35: "On Kim Pot Rice (安金煲仔飯)",
    36: "TOKENYO Korean BBQ Cuisine",
    37: "Hing Gor Beef Brisket (興哥牛腩)",
}
MAX_BRAND_ID = 45

_BRANCH_BLOCK_RE = re.compile(
    r"<li class='location-\d+'>.*?</li>\s*(?=<li class='location-|</ul>)", re.DOTALL
)
_DISTRICT_RE = re.compile(r"<h4[^>]*>(.*?)</h4>", re.DOTALL)
_CONTACT_RE = re.compile(r'icon-(tel|location)\.png.*?<p class="purple">(.*?)</p>', re.DOTALL)


def _clean(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _fetch_brand_branch_count(brand_id: int) -> int | None:
    """Return the branch count for one brand, or None if the fetch failed."""
    url = BRAND_URL.format(brand_id=brand_id)
    body = fetch_url(url, timeout=15)
    if body is None:
        return None
    html = body.decode("utf-8", errors="ignore")
    if "branch-location-section" not in html:
        return 0

    count = 0
    for block in _BRANCH_BLOCK_RE.findall(html):
        district_m = _DISTRICT_RE.search(block)
        if district_m is None:
            continue
        address = next(
            (text for kind, text in _CONTACT_RE.findall(block) if kind == "location"),
            None,
        )
        if address and _clean(address):
            count += 1
    return count


def collect_counts(snapshot_date: str) -> pd.DataFrame:
    """Probe all brand IDs and return a long-format branch-count frame for one date."""
    rows: list[dict] = []
    for brand_id in range(1, MAX_BRAND_ID + 1):
        count = _fetch_brand_branch_count(brand_id)
        if count is None:
            print(f"  Brand #{brand_id}: fetch failed, skipping")
            continue
        if count == 0:
            continue
        brand_name = BRAND_NAMES.get(brand_id, f"Brand #{brand_id}")
        print(f"  {brand_name:35s} (ID {brand_id:2d}): {count:3d} branches")
        rows.append({"date": snapshot_date, "region": brand_name, "store_count": count})

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
    parser = argparse.ArgumentParser(description="Scrape Tai Hing Group branch counts.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    out_path = Path(args.data_dir) / "processed" / "taihing_stores" / "store_counts.parquet"

    print(f"Tai Hing Group branch-count snapshot for {args.date}")
    print("=" * 60)

    df = collect_counts(args.date)
    if not df.empty:
        total = int(df[df["region"] == "TOTAL"]["store_count"].iloc[0])
        n_brands = len(df) - 1
        print(f"Total branches: {total} across {n_brands} sub-brands")
    else:
        print("No branch data extracted.")

    combined = append_snapshot(df, out_path)
    print(f"Wrote {out_path} ({len(combined)} rows)")


if __name__ == "__main__":
    main()
