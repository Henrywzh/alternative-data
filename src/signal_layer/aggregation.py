from __future__ import annotations

import math

import pandas as pd

from signal_layer.models import ASSET_SIGNAL_COLUMNS, THEME_SIGNAL_COLUMNS


def build_asset_signals(
    metric_signals: pd.DataFrame,
    asset_mapping: pd.DataFrame,
    metric_registry: pd.DataFrame,
) -> pd.DataFrame:
    if metric_signals.empty or asset_mapping.empty:
        return pd.DataFrame(columns=ASSET_SIGNAL_COLUMNS)

    if {"metric_id", "description"}.issubset(metric_registry.columns):
        descriptions = (
            metric_registry.loc[:, ["metric_id", "description"]]
            .drop_duplicates(subset=["metric_id"])
            .rename(columns={"description": "metric_description"})
        )
    else:
        descriptions = pd.DataFrame(columns=["metric_id", "metric_description"])
    mapping_columns = asset_mapping.rename(columns={"confidence": "mapping_confidence"})
    mapped = metric_signals.merge(mapping_columns, on="metric_id", how="inner")
    if mapped.empty:
        return pd.DataFrame(columns=ASSET_SIGNAL_COLUMNS)
    mapped = mapped.merge(descriptions, on="metric_id", how="left")

    mapped["as_of_date"] = pd.to_datetime(mapped["as_of_date"], errors="coerce")
    lag_days = (
        pd.to_numeric(mapped["lag_days"], errors="coerce")
        if "lag_days" in mapped.columns
        else pd.Series(0, index=mapped.index, dtype="float64")
    )
    mapped["lag_days"] = lag_days.fillna(0)
    mapped["as_of_date"] = mapped["as_of_date"] + pd.to_timedelta(mapped["lag_days"], unit="D")
    mapped["signed_stat"] = pd.to_numeric(mapped["signed_stat"], errors="coerce")
    mapped["exposure_weight"] = (
        pd.to_numeric(mapped["exposure_weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
    )
    mapped["adjusted_signed_stat"] = mapped["signed_stat"]
    negative_mask = mapped["expected_direction"].astype("string").str.lower().eq("negative")
    mapped.loc[negative_mask, "adjusted_signed_stat"] = -mapped.loc[negative_mask, "adjusted_signed_stat"]
    mapped["valid_driver"] = mapped["quality_state"].astype("string").eq("valid")
    mapped["sqrt_weight"] = mapped["exposure_weight"].pow(0.5)
    mapped["weighted_adjusted_stat"] = mapped["adjusted_signed_stat"] * mapped["sqrt_weight"]

    group_columns = ["ticker", "company_name", "asset_type", "as_of_date", "theme"]
    rows = [
        _asset_row(group)
        for _, group in mapped.groupby(group_columns, dropna=False, sort=True)
    ]
    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=ASSET_SIGNAL_COLUMNS)
    result["as_of_date"] = result["as_of_date"].dt.strftime("%Y-%m-%d")
    return result.loc[:, ASSET_SIGNAL_COLUMNS]


def build_theme_signals(asset_signals: pd.DataFrame) -> pd.DataFrame:
    if asset_signals.empty:
        return pd.DataFrame(columns=THEME_SIGNAL_COLUMNS)

    working = asset_signals.copy()
    working["as_of_date"] = pd.to_datetime(working["as_of_date"], errors="coerce")
    working["combined_signed_stat"] = pd.to_numeric(working["combined_signed_stat"], errors="coerce")
    working["combined_tail_probability"] = pd.to_numeric(
        working["combined_tail_probability"], errors="coerce"
    )
    working["median_signed_stat"] = pd.to_numeric(working["median_signed_stat"], errors="coerce")
    working["positive_evidence_count"] = pd.to_numeric(
        working["positive_evidence_count"], errors="coerce"
    ).fillna(0)
    working["negative_evidence_count"] = pd.to_numeric(
        working["negative_evidence_count"], errors="coerce"
    ).fillna(0)

    rows = [
        _theme_row(group)
        for _, group in working.groupby(["theme", "as_of_date"], dropna=False, sort=True)
    ]
    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=THEME_SIGNAL_COLUMNS)
    result["as_of_date"] = result["as_of_date"].dt.strftime("%Y-%m-%d")
    return result.loc[:, THEME_SIGNAL_COLUMNS]


