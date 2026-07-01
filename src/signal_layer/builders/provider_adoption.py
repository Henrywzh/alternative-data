from __future__ import annotations

from pathlib import Path

import pandas as pd

from signal_layer.models import METRIC_SIGNAL_COLUMNS
from signal_layer.quality import canonicalize_latest, duplicate_count, evaluate_metric_quality
from signal_layer.transforms import calculate_rolling_growth, summarize_latest_signal


def build_provider_adoption_signals(base_dir: Path, metric_registry: pd.DataFrame) -> pd.DataFrame:
    metrics = metric_registry.loc[metric_registry["source"] == "provider_adoption"].copy()
    if metrics.empty:
        return pd.DataFrame(columns=METRIC_SIGNAL_COLUMNS)

    records: list[dict[str, object]] = []
    normalized_root = Path(base_dir) / "data" / "normalized" / "provider_adoption"

    for _, metric in metrics.iterrows():
        dataset_path = normalized_root / f"{metric['dataset_id']}.parquet"
        if not dataset_path.exists():
            continue

        source = pd.read_parquet(dataset_path)
        if source.empty:
            continue

        entity_columns = [column for column in str(metric["entity_columns"]).split("|") if column]
        date_column = str(metric["date_column"])
        value_column = str(metric["value_column"])
        grain = [*entity_columns, date_column]

        metric_records = _build_metric_records(source, metric)
        if metric_records:
            records.extend(metric_records)

    if not records:
        return pd.DataFrame(columns=METRIC_SIGNAL_COLUMNS)

    return pd.DataFrame.from_records(records, columns=METRIC_SIGNAL_COLUMNS)


def _build_metric_records(source: pd.DataFrame, metric: pd.Series) -> list[dict[str, object]]:
    entity_columns = [column for column in str(metric["entity_columns"]).split("|") if column]
    date_column = str(metric["date_column"])
    value_column = str(metric["value_column"])
    grain = [*entity_columns, date_column]
    canonical = canonicalize_latest(
        source,
        grain=grain,
        prefer_non_null=["package_category"],
        run_id_column="source_run_id",
    )
    if canonical.empty:
        return []

    canonical = canonical.copy()
    canonical[date_column] = pd.to_datetime(canonical[date_column], errors="coerce")
    canonical[value_column] = pd.to_numeric(canonical[value_column], errors="coerce")
    canonical = canonical.sort_values(entity_columns + [date_column])

    raw = source.copy()
    raw[date_column] = pd.to_datetime(raw[date_column], errors="coerce")
    raw[value_column] = pd.to_numeric(raw[value_column], errors="coerce")

    run_date = pd.Timestamp.now("UTC").tz_localize(None)
    metric_records: list[dict[str, object]] = []

    for entity_values, entity_frame in canonical.groupby(entity_columns, dropna=False):
        entity_key_parts = entity_values if isinstance(entity_values, tuple) else (entity_values,)
        entity_filters = dict(zip(entity_columns, entity_key_parts))
        raw_entity = raw.copy()
        for column, value in entity_filters.items():
            raw_entity = raw_entity.loc[raw_entity[column] == value]

        series = entity_frame.set_index(date_column)[value_column].sort_index()
        transformed = calculate_rolling_growth(series, window=28).dropna()
        if transformed.empty:
            continue

        latest_date = transformed.index.max()
        transformed_before_latest = transformed.loc[transformed.index < latest_date].dropna()
        baseline_values = transformed_before_latest.tail(90)
        latest_transformed_value = float(transformed.loc[latest_date])
        latest_value = float(series.loc[latest_date])

        quality = evaluate_metric_quality(
            baseline_observation_count=int(len(baseline_values)),
            min_baseline_observations=int(metric["min_baseline_observations"]),
            latest_date=latest_date,
            run_date=run_date,
            max_freshness_lag_days=(
                None if pd.isna(metric["max_freshness_lag_days"]) else int(metric["max_freshness_lag_days"])
            ),
            invalid_value_count=int((raw_entity[value_column] < 0).fillna(False).sum()),
            duplicate_count=duplicate_count(raw_entity, grain),
            coverage_ratio=None,
            min_coverage_ratio=None,
            partial_period=False,
            source_validated=True,
        )
        summary = summarize_latest_signal(
            latest_value=latest_value,
            transformed_value=latest_transformed_value,
            baseline_values=baseline_values,
            baseline_method=str(metric["baseline_method"]),
            baseline_window=str(metric["baseline_window"]),
            metric_direction=str(metric["default_metric_direction"]),
            quality_state=quality.quality_state,
        )

        latest_row = entity_frame.loc[entity_frame[date_column] == latest_date].iloc[-1]
        source_updated_at = latest_row.get("scraped_at", pd.NA)
        entity_name = latest_row.get("provider_display_name", pd.NA)
        if pd.isna(entity_name):
            entity_name = latest_row.get(entity_columns[0], pd.NA)

        metric_records.append(
            {
                "metric_id": metric["metric_id"],
                "source": metric["source"],
                "as_of_date": latest_date.date().isoformat(),
                "entity_key": "|".join("" if pd.isna(value) else str(value) for value in entity_key_parts),
                "entity_name": entity_name,
                "latest_value": summary["latest_value"],
                "comparison_value": summary["comparison_value"],
                "raw_change": pd.NA,
                "pct_change": pd.NA,
                "yoy_change": pd.NA,
                "rolling_change": latest_transformed_value,
                "z_score": summary["z_score"],
                "robust_z_score": summary["robust_z_score"],
                "percentile": summary["percentile"],
                "rank": pd.NA,
                "rank_change": pd.NA,
                "baseline_value": summary["baseline_value"],
                "baseline_method": summary["baseline_method"],
                "baseline_window": summary["baseline_window"],
                "baseline_observation_count": summary["baseline_observation_count"],
                "empirical_percentile": summary["empirical_percentile"],
                "tail_probability": summary["tail_probability"],
                "effect_size": summary["effect_size"],
                "signed_stat": summary["signed_stat"],
                "metric_direction": metric["default_metric_direction"],
                "signal_state": summary["signal_state"],
                "confidence": "medium",
                "source_updated_at": source_updated_at,
                "quality_state": quality.quality_state,
                "quality_issues": quality.quality_issues,
                "caveats": metric["caveats"],
            }
        )

    return metric_records
