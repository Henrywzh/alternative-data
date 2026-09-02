"""Sino Land forecast-input contract.

This module is the hand-off between the issuer facts layer and a future
earnings model.  It intentionally does *not* fit a forecast.  The returned
long-form panel keeps the following evidence layers separate:

* official group/segment facts (reported context, generally not Hong Kong
  only);
* the interim Hong Kong external-revenue control (the reports disclose this
  geography separately for H1, but not a complete annual Hong Kong segment);
* the research-only SRPE contract-to-handover scenarios; and
* the sibling ``financial-data`` actual/consensus snapshots, which are not
  promoted to point-in-time clean inputs when announcement dates are absent.

The explicit eligibility field is the important part of this contract.  A
future model should filter on it instead of relying on a human remembering
which rows are global, JV-inclusive, research-only, or current snapshots.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import uuid

import pandas as pd

from .shkp_financial_model import FINANCIAL_DATA_DB_PATH
from .sino_land_financial_model import (
    ACTUALS_DATASET,
    CONSENSUS_DATASET,
    OFFICIAL_FACT_DATASET,
    SINO_LAND_TICKER,
    build_sino_land_financial_facts,
    load_sino_land_consensus,
    load_sino_land_financial_data_actuals,
)
from .sino_residential_bridge import SCHEDULE_DATASET
from .storage import load_latest_normalized, save_normalized_dataset


FORECAST_INPUT_DATASET = "sino_land_forecast_inputs"
FORECAST_INPUT_QUALITY_DATASET = "sino_land_forecast_input_quality"
FORECAST_INPUT_SELECTION_DATASET = "sino_land_forecast_input_selection"
H1_BASELINE_DATASET = "sino_land_h1_annualisation_baseline"
HK_SCOPE_PROXY_DATASET = "sino_land_hk_scope_proxy_scenario"

SINO_FORECAST_INPUT_COLUMNS = [
    "input_id",
    "ticker",
    "component",
    "metric",
    "value",
    "unit",
    "currency",
    "period_start",
    "period_end",
    "period_type",
    "geography_scope",
    "attribution_scope",
    "source_dataset",
    "source_fact_ids",
    "availability_date",
    "availability_quality",
    "model_eligibility",
    "research_only",
    "coverage_status",
    "caveat",
]

SINO_FORECAST_INPUT_QUALITY_COLUMNS = [
    "quality_id",
    "ticker",
    "check_name",
    "metric",
    "observed_value",
    "threshold",
    "status",
    "model_use",
    "caveat",
]

SINO_FORECAST_INPUT_SELECTION_COLUMNS = [
    "selection_id",
    "input_id",
    "ticker",
    "selection_bucket",
    "include_hk_core_control",
    "include_group_context",
    "include_scenario",
    "include_research_scenario",
    "include_pit_backtest",
    "selection_reason",
]

SINO_H1_BASELINE_COLUMNS = [
    "baseline_id",
    "ticker",
    "target_period_end",
    "component",
    "metric",
    "h1_actual_value_hkd_m",
    "annualised_value_hkd_m",
    "unit",
    "currency",
    "geography_scope",
    "attribution_scope",
    "source_dataset",
    "source_fact_ids",
    "availability_date",
    "availability_quality",
    "model_use",
    "research_only",
    "comparability_status",
    "caveat",
]

SINO_HK_SCOPE_PROXY_COLUMNS = [
    "proxy_id",
    "ticker",
    "fiscal_year_end",
    "metric",
    "combined_geography_value_hkd_m",
    "observed_h1_share_low_pct",
    "observed_h1_share_base_pct",
    "observed_h1_share_high_pct",
    "hk_proxy_low_hkd_m",
    "hk_proxy_base_hkd_m",
    "hk_proxy_high_hkd_m",
    "share_observation_periods",
    "unit",
    "currency",
    "source_dataset",
    "source_fact_ids",
    "model_use",
    "research_only",
    "coverage_status",
    "caveat",
]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    value = str(value).strip()
    return (
        None
        if not value or value.casefold() in {"nan", "nat", "none", "null"}
        else value
    )


def _date(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        # Keep an explicit release timestamp if it is not parseable rather
        # than silently deleting provenance.
        return text
    return parsed.strftime("%Y-%m-%d")


def _source_ids(value: Any) -> str:
    text = _text(value)
    if text is None:
        return "[]"
    return json.dumps([text], ensure_ascii=False)


def _input_id(*parts: Any) -> str:
    clean = [str(part).strip().lower().replace(" ", "_") for part in parts]
    return "sino_land_input:" + ":".join(clean)


def _period_start_from_end(
    period_end: str | None, period_type: str | None
) -> str | None:
    if not period_end:
        return None
    parsed = pd.to_datetime(period_end, errors="coerce")
    if pd.isna(parsed):
        return None
    if str(period_type or "").casefold() == "annual":
        return (parsed - pd.DateOffset(years=1) + pd.DateOffset(days=1)).strftime(
            "%Y-%m-%d"
        )
    return None


def _fiscal_year_end(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    fiscal_year = int(parsed.year) + (1 if int(parsed.month) > 6 else 0)
    return f"{fiscal_year}-06-30"


def _row(
    *,
    component: str,
    metric: str,
    value: Any,
    unit: str | None,
    currency: str | None,
    period_start: Any,
    period_end: Any,
    period_type: Any,
    geography_scope: str,
    attribution_scope: str,
    source_dataset: str,
    source_fact_ids: Any,
    availability_date: Any,
    availability_quality: str,
    model_eligibility: str,
    research_only: bool,
    coverage_status: str,
    caveat: str,
    input_suffix: Any | None = None,
) -> dict[str, Any]:
    period_end_text = _date(period_end)
    suffix = input_suffix if input_suffix is not None else source_fact_ids
    return {
        "input_id": _input_id(
            source_dataset, component, metric, period_end_text or "unknown", suffix
        ),
        "ticker": SINO_LAND_TICKER,
        "component": component,
        "metric": metric,
        "value": value,
        "unit": unit,
        "currency": currency,
        "period_start": _date(period_start),
        "period_end": period_end_text,
        "period_type": _text(period_type),
        "geography_scope": geography_scope,
        "attribution_scope": attribution_scope,
        "source_dataset": source_dataset,
        "source_fact_ids": (
            source_fact_ids
            if isinstance(source_fact_ids, str)
            else json.dumps(source_fact_ids or [], ensure_ascii=False)
        ),
        "availability_date": _date(availability_date),
        "availability_quality": availability_quality,
        "model_eligibility": model_eligibility,
        "research_only": bool(research_only),
        "coverage_status": coverage_status,
        "caveat": caveat,
    }


def _official_component(row: pd.Series) -> str:
    group = str(row.get("fact_group") or "")
    segment = str(row.get("segment") or "")
    metric = str(row.get("metric") or "")
    if group == "geographical_revenue":
        return (
            "hk_scope_controls"
            if str(row.get("geography_scope") or "") == "hong_kong"
            else "geography_context"
        )
    if group == "group_summary":
        return "group_context"
    if (
        segment == "property_sales"
        or "property_sales" in metric
        or metric == "sales_of_properties"
    ):
        # The issuer's property-sales segment is not a Hong Kong-residential-
        # only disclosure; keep the neutral label until an asset/type bridge
        # is available.
        return "property_sales_context"
    if segment == "property_rental" or "rental" in metric or "occupancy" in metric:
        return "commercial_rental_context"
    if segment == "hotel_operations" or "hotel" in metric:
        return "hotel_context"
    return "other_group_context"


def _official_eligibility(row: pd.Series, component: str) -> tuple[str, str, bool]:
    geography = str(row.get("geography_scope") or "")
    group = str(row.get("fact_group") or "")
    if group == "geographical_revenue" and geography == "hong_kong":
        return (
            "eligible_as_hk_scope_control",
            "h1_hk_geography_observed",
            False,
        )
    if component in {
        "property_sales_context",
        "commercial_rental_context",
        "hotel_context",
    }:
        return (
            "scenario_only_until_hk_scope_bridge",
            "observed_global_or_jv_scope",
            False,
        )
    return (
        "reported_group_context_only",
        "observed_official_group_fact",
        False,
    )


def build_sino_land_official_forecast_inputs(
    official_facts: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Convert official facts into explicitly tagged model inputs."""
    facts = (
        official_facts.copy()
        if official_facts is not None
        else build_sino_land_financial_facts()
    )
    if facts.empty:
        return pd.DataFrame(columns=SINO_FORECAST_INPUT_COLUMNS)
    rows: list[dict[str, Any]] = []
    for _, fact in facts.iterrows():
        component = _official_component(fact)
        eligibility, coverage, research_only = _official_eligibility(fact, component)
        geography = _text(fact.get("geography_scope")) or "unknown_scope"
        source_ids = _source_ids(fact.get("fact_id"))
        rows.append(
            _row(
                component=component,
                metric=str(fact.get("metric") or "unknown_metric"),
                value=fact.get("value"),
                unit=_text(fact.get("unit")),
                currency=_text(fact.get("currency")),
                period_start=fact.get("period_start"),
                period_end=fact.get("period_end"),
                period_type=fact.get("period_type"),
                geography_scope=geography,
                attribution_scope=_text(fact.get("attribution_scope"))
                or "unknown_attribution_scope",
                source_dataset=OFFICIAL_FACT_DATASET,
                source_fact_ids=source_ids,
                availability_date=fact.get("available_at"),
                availability_quality=_text(fact.get("availability_quality"))
                or "unknown",
                model_eligibility=eligibility,
                research_only=research_only,
                coverage_status=coverage,
                caveat=_text(fact.get("caveat"))
                or "Official fact; retain source semantics.",
                input_suffix=fact.get("fact_id"),
            )
        )
    return pd.DataFrame(rows, columns=SINO_FORECAST_INPUT_COLUMNS)