def _asset_row(group: pd.DataFrame) -> dict[str, object]:
    valid = group.loc[group["valid_driver"]].copy()
    combined_stat = _combine_signed_stats(valid, "adjusted_signed_stat", "exposure_weight")
    combined_tail = _tail_probability_from_stat(combined_stat)
    median_signed_stat = _safe_median(valid["adjusted_signed_stat"])
    top_metric_id, top_metric_description = _top_metric(valid if not valid.empty else group)
    quality_issues = _aggregate_quality_issues(group)
    confidence = _asset_confidence(valid, group)

    return {
        "ticker": group["ticker"].iloc[0],
        "company_name": group["company_name"].iloc[0],
        "asset_type": group["asset_type"].iloc[0],
        "as_of_date": group["as_of_date"].iloc[0],
        "theme": group["theme"].iloc[0],
        "combined_signed_stat": combined_stat,
        "combined_tail_probability": combined_tail,
        "median_signed_stat": median_signed_stat,
        "positive_evidence_count": int(valid["adjusted_signed_stat"].gt(0).sum()),
        "negative_evidence_count": int(valid["adjusted_signed_stat"].lt(0).sum()),
        "bullish_metric_count": int(group["signal_state"].astype("string").eq("bullish").sum()),
        "bearish_metric_count": int(group["signal_state"].astype("string").eq("bearish").sum()),
        "neutral_metric_count": int(
            (~group["signal_state"].astype("string").isin(["bullish", "bearish"])).sum()
        ),
        "top_metric_id": top_metric_id,
        "top_metric_description": top_metric_description,
        "driver_count": int(len(group)),
        "valid_driver_count": int(len(valid)),
        "non_valid_driver_count": int(len(group) - len(valid)),
        "quality_issues": quality_issues,
        "signal_state": _state_from_stat(combined_stat, combined_tail),
        "confidence": confidence,
        "summary": _asset_summary(
            group["ticker"].iloc[0], group["theme"].iloc[0], combined_stat, len(valid), len(group)
        ),
    }


def _theme_row(group: pd.DataFrame) -> dict[str, object]:
    evidence = group.loc[pd.to_numeric(group["valid_driver_count"], errors="coerce").fillna(0).gt(0)].copy()
    active_group = evidence if not evidence.empty else group.iloc[0:0]
    top_asset = _top_asset(active_group)
    combined_stat = _combine_asset_stats(group)
    combined_tail = _tail_probability_from_stat(combined_stat)
    median_signed_stat = _safe_median(group["combined_signed_stat"])
    confidence = _rollup_confidence(group["confidence"])

    return {
        "theme": group["theme"].iloc[0],
        "as_of_date": group["as_of_date"].iloc[0],
        "combined_signed_stat": combined_stat,
        "combined_tail_probability": combined_tail,
        "median_signed_stat": median_signed_stat,
        "positive_evidence_count": int(group["positive_evidence_count"].sum()),
        "negative_evidence_count": int(group["negative_evidence_count"].sum()),
        "active_metric_count": int(active_group["top_metric_id"].dropna().astype("string").nunique()),
        "active_asset_count": int(active_group["ticker"].dropna().astype("string").nunique()),
        "top_metric_id": top_asset.get("top_metric_id"),
        "top_ticker": top_asset.get("ticker"),
        "signal_state": _state_from_stat(combined_stat, combined_tail),
        "confidence": confidence,
        "summary": _theme_summary(
            group["theme"].iloc[0], combined_stat, int(active_group["ticker"].dropna().astype("string").nunique())
        ),
    }


def _combine_signed_stats(group: pd.DataFrame, stat_column: str, weight_column: str) -> float:
    if group.empty:
        return float("nan")
    valid = group.loc[group[stat_column].notna()].copy()
    if valid.empty:
        return float("nan")

    weights = pd.to_numeric(valid[weight_column], errors="coerce").fillna(0.0).clip(lower=0.0)
    positive_weight = weights.gt(0)
    if positive_weight.any():
        valid = valid.loc[positive_weight]
        weights = weights.loc[positive_weight]
        numerator = float((valid[stat_column] * weights.pow(0.5)).sum())
        denominator = math.sqrt(float(weights.sum()))
        return float("nan") if denominator == 0 else numerator / denominator

    return float(valid[stat_column].mean())


