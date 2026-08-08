"""Current airline price and market-cap snapshot for long/short research.

This is a point-in-time market-data snapshot, not a historical price tape.
Market capitalizations come from AkShare's Baidu valuation history and are
converted from native hundred-million units; quotes use Tencent's public quote
endpoint because the bulk Eastmoney spot endpoint can be transiently blocked.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, NORMALIZED_DIR


MARKET_UNIVERSE: tuple[dict[str, str], ...] = (
    {"ticker": "0293.HK", "symbol": "00293", "market": "HK", "company": "Cathay Pacific", "currency": "HKD", "valuation_function": "stock_hk_valuation_baidu", "valuation_symbol": "00293"},
    {"ticker": "0753.HK", "symbol": "601111", "market": "HK", "company": "Air China", "currency": "HKD", "valuation_function": "stock_hk_valuation_baidu", "valuation_symbol": "00753"},
    {"ticker": "01055.HK", "symbol": "600029", "market": "HK", "company": "China Southern Airlines", "currency": "HKD", "valuation_function": "stock_hk_valuation_baidu", "valuation_symbol": "01055"},
    {"ticker": "0670.HK", "symbol": "600115", "market": "HK", "company": "China Eastern Airlines", "currency": "HKD", "valuation_function": "stock_hk_valuation_baidu", "valuation_symbol": "00670"},
    {"ticker": "601021.SH", "symbol": "601021", "market": "CN_A", "company": "Spring Airlines", "currency": "RMB", "valuation_function": "stock_zh_valuation_baidu", "valuation_symbol": "601021"},
    {"ticker": "603885.SH", "symbol": "603885", "market": "CN_A", "company": "Juneyao Airlines", "currency": "RMB", "valuation_function": "stock_zh_valuation_baidu", "valuation_symbol": "603885"},
    {"ticker": "600221.SH", "symbol": "600221", "market": "CN_A", "company": "Hainan Airlines Holdings", "currency": "RMB", "valuation_function": "stock_zh_valuation_baidu", "valuation_symbol": "600221"},
    {"ticker": "601111.SH", "symbol": "601111", "market": "CN_A", "company": "Air China", "currency": "RMB", "valuation_function": "stock_zh_valuation_baidu", "valuation_symbol": "601111"},
    {"ticker": "600029.SH", "symbol": "600029", "market": "CN_A", "company": "China Southern Airlines", "currency": "RMB", "valuation_function": "stock_zh_valuation_baidu", "valuation_symbol": "600029"},
    {"ticker": "600115.SH", "symbol": "600115", "market": "CN_A", "company": "China Eastern Airlines", "currency": "RMB", "valuation_function": "stock_zh_valuation_baidu", "valuation_symbol": "600115"},
)

MARKET_SNAPSHOT_COLUMNS = [
    "dataset_id", "ticker", "symbol", "market", "company", "snapshot_date",
    "quote_timestamp", "latest_price_native", "price_currency", "price_source",
    "market_cap_observation_date", "market_cap_native_mn", "market_cap_currency",
    "market_cap_source", "market_cap_usd_mn", "usd_fx_pair", "fx_observation_date",
    "fx_value", "source_quality", "quote_source_url", "market_cap_source_url",
    "source_note", "retrieved_at",
]


def _fx_asof(fx_rates: pd.DataFrame | None, *, pair: str, as_of: str) -> tuple[str | None, float | None]:
    if fx_rates is None or fx_rates.empty:
        return None, None
    frame = fx_rates.loc[fx_rates["pair"].eq(pair)].copy()
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    target = pd.Timestamp(as_of)
    frame = frame.loc[frame["observation_date"].le(target)].dropna(subset=["observation_date", "value"])
    if frame.empty:
        return None, None
    row = frame.sort_values("observation_date").iloc[-1]
    return row["observation_date"].strftime("%Y-%m-%d"), float(row["value"])


def _tencent_symbol(ticker: str) -> str:
    code, suffix = ticker.split(".", 1)
    if suffix == "HK":
        return f"hk{code.zfill(5)}"
    prefix = {"SH": "sh", "SZ": "sz"}[suffix]
    return f"{prefix}{code}"


def _parse_tencent_timestamp(value: str) -> pd.Timestamp | None:
    text = str(value)
    for fmt in ("%Y%m%d%H%M%S", "%Y/%m/%d %H:%M:%S"):
        parsed = pd.to_datetime(text, format=fmt, errors="coerce")
        if not pd.isna(parsed):
            return parsed.tz_localize("Asia/Shanghai")
    return None


def _tencent_quotes(universe: tuple[dict[str, str], ...], *, session: requests.Session) -> dict[str, tuple[pd.Timestamp, float]]:
    symbols = {_tencent_symbol(row["ticker"]): row["ticker"] for row in universe}
    if not symbols:
        return {}
    response = session.get(
        "https://qt.gtimg.cn/q=" + ",".join(symbols),
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=max(DEFAULT_TIMEOUT, 20),
    )
    response.raise_for_status()
    result: dict[str, tuple[pd.Timestamp, float]] = {}
    for market_symbol, ticker in symbols.items():
        marker = f'v_{market_symbol}="'
        start = response.text.find(marker)
        if start < 0:
            continue
        payload = response.text[start + len(marker):].split('"', 1)[0]
        fields = payload.split("~")
        if len(fields) <= 30:
            continue
        try:
            price = float(fields[3])
        except (TypeError, ValueError):
            continue
        timestamp = _parse_tencent_timestamp(fields[30])
        if price > 0 and timestamp is not None:
            result[ticker] = (timestamp, price)
    return result


def _latest_baidu_market_cap(symbol: str, function_name: str) -> tuple[str | None, float | None]:
    import akshare as ak

    frame = getattr(ak, function_name)(symbol=symbol, indicator="总市值")
    if frame is None or frame.empty or not {"date", "value"}.issubset(frame.columns):
        return None, None
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["date", "value"]).sort_values("date")
    if frame.empty:
        return None, None
    row = frame.iloc[-1]
    return row["date"].strftime("%Y-%m-%d"), float(row["value"])


def build_market_snapshot(
    *,
    universe: tuple[dict[str, str], ...] = MARKET_UNIVERSE,
    fx_rates: pd.DataFrame | None = None,
    session: requests.Session | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Fetch one current row per covered A/H share class."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    http = session or requests.Session()
    try:
        quotes = _tencent_quotes(universe, session=http)
    except Exception:
        quotes = {}
    rows: list[dict[str, Any]] = []
    for item in universe:
        market_cap_date: str | None = None
        market_cap_raw: float | None = None
        try:
            market_cap_date, market_cap_raw = _latest_baidu_market_cap(
                item["valuation_symbol"], item["valuation_function"]
            )
        except Exception:
            pass
        quote_timestamp, latest_price = quotes.get(item["ticker"], (None, None))
        snapshot_date = market_cap_date or (quote_timestamp.strftime("%Y-%m-%d") if quote_timestamp else None)
        cap_native_mn = market_cap_raw * 100.0 if market_cap_raw is not None else None
        fx_pair = "USD_HKD" if item["currency"] == "HKD" else "USD_CNY"
        fx_date, fx_value = (
            _fx_asof(fx_rates, pair=fx_pair, as_of=snapshot_date)
            if snapshot_date
            else (None, None)
        )
        cap_usd_mn = cap_native_mn / fx_value if cap_native_mn is not None and fx_value else None
        rows.append(
            {
                "dataset_id": "airline_market_snapshot",
                "ticker": item["ticker"],
                "symbol": item["symbol"],
                "market": item["market"],
                "company": item["company"],
                "snapshot_date": snapshot_date,
                "quote_timestamp": quote_timestamp.isoformat() if quote_timestamp else None,
                "latest_price_native": latest_price,
                "price_currency": item["currency"],
                "price_source": "tencent_public_quote" if latest_price is not None else None,
                "market_cap_observation_date": market_cap_date,
                "market_cap_native_mn": cap_native_mn,
                "market_cap_currency": item["currency"],
                "market_cap_source": "akshare_baidu_valuation" if cap_native_mn is not None else None,
                "market_cap_usd_mn": cap_usd_mn,
                "usd_fx_pair": fx_pair if fx_value is not None else None,
                "fx_observation_date": fx_date,
                "fx_value": fx_value,
                "source_quality": "market_snapshot_discovery",
                "quote_source_url": "https://qt.gtimg.cn/",
                "market_cap_source_url": f"akshare.{item['valuation_function']}(indicator=总市值)",
                "source_note": (
                    "Current quote and market-cap snapshot; quote and valuation observations can have separate timestamps. "
                    "Market capitalization was returned by the public Baidu valuation history in native hundred-million units."
                ),
                "retrieved_at": retrieved,
            }
        )
    return pd.DataFrame(rows, columns=MARKET_SNAPSHOT_COLUMNS)


def fetch_airline_market_snapshot() -> pd.DataFrame:
    fx_path = NORMALIZED_DIR / "airline_fx_rates.parquet"
    fx_rates = pd.read_parquet(fx_path) if fx_path.exists() else None
    result = build_market_snapshot(fx_rates=fx_rates)
    result.to_csv(NORMALIZED_DIR / "airline_market_snapshot.csv", index=False)
    expectations = merge_market_expectations(result)
    expectations.to_csv(NORMALIZED_DIR / "airline_market_expectations_snapshot.csv", index=False)
    return result


def merge_market_expectations(
    market: pd.DataFrame,
    *,
    hk_consensus: pd.DataFrame | None = None,
    ashare_consensus: pd.DataFrame | None = None,
    ashare_detailed_consensus: pd.DataFrame | None = None,
    revenue_consensus: pd.DataFrame | None = None,
    fx_rates: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Join current market data to the latest FY2026 public expectation rows."""
    hk = hk_consensus
    if hk is None:
        path = NORMALIZED_DIR / "airline_consensus_snapshot.csv"
        hk = pd.read_csv(path) if path.exists() else pd.DataFrame()
    ashare = ashare_consensus
    if ashare is None:
        path = NORMALIZED_DIR / "airline_consensus_ashare_snapshot.csv"
        ashare = pd.read_csv(path) if path.exists() else pd.DataFrame()
    detailed = ashare_detailed_consensus
    if detailed is None:
        path = NORMALIZED_DIR / "airline_consensus_ashare_detailed.csv"
        detailed = pd.read_csv(path) if path.exists() else pd.DataFrame()
    revenue_estimates = revenue_consensus
    if revenue_estimates is None:
        path = NORMALIZED_DIR / "airline_revenue_consensus_yfinance.csv"
        revenue_estimates = pd.read_csv(path) if path.exists() else pd.DataFrame()
    if fx_rates is None:
        path = NORMALIZED_DIR / "airline_fx_rates.parquet"
        fx_rates = pd.read_parquet(path) if path.exists() else pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for _, item in market.iterrows():
        current_price = pd.to_numeric(item.get("latest_price_native"), errors="coerce")
        consensus_source = None
        consensus_date = None
        broker_count = None
        eps_avg = eps_low = eps_high = None
        eps_avg_usd = eps_low_usd = eps_high_usd = None
        net_profit_avg_mn = net_profit_low_mn = net_profit_high_mn = None
        net_profit_avg_usd_mn = net_profit_low_usd_mn = net_profit_high_usd_mn = None
        target_price = None
        target_price_usd = None
        target_price_currency = None
        revenue_avg_mn = None
        revenue_low_mn = None
        revenue_high_mn = None
        revenue_avg_usd_mn = revenue_low_usd_mn = revenue_high_usd_mn = None
        revenue_analyst_count = None
        revenue_growth_pct = None
        revenue_consensus_date = None
        revenue_consensus_source = None
        revenue_consensus_source_ticker = None
        revenue_consensus_scope = None
        revenue_fx_pair = None
        revenue_fx_observation_date = None
        revenue_fx_value = None
        if item["market"] == "HK" and not hk.empty:
            candidates = hk.loc[
                hk["ticker"].eq(item["ticker"]) & hk["fiscal_year"].eq(2026)
            ]
            if not candidates.empty:
                row = candidates.iloc[0]
                eps_avg, eps_low, eps_high = row[["eps_avg_native", "eps_low_native", "eps_high_native"]]
                if {"eps_avg_usd", "eps_low_usd", "eps_high_usd"}.issubset(row.index):
                    eps_avg_usd, eps_low_usd, eps_high_usd = row[
                        ["eps_avg_usd", "eps_low_usd", "eps_high_usd"]
                    ]
                net_profit_avg_mn, net_profit_low_mn, net_profit_high_mn = row[
                    ["net_profit_avg_native_mn", "net_profit_low_native_mn", "net_profit_high_native_mn"]
                ]
                if {
                    "net_profit_avg_usd_mn",
                    "net_profit_low_usd_mn",
                    "net_profit_high_usd_mn",
                }.issubset(row.index):
                    net_profit_avg_usd_mn, net_profit_low_usd_mn, net_profit_high_usd_mn = row[
                        [
                            "net_profit_avg_usd_mn",
                            "net_profit_low_usd_mn",
                            "net_profit_high_usd_mn",
                        ]
                    ]
                target_price = row.get("target_price_avg_hkd")
                target_price_usd = row.get("target_price_avg_usd")
                target_price_currency = "HKD"
                consensus_source = row.get("source_quality")
                consensus_date = row.get("snapshot_date")
                broker_count = row.get("broker_count")
        elif item["market"] == "CN_A" and not ashare.empty:
            candidates = ashare.loc[
                ashare["ticker"].astype(str).str.contains(re.escape(str(item["ticker"])), regex=True)
                & ashare["fiscal_year"].eq(2026)
            ]
            eps_rows = candidates.loc[candidates["metric"].eq("eps")]
            profit_rows = candidates.loc[candidates["metric"].eq("net_profit")]
            if not eps_rows.empty:
                row = eps_rows.iloc[0]
                eps_avg, eps_low, eps_high = row[["value_avg_native", "value_low_native", "value_high_native"]]
                if {
                    "value_avg_usd_at_snapshot",
                    "value_low_usd_at_snapshot",
                    "value_high_usd_at_snapshot",
                }.issubset(row.index):
                    eps_avg_usd, eps_low_usd, eps_high_usd = row[
                        [
                            "value_avg_usd_at_snapshot",
                            "value_low_usd_at_snapshot",
                            "value_high_usd_at_snapshot",
                        ]
                    ]
                consensus_source = row.get("source_quality")
                consensus_date = row.get("snapshot_date")
                broker_count = row.get("forecast_count")
            if not profit_rows.empty:
                row = profit_rows.iloc[0]
                net_profit_avg_mn, net_profit_low_mn, net_profit_high_mn = [
                    pd.to_numeric(row[column], errors="coerce") * 100.0
                    for column in ("value_avg_native", "value_low_native", "value_high_native")
                ]
                if {
                    "value_avg_usd_at_snapshot",
                    "value_low_usd_at_snapshot",
                    "value_high_usd_at_snapshot",
                }.issubset(row.index):
                    net_profit_avg_usd_mn, net_profit_low_usd_mn, net_profit_high_usd_mn = [
                        pd.to_numeric(row[column], errors="coerce") * 100.0
                        for column in (
                            "value_avg_usd_at_snapshot",
                            "value_low_usd_at_snapshot",
                            "value_high_usd_at_snapshot",
                        )
                    ]
                consensus_source = consensus_source or row.get("source_quality")
                consensus_date = consensus_date or row.get("snapshot_date")
                broker_count = broker_count or row.get("forecast_count")

        if not revenue_estimates.empty:
            revenue_candidates = revenue_estimates.loc[
                revenue_estimates["ticker"].eq(item["ticker"])
                & revenue_estimates["fiscal_year"].eq(2026)
            ]
            if not revenue_candidates.empty:
                row = revenue_candidates.iloc[0]
                revenue_avg_mn = pd.to_numeric(row.get("revenue_avg_native_mn"), errors="coerce")
                revenue_low_mn = pd.to_numeric(row.get("revenue_low_native_mn"), errors="coerce")
                revenue_high_mn = pd.to_numeric(row.get("revenue_high_native_mn"), errors="coerce")
                revenue_analyst_count = pd.to_numeric(row.get("analyst_count"), errors="coerce")
                revenue_growth_pct = pd.to_numeric(row.get("growth_pct"), errors="coerce")
                revenue_consensus_date = row.get("snapshot_date")
                revenue_consensus_source = row.get("source_quality")
                revenue_consensus_source_ticker = row.get("source_ticker")
                revenue_consensus_scope = "direct_ticker_vendor_estimate"
                revenue_currency = row.get("native_currency") or (
                    "HKD" if item["market"] == "HK" else "RMB"
                )
                revenue_fx_pair = "USD_HKD" if revenue_currency == "HKD" else "USD_CNY"
                revenue_fx_observation_date, revenue_fx_value = _fx_asof(
                    fx_rates, pair=revenue_fx_pair, as_of=revenue_consensus_date
                )
                if revenue_fx_value:
                    revenue_avg_usd_mn = revenue_avg_mn / revenue_fx_value
                    revenue_low_usd_mn = revenue_low_mn / revenue_fx_value
                    revenue_high_usd_mn = revenue_high_mn / revenue_fx_value

        # The A-share detailed forecast is a consolidated-company expectation.
        # For dual-listed H shares, use it only as a clearly labelled
        # cross-market proxy rather than pretending it is direct HK broker
        # consensus. Cathay has no matching A-share source and remains blank.
        if revenue_avg_mn is None and not detailed.empty:
            if "company" in detailed.columns:
                detailed_match = detailed["company"].eq(item["company"])
            else:
                detailed_match = detailed["ticker"].astype(str).str.contains(
                    re.escape(str(item["ticker"])), regex=True
                )
            detailed_candidates = detailed.loc[detailed_match & detailed["fiscal_year"].eq(2026)]
            revenue_rows = detailed_candidates.loc[detailed_candidates["metric"].eq("revenue")]
            growth_rows = detailed_candidates.loc[detailed_candidates["metric"].eq("revenue_growth")]
            if not revenue_rows.empty:
                row = revenue_rows.iloc[0]
                revenue_avg_mn = pd.to_numeric(row.get("value_avg_native"), errors="coerce") * 100.0
                revenue_consensus_date = row.get("snapshot_date")
                revenue_consensus_source = (
                    "cross_market_ashare_detailed_discovery"
                    if item["market"] == "HK"
                    else row.get("source_quality")
                )
                revenue_consensus_source_ticker = row.get("ticker")
                revenue_consensus_scope = (
                    "consolidated_group_cross_market_proxy"
                    if item["market"] == "HK"
                    else "consolidated_group"
                )
                revenue_currency = row.get("native_currency", "RMB")
                revenue_fx_pair = "USD_HKD" if revenue_currency == "HKD" else "USD_CNY"
                revenue_fx_observation_date, revenue_fx_value = _fx_asof(
                    fx_rates, pair=revenue_fx_pair, as_of=revenue_consensus_date
                )
                if revenue_fx_value:
                    revenue_avg_usd_mn = revenue_avg_mn / revenue_fx_value
            if not growth_rows.empty:
                revenue_growth_pct = pd.to_numeric(
                    growth_rows.iloc[0].get("value_avg_native"), errors="coerce"
                )

        forward_pe = None
        if pd.notna(current_price) and pd.notna(eps_avg) and float(eps_avg) > 0:
            forward_pe = float(current_price) / float(eps_avg)
        market_cap_pe = None
        cap = pd.to_numeric(item.get("market_cap_native_mn"), errors="coerce")
        if pd.notna(cap) and pd.notna(net_profit_avg_mn) and float(net_profit_avg_mn) > 0:
            market_cap_pe = float(cap) / float(net_profit_avg_mn)
        market_cap_pe_usd = None
        market_cap_revenue_usd = None
        consensus_net_margin_pct = None
        market_cap_usd = pd.to_numeric(item.get("market_cap_usd_mn"), errors="coerce")
        if pd.notna(market_cap_usd) and net_profit_avg_usd_mn is not None and float(net_profit_avg_usd_mn) > 0:
            market_cap_pe_usd = float(market_cap_usd) / float(net_profit_avg_usd_mn)
        if pd.notna(market_cap_usd) and revenue_avg_usd_mn is not None and float(revenue_avg_usd_mn) > 0:
            market_cap_revenue_usd = float(market_cap_usd) / float(revenue_avg_usd_mn)
        if net_profit_avg_usd_mn is not None and revenue_avg_usd_mn is not None and float(revenue_avg_usd_mn) > 0:
            consensus_net_margin_pct = 100.0 * float(net_profit_avg_usd_mn) / float(revenue_avg_usd_mn)
        profit_range_crosses_zero = (
            net_profit_low_usd_mn is not None
            and net_profit_high_usd_mn is not None
            and float(net_profit_low_usd_mn) <= 0 <= float(net_profit_high_usd_mn)
        )
        valuation_quality = (
            "unstable_profit_base"
            if net_profit_avg_usd_mn is None
            or float(net_profit_avg_usd_mn) <= 0
            or profit_range_crosses_zero
            else "profit_based_multiple_usable"
        )
        target_upside = None
        if pd.notna(target_price) and pd.notna(current_price) and float(current_price) > 0:
            target_upside = float(target_price) / float(current_price) - 1.0
        rows.append(
            {
                "dataset_id": "airline_market_expectations_snapshot",
                "ticker": item["ticker"],
                "company": item["company"],
                "market": item["market"],
                "snapshot_date": item["snapshot_date"],
                "latest_price_native": current_price,
                "price_currency": item["price_currency"],
                "market_cap_usd_mn": item["market_cap_usd_mn"],
                "fy2026_eps_avg_native": eps_avg,
                "fy2026_eps_low_native": eps_low,
                "fy2026_eps_high_native": eps_high,
                "fy2026_eps_avg_usd": eps_avg_usd,
                "fy2026_eps_low_usd": eps_low_usd,
                "fy2026_eps_high_usd": eps_high_usd,
                "fy2026_net_profit_avg_native_mn": net_profit_avg_mn,
                "fy2026_net_profit_low_native_mn": net_profit_low_mn,
                "fy2026_net_profit_high_native_mn": net_profit_high_mn,
                "fy2026_net_profit_avg_usd_mn": net_profit_avg_usd_mn,
                "fy2026_net_profit_low_usd_mn": net_profit_low_usd_mn,
                "fy2026_net_profit_high_usd_mn": net_profit_high_usd_mn,
                "fy2026_revenue_avg_native_mn": revenue_avg_mn,
                "fy2026_revenue_low_native_mn": revenue_low_mn,
                "fy2026_revenue_high_native_mn": revenue_high_mn,
                "fy2026_revenue_avg_usd_mn": revenue_avg_usd_mn,
                "fy2026_revenue_low_usd_mn": revenue_low_usd_mn,
                "fy2026_revenue_high_usd_mn": revenue_high_usd_mn,
                "revenue_fx_pair": revenue_fx_pair,
                "revenue_fx_observation_date": revenue_fx_observation_date,
                "revenue_fx_value": revenue_fx_value,
                "fy2026_revenue_analyst_count": revenue_analyst_count,
                "fy2026_revenue_growth_pct": revenue_growth_pct,
                "consensus_forward_pe": forward_pe,
                "market_cap_to_consensus_net_profit": market_cap_pe,
                "market_cap_to_consensus_net_profit_usd": market_cap_pe_usd,
                "market_cap_to_consensus_revenue_usd": market_cap_revenue_usd,
                "fy2026_consensus_net_margin_pct": consensus_net_margin_pct,
                "fy2026_profit_range_crosses_zero": profit_range_crosses_zero,
                "consensus_valuation_quality": valuation_quality,
                "target_price_avg_native": target_price,
                "target_price_currency": target_price_currency,
                "target_price_avg_usd": target_price_usd,
                "target_price_upside_pct": target_upside * 100.0 if target_upside is not None else None,
                "broker_count": broker_count,
                "consensus_snapshot_date": consensus_date,
                "consensus_source_quality": consensus_source,
                "revenue_consensus_snapshot_date": revenue_consensus_date,
                "revenue_consensus_source_quality": revenue_consensus_source,
                "revenue_consensus_source_ticker": revenue_consensus_source_ticker,
                "revenue_consensus_scope": revenue_consensus_scope,
                "source_note": (
                    "Derived bridge joining the current market snapshot to public FY2026 EPS/net-profit expectations. "
                    "Revenue fields prefer direct-ticker Yahoo Finance estimates with average/low/high and analyst count; "
                    "where unavailable they fall back to the 10jqka detailed-indicator average-only group layer. "
                    "A-share fallback values are consolidated-group estimates; an HK fallback is a same-company "
                    "cross-market proxy, not direct HK broker consensus. "
                    "Consensus rows are asynchronous discovery snapshots."
                ),
                "retrieved_at": item["retrieved_at"],
            }
        )
    return pd.DataFrame(rows)


def source_path() -> Path:
    return NORMALIZED_DIR / "airline_market_snapshot.csv"
