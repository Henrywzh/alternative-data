"""Company guidance, earnings-warning and formal-result coverage contract."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import NORMALIZED_DIR


EVENT_PATH = NORMALIZED_DIR / "airline_event_timeline.csv"
READINESS_PATH = NORMALIZED_DIR / "airline_pair_readiness.csv"
OFFICIAL_FILING_WATCH_PATH = NORMALIZED_DIR / "airline_official_filing_watch.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_guidance_coverage.csv"

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "market", "snapshot_date",
    "guidance_event_count", "warning_event_count", "formal_result_event_count",
    "latest_guidance_date", "latest_guidance_metric", "latest_guidance_value_min",
    "latest_guidance_value_max", "latest_guidance_native_unit", "latest_guidance_source_quality",
    "latest_guidance_source_url", "latest_warning_date", "latest_warning_metric",
    "latest_warning_value_min", "latest_warning_value_max", "latest_warning_native_unit",
    "latest_warning_source_quality", "latest_warning_source_url", "latest_financial_result_date",
    "formal_report_status", "formal_report_scheduled_date", "formal_report_actual_disclosure_date",
    "guidance_coverage_status", "source_note", "retrieved_at",
]


def _date(value: object) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _number(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _is_true(value: object) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _first_present(*values: object) -> object:
    for value in values:
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        if str(value).strip().lower() in {"", "nan", "none"}:
            continue
        return value
    return None


def _latest(frame: pd.DataFrame, event_type: str) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=object)
    selected = frame.loc[frame["event_type"].eq(event_type)].copy()
    if selected.empty:
        return pd.Series(dtype=object)
    selected["_event_date"] = pd.to_datetime(selected["event_date"], errors="coerce")
    selected = selected.dropna(subset=["_event_date"]).sort_values(["_event_date", "event_id"])
    return selected.iloc[-1] if not selected.empty else pd.Series(dtype=object)


def build_airline_guidance_coverage(
    *,
    events: pd.DataFrame | None = None,
    readiness: pd.DataFrame | None = None,
    official_filing_watch: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build one guidance/warning coverage row per company in the readiness gate."""
    events = events if events is not None else pd.read_csv(EVENT_PATH)
    readiness = readiness if readiness is not None else pd.read_csv(READINESS_PATH)
    official_filing_watch = (
        official_filing_watch
        if official_filing_watch is not None
        else (pd.read_csv(OFFICIAL_FILING_WATCH_PATH) if OFFICIAL_FILING_WATCH_PATH.exists() else pd.DataFrame())
    )
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    for _, company_row in readiness.iterrows():
        company = str(company_row["company"])
        company_events = events.loc[events["company"].eq(company)].copy()
        guidance = company_events.loc[company_events["event_type"].eq("earnings_guidance")]
        warnings = company_events.loc[company_events["event_type"].eq("earnings_warning")]
        results = company_events.loc[company_events["event_type"].eq("financial_results")]
        latest_guidance = _latest(company_events, "earnings_guidance")
        latest_warning = _latest(company_events, "earnings_warning")
        latest_result = _latest(company_events, "financial_results")
        filing_match = pd.DataFrame()
        if not official_filing_watch.empty and "company" in official_filing_watch.columns:
            filing_candidates = official_filing_watch.loc[
                official_filing_watch["company"].eq(company)
            ].copy()
            if not filing_candidates.empty:
                filing_candidates["_snapshot"] = pd.to_datetime(
                    filing_candidates["snapshot_date"], errors="coerce"
                )
                filing_match = filing_candidates.sort_values("_snapshot").iloc[-1:]
        if not guidance.empty:
            status = "direct_issuer_guidance"
        elif not warnings.empty:
            status = "issuer_earnings_warning_only"
        elif not results.empty:
            status = "formal_result_without_structured_guidance"
        else:
            status = "no_company_guidance_before_formal_1H2026"
        calendar_status = company_row.get("formal_report_status")
        scheduled_date = company_row.get("formal_report_scheduled_date")
        actual_disclosure_date = company_row.get("formal_report_actual_disclosure_date")
        if not filing_match.empty:
            watch_row = filing_match.iloc[0]
            scheduled_date = _first_present(watch_row.get("scheduled_date"), scheduled_date)
            if _is_true(watch_row.get("official_report_found")):
                calendar_status = "disclosed"
                actual_disclosure_date = watch_row.get("official_disclosure_date")
        rows.append({
            "dataset_id": "airline_guidance_coverage",
            "company": company,
            "ticker": company_row["ticker"],
            "market": company_row["market"],
            "snapshot_date": company_row["snapshot_date"],
            "guidance_event_count": int(len(guidance)),
            "warning_event_count": int(len(warnings)),
            "formal_result_event_count": int(len(results)),
            "latest_guidance_date": _date(latest_guidance.get("event_date")),
            "latest_guidance_metric": latest_guidance.get("metric"),
            "latest_guidance_value_min": _number(latest_guidance.get("value_min")),
            "latest_guidance_value_max": _number(latest_guidance.get("value_max")),
            "latest_guidance_native_unit": latest_guidance.get("native_unit"),
            "latest_guidance_source_quality": latest_guidance.get("source_quality"),
            "latest_guidance_source_url": latest_guidance.get("source_url"),
            "latest_warning_date": _date(latest_warning.get("event_date")),
            "latest_warning_metric": latest_warning.get("metric"),
            "latest_warning_value_min": _number(latest_warning.get("value_min")),
            "latest_warning_value_max": _number(latest_warning.get("value_max")),
            "latest_warning_native_unit": latest_warning.get("native_unit"),
            "latest_warning_source_quality": latest_warning.get("source_quality"),
            "latest_warning_source_url": latest_warning.get("source_url"),
            "latest_financial_result_date": _date(latest_result.get("event_date")),
            "formal_report_status": calendar_status,
            "formal_report_scheduled_date": scheduled_date,
            "formal_report_actual_disclosure_date": actual_disclosure_date,
            "guidance_coverage_status": status,
            "source_note": (
                "Company-level guidance/warning coverage derived from the curated dated event timeline. "
                "Missing guidance is explicit and is not treated as a neutral outlook; formal-report catalyst "
                "status comes from the point-in-time filing calendar/readiness gate and, "
                "when available, the direct CNINFO official-filing watch."
            ),
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_guidance_coverage() -> pd.DataFrame:
    result = build_airline_guidance_coverage()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
