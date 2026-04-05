from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


DATASET_REGISTRY: dict[str, dict[str, object]] = {
    "top_models": {
        "label": "Top Models",
        "domain": "rankings",
        "natural_keys": ["week_start_date", "entity_id"],
        "primary_date_column": "week_start_date",
        "metric_column": "metric_value",
    },
    "market_share": {
        "label": "Market Share",
        "domain": "rankings",
        "natural_keys": ["week_start_date", "entity_id"],
        "primary_date_column": "week_start_date",
        "metric_column": "metric_value",
    },
    "categories_programming": {
        "label": "Programming",
        "domain": "rankings",
        "natural_keys": ["week_start_date", "category_slug", "entity_id"],
        "primary_date_column": "week_start_date",
        "metric_column": "metric_value",
    },
    "app_metadata_snapshots": {
        "label": "App Metadata",
        "domain": "apps",
        "natural_keys": ["app_id", "scrape_date"],
        "primary_date_column": "scrape_date",
        "metric_column": None,
    },
    "app_usage_daily": {
        "label": "App Usage Daily",
        "domain": "apps",
        "natural_keys": ["app_id", "usage_date", "model_permaslug"],
        "primary_date_column": "usage_date",
        "metric_column": "total_tokens",
    },
    "app_top_models_daily_snapshot": {
        "label": "App Top Models",
        "domain": "apps",
        "natural_keys": ["app_id", "snapshot_date", "model_permaslug"],
        "primary_date_column": "snapshot_date",
        "metric_column": "total_tokens",
    },
    "apps_global_ranking_snapshots": {
        "label": "Global App Rankings",
        "domain": "apps",
        "natural_keys": ["snapshot_date", "period", "rank"],
        "primary_date_column": "snapshot_date",
        "metric_column": "tokens",
    },
    "apps_trending_snapshots": {
        "label": "Trending Apps",
        "domain": "apps",
        "natural_keys": ["snapshot_date", "rank"],
        "primary_date_column": "snapshot_date",
        "metric_column": "growth_percent",
    },
}

DOMAIN_ORDER = {
    "rankings": [
        "top_models",
        "market_share",
        "categories_programming",
    ],
    "apps": [
        "app_metadata_snapshots",
        "app_usage_daily",
        "app_top_models_daily_snapshot",
        "apps_global_ranking_snapshots",
        "apps_trending_snapshots",
    ],
}

EXPECTED_COLUMNS = [
    "dataset_id",
    "source_url",
    "source_run_id",
    "scraped_at",
    "week_label",
    "week_start_date",
    "entity_id",
    "entity_name",
    "parent_entity_id",
    "parent_entity_name",
    "metric_name",
    "metric_unit",
    "metric_value",
    "rank",
    "category_slug",
    "app_id",
    "app_name",
    "origin_url",
    "main_url",
    "description",
    "categories",
    "group_by_origin",
    "is_private",
    "is_hidden",
    "created_at",
    "scrape_date",
    "usage_date",
    "model_permaslug",
    "total_tokens",
    "snapshot_date",
    "observed_at",
    "period",
    "tokens",
    "growth_percent",
]

DATE_COLUMNS = ["week_start_date", "scrape_date", "usage_date", "snapshot_date", "scraped_at", "observed_at", "created_at"]
NUMERIC_COLUMNS = ["metric_value", "rank", "total_tokens", "tokens", "growth_percent"]


@dataclass(frozen=True)
class DatasetLoadResult:
    dataset_id: str
    label: str
    domain: str
    primary_date_column: str
    metric_column: str | None
    frame: pd.DataFrame
    source_format: str | None
    source_path: Path | None
    missing_columns: list[str]
    duplicate_rows: int
    first_date: str | None
    latest_date: str | None
    latest_scraped_at: str | None
    row_count: int


@dataclass(frozen=True)
class FreshnessInfo:
    latest_scraped_at: str | None
    latest_run_id: str | None
    latest_manifest_path: Path | None
    latest_manifest_scraped_at: str | None


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def normalized_root(base_dir: Path | None = None) -> Path:
    base = base_dir or repo_root()
    return base / "data" / "normalized" / "openrouter"


