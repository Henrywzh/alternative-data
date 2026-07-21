from __future__ import annotations

from pathlib import Path
import os
from io import StringIO
import re
from datetime import timedelta

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


def fetch_fred_history(
    series_id: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    api_key: str | None = None,
) -> pd.DataFrame:
    """Fetch a FRED series (e.g. IMF global commodity prices) as a daily price frame.

    FRED commodity series are monthly; we forward-fill onto business days so the
    downstream weekly resample/signal windows behave like the daily sources.
    """
    fred_key = api_key or _resolve_fred_api_key()
    if not fred_key:
        return pd.DataFrame(columns=["date", "price"])

    observation_start = start_date or "2018-01-01"
    url = (
        "https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}"
        f"&api_key={fred_key}"
        f"&file_type=json"
        f"&observation_start={observation_start}"
    )
    response = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    observations = response.json().get("observations", [])
    rows = [
        {"date": obs["date"], "price": float(obs["value"])}
        for obs in observations
        if obs.get("value", ".") != "."
    ]
    if not rows:
        return pd.DataFrame(columns=["date", "price"])

    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    series = frame.set_index("date").sort_index()["price"]
    upper = pd.Timestamp(end_date) if end_date else pd.Timestamp.today().normalize()
    daily = series.reindex(pd.date_range(series.index.min(), upper, freq="B")).ffill().dropna()
    result = daily.rename("price").rename_axis("date").reset_index()
    if start_date:
        result = result.loc[result["date"] >= pd.Timestamp(start_date)].copy()
    return result[["date", "price"]]


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
        elif row.price_source_type == "fred_series" and row.price_symbol_or_series_id:
            frame = fetch_fred_history(
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


def _resolve_fred_api_key() -> str | None:
    for env_name in ("FRED_API_KEY", "SEMICONDUCTOR_FRED_API_KEY", "MINERALS_FRED_API_KEY"):
        value = os.getenv(env_name)
        if value:
            return value
    config_path = Path(".config")
    if not config_path.exists():
        return None
    for line in config_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("FRED_API_KEY="):
            return line.split("=", 1)[1].strip()
    return None


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


def to_tencent_equity_symbol(ticker_normalized: str, market: str) -> str | None:
    """Convert normalized tickers to Tencent's undocumented quote symbols."""
    if market == "CN_A":
        code, suffix = ticker_normalized.upper().split(".", 1)
        prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(suffix)
        return f"{prefix}{code}" if prefix else None
    if market == "HK":
        code = ticker_normalized.split(".", 1)[0].zfill(5)
        return f"hk{code}"
    return None


def _empty_quote_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "date",
            "adj_close",
            "ticker_normalized",
            "market",
            "price_source",
            "source_timestamp",
            "price_is_adjusted",
        ]
    )


def _parse_tencent_timestamp(value: str) -> pd.Timestamp | pd.NaT:
    value = str(value or "").strip()
    for fmt in ("%Y%m%d%H%M%S", "%Y/%m/%d %H:%M:%S"):
        parsed = pd.to_datetime(value, format=fmt, errors="coerce")
        if not pd.isna(parsed):
            return parsed.tz_localize("Asia/Shanghai")
    return pd.NaT


def _extract_tencent_payload(body: str, symbol: str) -> str:
    marker = f'v_{symbol}="'
    start = body.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    end = body.find('"', start)
    return body[start:end] if end >= 0 else ""


