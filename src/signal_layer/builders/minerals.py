from __future__ import annotations

from pathlib import Path

import pandas as pd

from signal_layer.models import METRIC_SIGNAL_COLUMNS
from signal_layer.quality import canonicalize_latest, duplicate_count, evaluate_metric_quality
from signal_layer.transforms import calculate_rolling_growth, summarize_latest_signal


def build_minerals_signals(base_dir: Path, metric_registry: pd.DataFrame) -> pd.DataFrame:
    metrics = metric_registry.loc[metric_registry["source"] == "minerals"].copy()
    if metrics.empty:
        return pd.DataFrame(columns=METRIC_SIGNAL_COLUMNS)

    records: list[dict[str, object]] = []
    for _, metric in metrics.iterrows():
        if str(metric["transform"]) != "rolling_growth":
            continue

        dataset_id = str(metric["dataset_id"])
        dataset_path = (
            Path(base_dir)
            / "data"
            / "processed"
            / "minerals_signal_data"
            / dataset_id
            / "latest"
            / f"{dataset_id}.parquet"
        )
        if not dataset_path.exists():
            continue

        source = pd.read_parquet(dataset_path)
        if source.empty:
            continue

        records.extend(_build_price_records(source, metric))

    if not records:
        return pd.DataFrame(columns=METRIC_SIGNAL_COLUMNS)

    return pd.DataFrame.from_records(records, columns=METRIC_SIGNAL_COLUMNS)


def _build_price_records(source: pd.DataFrame, metric: pd.Series) -> list[dict[str, object]]:
    date_column = str(metric["date_column"])
    value_column = str(metric["value_column"])
    entity_columns = [column for column in str(metric["entity_columns"]).split("|") if column]

    working = source.copy()
    working[date_column] = pd.to_datetime(working[date_column], errors="coerce")
    working[value_column] = pd.to_numeric(working[value_column], errors="coerce")
    if "commodity" not in working.columns and entity_columns == ["commodity"]:
        working["commodity"] = value_column

    grain = entity_columns + [date_column]
    canonical = canonicalize_latest(working, grain=grain, prefer_non_null=[value_column], run_id_column="url")
    if canonical.empty:
        return []

    run_date = pd.Timestamp.now("UTC").tz_localize(None)
    metric_records: list[dict[str, object]] = []

    for entity_values, group in canonical.groupby(entity_columns, dropna=False):
        entity_tuple = entity_values if isinstance(entity_values, tuple) else (entity_values,)
        entity_filters = dict(zip(entity_columns, entity_tuple))
        source_entity = working.copy()
        for column, value in entity_filters.items():
            if pd.isna(value):
                source_entity = source_entity.loc[source_entity[column].isna()]
            else:
                source_entity = source_entity.loc[source_entity[column] == value]

        group = group.dropna(subset=[date_column, value_column]).sort_values(date_column)
        if group.empty:
            continue

        series = group.set_index(date_column)[value_column].sort_index()
        transformed = calculate_rolling_growth(series, window=65).dropna()
        if transformed.empty:
            continue

        latest_date = transformed.index.max()
        baseline_values = transformed.loc[transformed.index < latest_date].dropna().tail(252)
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
            invalid_value_count=int((source_entity[value_column] <= 0).fillna(False).sum()),
            duplicate_count=duplicate_count(source_entity, grain),
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

        entity_key = "|".join("" if pd.isna(value) else str(value) for value in entity_tuple)
        metric_records.append(
            {
                "metric_id": metric["metric_id"],
                "source": metric["source"],
                "as_of_date": latest_date.date().isoformat(),
                "entity_key": entity_key,
                "entity_name": entity_key,
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
                "source_updated_at": pd.NA,
                "quality_state": quality.quality_state,
                "quality_issues": quality.quality_issues,
                "caveats": metric["caveats"],
            }
        )

    return metric_records
