"""Historical P/B diagnostics for priority airline market legs.

AkShare's public Baidu valuation endpoint exposes roughly one year of daily
P/B observations for the target securities. This is a useful asset-value
cross-check for capital-intensive airlines, but it is not a substitute for a
long P/S/P/E history. Equity denominators are selected using the latest
issuer report announced on or before the dated market observation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR

WORKING_SET_PATH = NORMALIZED_DIR / "airline_pair_thesis_working_set.csv"
DRIVERS_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
CATHAY_EQUITY_BASIS_PATH = NORMALIZED_DIR / "airline_cathay_equity_basis.csv"
PB_HISTORY_PATH = NORMALIZED_DIR / "airline_pb_history.csv"
MARKET_SNAPSHOT_PATH = NORMALIZED_DIR / "airline_market_snapshot.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_historical_pb_valuation.csv"

PB_CONFIG: dict[str, dict[str, str]] = {
    "0293.HK": {"company": "Cathay Pacific", "function": "stock_hk_valuation_baidu", "symbol": "00293"},
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


def _asset_price_map(working: pd.DataFrame, market_snapshot: pd.DataFrame | None = None) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for _, row in working.iterrows():
        result[_text(row.get("asset_a"))] = _num(row.get("current_price_a_native"))
        result[_text(row.get("asset_b"))] = _num(row.get("current_price_b_native"))
    if market_snapshot is not None and not market_snapshot.empty:
        for _, row in market_snapshot.iterrows():
            asset = _text(row.get("ticker"))
            if asset and result.get(asset) is None:
                result[asset] = _num(row.get("latest_price_native"))
    return result


def _equity_frame(drivers: pd.DataFrame, cathay_basis: pd.DataFrame | None) -> pd.DataFrame:
    """Combine legacy mainland equity rows with official Cathay anchors."""

    frames: list[pd.DataFrame] = []
    if not drivers.empty and {"company", "metric"}.issubset(drivers.columns):
        frames.append(drivers.loc[drivers["metric"].eq("equity_attributable")].copy())
    if cathay_basis is not None and not cathay_basis.empty and {"company", "metric"}.issubset(cathay_basis.columns):
        frames.append(cathay_basis.loc[cathay_basis["metric"].eq("equity_attributable")].copy())
    if not frames:
        return pd.DataFrame()
    result = pd.concat(frames, ignore_index=True, sort=False)
    result["period_end_parsed"] = pd.to_datetime(result.get("period_end"), errors="coerce")
    result["announced_at_parsed"] = pd.to_datetime(result.get("announced_at"), errors="coerce")
    return result


def _equity_row_as_of(equity: pd.DataFrame, company: str, as_of: pd.Timestamp) -> pd.Series:
    if equity.empty or pd.isna(as_of):
        return pd.Series(dtype=object)
    frame = equity.loc[equity["company"].astype(str).eq(company)].copy()
    frame = frame.loc[
        frame["announced_at_parsed"].notna()
        & frame["announced_at_parsed"].le(as_of)
    ]
    if frame.empty:
        return pd.Series(dtype=object)
    return frame.sort_values(["period_end_parsed", "announced_at_parsed"]).iloc[-1]


def _annotate_pb_history(history: pd.DataFrame, equity: pd.DataFrame) -> pd.DataFrame:
    """Attach the latest public equity anchor to each dated P/B observation."""

    if history.empty or equity.empty:
        return history
    result = history.copy()
    result["observation_date"] = pd.to_datetime(result["observation_date"], errors="coerce")
    for column in (
        "equity_basis_period",
        "equity_basis_period_end",
        "equity_basis_announced_at",
        "equity_basis_usd_mn",
        "equity_basis_pit_status",
    ):
        result[column] = None
    for index, row in result.iterrows():
        company = _text(row.get("company"))
        selected = _equity_row_as_of(equity, company, row.get("observation_date"))
        if selected.empty:
            result.at[index, "equity_basis_pit_status"] = "no_announced_equity_basis_available"
            continue
        result.at[index, "equity_basis_period"] = _text(selected.get("statement_period"))
        result.at[index, "equity_basis_period_end"] = _text(selected.get("period_end"))
        result.at[index, "equity_basis_announced_at"] = _text(selected.get("announced_at"))
        result.at[index, "equity_basis_usd_mn"] = _num(selected.get("value_usd"))
        result.at[index, "equity_basis_pit_status"] = "announced_on_or_before_observation_date"
    return result


def build_airline_historical_pb_valuation(
    *,
    pb_history: pd.DataFrame | None = None,
    drivers: pd.DataFrame | None = None,
    cathay_basis: pd.DataFrame | None = None,
    working: pd.DataFrame | None = None,
    market_snapshot: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build one valuation-summary row per market leg in the priority set."""

    pb_history = pb_history if pb_history is not None else pd.read_csv(PB_HISTORY_PATH)
    drivers = drivers if drivers is not None else pd.read_csv(DRIVERS_PATH)
    cathay_basis = (
        cathay_basis
        if cathay_basis is not None
        else (pd.read_csv(CATHAY_EQUITY_BASIS_PATH) if CATHAY_EQUITY_BASIS_PATH.exists() else pd.DataFrame())
    )
    working = working if working is not None else pd.read_csv(WORKING_SET_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    prices = _asset_price_map(working, market_snapshot)
    working_assets = set(working.get("asset_a", pd.Series(dtype=str)).astype(str)) | set(working.get("asset_b", pd.Series(dtype=str)).astype(str))
    equity = _equity_frame(drivers, cathay_basis)
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
        equity_row = _equity_row_as_of(equity, company, hist["observation_date"].max() if not hist.empty else pd.NaT)
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
                "current_price_source": "airline_pair_thesis_working_set" if asset in working_assets else "airline_market_snapshot",
                "pb_target_return_p25_pct": target_returns["p25"],
                "pb_target_return_median_pct": target_returns["median"],
                "pb_target_return_p75_pct": target_returns["p75"],
                "equity_basis_period": equity_period,
                "equity_basis_period_end": equity_period_end,
                "equity_basis_announced_at": equity_announced,
                "equity_basis_usd_mn": equity_usd,
                "valuation_status": (
                    "historical_1y_pb_diagnostic_using_pit_primary_equity"
                    if company == "Cathay Pacific" and current_pb is not None and equity_usd is not None
                    else "historical_1y_pb_diagnostic_using_latest_primary_equity_pending_1H2026_refresh"
                    if current_pb is not None and equity_usd is not None
                    else "missing_pb_or_equity_basis"
                ),
                "point_in_time_status": (
                    "market_pb_history_is_dated; equity_basis_announced_on_or_before_pb_observation_end"
                    if not equity_row.empty
                    else "market_pb_history_is_dated; no_announced_equity_basis_on_or_before_pb_observation_end"
                ),
                "source_quality": "akshare_baidu_pb_plus_primary_issuer_equity",
                "source_url": f"akshare.{config['function']}(symbol={config['symbol']}, indicator=市净率);{DRIVERS_PATH.name};{CATHAY_EQUITY_BASIS_PATH.name}",
                "source_note": "P/B history is an approximately one-year public Baidu valuation series. Equity basis is selected by announcement date; target returns are relative P/B diagnostics, not an approved fair value and not a substitute for historical P/S/P/E.",
                "retrieved_at": retrieved,
            }
        )

    result = pd.DataFrame(rows)
    return result


def fetch_airline_historical_pb_valuation() -> pd.DataFrame:
    """Fetch the public P/B history and build the normalized diagnostic."""

    import akshare as ak

    from .airline_cathay_equity_basis import fetch_airline_cathay_equity_basis

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
    drivers = pd.read_csv(DRIVERS_PATH)
    cathay_basis = fetch_airline_cathay_equity_basis()
    equity = _equity_frame(drivers, cathay_basis)
    history = _annotate_pb_history(history, equity)
    history.to_csv(PB_HISTORY_PATH, index=False)
    market_snapshot = pd.read_csv(MARKET_SNAPSHOT_PATH) if MARKET_SNAPSHOT_PATH.exists() else pd.DataFrame()
    result = build_airline_historical_pb_valuation(
        market_snapshot=market_snapshot,
        drivers=drivers,
        cathay_basis=cathay_basis,
        retrieved_at=retrieved,
    )
    result.to_csv(OUTPUT_PATH, index=False)
    return result