def build_sino_land_hk_scope_controls(
    official_facts: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build direct H1 Hong Kong revenue controls and derived H1 share.

    The source reports Hong Kong, Mainland China and Singapore external
    revenue in the interim note.  It does not provide a complete annual
    Hong Kong-only segment in the current fact layer, so the derived share is
    explicitly labelled H1-only and is never annualised here.
    """
    facts = (
        official_facts.copy()
        if official_facts is not None
        else build_sino_land_financial_facts()
    )
    if facts.empty:
        return pd.DataFrame(columns=SINO_FORECAST_INPUT_COLUMNS)
    geographic = facts.loc[
        facts.get("fact_group", pd.Series(index=facts.index)).eq("geographical_revenue")
        & facts.get("geography_scope", pd.Series(index=facts.index)).eq("hong_kong")
    ].copy()
    consolidated = facts.loc[
        facts.get("metric", pd.Series(index=facts.index)).eq("consolidated_revenue")
    ].copy()
    rows: list[dict[str, Any]] = []
    for _, fact in geographic.iterrows():
        period_end = fact.get("period_end")
        rows.append(
            _row(
                component="hk_scope_controls",
                metric="hong_kong_consolidated_external_revenue",
                value=fact.get("value"),
                unit=_text(fact.get("unit")),
                currency=_text(fact.get("currency")),
                period_start=fact.get("period_start"),
                period_end=period_end,
                period_type=fact.get("period_type"),
                geography_scope="hong_kong",
                attribution_scope="consolidated_external_revenue",
                source_dataset=OFFICIAL_FACT_DATASET,
                source_fact_ids=_source_ids(fact.get("fact_id")),
                availability_date=fact.get("available_at"),
                availability_quality=_text(fact.get("availability_quality"))
                or "unknown",
                model_eligibility="eligible_as_hk_scope_control",
                research_only=False,
                coverage_status="h1_hk_geography_observed",
                caveat="Direct Hong Kong external revenue from the interim geography note; H1 only, not an annual HK segment.",
                input_suffix=f"hk_revenue:{fact.get('fact_id')}",
            )
        )
        matching = (
            consolidated.loc[consolidated["period_end"].eq(period_end)]
            if "period_end" in consolidated
            else pd.DataFrame()
        )
        if matching.empty:
            continue
        total = pd.to_numeric(matching.iloc[0].get("value"), errors="coerce")
        hk_value = pd.to_numeric(fact.get("value"), errors="coerce")
        if pd.isna(total) or pd.isna(hk_value) or float(total) == 0:
            continue
        fact_ids = [fact.get("fact_id"), matching.iloc[0].get("fact_id")]
        rows.append(
            _row(
                component="hk_scope_controls",
                metric="hong_kong_external_revenue_share_of_consolidated",
                value=float(hk_value) / float(total) * 100.0,
                unit="pct",
                currency=None,
                period_start=fact.get("period_start"),
                period_end=period_end,
                period_type=fact.get("period_type"),
                geography_scope="hong_kong_vs_group_consolidated",
                attribution_scope="consolidated_external_revenue",
                source_dataset=OFFICIAL_FACT_DATASET,
                source_fact_ids=json.dumps(fact_ids, ensure_ascii=False),
                availability_date=fact.get("available_at"),
                availability_quality=_text(fact.get("availability_quality"))
                or "unknown",
                model_eligibility="eligible_as_hk_scope_control",
                research_only=False,
                coverage_status="h1_derived_hk_share_only",
                caveat="Derived as Hong Kong external revenue divided by consolidated external revenue; H1 only, not an annual measure and not a segment-attributable revenue share.",
                input_suffix=f"hk_share:{period_end}",
            )
        )
    return pd.DataFrame(rows, columns=SINO_FORECAST_INPUT_COLUMNS)


def build_sino_land_residential_bridge_inputs(
    bridge_schedule: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Aggregate the SRPE contract cohort into FY scenario inputs.

    These are not accounting revenue.  They are low/base/high contract-value
    timing scenarios, retained only to inform a later residential handover
    forecast and to expose coverage gaps.
    """
    schedule = (
        bridge_schedule.copy()
        if bridge_schedule is not None
        else load_latest_normalized(SCHEDULE_DATASET)
    )
    if schedule.empty:
        return pd.DataFrame(columns=SINO_FORECAST_INPUT_COLUMNS)
    rows: list[dict[str, Any]] = []
    for scenario in ("low", "base", "high"):
        period_col = f"recognized_period_{scenario}"
        value_col = f"attributable_contract_value_{scenario}_hkd"
        if period_col not in schedule or value_col not in schedule:
            continue
        temp = schedule[[period_col, value_col]].copy()
        temp[period_col] = pd.to_datetime(temp[period_col], errors="coerce")
        temp[value_col] = pd.to_numeric(temp[value_col], errors="coerce")
        temp["fiscal_year_end"] = temp[period_col].map(_fiscal_year_end)
        temp = temp.dropna(subset=["fiscal_year_end", value_col])
        if temp.empty:
            continue
        grouped = temp.groupby("fiscal_year_end", dropna=False)
        for fiscal_year_end, group in grouped:
            value_m = float(group[value_col].sum()) / 1_000_000.0
            source_ids = []
            if "bridge_id" in schedule.columns:
                source_ids = [
                    str(value)
                    for value in schedule.loc[group.index, "bridge_id"]
                    .dropna()
                    .unique()
                ]
            elif "canonical_project_id" in schedule.columns:
                source_ids = [
                    str(value)
                    for value in schedule.loc[group.index, "canonical_project_id"]
                    .dropna()
                    .unique()
                ]
            rows.append(
                _row(
                    component="residential_handover_bridge",
                    metric=f"attributable_contract_value_{scenario}",
                    value=value_m,
                    unit="HKD_m",
                    currency="HKD",
                    period_start=(
                        pd.to_datetime(fiscal_year_end)
                        - pd.DateOffset(years=1)
                        + pd.DateOffset(days=1)
                    ).strftime("%Y-%m-%d"),
                    period_end=fiscal_year_end,
                    period_type="annual",
                    geography_scope="hong_kong_residential_research_schedule",
                    attribution_scope="assumed_stake_scenario_not_accounting_revenue",
                    source_dataset=SCHEDULE_DATASET,
                    source_fact_ids=json.dumps(source_ids, ensure_ascii=False),
                    availability_date=None,
                    availability_quality="latest_normalized_snapshot",
                    model_eligibility="research_only_scenario",
                    research_only=True,
                    coverage_status="cohort_schedule_observed",
                    caveat=f"SRPE contract cohort value under {scenario} stake/lag scenario; not recognized revenue. Coverage is limited to the current bridge snapshot and does not imply zero outside observed cohorts.",
                    input_suffix=f"{scenario}:{fiscal_year_end}",
                )
            )
    return pd.DataFrame(rows, columns=SINO_FORECAST_INPUT_COLUMNS)


def _supplemental_date(row: pd.Series) -> Any:
    for column in (
        "announcement_date",
        "available_at",
        "observation_date",
        "release_date",
        "report_date",
        "source_date",
    ):
        if column in row and _text(row.get(column)) is not None:
            return row.get(column)
    return None


def _restrict_snapshot_to_sino_land(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the fallback scoped to 0083 when a shared snapshot has tickers.

    The normal sibling-DB loaders already apply this filter.  The persisted
    fallback is deliberately defensive because a future normalized snapshot
    could contain more than one issuer even though today's Sino datasets do
    not.
    """
    if frame is None or frame.empty or "ticker" not in frame.columns:
        return frame
    tickers = frame["ticker"].astype("string").str.strip().str.upper()
    return frame.loc[tickers.eq(SINO_LAND_TICKER)].copy()


def build_sino_land_supplemental_inputs(
    frame: pd.DataFrame | None,
    *,
    source_dataset: str,
    component: str,
    snapshot_fallback_note: str | None = None,
) -> pd.DataFrame:
    """Retain vendor actual/consensus rows without pretending they are PIT.

    The sibling repository has intentionally heterogeneous schemas.  This
    adapter only standardises the fields needed by the contract and keeps the
    original row index in the input id; it does not reconcile sources or
    infer missing release dates.
    """
    if frame is None or frame.empty:
        return pd.DataFrame(columns=SINO_FORECAST_INPUT_COLUMNS)
    rows: list[dict[str, Any]] = []
    for index, source_row in frame.reset_index(drop=True).iterrows():
        value = pd.to_numeric(source_row.get("value"), errors="coerce")
        if pd.isna(value):
            continue
        period_end = source_row.get("period_end")
        period_type = source_row.get("period_type")
        source_name = _text(source_row.get("source")) or "sibling_financial_data"
        fallback_quality = (
            "persisted_snapshot_fallback_not_pit_clean"
            if snapshot_fallback_note
            else (
                "not_pit_clean_missing_announcement_date"
                if _text(_supplemental_date(source_row)) is None
                else "vendor_timestamp_not_source_verified"
            )
        )
        fallback_caveat = (
            f" Explicit persisted-snapshot fallback was used because the sibling DB could not be read: {snapshot_fallback_note}."
            if snapshot_fallback_note
            else ""
        )
        rows.append(
            _row(
                component=component,
                metric=_text(source_row.get("metric")) or "unknown_metric",
                value=float(value),
                unit=_text(source_row.get("unit")) or _text(source_row.get("raw_unit")),
                currency=_text(source_row.get("currency")),
                period_start=source_row.get("period_start"),
                period_end=period_end,
                period_type=period_type,
                geography_scope=_text(source_row.get("geography_scope"))
                or "unknown_vendor_scope",
                attribution_scope=_text(source_row.get("attribution_scope"))
                or "unknown_vendor_scope",
                source_dataset=source_dataset,
                source_fact_ids=_source_ids(
                    source_row.get("fact_id") or source_row.get("row_id") or index
                ),
                availability_date=_supplemental_date(source_row),
                availability_quality=fallback_quality,
                model_eligibility="not_pit_clean",
                research_only=False,
                coverage_status="supplemental_snapshot_row",
                caveat=f"Supplemental {source_name} row retained for research; source overlap, accounting scope and original announcement vintage require reconciliation before backtesting.{fallback_caveat}",
                input_suffix=f"{source_dataset}:{index}",
            )
        )
    return pd.DataFrame(rows, columns=SINO_FORECAST_INPUT_COLUMNS)


def build_sino_land_forecast_input_selection(
    panel: pd.DataFrame | None,
) -> pd.DataFrame:
    """Apply the model-boundary rules to every tagged input row.

    This is intentionally a separate table rather than a filtered copy.  A
    future model can join it to the full evidence panel and see why a row was
    included or excluded.  In particular, a global/JV fact may be useful for a
    group scenario while remaining ineligible for the Hong Kong core model.
    """
    frame = panel.copy() if panel is not None else pd.DataFrame()
    if frame.empty:
        return pd.DataFrame(columns=SINO_FORECAST_INPUT_SELECTION_COLUMNS)
    rows: list[dict[str, Any]] = []
    for _, source_row in frame.iterrows():
        eligibility = _text(source_row.get("model_eligibility")) or "unknown"
        research_only = (
            bool(source_row.get("research_only"))
            if pd.notna(source_row.get("research_only"))
            else False
        )
        source_dataset = _text(source_row.get("source_dataset")) or "unknown"
        availability_quality = (
            _text(source_row.get("availability_quality")) or "unknown"
        )
        if research_only or eligibility == "research_only_scenario":
            bucket = "research_only_scenario"
            hk_core = False
            group_context = False
            scenario = False
            research_scenario = True
            reason = "Research-only contract cohort; never accounting revenue or a core target."
        elif eligibility == "eligible_as_hk_scope_control":
            bucket = "hk_core_control"
            hk_core = True
            group_context = False
            scenario = False
            research_scenario = False
            reason = "Direct H1 Hong Kong geography control; not an annual HK segment or component revenue target."
        elif eligibility == "scenario_only_until_hk_scope_bridge":
            bucket = "group_scenario_only"
            hk_core = False
            group_context = False
            scenario = True
            research_scenario = False
            reason = "Global and/or JV-inclusive component fact; usable for a scenario only until an HK scope bridge exists."
        elif eligibility == "not_pit_clean":
            bucket = "current_snapshot_only"
            hk_core = False
            group_context = False
            scenario = True
            research_scenario = False
            reason = "Supplemental snapshot retained for current context; excluded from historical PIT backtests."
        elif eligibility == "reported_group_context_only":
            bucket = "reported_group_context"
            hk_core = False
            group_context = True
            scenario = False
            research_scenario = False
            reason = "Official group context; not a Hong Kong-only component input."
        else:
            bucket = "unclassified"
            hk_core = False
            group_context = False
            scenario = False
            research_scenario = False
            reason = "Unknown eligibility; quarantine until manually classified."

        pit_backtest = bool(
            source_dataset == OFFICIAL_FACT_DATASET
            and availability_quality == "hkex_release_time_verified"
            and not research_only
        )
        if bucket in {
            "research_only_scenario",
            "group_scenario_only",
            "current_snapshot_only",
        }:
            pit_backtest = False
        rows.append(
            {
                "selection_id": _input_id("selection", source_row.get("input_id")),
                "input_id": source_row.get("input_id"),
                "ticker": source_row.get("ticker") or SINO_LAND_TICKER,
                "selection_bucket": bucket,
                "include_hk_core_control": hk_core,
                "include_group_context": group_context,
                "include_scenario": scenario,
                "include_research_scenario": research_scenario,
                "include_pit_backtest": pit_backtest,
                "selection_reason": reason,
            }
        )
    return pd.DataFrame(rows, columns=SINO_FORECAST_INPUT_SELECTION_COLUMNS)


def build_sino_land_h1_annualisation_baseline(
    official_facts: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build the transparent ``2 x H1`` benchmark for the latest H1.

    This is deliberately a benchmark, not a forecast.  It only annualises
    consolidated H1 facts whose period is the latest observed interim period;
    it does not annualise the Hong Kong geography control or mix incomparable
    annual-report business-review numbers into a growth rate.
    """
    facts = (
        official_facts.copy()
        if official_facts is not None
        else build_sino_land_financial_facts()
    )
    if facts.empty:
        return pd.DataFrame(columns=SINO_H1_BASELINE_COLUMNS)
    facts = facts.copy()
    facts["period_end"] = pd.to_datetime(facts["period_end"], errors="coerce")
    interim = facts.loc[
        facts["period_type"].eq("interim")
        & facts["period_end"].notna()
        & facts["unit"].eq("HKD_m")
        & facts["metric"].isin(
            {
                "consolidated_revenue",
                "sales_of_properties",
                "rental_income_operating_leases",
                "hotel_operations_revenue",
                "underlying_profit_attributable",
                "profit_attributable",
            }
        )
    ].copy()
    if interim.empty:
        return pd.DataFrame(columns=SINO_H1_BASELINE_COLUMNS)
    latest_end = interim["period_end"].max()
    interim = interim.loc[interim["period_end"].eq(latest_end)]
    component_by_metric = {
        "consolidated_revenue": "group_context",
        "sales_of_properties": "property_sales_context",
        "rental_income_operating_leases": "commercial_rental_context",
        "hotel_operations_revenue": "hotel_context",
        "underlying_profit_attributable": "group_context",
        "profit_attributable": "group_context",
    }
    rows: list[dict[str, Any]] = []
    target_end = _fiscal_year_end(latest_end) or latest_end.strftime("%Y-%m-%d")
    for _, fact in interim.sort_values("metric").iterrows():
        value = pd.to_numeric(fact.get("value"), errors="coerce")
        if pd.isna(value):
            continue
        source_fact_id = _text(fact.get("fact_id")) or "unknown_fact"
        rows.append(
            {
                "baseline_id": _input_id("h1_baseline", fact.get("metric"), target_end),
                "ticker": SINO_LAND_TICKER,
                "target_period_end": target_end,
                "component": component_by_metric.get(
                    str(fact.get("metric")), "group_context"
                ),
                "metric": fact.get("metric"),
                "h1_actual_value_hkd_m": float(value),
                "annualised_value_hkd_m": float(value) * 2.0,
                "unit": "HKD_m",
                "currency": "HKD",
                "geography_scope": _text(fact.get("geography_scope"))
                or "unknown_scope",
                "attribution_scope": _text(fact.get("attribution_scope"))
                or "unknown_scope",
                "source_dataset": OFFICIAL_FACT_DATASET,
                "source_fact_ids": json.dumps([source_fact_id], ensure_ascii=False),
                "availability_date": _date(fact.get("available_at")),
                "availability_quality": _text(fact.get("availability_quality"))
                or "unknown",
                "model_use": "naive_h1_annualisation_benchmark",
                "research_only": True,
                "comparability_status": "benchmark_only_no_scope_matched_fy_growth",
                "caveat": "2 x latest H1 actual; not a formal forecast. H2 seasonality, project handover timing and scope changes are not modelled, and no FY growth rate is inferred from incomparable annual-report metrics.",
            }
        )
    return pd.DataFrame(rows, columns=SINO_H1_BASELINE_COLUMNS)


def build_sino_land_hk_scope_proxy_scenario(
    official_facts: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Estimate a range for annual HK external revenue from disclosed H1 mix.

    Annual Note 6 reports Mainland China plus Hong Kong together.  The interim
    note separately reports Hong Kong, Mainland China and Singapore, allowing
    a deliberately rough observed-share range.  This function applies the
    minimum/mean/maximum of those H1 shares to the annual combined geography
    *external revenue* only.  It is a research scenario, not a reported HK
    segment and not an attributable/JV revenue allocation.
    """
    facts = (
        official_facts.copy()
        if official_facts is not None
        else build_sino_land_financial_facts()
    )
    if facts.empty:
        return pd.DataFrame(columns=SINO_HK_SCOPE_PROXY_COLUMNS)
    geography = facts.loc[
        facts["fact_group"].eq("geographical_revenue")
        & facts["metric"].eq("consolidated_external_revenue_by_geography")
        & facts["period_type"].eq("interim")
        & facts["geography_scope"].isin({"hong_kong", "chinese_mainland", "singapore"})
    ].copy()
    if geography.empty:
        return pd.DataFrame(columns=SINO_HK_SCOPE_PROXY_COLUMNS)
    pivot = geography.pivot_table(
        index="period_end",
        columns="geography_scope",
        values="value",
        aggfunc="first",
    )
    required_regions = {"hong_kong", "chinese_mainland", "singapore"}
    if not required_regions.issubset(pivot.columns):
        return pd.DataFrame(columns=SINO_HK_SCOPE_PROXY_COLUMNS)
    pivot = pivot.dropna(subset=list(required_regions))
    if pivot.empty:
        return pd.DataFrame(columns=SINO_HK_SCOPE_PROXY_COLUMNS)
    pivot["hk_share_pct"] = (
        pivot["hong_kong"]
        / pivot[["hong_kong", "chinese_mainland", "singapore"]].sum(axis=1)
        * 100.0
    )
    shares = pivot["hk_share_pct"]
    low_share = float(shares.min())
    base_share = float(shares.mean())
    high_share = float(shares.max())
    annual_combined = facts.loc[
        facts["fact_group"].eq("geographical_revenue")
        & facts["metric"].eq("external_revenue_by_geography")
        & facts["period_type"].eq("annual")
        & facts["geography_scope"].eq("mainland_china_and_hong_kong")
    ].copy()
    if annual_combined.empty:
        return pd.DataFrame(columns=SINO_HK_SCOPE_PROXY_COLUMNS)
    periods = [str(value) for value in pivot.index.tolist()]
    h1_source_ids = geography["fact_id"].dropna().astype(str).tolist()
    rows: list[dict[str, Any]] = []
    for _, fact in annual_combined.sort_values("period_end").iterrows():
        combined_value = pd.to_numeric(fact.get("value"), errors="coerce")
        if pd.isna(combined_value):
            continue
        source_ids = h1_source_ids + (
            [_text(fact.get("fact_id"))] if _text(fact.get("fact_id")) else []
        )
        period_end = _date(fact.get("period_end"))
        rows.append(
            {
                "proxy_id": _input_id("hk_scope_proxy", period_end),
                "ticker": SINO_LAND_TICKER,
                "fiscal_year_end": period_end,
                "metric": "consolidated_external_revenue_hk_scope_proxy",
                "combined_geography_value_hkd_m": float(combined_value),
                "observed_h1_share_low_pct": low_share,
                "observed_h1_share_base_pct": base_share,
                "observed_h1_share_high_pct": high_share,
                "hk_proxy_low_hkd_m": float(combined_value) * low_share / 100.0,
                "hk_proxy_base_hkd_m": float(combined_value) * base_share / 100.0,
                "hk_proxy_high_hkd_m": float(combined_value) * high_share / 100.0,
                "share_observation_periods": ",".join(periods),
                "unit": "HKD_m",
                "currency": "HKD",
                "source_dataset": OFFICIAL_FACT_DATASET,
                "source_fact_ids": json.dumps(source_ids, ensure_ascii=False),
                "model_use": "research_only_hk_scope_proxy_scenario",
                "research_only": True,
                "coverage_status": "annual_combined_geography_split_by_two_h1_observations",
                "caveat": "Applied the observed H1 Hong Kong share range to annual Mainland-China-plus-Hong-Kong external revenue. This is not a reported Hong Kong segment, excludes any JV-attributable allocation and is not eligible for the core model or PIT backtest.",
            }
        )
    return pd.DataFrame(rows, columns=SINO_HK_SCOPE_PROXY_COLUMNS)


def build_sino_land_forecast_inputs(
    *,
    official_facts: pd.DataFrame | None = None,
    financial_data_actuals: pd.DataFrame | None = None,
    consensus: pd.DataFrame | None = None,
    bridge_schedule: pd.DataFrame | None = None,
    load_financial_data: bool = True,
    use_persisted_financial_fallback: bool = False,
    db_path: Path = FINANCIAL_DATA_DB_PATH,
) -> dict[str, Any]:
    """Build the tagged forecast-input panel without fitting a model."""
    official = (
        official_facts.copy()
        if official_facts is not None
        else build_sino_land_financial_facts()
    )
    actuals = (
        financial_data_actuals.copy()
        if financial_data_actuals is not None
        else pd.DataFrame()
    )
    consensus_frame = consensus.copy() if consensus is not None else pd.DataFrame()
    fallback_notes: dict[str, str] = {}
    if load_financial_data and financial_data_actuals is None:
        try:
            actuals = load_sino_land_financial_data_actuals(db_path)
        except Exception as exc:
            if not use_persisted_financial_fallback:
                raise
            actuals = _restrict_snapshot_to_sino_land(
                load_latest_normalized(ACTUALS_DATASET)
            )
            fallback_notes[ACTUALS_DATASET] = f"{type(exc).__name__}: {exc}"
    if load_financial_data and consensus is None:
        try:
            consensus_frame = load_sino_land_consensus(db_path)
        except Exception as exc:
            if not use_persisted_financial_fallback:
                raise
            consensus_frame = _restrict_snapshot_to_sino_land(
                load_latest_normalized(CONSENSUS_DATASET)
            )
            fallback_notes[CONSENSUS_DATASET] = f"{type(exc).__name__}: {exc}"
    parts = [
        build_sino_land_official_forecast_inputs(official),
        build_sino_land_hk_scope_controls(official),
        build_sino_land_residential_bridge_inputs(bridge_schedule),
        build_sino_land_supplemental_inputs(
            actuals,
            source_dataset=ACTUALS_DATASET,
            component="financial_data_actuals_snapshot",
            snapshot_fallback_note=fallback_notes.get(ACTUALS_DATASET),
        ),
        build_sino_land_supplemental_inputs(
            consensus_frame,
            source_dataset=CONSENSUS_DATASET,
            component="consensus_snapshot",
            snapshot_fallback_note=fallback_notes.get(CONSENSUS_DATASET),
        ),
    ]
    non_empty_parts = [part for part in parts if part is not None and not part.empty]
    panel = (
        pd.concat(non_empty_parts, ignore_index=True)
        if non_empty_parts
        else pd.DataFrame(columns=SINO_FORECAST_INPUT_COLUMNS)
    )
    if panel.empty:
        panel = pd.DataFrame(columns=SINO_FORECAST_INPUT_COLUMNS)
    else:
        panel = panel.reindex(columns=SINO_FORECAST_INPUT_COLUMNS)
        panel = panel.sort_values(
            ["period_end", "component", "metric", "source_dataset"], na_position="last"
        ).reset_index(drop=True)
    selection = build_sino_land_forecast_input_selection(panel)
    h1_baseline = build_sino_land_h1_annualisation_baseline(official)
    hk_scope_proxy = build_sino_land_hk_scope_proxy_scenario(official)
    quality = build_sino_land_forecast_input_quality(panel)
    return {
        "forecast_inputs": panel,
        "selection": selection,
        "h1_baseline": h1_baseline,
        "hk_scope_proxy": hk_scope_proxy,
        "quality": quality,
        "financial_data_load_status": (
            "persisted_snapshot_fallback_used"
            if fallback_notes
            else (
                "loaded_from_sibling_db" if load_financial_data else "skipped_by_option"
            )
        ),
        "financial_data_fallback_notes": fallback_notes,
    }


def build_sino_land_forecast_input_quality(panel: pd.DataFrame) -> pd.DataFrame:
    """Quality gates for the hand-off contract itself."""
    frame = (
        panel.copy()
        if panel is not None
        else pd.DataFrame(columns=SINO_FORECAST_INPUT_COLUMNS)
    )
    rows: list[dict[str, Any]] = []

    def add(
        name: str,
        metric: str,
        value: Any,
        threshold: Any,
        status: str,
        model_use: str,
        caveat: str,
    ) -> None:
        rows.append(
            {
                "quality_id": _input_id("quality", name, metric),
                "ticker": SINO_LAND_TICKER,
                "check_name": name,
                "metric": metric,
                "observed_value": value,
                "threshold": threshold,
                "status": status,
                "model_use": model_use,
                "caveat": caveat,
            }
        )

    if frame.empty:
        add(
            "non_empty",
            "input_rows",
            0,
            ">0",
            "fail",
            "do_not_use",
            "No tagged forecast inputs were built.",
        )
        return pd.DataFrame(rows, columns=SINO_FORECAST_INPUT_QUALITY_COLUMNS)

    duplicate_count = int(frame["input_id"].duplicated().sum())
    add(
        "duplicate_input_ids",
        "duplicate_rows",
        duplicate_count,
        "0",
        "pass" if duplicate_count == 0 else "fail",
        "do_not_use" if duplicate_count else "eligible_rows_only",
        "Every input row must have a unique deterministic identity.",
    )
    required = [
        "source_dataset",
        "source_fact_ids",
        "model_eligibility",
        "coverage_status",
        "caveat",
    ]
    missing_pct = float(frame[required].isna().any(axis=1).mean() * 100.0)
    add(
        "contract_metadata_completeness",
        "rows_missing_required_metadata_pct",
        missing_pct,
        "0",
        "pass" if missing_pct == 0 else "fail",
        "do_not_use" if missing_pct else "eligible_rows_only",
        "Source identity and eligibility are required for model promotion.",
    )

    hk_controls = frame.loc[frame["component"].eq("hk_scope_controls")]
    add(
        "hk_scope_control_coverage",
        "hk_control_rows",
        int(len(hk_controls)),
        ">0",
        "pass" if len(hk_controls) else "warn",
        "eligible_as_hk_scope_control" if len(hk_controls) else "scope_bridge_missing",
        "Current official facts contain H1 Hong Kong geography controls only; annual HK segment coverage remains a gap.",
    )
    annual_hk = frame.loc[
        frame["geography_scope"].eq("hong_kong") & frame["period_type"].eq("annual")
    ]
    add(
        "annual_hk_scope_gap",
        "annual_hk_rows",
        int(len(annual_hk)),
        ">0",
        "pass" if len(annual_hk) else "warn",
        (
            "eligible_as_hk_scope_control"
            if len(annual_hk)
            else "do_not_use_as_annual_hk_target"
        ),
        "No annual HK-only segment is currently disclosed in this contract; H1 geography rows must not be extrapolated silently.",
    )
    annual_combined = frame.loc[
        frame["geography_scope"].eq("mainland_china_and_hong_kong")
        & frame["period_type"].eq("annual")
    ]
    add(
        "annual_combined_geography_coverage",
        "mainland_china_and_hong_kong_rows",
        int(len(annual_combined)),
        ">0",
        "pass" if len(annual_combined) else "warn",
        "geography_context" if len(annual_combined) else "combined_geography_missing",
        "Annual geography facts are available only as a Mainland-China-plus-Hong-Kong combined scope; they cannot be used as Hong Kong-only revenue.",
    )

    global_rows = int(
        frame["model_eligibility"].eq("scenario_only_until_hk_scope_bridge").sum()
    )
    add(
        "global_scope_quarantine",
        "global_or_jv_scenario_rows",
        global_rows,
        ">=0",
        "pass",
        "scenario_only_until_hk_scope_bridge",
        "Global/JV-inclusive commercial, hotel and sales facts remain available for scenarios but are quarantined from an HK-only core model.",
    )
    research_mask = frame["research_only"].map(
        lambda value: bool(value) if pd.notna(value) else False
    )
    research_rows = int(research_mask.sum())
    research_unquarantined = int(
        (research_mask & ~frame["model_eligibility"].eq("research_only_scenario")).sum()
    )
    add(
        "research_bridge_quarantine",
        "research_rows",
        research_rows,
        ">=0",
        "pass" if research_unquarantined == 0 else "fail",
        "research_only_scenario" if research_unquarantined == 0 else "do_not_use",
        "Residential contract cohorts are explicitly research-only and cannot be treated as accounting revenue.",
    )
    current_snapshot_rows = int(frame["model_eligibility"].eq("not_pit_clean").sum())
    add(
        "supplemental_pit_guard",
        "not_pit_clean_rows",
        current_snapshot_rows,
        ">=0",
        "pass",
        "not_pit_clean",
        "Financial-data actuals/consensus are retained as snapshots but are not PIT-clean until announcement-vintage coverage is repaired.",
    )
    selection = build_sino_land_forecast_input_selection(frame)
    forbidden_hk_rows = int(
        (
            selection["include_hk_core_control"]
            & ~selection["selection_bucket"].eq("hk_core_control")
        ).sum()
    )
    add(
        "selection_hk_core_guard",
        "forbidden_hk_core_rows",
        forbidden_hk_rows,
        "0",
        "pass" if forbidden_hk_rows == 0 else "fail",
        "eligible_as_hk_scope_control" if forbidden_hk_rows == 0 else "do_not_use",
        "Only direct H1 Hong Kong scope-control rows may enter the Hong Kong core-control bucket.",
    )
    forbidden_pit_rows = int(
        (
            selection["include_pit_backtest"]
            & ~selection["selection_bucket"].isin(
                {"hk_core_control", "reported_group_context"}
            )
        ).sum()
    )
    add(
        "selection_pit_guard",
        "forbidden_pit_backtest_rows",
        forbidden_pit_rows,
        "0",
        "pass" if forbidden_pit_rows == 0 else "fail",
        "pit_eligible_rows_only" if forbidden_pit_rows == 0 else "do_not_use",
        "Research-only, global scenario and current snapshot rows cannot be promoted into a PIT backtest.",
    )
    return pd.DataFrame(rows, columns=SINO_FORECAST_INPUT_QUALITY_COLUMNS)


def run_sino_land_forecast_inputs(
    *,
    db_path: Path = FINANCIAL_DATA_DB_PATH,
    persist: bool = True,
    load_financial_data: bool = True,
    use_persisted_financial_fallback: bool = False,
    bridge_schedule: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build and optionally persist the forecast-input contract."""
    run_id = f"sino-land-forecast-inputs-{uuid.uuid4()}"
    frames = build_sino_land_forecast_inputs(
        db_path=db_path,
        load_financial_data=load_financial_data,
        use_persisted_financial_fallback=use_persisted_financial_fallback,
        bridge_schedule=bridge_schedule,
    )
    normalized: dict[str, Any] = {}
    if persist:
        source_urls = [
            "https://web-media.sino.com/20a53f0a-15c8-0029-b8df-e495023b403f/4b78aed8-b020-4e92-a612-0d1a5bbc3ed7/E_SL_Annual%20Report%202023.pdf",
            "https://www.hkexnews.hk/listedco/listconews/sehk/2024/0926/2024092601281.pdf",
            "https://web-media.sino.com/20a53f0a-15c8-0029-b8df-e495023b403f/c468acfe-1a59-4c93-9131-6eeba511b501/E_SL_Annual%20Report%202025.pdf",
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0317/2026031700201.pdf",
        ]
        if bridge_schedule is None:
            source_urls.append("https://www.srpe.gov.hk/opip/all_development")
        lineage_base = {
            "lineage_type": "sino_land_forecast_input_contract",
            "run_id": run_id,
            "ticker": SINO_LAND_TICKER,
            "source_urls": source_urls,
            "source_datasets": [
                OFFICIAL_FACT_DATASET,
                SCHEDULE_DATASET,
                ACTUALS_DATASET,
                CONSENSUS_DATASET,
            ],
            "research_only": False,
            "model_fit_performed": False,
            "financial_data_load_status": frames["financial_data_load_status"],
            "financial_data_fallback_notes": frames["financial_data_fallback_notes"],
        }
        for dataset, frame in (
            (FORECAST_INPUT_DATASET, frames["forecast_inputs"]),
            (FORECAST_INPUT_SELECTION_DATASET, frames["selection"]),
            (H1_BASELINE_DATASET, frames["h1_baseline"]),
            (HK_SCOPE_PROXY_DATASET, frames["hk_scope_proxy"]),
            (FORECAST_INPUT_QUALITY_DATASET, frames["quality"]),
        ):
            metadata = dict(lineage_base)
            metadata["research_only"] = dataset in {
                FORECAST_INPUT_SELECTION_DATASET,
                H1_BASELINE_DATASET,
                HK_SCOPE_PROXY_DATASET,
                FORECAST_INPUT_QUALITY_DATASET,
            }
            normalized[dataset] = save_normalized_dataset(
                dataset,
                frame,
                run_id=run_id,
                source_urls=source_urls,
                lineage_metadata=metadata,
            )
    return {
        "run_id": run_id,
        "ticker": SINO_LAND_TICKER,
        "forecast_input_rows": int(len(frames["forecast_inputs"])),
        "selection_rows": int(len(frames["selection"])),
        "h1_baseline_rows": int(len(frames["h1_baseline"])),
        "hk_scope_proxy_rows": int(len(frames["hk_scope_proxy"])),
        "quality_rows": int(len(frames["quality"])),
        "normalized": normalized,
        "model_fit_performed": False,
        "financial_data_load_status": frames["financial_data_load_status"],
        "financial_data_fallback_notes": frames["financial_data_fallback_notes"],
        "research_bridge_rows": (
            int(
                frames["forecast_inputs"]["research_only"]
                .map(lambda value: bool(value) if pd.notna(value) else False)
                .sum()
            )
            if not frames["forecast_inputs"].empty
            else 0
        ),
    }