def _combine_asset_stats(group: pd.DataFrame) -> float:
    stats = pd.to_numeric(group["combined_signed_stat"], errors="coerce").dropna()
    if stats.empty:
        return float("nan")
    return float(stats.sum() / math.sqrt(len(stats)))


def _tail_probability_from_stat(stat: float) -> float:
    if pd.isna(stat):
        return float("nan")
    return float(math.erfc(abs(float(stat)) / math.sqrt(2.0)))


def _state_from_stat(stat: float, tail_probability: float) -> str:
    if pd.isna(stat) or pd.isna(tail_probability):
        return "watch"
    if tail_probability <= 0.05 and stat > 0:
        return "bullish"
    if tail_probability <= 0.05 and stat < 0:
        return "bearish"
    if tail_probability <= 0.10:
        return "watch"
    return "neutral"


def _safe_median(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return float("nan")
    return float(clean.median())


def _top_metric(group: pd.DataFrame) -> tuple[str | None, str | None]:
    if group.empty:
        return None, None
    ranked = group.assign(_abs_stat=group["adjusted_signed_stat"].abs()).sort_values(
        ["_abs_stat", "metric_id"], ascending=[False, True]
    )
    top = ranked.iloc[0]
    metric_id = top.get("metric_id")
    description = top.get("metric_description")
    return (
        None if pd.isna(metric_id) else str(metric_id),
        None if pd.isna(description) else str(description),
    )


def _top_asset(group: pd.DataFrame) -> dict[str, object]:
    ranked = group.assign(_abs_stat=group["combined_signed_stat"].abs()).sort_values(
        ["_abs_stat", "ticker"], ascending=[False, True]
    )
    return ranked.iloc[0].to_dict() if not ranked.empty else {}


def _aggregate_quality_issues(group: pd.DataFrame) -> str:
    issues: list[str] = []
    for row in group.itertuples(index=False):
        metric_id = getattr(row, "metric_id", None)
        quality_state = getattr(row, "quality_state", None)
        quality_issues = getattr(row, "quality_issues", None)
        if quality_state == "valid" and (quality_issues is None or str(quality_issues).strip() == ""):
            continue
        fragments = [str(metric_id)] if metric_id is not None and not pd.isna(metric_id) else []
        if quality_state is not None and not pd.isna(quality_state):
            fragments.append(f"quality_state={quality_state}")
        if quality_issues is not None and not pd.isna(quality_issues) and str(quality_issues).strip():
            fragments.append(str(quality_issues))
        if fragments:
            issues.append(": ".join([fragments[0], "; ".join(fragments[1:])]) if len(fragments) > 1 else fragments[0])
    return " | ".join(issues)


def _asset_confidence(valid: pd.DataFrame, group: pd.DataFrame) -> str:
    mapping_confidence = _rollup_confidence(group["mapping_confidence"])
    if valid.empty:
        return "low"
    if mapping_confidence == "high" and len(valid) >= 2:
        return "high"
    if mapping_confidence in {"high", "medium"}:
        return "medium"
    return "low"


def _rollup_confidence(series: pd.Series) -> str:
    values = [str(value).lower() for value in series.dropna() if str(value).strip()]
    if not values:
        return "low"
    if all(value == "high" for value in values):
        return "high"
    if any(value in {"high", "medium"} for value in values):
        return "medium"
    return "low"


def _asset_summary(ticker: object, theme: object, stat: float, valid_count: int, driver_count: int) -> str:
    stat_text = "nan" if pd.isna(stat) else f"{float(stat):.2f}"
    return (
        f"{ticker} {theme} evidence summary: combined_stat={stat_text}, "
        f"valid_drivers={valid_count}/{driver_count}."
    )


def _theme_summary(theme: object, stat: float, asset_count: int) -> str:
    stat_text = "nan" if pd.isna(stat) else f"{float(stat):.2f}"
    return f"{theme} evidence summary: combined_stat={stat_text}, active_assets={asset_count}."
