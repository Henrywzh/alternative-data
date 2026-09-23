"""A-share / HK-listed ETF and index daily data via akshare (Eastmoney).

Columns are normalized to a stable contract up-front: date / open / high /
low / close / volume / amount (+ fund_id / index_id from the caller). akshare
is lazy-imported so tests that don't hit the network never import it.
"""

from __future__ import annotations

import re
import time
from datetime import date
from typing import Any

import pandas as pd
import requests

from ..config import (
    ETF_SPOT_MAX_ATTEMPTS,
    ETF_SPOT_RETRY_BASE_SECONDS,
    ETF_SPOT_RETRYABLE_STATUS_CODES,
)
from ..freshness import isoformat_utc, market_date


OHLCV_COLUMNS = ("date", "open", "high", "low", "close", "volume", "amount")

# Sina index symbols for the V1 universe (Eastmoney's index_zh_a_hist is
# intermittently disconnected from some networks; Sina is a reliable fallback).
SINA_INDEX_SYMBOLS = {
    "000300.SH": "sh000300",
    "000905.SH": "sh000905",
    "000852.SH": "sh000852",
    "000015.SH": "sh000015",
    "000688.SH": "sh000688",
    "399006.SZ": "sz399006",
    "000993.SH": "sh000993",
    "000932.SH": "sh000932",
    "932000.CSI": None,  # not available on Sina's index endpoint
}

# Hang Seng and CSI-Hong-Kong indices come from Sina's separate HK endpoint,
# which takes the index's own symbol rather than an sh/sz-prefixed code.
SINA_HK_INDEX_SYMBOLS = frozenset({"HSI", "HSTECH", "HSCEI", "CSHKDIV", "CSHKMCS"})

# AkShare's ETF spot adapter uses the `push2delay` host and downloads the
# entire ETF universe through its paginated helper. When that host returns
# persistent 502s, retrying the same full-universe request cannot recover.
# Keep a small, field-minimal direct fallback on Eastmoney's public
# `clist/get` endpoint, rotating hosts page-by-page only when needed.
ETF_SPOT_PAGE_SIZE = 100  # Eastmoney caps this endpoint at 100 rows per page.
ETF_SPOT_BASE_URLS = (
    "https://88.push2.eastmoney.com",
    "https://82.push2.eastmoney.com",
    "https://push2.eastmoney.com",
    "https://push2delay.eastmoney.com",
)
ETF_SPOT_FIELDS = (
    "f2,f3,f5,f6,f12,f13,f14,f20,f21,f31,f32,f38,f402,f441"
)
ETF_SPOT_FIELD_RENAMES = {
    "f12": "代码",
    "f14": "名称",
    "f2": "最新价",
    "f441": "IOPV实时估值",
    "f402": "基金折价率",
    "f3": "涨跌幅",
    "f5": "成交量",
    "f6": "成交额",
    "f31": "买一",
    "f32": "卖一",
    "f38": "最新份额",
    "f20": "总市值",
    "f21": "流通市值",
}


def _spot_error_label(exc: Exception) -> str:
    """Include an HTTP status in source logs instead of hiding it as HTTPError."""
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    suffix = f" HTTP {status_code}" if status_code is not None else ""
    return f"{type(exc).__name__}{suffix}"


def _fetch_etf_spot_page(
    session: requests.Session,
    page: int,
) -> tuple[list[dict[str, Any]], int]:
    """Fetch one ETF-list page with bounded Eastmoney host failover."""
    params = {
        "pn": str(page),
        "pz": str(ETF_SPOT_PAGE_SIZE),
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "wbp2u": "|0|0|0|web",
        "fid": "f12",
        "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024,b:MK0827",
        "fields": ETF_SPOT_FIELDS,
    }
    headers = {
        "Referer": "https://quote.eastmoney.com/",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    }
    last_error: Exception | None = None
    attempts = min(ETF_SPOT_MAX_ATTEMPTS, len(ETF_SPOT_BASE_URLS))
    for attempt in range(attempts):
        base_url = ETF_SPOT_BASE_URLS[attempt]
        try:
            response = session.get(
                f"{base_url}/api/qt/clist/get",
                params=params,
                headers=headers,
                timeout=(5, 15),
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("rc") not in (0, "0"):
                raise RuntimeError(
                    f"Eastmoney ETF list returned invalid response from {base_url}"
                )
            data = payload.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("diff"), list):
                raise RuntimeError(
                    f"Eastmoney ETF list omitted page data from {base_url}"
                )
            total = int(data.get("total") or 0)
            rows = data["diff"]
            if total <= 0 or not rows:
                raise RuntimeError(
                    f"Eastmoney ETF list returned no rows from {base_url}"
                )
            return rows, total
        except Exception as exc:  # noqa: BLE001 - try only bounded alternate hosts
            last_error = exc
            retryable = _is_retryable_spot_error(exc) or isinstance(exc, RuntimeError)
            if attempt + 1 >= attempts or not retryable:
                raise
            print(
                f"  [market_monitor] ETF spot page {page} failed at "
                f"{base_url} ({_spot_error_label(exc)}: {exc}); trying alternate host"
            )
            time.sleep(ETF_SPOT_RETRY_BASE_SECONDS * (attempt + 1))

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Eastmoney ETF spot page {page} could not be fetched")


