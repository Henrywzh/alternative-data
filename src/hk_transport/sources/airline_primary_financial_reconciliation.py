"""Reconcile provider financial history to covered primary issuer reports."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import NORMALIZED_DIR


OFFICIAL_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
HISTORY_PATH = NORMALIZED_DIR / "airline_financial_history_trend.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_primary_financial_reconciliation.csv"

METRICS = ["total_revenue", "operating_cost", "attributable_net_income", "operating_cash_flow", "basic_eps"]
PERIODS = {"FY2025": "2025-12-31", "1H2025": "2025-06-30"}

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "statement_period", "period_end", "metric",
    "official_value_native", "official_native_unit", "official_native_currency", "official_value_usd",
    "official_announced_at", "official_source_quality", "official_source_url", "official_source_page",
    "provider_value_native", "provider_native_unit", "provider_native_currency", "provider_value_usd",
    "provider_as_of_date", "provider_point_in_time_status", "native_unit_match", "native_currency_match",
    "difference_native", "difference_pct_vs_provider", "reconciliation_status", "source_quality",
    "source_note", "retrieved_at",
]


def _number(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _matched(first: float | None, second: float | None) -> bool | None:
    if first is None or second is None:
        return None
    return abs(first - second) <= max(0.01, abs(second) * 1e-6)


def build_airline_primary_financial_reconciliation(
    *, official: pd.DataFrame | None = None,
    history: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    official = official if official is not None else pd.read_csv(OFFICIAL_PATH)
    history = history if history is not None else pd.read_csv(HISTORY_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    companies = sorted(set(official["company"].dropna()) | set(history["company"].dropna()))
    rows: list[dict[str, object]] = []
    for company in companies:
        ticker_rows = official.loc[official["company"].eq(company), "ticker"].dropna()
        ticker = ticker_rows.iloc[0] if not ticker_rows.empty else history.loc[history["company"].eq(company), "ticker"].iloc[0]
        for statement_period, period_end in PERIODS.items():
            for metric in METRICS:
                official_rows = official.loc[
                    official["company"].eq(company)
                    & official["statement_period"].eq(statement_period)
                    & official["metric"].eq(metric)
                ]
                provider_rows = history.loc[
                    history["company"].eq(company)
                    & history["period_end"].eq(period_end)
                    & history["metric"].eq(metric)
                ]
                official_row = official_rows.iloc[0] if not official_rows.empty else pd.Series(dtype=object)
                provider_row = provider_rows.iloc[0] if not provider_rows.empty else pd.Series(dtype=object)
                official_value = _number(official_row.get("value_native"))
                provider_value = _number(provider_row.get("value_native"))
                unit_match = None if official_row.empty or provider_row.empty else str(official_row.get("native_unit")) == str(provider_row.get("native_unit"))
                currency_match = None if official_row.empty or provider_row.empty else str(official_row.get("native_currency")) == str(provider_row.get("native_currency"))
                if official_value is None and provider_value is None:
                    status = "both_missing"
                elif official_value is None:
                    status = "official_gap_provider_only"
                elif provider_value is None:
                    status = "provider_gap_official_only"
                elif _matched(official_value, provider_value):
                    status = "matched"
                else:
                    status = "official_provider_mismatch"
                difference = official_value - provider_value if official_value is not None and provider_value is not None else None
                difference_pct = 100.0 * difference / abs(provider_value) if difference is not None and provider_value not in (None, 0) else None
                rows.append({
                    "dataset_id": "airline_primary_financial_reconciliation",
                    "company": company, "ticker": ticker, "statement_period": statement_period,
                    "period_end": period_end, "metric": metric,
                    "official_value_native": official_value,
                    "official_native_unit": official_row.get("native_unit"),
                    "official_native_currency": official_row.get("native_currency"),
                    "official_value_usd": _number(official_row.get("value_usd")),
                    "official_announced_at": official_row.get("announced_at"),
                    "official_source_quality": official_row.get("source_quality"),
                    "official_source_url": official_row.get("source_url"),
                    "official_source_page": official_row.get("source_page"),
                    "provider_value_native": provider_value,
                    "provider_native_unit": provider_row.get("native_unit"),
                    "provider_native_currency": provider_row.get("native_currency"),
                    "provider_value_usd": _number(provider_row.get("value_usd")),
                    "provider_as_of_date": provider_row.get("as_of_date"),
                    "provider_point_in_time_status": provider_row.get("point_in_time_status"),
                    "native_unit_match": unit_match,
                    "native_currency_match": currency_match,
                    "difference_native": difference,
                    "difference_pct_vs_provider": difference_pct,
                    "reconciliation_status": status,
                    "source_quality": "primary_vs_provider_reconciliation",
                    "source_note": (
                        "Official issuer value controls the final thesis when present. Provider history is retained for long-run context; "
                        "operating-cost mismatches require definition/scope review before use in CASK or earnings bridges."
                    ),
                    "retrieved_at": retrieved,
                })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_primary_financial_reconciliation() -> pd.DataFrame:
    result = build_airline_primary_financial_reconciliation()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
