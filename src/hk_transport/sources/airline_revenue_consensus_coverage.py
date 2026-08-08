"""Coverage contract for airline revenue expectations by share class."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import NORMALIZED_DIR


BRIDGE_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
YFINANCE_PATH = NORMALIZED_DIR / "airline_revenue_consensus_yfinance.csv"
ASHARE_PATH = NORMALIZED_DIR / "airline_consensus_ashare_detailed.csv"
SELL_SIDE_PATH = NORMALIZED_DIR / "airline_sell_side_revenue_forecasts.csv"
SELL_SIDE_REVISION_PATH = NORMALIZED_DIR / "airline_sell_side_revenue_revisions.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_revenue_consensus_coverage.csv"

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "market", "snapshot_date", "fiscal_year",
    "source_layer", "coverage_scope", "source_quality", "forecast_row_count",
    "analyst_count", "forecast_date_min", "forecast_date_max",
    "native_unit", "normalization_factor_to_native_mn",
    "revenue_avg_native_mn", "revenue_low_native_mn", "revenue_high_native_mn",
    "revision_history_available", "sell_side_report_row_count",
    "sell_side_revision_row_count", "sell_side_latest_report_date", "source_url",
    "source_note", "retrieved_at",
]


def _number(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _date(value: object) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _latest(frame: pd.DataFrame, column: str) -> str | None:
    if frame.empty or column not in frame.columns:
        return None
    values = pd.to_datetime(frame[column], errors="coerce").dropna()
    return values.max().strftime("%Y-%m-%d") if not values.empty else None


def _earliest(frame: pd.DataFrame, column: str) -> str | None:
    if frame.empty or column not in frame.columns:
        return None
    values = pd.to_datetime(frame[column], errors="coerce").dropna()
    return values.min().strftime("%Y-%m-%d") if not values.empty else None


def _direct_yfinance(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    return frame.loc[
        frame["ticker"].eq(ticker)
        & pd.to_numeric(frame.get("fiscal_year"), errors="coerce").eq(2026)
    ].copy()


def _fallback_ashare(frame: pd.DataFrame, company: str) -> pd.DataFrame:
    if frame.empty or "company" not in frame.columns:
        return pd.DataFrame()
    return frame.loc[
        frame["company"].eq(company)
        & frame["metric"].astype(str).str.lower().eq("revenue")
        & pd.to_numeric(frame["fiscal_year"], errors="coerce").eq(2026)
    ].copy()


def build_airline_revenue_consensus_coverage(
    *,
    bridge: pd.DataFrame | None = None,
    yfinance: pd.DataFrame | None = None,
    ashare_detailed: pd.DataFrame | None = None,
    sell_side: pd.DataFrame | None = None,
    sell_side_revisions: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build one explicit revenue-consensus coverage row per traded share class."""
    bridge = bridge if bridge is not None else pd.read_csv(BRIDGE_PATH)
    yfinance = yfinance if yfinance is not None else (
        pd.read_csv(YFINANCE_PATH) if YFINANCE_PATH.exists() else pd.DataFrame()
    )
    ashare_detailed = ashare_detailed if ashare_detailed is not None else (
        pd.read_csv(ASHARE_PATH) if ASHARE_PATH.exists() else pd.DataFrame()
    )
    sell_side = sell_side if sell_side is not None else (
        pd.read_csv(SELL_SIDE_PATH) if SELL_SIDE_PATH.exists() else pd.DataFrame()
    )
    sell_side_revisions = sell_side_revisions if sell_side_revisions is not None else (
        pd.read_csv(SELL_SIDE_REVISION_PATH) if SELL_SIDE_REVISION_PATH.exists() else pd.DataFrame()
    )
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    for _, share in bridge.iterrows():
        company = str(share["company"])
        ticker = str(share["market_ticker"])
        market = str(share["market"])
        direct = _direct_yfinance(yfinance, ticker)
        fallback = pd.DataFrame() if not direct.empty else _fallback_ashare(ashare_detailed, company)
        if not direct.empty:
            source_layer = "vendor_revenue_consensus"
            scope = "direct_ticker_vendor_estimate"
            quality = "yfinance_discovery"
            source = direct
            avg = _number(source["revenue_avg_native_mn"].mean())
            low = _number(source["revenue_low_native_mn"].min())
            high = _number(source["revenue_high_native_mn"].max())
            analyst_count = _number(source["analyst_count"].max())
            forecast_min = _latest(source, "snapshot_date")
            forecast_max = forecast_min
            source_url = source.iloc[0].get("source_url")
            revision_history = bool(source.get("revision_history_available", pd.Series(dtype=bool)).fillna(False).any())
            native_unit = "RMB million" if str(source.iloc[0].get("native_currency")) == "RMB" else "HKD million"
            normalization_factor = 1.0
        elif not fallback.empty:
            source_layer = "ashare_detailed_revenue_consensus"
            scope = "same_company_cross_market_fallback"
            quality = "akshare_discovery"
            source = fallback
            # 10jqka's detailed-indicator revenue is RMB 100 million; convert
            # to the RMB-million contract used by the direct vendor layer.
            avg = _number(source["value_avg_native"].mean() * 100.0)
            low_value = _number(source.get("value_low_native", pd.Series(dtype=float)).min())
            high_value = _number(source.get("value_high_native", pd.Series(dtype=float)).max())
            low = low_value * 100.0 if low_value is not None else None
            high = high_value * 100.0 if high_value is not None else None
            analyst_count = _number(source.get("forecast_count", pd.Series(dtype=float)).max())
            forecast_min = _earliest(source, "forecast_date_min")
            forecast_max = _latest(source, "forecast_date_max")
            source_url = source.iloc[0].get("source_url")
            revision_history = False
            native_unit = "RMB million"
            normalization_factor = 100.0
        else:
            source_layer = "none"
            scope = "missing"
            quality = "missing"
            source = pd.DataFrame()
            avg = low = high = analyst_count = None
            forecast_min = forecast_max = source_url = None
            revision_history = False
            native_unit = None
            normalization_factor = None

        company_sell_side = sell_side.loc[sell_side["company"].eq(company)] if not sell_side.empty else pd.DataFrame()
        company_sell_side = company_sell_side.loc[
            pd.to_numeric(company_sell_side.get("fiscal_year"), errors="coerce").eq(2026)
        ] if not company_sell_side.empty else company_sell_side
        company_revisions = sell_side_revisions.loc[sell_side_revisions["company"].eq(company)] if not sell_side_revisions.empty else pd.DataFrame()
        company_revisions = company_revisions.loc[
            pd.to_numeric(company_revisions.get("fiscal_year"), errors="coerce").eq(2026)
            & company_revisions.get("prior_report_date").notna()
        ] if not company_revisions.empty else company_revisions
        snapshot = _date(share.get("snapshot_date"))
        rows.append({
            "dataset_id": "airline_revenue_consensus_coverage",
            "company": company,
            "ticker": ticker,
            "market": market,
            "snapshot_date": snapshot,
            "fiscal_year": 2026,
            "source_layer": source_layer,
            "coverage_scope": scope,
            "source_quality": quality,
            "forecast_row_count": int(len(source)),
            "analyst_count": analyst_count,
            "forecast_date_min": forecast_min,
            "forecast_date_max": forecast_max,
            "native_unit": native_unit,
            "normalization_factor_to_native_mn": normalization_factor,
            "revenue_avg_native_mn": avg,
            "revenue_low_native_mn": low,
            "revenue_high_native_mn": high,
            "revision_history_available": revision_history,
            "sell_side_report_row_count": int(len(company_sell_side)),
            "sell_side_revision_row_count": int(len(company_revisions)),
            "sell_side_latest_report_date": _latest(company_sell_side, "report_date"),
            "source_url": source_url,
            "source_note": (
                "Coverage contract for revenue expectations. Direct rows are preferred; "
                "same-company cross-market fallback is explicitly labelled. Current vendor "
                "snapshots do not provide a complete consensus-vintage history."
            ),
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_revenue_consensus_coverage() -> pd.DataFrame:
    result = build_airline_revenue_consensus_coverage()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
