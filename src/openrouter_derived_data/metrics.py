"""Derived workload-intensity metrics from canonical OpenRouter activity."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Final

import pandas as pd

from .identity import CapabilityMap, compatible_activity_ids


METHODOLOGY_VERSION: Final = "openrouter-derived-v1"
DAILY_DATASET_ID: Final = "openrouter_usage_economics_daily"
TOKEN_METRICS: Final = {
    "total_tokens_per_request": "total_tokens",
    "prompt_tokens_per_request": "prompt_tokens",
    "completion_tokens_per_request": "completion_tokens",
}
_DAILY_COLUMNS: Final = [
    "dataset_id",
    "source_url",
    "source_run_id",
    "scraped_at",
    "usage_date",
    "metric_id",
    "cohort_id",
    "value",
    "numerator",
    "denominator",
    "rolling_window_days",
    "benchmark_snapshot_date",
    "pricing_snapshot_date",
    "expected_family_count",
    "priced_family_count",
    "observed_family_count",
    "observed_model_count",
    "included_tokens",
    "excluded_free_tokens",
    "excluded_unpriced_tokens",
    "excluded_zero_request_rows",
    "pricing_join_status",
    "methodology_version",
]
_MODEL_COLUMNS: Final = [
    "window_start_date",
    "window_end_date",
    "model_id",
    "company_id",
    "total_tokens",
    "prompt_tokens",
    "completion_tokens",
    "request_count",
    "token_share",
    "request_share",
    "tokens_per_request",
    "intensity_ratio",
    "model_match_status",
    "methodology_version",
]


def _empty_daily() -> pd.DataFrame:
    return pd.DataFrame(columns=_DAILY_COLUMNS)


def _empty_models() -> pd.DataFrame:
    return pd.DataFrame(columns=_MODEL_COLUMNS)


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _prepare_activity(activity: pd.DataFrame, *, today: date) -> pd.DataFrame:
    """Normalize activity rows and retain only complete observation dates."""
    required_columns = {
        "usage_date",
        "model_permaslug",
        "entity_id",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "request_count",
    }
    normalized = activity.copy()
    for column in required_columns:
        if column not in normalized:
            normalized[column] = pd.NA

    normalized["usage_date"] = pd.to_datetime(normalized["usage_date"], errors="coerce").dt.normalize()
    for column in ("total_tokens", "prompt_tokens", "completion_tokens", "request_count"):
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    complete_day_rows = normalized["usage_date"].lt(pd.Timestamp(today))
    return normalized.loc[complete_day_rows].copy()


def _activity_provenance(activity: pd.DataFrame) -> dict[str, object]:
    """Carry available source metadata without inventing raw-source values."""
    provenance: dict[str, object] = {}
    for column in ("source_url", "source_run_id", "scraped_at"):
        values = activity[column].dropna() if column in activity else pd.Series(dtype="object")
        provenance[column] = values.iloc[-1] if not values.empty else pd.NA
    return provenance


def compute_workload_intensity_daily(
    activity: pd.DataFrame, *, today: date | None = None
) -> pd.DataFrame:
    """Return daily and seven-calendar-day rolling token-per-request ratios."""
    complete_activity = _prepare_activity(activity, today=today or _utc_today())
    if complete_activity.empty:
        return _empty_daily()

    calendar_days = pd.date_range(
        complete_activity["usage_date"].min(),
        complete_activity["usage_date"].max(),
        freq="D",
    )
    invalid_request_rows = (
        complete_activity["request_count"].isna()
        | complete_activity["request_count"].le(0)
    )
    excluded_by_day = (
        complete_activity.loc[invalid_request_rows]
        .groupby("usage_date")
        .size()
        .reindex(calendar_days, fill_value=0)
    )
    provenance = _activity_provenance(activity)
    rows: list[dict[str, object]] = []
    for metric_id, source_column in TOKEN_METRICS.items():
        metric_eligible = complete_activity.loc[
            complete_activity["request_count"].gt(0)
            & complete_activity[source_column].notna()
        ].copy()
        tokens_by_day = (
            metric_eligible.groupby("usage_date")[source_column]
            .sum()
            .reindex(calendar_days)
        )
        requests_by_day = (
            metric_eligible.groupby("usage_date")["request_count"]
            .sum()
            .reindex(calendar_days)
        )
        for window in (1, 7):
            rolling_tokens = tokens_by_day.rolling(window, min_periods=1).sum()
            rolling_requests = requests_by_day.rolling(window, min_periods=1).sum()
            values = rolling_tokens / rolling_requests
            excluded_in_window = excluded_by_day.rolling(window, min_periods=1).sum()
            for index, day in enumerate(calendar_days):
                window_start = day - pd.Timedelta(days=window - 1)
                contributing_models = metric_eligible.loc[
                    metric_eligible["usage_date"].between(window_start, day),
                    "model_permaslug",
                ]
                rows.append(
                    {
                        "dataset_id": DAILY_DATASET_ID,
                        **provenance,
                        "usage_date": day.strftime("%Y-%m-%d"),
                        "metric_id": metric_id,
                        "cohort_id": "all_models",
                        "value": values.iloc[index],
                        "numerator": rolling_tokens.iloc[index],
                        "denominator": rolling_requests.iloc[index],
                        "rolling_window_days": window,
                        "benchmark_snapshot_date": pd.NA,
                        "pricing_snapshot_date": pd.NA,
                        "expected_family_count": pd.NA,
                        "priced_family_count": pd.NA,
                        "observed_family_count": pd.NA,
                        "observed_model_count": contributing_models.nunique(),
                        "included_tokens": rolling_tokens.iloc[index],
                        "excluded_free_tokens": pd.NA,
                        "excluded_unpriced_tokens": pd.NA,
                        "excluded_zero_request_rows": excluded_in_window.iloc[index],
                        "methodology_version": METHODOLOGY_VERSION,
                    }
                )
    return pd.DataFrame(rows, columns=_DAILY_COLUMNS)


def compute_workload_intensity_models(
    activity: pd.DataFrame, *, today: date | None = None, window_days: int = 30
) -> pd.DataFrame:
    """Compare canonical models over the latest complete observation window."""
    if window_days < 1:
        raise ValueError("window_days must be positive")

    eligible = _prepare_activity(activity, today=today or _utc_today())
    eligible = eligible.loc[
        eligible["request_count"].gt(0) & eligible["total_tokens"].notna()
    ].copy()
    if eligible.empty:
        return _empty_models()

    window_end_date = eligible["usage_date"].max()
    window_start_date = window_end_date - pd.Timedelta(days=window_days - 1)
    window = eligible.loc[eligible["usage_date"].ge(window_start_date)].copy()
    grouped = (
        window.groupby(["model_permaslug", "entity_id"], dropna=False, as_index=False)
        .agg(
            total_tokens=("total_tokens", lambda values: values.sum(min_count=1)),
            prompt_tokens=("prompt_tokens", lambda values: values.sum(min_count=1)),
            completion_tokens=("completion_tokens", lambda values: values.sum(min_count=1)),
            request_count=("request_count", "sum"),
        )
        .rename(columns={"model_permaslug": "model_id", "entity_id": "company_id"})
    )
    total_tokens = grouped["total_tokens"].sum(min_count=1)
    total_requests = grouped["request_count"].sum(min_count=1)
    grouped["token_share"] = grouped["total_tokens"] / total_tokens
    grouped["request_share"] = grouped["request_count"] / total_requests
    grouped["tokens_per_request"] = grouped["total_tokens"] / grouped["request_count"].replace(0, pd.NA)
    grouped["intensity_ratio"] = grouped["token_share"] / grouped["request_share"].replace(0, pd.NA)
    grouped["window_start_date"] = window_start_date.strftime("%Y-%m-%d")
    grouped["window_end_date"] = window_end_date.strftime("%Y-%m-%d")
    grouped["model_match_status"] = "canonical"
    grouped["methodology_version"] = METHODOLOGY_VERSION
    return grouped.loc[:, _MODEL_COLUMNS].sort_values("model_id", kind="stable").reset_index(drop=True)


def compute_price_metrics(
    economics: pd.DataFrame,
    pricing: pd.DataFrame,
    rankings: pd.DataFrame,
    capability_map: CapabilityMap,
    *,
    today: date | None = None,
    derived_provenance: dict[str, object] | None = None,
) -> pd.DataFrame:
    """Build guarded realized and capability-aware price indices.

    Capability measures use only exact routes from ``capability_map`` and pricing
    snapshots available on or before the usage date. Realized measures are
    seven-calendar-day ratios of summed revenue to summed paid tokens.
    """
    prepared_economics = _prepare_economics(economics)
    prepared_pricing = _prepare_pricing(pricing)
    prepared_rankings = _prepare_rankings(rankings)
    cutoff = pd.Timestamp(today or _utc_today())
    prepared_economics = prepared_economics.loc[
        prepared_economics["usage_date"].lt(cutoff)
    ].copy()
    prepared_rankings = prepared_rankings.loc[
        prepared_rankings["usage_date"].lt(cutoff)
    ].copy()
    source_dates = sorted(
        set(prepared_economics["usage_date"].dropna())
        | set(prepared_rankings["usage_date"].dropna())
    )
    if not source_dates:
        return _empty_daily()
    dates = pd.date_range(source_dates[0], source_dates[-1], freq="D")

    provenance = _price_provenance(economics, derived_provenance)
    sota_daily, sota_daily_coverage = _prepare_sota_daily(
        prepared_economics,
        prepared_rankings,
        prepared_pricing,
        capability_map,
    )
    rows: list[dict[str, object]] = []
    for usage_date in dates:
        window_start = usage_date - pd.Timedelta(days=6)
        window = prepared_economics.loc[
            prepared_economics["usage_date"].between(window_start, usage_date)
        ].copy()
        daily_rankings = prepared_rankings.loc[
            prepared_rankings["usage_date"].eq(usage_date)
        ].copy()

        rows.append(
            _realized_row(
                usage_date,
                "realized_market_average",
                "all_models",
                window,
                provenance,
            )
        )
        for tier, metric_id, cohort_id in (
            ("sota", "sota_median_list_price", "sota"),
            (
                "frontier_contender",
                "frontier_contenders_median_list_price",
                "frontier_contenders",
            ),
        ):
            tier_rankings = daily_rankings.loc[
                daily_rankings["capability_tier"].eq(tier)
            ].copy()
            rows.append(
                _list_price_row(
                    usage_date,
                    metric_id,
                    cohort_id,
                    tier_rankings,
                    prepared_pricing,
                    capability_map,
                    provenance,
                )
            )

        rows.append(
            _realized_sota_row(
                usage_date,
                daily_rankings.loc[
                    daily_rankings["capability_tier"].eq("sota")
                ].copy(),
                sota_daily,
                sota_daily_coverage,
                prepared_pricing,
                capability_map,
                provenance,
            )
        )

        cohort_rows: dict[str, dict[str, object]] = {}
        for cohort_id, metric_id in (
            ("premium_priced", "premium_priced_realized"),
            ("mid_priced", "mid_priced_realized"),
            ("low_priced", "low_priced_realized"),
        ):
            cohort_window = window.loc[window["price_cohort"].eq(cohort_id)].copy()
            row = _realized_row(
                usage_date,
                metric_id,
                cohort_id,
                cohort_window,
                provenance,
                pricing_status="as_recorded_pricing",
                coverage_window=window,
            )
            rows.append(row)
            cohort_rows[cohort_id] = row
        rows.append(_fixed_basket_row(usage_date, cohort_rows, provenance))

    return pd.DataFrame(rows, columns=_DAILY_COLUMNS)


def _price_provenance(
    economics: pd.DataFrame,
    derived_provenance: dict[str, object] | None,
) -> dict[str, object]:
    """Select one coherent upstream run, or explicitly label derived provenance."""
    columns = ["source_url", "source_run_id", "scraped_at"]
    if set(columns).issubset(economics.columns):
        candidates = economics.loc[:, columns].dropna().drop_duplicates().copy()
        if not candidates.empty:
            candidates["_scraped_at"] = pd.to_datetime(
                candidates["scraped_at"], errors="coerce", utc=True
            )
            candidates = candidates.dropna(subset=["_scraped_at"])
            if not candidates.empty:
                selected = candidates.sort_values(
                    ["_scraped_at", "source_run_id", "source_url"], kind="stable"
                ).iloc[-1]
                return {column: selected[column] for column in columns}
    if derived_provenance is not None:
        return {column: derived_provenance.get(column, pd.NA) for column in columns}
    return {
        "source_url": "derived://openrouter-price-metrics",
        "source_run_id": "derived-unattributed",
        "scraped_at": pd.NA,
    }


def _prepare_economics(economics: pd.DataFrame) -> pd.DataFrame:
    prepared = economics.copy()
    defaults: dict[str, object] = {
        "usage_date": pd.NaT,
        "model_permaslug": pd.NA,
        "total_tokens": pd.NA,
        "estimated_revenue": pd.NA,
        "pricing_snapshot_ts": pd.NaT,
        "pricing_prompt": pd.NA,
        "pricing_completion": pd.NA,
        "pricing_join_status": "unresolved_missing_pricing",
    }
    for column, default in defaults.items():
        if column not in prepared:
            prepared[column] = default
    prepared["usage_date"] = pd.to_datetime(
        prepared["usage_date"], errors="coerce", utc=True
    ).dt.tz_localize(None).dt.normalize()
    prepared["pricing_snapshot_date"] = pd.to_datetime(
        prepared["pricing_snapshot_ts"], errors="coerce", utc=True
    ).dt.tz_localize(None).dt.normalize()
    for column in (
        "total_tokens",
        "estimated_revenue",
        "pricing_prompt",
        "pricing_completion",
    ):
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    model_ids = prepared["model_permaslug"].astype("string")
    statuses = prepared["pricing_join_status"].astype("string")
    zero_prices = prepared["pricing_prompt"].eq(0) & prepared[
        "pricing_completion"
    ].eq(0)
    prepared["is_free"] = (
        model_ids.str.endswith(":free", na=False)
        | statuses.str.contains("free", case=False, na=False)
        | zero_prices
    )
    prepared["is_paid_priced"] = (
        ~prepared["is_free"]
        & prepared["estimated_revenue"].notna()
        & prepared["total_tokens"].gt(0)
        & prepared["pricing_snapshot_date"].notna()
        & prepared["pricing_prompt"].notna()
        & prepared["pricing_completion"].notna()
        & ~statuses.str.contains(
            "unpriced|unresolved|synthetic", case=False, na=False
        )
    )
    prepared["blended_price"] = (
        prepared["pricing_prompt"] * 0.977
        + prepared["pricing_completion"] * 0.023
    )
    prepared["price_cohort"] = pd.Series(
        "mid_priced", index=prepared.index, dtype="string"
    )
    prepared.loc[
        prepared["blended_price"].ge(2.0e-6), "price_cohort"
    ] = "premium_priced"
    prepared.loc[prepared["blended_price"].lt(0.5e-6), "price_cohort"] = "low_priced"
    prepared.loc[~prepared["is_paid_priced"], "price_cohort"] = pd.NA
    return prepared.dropna(subset=["usage_date"])


def _prepare_pricing(pricing: pd.DataFrame) -> pd.DataFrame:
    prepared = pricing.copy()
    for column in ("model_id", "snapshot_ts", "pricing_prompt", "pricing_completion"):
        if column not in prepared:
            prepared[column] = pd.NA
    prepared["_snapshot_instant"] = pd.to_datetime(
        prepared["snapshot_ts"], errors="coerce", utc=True
    )
    prepared["snapshot_date"] = (
        prepared["_snapshot_instant"].dt.tz_localize(None).dt.normalize()
    )
    prepared["pricing_prompt"] = pd.to_numeric(
        prepared["pricing_prompt"], errors="coerce"
    )
    prepared["pricing_completion"] = pd.to_numeric(
        prepared["pricing_completion"], errors="coerce"
    )
    model_ids = prepared["model_id"].astype("string")
    prepared["is_free"] = (
        model_ids.str.endswith(":free", na=False)
        | (prepared["pricing_prompt"].eq(0) & prepared["pricing_completion"].eq(0))
    )
    prepared["blended_price_per_million"] = (
        prepared["pricing_prompt"] * 0.977
        + prepared["pricing_completion"] * 0.023
    ) * 1_000_000
    return prepared.dropna(subset=["model_id", "snapshot_date"]).sort_values(
        ["model_id", "_snapshot_instant"], kind="stable"
    )


def _prepare_rankings(rankings: pd.DataFrame) -> pd.DataFrame:
    prepared = rankings.copy()
    for column in (
        "usage_date",
        "benchmark_snapshot_date",
        "family_id",
        "capability_tier",
        "representative_aa_model_id",
        "family_rank",
    ):
        if column not in prepared:
            prepared[column] = pd.NA
    for column in ("usage_date", "benchmark_snapshot_date"):
        prepared[column] = pd.to_datetime(
            prepared[column], errors="coerce", utc=True
        ).dt.tz_localize(None).dt.normalize()
    prepared["family_rank"] = pd.to_numeric(
        prepared["family_rank"], errors="coerce"
    )
    return prepared.dropna(subset=["usage_date"])


def _tier_cohort(
    rankings: pd.DataFrame, tier: str
) -> tuple[pd.DataFrame, bool]:
    required_ranks = (
        frozenset(range(1, 6))
        if tier == "sota"
        else frozenset(range(6, 11))
    )
    cohort = rankings.loc[
        rankings["capability_tier"].eq(tier)
        & rankings["family_rank"].isin(required_ranks)
    ].copy()
    cohort = cohort.sort_values(
        ["family_rank", "family_id", "representative_aa_model_id"],
        kind="stable",
    ).drop_duplicates(["family_rank", "family_id"], keep="first")
    complete = (
        frozenset(cohort["family_rank"].dropna().astype(int)) == required_ranks
        and cohort["family_id"].nunique() == 5
        and len(cohort) == 5
    )
    return cohort, complete


def _routes_for_rankings(
    rankings: pd.DataFrame, capability_map: CapabilityMap
) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for ranking in rankings.itertuples(index=False):
        for model_id in compatible_activity_ids(
            capability_map, ranking.representative_aa_model_id
        ):
            rows.append({"family_id": ranking.family_id, "model_id": model_id})
    return pd.DataFrame(rows, columns=["family_id", "model_id"]).drop_duplicates()


def _asof_route_prices(
    usage_date: pd.Timestamp,
    rankings: pd.DataFrame,
    pricing: pd.DataFrame,
    capability_map: CapabilityMap,
) -> pd.DataFrame:
    routes = _routes_for_rankings(rankings, capability_map)
    if routes.empty or pricing.empty:
        return pd.DataFrame(
            columns=[
                "family_id",
                "model_id",
                "snapshot_date",
                "blended_price_per_million",
                "is_free",
            ]
        )
    eligible = routes.merge(pricing, on="model_id", how="left", validate="one_to_many")
    eligible = eligible.loc[eligible["snapshot_date"].le(usage_date)].copy()
    if eligible.empty:
        return eligible
    return eligible.sort_values(
        ["family_id", "model_id", "_snapshot_instant"], kind="stable"
    ).drop_duplicates(["family_id", "model_id"], keep="last")


def _base_daily_row(
    usage_date: pd.Timestamp,
    metric_id: str,
    cohort_id: str,
    provenance: dict[str, object],
) -> dict[str, object]:
    return {
        "dataset_id": DAILY_DATASET_ID,
        **provenance,
        "usage_date": usage_date.strftime("%Y-%m-%d"),
        "metric_id": metric_id,
        "cohort_id": cohort_id,
        "value": pd.NA,
        "numerator": pd.NA,
        "denominator": pd.NA,
        "rolling_window_days": 7,
        "benchmark_snapshot_date": pd.NA,
        "pricing_snapshot_date": pd.NA,
        "expected_family_count": pd.NA,
        "priced_family_count": pd.NA,
        "observed_family_count": pd.NA,
        "observed_model_count": pd.NA,
        "included_tokens": pd.NA,
        "excluded_free_tokens": pd.NA,
        "excluded_unpriced_tokens": pd.NA,
        "excluded_zero_request_rows": pd.NA,
        "pricing_join_status": pd.NA,
        "methodology_version": METHODOLOGY_VERSION,
    }


def _status_summary(values: pd.Series) -> object:
    statuses = sorted(set(values.dropna().astype(str)))
    return "|".join(statuses) if statuses else pd.NA


def _latest_date(values: pd.Series) -> object:
    latest = values.dropna().max()
    return latest.strftime("%Y-%m-%d") if pd.notna(latest) else pd.NA


def _realized_row(
    usage_date: pd.Timestamp,
    metric_id: str,
    cohort_id: str,
    window: pd.DataFrame,
    provenance: dict[str, object],
    *,
    pricing_status: str | None = None,
    coverage_window: pd.DataFrame | None = None,
) -> dict[str, object]:
    row = _base_daily_row(usage_date, metric_id, cohort_id, provenance)
    paid = window.loc[window["is_paid_priced"]].copy()
    coverage = window if coverage_window is None else coverage_window
    free = coverage.loc[coverage["is_free"]]
    unpriced = coverage.loc[
        ~coverage["is_free"] & ~coverage["is_paid_priced"]
    ]
    numerator = paid["estimated_revenue"].sum(min_count=1)
    denominator = paid["total_tokens"].sum(min_count=1)
    row.update(
        {
            "value": numerator / denominator * 1_000_000
            if pd.notna(denominator) and denominator > 0
            else pd.NA,
            "numerator": numerator,
            "denominator": denominator,
            "observed_model_count": paid["model_permaslug"].nunique(),
            "included_tokens": denominator,
            "excluded_free_tokens": free["total_tokens"].sum(),
            "excluded_unpriced_tokens": unpriced["total_tokens"].sum(),
            "pricing_snapshot_date": _latest_date(paid["pricing_snapshot_date"]),
            "pricing_join_status": pricing_status
            if pricing_status is not None
            else _status_summary(paid["pricing_join_status"]),
        }
    )
    return row


def _list_price_row(
    usage_date: pd.Timestamp,
    metric_id: str,
    cohort_id: str,
    rankings: pd.DataFrame,
    pricing: pd.DataFrame,
    capability_map: CapabilityMap,
    provenance: dict[str, object],
) -> dict[str, object]:
    row = _base_daily_row(usage_date, metric_id, cohort_id, provenance)
    row["rolling_window_days"] = 1
    tier = "sota" if cohort_id == "sota" else "frontier_contender"
    rankings, complete_cohort = _tier_cohort(rankings, tier)
    route_prices = _asof_route_prices(
        usage_date, rankings, pricing, capability_map
    )
    paid_prices = route_prices.loc[
        ~route_prices.get("is_free", pd.Series(dtype=bool)).fillna(False)
        & route_prices.get(
            "blended_price_per_million", pd.Series(dtype=float)
        ).notna()
    ].copy()
    family_prices = paid_prices.groupby("family_id")[
        "blended_price_per_million"
    ].median()
    priced_count = len(family_prices)
    benchmark_dates = rankings["benchmark_snapshot_date"].dropna()
    row.update(
        {
            "value": family_prices.median()
            if complete_cohort and priced_count >= 3
            else pd.NA,
            "numerator": family_prices.sum(min_count=1),
            "denominator": priced_count,
            "benchmark_snapshot_date": _latest_date(benchmark_dates),
            "pricing_snapshot_date": _latest_date(paid_prices["snapshot_date"]),
            "expected_family_count": 5,
            "priced_family_count": priced_count,
            "pricing_join_status": "strict_asof_pricing",
            "methodology_version": capability_map.methodology_version,
        }
    )
    return row


def _realized_sota_row(
    usage_date: pd.Timestamp,
    current_rankings: pd.DataFrame,
    daily_sota: pd.DataFrame,
    daily_coverage: pd.DataFrame,
    pricing: pd.DataFrame,
    capability_map: CapabilityMap,
    provenance: dict[str, object],
) -> dict[str, object]:
    row = _base_daily_row(
        usage_date, "realized_sota_price", "sota", provenance
    )
    current_rankings, complete_current_cohort = _tier_cohort(
        current_rankings, "sota"
    )
    current_route_prices = _asof_route_prices(
        usage_date, current_rankings, pricing, capability_map
    )
    current_paid_route_prices = current_route_prices.loc[
        ~current_route_prices.get("is_free", pd.Series(dtype=bool)).fillna(False)
        & current_route_prices.get(
            "blended_price_per_million", pd.Series(dtype=float)
        ).notna()
    ]
    window_start = usage_date - pd.Timedelta(days=6)
    paid = daily_sota.loc[
        daily_sota["usage_date"].between(window_start, usage_date)
    ]
    coverage = daily_coverage.loc[
        daily_coverage["usage_date"].between(window_start, usage_date)
    ]
    numerator = paid["numerator"].sum(min_count=1)
    denominator = paid["denominator"].sum(min_count=1)
    observed_count = paid["family_id"].nunique()
    observed_models: set[str] = set()
    for model_ids in paid["model_ids"]:
        observed_models.update(model_ids)
    priced_count = current_paid_route_prices["family_id"].nunique()
    guarded = (
        complete_current_cohort
        and observed_count >= 3
        and priced_count >= 3
    )
    row.update(
        {
            "value": numerator / denominator * 1_000_000
            if guarded and pd.notna(denominator) and denominator > 0
            else pd.NA,
            "numerator": numerator,
            "denominator": denominator,
            "benchmark_snapshot_date": _latest_date(
                current_rankings["benchmark_snapshot_date"].dropna()
            ),
            "pricing_snapshot_date": _latest_date(
                coverage["pricing_snapshot_date"]
            ),
            "expected_family_count": 5,
            "priced_family_count": priced_count,
            "observed_family_count": observed_count,
            "observed_model_count": len(observed_models),
            "included_tokens": denominator,
            "excluded_free_tokens": coverage["excluded_free_tokens"].sum(),
            "excluded_unpriced_tokens": coverage[
                "excluded_unpriced_tokens"
            ].sum(),
            "pricing_join_status": "strict_asof_pricing",
            "methodology_version": capability_map.methodology_version,
        }
    )
    return row


def _prepare_sota_daily(
    economics: pd.DataFrame,
    rankings: pd.DataFrame,
    pricing: pd.DataFrame,
    capability_map: CapabilityMap,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    paid_days: list[pd.DataFrame] = []
    coverage_rows: list[dict[str, object]] = []
    for activity_date, activity_day in economics.groupby("usage_date"):
        daily_rankings, complete_cohort = _tier_cohort(
            rankings.loc[rankings["usage_date"].eq(activity_date)], "sota"
        )
        if not complete_cohort:
            continue
        daily_routes = _routes_for_rankings(daily_rankings, capability_map)
        daily_route_prices = _asof_route_prices(
            activity_date, daily_rankings, pricing, capability_map
        )
        daily_paid_route_prices = daily_route_prices.loc[
            ~daily_route_prices.get(
                "is_free", pd.Series(dtype=bool)
            ).fillna(False)
            & daily_route_prices.get(
                "blended_price_per_million", pd.Series(dtype=float)
            ).notna()
        ]
        valid_paid_routes = set(daily_paid_route_prices["model_id"].astype(str))
        route_family = (
            daily_routes.drop_duplicates("model_id")
            .set_index("model_id")["family_id"]
            if not daily_routes.empty
            else pd.Series(dtype="object")
        )
        compatible = activity_day.loc[
            activity_day["model_permaslug"]
            .astype("string")
            .isin(set(daily_routes["model_id"].astype(str)))
        ].copy()
        compatible["family_id"] = compatible["model_permaslug"].map(
            route_family
        )
        strict_snapshot = compatible["pricing_snapshot_date"].notna() & compatible[
            "pricing_snapshot_date"
        ].le(compatible["usage_date"])
        not_backcast = ~compatible["pricing_join_status"].astype(
            "string"
        ).str.contains("backcast", case=False, na=False)
        paid = compatible.loc[
            compatible["model_permaslug"]
            .astype("string")
            .isin(valid_paid_routes)
            & compatible["is_paid_priced"]
            & strict_snapshot
            & not_backcast
        ].copy()
        free = compatible.loc[compatible["is_free"]]
        unpriced = compatible.loc[
            ~compatible["is_free"] & ~compatible.index.isin(paid.index)
        ]
        grouped = (
            paid.groupby("family_id", as_index=False)
            .agg(
                numerator=(
                    "estimated_revenue",
                    lambda values: values.sum(min_count=1),
                ),
                denominator=("total_tokens", lambda values: values.sum(min_count=1)),
                model_ids=(
                    "model_permaslug",
                    lambda values: frozenset(values.dropna().astype(str)),
                ),
            )
        )
        grouped["usage_date"] = activity_date
        paid_days.append(grouped)
        contributing_prices = daily_paid_route_prices.loc[
            daily_paid_route_prices["model_id"].astype("string").isin(
                set(paid["model_permaslug"].astype(str))
            )
        ]
        coverage_rows.append(
            {
                "usage_date": activity_date,
                "excluded_free_tokens": free["total_tokens"].sum(),
                "excluded_unpriced_tokens": unpriced["total_tokens"].sum(),
                "pricing_snapshot_date": contributing_prices[
                    "snapshot_date"
                ].max(),
            }
        )
    daily = (
        pd.concat(paid_days, ignore_index=True)
        if paid_days
        else pd.DataFrame(
            columns=[
                "usage_date",
                "family_id",
                "numerator",
                "denominator",
                "model_ids",
            ]
        )
    )
    coverage = pd.DataFrame(
        coverage_rows,
        columns=[
            "usage_date",
            "excluded_free_tokens",
            "excluded_unpriced_tokens",
            "pricing_snapshot_date",
        ],
    )
    return daily, coverage


def _fixed_basket_row(
    usage_date: pd.Timestamp,
    cohorts: dict[str, dict[str, object]],
    provenance: dict[str, object],
) -> dict[str, object]:
    row = _base_daily_row(
        usage_date, "fixed_workload_basket", "fixed_workload", provenance
    )
    weights = {
        "premium_priced": 0.5,
        "mid_priced": 0.4,
        "low_priced": 0.1,
    }
    values = {cohort: cohorts[cohort]["value"] for cohort in weights}
    supported = all(pd.notna(value) for value in values.values())
    basket_value = (
        sum(weights[cohort] * float(values[cohort]) for cohort in weights)
        if supported
        else pd.NA
    )
    row.update(
        {
            "value": basket_value,
            "numerator": basket_value,
            "denominator": 1.0 if supported else pd.NA,
            "included_tokens": sum(
                float(cohorts[cohort]["included_tokens"])
                for cohort in weights
                if pd.notna(cohorts[cohort]["included_tokens"])
            ),
            "pricing_snapshot_date": max(
                (
                    cohorts[cohort]["pricing_snapshot_date"]
                    for cohort in weights
                    if pd.notna(cohorts[cohort]["pricing_snapshot_date"])
                ),
                default=pd.NA,
            ),
            "excluded_free_tokens": max(
                (
                    float(cohorts[cohort]["excluded_free_tokens"])
                    for cohort in weights
                    if pd.notna(cohorts[cohort]["excluded_free_tokens"])
                ),
                default=pd.NA,
            ),
            "excluded_unpriced_tokens": max(
                (
                    float(cohorts[cohort]["excluded_unpriced_tokens"])
                    for cohort in weights
                    if pd.notna(cohorts[cohort]["excluded_unpriced_tokens"])
                ),
                default=pd.NA,
            ),
            "pricing_join_status": "fixed_workload_from_realized_cohorts",
        }
    )
    return row
