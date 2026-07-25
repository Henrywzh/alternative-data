#!/usr/bin/env python3
"""
百度迁徙 (Baidu Qianxi / Huiyan Migration) — Data Fetcher

Uses the undocumented but publicly-accessible JSONP API of
huiyan.baidu.com to retrieve daily population migration data
between Chinese cities.

API endpoints (all verified 2026-07-25):
  lastdate.jsonp                    → latest available date
  cityrank.jsonp?dt=country&id=0    → national city ranking (top 100)
  cityrank.jsonp?dt=city&id={code}  → city-specific origin/dest ranking
  routerank.jsonp?dt=city&id={code} → city-to-city route ranking

No authentication required. Rate-limit not formally documented,
suggest >=1s interval between requests.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "https://huiyan.baidu.com/migration"

DEFAULT_CITIES = [
    # 一线 / 重点城市 (key cities for economic monitoring)
    110000,  # 北京市
    310000,  # 上海市
    440100,  # 广州市
    440300,  # 深圳市
    440305,  # 深圳市(南山) – keep 440300, this is right
    330100,  # 杭州市
    320100,  # 南京市
    420100,  # 武汉市
    510100,  # 成都市
    500000,  # 重庆市
    440400,  # 珠海市
    441900,  # 东莞市
    440600,  # 佛山市
    350200,  # 厦门市
    370200,  # 青岛市
    210100,  # 沈阳市
    610100,  # 西安市
    430100,  # 长沙市
    410100,  # 郑州市
    120000,  # 天津市
]

# Output directory – relative to repo root
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "baidu_migration"


def last_date() -> str:
    """Return the latest data date as YYYYMMDD string."""
    resp = requests.get(f"{BASE_URL}/lastdate.jsonp", timeout=15)
    resp.raise_for_status()
    raw = resp.text
    obj = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    return obj["data"]["lastdate"]


def fetch_cityrank(
    dt: str = "country",
    city_id: int = 0,
    direction: str = "move_in",
    date: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch city-level migration ranking.

    dt        : "country" (national) or "city" (for a specific city)
    city_id   : 6-digit administrative code; ignored for dt=country
    direction : "move_in" or "move_out"
    date      : YYYYMMDD; defaults to latest
    """
    if date is None:
        date = last_date()

    params = {"dt": dt, "type": direction, "date": date}
    if dt == "city":
        params["id"] = city_id
    else:
        params["id"] = 0

    resp = requests.get(f"{BASE_URL}/cityrank.jsonp", params=params, timeout=15)
    resp.raise_for_status()
    raw = resp.text
    obj = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])

    if obj.get("errno") != 0:
        raise RuntimeError(f"API error: {obj.get('errmsg')} (params={params})")

    return obj["data"]["list"]