def raw_root(base_dir: Path | None = None) -> Path:
    base = base_dir or repo_root()
    return base / "data" / "raw" / "openrouter"


def dataset_ids() -> list[str]:
    return list(DATASET_REGISTRY)


def domain_dataset_ids(domain: str) -> list[str]:
    return DOMAIN_ORDER[domain]


def load_dataset(dataset_id: str, base_dir: Path | None = None) -> DatasetLoadResult:
    metadata = DATASET_REGISTRY[dataset_id]
    base = normalized_root(base_dir)
    parquet_path = base / f"{dataset_id}.parquet"
    csv_path = base / f"{dataset_id}.csv"
    frame = pd.DataFrame(columns=EXPECTED_COLUMNS)
    source_format: str | None = None
    source_path: Path | None = None

    if parquet_path.exists():
        frame = pd.read_parquet(parquet_path)
        source_format = "parquet"
        source_path = parquet_path
    elif csv_path.exists():
        frame = pd.read_csv(csv_path)
        source_format = "csv"
        source_path = csv_path

    missing_columns = [column for column in EXPECTED_COLUMNS if column not in frame.columns]
    for column in EXPECTED_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA

    frame = frame[EXPECTED_COLUMNS].copy()
    for column in DATE_COLUMNS:
        if column in frame.columns:
            frame[column] = frame[column].astype("string")
    for column in NUMERIC_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    keys = metadata["natural_keys"]
    duplicate_rows = 0
    if not frame.empty and all(key in frame.columns for key in keys):
        duplicate_rows = int(frame.duplicated(subset=keys).sum())

    primary_date_column = metadata["primary_date_column"]
    date_values = (
        sorted(frame[primary_date_column].dropna().astype(str).unique().tolist())
        if primary_date_column in frame.columns
        else []
    )
    scraped_values = sorted(frame["scraped_at"].dropna().astype(str).unique().tolist()) if "scraped_at" in frame.columns else []

    return DatasetLoadResult(
        dataset_id=dataset_id,
        label=str(metadata["label"]),
        domain=str(metadata["domain"]),
        primary_date_column=str(primary_date_column),
        metric_column=str(metadata["metric_column"]) if metadata["metric_column"] is not None else None,
        frame=frame,
        source_format=source_format,
        source_path=source_path,
        missing_columns=missing_columns,
        duplicate_rows=duplicate_rows,
        first_date=date_values[0] if date_values else None,
        latest_date=date_values[-1] if date_values else None,
        latest_scraped_at=scraped_values[-1] if scraped_values else None,
        row_count=len(frame),
    )


def load_all_datasets(base_dir: Path | None = None) -> dict[str, DatasetLoadResult]:
    return {dataset_id: load_dataset(dataset_id, base_dir=base_dir) for dataset_id in dataset_ids()}


def load_latest_manifest(
    base_dir: Path | None = None,
    datasets: dict[str, DatasetLoadResult] | None = None,
) -> FreshnessInfo:
    latest_scraped_at: str | None = None
    latest_run_id: str | None = None
    manifest_path: Path | None = None
    manifest_scraped_at: str | None = None

    manifests = sorted(raw_root(base_dir).glob("*/manifest.json"))
    if manifests:
        manifest_path = manifests[-1]
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        latest_run_id = payload.get("run_id")
        manifest_scraped_at = payload.get("scraped_at")

    results = datasets if datasets is not None else load_all_datasets(base_dir=base_dir)
    scraped_values = [result.latest_scraped_at for result in results.values() if result.latest_scraped_at]
    if scraped_values:
        latest_scraped_at = max(scraped_values)

    return FreshnessInfo(
        latest_scraped_at=latest_scraped_at,
        latest_run_id=latest_run_id,
        latest_manifest_path=manifest_path,
        latest_manifest_scraped_at=manifest_scraped_at,
    )
