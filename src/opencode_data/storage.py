from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

# Columns that uniquely identify a row within each normalized dataset, used to
# upsert incoming rows against previously stored history rather than
# overwriting it. Each scrape only reflects the site's current
# (likely trailing-window) payload, so history must be preserved across runs
# by merging on these keys, keeping the newest row per key.
NATURAL_KEYS: dict[str, list[str]] = {
    # date_occurrence disambiguates coarse timeframes (e.g. "ALL") where the
    # site legitimately emits multiple distinct entries under the same
    # "date" label (e.g. two different "APR" totals) -- see extract.py.
    "opencode_market_share": ["timeframe", "usage_date", "date_occurrence", "author"],
    "opencode_usage_daily": ["user_tier", "timeframe", "usage_date", "date_occurrence", "model_slug"],
    "opencode_users_daily": ["user_tier", "timeframe", "usage_date", "date_occurrence", "model_slug"],
    "opencode_leaderboard": ["snapshot_date", "user_tier", "timeframe", "model_slug"],
    "opencode_country_usage": ["snapshot_date", "timeframe", "country_code"],
    "opencode_model_catalog": ["snapshot_date", "slug"],
    # variant/dataset/version (e.g. "no tools" vs "with tools", "max" vs
    # "medium", FrontierMath "Tier 1-3" vs "Tier 4") are real distinguishing
    # dimensions the site reports per benchmark row, not noise.
    "opencode_benchmarks": [
        "snapshot_date", "model_slug", "benchmark_name", "metric", "harness", "variant", "dataset", "version",
    ],
    "opencode_model_deepdives": ["snapshot_date", "model_slug"],
}


def save_raw_snapshot(base_dir: Path, name: str, data: Any, scraped_at: str) -> Path:
    """Save raw JSON payload to data/raw/opencode/{date}/{name}.json."""
    date_str = scraped_at.split("T", 1)[0]
    out_dir = base_dir / "data" / "raw" / "opencode" / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{name}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return out_file


def _read_existing(csv_path: Path, parquet_path: Path) -> pd.DataFrame:
    if parquet_path.exists():
        try:
            return pd.read_parquet(parquet_path)
        except Exception as e:
            print(f"Notice: Could not read existing parquet for {parquet_path.name}: {e}")
    if csv_path.exists():
        return pd.read_csv(csv_path)
    return pd.DataFrame()


def save_normalized_dataset(base_dir: Path, name: str, rows: list[dict[str, Any]]) -> tuple[Path | None, Path]:
    """Upsert normalized rows into data/normalized/opencode/{name}.csv and optional .parquet.

    Merges incoming rows with whatever is already stored, keyed by
    NATURAL_KEYS[name], so each run adds/refreshes its own rows without
    discarding history accumulated by previous runs. Datasets without a
    registered natural key fall back to a plain overwrite (should not
    normally happen -- add an entry to NATURAL_KEYS for new datasets).
    """
    out_dir = base_dir / "data" / "normalized" / "opencode"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{name}.csv"
    parquet_path = out_dir / f"{name}.parquet"

    incoming = pd.DataFrame(rows)
    keys = NATURAL_KEYS.get(name)
    if keys is None:
        print(f"Warning: no NATURAL_KEYS entry for '{name}'; overwriting without merging history.")
        merged = incoming
    elif incoming.empty:
        # Nothing new this run (e.g. no deepdives fetched) -- keep whatever
        # history is already stored untouched rather than wiping it out.
        merged = _read_existing(csv_path, parquet_path)
    else:
        existing = _read_existing(csv_path, parquet_path)
        missing_key_columns = [k for k in keys if k not in incoming.columns]
        if missing_key_columns:
            raise ValueError(f"Dataset '{name}' incoming rows are missing natural key columns: {missing_key_columns}")
        if existing.empty:
            merged = incoming
        else:
            merged = pd.concat([existing, incoming], ignore_index=True)
        if not merged.empty:
            merged = merged.drop_duplicates(subset=keys, keep="last").sort_values(by=keys, na_position="last").reset_index(drop=True)

    merged.to_csv(csv_path, index=False)

    parquet_saved = None
    try:
        merged.to_parquet(parquet_path, index=False)
        parquet_saved = parquet_path
    except Exception as e:
        print(f"Notice: Could not write parquet file for {name}: {e}")

    return parquet_saved, csv_path
