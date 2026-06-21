"""
Combines Google Trends weekly data with stock price data into a single aligned DataFrame.
"""
import logging
from dataclasses import asdict
from typing import List, Optional

import pandas as pd

from .models import TrendsDataPoint, StockDataPoint, CombinedSignal

logger = logging.getLogger(__name__)


def combine(
    trends: List[TrendsDataPoint],
    stocks: List[StockDataPoint],
) -> pd.DataFrame:
    """
    Align weekly Google Trends values with weekly stock closing prices.

    Strategy:
    - Google Trends gives weekly data points anchored to Sundays.
    - Stock data is daily; we resample to weekly (last close of each Mon-Sun week).
    - We use pd.merge_asof (nearest) to match each Trends Sunday to the nearest
      Sunday stock week-end within a 7-day tolerance. This is robust to 1-2 day
      misalignments from holidays or HK market closures.
    - Compute weekly return on adj_close.

    Returns:
        DataFrame with columns:
          week_start, keyword, geo, trend_value, is_partial,
          ticker, stock_close, stock_adj_close, stock_weekly_return
    """
    if not trends:
        raise ValueError("trends list is empty — nothing to combine")

    # ── Trends DF ────────────────────────────────────────────────────────────
    trend_df = pd.DataFrame([asdict(t) for t in trends])
    # trendspyg returns tz-aware ISO8601; strip to tz-naive for merge
    trend_df["week_start"] = (
        pd.to_datetime(trend_df["date"], utc=True)
        .dt.tz_convert(None)
        .dt.normalize()
    )
    trend_df = trend_df.sort_values("week_start").reset_index(drop=True)

    # ── Stock DF ─────────────────────────────────────────────────────────────
    if stocks:
        stock_df = pd.DataFrame([asdict(s) for s in stocks])
        # Stock dates are plain "YYYY-MM-DD" strings → parse as tz-naive
        stock_df["date"] = pd.to_datetime(stock_df["date"])
        stock_df = stock_df.sort_values("date").reset_index(drop=True)

        # Resample to weekly: take LAST close of each Mon-Sun week (anchored Sunday)
        stock_weekly = (
            stock_df
            .set_index("date")[["ticker", "close", "adj_close"]]
            .resample("W")      # pandas "W" anchors on Sunday by default
            .agg({"ticker": "last", "close": "last", "adj_close": "last"})
            .reset_index()
            .rename(columns={"date": "week_end"})
        )
        # Drop empty weeks (e.g. holidays with no trading)
        stock_weekly = stock_weekly.dropna(subset=["close"]).reset_index(drop=True)

        # Weekly return on adj_close
        stock_weekly["stock_weekly_return"] = stock_weekly["adj_close"].pct_change()

        # ── merge_asof: match each Trends Sunday → nearest stock week-end ────
        # Both series are already sorted. tolerance=7d ensures we only match
        # within the same calendar week even if exact day differs.
        merged = pd.merge_asof(
            trend_df,
            stock_weekly,
            left_on="week_start",
            right_on="week_end",
            direction="nearest",
            tolerance=pd.Timedelta("7d"),
        )
    else:
        logger.warning("No stock data provided; stock columns will be NaN")
        merged = trend_df.copy()
        merged["ticker"] = None
        merged["close"] = None
        merged["adj_close"] = None
        merged["stock_weekly_return"] = None

    # ── Clean up ─────────────────────────────────────────────────────────────
    merged = merged.rename(columns={
        "close": "stock_close",
        "adj_close": "stock_adj_close",
    })

    keep = [
        "week_start", "keyword", "geo", "trend_value", "is_partial",
        "ticker", "stock_close", "stock_adj_close", "stock_weekly_return",
    ]
    available = [c for c in keep if c in merged.columns]
    merged = merged[available]

    n_matched = merged["stock_close"].notna().sum()
    logger.info(
        f"Combined DataFrame: {len(merged)} rows ({n_matched} with stock data), "
        f"date range {merged['week_start'].min()} → {merged['week_start'].max()}"
    )
    return merged


def correlation_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute a quick correlation table between trend_value and
    current/lead/lag stock returns for signal analysis.
    """
    df = df.dropna(subset=["trend_value", "stock_adj_close"]).copy()

    df["ret_0w"] = df["stock_weekly_return"]           # same-week return
    df["ret_+1w"] = df["ret_0w"].shift(-1)             # next-week return
    df["ret_+2w"] = df["ret_0w"].shift(-2)             # 2-week forward return
    df["ret_-1w"] = df["ret_0w"].shift(1)              # prior-week return

    corr_cols = ["ret_-1w", "ret_0w", "ret_+1w", "ret_+2w"]
    corr_data = []
    for col in corr_cols:
        sub = df[["trend_value", col]].dropna()
        if len(sub) > 5:
            corr = sub["trend_value"].corr(sub[col])
            corr_data.append({"lag_label": col, "pearson_r": round(corr, 4), "n_obs": len(sub)})

    return pd.DataFrame(corr_data)
