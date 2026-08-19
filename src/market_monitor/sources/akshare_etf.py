"""A-share / HK-listed ETF and index daily data via akshare (Eastmoney).

Columns are normalized to a stable contract up-front: date / open / high /
low / close / volume / amount (+ fund_id / index_id from the caller). akshare
is lazy-imported so tests that don't hit the network never import it.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


OHLCV_COLUMNS = ("date", "open", "high", "low", "close", "volume", "amount")

# Sina index symbols for the V1 universe (Eastmoney's index_zh_a_hist is
# intermittently disconnected from some networks; Sina is a reliable fallback).
SINA_INDEX_SYMBOLS = {
    "000300.SH": "sh000300",
    "000905.SH": "sh000905",
    "000852.SH": "sh000852",
    "000015.SH": "sh000015",
    "000688.SH": "sh000688",
    "932000.CSI": None,  # not available on Sina's index endpoint
    "HSTECH": None,
}


def _fmt_start(value: str | date | None, *, em: bool) -> str:
    """Normalize a start date to Eastmoney (YYYYMMDD) or ISO (YYYY-MM-DD)."""
    if value is None:
        return ""
    if isinstance(value, date):
        return value.strftime("%Y%m%d" if em else "%Y-%m-%d")
    text = str(value)
    if "-" in text:
        text = text.replace("-", "")
    return text if em else f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def _parse_date(value: str | date | None) -> pd.Timestamp | None:
    """Parse YYYYMMDD or YYYY-MM-DD into a Timestamp, or None."""
    if value is None:
        return None
    text = str(value).replace("-", "")
    if len(text) >= 8:
        return pd.Timestamp(f"{text[:4]}-{text[4:6]}-{text[6:8]}")
    return None


def _coerce_symbol(value: str) -> str:
    """Turn 510300.SH / 510300.SZ / 510300 into a bare 6-digit code."""
    return str(value).split(".")[0].zfill(6)


def fetch_etf_daily(symbol: str, start_date: str | date | None = None, end_date: str | date | None = None) -> pd.DataFrame:
    """Daily OHLCV for one A-share ETF via Eastmoney."""
    import akshare as ak
    import time

    start = _fmt_start(start_date, em=True) or "19900101"
    end = _fmt_start(end_date, em=True) or date.today().strftime("%Y%m%d")
    # Prefer Sina (stable from more networks); fall back to Eastmoney spot if
    # Sina is unavailable for a particular issue.
    code = _coerce_symbol(symbol)
    sina_symbol = ("sh" if str(symbol).upper().endswith(".SH") else "sz") + code
    try:
        df = ak.fund_etf_hist_sina(symbol=sina_symbol)
        if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
            df = df.rename(columns={"日期": "date", "开盘": "open", "最高": "high", "最低": "low", "收盘": "close", "成交量": "volume", "成交额": "amount"})
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            start_ts = _parse_date(start)
            end_ts = _parse_date(end) or pd.Timestamp(date.today())
            if start_ts:
                df = df[df["date"] >= start_ts]
            if end_ts:
                df = df[df["date"] <= end_ts]
        else:
            raise RuntimeError("empty sina frame")
    except Exception:
        time.sleep(0.5)
        df = ak.fund_etf_hist_em(symbol=code, period="daily", start_date=start, end_date=end, adjust="")
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    raw = df.rename(
        columns={
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
        }
    )
    keep = [c for c in OHLCV_COLUMNS if c in raw.columns]
    out = raw[keep].copy()
    for col in ("open", "high", "low", "close"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in ("volume", "amount"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return out[keep].dropna(subset=["date"]).reset_index(drop=True)


def fetch_index_daily(symbol: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
    """Daily OHLCV for one index (000300.SH, 000905.SH, HSTECH-ish via EM code)."""
    import akshare as ak

    start = _fmt_start(start_date, em=True) or "19900101"
    end = _fmt_start(end_date, em=True) or date.today().strftime("%Y%m%d")
    code = _coerce_symbol(symbol)
    sina_symbol = SINA_INDEX_SYMBOLS.get(symbol)
    if symbol in ("HSTECH",):
        # Hang Seng TECH via Sina's HK index endpoint.
        df = ak.stock_hk_index_daily_sina(symbol="HSTECH")
        if df is not None and isinstance(df, pd.DataFrame) and "date" in df.columns:
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            start_ts = _parse_date(start)
            end_ts = _parse_date(end) or pd.Timestamp(date.today())
            if start_ts:
                df = df[df["date"] >= start_ts]
            if end_ts:
                df = df[df["date"] <= end_ts]
    elif sina_symbol:
        # Sina history has no start/end filter; slice here.
        df = ak.stock_zh_index_daily(symbol=sina_symbol)
        slice_from = _parse_date(start)
        if df is not None and not df.empty and isinstance(df, pd.DataFrame):
            df = df.copy()
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
                if slice_from:
                    df = df[df["date"] >= slice_from]
                end_ts = _parse_date(end) or pd.Timestamp(date.today())
                if end_ts:
                    df = df[df["date"] <= end_ts]
    else:
        df = ak.index_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end)
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    raw = df.rename(
        columns={
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
        }
    )
    keep = [c for c in OHLCV_COLUMNS if c in raw.columns]
    out = raw[keep].copy()
    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return out[keep].dropna(subset=["date"]).reset_index(drop=True)


def fetch_etf_spot() -> pd.DataFrame:
    """Current ETF snapshot from Eastmoney (price, premium/discount, turnover)."""
    import akshare as ak

    df = ak.fund_etf_spot_em()
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.rename(
        columns={
            "代码": "ticker",
            "名称": "fund_name",
            "最新价": "market_price",
            "涨跌幅": "pct_chg",
            "成交额": "turnover",
            "成交量": "volume",
            "IOPV实时估值": "iopv",
            # Em's field is literally 折价率 (discount rate), so it arrives
            # discount-positive and is flipped below. Verified against a live
            # snapshot: 512100 mp=3.048 iopv=3.0431 -> +0.161%, stored as +0.16.
            "基金折价率": "premium_pct",
            "买一": "bid",
            "卖一": "ask",
            "最新份额": "units",
            "总市值": "markcap",
            "流通市值": "float_markcap",
        }
    )
    keep = [c for c in ("ticker", "fund_name", "market_price", "iopv", "pct_chg", "turnover", "volume", "premium_pct", "bid", "ask", "units", "markcap", "float_markcap") if c in out.columns]
    out = out[keep].copy()
    for col in ("market_price", "iopv", "pct_chg", "turnover", "volume", "premium_pct", "bid", "ask", "units", "markcap", "float_markcap"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "bid" in out.columns and "ask" in out.columns:
        mid = (out["ask"] + out["bid"]) / 2.0
        out["spread_bp"] = ((out["ask"] - out["bid"]) / mid * 10000.0).where(mid > 0, float("nan"))
        keep.append("spread_bp")
    # Flip away from Eastmoney's convention into this domain's: positive =
    # ETF trades at a premium to IOPV = expensive. entry_status and the whole
    # buy-side ranking read the sign this way, so it is fixed here once.
    if "premium_pct" in out.columns:
        out["premium_pct"] = -out["premium_pct"]
    if "units" in out.columns and "markcap" in out.columns:
        out["aum"] = out["markcap"]  # CNY, from EM total market cap
    out["ticker"] = out["ticker"].astype(str)
    return out.reset_index(drop=True)