def fetch_routerank(
    city_id: int,
    direction: str = "move_in",
    date: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch city-to-city route ranking for a specific city.

    Note: this endpoint returns route rankings WITHOUT numeric values,
    only city name pairs ordered by popularity.
    """
    if date is None:
        date = last_date()

    params = {"dt": "city", "id": city_id, "type": direction, "date": date}
    resp = requests.get(f"{BASE_URL}/routerank.jsonp", params=params, timeout=15)
    resp.raise_for_status()
    raw = resp.text
    obj = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])

    if obj.get("errno") != 0:
        raise RuntimeError(f"API error: {obj.get('errmsg')} (params={params})")

    return obj["data"]["list"]


def run_national_snapshot(date: str | None = None) -> pd.DataFrame:
    """Fetch national city ranking (both move_in and move_out)."""
    if date is None:
        date = last_date()

    rows: list[dict] = []
    for direction in ("move_in", "move_out"):
        records = fetch_cityrank(dt="country", direction=direction, date=date)
        for r in records:
            rows.append(
                {
                    "date": date,
                    "city_name": r["city_name"],
                    "province_name": r["province_name"],
                    "direction": direction.replace("move_", ""),
                    "pct": r["value"],
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        time.sleep(0.5)

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["direction", "pct"], ascending=[True, False]).reset_index(drop=True)
    return df


def run_city_snapshot(
    city_ids: list[int],
    date: str | None = None,
) -> pd.DataFrame:
    """For each city, fetch its top origin/dest city rankings."""
    if date is None:
        date = last_date()

    rows: list[dict] = []
    for cid in city_ids:
        for direction in ("move_in", "move_out"):
            try:
                records = fetch_cityrank(dt="city", city_id=cid, direction=direction, date=date)
                for r in records:
                    rows.append(
                        {
                            "date": date,
                            "target_city_id": cid,
                            "city_name": r["city_name"],
                            "province_name": r["province_name"],
                            "direction": direction.replace("move_", ""),
                            "pct": r["value"],
                            "fetched_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                time.sleep(0.5)
            except Exception as e:
                print(f"  Warning: city {cid} {direction} failed: {e}", file=sys.stderr)

    return pd.DataFrame(rows)


def save(df: pd.DataFrame, name: str) -> Path:
    """Save DataFrame as parquet."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{name}.parquet"
    df.to_parquet(path, index=False)
    print(f"  Saved {len(df)} rows → {path}")
    return path


def append_history(existing: pd.DataFrame, new: pd.DataFrame, key_col: str = "date") -> pd.DataFrame:
    """Append new rows to existing dataframe, deduplicating on date."""
    if existing.empty:
        return new
    combined = pd.concat([existing, new], ignore_index=True)
    combined = combined.drop_duplicates(subset=[key_col] if key_col in combined.columns else None, keep="last")
    return combined.sort_values(key_col).reset_index(drop=True) if key_col in combined.columns else combined


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Baidu Qianxi (Migration) data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s                          # fetch national snapshot\n"
            "  %(prog)s --city                   # fetch per-city detail\n"
            "  %(prog)s --all                    # national + city detail\n"
            "  %(prog)s --date 20260701          # specific date\n"
            "  %(prog)s --date-latest            # latest available\n"
            "  %(prog)s --backfill 2024-01 2024-03  # monthly backfill range\n"
        ),
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Target date (YYYYMMDD). Default: latest available.",
    )
    parser.add_argument(
        "--date-latest",
        action="store_true",
        help="Force latest date (overrides --date).",
    )
    parser.add_argument(
        "--national",
        action="store_true",
        default=False,
        dest="national",
        help="Fetch national city ranking (default).",
    )
    parser.add_argument(
        "--city",
        action="store_true",
        dest="city_detail",
        help="Fetch per-city detail ranking.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_modes",
        help="Fetch both national + per-city.",
    )
    parser.add_argument(
        "--city-ids",
        nargs="+",
        type=int,
        default=None,
        help="Override city IDs for per-city fetch (space-separated).",
    )
    parser.add_argument(
        "--backfill",
        nargs=2,
        metavar=("START", "END"),
        default=None,
        help="Backfill months: YYYY-MM YYYY-MM. Fetches ~monthly snapshots.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for parquet files",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print extra details.",
    )

    args = parser.parse_args()
    global DATA_DIR
    DATA_DIR = args.output_dir if args.output_dir is not None else DATA_DIR

    # Resolve date
    if args.date_latest:
        target_date = last_date()
    elif args.date:
        target_date = args.date
    else:
        target_date = last_date()

    # Determine what to fetch
    do_national = args.national or args.all_modes or not (args.city_detail or args.all_modes)
    do_city = args.city_detail or args.all_modes

    print(f"Target date: {target_date}")

    # Backfill mode
    if args.backfill:
        start, end = args.backfill
        print(f"Backfill mode: {start} → {end}")
        # Generate monthly midpoints
        months = pd.date_range(start + "-01", end + "-01", freq="MS", tz="UTC")
        dates = [m.strftime("%Y%m") + "15" for m in months]  # ~mid-month
        # Always include latest date
        if target_date and target_date not in dates:
            dates.append(target_date)

        national_concat = []
        city_concat = []
        for i, d in enumerate(dates):
            print(f"  [{i+1}/{len(dates)}] Fetching {d}...")
            if do_national:
                try:
                    df_nat = run_national_snapshot(d)
                    national_concat.append(df_nat)
                except Exception as e:
                    print(f"    Failed: {e}", file=sys.stderr)
            if do_city:
                try:
                    cids = args.city_ids or DEFAULT_CITIES
                    df_city = run_city_snapshot(cids, d)
                    city_concat.append(df_city)
                except Exception as e:
                    print(f"    Failed: {e}", file=sys.stderr)
            time.sleep(1.0)

        if national_concat:
            df_nat_all = pd.concat(national_concat, ignore_index=True)
            save(df_nat_all, "national_history")
        if city_concat:
            df_city_all = pd.concat(city_concat, ignore_index=True)
            save(df_city_all, "city_history")
        return

    # Single-date mode
    if do_national:
        print("Fetching national city ranking...")
        df_nat = run_national_snapshot(target_date)
        if not df_nat.empty:
            save(df_nat, "national_latest")
        else:
            print("  (empty)", file=sys.stderr)

    if do_city:
        cids = args.city_ids or DEFAULT_CITIES
        print(f"Fetching per-city detail for {len(cids)} cities...")
        df_city = run_city_snapshot(cids, target_date)
        if not df_city.empty:
            save(df_city, "city_detail_latest")

    print("Done.")


if __name__ == "__main__":
    main()
