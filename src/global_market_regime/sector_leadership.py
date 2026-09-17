"""US sector-ETF leadership versus a broad benchmark."""

from __future__ import annotations

from typing import Any, Sequence

import pandas as pd

from .config import SECTOR_LEADERSHIP_BENCHMARK, SECTOR_LEADERSHIP_EXPOSURES


def _clean_prices(prices: pd.DataFrame, exposure_ids: Sequence[str]) -> pd.DataFrame:
    if prices is None or prices.empty:
        return pd.DataFrame(columns=["date", "exposure_id", "close"])
    required = {"date", "exposure_id", "close"}
    if not required.issubset(prices.columns):
        return pd.DataFrame(columns=["date", "exposure_id", "close"])
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["exposure_id"] = frame["exposure_id"].astype(str)
    return (
        frame.loc[frame["exposure_id"].isin([str(item) for item in exposure_ids])]
        .dropna(subset=["date", "exposure_id", "close"])
        .loc[lambda value: value["close"].gt(0)]
        .sort_values(["exposure_id", "date"], kind="mergesort")
        .drop_duplicates(["exposure_id", "date"], keep="last")
        .reset_index(drop=True)
    )


def _window_return(closes: pd.Series, window: int) -> float | None:
    if len(closes) <= window:
        return None
    start = float(closes.iloc[-window - 1])
    if start <= 0:
        return None
    return (float(closes.iloc[-1]) / start - 1.0) * 100.0


def _annualized_sma_slope(closes: pd.Series, window: int = 200) -> float | None:
    if len(closes) < window + 5:
        return None
    sma = closes.rolling(window).mean().dropna()
    if len(sma) < 6:
        return None
    start = float(sma.iloc[-6])
    end = float(sma.iloc[-1])
    if start <= 0:
        return None
    daily = (end / start) ** (1.0 / 5.0) - 1.0
    return ((1.0 + daily) ** 252 - 1.0) * 100.0


def build_sector_leadership(
    prices: pd.DataFrame,
    *,
    sector_ids: Sequence[str] = SECTOR_LEADERSHIP_EXPOSURES,
    benchmark_id: str = SECTOR_LEADERSHIP_BENCHMARK,
) -> pd.DataFrame:
    """Latest absolute and relative returns for sector ETFs versus a benchmark."""
    wanted = list(dict.fromkeys([*sector_ids, benchmark_id]))
    frame = _clean_prices(prices, wanted)
    if frame.empty:
        return pd.DataFrame()
    by_id = {
        str(exposure_id): group["close"].reset_index(drop=True)
        for exposure_id, group in frame.groupby("exposure_id", sort=False)
    }
    dates = {
        str(exposure_id): group["date"].iloc[-1]
        for exposure_id, group in frame.groupby("exposure_id", sort=False)
    }
    benchmark = by_id.get(str(benchmark_id))
    if benchmark is None or benchmark.empty:
        return pd.DataFrame()
    bench_ret_20 = _window_return(benchmark, 20)
    bench_ret_60 = _window_return(benchmark, 60)
    rows: list[dict[str, Any]] = []
    for exposure_id in sector_ids:
        closes = by_id.get(str(exposure_id))
        if closes is None or closes.empty:
            continue
        ret_20 = _window_return(closes, 20)
        ret_60 = _window_return(closes, 60)
        rows.append(
            {
                "exposure_id": str(exposure_id),
                "benchmark_id": str(benchmark_id),
                "date": dates.get(str(exposure_id)),
                "return_20d_pct": None if ret_20 is None else round(ret_20, 3),
                "return_60d_pct": None if ret_60 is None else round(ret_60, 3),
                "rel_20d_pct": None if ret_20 is None or bench_ret_20 is None else round(ret_20 - bench_ret_20, 3),
                "rel_60d_pct": None if ret_60 is None or bench_ret_60 is None else round(ret_60 - bench_ret_60, 3),
                "sma200_slope_ann_pct": (
                    None if (slope := _annualized_sma_slope(closes)) is None else round(slope, 3)
                ),
            }
        )
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out = out.sort_values("rel_20d_pct", ascending=False, na_position="last").reset_index(drop=True)
    out["rank_20d"] = range(1, len(out) + 1)
    return out
