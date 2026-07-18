from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from artificial_analysis_data.countries import artificial_analysis_country_label
from openrouter_revenue import build_provider_revenue_estimates


DATASET_ID = "market_pulse_daily"


def _read(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    try:
        return pd.read_parquet(path, columns=columns)
    except (KeyError, ValueError):
        # Transitional files can predate a newly projected column. Reading the
        # file once and intersecting is still bounded because each source here
        # is already a compact gold table, never a raw/detail dataset.
        frame = pd.read_parquet(path)
        return frame.reindex(columns=columns)


def _latest_row(frame: pd.DataFrame, date_column: str) -> pd.Series | None:
    if frame.empty or date_column not in frame.columns:
        return None
    dated = frame[frame[date_column].notna()].copy()
    if dated.empty:
        return None
    dated[date_column] = dated[date_column].astype(str)
    return dated.sort_values(date_column).iloc[-1]


def _value(row: pd.Series | None, column: str) -> Any:
    if row is None or column not in row.index or pd.isna(row[column]):
        return None
    return row[column]


OVERVIEW_SIGNAL_COLUMNS = [
    "dataset_id",
    "signal_id",
    "signal_label",
    "signal_date",
    "time_grain",
    "value",
    "unit",
    "detail_label",
    "source_dataset",
    "source_url",
    "is_complete",
    "source_run_id",
    "scraped_at",
]


def _signal_rows(
    frame: pd.DataFrame,
    *,
    signal_id: str,
    signal_label: str,
    date_column: str,
    value_column: str,
    unit: str,
    time_grain: str,
    source_dataset: str,
    run_id: str,
    scraped_at: str,
    detail_column: str | None = None,
    complete_column: str | None = None,
) -> list[dict[str, Any]]:
    if frame.empty or not {date_column, value_column}.issubset(frame.columns):
        return []
    rows: list[dict[str, Any]] = []
    for _, item in frame.iterrows():
        signal_date = pd.to_datetime(item.get(date_column), errors="coerce")
        value = pd.to_numeric(pd.Series([item.get(value_column)]), errors="coerce").iloc[0]
        if pd.isna(signal_date) or pd.isna(value):
            continue
        source_url = item.get("source_url")
        rows.append(
            {
                "dataset_id": "overview_signal_series",
                "signal_id": signal_id,
                "signal_label": signal_label,
                "signal_date": signal_date.date().isoformat(),
                "time_grain": time_grain,
                "value": float(value),
                "unit": unit,
                "detail_label": item.get(detail_column) if detail_column else None,
                "source_dataset": source_dataset,
                "source_url": source_url if pd.notna(source_url) else None,
                "is_complete": bool(item.get(complete_column, True)) if complete_column else True,
                "source_run_id": run_id,
                "scraped_at": scraped_at,
            }
        )
    return rows


def build_overview_signal_series(base_dir: Path, *, run_id: str, scraped_at: str) -> pd.DataFrame:
    """Build compact histories for the landing page without loading full dashboard domains."""
    normalized = base_dir / "data" / "normalized"
    rows: list[dict[str, Any]] = []

    rankings = _read(
        normalized / "openrouter_official" / "official_model_rankings_daily.parquet",
        ["usage_date", "total_tokens", "source_url"],
    )
    latest_completed_openrouter_date: str | None = None
    if not rankings.empty:
        rankings["total_tokens"] = pd.to_numeric(rankings["total_tokens"], errors="coerce").fillna(0.0)
        official_daily = (
            rankings.groupby("usage_date", as_index=False)
            .agg(value=("total_tokens", "sum"), source_url=("source_url", "last"))
            .sort_values("usage_date")
        )
        latest_completed_openrouter_date = str(official_daily["usage_date"].astype(str).max())
        rows.extend(
            _signal_rows(
                official_daily,
                signal_id="openrouter_full_market_tokens",
                signal_label="OpenRouter Full-Market Tokens",
                date_column="usage_date",
                value_column="value",
                unit="tokens",
                time_grain="day",
                source_dataset="official_model_rankings_daily",
                run_id=run_id,
                scraped_at=scraped_at,
            )
        )

    provider_path = normalized / "openrouter" / "provider_daily_activity.parquet"
    if provider_path.exists():
        activity = _read(
            provider_path,
            [
                "usage_date",
                "entity_id",
                "entity_name",
                "model_permaslug",
                "total_tokens",
                "prompt_tokens",
                "completion_tokens",
                "reasoning_tokens",
            ],
        )
        pricing = _read(
            normalized / "compute_availability" / "raw_openrouter_models.parquet",
            [
                "model_id",
                "canonical_slug",
                "provider_prefix",
                "snapshot_ts",
                "pricing_prompt",
                "pricing_completion",
            ],
        )
        if not activity.empty:
            activity["total_tokens"] = pd.to_numeric(activity["total_tokens"], errors="coerce").fillna(0.0)
            tracked_daily = activity.groupby("usage_date", as_index=False).agg(value=("total_tokens", "sum"))
            tracked_daily["source_url"] = "derived://provider-daily-activity"
            tracked_daily["is_complete"] = (
                tracked_daily["usage_date"].astype(str) <= latest_completed_openrouter_date
                if latest_completed_openrouter_date
                else True
            )
            rows.extend(
                _signal_rows(
                    tracked_daily,
                    signal_id="openrouter_tracked_tokens",
                    signal_label="Tracked-Provider Tokens",
                    date_column="usage_date",
                    value_column="value",
                    unit="tokens",
                    time_grain="day",
                    source_dataset="provider_daily_activity",
                    run_id=run_id,
                    scraped_at=scraped_at,
                    complete_column="is_complete",
                )
            )

            estimates = build_provider_revenue_estimates(activity, pricing)
            if not estimates.empty:
                estimates["estimated_revenue"] = pd.to_numeric(estimates["estimated_revenue"], errors="coerce")
                revenue_daily = (
                    estimates.groupby("usage_date", as_index=False)["estimated_revenue"]
                    .sum(min_count=1)
                    .dropna(subset=["estimated_revenue"])
                    .sort_values("usage_date")
                )
                first_pricing_date = pd.to_datetime(pricing["snapshot_ts"], errors="coerce", utc=True).min()
                first_pricing_day = None if pd.isna(first_pricing_date) else first_pricing_date.strftime("%Y-%m-%d")
                revenue_daily["pricing_mode"] = "as_of_pricing"
                if first_pricing_day is not None:
                    revenue_daily.loc[
                        revenue_daily["usage_date"].astype(str) < first_pricing_day,
                        "pricing_mode",
                    ] = "backcast_earliest_pricing"
                revenue_daily["source_url"] = "derived://provider-revenue-estimates"
                revenue_daily["is_complete"] = (
                    revenue_daily["usage_date"].astype(str) <= latest_completed_openrouter_date
                    if latest_completed_openrouter_date
                    else True
                )
                rows.extend(
                    _signal_rows(
                        revenue_daily,
                        signal_id="openrouter_estimated_revenue",
                        signal_label="Estimated OpenRouter Revenue",
                        date_column="usage_date",
                        value_column="estimated_revenue",
                        unit="usd",
                        time_grain="day",
                        source_dataset="provider_revenue_estimates",
                        run_id=run_id,
                        scraped_at=scraped_at,
                        detail_column="pricing_mode",
                        complete_column="is_complete",
                    )
                )

    ppi = _read(
        normalized / "semiconductor_memory" / "fred_semiconductor_ppi_monthly.parquet",
        ["month", "fred_ppi_value", "fred_ppi_3m_trend", "source_url"],
    )
    for signal_id, label, column in (
        ("ai_demand_ppi", "AI Demand PPI", "fred_ppi_value"),
        ("ai_demand_ppi_3m_trend", "AI Demand PPI 3M Trend", "fred_ppi_3m_trend"),
    ):
        rows.extend(
            _signal_rows(
                ppi,
                signal_id=signal_id,
                signal_label=label,
                date_column="month",
                value_column=column,
                unit="index",
                time_grain="month",
                source_dataset="fred_semiconductor_ppi_monthly",
                run_id=run_id,
                scraped_at=scraped_at,
            )
        )

    ramp = _read(
        normalized / "ramp" / "ramp_ai_adoption_overall.parquet",
        ["date_month", "adoption_rate_pct", "source_url"],
    )
    rows.extend(
        _signal_rows(
            ramp,
            signal_id="ramp_ai_adoption",
            signal_label="Business AI Adoption",
            date_column="date_month",
            value_column="adoption_rate_pct",
            unit="percent",
            time_grain="month",
            source_dataset="ramp_ai_adoption_overall",
            run_id=run_id,
            scraped_at=scraped_at,
        )
    )

    pepm = _read(
        normalized / "ramp" / "ramp_ai_pepm_spend.parquet",
        ["date_month", "median_pepm", "source_url"],
    )
    rows.extend(
        _signal_rows(
            pepm,
            signal_id="ramp_ai_median_pepm",
            signal_label="Median AI Spend per Employee",
            date_column="date_month",
            value_column="median_pepm",
            unit="usd_per_employee_month",
            time_grain="month",
            source_dataset="ramp_ai_pepm_spend",
            run_id=run_id,
            scraped_at=scraped_at,
        )
    )

    models = _read(
        normalized / "artificial_analysis" / "artificial_analysis_models_daily.parquet",
        [
            "model_id",
            "model_name",
            "creator_name",
            "creator_slug",
            "creator_country",
            "release_date",
            "intelligence_index",
            "source_url",
        ],
    )
    if not models.empty:
        models["release_date"] = pd.to_datetime(models["release_date"], errors="coerce")
        models["intelligence_index"] = pd.to_numeric(models["intelligence_index"], errors="coerce")
        models = models.dropna(subset=["release_date", "intelligence_index"]).copy()
        models["detail_label"] = models["model_name"].astype(str) + " · " + models["creator_name"].astype(str)
        daily_frontier = models.loc[models.groupby("release_date")["intelligence_index"].idxmax()].sort_values("release_date")
        daily_frontier = daily_frontier.loc[
            daily_frontier["intelligence_index"].eq(daily_frontier["intelligence_index"].cummax())
        ].copy()
        rows.extend(
            _signal_rows(
                daily_frontier,
                signal_id="frontier_intelligence",
                signal_label="Frontier Intelligence",
                date_column="release_date",
                value_column="intelligence_index",
                unit="index",
                time_grain="release",
                source_dataset="artificial_analysis_models_daily",
                run_id=run_id,
                scraped_at=scraped_at,
                detail_column="detail_label",
            )
        )
        models["country_label"] = models.apply(
            lambda item: artificial_analysis_country_label(
                creator_country=item.get("creator_country"),
                creator_slug=item.get("creator_slug"),
            ),
            axis=1,
        )
        country_signal_ids = {
            "United States": "frontier_intelligence_us",
            "China": "frontier_intelligence_china",
        }
        for country_label, signal_id in country_signal_ids.items():
            country_models = models[models["country_label"].eq(country_label)].copy()
            if country_models.empty:
                continue
            country_daily = country_models.loc[
                country_models.groupby("release_date")["intelligence_index"].idxmax()
            ].sort_values("release_date")
            country_frontier = country_daily.loc[
                country_daily["intelligence_index"].eq(country_daily["intelligence_index"].cummax())
            ].copy()
            rows.extend(
                _signal_rows(
                    country_frontier,
                    signal_id=signal_id,
                    signal_label=f"{country_label} Frontier Intelligence",
                    date_column="release_date",
                    value_column="intelligence_index",
                    unit="index",
                    time_grain="release",
                    source_dataset="artificial_analysis_models_daily",
                    run_id=run_id,
                    scraped_at=scraped_at,
                    detail_column="detail_label",
                )
            )

    momentum = _read(
        normalized / "provider_adoption" / "provider_momentum_daily.parquet",
        ["provider", "provider_display_name", "momentum_score", "scraped_at", "source_url"],
    )
    if not momentum.empty:
        momentum["signal_date"] = momentum["scraped_at"].astype(str).str[:10]
        momentum["momentum_score"] = pd.to_numeric(momentum["momentum_score"], errors="coerce")
        momentum = momentum.dropna(subset=["momentum_score"]).sort_values("scraped_at")
        momentum = momentum.drop_duplicates(["signal_date", "provider"], keep="last")
        leaders = momentum.loc[momentum.groupby("signal_date")["momentum_score"].idxmax()].copy()
        leaders["detail_label"] = leaders["provider_display_name"].fillna(leaders["provider"])
        rows.extend(
            _signal_rows(
                leaders,
                signal_id="developer_momentum_leader",
                signal_label="Developer Momentum Leader",
                date_column="signal_date",
                value_column="momentum_score",
                unit="score",
                time_grain="day",
                source_dataset="provider_momentum_daily",
                run_id=run_id,
                scraped_at=scraped_at,
                detail_column="detail_label",
            )
        )

    incidents = _read(
        normalized / "provider_incidents" / "provider_incidents.parquet",
        ["provider_id", "source_incident_id", "started_at", "published_at", "source_url"],
    )
    if not incidents.empty:
        started = pd.to_datetime(incidents["started_at"], errors="coerce", utc=True)
        published = pd.to_datetime(incidents["published_at"], errors="coerce", utc=True)
        incidents["signal_date"] = started.fillna(published).dt.strftime("%Y-%m-01")
        monthly_incidents = (
            incidents.dropna(subset=["signal_date"])
            .drop_duplicates(["provider_id", "source_incident_id"])
            .groupby("signal_date", as_index=False)
            .agg(value=("source_incident_id", "count"), providers=("provider_id", "nunique"))
        )
        monthly_incidents["detail_label"] = monthly_incidents["providers"].astype(str) + " providers"
        monthly_incidents["source_url"] = "derived://provider-incidents"
        monthly_incidents["is_complete"] = monthly_incidents["signal_date"].str[:7] < scraped_at[:7]
        rows.extend(
            _signal_rows(
                monthly_incidents,
                signal_id="provider_incidents",
                signal_label="Provider Incidents",
                date_column="signal_date",
                value_column="value",
                unit="incidents",
                time_grain="month",
                source_dataset="provider_incidents",
                run_id=run_id,
                scraped_at=scraped_at,
                detail_column="detail_label",
                complete_column="is_complete",
            )
        )

    hiring = _read(
        normalized / "ai_hiring" / "hiring_demand_daily.parquet",
        ["snapshot_date", "company_id", "role_family", "active_postings", "ai_role_postings", "source_url"],
    )
    if not hiring.empty:
        hiring = hiring[hiring["role_family"].astype(str).eq("All roles")].copy()
        for column in ("active_postings", "ai_role_postings"):
            hiring[column] = pd.to_numeric(hiring[column], errors="coerce").fillna(0.0)
        hiring_daily = (
            hiring.groupby("snapshot_date", as_index=False)
            .agg(active_postings=("active_postings", "sum"), ai_role_postings=("ai_role_postings", "sum"))
        )
        hiring_daily["source_url"] = "derived://ai-hiring-demand"
        for signal_id, label, column in (
            ("ai_hiring_active_postings", "Tracked AI-Company Job Postings", "active_postings"),
            ("ai_hiring_ai_roles", "Explicit AI/ML Job Postings", "ai_role_postings"),
        ):
            rows.extend(
                _signal_rows(
                    hiring_daily,
                    signal_id=signal_id,
                    signal_label=label,
                    date_column="snapshot_date",
                    value_column=column,
                    unit="postings",
                    time_grain="day",
                    source_dataset="hiring_demand_daily",
                    run_id=run_id,
                    scraped_at=scraped_at,
                )
            )

    result = pd.DataFrame(rows, columns=OVERVIEW_SIGNAL_COLUMNS)
    if not result.empty:
        result = result.sort_values(["signal_id", "signal_date"]).drop_duplicates(
            ["signal_id", "signal_date"], keep="last"
        ).reset_index(drop=True)
    output_path = normalized / "overview" / "overview_signal_series.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".tmp")
    result.to_parquet(temp_path, index=False)
    temp_path.replace(output_path)
    return result


def build_market_pulse(base_dir: Path, *, run_id: str, scraped_at: str) -> pd.DataFrame:
    """Build a tiny, source-labelled landing-page mart.

    Detailed source tables remain authoritative. This mart intentionally stores
    only daily aggregates and latest cross-dashboard signals so Streamlit can
    render the landing page without loading large research datasets.
    """

    normalized = base_dir / "data" / "normalized"
    overview_root = normalized / "overview"
    overview_root.mkdir(parents=True, exist_ok=True)
    output_path = overview_root / f"{DATASET_ID}.parquet"
    existing = pd.read_parquet(output_path) if output_path.exists() else pd.DataFrame()
    existing_by_date = {
        str(row["pulse_date"]): row.to_dict()
        for _, row in existing.iterrows()
        if pd.notna(row.get("pulse_date"))
    }

    rankings = _read(
        normalized / "openrouter_official" / "official_model_rankings_daily.parquet",
        ["usage_date", "model_permaslug", "total_tokens", "is_other", "source_url", "as_of"],
    )
    if rankings.empty:
        return existing
    rankings["total_tokens"] = pd.to_numeric(rankings["total_tokens"], errors="coerce").fillna(0.0)
    rankings["is_other"] = rankings["is_other"].fillna(False).astype(bool)
    rankings["usage_date"] = rankings["usage_date"].astype(str)

    rows: list[dict[str, Any]] = []
    for usage_date, daily in rankings.groupby("usage_date", sort=True):
        named = daily[~daily["is_other"]].sort_values("total_tokens", ascending=False)
        total_tokens = float(daily["total_tokens"].sum())
        named_tokens = float(named["total_tokens"].sum())
        top = named.iloc[0] if not named.empty else None
        row = existing_by_date.get(str(usage_date), {}).copy()
        row.update(
            {
                "dataset_id": DATASET_ID,
                "pulse_date": str(usage_date),
                "openrouter_total_tokens": total_tokens,
                "openrouter_named_tokens": named_tokens,
                "openrouter_other_tokens": total_tokens - named_tokens,
                "openrouter_other_share_pct": ((total_tokens - named_tokens) / total_tokens * 100.0) if total_tokens else None,
                "openrouter_top_model": None if top is None else top["model_permaslug"],
                "openrouter_top_model_tokens": None if top is None else float(top["total_tokens"]),
                "openrouter_top_model_share_pct": None if top is None or not total_tokens else float(top["total_tokens"]) / total_tokens * 100.0,
                "openrouter_source_url": daily["source_url"].dropna().astype(str).iloc[-1] if daily["source_url"].notna().any() else None,
                "openrouter_as_of": daily["as_of"].dropna().astype(str).iloc[-1] if daily["as_of"].notna().any() else None,
                "source_url": "https://openrouter.ai/api/v1/datasets/rankings-daily",
                "source_run_id": run_id,
                "scraped_at": scraped_at,
            }
        )
        rows.append(row)

    latest = rows[-1]
    latest_date = datetime.fromisoformat(str(latest["pulse_date"])).replace(tzinfo=timezone.utc)

    catalog_path = normalized / "compute_availability" / "raw_openrouter_models_current.parquet"
    if not catalog_path.exists():
        catalog_path = normalized / "compute_availability" / "raw_openrouter_models.parquet"
    catalog = _read(
        catalog_path,
        ["model_id", "created_at", "snapshot_ts", "source_url"],
    )
    if not catalog.empty:
        if "snapshot_ts" in catalog.columns and catalog["snapshot_ts"].notna().any():
            current_snapshot = catalog["snapshot_ts"].astype(str).max()
            catalog = catalog[catalog["snapshot_ts"].astype(str) == current_snapshot].copy()
        catalog = catalog.drop_duplicates("model_id")
        created = pd.to_datetime(pd.to_numeric(catalog["created_at"], errors="coerce"), unit="s", utc=True, errors="coerce")
        latest.update(
            {
                "catalog_model_count": int(catalog["model_id"].nunique()),
                "catalog_models_added_30d": int(((created >= latest_date - timedelta(days=29)) & (created <= latest_date + timedelta(days=1))).sum()),
                "catalog_as_of": catalog["snapshot_ts"].dropna().astype(str).max() if catalog["snapshot_ts"].notna().any() else None,
                "catalog_source_url": catalog["source_url"].dropna().astype(str).iloc[-1] if catalog["source_url"].notna().any() else None,
            }
        )

    providers = _read(
        normalized / "openrouter_official" / "official_providers.parquet",
        ["snapshot_date", "provider_slug"],
    )
    if not providers.empty:
        provider_date = providers["snapshot_date"].astype(str).max()
        latest["official_provider_count"] = int(
            providers[providers["snapshot_date"].astype(str) == provider_date]["provider_slug"].nunique()
        )
        latest["official_provider_as_of"] = provider_date

    apps = _read(
        normalized / "openrouter_official" / "official_app_rankings.parquet",
        ["snapshot_date", "ranking_type", "app_name", "rank", "total_tokens", "total_requests", "source_url"],
    )
    popular = apps[apps["ranking_type"].astype(str) == "popular"].copy() if not apps.empty else pd.DataFrame()
    if not popular.empty:
        app_date = popular["snapshot_date"].astype(str).max()
        app_latest = popular[popular["snapshot_date"].astype(str) == app_date].sort_values("rank").iloc[0]
        latest.update(
            {
                "top_app": _value(app_latest, "app_name"),
                "top_app_tokens": _value(app_latest, "total_tokens"),
                "top_app_requests": _value(app_latest, "total_requests"),
                "top_app_as_of": app_date,
                "top_app_source_url": _value(app_latest, "source_url"),
            }
        )

    tasks = _read(
        normalized / "openrouter_official" / "official_task_classifications.parquet",
        ["snapshot_date", "window_days", "display_name", "tag", "usage_share", "source_url"],
    )
    if not tasks.empty:
        task_date = tasks["snapshot_date"].astype(str).max()
        task_latest = tasks[tasks["snapshot_date"].astype(str) == task_date].copy()
        task_latest["usage_share"] = pd.to_numeric(task_latest["usage_share"], errors="coerce")
        task_top = task_latest.sort_values("usage_share", ascending=False).iloc[0]
        latest.update(
            {
                "top_task": _value(task_top, "display_name") or _value(task_top, "tag"),
                "top_task_share_pct": float(task_top["usage_share"]) * 100.0,
                "top_task_window_days": _value(task_top, "window_days"),
                "top_task_as_of": task_date,
                "top_task_source_url": _value(task_top, "source_url"),
            }
        )

    ramp = _read(
        normalized / "ramp" / "ramp_ai_adoption_overall.parquet",
        ["date_month", "adoption_rate_pct", "mom_change_pp", "yoy_change_pp", "source_url"],
    )
    ramp_latest = _latest_row(ramp, "date_month")
    latest.update(
        {
            "ramp_as_of": _value(ramp_latest, "date_month"),
            "ramp_ai_adoption_pct": _value(ramp_latest, "adoption_rate_pct"),
            "ramp_ai_adoption_mom_pp": _value(ramp_latest, "mom_change_pp"),
            "ramp_ai_adoption_yoy_pp": _value(ramp_latest, "yoy_change_pp"),
            "ramp_source_url": _value(ramp_latest, "source_url"),
        }
    )

    ppi = _read(
        normalized / "semiconductor_memory" / "fred_semiconductor_ppi_monthly.parquet",
        ["month", "fred_ppi_value", "fred_ppi_mom_pct", "fred_ppi_3m_trend", "source_url"],
    )
    ppi_latest = _latest_row(ppi, "month")
    latest.update(
        {
            "semiconductor_as_of": _value(ppi_latest, "month"),
            "ai_demand_ppi": _value(ppi_latest, "fred_ppi_value"),
            "ai_demand_ppi_mom_pct": _value(ppi_latest, "fred_ppi_mom_pct"),
            "ai_demand_ppi_3m_trend": _value(ppi_latest, "fred_ppi_3m_trend"),
            "semiconductor_source_url": _value(ppi_latest, "source_url"),
        }
    )

    momentum = _read(
        normalized / "provider_adoption" / "provider_momentum_daily.parquet",
        ["signal_date", "provider", "provider_display_name", "momentum_score", "source_url"],
    )
    if not momentum.empty:
        momentum_date = momentum["signal_date"].dropna().astype(str).max()
        momentum_latest = momentum[momentum["signal_date"].astype(str) == momentum_date].copy()
        momentum_latest["momentum_score"] = pd.to_numeric(momentum_latest["momentum_score"], errors="coerce")
        momentum_top = momentum_latest.sort_values("momentum_score", ascending=False).iloc[0]
        latest.update(
            {
                "momentum_provider": _value(momentum_top, "provider_display_name") or _value(momentum_top, "provider"),
                "momentum_score": _value(momentum_top, "momentum_score"),
                "momentum_as_of": momentum_date,
                "momentum_source_url": _value(momentum_top, "source_url"),
            }
        )

    analysis = _read(
        normalized / "artificial_analysis" / "artificial_analysis_models_daily.parquet",
        ["as_of_date", "model_name", "creator_name", "intelligence_index", "price_1m_blended_3_to_1", "source_url"],
    )
    if not analysis.empty:
        analysis_date = analysis["as_of_date"].dropna().astype(str).max()
        analysis_latest = analysis[analysis["as_of_date"].astype(str) == analysis_date].copy()
        analysis_latest["intelligence_index"] = pd.to_numeric(analysis_latest["intelligence_index"], errors="coerce")
        frontier = analysis_latest.sort_values("intelligence_index", ascending=False).iloc[0]
        latest.update(
            {
                "frontier_model": _value(frontier, "model_name"),
                "frontier_creator": _value(frontier, "creator_name"),
                "frontier_intelligence_index": _value(frontier, "intelligence_index"),
                "frontier_price_1m": _value(frontier, "price_1m_blended_3_to_1"),
                "frontier_as_of": analysis_date,
                "frontier_source_url": _value(frontier, "source_url"),
            }
        )

    result = pd.DataFrame(rows).sort_values("pulse_date").reset_index(drop=True)
    temp_path = output_path.with_suffix(".tmp")
    result.to_parquet(temp_path, index=False)
    temp_path.replace(output_path)
    return result
