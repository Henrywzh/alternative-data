from __future__ import annotations

from pathlib import Path

import pandas as pd

from dashboard import data as dashboard_data

from .loaders import resolve_base_dir
from .marts import MART_REGISTRY, mart_paths, read_mart


def _mart_date_range(frame: pd.DataFrame, date_column: str | None) -> tuple[str | None, str | None]:
    if frame.empty or not date_column or date_column not in frame.columns:
        return None, None
    dates = pd.to_datetime(frame[date_column], errors="coerce").dropna()
    if dates.empty:
        return None, None
    return dates.min().strftime("%Y-%m-%d"), dates.max().strftime("%Y-%m-%d")


def catalog(base_dir: str | Path | None = None) -> pd.DataFrame:
    base = resolve_base_dir(base_dir)
    results = dashboard_data.load_all_datasets(base_dir=base)
    freshness = dashboard_data.load_latest_manifest(base_dir=base, datasets=results)

    rows: list[dict[str, object]] = []
    for dataset_id, result in results.items():
        rows.append(
            {
                "dataset_kind": "source",
                "dataset_id": dataset_id,
                "label": result.label,
                "domain": result.domain,
                "source_path": str(result.source_path) if result.source_path else None,
                "source_format": result.source_format,
                "row_count": result.row_count,
                "primary_date_column": result.primary_date_column,
                "metric_column": result.metric_column,
                "first_date": result.first_date,
                "latest_date": result.latest_date,
                "latest_scraped_at": result.latest_scraped_at,
                "duplicate_rows": result.duplicate_rows,
                "missing_columns": "|".join(result.missing_columns) if result.missing_columns else "",
                "latest_manifest_run_id": freshness.latest_run_id,
                "latest_manifest_scraped_at": freshness.latest_manifest_scraped_at,
            }
        )

    for mart_name, metadata in MART_REGISTRY.items():
        csv_path, parquet_path = mart_paths(mart_name, base_dir=base)
        existing_path = parquet_path if parquet_path.exists() else csv_path if csv_path.exists() else None
        if existing_path is None:
            continue
        frame = read_mart(mart_name, base_dir=base)
        first_date, latest_date = _mart_date_range(frame, metadata.get("primary_date_column"))
        rows.append(
            {
                "dataset_kind": "mart",
                "dataset_id": mart_name,
                "label": metadata["label"],
                "domain": metadata["domain"],
                "source_path": str(existing_path),
                "source_format": existing_path.suffix.lstrip("."),
                "row_count": len(frame),
                "primary_date_column": metadata.get("primary_date_column"),
                "metric_column": metadata.get("metric_column"),
                "first_date": first_date,
                "latest_date": latest_date,
                "latest_scraped_at": None,
                "duplicate_rows": int(frame.duplicated().sum()) if not frame.empty else 0,
                "missing_columns": "",
                "latest_manifest_run_id": freshness.latest_run_id,
                "latest_manifest_scraped_at": freshness.latest_manifest_scraped_at,
            }
        )

    catalog_df = pd.DataFrame(rows)
    if catalog_df.empty:
        return catalog_df
    return catalog_df.sort_values(["dataset_kind", "domain", "dataset_id"], ignore_index=True)
