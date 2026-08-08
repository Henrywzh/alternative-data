"""Historical P/B diagnostics for priority airline market legs.

AkShare's public Baidu valuation endpoint exposes roughly one year of daily
P/B observations for the target securities. This is a useful asset-value
cross-check for capital-intensive airlines, but it is not a substitute for a
long P/S/P/E history: the equity basis below is the latest available primary
issuer equity row and must be refreshed after 1H2026 filings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR

WORKING_SET_PATH = NORMALIZED_DIR / "airline_pair_thesis_working_set.csv"
DRIVERS_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
PB_HISTORY_PATH = NORMALIZED_DIR / "airline_pb_history.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_historical_pb_valuation.csv"

PB_CONFIG: dict[str, dict[str, str]] = {
    "01055.HK": {"company": "China Southern Airlines", "function": "stock_hk_valuation_baidu", "symbol": "01055"},
    "0670.HK": {"company": "China Eastern Airlines", "function": "stock_hk_valuation_baidu", "symbol": "00670"},
    "0753.HK": {"company": "Air China", "function": "stock_hk_valuation_baidu", "symbol": "00753"},
    "600221.SH": {"company": "Hainan Airlines Holdings", "function": "stock_zh_valuation_baidu", "symbol": "600221"},
    "601021.SH": {"company": "Spring Airlines", "function": "stock_zh_valuation_baidu", "symbol": "601021"},
    "603885.SH": {"company": "Juneyao Airlines", "function": "stock_zh_valuation_baidu", "symbol": "603885"},
}


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def _asset_price_map(working: pd.DataFrame) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for _, row in working.iterrows():
        result[_text(row.get("asset_a"))] = _num(row.get("current_price_a_native"))
        result[_text(row.get("asset_b"))] = _num(row.get("current_price_b_native"))
    return result


def _equity_rows(drivers: pd.DataFrame) -> dict[str, pd.Series]:
    result: dict[str, pd.Series] = {}
    if drivers.empty:
        return result
    frame = drivers[drivers["metric"].eq("equity_attributable")].copy()
    frame["period_end_parsed"] = pd.to_datetime(frame["period_end"], errors="coerce")
    for company, group in frame.groupby("company"):
        result[str(company)] = group.sort_values("period_end_parsed").iloc[-1]
    return result


def build_airline_historical_pb_valuation(
    *,
    pb_history: pd.DataFrame | None = None,
    drivers: pd.DataFrame | None = None,
    working: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build one valuation-summary row per market leg in the priority set."""

    pb_history = pb_history if pb_history is not None else pd.read_csv(PB_HISTORY_PATH)
    drivers = drivers if drivers is not None else pd.read_csv(DRIVERS_PATH)
    working = working if working is not None else pd.read_csv(WORKING_SET_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    prices = _asset_price_map(working)
    equity = _equity_rows(drivers)
    rows: list[dict[str, Any]] = []

    for asset, config in PB_CONFIG.items():
        hist = pb_history[pb_history["asset"].eq(asset)].copy() if not pb_history.empty else pd.DataFrame()
        hist["observation_date"] = pd.to_datetime(hist.get("observation_date"), errors="coerce")
        hist["pb"] = pd.to_numeric(hist.get("pb"), errors="coerce")
        hist = hist.dropna(subset=["observation_date", "pb"])
        hist = hist.loc[hist["pb"].gt(0)].sort_values("observation_date")
        latest = hist.iloc[-1] if not hist.empty else pd.Series(dtype=object)
        current_pb = _num(latest.get("pb"))
        price = prices.get(asset)
        company = config["company"]
        equity_row = equity.get(company, pd.Series(dtype=object))
        equity_usd = _num(equity_row.get("value_usd"))
        equity_period = _text(equity_row.get("statement_period"))
        equity_period_end = _text(equity_row.get("period_end"))
        equity_announced = _text(equity_row.get("announced_at"))
        target_values = {
            "p25": float(hist["pb"].quantile(0.25)) if not hist.empty else None,
            "median": float(hist["pb"].median()) if not hist.empty else None,
            "p75": float(hist["pb"].quantile(0.75)) if not hist.empty else None,
        }
        target_returns = {
            key: (100.0 * value / current_pb - 100.0) if value is not None and current_pb not in (None, 0) else None
            for key, value in target_values.items()
        }
        current_percentile = (
            100.0 * float((hist["pb"] <= current_pb).mean())
            if current_pb is not None and not hist.empty
            else None
        )
        rows.append(
            {
                "dataset_id": "airline_historical_pb_valuation",
                "asset": asset,
                "company": company,
                "observation_start_date": hist["observation_date"].min().date().isoformat() if not hist.empty else None,
                "observation_end_date": hist["observation_date"].max().date().isoformat() if not hist.empty else None,
                "pb_observation_count": int(len(hist)),
                "current_pb": current_pb,
                "pb_min_1y": float(hist["pb"].min()) if not hist.empty else None,
                "pb_p25_1y": target_values["p25"],
                "pb_median_1y": target_values["median"],
                "pb_p75_1y": target_values["p75"],
                "pb_max_1y": float(hist["pb"].max()) if not hist.empty else None,
                "current_pb_percentile_1y": current_percentile,
                "current_price_native": price,
                "current_price_source": "airline_pair_thesis_working_set",
                "pb_target_return_p25_pct": target_returns["p25"],
                "pb_target_return_median_pct": target_returns["median"],
                "pb_target_return_p75_pct": target_returns["p75"],
                "equity_basis_period": equity_period,
                "equity_basis_period_end": equity_period_end,
                "equity_basis_announced_at": equity_announced,
                "equity_basis_usd_mn": equity_usd,
                "valuation_status": "historical_1y_pb_diagnostic_using_latest_primary_equity_pending_1H2026_refresh" if current_pb is not None and equity_usd is not None else "missing_pb_or_equity_basis",
                "point_in_time_status": "market_pb_history_is_dated; equity_basis_is_latest_available_primary_report_not_1H2026",
                "source_quality": "akshare_baidu_pb_plus_primary_issuer_equity",
                "source_url": f"akshare.{config['function']}(symbol={config['symbol']}, indicator=市净率);airline_official_report_drivers.csv",
                "source_note": "P/B history is an approximately one-year public Baidu valuation series. Target returns are relative P/B diagnostics; they are not an approved fair value and do not establish P/S/P/E history.",
                "retrieved_at": retrieved,
            }
        )

    result = pd.DataFrame(rows)
    return result


def fetch_airline_historical_pb_valuation() -> pd.DataFrame:
    """Fetch the public P/B history and build the normalized diagnostic."""

    import akshare as ak

    retrieved = datetime.now(timezone.utc).isoformat()
    history_rows: list[dict[str, object]] = []
    for asset, config in PB_CONFIG.items():
        frame = getattr(ak, config["function"])(symbol=config["symbol"], indicator="市净率")
        if frame is None or frame.empty or not {"date", "value"}.issubset(frame.columns):
            continue
        for _, row in frame.iterrows():
            history_rows.append(
                {
                    "dataset_id": "airline_pb_history",
                    "asset": asset,
                    "company": config["company"],
                    "observation_date": pd.to_datetime(row["date"], errors="coerce").date().isoformat(),
                    "pb": _num(row["value"]),
                    "source_quality": "akshare_baidu_valuation_history",
                    "source_url": f"akshare.{config['function']}(symbol={config['symbol']}, indicator=市净率)",
                    "retrieved_at": retrieved,
                }
            )
    history = pd.DataFrame(history_rows)
    history.to_csv(PB_HISTORY_PATH, index=False)
    result = build_airline_historical_pb_valuation(retrieved_at=retrieved)
    result.to_csv(OUTPUT_PATH, index=False)
    return result