def fetch_tencent_quotes(stock_mapping: pd.DataFrame, *, timeout: int = 20) -> pd.DataFrame:
    """Fetch current A-share/HK quotes from Tencent's public quote endpoint."""
    requested: list[tuple[str, str, str]] = []
    for row in stock_mapping[["ticker_normalized", "market"]].drop_duplicates().itertuples(index=False):
        symbol = to_tencent_equity_symbol(row.ticker_normalized, row.market)
        if symbol:
            requested.append((symbol, row.ticker_normalized, row.market))
    if not requested:
        return _empty_quote_frame()

    response = requests.get(
        "https://qt.gtimg.cn/q=" + ",".join(item[0] for item in requested),
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    rows: list[dict[str, object]] = []
    for symbol, ticker, market in requested:
        payload = _extract_tencent_payload(response.text, symbol)
        fields = payload.split("~")
        if len(fields) <= 30:
            continue
        try:
            price = float(fields[3])
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        source_timestamp = _parse_tencent_timestamp(fields[30])
        if pd.isna(source_timestamp):
            continue
        rows.append(
            {
                "date": source_timestamp.tz_convert("Asia/Shanghai").normalize().tz_localize(None),
                "adj_close": price,
                "ticker_normalized": ticker,
                "market": market,
                "price_source": "tencent",
                "source_timestamp": source_timestamp,
                "price_is_adjusted": False,
            }
        )
    return pd.DataFrame(rows) if rows else _empty_quote_frame()


def _akshare_quote_rows(
    frame: pd.DataFrame,
    *,
    market: str,
    requested: set[str],
    retrieved_at: pd.Timestamp,
) -> list[dict[str, object]]:
    if frame.empty or "代码" not in frame.columns or "最新价" not in frame.columns:
        return []
    rows: list[dict[str, object]] = []
    for row in frame[["代码", "最新价"]].itertuples(index=False):
        code = str(row[0]).split(".", 1)[0].strip()
        code = re.sub(r"\.0$", "", code)
        code = code.zfill(6 if market == "CN_A" else 5)
        ticker = f"{code}.{'SZ' if code.startswith(('0', '3')) and market == 'CN_A' else 'SH'}" if market == "CN_A" else f"{code}.HK"
        if ticker not in requested:
            continue
        try:
            price = float(row[1])
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        rows.append(
            {
                "date": retrieved_at.tz_convert("Asia/Shanghai").normalize().tz_localize(None),
                "adj_close": price,
                "ticker_normalized": ticker,
                "market": market,
                "price_source": "akshare_eastmoney",
                "source_timestamp": retrieved_at,
                "price_is_adjusted": False,
            }
        )
    return rows


def fetch_akshare_quotes(stock_mapping: pd.DataFrame) -> pd.DataFrame:
    """Fetch missing current quotes through AKShare/Eastmoney."""
    import akshare as ak

    retrieved_at = pd.Timestamp.now(tz="UTC")
    requested_by_market = {
        market: set(group["ticker_normalized"])
        for market, group in stock_mapping.groupby("market")
        if market in {"CN_A", "HK"}
    }
    rows: list[dict[str, object]] = []
    if requested_by_market.get("CN_A"):
        rows.extend(
            _akshare_quote_rows(
                ak.stock_zh_a_spot_em(),
                market="CN_A",
                requested=requested_by_market["CN_A"],
                retrieved_at=retrieved_at,
            )
        )
    if requested_by_market.get("HK"):
        rows.extend(
            _akshare_quote_rows(
                ak.stock_hk_spot_em(),
                market="HK",
                requested=requested_by_market["HK"],
                retrieved_at=retrieved_at,
            )
        )
    return pd.DataFrame(rows) if rows else _empty_quote_frame()


def fetch_yfinance_latest_quote(
    ticker_normalized: str,
    market: str,
    *,
    as_of_date: pd.Timestamp,
) -> pd.DataFrame:
    symbol = to_yfinance_equity_symbol(ticker_normalized, market)
    frame = fetch_yfinance_history(
        symbol,
        start_date=(as_of_date - timedelta(days=10)).date().isoformat(),
        end_date=(as_of_date + timedelta(days=1)).date().isoformat(),
    )
    if frame.empty:
        return _empty_quote_frame()
    frame = frame.dropna(subset=["price"]).sort_values("date")
    if frame.empty:
        return _empty_quote_frame()
    latest = frame.iloc[-1]
    latest_date = pd.Timestamp(latest["date"])
    latest_date = latest_date.tz_convert(None) if latest_date.tzinfo else latest_date
    return pd.DataFrame(
        [
            {
                "date": latest_date,
                "adj_close": float(latest["price"]),
                "ticker_normalized": ticker_normalized,
                "market": market,
                "price_source": "yfinance",
                "source_timestamp": pd.NaT,
                "price_is_adjusted": True,
            }
        ]
    )


def fetch_same_day_stock_quotes(
    stock_mapping: pd.DataFrame,
    *,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    """Fetch the latest quote with Tencent -> AKShare -> Yahoo fallback."""
    if stock_mapping.empty:
        return _empty_quote_frame()
    target_date = pd.Timestamp(as_of_date).normalize() if as_of_date else pd.Timestamp.now(tz="Asia/Shanghai").normalize().tz_localize(None)
    requested = stock_mapping[["ticker_normalized", "market"]].drop_duplicates()
    rows: list[pd.DataFrame] = []
    try:
        tencent = fetch_tencent_quotes(requested)
    except Exception:
        tencent = _empty_quote_frame()
    if not tencent.empty:
        rows.append(tencent)
    covered = set(tencent["ticker_normalized"]) if not tencent.empty else set()
    missing = requested.loc[~requested["ticker_normalized"].isin(covered)].copy()

    if not missing.empty:
        try:
            akshare = fetch_akshare_quotes(missing)
        except Exception:
            akshare = _empty_quote_frame()
        if not akshare.empty:
            rows.append(akshare)
        covered |= set(akshare["ticker_normalized"]) if not akshare.empty else set()

    missing = requested.loc[~requested["ticker_normalized"].isin(covered)].copy()
    for row in missing.itertuples(index=False):
        try:
            fallback = fetch_yfinance_latest_quote(
                row.ticker_normalized,
                row.market,
                as_of_date=target_date,
            )
        except Exception:
            fallback = _empty_quote_frame()
        if not fallback.empty:
            rows.append(fallback)
    if not rows:
        return _empty_quote_frame()
    result = pd.concat(rows, ignore_index=True)
    return result.loc[result["date"] <= target_date].reset_index(drop=True)


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
        frame["price_source"] = "yfinance"
        frame["source_timestamp"] = pd.NaT
        frame["price_is_adjusted"] = True
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if end_date is None or pd.Timestamp(end_date).normalize() >= pd.Timestamp.now(tz="Asia/Shanghai").normalize().tz_localize(None):
        same_day = fetch_same_day_stock_quotes(stock_mapping)
        if not same_day.empty:
            if start_date:
                same_day = same_day.loc[same_day["date"] >= pd.Timestamp(start_date)].copy()
            if end_date:
                same_day = same_day.loc[same_day["date"] <= pd.Timestamp(end_date)].copy()
            if result.empty:
                result = same_day
            else:
                keys = ["ticker_normalized", "market", "date"]
                result = pd.concat([result, same_day], ignore_index=True)
                result = result.drop_duplicates(keys, keep="last")
    return result.reset_index(drop=True) if not result.empty else result


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
    # Normalize to one timezone-naive nanosecond dtype before merge_asof.
    # pandas 3 can otherwise reject equivalent date columns with different
    # resolutions (for example datetime64[us] versus datetime64[s]).
    frame["date"] = (
        pd.to_datetime(frame["date"], errors="coerce", utc=True)
        .dt.tz_localize(None)
        .dt.normalize()
        .astype("datetime64[ns]")
    )
    frame["fx_to_usd"] = 1.0
    if fx_history.empty:
        return frame

    fx_frame = fx_history.copy()
    fx_frame["date"] = (
        pd.to_datetime(fx_frame["date"], errors="coerce", utc=True)
        .dt.tz_localize(None)
        .dt.normalize()
        .astype("datetime64[ns]")
    )
    for market in ("HK", "CN_A"):
        market_mask = frame["market"] == market
        if not market_mask.any():
            continue
        market_fx = (
            fx_frame.loc[fx_frame["market"] == market, ["date", "fx_to_usd"]]
            .rename(columns={"fx_to_usd": "fx_rate"})
            .sort_values("date")
        )
        if market_fx.empty:
            continue
        market_rows = frame.loc[market_mask].copy()
        market_rows["_row_index"] = market_rows.index
        merged = pd.merge_asof(
            market_rows.sort_values("date"),
            market_fx,
            on="date",
            direction="backward",
        )
        merged["fx_rate"] = merged["fx_rate"].ffill().bfill()
        values = merged.set_index("_row_index")["fx_rate"].reindex(market_rows.index)
        frame.loc[market_mask, "fx_to_usd"] = values.to_numpy()
    return frame
