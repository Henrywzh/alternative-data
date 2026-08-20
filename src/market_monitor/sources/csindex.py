"""Daily index history from China Securities Index Co.

The CSI Hong Kong Connect series lives here and nowhere else we use: Sina's
HK index endpoint carries the Hang Seng family and a few CSI Hong Kong
indices, but not the Connect thematics. Sina also answers 200 for several CSI
style indices with data that stopped years ago (中证800成长 in 2016,
中证800价值 in 2019), so a CSI index is taken from CSI itself.
"""

from __future__ import annotations

from datetime import date

import pandas as pd


_COLUMNS = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交金额": "amount",
}


def fetch_index_daily(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Daily OHLCV for one CSI index code, e.g. ``931637``."""
    import akshare as ak

    start = (start_date or "19900101").replace("-", "")
    end = (end_date or date.today().strftime("%Y%m%d")).replace("-", "")
    frame = ak.stock_zh_index_hist_csindex(symbol=str(symbol), start_date=start, end_date=end)
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.rename(columns=_COLUMNS)
    keep = [c for c in ("date", "open", "high", "low", "close", "volume", "amount") if c in out.columns]
    out = out[keep].copy()
    # ISO strings, matching the other index sources. Returning datetimes here
    # made the concatenated frame an object column of mixed str and Timestamp,
    # and parquet refused to write it: "Expected bytes, got a 'Timestamp'".
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for column in keep:
        if column != "date":
            out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date")
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out.reset_index(drop=True)
