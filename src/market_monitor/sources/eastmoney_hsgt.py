"""Eastmoney Stock Connect (沪深港通) history via akshare."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd


INDIVIDUAL_COLUMNS = {
    "持股日期": "hold_date",
    "当日收盘价": "close",
    "当日涨跌幅": "day_change_pct",
    "持股数量": "holding_shares",
    "持股市值": "holding_market_value",
    "持股数量占A股百分比": "holding_share_pct",
    "持股市值变化-1日": "holding_mv_change_1d",
    "持股市值变化-5日": "holding_mv_change_5d",
    "持股市值变化-10日": "holding_mv_change_10d",
}

MARKET_COLUMNS = {
    "日期": "trade_date",
    "当日成交净买额": "net_buy_yi",
    "买入成交额": "buy_turnover_yi",
    "卖出成交额": "sell_turnover_yi",
    "历史累计净买额": "cumulative_net_buy_trillion",
    "当日资金流入": "inflow_yi",
    "当日余额": "balance_yi",
    "持股市值": "holding_market_value",
    "领涨股": "leader_name",
    "领涨股-涨跌幅": "leader_change_pct",
    "沪深300": "csi300",
    "沪深300-涨跌幅": "csi300_change_pct",
    "领涨股-代码": "leader_code",
}


_MARKET_NUMERIC_COLUMNS = (
    "net_buy_yi",
    "buy_turnover_yi",
    "sell_turnover_yi",
    "cumulative_net_buy_trillion",
    "inflow_yi",
    "balance_yi",
    "holding_market_value",
    "leader_change_pct",
    "csi300",
    "csi300_change_pct",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_southbound_individual(symbol: str = "00700") -> pd.DataFrame:
    import akshare as ak

    raw = ak.stock_hsgt_individual_em(symbol=symbol)
    if raw is None or raw.empty:
        return pd.DataFrame()
    frame = raw.rename(columns=INDIVIDUAL_COLUMNS).copy()
    frame["hold_date"] = pd.to_datetime(frame["hold_date"], errors="coerce")
    for column in (
        "close",
        "day_change_pct",
        "holding_shares",
        "holding_market_value",
        "holding_share_pct",
        "holding_mv_change_1d",
        "holding_mv_change_5d",
        "holding_mv_change_10d",
    ):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["hold_date"]).sort_values("hold_date").reset_index(drop=True)
    frame["security_code"] = str(symbol).zfill(5)
    frame["source_id"] = "eastmoney:hsgt_individual"
    frame["source_url"] = "https://data.eastmoney.com/hsgt/hsgtV2.html"
    frame["retrieved_at_utc"] = _now()
    return frame


def fetch_southbound_market_flow() -> pd.DataFrame:
    import akshare as ak

    raw = ak.stock_hsgt_hist_em(symbol="南向资金")
    if raw is None or raw.empty:
        return pd.DataFrame()

    frame = normalize_southbound_market_flow(raw)
    if frame.empty:
        return frame
    frame["flow"] = "southbound"
    frame["source_id"] = "eastmoney:hsgt_hist"
    frame["source_url"] = "https://data.eastmoney.com/hsgt/hsgtV2.html"
    frame["retrieved_at_utc"] = _now()
    return frame


def normalize_southbound_market_flow(raw: pd.DataFrame | None) -> pd.DataFrame:
    """Normalize the aggregate Stock Connect feed at every read boundary.

    Eastmoney has historically used ``0`` as a placeholder for market-wide
    holding value before that field was populated, and it can repeat the
    placeholder in a current response.  A zero holding value is not a valid
    market-wide observation, so preserve it as missing rather than drawing a
    fake collapse to HK$0 or treating it as a fresh value.  The function also
    accepts an already-normalized frame so artifact rebuilds repair older local
    snapshots without needing a new network call.
    """
    if raw is None or raw.empty:
        return pd.DataFrame()

    frame = raw.rename(columns=MARKET_COLUMNS).copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    for column in _MARKET_NUMERIC_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "holding_market_value" in frame.columns:
        holding_value = frame["holding_market_value"]
        frame["holding_market_value"] = holding_value.where(holding_value.gt(0))
    frame = frame.dropna(subset=["trade_date"]).sort_values("trade_date").reset_index(drop=True)
    return frame
