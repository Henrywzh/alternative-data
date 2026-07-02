from __future__ import annotations

from pathlib import Path

import pandas as pd

from signal_layer.models import METRIC_SIGNAL_COLUMNS
from signal_layer.quality import canonicalize_latest, duplicate_count, evaluate_metric_quality
from signal_layer.transforms import calculate_yoy_growth, summarize_latest_signal


DATASET_LOCATIONS = {
    "tw_monthly_revenue": ("taiwan_semiconductor_revenue", "tw_monthly_revenue.parquet"),
    "fred_semiconductor_ppi": ("semiconductor_memory", "fred_semiconductor_ppi.parquet"),
    "semiconductor_official_monthly": ("semiconductor_proxies", "semiconductor_official_monthly.parquet"),
}


def build_semiconductor_signals(base_dir: Path, metric_registry: pd.DataFrame) -> pd.DataFrame:
    metrics = metric_registry.loc[metric_registry["source"] == "semiconductor"].copy()
    if metrics.empty:
        return pd.DataFrame(columns=METRIC_SIGNAL_COLUMNS)

    normalized_root = Path(base_dir) / "data" / "normalized"
    records: list[dict[str, object]] = []

    for _, metric in metrics.iterrows():
        if str(metric["transform"]) != "yoy_growth":
            continue

        dataset_id = str(metric["dataset_id"])
        location = DATASET_LOCATIONS.get(dataset_id)
        if location is None:
            continue

        dataset_dir, filename = location
        dataset_path = normalized_root / dataset_dir / filename
        if not dataset_path.exists():
            continue

        source = pd.read_parquet(dataset_path)
        if source.empty:
            continue

        records.extend(_build_metric_records(source, metric))

    if not records:
        return pd.DataFrame(columns=METRIC_SIGNAL_COLUMNS)

    return pd.DataFrame.from_records(records, columns=METRIC_SIGNAL_COLUMNS)


def _build_metric_records(source: pd.DataFrame, metric: pd.Series) -> list[dict[str, object]]:
    entity_columns = [column for column in str(metric["entity_columns"]).split("|") if column]
    date_column = str(metric["date_column"])
    value_column = str(metric["value_column"])
    grain = [*entity_columns, date_column]

    raw = source.copy()
    canonical = canonicalize_latest(raw, grain=grain, prefer_non_null=[], run_id_column="source_run_id")
    if canonical.empty:
        return []

    canonical = canonical.copy()
    canonical[date_column] = _parse_monthly_dates(canonical[date_column])
    canonical[value_column] = pd.to_numeric(canonical[value_column], errors="coerce")
    canonical = canonical.dropna(subset=[date_column, value_column]).sort_values(entity_columns + [date_column])
    if canonical.empty:
        return []

    raw = raw.copy()
    raw[date_column] = _parse_monthly_dates(raw[date_column])
    raw[value_column] = pd.to_numeric(raw[value_column], errors="coerce")

    run_date = pd.Timestamp.now("UTC").tz_localize(None)
    metric_records: list[dict[str, object]] = []

    for entity_values, entity_frame in canonical.groupby(entity_columns, dropna=False):
        entity_tuple = entity_values if isinstance(entity_values, tuple) else (entity_values,)
        entity_filters = dict(zip(entity_columns, entity_tuple))
        raw_entity = raw.copy()
        for column, value in entity_filters.items():
            if pd.isna(value):
                raw_entity = raw_entity.loc[raw_entity[column].isna()]
            else:
                raw_entity = raw_entity.loc[raw_entity[column] == value]

        series = entity_frame.set_index(date_column)[value_column].sort_index()
        transformed = calculate_yoy_growth(series).dropna()
        if transformed.empty:
            continue

        latest_date = transformed.index.max()
        baseline_values = transformed.loc[transformed.index < latest_date].dropna().tail(
            _baseline_periods(metric.get("baseline_window"))
        )
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
        entity_name = _entity_name(latest_row, entity_columns)
        source_updated_at = latest_row.get("scraped_at", pd.NA)
        entity_key = "|".join("" if pd.isna(value) else str(value) for value in entity_tuple)

        metric_records.append(
            {
                "metric_id": metric["metric_id"],
                "source": metric["source"],
                "as_of_date": latest_date.date().isoformat(),
                "entity_key": entity_key,
                "entity_name": entity_name,
                "latest_value": summary["latest_value"],
                "comparison_value": summary["comparison_value"],
                "raw_change": pd.NA,
                "pct_change": pd.NA,
                "yoy_change": latest_transformed_value,
                "rolling_change": pd.NA,
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


def _parse_monthly_dates(values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    missing = parsed.isna()
    if missing.any():
        parsed.loc[missing] = pd.to_datetime(values.loc[missing].astype("string") + "-01", errors="coerce")
    return parsed


def _baseline_periods(baseline_window: object) -> int:
    window = str(baseline_window).strip().upper()
    if window.endswith("M") and window[:-1].isdigit():
        return int(window[:-1])
    return 36


def _entity_name(row: pd.Series, entity_columns: list[str]) -> object:
    for candidate in ("company_name", "series_name", "category_label", "country_name"):
        value = row.get(candidate, pd.NA)
        if not pd.isna(value):
            return value
    first_entity = entity_columns[0] if entity_columns else None
    return row.get(first_entity, pd.NA) if first_entity is not None else pd.NA
