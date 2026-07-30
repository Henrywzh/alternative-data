import logging
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..config import HK_CONSUMER_TICKERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = ["date", "ticker", "company_name", "pe_ttm", "pb_ratio", "market_cap_hkd_b"]

# stock_hk_valuation_baidu requires an explicit `indicator` argument -- the
# default ("总市值") is market cap only, and calling it with no indicator at
# all (the prior bug) silently returns market-cap-only rows mislabeled as
# every field, i.e. every non-market-cap column comes back null. There is no
# dividend-yield indicator on this endpoint (verified against its live
# choice list: 总市值 / 市盈率(TTM) / 市盈率(静) / 市净率 / 市现率), so yield is not
# fetched here -- it is a documented gap, not a null placeholder.
_INDICATORS = {"market_cap_hkd_b": "总市值", "pe_ttm": "市盈率(TTM)", "pb_ratio": "市净率"}
# 总市值 is returned in 亿 HKD (100-million units); convert to HKD billions.
_YI_TO_BILLIONS = 0.1


def fetch_hk_consumer_valuations(tickers: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """Fetch the latest ten years of daily HK stock valuation history.

    The Baidu valuation endpoint returns a longer history than the dashboard
    needs. Keep a date-based ten-year window here rather than a fixed 30-row
    tail so the source contract remains historical for a daily series.
    """
    target_tickers = tickers or HK_CONSUMER_TICKERS
    source_url = "akshare.stock_hk_valuation_baidu"

    try:
        import akshare as ak
    except ImportError:
        logger.error("akshare is not installed; cannot fetch HK consumer valuations.")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    per_ticker_frames = []
    for ticker_code, name in target_tickers.items():
        padded_symbol = ticker_code.zfill(5)
        field_frames = {}
        for field, indicator in _INDICATORS.items():
            try:
                df_ind = ak.stock_hk_valuation_baidu(symbol=padded_symbol, indicator=indicator)
                if df_ind is None or df_ind.empty:
                    continue
                df_ind["date"] = pd.to_datetime(df_ind["date"], errors="coerce")
                df_ind = df_ind.dropna(subset=["date"])
                if not df_ind.empty:
                    cutoff = df_ind["date"].max() - pd.DateOffset(years=10)
                    df_ind = df_ind[df_ind["date"] >= cutoff]
                df_ind = df_ind.rename(columns={"value": field})
                df_ind["date"] = df_ind["date"].dt.strftime("%Y-%m-%d")
                field_frames[field] = df_ind.set_index("date")[field]
            except Exception as e:
                logger.debug(f"Could not fetch {indicator} for ticker {padded_symbol}: {e}")

        if not field_frames:
            continue
        merged = pd.concat(field_frames.values(), axis=1).reset_index()
        merged["ticker"] = f"{padded_symbol}.HK"
        merged["company_name"] = name
        if "market_cap_hkd_b" in merged.columns:
            merged["market_cap_hkd_b"] = merged["market_cap_hkd_b"] * _YI_TO_BILLIONS
        per_ticker_frames.append(merged)

    if not per_ticker_frames:
        logger.error("HK consumer ticker valuations unavailable; returning empty dataset (no fabricated data).")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    df_norm = pd.concat(per_ticker_frames, ignore_index=True)
    for col in SCHEMA_COLUMNS:
        if col not in df_norm.columns:
            df_norm[col] = None
    df_norm = df_norm[SCHEMA_COLUMNS]
    raw_path = save_raw_snapshot(
        "hk_consumer_valuations", df_norm.to_dict(orient="records"), file_ext="json", source_url=source_url
    )
    df_norm.attrs["raw_snapshot"] = str(raw_path)
    df_norm.attrs["source_url"] = source_url
    return df_norm
