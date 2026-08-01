"""HK Stablecoin & Crypto watchlist live price/volume data via akshare.

Mirrors `src/hk_reit/sources/reit_price.py`'s structure exactly:
`ak.stock_hk_spot_em()` for a bulk latest-quote snapshot of ALL HK-listed
stocks (filtered down to just the WATCHLIST tickers), and
`ak.stock_hk_hist()` per-ticker for daily OHLCV history. Both are wrapped
in per-call try/except so one bad ticker never fails the whole batch.

Ticker normalization: WATCHLIST tickers (config.WATCHLIST) are already
zero-padded 5-digit codes with a ".HK" suffix, e.g. "00863.HK" -- stripping
the ".HK" suffix yields the bare akshare `代码` code directly. Confirmed
live 2026-08-01: akshare's `stock_hk_spot_em()` `代码` column uses the same
plain 5-digit zero-padded string format (e.g. "00863"), so no re-padding
is required, just the suffix strip.

`hkexnews_announcements.py` already has an `all_watchlist_tickers()`
helper that flattens config.WATCHLIST into a plain `list[str]` of dotted
tickers (e.g. "00863.HK"), used there to resolve HKEXnews' internal
stockId. This module needs the bare akshare code *plus* tier and
company_name attached to each entry for downstream grouping/joins, which
that helper's shape doesn't carry -- so this module defines its own
`all_watchlist_tickers()` with the richer per-entry shape rather than
repurposing the plain-ticker list for a job it wasn't built for. Both
walk the same config.WATCHLIST source of truth, so they cannot drift on
*which* tickers are covered, only on what shape they hand back.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from ..config import WATCHLIST
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SOURCE_NAME = "watchlist_price_akshare"
SOURCE_URL = "akshare.stock_hk_spot_em / akshare.stock_hk_hist"


def all_watchlist_tickers() -> list[dict]:
    """Flatten config.WATCHLIST (TIER_1..TIER_4) into one list of
    {code, ticker, company_name, tier} dicts.

    `code` is the bare akshare-format code (".HK" suffix stripped, e.g.
    "00863"); `ticker` is the original dotted WATCHLIST form (e.g.
    "00863.HK"); `company_name` is the entry's `name_en`; `tier` is the
    int tier number.
    """
    entries: list[dict] = []
    for tier_entries in WATCHLIST.values():
        for entry in tier_entries:
            ticker = entry.get("ticker")
            if not ticker:
                continue
            code = str(ticker).replace(".HK", "").strip().zfill(5)
            entries.append(
                {
                    "code": code,
                    "ticker": ticker,
                    "company_name": entry.get("name_en", ""),
                    "tier": entry.get("tier"),
                }
            )
    return entries


def fetch_watchlist_spot_quotes(*, run_id: Optional[str] = None) -> pd.DataFrame:
    """Latest spot quote (price, day change, volume) for every WATCHLIST ticker.

    `run_id` is accepted for interface parity with the reit_price.py
    template; this package's `save_raw_snapshot()` (unlike hk_reit's) does
    not thread a run_id through, so it is not forwarded further.
    """
    try:
        import akshare as ak
    except ImportError:
        logger.error("akshare is not installed; cannot fetch watchlist spot quotes.")
        return pd.DataFrame()

    try:
        spot = ak.stock_hk_spot_em()
    except Exception as exc:
        logger.warning("stock_hk_spot_em() fetch failed: %s.", exc)
        return pd.DataFrame()

    if spot.empty or "代码" not in spot.columns:
        logger.warning("stock_hk_spot_em() returned no usable data.")
        return pd.DataFrame()

    entries = all_watchlist_tickers()
    code_map = {entry["code"]: entry for entry in entries}

    subset = spot[spot["代码"].isin(code_map.keys())].copy()
    if subset.empty:
        logger.warning("None of the configured watchlist tickers were found in stock_hk_spot_em().")
        return pd.DataFrame()

    raw_path = save_raw_snapshot(
        SOURCE_NAME + "_spot",
        subset.to_json(orient="records", force_ascii=False),
        file_ext="json",
        source_url=SOURCE_URL,
    )

    codes_col = subset["代码"].astype(str)
    now = datetime.now(timezone.utc)

    out = pd.DataFrame(
        {
            "date": pd.Timestamp(now.date()),
            "ticker": codes_col,
            "company_name": codes_col.map(lambda c: code_map.get(c, {}).get("company_name", "")),
            "tier": codes_col.map(lambda c: code_map.get(c, {}).get("tier")),
            "latest_price_hkd": pd.to_numeric(subset.get("最新价"), errors="coerce"),
            "change_pct": pd.to_numeric(subset.get("涨跌幅"), errors="coerce"),
            "volume": pd.to_numeric(subset.get("成交量"), errors="coerce"),
            "turnover_hkd": pd.to_numeric(subset.get("成交额"), errors="coerce"),
            "fetched_at": now.isoformat(),
        }
    )
    out["tier"] = out["tier"].astype("Int64")
    out.attrs.update(raw_snapshot=str(raw_path), source_url=SOURCE_URL)
    return out.reset_index(drop=True)


def fetch_watchlist_price_history(
    *, lookback_days: int = 120, run_id: Optional[str] = None
) -> pd.DataFrame:
    """Daily OHLCV history for every WATCHLIST ticker, `lookback_days` back from today."""
    try:
        import akshare as ak
    except ImportError:
        logger.error("akshare is not installed; cannot fetch watchlist price history.")
        return pd.DataFrame()

    end = date.today()
    start = end - timedelta(days=lookback_days)
    frames: list[pd.DataFrame] = []
    for entry in all_watchlist_tickers():
        code = entry["code"]
        name = entry["company_name"]
        try:
            hist = ak.stock_hk_hist(
                symbol=code,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="",
            )
            if hist is not None and not hist.empty:
                frame = pd.DataFrame(
                    {
                        "date": pd.to_datetime(hist.get("日期"), errors="coerce"),
                        "ticker": code,
                        "company_name": name,
                        "open_hkd": pd.to_numeric(hist.get("开盘"), errors="coerce"),
                        "high_hkd": pd.to_numeric(hist.get("最高"), errors="coerce"),
                        "low_hkd": pd.to_numeric(hist.get("最低"), errors="coerce"),
                        "close_hkd": pd.to_numeric(hist.get("收盘"), errors="coerce"),
                        "volume": pd.to_numeric(hist.get("成交量"), errors="coerce"),
                    }
                )
                frames.append(frame.dropna(subset=["date"]))
        except Exception:
            logger.exception("stock_hk_hist(%s) failed for %s.", code, name)
            continue

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    raw_path = save_raw_snapshot(
        SOURCE_NAME + "_history",
        combined.to_json(orient="records", force_ascii=False, date_format="iso"),
        file_ext="json",
        source_url=SOURCE_URL,
    )
    combined.attrs.update(raw_snapshot=str(raw_path), source_url=SOURCE_URL)
    return combined
