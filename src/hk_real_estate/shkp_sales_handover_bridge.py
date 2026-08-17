"""Research-only SHKP sales -> handover -> revenue timing bridge.

This module is deliberately a *timing and coverage* contract, not a revenue
allocator.  SRPE registers provide gross contract activity by phase and month;
SHKP annual reports and completion schedules provide dated evidence or planned
windows; the Buildings Department crosswalk provides a current OP snapshot.
The company financial facts are annual group/segment anchors only.  No phase is
assigned a share of revenue, and an absent month is never converted to zero.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .shkp_financial_model import build_shkp_disclosed_financial_facts
from .shkp_signals import (
    ALL_HISTORY_INDICATIVE_SIGNAL_DATASET,
    INDICATIVE_SIGNAL_DATASET,
)
from .storage import load_latest_normalized, save_normalized_dataset


PHASE_DATASET = "shkp_sales_handover_revenue_bridge"
ANNUAL_DATASET = "shkp_sales_handover_revenue_annual"
COVERAGE_DATASET = "shkp_sales_handover_revenue_coverage"

PHASE_COLUMNS = [
    "bridge_id",
    "srpe_development_id",
    "development_name",
    "phase_name",
    "signal_scope",
    "sales_period_start",
    "sales_period_end",
    "last_nonzero_sales_period",
    "sales_months_observed",
    "sales_months_missing_inside_window",
    "sales_units_gross",
    "sales_value_gross_hkd",
    "active_units_latest",
    "cumulative_unique_units_latest",
    "sales_observation_status",
    "indicative_owner_status",
    "indicative_ownership_pct",
    "indicative_confidence",
    "indicative_evidence_basis",
    "handover_disclosure_status",
    "handover_report_period_end",
    "handover_report_evidence_count",
    "handover_report_match_status",
    "completion_schedule_as_of",
    "completion_window",
    "completion_schedule_evidence_count",
    "completion_schedule_match_status",
    "completion_schedule_ownership_pct",
    "bd_occupation_status",
    "bd_occupation_permit_count",
    "bd_occupation_units",
    "bd_snapshot_date_available",
    "revenue_anchor_status",
    "revenue_anchor_period_count",
    "revenue_anchor_latest_period_end",
    "bridge_status",
    "model_use",
    "source_urls_json",
    "caveat",
]

ANNUAL_COLUMNS = [
    "bridge_id",
    "fiscal_year_end",
    "fiscal_label",
    "signal_scope",
    "phase_count",
    "sales_phase_count",
    "sales_month_rows",
    "sales_units_gross",
    "sales_value_gross_hkd",
    "indicative_sales_value_hkd",
    "handover_observed_phase_count",
    "handover_schedule_phase_count",
    "bd_occupation_phase_count",
    "disclosed_property_sales_revenue_hkd_m",
    "disclosed_hk_contract_sales_yet_to_be_recognized_hkd_m",
    "disclosed_hk_contract_sales_expected_recognition_hkd_m",
    "gross_sales_to_property_revenue_ratio_pct",
    "revenue_anchor_status",
    "bridge_status",
    "model_use",
    "source_urls_json",
    "caveat",
]

COVERAGE_COLUMNS = [
    "coverage_id",
    "signal_scope",
    "phase_count",
    "sales_month_rows",
    "period_min",
    "period_max",
    "sales_value_gross_hkd",
    "nonzero_sales_phase_count",
    "indicative_numeric_phase_count",
    "handover_observed_phase_count",
    "completion_schedule_phase_count",
    "bd_occupation_phase_count",
    "phase_revenue_allocated_count",
    "not_covered_phase_count",
    "data_quality_status",
    "source_lineage",
    "caveat",
]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    value = str(value).strip()
    return value or None


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(parsed) if pd.notna(parsed) else None


def _date(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.strftime("%Y-%m-%d") if pd.notna(parsed) else None


def _unique_text(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, pd.Series):
        values = values.tolist()
    result: list[str] = []
    for value in values:
        text = _text(value)
        if text and text not in result:
            result.append(text)
    return result


def _join_unique(values: Any, *, separator: str = " | ") -> str | None:
    items = _unique_text(values)
    return separator.join(items) if items else None


def _json_urls(values: Any) -> str | None:
    urls = sorted({value for value in _unique_text(values) if value.startswith(("http://", "https://"))})
    return json.dumps(urls, ensure_ascii=False) if urls else None


def _fiscal_year_end(value: Any) -> int | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return int(parsed.year + (1 if parsed.month >= 7 else 0))


def _normalise_signals(signals: pd.DataFrame | None) -> pd.DataFrame:
    if signals is None or signals.empty:
        return pd.DataFrame()
    frame = signals.copy()
    if "srpe_development_id" not in frame.columns:
        if "phase_id" in frame.columns:
            frame["srpe_development_id"] = frame["phase_id"]
        else:
            return pd.DataFrame()
    frame["srpe_development_id"] = frame["srpe_development_id"].map(_text)
    frame = frame[frame["srpe_development_id"].notna()].copy()
    if "period" not in frame.columns:
        return pd.DataFrame()
    frame["period"] = pd.to_datetime(frame["period"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    frame = frame[frame["period"].notna()].copy()
    if "signal_scope" not in frame.columns:
        frame["signal_scope"] = "current_candidate_signal"
    frame["signal_scope"] = frame["signal_scope"].fillna("unknown_scope").astype(str)
    aliases = {
        "active_units_eom": "cumulative_unique_active_units",
        "indicative_owner_status": "indicative_attribution_status",
        "indicative_sales_value_hkd": "sales_value_gross_hkd",
    }
    for target, source in aliases.items():
        if target not in frame.columns and source in frame.columns:
            frame[target] = frame[source]
    numeric_columns = [
        "sales_units_gross",
        "sales_value_gross_hkd",
        "active_units_eom",
        "cumulative_unique_active_units",
        "indicative_sales_value_hkd",
        "indicative_ownership_pct",
        "ownership_pct",
    ]
    for column in numeric_columns:
        if column not in frame.columns:
            frame[column] = pd.NA
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    text_columns = [
        "development_name",
        "phase_name",
        "indicative_attribution_status",
        "indicative_owner_status",
        "indicative_confidence",
        "indicative_evidence_basis",
    ]
    for column in text_columns:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame.sort_values(["srpe_development_id", "signal_scope", "period"]).reset_index(drop=True)


def _phase_source_urls(*frames: pd.DataFrame, phase_id: str) -> list[str]:
    urls: list[str] = []
    for frame in frames:
        if frame is None or frame.empty or "srpe_development_id" not in frame.columns:
            continue
        matched = frame[frame["srpe_development_id"].astype(str).eq(str(phase_id))]
        for column in ("source_url", "document_url", "annual_document_url", "bd_source_url", "srpe_source_url"):
            if column in matched.columns:
                urls.extend(matched[column].tolist())
    return sorted({value for value in _unique_text(urls) if value.startswith(("http://", "https://"))})


def build_shkp_sales_handover_revenue_bridge(
    signals: pd.DataFrame | None,
    *,
    completion_schedule: pd.DataFrame | None = None,
    annual_crosswalk: pd.DataFrame | None = None,
    bd_crosswalk: pd.DataFrame | None = None,
    ownership_timeline: pd.DataFrame | None = None,
    disclosed_facts: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build one row per phase and signal scope with explicit timing states."""
    frame = _normalise_signals(signals)
    if frame.empty:
        return pd.DataFrame(columns=PHASE_COLUMNS)

    schedule = completion_schedule.copy() if completion_schedule is not None else pd.DataFrame()
    annual = annual_crosswalk.copy() if annual_crosswalk is not None else pd.DataFrame()
    bd = bd_crosswalk.copy() if bd_crosswalk is not None else pd.DataFrame()
    timeline = ownership_timeline.copy() if ownership_timeline is not None else pd.DataFrame()
    facts = disclosed_facts.copy() if disclosed_facts is not None else pd.DataFrame()
    for source in (schedule, annual, bd, timeline):
        if "srpe_development_id" in source.columns:
            source["srpe_development_id"] = source["srpe_development_id"].map(_text)

    revenue_facts = facts.loc[
        facts.get("metric", pd.Series(dtype="string")).isin(
            ["property_sales_revenue_including_jv_associates"]
        )
    ].copy() if not facts.empty else pd.DataFrame()
    revenue_periods = _unique_text(revenue_facts.get("period_end", pd.Series(dtype="string")))
    revenue_latest = max(revenue_periods) if revenue_periods else None

    rows: list[dict[str, Any]] = []
    for (phase_id, scope), group in frame.groupby(["srpe_development_id", "signal_scope"], dropna=False):
        group = group.sort_values("period")
        period_min = group["period"].min()
        period_max = group["period"].max()
        nonzero = group[
            group["sales_units_gross"].fillna(0).gt(0)
            | group["sales_value_gross_hkd"].fillna(0).gt(0)
        ]
        last_nonzero = nonzero["period"].max() if not nonzero.empty else pd.NaT
        observed_months = int(group["period"].nunique())
        span_months = (
            (period_max.year - period_min.year) * 12 + period_max.month - period_min.month + 1
            if pd.notna(period_min) and pd.notna(period_max)
            else observed_months
        )
        missing_inside = max(int(span_months) - observed_months, 0)
        sales_units = _number(group["sales_units_gross"].sum(min_count=1))
        sales_value = _number(group["sales_value_gross_hkd"].sum(min_count=1))
        last = group.iloc[-1]
        # The merged all-history contract can retain a trailing month whose
        # register is present but has no parsed unit rows.  Use the last
        # non-null snapshot rather than turning that legitimate parser gap
        # into an apparent collapse to zero/NA.
        active_series = group["active_units_eom"].dropna()
        cumulative_series = group["cumulative_unique_active_units"].dropna()
        active_latest = _number(active_series.iloc[-1]) if not active_series.empty else None
        cumulative_latest = _number(cumulative_series.iloc[-1]) if not cumulative_series.empty else None
        sales_status = "observed_register_months_with_activity" if not nonzero.empty else "observed_register_months_no_nonzero_event"

        # Annual report rows are evidence of the issuer's handover table, not a
        # precise OP date.  Keep the report period and match state separate.
        annual_rows = annual[annual["srpe_development_id"].eq(phase_id)] if not annual.empty and "srpe_development_id" in annual.columns else pd.DataFrame()
        handover_rows = annual_rows[annual_rows.get("project_state", pd.Series(dtype="string")).eq("handover_completed")] if not annual_rows.empty else pd.DataFrame()
        annual_periods = pd.to_datetime(annual_rows.get("report_period_end", pd.Series(dtype="string")), errors="coerce").dropna()
        handover_periods = pd.to_datetime(handover_rows.get("report_period_end", pd.Series(dtype="string")), errors="coerce").dropna()
        if not handover_rows.empty:
            handover_status = "observed_annual_handover_completed"
        elif not annual_rows.empty:
            handover_status = "annual_project_evidence_no_handover_completed"
        else:
            handover_status = "not_observed"

        schedule_rows = schedule[schedule["srpe_development_id"].eq(phase_id)] if not schedule.empty and "srpe_development_id" in schedule.columns else pd.DataFrame()
        schedule_dates = pd.to_datetime(schedule_rows.get("schedule_date", pd.Series(dtype="string")), errors="coerce") if not schedule_rows.empty else pd.Series(dtype="datetime64[ns]")
        latest_schedule_date = schedule_dates.max() if not schedule_dates.empty else pd.NaT
        latest_schedule_rows = schedule_rows.loc[schedule_dates.eq(latest_schedule_date)] if not schedule_rows.empty and pd.notna(latest_schedule_date) else pd.DataFrame()
        schedule_window = _join_unique(latest_schedule_rows.get("completion_window", pd.Series(dtype="string")))
        schedule_match = _join_unique(latest_schedule_rows.get("match_status", pd.Series(dtype="string")))
        schedule_ownership_status = _join_unique(latest_schedule_rows.get("ownership_status", pd.Series(dtype="string")))
        schedule_pct = _number(latest_schedule_rows.get("group_interest_pct", pd.Series(dtype="float64")).dropna().iloc[-1]) if not latest_schedule_rows.empty and latest_schedule_rows.get("group_interest_pct", pd.Series(dtype="float64")).notna().any() else None

        timeline_rows = timeline[
            timeline["srpe_development_id"].eq(phase_id)
            & timeline.get("event_type", pd.Series(dtype="string")).astype(str).eq("handover_table")
        ] if not timeline.empty and "srpe_development_id" in timeline.columns else pd.DataFrame()
        # A timeline handover event confirms source semantics but does not add
        # an extra date beyond the annual report period.
        if handover_status == "not_observed" and not timeline_rows.empty:
            handover_status = "observed_annual_handover_evidence_timeline"

        bd_rows = bd[bd["srpe_development_id"].eq(phase_id)] if not bd.empty and "srpe_development_id" in bd.columns else pd.DataFrame()
        op_rows = bd_rows[bd_rows.get("bd_permit_stage", pd.Series(dtype="string")).astype(str).str.contains("Occupation", case=False, na=False)] if not bd_rows.empty else pd.DataFrame()
        bd_status = "current_bd_occupation_permit_snapshot" if not op_rows.empty else ("current_bd_crosswalk_no_op_match" if not bd_rows.empty else "not_observed")
        permit_count = int(op_rows.get("bd_permit_number", pd.Series(dtype="string")).dropna().astype(str).nunique()) if not op_rows.empty else 0
        bd_units = _number(op_rows.get("bd_domestic_units_count", pd.Series(dtype="float64")).sum(min_count=1)) if not op_rows.empty else None

        if handover_status.startswith("observed"):
            bridge_status = "sales_observed_handover_disclosure_observed_revenue_not_phase_allocated"
        elif schedule_window:
            bridge_status = "sales_observed_handover_schedule_window_only"
        elif bd_status.startswith("current_bd_occupation"):
            bridge_status = "sales_observed_current_bd_op_snapshot_only"
        else:
            bridge_status = "sales_observed_handover_not_observed"

        urls = _phase_source_urls(schedule, annual, bd, timeline, phase_id=str(phase_id))
        rows.append(
            {
                "bridge_id": f"{phase_id}:{scope}",
                "srpe_development_id": str(phase_id),
                "development_name": _text(last.get("development_name")),
                "phase_name": _text(last.get("phase_name")),
                "signal_scope": str(scope),
                "sales_period_start": _date(period_min),
                "sales_period_end": _date(period_max),
                "last_nonzero_sales_period": _date(last_nonzero),
                "sales_months_observed": observed_months,
                "sales_months_missing_inside_window": missing_inside,
                "sales_units_gross": sales_units,
                "sales_value_gross_hkd": sales_value,
                "active_units_latest": active_latest,
                "cumulative_unique_units_latest": cumulative_latest,
                "sales_observation_status": sales_status,
                "indicative_owner_status": _text(last.get("indicative_owner_status")) or _text(last.get("indicative_attribution_status")),
                "indicative_ownership_pct": (
                    _number(last.get("indicative_ownership_pct"))
                    if _number(last.get("indicative_ownership_pct")) is not None
                    else _number(last.get("ownership_pct"))
                ),
                "indicative_confidence": _text(last.get("indicative_confidence")),
                "indicative_evidence_basis": _text(last.get("indicative_evidence_basis")),
                "handover_disclosure_status": handover_status,
                "handover_report_period_end": _date(handover_periods.max()) if not handover_periods.empty else None,
                "handover_report_evidence_count": int(len(handover_rows) or len(timeline_rows)),
                "handover_report_match_status": _join_unique(handover_rows.get("match_status", pd.Series(dtype="string"))) if not handover_rows.empty else None,
                "completion_schedule_as_of": _date(latest_schedule_date),
                "completion_window": schedule_window,
                "completion_schedule_evidence_count": int(len(schedule_rows)),
                "completion_schedule_match_status": schedule_match,
                "completion_schedule_ownership_pct": schedule_pct,
                "bd_occupation_status": bd_status,
                "bd_occupation_permit_count": permit_count,
                "bd_occupation_units": bd_units,
                "bd_snapshot_date_available": False if not op_rows.empty else None,
                "revenue_anchor_status": "company_annual_property_sales_only_not_phase_allocated" if not revenue_facts.empty else "not_observed",
                "revenue_anchor_period_count": int(len(revenue_facts)),
                "revenue_anchor_latest_period_end": revenue_latest,
                "bridge_status": bridge_status,
                "model_use": "timing_bridge_only_research",
                "source_urls_json": _json_urls(urls),
                "caveat": (
                    "SRPE is gross contract activity and may include register updates/resales; it is not booked revenue. "
                    "Annual-report handover rows are report-period evidence, completion schedules are planned/as-of windows, "
                    "and BD OP is a current snapshot without an event date in this crosswalk. Missing months are not zero-filled; "
                    "no phase-level revenue allocation is made."
                ),
            }
        )
    return pd.DataFrame(rows, columns=PHASE_COLUMNS)