def _fetch_etf_spot_from_hosts() -> pd.DataFrame:
    """Fetch a complete Eastmoney ETF snapshot via paginated host failover.

    Pagination is kept here rather than retried as one giant AkShare call, so
    a single gateway failure only retries its page. A short page, duplicate
    code, or changing row count is treated as incomplete; callers must not
    mistake a partial universe for a valid current snapshot.
    """
    rows: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    expected_total: int | None = None
    total_pages: int | None = None
    with requests.Session() as session:
        page = 1
        while total_pages is None or page <= total_pages:
            page_rows, page_total = _fetch_etf_spot_page(session, page)
            if expected_total is None:
                expected_total = page_total
                total_pages = (expected_total + ETF_SPOT_PAGE_SIZE - 1) // ETF_SPOT_PAGE_SIZE
            elif page_total != expected_total:
                raise RuntimeError(
                    "Eastmoney ETF universe changed during pagination "
                    f"({expected_total} to {page_total} rows)"
                )

            expected_page_rows = min(
                ETF_SPOT_PAGE_SIZE,
                max(expected_total - (page - 1) * ETF_SPOT_PAGE_SIZE, 0),
            )
            if len(page_rows) != expected_page_rows:
                raise RuntimeError(
                    f"Eastmoney ETF page {page} incomplete: "
                    f"{len(page_rows)}/{expected_page_rows} rows"
                )
            page_codes = [str(row.get("f12") or "") for row in page_rows]
            if any(not code for code in page_codes):
                raise RuntimeError(f"Eastmoney ETF page {page} contains a missing code")
            duplicates = seen_codes.intersection(page_codes)
            if duplicates or len(set(page_codes)) != len(page_codes):
                raise RuntimeError(
                    f"Eastmoney ETF page {page} contains duplicate codes: "
                    f"{sorted(duplicates)[:5]}"
                )
            seen_codes.update(page_codes)
            rows.extend(page_rows)
            print(
                f"  [market_monitor] ETF spot fallback page {page}/"
                f"{total_pages}: {len(rows)}/{expected_total} rows"
            )
            page += 1
            if page <= total_pages:
                # Avoid hammering the provider while walking a live list.
                time.sleep(min(0.25, ETF_SPOT_RETRY_BASE_SECONDS))

    if expected_total is None or len(rows) != expected_total:
        raise RuntimeError(
            f"Eastmoney ETF snapshot incomplete: {len(rows)}/{expected_total or 0} rows"
        )
    return pd.DataFrame(rows).rename(columns=ETF_SPOT_FIELD_RENAMES)


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
    end = _fmt_start(end_date, em=True) or market_date().replace("-", "")
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
            end_ts = _parse_date(end) or pd.Timestamp(market_date())
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
    if "close" not in keep:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    out = raw[keep].copy()
    for col in ("open", "high", "low", "close"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in ("volume", "amount"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out = out[keep].dropna(subset=["date", "close"]).reset_index(drop=True)
    out["retrieved_at_utc"] = isoformat_utc()
    out["observation_type"] = "daily_close"
    return out


def fetch_index_daily(symbol: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
    """Daily OHLCV for one index (000300.SH, 000905.SH, HSTECH-ish via EM code)."""
    sina_symbol = SINA_INDEX_SYMBOLS.get(symbol)
    if symbol not in SINA_INDEX_SYMBOLS and symbol not in SINA_HK_INDEX_SYMBOLS and not symbol[:1].isdigit():
        # _coerce_symbol zero-pads, so a non-numeric ticker that reaches the
        # Eastmoney branch is silently turned into nonsense ("SPX" -> "000SPX")
        # and the request fails with a confusing provider error. The pipeline
        # routes SPX to yfinance so this is unreachable today; fail loudly
        # rather than leave the trap armed for the next index that is added.
        raise ValueError(
            f"{symbol!r} has no Sina mapping and is not an Eastmoney numeric code; "
            "add it to SINA_INDEX_SYMBOLS or route it to another source"
        )

    import akshare as ak

    start = _fmt_start(start_date, em=True) or "19900101"
    end = _fmt_start(end_date, em=True) or market_date().replace("-", "")
    code = _coerce_symbol(symbol)
    if symbol in SINA_HK_INDEX_SYMBOLS:
        # Hong Kong indexes via Sina's HK index endpoint.
        df = ak.stock_hk_index_daily_sina(symbol=symbol)
        if df is not None and isinstance(df, pd.DataFrame) and "date" in df.columns:
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            start_ts = _parse_date(start)
            end_ts = _parse_date(end) or pd.Timestamp(market_date())
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
                end_ts = _parse_date(end) or pd.Timestamp(market_date())
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
    if "close" not in keep:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    out = raw[keep].copy()
    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out = out[keep].dropna(subset=["date", "close"]).reset_index(drop=True)
    out["retrieved_at_utc"] = isoformat_utc()
    out["observation_type"] = "daily_close"
    return out


def _is_retryable_spot_error(exc: Exception) -> bool:
    """Return whether an Eastmoney spot failure is likely transient."""
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    try:
        if int(status_code) in ETF_SPOT_RETRYABLE_STATUS_CODES:
            return True
    except (TypeError, ValueError):
        pass

    message = str(exc)
    if any(re.search(rf"\b{code}\b", message) for code in ETF_SPOT_RETRYABLE_STATUS_CODES):
        return True
    return type(exc).__name__ in {
        "ConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
        "Timeout",
        "JSONDecodeError",
        "ChunkedEncodingError",
    }


def _fetch_etf_spot_with_retry(ak: Any) -> pd.DataFrame:
    """Fetch the raw spot frame with bounded retry/backoff semantics."""
    for attempt in range(ETF_SPOT_MAX_ATTEMPTS):
        try:
            df = ak.fund_etf_spot_em()
        except Exception as exc:  # noqa: BLE001 - classify only transient failures
            if attempt == ETF_SPOT_MAX_ATTEMPTS - 1 or not _is_retryable_spot_error(exc):
                raise
            print(
                f"  [market_monitor] transient ETF spot failure ({_spot_error_label(exc)}); "
                f"retry {attempt + 1}/{ETF_SPOT_MAX_ATTEMPTS - 1}"
            )
        else:
            if isinstance(df, pd.DataFrame) and not df.empty:
                return df
            if attempt == ETF_SPOT_MAX_ATTEMPTS - 1:
                return pd.DataFrame()
            print(
                "  [market_monitor] empty ETF spot response; "
                f"retry {attempt + 1}/{ETF_SPOT_MAX_ATTEMPTS - 1}"
            )

        time.sleep(ETF_SPOT_RETRY_BASE_SECONDS * (2**attempt))

    return pd.DataFrame()


def fetch_etf_spot() -> pd.DataFrame:
    """Current ETF snapshot from Eastmoney (price, premium/discount, turnover)."""
    primary_error: Exception | None = None
    try:
        import akshare as ak

        df = _fetch_etf_spot_with_retry(ak)
        if df is None or df.empty:
            raise RuntimeError("AkShare ETF spot returned an empty frame")
    except Exception as exc:  # noqa: BLE001 - retain direct source fallback
        primary_error = exc
        print(
            "  [market_monitor] AkShare ETF spot unavailable "
            f"({_spot_error_label(exc)}: {exc}); using bounded Eastmoney host fallback"
        )
        try:
            df = _fetch_etf_spot_from_hosts()
        except Exception as fallback_error:  # noqa: BLE001 - fail closed if both paths fail
            message = (
                "ETF spot fetch failed on both paths: "
                f"AkShare {_spot_error_label(primary_error)} ({primary_error}); "
                f"Eastmoney host fallback {_spot_error_label(fallback_error)} "
                f"({fallback_error})"
            )
            raise RuntimeError(message) from fallback_error
    if df is None or df.empty:
        return pd.DataFrame()
    retrieved_at_utc = isoformat_utc()
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
    # Guarded on markcap alone: the previous condition also required `units`,
    # which is not involved in the assignment, so a snapshot carrying market
    # cap but no share count silently produced no size column at all.
    if "markcap" in out.columns:
        out["aum"] = out["markcap"]  # CNY, from EM total market cap
    out["ticker"] = out["ticker"].astype(str)
    # Eastmoney's public spot frame does not expose a stable per-row UTC quote
    # timestamp. Keep retrieval time explicit, but do not pretend it is the
    # exchange's observation time. Downstream freshness logic can therefore
    # reject an old snapshot instead of calling it live.
    out["retrieved_at_utc"] = retrieved_at_utc
    out["source_observed_at_utc"] = pd.NaT
    out["timestamp_basis"] = "retrieved_at"
    out["observation_type"] = "intraday_quote"
    return out.reset_index(drop=True)
