"""Weekly store-count scraper for Chow Sang Sang (周生生, 00116.HK).

Uses the official store locator PHP API which returns all store locations
by region. Currently has data for HK (744 stores) and Taiwan (38 stores).

Output: data/processed/chowsangsang_stores/store_counts.parquet
    columns: date, region, store_count

Run:
    python scripts/scrape_chowsangsang_stores.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.request
from pathlib import Path

import pandas as pd

STORE_API_URL = "https://www.chowsangsang.com/script/api/css/getStoreLocator.php?region={region}&lang=zh_HK"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _fetch_stores_for_region(region: str) -> list[dict]:
    """Fetch stores for a single region code."""
    url = STORE_API_URL.format(region=region)
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("result", [])
    except Exception as exc:
        print(f"  Region {region}: {exc}")
        return []


def collect_counts(snapshot_date: str) -> pd.DataFrame:
    # Known active regions
    regions = {
        "HK": "Hong Kong",
        "TW": "Taiwan",
    }
    # Also try others silently
    for extra in ["CN", "MAC", "SG", "MY"]:
        try:
            stores = _fetch_stores_for_region(extra)
            if stores:
                regions[extra] = extra
        except Exception:
            pass

    all_stores: list[dict] = []
    region_counts: dict[str, int] = {}

    for code, name in regions.items():
        stores = _fetch_stores_for_region(code)
        if stores:
            region_counts[name] = len(stores)
            all_stores.extend(stores)

    rows = [
        {"date": snapshot_date, "region": r, "store_count": c}
        for r, c in sorted(region_counts.items(), key=lambda x: -x[1])
    ]
    rows.append({"date": snapshot_date, "region": "TOTAL", "store_count": len(all_stores)})
    return pd.DataFrame(rows)


def append_snapshot(df: pd.DataFrame, out_path: Path) -> pd.DataFrame:
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
    parser = argparse.ArgumentParser(description="Scrape Chow Sang Sang store counts.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    out_path = Path(args.data_dir) / "processed" / "chowsangsang_stores" / "store_counts.parquet"

    print(f"Chow Sang Sang store-count snapshot for {args.date}")
    print("=" * 50)

    df = collect_counts(args.date)
    total_row = df[df["region"] == "TOTAL"].iloc[0] if not df.empty else {}
    total = int(total_row.get("store_count", 0))

    print(f"Total stores: {total}")
    for _, row in df[df["region"] != "TOTAL"].iterrows():
        print(f"  {row['region']}: {row['store_count']}")

    combined = append_snapshot(df, out_path)
    print(f"Wrote {out_path} ({len(combined)} rows, {combined['date'].nunique()} snapshots)")


if __name__ == "__main__":
    main()
