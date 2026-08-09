"""Cross-sectional factor residual tests for airline pair spreads.

This is a transparent free-data diagnostic, not a vendor Barra model.  It
builds market, size, value, momentum and low-volatility factor returns from
the seven-airline universe, then regresses each mechanical beta-hedged pair
spread on those factors.  Static size/value exposures are current-snapshot
proxies and are labelled accordingly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..config import NORMALIZED_DIR, RAW_DIR


PAIR_RISK_PATH = NORMALIZED_DIR / "airline_pair_risk_metrics.csv"
MARKET_SNAPSHOT_PATH = NORMALIZED_DIR / "airline_market_snapshot.csv"
PB_PATH = NORMALIZED_DIR / "airline_historical_pb_valuation.csv"
RAW_BARS_PATH = RAW_DIR / "airline_factor_test_bars.parquet"
FACTOR_SERIES_PATH = NORMALIZED_DIR / "airline_factor_return_series.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_factor_residual_test.csv"

YF_SYMBOLS = {
    "0293.HK": "0293.HK",
    "0753.HK": "0753.HK",
    "01055.HK": "1055.HK",
    "0670.HK": "0670.HK",
    "601021.SH": "601021.SS",
    "603885.SH": "603885.SS",
    "600221.SH": "600221.SS",
}
ASSET_TO_YF = YF_SYMBOLS

FACTOR_COLUMNS = [
    "market_factor_return",
    "size_factor_return",
    "value_factor_return",
    "momentum_factor_return",
    "low_vol_factor_return",
]

OUTPUT_COLUMNS = [
    "dataset_id",
    "pair_id",
    "asset_a",
    "company_a",
    "asset_b",
    "company_b",
    "same_market",
    "observation_start_date",
    "observation_end_date",
    "observations",
    "hedge_ratio_a_to_b",
    "static_log_size_gap_a_minus_b",
    "static_pb_gap_a_minus_b",
    "alpha_daily_pct",
    "alpha_annualized_pct",
    "factor_beta_market",
    "factor_beta_size",
    "factor_beta_value",
    "factor_beta_momentum",
    "factor_beta_low_vol",
    "r_squared",
    "residual_volatility_annualized_pct",
    "residual_cumulative_return_pct",
    "residual_max_drawdown_pct",
    "equal_notional_alpha_annualized_pct",
    "regression_status",
    "factor_construction_status",
    "point_in_time_status",
    "source_quality",
    "source_paths",
    "source_note",
    "retrieved_at",
]


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _normalize_bars(bars: pd.DataFrame) -> pd.DataFrame:
    required = {"ticker", "adj_close"}
    if not required.issubset(bars.columns):
        raise ValueError(f"Factor bars are missing columns: {sorted(required.difference(bars.columns))}")
    frame = bars.copy()
    if "observation_date" in frame.columns:
        frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
    elif "timestamp_utc" in frame.columns:
        frame["observation_date"] = pd.to_datetime(frame["timestamp_utc"], errors="coerce").dt.tz_localize(None)
    else:
        raise ValueError("Factor bars require observation_date or timestamp_utc")
    frame["adj_close"] = pd.to_numeric(frame["adj_close"], errors="coerce")
    frame = frame.loc[frame["ticker"].isin(set(YF_SYMBOLS.values()))]
    return frame.dropna(subset=["observation_date", "adj_close"]).sort_values(["observation_date", "ticker"])


def _portfolio_spread(returns: pd.Series, scores: pd.Series, *, low_is_long: bool) -> float | None:
    data = pd.concat([returns.rename("return"), scores.rename("score")], axis=1).dropna()
    if len(data) < 4:
        return None
    ordered = data.sort_values("score", ascending=low_is_long)
    half = max(1, len(ordered) // 2)
    long_leg = ordered.iloc[:half]["return"].mean()
    short_leg = ordered.iloc[-half:]["return"].mean()
    return float(long_leg - short_leg)


def _build_factor_series(prices: pd.DataFrame, market_caps: pd.Series, pb_values: pd.Series) -> pd.DataFrame:
    returns = prices.pct_change(fill_method=None)
    factors = pd.DataFrame(index=returns.index)
    factors["market_factor_return"] = returns.mean(axis=1, skipna=True)
    factors["size_factor_return"] = returns.apply(
        lambda row: _portfolio_spread(row, market_caps, low_is_long=True), axis=1
    )
    factors["value_factor_return"] = returns.apply(
        lambda row: _portfolio_spread(row, pb_values, low_is_long=True), axis=1
    )

    momentum_signal = prices.pct_change(126, fill_method=None).shift(1)
    volatility_signal = returns.rolling(20, min_periods=20).std().shift(1)
    factors["momentum_factor_return"] = [
        _portfolio_spread(returns.loc[date], momentum_signal.loc[date], low_is_long=False)
        for date in returns.index
    ]
    factors["low_vol_factor_return"] = [
        _portfolio_spread(returns.loc[date], volatility_signal.loc[date], low_is_long=True)
        for date in returns.index
    ]
    return factors.dropna(subset=FACTOR_COLUMNS, how="all")


def _max_drawdown(returns: pd.Series) -> float | None:
    if returns.empty:
        return None
    curve = (1.0 + returns.fillna(0.0)).cumprod()
    return float((curve / curve.cummax() - 1.0).min() * 100.0)


def _regress(y: pd.Series, factors: pd.DataFrame) -> dict[str, Any]:
    frame = pd.concat([y.rename("spread"), factors[FACTOR_COLUMNS]], axis=1).dropna()
    nobs = len(frame)
    if nobs == 0:
        return {"observations": 0, "regression_status": "insufficient_observations"}
    x = np.column_stack([np.ones(nobs), frame[FACTOR_COLUMNS].to_numpy(dtype=float)])
    target = frame["spread"].to_numpy(dtype=float)
    coefficients, *_ = np.linalg.lstsq(x, target, rcond=None)
    fitted = x @ coefficients
    residual = target - fitted
    total_ss = float(((target - target.mean()) ** 2).sum())
    r_squared = 1.0 - float((residual**2).sum()) / total_ss if total_ss > 0 else None
    return {
        "observations": nobs,
        "observation_start_date": frame.index.min().date().isoformat(),
        "observation_end_date": frame.index.max().date().isoformat(),
        "alpha_daily_pct": float(coefficients[0] * 100.0),
        "alpha_annualized_pct": float(coefficients[0] * 252.0 * 100.0),
        "factor_beta_market": float(coefficients[1]),
        "factor_beta_size": float(coefficients[2]),
        "factor_beta_value": float(coefficients[3]),
        "factor_beta_momentum": float(coefficients[4]),
        "factor_beta_low_vol": float(coefficients[5]),
        "r_squared": r_squared,
        "residual_volatility_annualized_pct": float(np.std(residual, ddof=1) * np.sqrt(252.0) * 100.0) if nobs > 1 else None,
        "residual_cumulative_return_pct": float((np.prod(1.0 + residual) - 1.0) * 100.0),
        "residual_max_drawdown_pct": _max_drawdown(pd.Series(residual, index=frame.index)),
        "regression_status": "estimated" if nobs >= 60 else "low_observation_count",
    }


def build_airline_pair_factor_residual_test(
    *,
    bars: pd.DataFrame,
    pair_risk: pd.DataFrame,
    market_snapshot: pd.DataFrame,
    pb_valuation: pd.DataFrame,
    retrieved_at: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build factor returns and residual diagnostics from long-form price bars."""

    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    bars = _normalize_bars(bars)
    prices = bars.pivot_table(index="observation_date", columns="ticker", values="adj_close", aggfunc="last")
    prices = prices.sort_index()
    # The fundamental/market snapshot uses exchange-qualified asset IDs for
    # A-shares (e.g. 601021.SH), while Yahoo uses .SS (601021.SS).  Bridge
    # before reindexing; otherwise the size factor silently becomes all-NA.
    market_caps_raw = market_snapshot.set_index("ticker")["market_cap_usd_mn"].map(_num)
    market_caps = pd.Series(
        {YF_SYMBOLS.get(str(asset), str(asset)): value for asset, value in market_caps_raw.items()}
    )
    pb_values = pb_valuation.set_index("asset")["current_pb"].map(_num)
    market_caps = market_caps.reindex(list(YF_SYMBOLS.values()))
    pb_values = pb_values.reindex(list(YF_SYMBOLS.keys()))
    pb_values.index = [ASSET_TO_YF[asset] for asset in pb_values.index]
    factors = _build_factor_series(prices, market_caps, pb_values)
    factor_output = factors.reset_index().rename(columns={"observation_date": "observation_date"})
    factor_output["retrieved_at"] = retrieved

    rows: list[dict[str, Any]] = []
    for _, pair in pair_risk.iterrows():
        asset_a, asset_b = str(pair["asset_a"]), str(pair["asset_b"])
        yf_a, yf_b = ASSET_TO_YF.get(asset_a), ASSET_TO_YF.get(asset_b)
        if yf_a not in prices.columns or yf_b not in prices.columns:
            continue
        hedge = _num(pair.get("beta_a_to_b"))
        if hedge is None or hedge <= 0:
            a_ret, b_ret = prices[yf_a].pct_change(fill_method=None), prices[yf_b].pct_change(fill_method=None)
            hedge = float(a_ret.cov(b_ret) / b_ret.var()) if b_ret.var() else 1.0
        equal_spread = prices[yf_a].pct_change(fill_method=None) - prices[yf_b].pct_change(fill_method=None)
        beta_spread = prices[yf_a].pct_change(fill_method=None) - hedge * prices[yf_b].pct_change(fill_method=None)
        model = _regress(beta_spread, factors)
        equal_model = _regress(equal_spread, factors)
        cap_a, cap_b = _num(market_caps.get(yf_a)), _num(market_caps.get(yf_b))
        pb_a, pb_b = _num(pb_values.get(yf_a)), _num(pb_values.get(yf_b))
        rows.append(
            {
                "dataset_id": "airline_pair_factor_residual_test",
                "pair_id": str(pair.get("pair_id", "__".join(sorted([asset_a, asset_b])))),
                "asset_a": asset_a,
                "company_a": pair["company_a"],
                "asset_b": asset_b,
                "company_b": pair["company_b"],
                "same_market": pair.get("same_market"),
                "observation_start_date": model.get("observation_start_date"),
                "observation_end_date": model.get("observation_end_date"),
                "observations": model.get("observations", 0),
                "hedge_ratio_a_to_b": hedge,
                "static_log_size_gap_a_minus_b": np.log(cap_a) - np.log(cap_b) if cap_a and cap_b else None,
                "static_pb_gap_a_minus_b": pb_a - pb_b if pb_a is not None and pb_b is not None else None,
                "alpha_daily_pct": model.get("alpha_daily_pct"),
                "alpha_annualized_pct": model.get("alpha_annualized_pct"),
                "factor_beta_market": model.get("factor_beta_market"),
                "factor_beta_size": model.get("factor_beta_size"),
                "factor_beta_value": model.get("factor_beta_value"),
                "factor_beta_momentum": model.get("factor_beta_momentum"),
                "factor_beta_low_vol": model.get("factor_beta_low_vol"),
                "r_squared": model.get("r_squared"),
                "residual_volatility_annualized_pct": model.get("residual_volatility_annualized_pct"),
                "residual_cumulative_return_pct": model.get("residual_cumulative_return_pct"),
                "residual_max_drawdown_pct": model.get("residual_max_drawdown_pct"),
                "equal_notional_alpha_annualized_pct": equal_model.get("alpha_annualized_pct"),
                "regression_status": model.get("regression_status", "insufficient_observations"),
                "factor_construction_status": "seven_airline_cross_sectional_portfolios",
                "point_in_time_status": "price_history_dated; size_and_value_exposures_use_current_snapshot",
                "source_quality": "derived_free_cross_sectional_factor_residual_test",
                "source_paths": f"{RAW_BARS_PATH};{PAIR_RISK_PATH};{MARKET_SNAPSHOT_PATH};{PB_PATH}",
                "source_note": (
                    "Beta-hedged spread regressed on market, size, value, momentum and low-volatility portfolios "
                    "formed from the seven-airline universe. This is a transparent free-data residual test, not "
                    "a formal Barra exposure file; static size/value rankings are current-snapshot proxies and "
                    "the result is not a trade recommendation."
                ),
                "retrieved_at": retrieved,
            }
        )
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS), factor_output


