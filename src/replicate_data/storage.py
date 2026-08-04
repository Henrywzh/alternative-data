import json
from pathlib import Path
from typing import Dict, Any
import pandas as pd

# Columns that uniquely identify a row within each normalized dataset, used to
# upsert incoming rows against previously stored history rather than
# overwriting it. Each scrape only reflects the site's current state, so
# history must be preserved across runs by merging on these keys, keeping
# the newest row per key.
NATURAL_KEYS: dict[str, list[str]] = {
    "replicate_model_catalog": ["snapshot_date", "slug"],
    "replicate_collections_summary": ["snapshot_date", "collection_slug"],
}

def save_raw_snapshot(base_dir: Path, data: Dict[str, Any], date_str: str, filename: str) -> Path:
    """Save raw JSON payload to data/raw/replicate/{date}/."""
    out_dir = base_dir / "data" / "raw" / "replicate" / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"[replicate_data] Raw snapshot saved: {out_path}")
    return out_path

def _read_existing(csv_path: Path, parquet_path: Path) -> pd.DataFrame:
    if parquet_path.exists():
        try:
            return pd.read_parquet(parquet_path)
        except Exception as e:
            print(f"[replicate_data] Notice: Could not read existing parquet for {parquet_path.name}: {e}")
    if csv_path.exists():
        return pd.read_csv(csv_path)
    return pd.DataFrame()

def save_normalized_dataset(base_dir: Path, df: pd.DataFrame, filename_base: str) -> Path:
    """Upsert a normalized DataFrame into CSV and Parquet under data/normalized/replicate/.

    Merges incoming rows with whatever is already stored, keyed by
    NATURAL_KEYS[filename_base], so each run adds/refreshes its own snapshot
    without discarding history accumulated by previous runs.
    """
    out_dir = base_dir / "data" / "normalized" / "replicate"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{filename_base}.csv"
    parquet_path = out_dir / f"{filename_base}.parquet"

    keys = NATURAL_KEYS.get(filename_base)
    if keys is None:
        print(f"[replicate_data] Warning: no NATURAL_KEYS entry for '{filename_base}'; overwriting without merging history.")
        merged = df
    elif df.empty:
        # Nothing new this run -- keep whatever history is already stored
        # untouched rather than wiping it out.
        merged = _read_existing(csv_path, parquet_path)
    else:
        existing = _read_existing(csv_path, parquet_path)
        missing_key_columns = [k for k in keys if k not in df.columns]
        if missing_key_columns:
            raise ValueError(f"Dataset '{filename_base}' incoming rows are missing natural key columns: {missing_key_columns}")
        merged = pd.concat([existing, df], ignore_index=True) if not existing.empty else df
        merged = merged.drop_duplicates(subset=keys, keep="last").sort_values(by=keys, na_position="last").reset_index(drop=True)

    merged.to_csv(csv_path, index=False)
    print(f"[replicate_data] Saved CSV: {csv_path} ({len(merged)} rows)")

    try:
        merged.to_parquet(parquet_path, index=False)
        print(f"[replicate_data] Saved Parquet: {parquet_path}")
    except Exception as e:
        print(f"[replicate_data] Note: Parquet export skipped ({e})")

    return csv_path
