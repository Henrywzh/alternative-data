from __future__ import annotations

from pathlib import Path
import os
from io import StringIO

import pandas as pd
import requests
import yfinance as yf


def fetch_yfinance_history(symbol: str, *, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
    history = yf.download(symbol, start=start_date, end=end_date, auto_adjust=False, progress=False)
    if history.empty:
        return pd.DataFrame(columns=["date", "price"])
    if isinstance(history.columns, pd.MultiIndex):
        if ("Adj Close", symbol) in history.columns:
            price_series = history[("Adj Close", symbol)]
        elif ("Close", symbol) in history.columns:
            price_series = history[("Close", symbol)]
        else:
            first_price_col = next((column for column in history.columns if column[0] in {"Adj Close", "Close"}), None)
            if first_price_col is None:
                return pd.DataFrame(columns=["date", "price"])
            price_series = history[first_price_col]
    else:
        price_column = "Adj Close" if "Adj Close" in history.columns else "Close"
        price_series = history[price_column]
    frame = price_series.rename("price").to_frame().reset_index()
    date_column = "Date" if "Date" in frame.columns else frame.columns[0]
    return frame.rename(columns={date_column: "date"})[["date", "price"]]


def fetch_tradingeconomics_history(
    symbol: str,
    *,
    start_date: str,
    end_date: str | None = None,
    api_key: str | None = None,
) -> pd.DataFrame:
    tradingeconomics_key = api_key or _resolve_tradingeconomics_api_key()
    if not tradingeconomics_key:
        return pd.DataFrame(columns=["date", "price"])

    params = {
        "c": tradingeconomics_key,
        "d1": start_date,
        "f": "json",
    }
    if end_date:
        params["d2"] = end_date
    response = requests.get(
        f"https://api.tradingeconomics.com/markets/historical/{symbol}",
        params=params,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    payload = response.json()
    if not payload:
        return pd.DataFrame(columns=["date", "price"])
    frame = pd.DataFrame(payload)
    price_column = "Close" if "Close" in frame.columns else "close"
    date_column = "Date" if "Date" in frame.columns else "date"
    frame = frame.rename(columns={date_column: "date", price_column: "price"})[["date", "price"]]
    frame["date"] = pd.to_datetime(frame["date"], dayfirst=True, errors="coerce")
    frame = frame.dropna(subset=["date", "price"]).sort_values("date").reset_index(drop=True)
    return frame


def fetch_investing_history(url: str) -> pd.DataFrame:
    response = requests.get(
        url,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text))
    history_table = next(
        (
            table for table in tables
            if {"Date", "Price"}.issubset(set(table.columns))
        ),
        None,
    )
    if history_table is None:
        return pd.DataFrame(columns=["date", "price"])
    frame = history_table[["Date", "Price"]].copy()
    sample_date = str(frame["Date"].iloc[0]) if not frame.empty else ""
    dayfirst = "/" in sample_date
    frame["date"] = pd.to_datetime(frame["Date"], dayfirst=dayfirst, errors="coerce")
    frame["price"] = (
        frame["Price"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace(r"[^0-9.\-]", "", regex=True)
        .replace("", pd.NA)
        .astype(float)
    )
    frame = frame.dropna(subset=["date", "price"]).sort_values("date").reset_index(drop=True)
    return frame[["date", "price"]]


def fetch_public_mineral_prices(
    price_universe: pd.DataFrame,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    manual_prices_path: str | Path | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    manual_prices = pd.read_csv(manual_prices_path) if manual_prices_path else pd.DataFrame()
    if not manual_prices.empty:
        manual_prices["date"] = pd.to_datetime(manual_prices["date"])

    for row in price_universe.itertuples(index=False):
        frame = pd.DataFrame(columns=["date", "price"])
        if row.price_source_type == "yfinance_futures" and row.price_symbol_or_series_id:
            frame = fetch_yfinance_history(
                row.price_symbol_or_series_id,
                start_date=start_date,
                end_date=end_date,
            )
        elif row.price_source_type == "tradingeconomics_api" and row.price_symbol_or_series_id and start_date:
            frame = fetch_tradingeconomics_history(
                row.price_symbol_or_series_id,
                start_date=start_date,
                end_date=end_date,
            )
        elif row.price_source_type == "investing_html" and row.price_symbol_or_series_id:
            frame = fetch_investing_history(row.price_symbol_or_series_id)
            if start_date:
                frame = frame.loc[frame["date"] >= pd.Timestamp(start_date)].copy()
            if end_date:
                frame = frame.loc[frame["date"] <= pd.Timestamp(end_date)].copy()
        elif not manual_prices.empty:
            frame = manual_prices.loc[
                manual_prices["normalized_mineral_id"] == row.normalized_mineral_id,
                ["date", "price"],
            ].copy()
        if frame.empty:
            continue
        frame["normalized_mineral_id"] = row.normalized_mineral_id
        frame["mineral_name"] = row.mineral_name
        frame["source_type"] = row.price_source_type
        frames.append(frame)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _resolve_tradingeconomics_api_key() -> str | None:
    for env_name in ("TRADING_ECONOMICS_API_KEY", "TRADINGECONOMICS_API_KEY"):
        value = os.getenv(env_name)
        if value:
            return value
    config_path = Path(".config")
    if not config_path.exists():
        return None
    for line in config_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("TRADING_ECONOMICS_API_KEY="):
            return line.split("=", 1)[1].strip()
        if line.startswith("TRADINGECONOMICS_API_KEY="):
            return line.split("=", 1)[1].strip()
    return None


def to_yfinance_equity_symbol(ticker_normalized: str, market: str) -> str:
    if market == "US":
        return ticker_normalized
    if market == "HK":
        code = ticker_normalized.split(".")[0].zfill(4)
        return f"{code}.HK"
    if market == "CN_A":
        code, suffix = ticker_normalized.split(".")
        yahoo_suffix = "SS" if suffix == "SH" else suffix
        return f"{code}.{yahoo_suffix}"
    raise ValueError(f"Unsupported market: {market}")


def fetch_public_stock_prices(
    stock_mapping: pd.DataFrame,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    tickers = stock_mapping[["ticker_normalized", "market"]].drop_duplicates().sort_values(
        ["market", "ticker_normalized"]
    )
    for row in tickers.itertuples(index=False):
        symbol = to_yfinance_equity_symbol(row.ticker_normalized, row.market)
        frame = fetch_yfinance_history(symbol, start_date=start_date, end_date=end_date)
        if frame.empty:
            continue
        frame["ticker_normalized"] = row.ticker_normalized
        frame["market"] = row.market
        frame = frame.rename(columns={"price": "adj_close"})
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_fx_to_usd_history(*, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    symbol_map = {
        "HK": ("USDHKD=X", lambda close: 1.0 / close),
        "CN_A": ("USDCNY=X", lambda close: 1.0 / close),
    }
    for market, (symbol, transform) in symbol_map.items():
        frame = fetch_yfinance_history(symbol, start_date=start_date, end_date=end_date)
        if frame.empty:
            continue
        frame["market"] = market
        frame["fx_to_usd"] = frame["price"].map(transform)
        rows.append(frame[["date", "market", "fx_to_usd"]])
    if not rows:
        return pd.DataFrame(columns=["date", "market", "fx_to_usd"])
    return pd.concat(rows, ignore_index=True)


def attach_fx_to_stock_prices(stock_prices: pd.DataFrame, fx_history: pd.DataFrame) -> pd.DataFrame:
    if stock_prices.empty:
        return stock_prices.copy()
    frame = stock_prices.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["fx_to_usd"] = 1.0
    if fx_history.empty:
        return frame

    fx_frame = fx_history.copy()
    fx_frame["date"] = pd.to_datetime(fx_frame["date"])
    for market in ("HK", "CN_A"):
        market_mask = frame["market"] == market
        if not market_mask.any():
            continue
        market_fx = fx_frame.loc[fx_frame["market"] == market, ["date", "fx_to_usd"]].sort_values("date")
        if market_fx.empty:
            continue
        merged = pd.merge_asof(
            frame.loc[market_mask].sort_values("date"),
            market_fx,
            on="date",
            direction="backward",
        )
        frame.loc[market_mask, "fx_to_usd"] = merged["fx_to_usd_y"].ffill().bfill().values
    return frame
