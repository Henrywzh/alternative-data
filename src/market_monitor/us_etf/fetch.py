"""Data fetching and technical feature computation for US Sector & Sub-industry ETFs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from .universe import ALL_US_ETFS, US_SECTOR_ETFS, US_SUB_INDUSTRY_ETFS, US_ETF_TICKERS

logger = logging.getLogger(__name__)


def compute_rsi(series: pd.Series, period: int = 14) -> float | None:
    """Calculate Wilder's RSI on close series."""
    if series is None or len(series) < period + 1:
        return None
    delta = series.diff().dropna()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.iloc[:period].mean()
    avg_loss = loss.iloc[:period].mean()

    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gain.iloc[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss.iloc[i]) / period

    if avg_loss == 0:
        # A window with no down move has an undefined RSI. Returning 100 would
        # claim "maximally overbought" for a series that never moved at all.
        return None if avg_gain == 0 else 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def fetch_us_etf_history(period: str = "2y", tickers: list[str] | None = None) -> pd.DataFrame:
    """Batch fetch daily OHLCV for US ETFs via yfinance."""
    target_tickers = tickers or US_ETF_TICKERS
    ticker_str = " ".join(target_tickers)
    logger.info("Fetching US ETF data for %d tickers via yfinance...", len(target_tickers))
    
    try:
        raw = yf.download(ticker_str, period=period, interval="1d", group_by="ticker", auto_adjust=True, progress=False)
    except Exception as exc:
        logger.error("yfinance batch download failed: %s", exc)
        return pd.DataFrame()

    records = []
    delivered: set[str] = set()
    for ticker in target_tickers:
        try:
            if len(target_tickers) == 1:
                df = raw.copy()
            else:
                if ticker not in raw.columns.levels[0]:
                    continue
                df = raw[ticker].dropna(subset=["Close"]).copy()
                
            if df.empty:
                continue
            df = df.reset_index()
            # Normalize date column
            date_col = "Date" if "Date" in df.columns else df.columns[0]
            df["date"] = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")
            df["ticker"] = ticker
            df["close"] = df["Close"].astype(float)
            df["open"] = df["Open"].astype(float) if "Open" in df.columns else df["close"]
            df["high"] = df["High"].astype(float) if "High" in df.columns else df["close"]
            df["low"] = df["Low"].astype(float) if "Low" in df.columns else df["close"]
            df["volume"] = df["Volume"].astype(float) if "Volume" in df.columns else 0.0
            
            clean_df = df[["date", "ticker", "open", "high", "low", "close", "volume"]].sort_values("date")
            records.append(clean_df)
            delivered.add(ticker)
        except Exception as err:
            logger.warning("Failed extracting ticker %s: %s", ticker, err)

    missing = sorted(set(target_tickers) - delivered)
    if missing:
        # A partial answer must not read as a complete one. The caller decides
        # what to do; it can only do that if it is told.
        logger.warning(
            "yfinance delivered %d of %d tickers; missing: %s",
            len(delivered), len(target_tickers), ", ".join(missing),
        )
    if not records:
        return pd.DataFrame()
    frame = pd.concat(records, ignore_index=True)
    frame.attrs["requested_tickers"] = list(target_tickers)
    frame.attrs["missing_tickers"] = missing
    return frame


def _pct_change(closes: pd.Series, lookback: int) -> float | None:
    """Return over ``lookback`` sessions, or None when the history is short.

    Never 0.0: a fund with too little history is not a flat fund, and a caller
    cannot tell the two apart once the gap has been filled with a real number.
    """

    if len(closes) < lookback + 1:
        return None
    prior = float(closes.iloc[-(lookback + 1)])
    if prior <= 0:
        return None
    return float(closes.iloc[-1] / prior - 1.0)


def _common_rebase_window(
    df_history: pd.DataFrame, tickers: list[str], days: int
) -> tuple[str | None, list[str]]:
    """Pick the base date for the shared rebased chart, and who cannot use it.

    Rebased series drawn on one axis have to share a base date. Rebasing each
    line against its own first row compares cumulative returns measured over
    different windows -- and it silently starts doing that the moment one
    ticker comes back short, which a partial provider answer does routinely.

    The window is taken from the calendar, not from the shortest series: one
    fund with five sessions of history must not collapse everyone else's
    sixty-day view down to five. Series that do not cover the window are
    reported and left out of the chart instead.
    """

    if df_history.empty or not tickers:
        return None, list(tickers)
    wide = (
        df_history[df_history["ticker"].isin(tickers)]
        .pivot_table(index="date", columns="ticker", values="close", aggfunc="last")
        .sort_index()
    )
    present = [t for t in tickers if t in wide.columns]
    if not present or len(wide) < 2:
        return None, list(tickers)

    window = wide.tail(days)
    base_date = str(window.index[0])
    covered = [t for t in present if window[t].notna().all()]
    if not covered:
        # Nothing spans the full window. Fall back to the longest history
        # available and rebase there rather than inventing a base date.
        best = max(present, key=lambda t: int(wide[t].notna().sum()))
        available = wide[best].dropna()
        if len(available) < 2:
            return None, list(tickers)
        base_date = str(available.tail(days).index[0])
        covered = [best]

    excluded = sorted(set(tickers) - set(covered))
    return base_date, excluded