def fetch_airline_pair_factor_residual_test(*, period: str = "5y") -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("yfinance is required for the factor residual test") from exc
    retrieved = datetime.now(timezone.utc).isoformat()
    symbols = list(YF_SYMBOLS.values())
    downloaded = yf.download(symbols, period=period, interval="1d", auto_adjust=False, progress=False, threads=False)
    if downloaded.empty:
        raise ValueError("yfinance returned no daily bars for the airline factor test")
    field = "Adj Close" if "Adj Close" in downloaded.columns else "Close"
    rows: list[dict[str, object]] = []
    if isinstance(downloaded.columns, pd.MultiIndex):
        for symbol in symbols:
            if (field, symbol) not in downloaded.columns:
                continue
            series = downloaded[field][symbol]
            for date, value in series.dropna().items():
                rows.append({"ticker": symbol, "interval": "1d", "observation_date": pd.Timestamp(date).date().isoformat(), "adj_close": float(value), "captured_at": retrieved})
    else:
        symbol = symbols[0]
        for date, value in downloaded[field].dropna().items():
            rows.append({"ticker": symbol, "interval": "1d", "observation_date": pd.Timestamp(date).date().isoformat(), "adj_close": float(value), "captured_at": retrieved})
    bars = pd.DataFrame(rows)
    RAW_BARS_PATH.parent.mkdir(parents=True, exist_ok=True)
    bars.to_parquet(RAW_BARS_PATH, index=False)
    result, factors = build_airline_pair_factor_residual_test(
        bars=bars,
        pair_risk=pd.read_csv(PAIR_RISK_PATH),
        market_snapshot=pd.read_csv(MARKET_SNAPSHOT_PATH),
        pb_valuation=pd.read_csv(PB_PATH),
        retrieved_at=retrieved,
    )
    factors.to_csv(FACTOR_SERIES_PATH, index=False)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