def build_shkp_sales_handover_revenue_annual(
    signals: pd.DataFrame | None,
    phase_bridge: pd.DataFrame | None,
    disclosed_facts: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Aggregate gross activity by fiscal year beside company-level anchors."""
    frame = _normalise_signals(signals)
    phase = phase_bridge.copy() if phase_bridge is not None else pd.DataFrame()
    if frame.empty:
        return pd.DataFrame(columns=ANNUAL_COLUMNS)
    frame["fiscal_year_end"] = frame["period"].map(_fiscal_year_end)
    frame = frame[frame["fiscal_year_end"].notna()].copy()
    facts = disclosed_facts.copy() if disclosed_facts is not None else pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for (fiscal_year, scope), group in frame.groupby(["fiscal_year_end", "signal_scope"], dropna=False):
        year = int(fiscal_year)
        phase_ids = set(group["srpe_development_id"].astype(str))
        phase_rows = phase[phase.get("srpe_development_id", pd.Series(dtype="string")).astype(str).isin(phase_ids) & phase.get("signal_scope", pd.Series(dtype="string")).eq(scope)] if not phase.empty else pd.DataFrame()
        sales_phase_count = int(group.loc[group["sales_units_gross"].fillna(0).gt(0) | group["sales_value_gross_hkd"].fillna(0).gt(0), "srpe_development_id"].nunique())
        property_revenue = facts[
            facts.get("metric", pd.Series(dtype="string")).eq("property_sales_revenue_including_jv_associates")
            & pd.to_datetime(facts.get("period_end", pd.Series(dtype="string")), errors="coerce").dt.year.eq(year)
        ] if not facts.empty else pd.DataFrame()
        backlog = facts[
            facts.get("metric", pd.Series(dtype="string")).eq("hk_contract_sales_yet_to_be_recognized")
            & pd.to_datetime(facts.get("period_end", pd.Series(dtype="string")), errors="coerce").dt.year.eq(year)
        ] if not facts.empty else pd.DataFrame()
        expected = facts[
            facts.get("metric", pd.Series(dtype="string")).eq("hk_contract_sales_expected_recognition")
            & pd.to_datetime(facts.get("period_end", pd.Series(dtype="string")), errors="coerce").dt.year.eq(year)
        ] if not facts.empty else pd.DataFrame()
        revenue = _number(property_revenue["value"].iloc[-1]) if not property_revenue.empty else None
        backlog_value = _number(backlog["value"].iloc[-1]) if not backlog.empty else None
        expected_value = _number(expected["value"].iloc[-1]) if not expected.empty else None
        ratio = (float(group["sales_value_gross_hkd"].sum()) / (revenue * 1_000_000.0) * 100.0) if revenue and revenue != 0 else None
        rows.append(
            {
                "bridge_id": f"FY{year}:{scope}",
                "fiscal_year_end": year,
                "fiscal_label": f"FY{year - 1}/{str(year)[-2:]}",
                "signal_scope": str(scope),
                "phase_count": int(group["srpe_development_id"].nunique()),
                "sales_phase_count": sales_phase_count,
                "sales_month_rows": int(len(group)),
                "sales_units_gross": _number(group["sales_units_gross"].sum(min_count=1)),
                "sales_value_gross_hkd": _number(group["sales_value_gross_hkd"].sum(min_count=1)),
                "indicative_sales_value_hkd": _number(group["indicative_sales_value_hkd"].sum(min_count=1)),
                "handover_observed_phase_count": int(phase_rows["handover_disclosure_status"].astype(str).str.startswith("observed").sum()) if not phase_rows.empty and "handover_disclosure_status" in phase_rows.columns else 0,
                "handover_schedule_phase_count": int(phase_rows["completion_window"].notna().sum()) if not phase_rows.empty and "completion_window" in phase_rows.columns else 0,
                "bd_occupation_phase_count": int(phase_rows["bd_occupation_status"].astype(str).str.startswith("current_bd_occupation").sum()) if not phase_rows.empty and "bd_occupation_status" in phase_rows.columns else 0,
                "disclosed_property_sales_revenue_hkd_m": revenue,
                "disclosed_hk_contract_sales_yet_to_be_recognized_hkd_m": backlog_value,
                "disclosed_hk_contract_sales_expected_recognition_hkd_m": expected_value,
                "gross_sales_to_property_revenue_ratio_pct": ratio,
                "revenue_anchor_status": "company_annual_anchor_not_phase_allocated" if revenue is not None else "no_company_annual_anchor",
                "bridge_status": "directional_timing_diagnostic",
                "model_use": "annual_timing_diagnostic_only_research",
                "source_urls_json": _json_urls(facts.get("source_url", pd.Series(dtype="string")).tolist() if not facts.empty else []),
                "caveat": (
                    "Gross SRPE contract activity and issuer property-sales revenue differ in timing, geography, JV scope and phase coverage. "
                    "The ratio is a diagnostic, not an accuracy score or revenue conversion factor."
                ),
            }
        )
    return pd.DataFrame(rows, columns=ANNUAL_COLUMNS).sort_values(["fiscal_year_end", "signal_scope"]).reset_index(drop=True)


def build_shkp_sales_handover_revenue_coverage(
    phase_bridge: pd.DataFrame | None,
    annual_bridge: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return compact completeness/coverage diagnostics for the bridge."""
    phase = phase_bridge.copy() if phase_bridge is not None else pd.DataFrame()
    if phase.empty:
        return pd.DataFrame(columns=COVERAGE_COLUMNS)
    rows: list[dict[str, Any]] = []
    for scope, group in phase.groupby("signal_scope", dropna=False):
        observed = group["sales_observation_status"].astype(str).str.contains("activity", na=False)
        numeric = pd.to_numeric(group["indicative_ownership_pct"], errors="coerce").notna()
        handover = group["handover_disclosure_status"].astype(str).str.startswith("observed")
        schedule = group["completion_window"].notna()
        op = group["bd_occupation_status"].astype(str).str.startswith("current_bd_occupation")
        rows.append(
            {
                "coverage_id": f"{scope}:latest",
                "signal_scope": str(scope),
                "phase_count": int(group["srpe_development_id"].nunique()),
                "sales_month_rows": int(group["sales_months_observed"].sum()),
                "period_min": group["sales_period_start"].min(),
                "period_max": group["sales_period_end"].max(),
                "sales_value_gross_hkd": _number(group["sales_value_gross_hkd"].sum(min_count=1)),
                "nonzero_sales_phase_count": int(observed.sum()),
                "indicative_numeric_phase_count": int(numeric.sum()),
                "handover_observed_phase_count": int(handover.sum()),
                "completion_schedule_phase_count": int(schedule.sum()),
                "bd_occupation_phase_count": int(op.sum()),
                "phase_revenue_allocated_count": 0,
                "not_covered_phase_count": int((~observed).sum()),
                "data_quality_status": "usable_for_timing_monitoring_not_revenue_model",
                "source_lineage": "SRPE registers + SHKP annual report/completion schedule crosswalk + BD OP crosswalk + issuer financial facts",
                "caveat": "Missing months are not zero-filled; ownership and phase-level revenue allocation remain unresolved.",
            }
        )
    return pd.DataFrame(rows, columns=COVERAGE_COLUMNS)


def run_shkp_sales_handover_revenue_bridge() -> dict[str, Any]:
    """Load latest normalized sources and persist the three bridge layers."""
    run_id = f"shkp-sales-handover-bridge-{uuid.uuid4()}"
    signals = load_latest_normalized(ALL_HISTORY_INDICATIVE_SIGNAL_DATASET)
    if signals.empty:
        signals = load_latest_normalized(INDICATIVE_SIGNAL_DATASET)
    disclosed = load_latest_normalized("shkp_financial_model_disclosed_facts")
    if disclosed.empty:
        disclosed = build_shkp_disclosed_financial_facts()
    phase = build_shkp_sales_handover_revenue_bridge(
        signals,
        completion_schedule=load_latest_normalized("shkp_completion_schedule_crosswalk"),
        annual_crosswalk=load_latest_normalized("shkp_annual_srpe_crosswalk"),
        bd_crosswalk=load_latest_normalized("shkp_bd_crosswalk"),
        ownership_timeline=load_latest_normalized("shkp_ownership_evidence_timeline"),
        disclosed_facts=disclosed,
    )
    annual = build_shkp_sales_handover_revenue_annual(signals, phase, disclosed)
    coverage = build_shkp_sales_handover_revenue_coverage(phase, annual)
    lineage = {
        "lineage_type": "shkp_sales_handover_revenue_timing_bridge",
        "source_datasets": [
            ALL_HISTORY_INDICATIVE_SIGNAL_DATASET if not load_latest_normalized(ALL_HISTORY_INDICATIVE_SIGNAL_DATASET).empty else INDICATIVE_SIGNAL_DATASET,
            "shkp_completion_schedule_crosswalk",
            "shkp_annual_srpe_crosswalk",
            "shkp_bd_crosswalk",
            "shkp_ownership_evidence_timeline",
            "shkp_financial_model_disclosed_facts",
        ],
        "revenue_allocation": False,
        "missing_month_policy": "not_zero_filled",
        "ownership_promotion": False,
        "research_only": True,
    }
    normalized = {
        PHASE_DATASET: save_normalized_dataset(PHASE_DATASET, phase, run_id=run_id, lineage_metadata=lineage),
        ANNUAL_DATASET: save_normalized_dataset(ANNUAL_DATASET, annual, run_id=run_id, lineage_metadata=lineage),
        COVERAGE_DATASET: save_normalized_dataset(COVERAGE_DATASET, coverage, run_id=run_id, lineage_metadata=lineage),
    }
    return {
        "run_id": run_id,
        "phase_rows": int(len(phase)),
        "annual_rows": int(len(annual)),
        "coverage_rows": int(len(coverage)),
        "phase_count": int(phase["srpe_development_id"].nunique()) if not phase.empty else 0,
        "normalized": normalized,
        "research_only": True,
    }
