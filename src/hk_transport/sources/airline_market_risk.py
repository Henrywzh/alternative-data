"""Free historical market-risk and liquidity metrics for airline long/short work."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..config import NORMALIZED_DIR


OUTPUT_PATH = NORMALIZED_DIR / "airline_market_risk_metrics.csv"
MARKET_SNAPSHOT_PATH = NORMALIZED_DIR / "airline_market_expectations_snapshot.csv"
FX_PATH = NORMALIZED_DIR / "airline_fx_rates.parquet"

UNIVERSE = (
    ("0293.HK", "Cathay Pacific", "HK", "HKD", "^HSI"),
    ("0753.HK", "Air China", "HK", "HKD", "^HSI"),
    ("01055.HK", "China Southern Airlines", "HK", "HKD", "^HSI"),
    ("0670.HK", "China Eastern Airlines", "HK", "HKD", "^HSI"),
    ("601021.SH", "Spring Airlines", "CN_A", "RMB", "000300.SS"),
    ("603885.SH", "Juneyao Airlines", "CN_A", "RMB", "000300.SS"),
    ("600221.SH", "Hainan Airlines Holdings", "CN_A", "RMB", "000300.SS"),
)

YF_SYMBOLS = {
    "0293.HK": "0293.HK", "0753.HK": "0753.HK", "01055.HK": "1055.HK",
    "0670.HK": "0670.HK", "601021.SH": "601021.SS", "603885.SH": "603885.SS",
    "600221.SH": "600221.SS",
}
TICKER_ALIASES = {"00670.HK": "0670.HK"}

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "market", "native_currency", "yf_symbol",
    "benchmark_ticker", "snapshot_date", "window_start_date", "window_label",
    "last_close_native", "one_year_return_pct", "three_month_return_pct",
    "annualized_volatility_pct", "max_drawdown_pct", "drawdown_from_peak_pct",
    "beta_to_benchmark", "correlation_to_benchmark", "benchmark_one_year_return_pct",
    "benchmark_annualized_volatility_pct", "avg_daily_turnover_usd_mn_60d",
    "median_daily_turnover_usd_mn_60d", "median_turnover_to_market_cap_pct_60d",
    "market_cap_usd_mn", "borrow_data_available", "source_quality", "source_url",
    "source_note", "retrieved_at",
]


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _latest_fx(fx: pd.DataFrame | None, currency: str, as_of: pd.Timestamp) -> float | None:
    if currency == "USD":
        return 1.0
    if fx is None or fx.empty:
        return None
    pair = "USD_HKD" if currency == "HKD" else "USD_CNY"
    frame = fx.loc[fx["pair"].eq(pair)].copy()
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.loc[frame["observation_date"].le(as_of)].dropna(subset=["observation_date", "value"])
    if frame.empty:
        return None
    return float(frame.sort_values("observation_date").iloc[-1]["value"])


def _close_volume(downloaded: pd.DataFrame, symbol: str, field: str) -> pd.Series:
    if downloaded.empty:
        return pd.Series(dtype=float)
    try:
        if isinstance(downloaded.columns, pd.MultiIndex):
            series = downloaded[field][symbol]
        else:
            series = downloaded[field]
    except (KeyError, TypeError):
        return pd.Series(dtype=float)
    return pd.to_numeric(series, errors="coerce").dropna()


def _metric_row(
    *,
    item: tuple[str, str, str, str, str],
    downloaded: pd.DataFrame,
    fx_rates: pd.DataFrame | None,
    market_cap: float | None,
    retrieved: str,
) -> dict[str, Any] | None:
    ticker, company, market, currency, benchmark = item
    symbol = YF_SYMBOLS[ticker]
    close = _close_volume(downloaded, symbol, "Close")
    volume = _close_volume(downloaded, symbol, "Volume")
    benchmark_close = _close_volume(downloaded, benchmark, "Close")
    if close.empty or benchmark_close.empty:
        return None
    close = close.sort_index()
    benchmark_close = benchmark_close.sort_index()
    returns = close.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    benchmark_returns = benchmark_close.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    overlap = pd.concat([returns.rename("asset"), benchmark_returns.rename("benchmark")], axis=1).dropna()
    if overlap.empty:
        return None
    snapshot = close.index.max()
    window_start = close.index.min()
    fx = _latest_fx(fx_rates, currency, pd.Timestamp(snapshot))
    turnover = pd.Series(dtype=float)
    if not volume.empty:
        turnover = (close * volume).dropna().tail(60) / fx / 1_000_000 if fx else pd.Series(dtype=float)
    market_cap = _number(market_cap)
    rolling_peak = close.cummax()
    max_drawdown = float((close / rolling_peak - 1.0).min() * 100.0)
    benchmark_var = float(overlap["benchmark"].var())
    beta = float(overlap["asset"].cov(overlap["benchmark"]) / benchmark_var) if benchmark_var else None
    asset_return = float((close.iloc[-1] / close.iloc[0] - 1.0) * 100.0)
    three_month = close.tail(63)
    three_month_return = float((three_month.iloc[-1] / three_month.iloc[0] - 1.0) * 100.0) if len(three_month) > 1 else None
    benchmark_return = float((benchmark_close.iloc[-1] / benchmark_close.iloc[0] - 1.0) * 100.0)
    drawdown_from_peak = float((close.iloc[-1] / rolling_peak.iloc[-1] - 1.0) * 100.0)
    turnover_median = float(turnover.median()) if not turnover.empty else None
    return {
        "dataset_id": "airline_market_risk_metrics",
        "company": company, "ticker": ticker, "market": market, "native_currency": currency,
        "yf_symbol": symbol, "benchmark_ticker": benchmark, "snapshot_date": snapshot.strftime("%Y-%m-%d"),
        "window_start_date": window_start.strftime("%Y-%m-%d"), "window_label": "1y_daily",
        "last_close_native": float(close.iloc[-1]), "one_year_return_pct": asset_return,
        "three_month_return_pct": three_month_return,
        "annualized_volatility_pct": float(returns.std() * np.sqrt(252) * 100.0),
        "max_drawdown_pct": max_drawdown, "drawdown_from_peak_pct": drawdown_from_peak,
        "beta_to_benchmark": beta, "correlation_to_benchmark": float(overlap["asset"].corr(overlap["benchmark"])),
        "benchmark_one_year_return_pct": benchmark_return,
        "benchmark_annualized_volatility_pct": float(benchmark_returns.std() * np.sqrt(252) * 100.0),
        "avg_daily_turnover_usd_mn_60d": float(turnover.mean()) if not turnover.empty else None,
        "median_daily_turnover_usd_mn_60d": turnover_median,
        "median_turnover_to_market_cap_pct_60d": 100.0 * turnover_median / market_cap if turnover_median is not None and market_cap else None,
        "market_cap_usd_mn": market_cap,
        "borrow_data_available": False,
        "source_quality": "yfinance_discovery",
        "source_url": f"https://finance.yahoo.com/quote/{symbol}/history",
        "source_note": (
            "Daily Yahoo Finance price/volume discovery layer. Beta and correlation use the market benchmark "
            f"{benchmark}; turnover is converted with nearest-prior ECB FX. Borrow availability, borrow cost and short-sale constraints are not available from this free source."
        ),
        "retrieved_at": retrieved,
    }


def merge_market_risk_history(prior: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    result = pd.concat([prior, current], ignore_index=True)
    if result.empty:
        return result
    result["ticker"] = result["ticker"].replace(TICKER_ALIASES)
    key = ["ticker", "snapshot_date", "window_label"]
    return result.drop_duplicates(key, keep="last").sort_values(["ticker", "snapshot_date"]).reset_index(drop=True)


def fetch_airline_market_risk_metrics(*, period: str = "1y") -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("yfinance is required for airline market-risk metrics") from exc
    retrieved = datetime.now(timezone.utc).isoformat()
    symbols = list(dict.fromkeys([YF_SYMBOLS[ticker] for ticker, *_ in UNIVERSE] + ["^HSI", "000300.SS"]))
    downloaded = yf.download(symbols, period=period, interval="1d", auto_adjust=False, progress=False, threads=False)
    fx = pd.read_parquet(FX_PATH) if FX_PATH.exists() else None
    market = pd.read_csv(MARKET_SNAPSHOT_PATH) if MARKET_SNAPSHOT_PATH.exists() else pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for item in UNIVERSE:
        ticker, company, *_ = item
        market_rows = market.loc[market["ticker"].eq(ticker)] if not market.empty else pd.DataFrame()
        market_cap = market_rows.iloc[0].get("market_cap_usd_mn") if not market_rows.empty else None
        row = _metric_row(item=item, downloaded=downloaded, fx_rates=fx, market_cap=market_cap, retrieved=retrieved)
        if row is not None:
            rows.append(row)
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if OUTPUT_PATH.exists():
        result = merge_market_risk_history(pd.read_csv(OUTPUT_PATH), result)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def build_airline_market_risk_metrics(*, period: str = "1y") -> pd.DataFrame:
    """Build the current free market-risk snapshot.

    The yfinance pull is intentionally kept in the builder because the risk
    metrics are defined by the latest overlapping price window.
    """
    return fetch_airline_market_risk_metrics(period=period)


def source_path() -> Path:
    return OUTPUT_PATH
