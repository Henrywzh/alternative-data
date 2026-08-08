"""Pair-level correlation and beta-hedge diagnostics for airline long/short work."""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..config import NORMALIZED_DIR
from .airline_market_risk import FX_PATH, TICKER_ALIASES, UNIVERSE, YF_SYMBOLS, _close_volume, _latest_fx


OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_risk_metrics.csv"

OUTPUT_COLUMNS = [
    "dataset_id", "asset_a", "company_a", "market_a", "asset_b", "company_b", "market_b",
    "same_market", "snapshot_date", "window_start_date", "window_label", "observations",
    "correlation_a_b", "beta_a_to_b", "beta_b_to_a", "hedged_spread_vol_a_minus_beta_b_pct",
    "hedged_spread_vol_b_minus_beta_a_pct", "hedged_spread_max_drawdown_a_minus_beta_b_pct",
    "hedged_spread_max_drawdown_b_minus_beta_a_pct",
    "median_turnover_a_usd_mn_60d", "median_turnover_b_usd_mn_60d",
    "borrow_data_available_a", "borrow_data_available_b", "source_quality", "source_note",
    "retrieved_at",
]


def _spread_max_drawdown(returns: pd.Series) -> float | None:
    if returns.empty:
        return None
    wealth = (1.0 + returns).cumprod()
    return float((wealth / wealth.cummax() - 1.0).min() * 100.0)


def _median_turnover(
    downloaded: pd.DataFrame,
    symbol: str,
    currency: str,
    fx_rates: pd.DataFrame | None,
    as_of: pd.Timestamp,
) -> float | None:
    close = _close_volume(downloaded, symbol, "Close")
    volume = _close_volume(downloaded, symbol, "Volume")
    if close.empty or volume.empty:
        return None
    fx = _latest_fx(fx_rates, currency, as_of)
    turnover = (close * volume).dropna().tail(60) / fx if fx else pd.Series(dtype=float)
    return float(turnover.median() / 1_000_000) if not turnover.empty else None


def merge_pair_risk_history(prior: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    result = pd.concat([prior, current], ignore_index=True)
    if result.empty:
        return result
    result["asset_a"] = result["asset_a"].replace(TICKER_ALIASES)
    result["asset_b"] = result["asset_b"].replace(TICKER_ALIASES)
    key = ["asset_a", "asset_b", "snapshot_date", "window_label"]
    return result.drop_duplicates(key, keep="last").sort_values(["asset_a", "asset_b"]).reset_index(drop=True)


def fetch_airline_pair_risk_metrics(*, period: str = "1y") -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("yfinance is required for airline pair-risk metrics") from exc
    retrieved = datetime.now(timezone.utc).isoformat()
    symbols = [YF_SYMBOLS[ticker] for ticker, *_ in UNIVERSE]
    downloaded = yf.download(symbols, period=period, interval="1d", auto_adjust=False, progress=False, threads=False)
    fx_rates = pd.read_parquet(FX_PATH) if FX_PATH.exists() else None
    normalized = [
        {"asset": ticker, "company": company, "market": market, "currency": currency, "symbol": YF_SYMBOLS[ticker]}
        for ticker, company, market, currency, *_ in UNIVERSE
    ]
    rows: list[dict[str, Any]] = []
    for first, second in combinations(normalized, 2):
        a = _close_volume(downloaded, first["symbol"], "Close").sort_index()
        b = _close_volume(downloaded, second["symbol"], "Close").sort_index()
        overlap = pd.concat([a.pct_change().rename("a"), b.pct_change().rename("b")], axis=1).dropna()
        if len(overlap) < 30:
            continue
        var_a = float(overlap["a"].var())
        var_b = float(overlap["b"].var())
        beta_a_to_b = float(overlap["a"].cov(overlap["b"]) / var_b) if var_b else None
        beta_b_to_a = float(overlap["a"].cov(overlap["b"]) / var_a) if var_a else None
        spread_a = overlap["a"] - beta_a_to_b * overlap["b"] if beta_a_to_b is not None else pd.Series(dtype=float)
        spread_b = overlap["b"] - beta_b_to_a * overlap["a"] if beta_b_to_a is not None else pd.Series(dtype=float)
        rows.append({
            "dataset_id": "airline_pair_risk_metrics",
            "asset_a": first["asset"], "company_a": first["company"], "market_a": first["market"],
            "asset_b": second["asset"], "company_b": second["company"], "market_b": second["market"],
            "same_market": first["market"] == second["market"],
            "snapshot_date": overlap.index.max().strftime("%Y-%m-%d"),
            "window_start_date": overlap.index.min().strftime("%Y-%m-%d"),
            "window_label": "1y_daily", "observations": len(overlap),
            "correlation_a_b": float(overlap["a"].corr(overlap["b"])),
            "beta_a_to_b": beta_a_to_b, "beta_b_to_a": beta_b_to_a,
            "hedged_spread_vol_a_minus_beta_b_pct": float(spread_a.std() * np.sqrt(252) * 100.0) if not spread_a.empty else None,
            "hedged_spread_vol_b_minus_beta_a_pct": float(spread_b.std() * np.sqrt(252) * 100.0) if not spread_b.empty else None,
            "hedged_spread_max_drawdown_a_minus_beta_b_pct": _spread_max_drawdown(spread_a),
            "hedged_spread_max_drawdown_b_minus_beta_a_pct": _spread_max_drawdown(spread_b),
            "median_turnover_a_usd_mn_60d": _median_turnover(downloaded, first["symbol"], first["currency"], fx_rates, pd.Timestamp(overlap.index.max())),
            "median_turnover_b_usd_mn_60d": _median_turnover(downloaded, second["symbol"], second["currency"], fx_rates, pd.Timestamp(overlap.index.max())),
            "borrow_data_available_a": False, "borrow_data_available_b": False,
            "source_quality": "yfinance_discovery",
            "source_note": (
                "Pair diagnostics use overlapping Yahoo Finance daily returns. Beta hedge ratios are mechanical OLS-style ratios; "
                "they are not factor-model neutralization and borrow/short-sale feasibility is unavailable."
            ),
            "retrieved_at": retrieved,
        })
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if OUTPUT_PATH.exists():
        result = merge_pair_risk_history(pd.read_csv(OUTPUT_PATH), result)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