def build_us_sector_artifact(df_history: pd.DataFrame, report_date: str | None = None) -> dict[str, Any]:
    """Calculate technical indicators, 60D sparklines, and build hot/warm artifacts."""
    if df_history.empty:
        return {"as_of": report_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"), "sectors": [], "sub_industries": {}}

    as_of = report_date or df_history["date"].max()

    sector_tickers = [item["ticker"] for item in US_SECTOR_ETFS]
    rebase_date, rebase_excluded = _common_rebase_window(df_history, sector_tickers, 60)

    sector_items = []
    sub_by_sector: dict[str, list[dict[str, Any]]] = {}

    for item in ALL_US_ETFS:
        ticker = item["ticker"]
        sub_df = df_history[df_history["ticker"] == ticker].sort_values("date").copy()
        if sub_df.empty or len(sub_df) < 5:
            continue
            
        closes = sub_df["close"]
        latest_close = float(closes.iloc[-1])
        
        # Returns. None, never 0.0, when the history does not reach back.
        ret_1d = _pct_change(closes, 1)
        ret_5d = _pct_change(closes, 5)
        ret_20d = _pct_change(closes, 20)
        ret_60d = _pct_change(closes, 60)

        # Moving averages. A fund without 20 sessions has no MA20; claiming it
        # sits exactly on its average is a fabricated reading.
        ma20 = float(closes.tail(20).mean()) if len(closes) >= 20 else None
        ma60 = float(closes.tail(60).mean()) if len(closes) >= 60 else None
        ma20_pct = float((latest_close / ma20 - 1) * 100) if ma20 and ma20 > 0 else None
        ma60_pct = float((latest_close / ma60 - 1) * 100) if ma60 and ma60 > 0 else None

        # 60D drawdown
        peak60 = float(closes.tail(60).max())
        drawdown_60d = float((latest_close / peak60 - 1) * 100) if peak60 > 0 else None

        # RSI 14
        rsi = compute_rsi(closes, period=14)

        # 60D sparkline. Every series is rebased against the same base date so
        # the lines can share one axis; a series that does not reach that date
        # is left without a rebased track rather than being rebased against a
        # later day and drawn as though it were comparable.
        tail_spark = sub_df[sub_df["date"] >= rebase_date] if rebase_date else sub_df.iloc[0:0]
        base_row = tail_spark["close"].iloc[0] if not tail_spark.empty else None
        covers_window = (
            base_row is not None
            and float(base_row) > 0
            and str(tail_spark["date"].iloc[0]) == rebase_date
        )
        if covers_window:
            base_val = float(base_row)
            sparkline = [
                {"d": d, "v": round(float(c), 2), "rebased": round(float(c) / base_val * 100.0, 2)}
                for d, c in zip(tail_spark["date"], tail_spark["close"])
            ]
        else:
            sparkline = []
        
        payload = {
            "ticker": ticker,
            "name_en": item["name_en"],
            "name_zh": item["name_zh"],
            # No default fee: a registry entry with no expense ratio is an
            # unknown cost, not a 0.09% one.
            "expense_ratio": item.get("expense_ratio"),
            "expense_ratio_str": (
                f"{item['expense_ratio']*100:.2f}%/yr"
                if item.get("expense_ratio") is not None
                else None
            ),
            "close": latest_close,
            "ret_1d_pct": _rounded_pct(ret_1d),
            "ret_5d_pct": _rounded_pct(ret_5d),
            "ret_20d_pct": _rounded_pct(ret_20d),
            "ret_60d_pct": _rounded_pct(ret_60d),
            "ma20_pct": round(ma20_pct, 2) if ma20_pct is not None else None,
            "ma60_pct": round(ma60_pct, 2) if ma60_pct is not None else None,
            "rsi": round(rsi, 1) if rsi is not None else None,
            "drawdown_60d": round(drawdown_60d, 2) if drawdown_60d is not None else None,
            "sparkline_60d": sparkline,
            "rebase_base_date": rebase_date if sparkline else None,
        }
        
        if "sector" in item: # Level 1 Sector ETF
            payload["sector"] = item["sector"]
            payload["sector_zh"] = item["sector_zh"]
            payload["description_zh"] = item.get("description_zh", "")
            sector_items.append(payload)
        else: # Sub-industry ETF
            parent = item["parent_sector"]
            payload["parent_sector"] = parent
            payload["sub_industry"] = item["sub_industry"]
            payload["sub_industry_zh"] = item["sub_industry_zh"]
            sub_by_sector.setdefault(parent, []).append(payload)

    # Sort sector items by 20D momentum
    # Unmeasured momentum sorts last rather than being read as zero.
    sector_items.sort(
        key=lambda x: (x["ret_20d_pct"] is not None, x["ret_20d_pct"] or 0.0),
        reverse=True,
    )

    delivered = {item["ticker"] for item in sector_items}
    missing = sorted(set(sector_tickers) - delivered)
    return {
        "as_of": as_of,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sectors": sector_items,
        "sub_industries": sub_by_sector,
        # Coverage travels with the artifact: 4 sectors out of 11 must not
        # render as though 4 were all there is.
        "coverage": {
            "sectors_expected": len(sector_tickers),
            "sectors_delivered": len(delivered),
            "sectors_missing": missing,
            "rebase_base_date": rebase_date,
            "rebase_excluded": sorted(set(rebase_excluded) | set(missing)),
        },
    }


def _rounded_pct(value: float | None) -> float | None:
    return None if value is None else round(value * 100, 2)
