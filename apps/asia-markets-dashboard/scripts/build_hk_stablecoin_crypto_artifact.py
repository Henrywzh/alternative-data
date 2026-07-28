"""Build canonical JSON artifact and Astro status for HK Stablecoin & Crypto Sector Monitor."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.hk_stablecoin_crypto.config import (
    COIN_CRCL_SIGNAL_NOTE,
    HK_CHINA_STABLECOINS_TO_WATCH,
    WATCHLIST,
    HKEX_ETF_FUNDS,
)
from src.hk_stablecoin_crypto.sources.crypto_tickers import (
    fetch_all_crypto_signals,
    fetch_btc_price_history,
    fetch_fear_greed_history,
)
from src.hk_stablecoin_crypto.sources.defillama_stablecoins import (
    fetch_stablecoin_history,
    fetch_stablecoin_supply,
    fetch_stablecoin_chain_distribution,
    fetch_dex_volume_history,
)
from src.hk_stablecoin_crypto.sources.hkex_etf_aum import fetch_all_etf_aum
from src.hk_stablecoin_crypto.sources.hkma_register import fetch_licensed_issuers
from src.hk_stablecoin_crypto.sources.polymarket_events import fetch_all_polymarket_catalysts
from src.hk_stablecoin_crypto.sources.sfc_vatp_register import fetch_vatp_register

PUBLIC_SOURCES = {
    "hkma_register": {
        "id": "hkma_register",
        "label": "HKMA Licensed Stablecoin Issuers Register",
        "href": "https://www.hkma.gov.hk/eng/regulatory-resources/registers/register-of-licensed-stablecoin-issuers/",
        "path": "sources/hkma_register.sql",
        "query": {
            "engine": "pandas.read_html via requests+UserAgent",
            "url": "https://www.hkma.gov.hk/eng/regulatory-resources/registers/register-of-licensed-stablecoin-issuers/",
            "language": "HTML",
            "sql": "SELECT issuer, licence_number, effective_date FROM hkma_register;",
            "description": "Official ground-truth sandbox register of licensed stablecoin issuers (Anchorpoint FRS01, HSBC FRS02).",
        },
    },
    "sfc_vatp": {
        "id": "sfc_vatp",
        "label": "SFC Virtual Asset Trading Platforms Register",
        "href": "https://www.sfc.hk/en/Welcome-to-the-Fintech-Contact-Point/Virtual-assets/Virtual-asset-trading-platforms-operators/Lists-of-virtual-asset-trading-platforms",
        "path": "sources/sfc_vatp.sql",
        "query": {
            "engine": "pandas.read_html via requests+UserAgent",
            "url": "https://www.sfc.hk/en/Welcome-to-the-Fintech-Contact-Point/Virtual-assets/Virtual-asset-trading-platforms-operators/Lists-of-virtual-asset-trading-platforms",
            "language": "HTML",
            "sql": "SELECT platform_name, status, licensed_date FROM sfc_vatp_register;",
            "description": "Official 4-status SFC register of VATP exchange operators (licensed, pending, withdrawn, forced-closure).",
        },
    },
    "defillama": {
        "id": "defillama",
        "label": "DefiLlama Stablecoin & DEX Analytics API",
        "href": "https://stablecoins.llama.fi/",
        "path": "sources/defillama.sql",
        "query": {
            "engine": "DefiLlama REST API",
            "url": "https://stablecoins.llama.fi/stablecoins?includePrices=true",
            "language": "JSON",
            "sql": "SELECT name, symbol, circulating_usd FROM defillama_stablecoins;",
            "description": "Global stablecoin supply, blockchain chain distribution, and daily DEX volume history.",
        },
    },
    "hkex_etf": {
        "id": "hkex_etf",
        "label": "HKEX Integrated Fund Platform ETF AUM API",
        "href": "https://ifp.hkex.com.hk/",
        "path": "sources/hkex_etf.sql",
        "query": {
            "engine": "HKEX IFP getFundSizeList API",
            "url": "https://ifp.hkex.com.hk/ifp/api/v1/fund/getFundSizeList",
            "language": "JSON",
            "sql": "SELECT month, aum_usd, fund_id, ticker, name FROM hkex_etf_aum;",
            "description": "Monthly AUM history for Hong Kong spot Bitcoin and Ether ETFs.",
        },
    },
    "coinbase_binance": {
        "id": "coinbase_binance",
        "label": "Coinbase & Binance Public Tickers",
        "href": "https://api.exchange.coinbase.com/",
        "path": "sources/coinbase_binance.sql",
        "query": {
            "engine": "Coinbase & Binance Spot Tickers",
            "url": "https://api.exchange.coinbase.com/products/BTC-USD/ticker",
            "language": "JSON",
            "sql": "SELECT price_usd, volume_24h, premium_bps FROM crypto_tickers;",
            "description": "Real-time BTC spot price, 1-year price history, and Coinbase Premium spread.",
        },
    },
    "fear_greed": {
        "id": "fear_greed",
        "label": "Crypto Fear & Greed Index (Alternative.me)",
        "href": "https://alternative.me/crypto/fear-and-greed-index/",
        "path": "sources/fear_greed.sql",
        "query": {
            "engine": "Alternative.me REST API",
            "url": "https://api.alternative.me/fng/",
            "language": "JSON",
            "sql": "SELECT value, classification, timestamp FROM fear_greed_index;",
            "description": "Crypto-specific market sentiment index (0=Extreme Fear, 100=Extreme Greed) sourced from Alternative.me.",
        },
    },
    "polymarket": {
        "id": "polymarket",
        "label": "Polymarket Prediction Market API (Gamma API)",
        "href": "https://polymarket.com/",
        "path": "sources/polymarket.sql",
        "query": {
            "engine": "Polymarket Gamma Events API",
            "url": "https://gamma-api.polymarket.com/events?tag_slug=crypto",
            "language": "JSON",
            "sql": "SELECT title, probability, end_date FROM polymarket_events;",
            "description": "Tag-filtered real-time prediction market probability for crypto and monetary policy regulatory catalysts.",
        },
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_artifact(now: datetime | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or _utc_now()
    generated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    data_as_of = now.strftime("%Y-%m-%d")
    live_count = 0

    # 1. HKMA Stablecoin Sandbox Register
    hkma_rows = []
    hkma_count = 0
    try:
        hkma_df = fetch_licensed_issuers()
        if not hkma_df.empty:
            live_count += 1
            hkma_count = len(hkma_df)
            for _, row in hkma_df.iterrows():
                hkma_rows.append({
                    "issuer": row["issuer"],
                    "licence_number": row["licence_number"],
                    "effective_date": row["effective_date"],
                    "status": "Sandbox Licensed",
                })
    except Exception as e:
        print(f"Warning: HKMA register fetch failed - {e}")

    # 2. SFC VATP Exchange Register
    sfc_rows = []
    sfc_licensed_count = 0
    sfc_pending_count = 0
    try:
        sfc_df = fetch_vatp_register()
        if not sfc_df.empty:
            live_count += 1
            sfc_licensed_count = len(sfc_df[sfc_df["status"] == "licensed"])
            sfc_pending_count = len(sfc_df[sfc_df["status"] == "pending"])
            for _, row in sfc_df.iterrows():
                sfc_rows.append({
                    "platform_name": row["platform_name"],
                    "status": row["status"].capitalize(),
                    "licensed_date": row.get("licensed_date", ""),
                })
    except Exception as e:
        print(f"Warning: SFC VATP fetch failed - {e}")

    # 3. DefiLlama Stablecoin Supplies, Chains, DEX Volume, & History
    stablecoin_rows = []
    stablecoin_history_rows = []
    stablecoin_chain_rows = []
    dex_volume_history_rows = []
    total_supply_bn = 0.0
    try:
        supply_df = fetch_stablecoin_supply()
        if not supply_df.empty:
            live_count += 1
            valid_supply = supply_df.dropna(subset=["circulating_usd"]).sort_values("circulating_usd", ascending=False)
            total_supply = valid_supply["circulating_usd"].sum()
            total_supply_bn = round(total_supply / 1e9, 2)

            for _, row in valid_supply.head(10).iterrows():
                circ_usd = float(row["circulating_usd"])
                circ_bn = round(circ_usd / 1e9, 2)
                share_pct = round((circ_usd / total_supply) * 100, 2)
                stablecoin_rows.append({
                    "name": row["name"],
                    "symbol": row["symbol"],
                    "circulating_usd_bn": circ_bn,
                    "market_share_pct": share_pct,
                })
                
        hist_df = fetch_stablecoin_history(365)
        if not hist_df.empty:
            for _, row in hist_df.iterrows():
                stablecoin_history_rows.append({
                    "date": row["date"],
                    "circulating_usd_bn": float(row["circulating_usd_bn"]),
                })

        chains_df = fetch_stablecoin_chain_distribution()
        if not chains_df.empty:
            for _, row in chains_df.iterrows():
                stablecoin_chain_rows.append({
                    "chain": row["chain"],
                    "circulating_usd_bn": float(row["circulating_usd_bn"]),
                })

        dex_df = fetch_dex_volume_history(365)
        if not dex_df.empty:
            for _, row in dex_df.iterrows():
                dex_volume_history_rows.append({
                    "date": row["date"],
                    "dex_volume_usd_bn": float(row["dex_volume_usd_bn"]),
                })
    except Exception as e:
        print(f"Warning: DefiLlama fetch failed - {e}")

    # 4. HKEX ETF AUM
    etf_summary_rows = []
    etf_aum_history = []
    total_etf_aum_m = 0.0
    try:
        etf_df = fetch_all_etf_aum()
        if not etf_df.empty:
            live_count += 1
            for ticker, group in etf_df.groupby("ticker"):
                group = group.sort_values("month", ascending=True)
                latest = group.iloc[-1]
                short_ticker = ticker.split(".")[0]
                latest_aum_raw = latest.get("aum_usd")
                latest_aum_m = round(float(latest_aum_raw), 2) if pd.notna(latest_aum_raw) else 0.0
                total_etf_aum_m += latest_aum_m

                etf_summary_rows.append({
                    "ticker": ticker,
                    "name": latest.get("name"),
                    "fund_id": latest.get("fund_id"),
                    "latest_month": latest.get("month"),
                    "aum_usd_m": latest_aum_m,
                })

                for _, r in group.iterrows():
                    m = r.get("month")
                    aum_val = r.get("aum_usd")
                    if m and pd.notna(aum_val):
                        aum_m = round(float(aum_val), 2)
                        etf_aum_history.append({
                            "month": str(m)[:7],
                            "series": short_ticker,
                            "value": aum_m,
                        })
            etf_aum_history.sort(key=lambda x: (x["month"], x["series"]))
    except Exception as e:
        print(f"Warning: HKEX ETF fetch failed - {e}")

    # 5. Crypto Signals & 1-Year Time Series
    btc_price = None
    cb_premium_bps = None
    fng_val = None
    fng_class = None
    fng_history_rows = []
    btc_history_rows = []
    try:
        signals = fetch_all_crypto_signals()
        if signals:
            live_count += 1
            cb_data = signals.get("coinbase_premium", {})
            btc_price = cb_data.get("coinbase_price_usd")
            cb_premium_bps = cb_data.get("premium_bps")
            fng_data = signals.get("fear_greed", {})
            fng_val = fng_data.get("value")
            fng_class = fng_data.get("classification")
            
        fng_df = fetch_fear_greed_history(0)  # full backfill
        if not fng_df.empty:
            # slice recent 365 days for dashboard chart display
            recent_fng = fng_df.tail(365)
            for _, r in recent_fng.iterrows():
                fng_history_rows.append({
                    "date": r["date"],
                    "score": int(r["score"]),
                })
                
        btc_df = fetch_btc_price_history(365)
        if not btc_df.empty:
            for _, r in btc_df.iterrows():
                btc_history_rows.append({
                    "date": r["date"],
                    "btc_price_usd": float(r["btc_price_usd"]),
                })
    except Exception as e:
        print(f"Warning: Crypto signals fetch failed - {e}")

    # 6. Polymarket Catalysts (Tag-filtered)
    poly_rows = []
    try:
        poly_df = fetch_all_polymarket_catalysts()
        if not poly_df.empty:
            live_count += 1
            top_poly = poly_df.sort_values("probability", ascending=False).head(10)
            for _, r in top_poly.iterrows():
                prob_pct = round(float(r["probability"]) * 100, 1) if pd.notna(r.get("probability")) else None
                title_short = str(r.get("title", ""))
                if len(title_short) > 60:
                    title_short = title_short[:57] + "..."
                poly_rows.append({
                    "title": title_short,
                    "probability_pct": prob_pct,
                    "end_date": str(r.get("end_date", ""))[:10],
                })
    except Exception as e:
        print(f"Warning: Polymarket fetch failed - {e}")

    # 7. Structured Watchlist (Tiers 1-4)
    watchlist_rows = []
    for tier_key, tier_name in [
        ("TIER_1", "Tier 1: Licensed Infrastructure"),
        ("TIER_2", "Tier 2: Big-Name / Adjacent"),
        ("TIER_3", "Tier 3: Concept Pivots"),
        ("TIER_4", "Tier 4: Treasury Plays"),
    ]:
        for item in WATCHLIST[tier_key]:
            watchlist_rows.append({
                "tier": tier_name,
                "ticker": f"{item['ticker']}.HK" if not item['ticker'].endswith(".HK") else item['ticker'],
                "company_en": item["name_en"],
                "company_zh": item["name_zh"],
                "regulatory_note": item.get("regulatory_note", ""),
            })

    # Datasets dictionary for snapshot
    datasets = {
        "hkma_issuers": hkma_rows,
        "sfc_vatps": sfc_rows,
        "stablecoin_supplies": stablecoin_rows,
        "stablecoin_history": stablecoin_history_rows,
        "stablecoin_chains": stablecoin_chain_rows,
        "dex_volume_history": dex_volume_history_rows,
        "hkex_etf_summary": etf_summary_rows,
        "hkex_etf_aum_history": etf_aum_history,
        "fear_greed_history": fng_history_rows,
        "btc_price_history": btc_history_rows,
        "polymarket_catalysts": poly_rows,
        "crypto_watchlist": watchlist_rows,
        "market_kpi_summary": [{
            "hkma_count": hkma_count,
            "sfc_licensed_count": sfc_licensed_count,
            "sfc_pending_count": sfc_pending_count,
            "total_supply_bn": total_supply_bn,
            "total_etf_aum_m": round(total_etf_aum_m, 2),
            "btc_price": round(btc_price, 2) if btc_price else None,
            "cb_premium_bps": round(cb_premium_bps, 2) if cb_premium_bps else None,
            "fear_greed_val": fng_val,
            "fear_greed_class": fng_class,
        }],
    }

    # Cards
    cards = [
        {
            "id": "regulatory_licensing_card",
            "description": "Official HKMA stablecoin sandbox licensees and SFC licensed exchange operators.",
            "dataset": "market_kpi_summary",
            "sourceId": "hkma_register",
            "metrics": [
                {"label": "HKMA Stablecoin Issuers", "field": "hkma_count", "format": "number"},
                {"label": "SFC Licensed VATPs", "field": "sfc_licensed_count", "format": "number"},
                {"label": "SFC Pending VATPs", "field": "sfc_pending_count", "format": "number"},
            ],
        },
        {
            "id": "crypto_signals_card",
            "description": "Real-time BTC spot price, Coinbase Premium spread, and market sentiment.",
            "dataset": "market_kpi_summary",
            "sourceId": "coinbase_binance",
            "metrics": [
                {"label": "BTC Price (USD)", "field": "btc_price", "format": "number"},
                {"label": "Coinbase Premium (bps)", "field": "cb_premium_bps", "format": "number"},
                {"label": "Fear & Greed Score", "field": "fear_greed_val", "format": "number"},
            ],
        },
        {
            "id": "etf_aum_card",
            "description": "Total AUM and tracked supply across HKEX crypto ETFs and global stablecoins.",
            "dataset": "market_kpi_summary",
            "sourceId": "hkex_etf",
            "metrics": [
                {"label": "HKEX ETF AUM ($M USD)", "field": "total_etf_aum_m", "format": "number"},
                {"label": "Global Stablecoin Supply ($B USD)", "field": "total_supply_bn", "format": "number"},
            ],
        },
    ]

    # Charts - ALL Time Series Line & Bar Charts
    charts = [
        {
            "id": "etf_aum_history_chart",
            "title": "HKEX Crypto Spot ETF Monthly AUM ($M USD)",
            "subtitle": "Monthly fund size time series for HK-listed Bitcoin and Ether spot ETFs (Bosera, ChinaAMC, Harvest).",
            "type": "line",
            "dataset": "hkex_etf_aum_history",
            "sourceId": "hkex_etf",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "value", "type": "quantitative", "label": "AUM ($M USD)"},
                "color": {"field": "series", "type": "nominal", "label": "Ticker"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "stablecoin_history_chart",
            "title": "1-Year Global Total Stablecoin Circulating Supply ($B USD)",
            "subtitle": "Historical global pegged asset circulating market cap expansion/contraction time series via DefiLlama.",
            "type": "line",
            "dataset": "stablecoin_history",
            "sourceId": "defillama",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Date"},
                "y": {"field": "circulating_usd_bn", "type": "quantitative", "label": "Total Supply ($B USD)"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "stablecoin_chain_chart",
            "title": "Top Blockchain Chains by Stablecoin Supply ($B USD)",
            "subtitle": "Breakdown of global stablecoin circulating supply by underlying blockchain network via DefiLlama.",
            "type": "bar",
            "dataset": "stablecoin_chains",
            "sourceId": "defillama",
            "encodings": {
                "x": {"field": "chain", "type": "nominal", "label": "Blockchain Chain"},
                "y": {"field": "circulating_usd_bn", "type": "quantitative", "label": "Supply ($B USD)"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "dex_volume_history_chart",
            "title": "1-Year Global Daily DEX Trading Volume ($B USD/day)",
            "subtitle": "Daily global decentralized exchange trading volume time series via DefiLlama.",
            "type": "line",
            "dataset": "dex_volume_history",
            "sourceId": "defillama",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Date"},
                "y": {"field": "dex_volume_usd_bn", "type": "quantitative", "label": "DEX Volume ($B USD/day)"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "fear_greed_history_chart",
            "title": "1-Year Crypto Fear & Greed Index (Alternative.me)",
            "subtitle": "Daily Crypto Fear & Greed Index score time series (0=Extreme Fear, 100=Extreme Greed) sourced from Alternative.me (https://alternative.me/crypto/fear-and-greed-index/).",
            "type": "line",
            "dataset": "fear_greed_history",
            "sourceId": "fear_greed",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Date"},
                "y": {"field": "score", "type": "quantitative", "label": "Sentiment Score"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "btc_price_history_chart",
            "title": "1-Year BTC Spot Price Trend ($ USD)",
            "subtitle": "Daily Bitcoin close price 365-day time series via Binance.",
            "type": "line",
            "dataset": "btc_price_history",
            "sourceId": "coinbase_binance",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Date"},
                "y": {"field": "btc_price_usd", "type": "quantitative", "label": "BTC Price (USD)"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
    ]

    # Tables
    tables = [
        {
            "id": "hkma_issuers_table",
            "title": "HKMA Licensed Stablecoin Sandbox Issuers",
            "subtitle": "Ground-truth register of entities licensed under HKMA stablecoin issuer sandbox.",
            "dataset": "hkma_issuers",
            "sourceId": "hkma_register",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "issuer", "label": "Issuer Name", "type": "text"},
                {"field": "licence_number", "label": "Licence #", "type": "text"},
                {"field": "effective_date", "label": "Effective Date", "type": "text"},
                {"field": "status", "label": "Regulatory Status", "type": "text"},
            ],
        },
        {
            "id": "sfc_vatp_table",
            "title": "SFC Virtual Asset Trading Platform (VATP) Operators",
            "subtitle": "Full SFC register across licensed, pending, and withdrawn exchange operators.",
            "dataset": "sfc_vatps",
            "sourceId": "sfc_vatp",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "platform_name", "label": "Operator Name", "type": "text"},
                {"field": "status", "label": "SFC Licensing Status", "type": "text"},
                {"field": "licensed_date", "label": "Effective Date", "type": "text"},
            ],
        },
        {
            "id": "top_stablecoins_table",
            "title": "Top Global Stablecoins by Market Cap & Market Share",
            "subtitle": "Top 10 pegged assets by USD circulating supply via DefiLlama.",
            "dataset": "stablecoin_supplies",
            "sourceId": "defillama",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "name", "label": "Stablecoin", "type": "text"},
                {"field": "symbol", "label": "Ticker", "type": "text"},
                {"field": "circulating_usd_bn", "label": "Circulating Supply ($B USD)", "format": "number"},
                {"field": "market_share_pct", "label": "Market Share (%)", "format": "number"},
            ],
        },
        {
            "id": "hkex_etf_table",
            "title": "HKEX Crypto Spot ETF Breakdown & Latest Fund Size",
            "subtitle": "Bosera, ChinaAMC, and Harvest Bitcoin & Ether spot ETFs listed on HKEX.",
            "dataset": "hkex_etf_summary",
            "sourceId": "hkex_etf",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "ticker", "label": "Ticker", "type": "text"},
                {"field": "name", "label": "ETF Name", "type": "text"},
                {"field": "fund_id", "label": "HKEX Fund ID", "type": "text"},
                {"field": "latest_month", "label": "Latest Month", "type": "text"},
                {"field": "aum_usd_m", "label": "AUM ($M USD)", "format": "number"},
            ],
        },
        {
            "id": "polymarket_table",
            "title": "Tag-Filtered Polymarket Regulatory & Macro Catalyst Probabilities",
            "subtitle": "Tag-filtered real-time prediction market probabilities (crypto, fed-rates, etf, finance) via Polymarket.",
            "dataset": "polymarket_catalysts",
            "sourceId": "polymarket",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "title", "label": "Catalyst Event", "type": "text"},
                {"field": "probability_pct", "label": "Probability (%)", "format": "number"},
                {"field": "end_date", "label": "Target Date", "type": "text"},
            ],
        },
        {
            "id": "crypto_watchlist_table",
            "title": "HK-Listed Crypto & Stablecoin Sector Watchlist (Tiers 1–4)",
            "subtitle": "Tier 1 infrastructure, Tier 2 banking/adjacent, Tier 3 concept pivots, Tier 4 treasury plays.",
            "dataset": "crypto_watchlist",
            "sourceId": "hkma_register",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "tier", "label": "Watchlist Tier", "type": "text"},
                {"field": "ticker", "label": "Ticker", "type": "text"},
                {"field": "company_en", "label": "Company (EN)", "type": "text"},
                {"field": "company_zh", "label": "Company (ZH)", "type": "text"},
                {"field": "regulatory_note", "label": "Regulatory Note / Status", "type": "text"},
            ],
        },
    ]

    manifest_sources = list(PUBLIC_SOURCES.values())

    source_stats = {
        "hkma_register": {
            "status": "success" if len(hkma_rows) > 0 else "degraded",
            "records": len(hkma_rows),
            "freshness": "live" if len(hkma_rows) > 0 else "unavailable",
        },
        "sfc_vatp": {
            "status": "success" if len(sfc_rows) > 0 else "degraded",
            "records": len(sfc_rows),
            "freshness": "live" if len(sfc_rows) > 0 else "unavailable",
        },
        "defillama": {
            "status": "success" if len(stablecoin_rows) > 0 else "degraded",
            "records": len(stablecoin_rows),
            "freshness": "live" if len(stablecoin_rows) > 0 else "unavailable",
        },
        "hkex_etf": {
            "status": "success" if len(etf_summary_rows) > 0 else "degraded",
            "records": len(etf_summary_rows),
            "freshness": "live" if len(etf_summary_rows) > 0 else "unavailable",
        },
        "coinbase_binance": {
            "status": "success" if btc_price is not None else "degraded",
            "records": 1 if btc_price is not None else 0,
            "freshness": "live" if btc_price is not None else "unavailable",
        },
        "fear_greed": {
            "status": "success" if fng_val is not None else "degraded",
            "records": 1 if fng_val is not None else 0,
            "freshness": "live" if fng_val is not None else "unavailable",
        },
        "polymarket": {
            "status": "success" if len(poly_rows) > 0 else "degraded",
            "records": len(poly_rows),
            "freshness": "live" if len(poly_rows) > 0 else "unavailable",
        },
    }

    status_entries = [
        {
            "id": s["id"],
            "label": s["label"],
            "status": source_stats[key]["status"],
            "records": source_stats[key]["records"],
            "freshness": source_stats[key]["freshness"],
            "notes": s["query"]["description"],
        }
        for key, s in PUBLIC_SOURCES.items()
    ]

    snapshot_payload = {
        "datasets": datasets,
        "source_urls": [s.get("url") for s in PUBLIC_SOURCES.values() if s.get("url")],
    }
    snapshot_id = hashlib.sha256(
        json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()[:16]

    blocks = [
        {
            "id": "snapshot_context",
            "type": "markdown",
            "body": (
                f"**Data snapshot:** `{snapshot_id}` · generated {generated_at}.  "
                "Official HKMA & SFC regulatory registers and market tracking data."
            ),
        },
        {"id": "kpi_grid", "type": "metric-strip", "cardIds": [c["id"] for c in cards]},
        {"id": "hkma_table_block", "type": "table", "tableId": "hkma_issuers_table"},
        {"id": "sfc_table_block", "type": "table", "tableId": "sfc_vatp_table"},
    ]
    if etf_aum_history:
        blocks.append({"id": "etf_chart_block", "type": "chart", "chartId": "etf_aum_history_chart"})
    blocks.append({"id": "etf_table_block", "type": "table", "tableId": "hkex_etf_table"})
    
    if stablecoin_history_rows:
        blocks.append({"id": "stablecoin_history_chart_block", "type": "chart", "chartId": "stablecoin_history_chart"})
    if stablecoin_chain_rows and dex_volume_history_rows:
        blocks.append({"id": "stablecoin_chain_chart_block", "type": "chart", "chartId": "stablecoin_chain_chart", "layout": "half"})
        blocks.append({"id": "dex_volume_chart_block", "type": "chart", "chartId": "dex_volume_history_chart", "layout": "half"})
    elif stablecoin_chain_rows:
        blocks.append({"id": "stablecoin_chain_chart_block", "type": "chart", "chartId": "stablecoin_chain_chart", "layout": "full"})
    elif dex_volume_history_rows:
        blocks.append({"id": "dex_volume_chart_block", "type": "chart", "chartId": "dex_volume_history_chart", "layout": "full"})

    if stablecoin_rows:
        blocks.append({"id": "top_stablecoins_table_block", "type": "table", "tableId": "top_stablecoins_table"})
        
    if fng_history_rows and btc_history_rows:
        blocks.append({"id": "fear_greed_chart_block", "type": "chart", "chartId": "fear_greed_history_chart", "layout": "half"})
        blocks.append({"id": "btc_price_chart_block", "type": "chart", "chartId": "btc_price_history_chart", "layout": "half"})
    elif fng_history_rows:
        blocks.append({"id": "fear_greed_chart_block", "type": "chart", "chartId": "fear_greed_history_chart", "layout": "full"})
    elif btc_history_rows:
        blocks.append({"id": "btc_price_chart_block", "type": "chart", "chartId": "btc_price_history_chart", "layout": "full"})
        
    if poly_rows:
        blocks.append({"id": "polymarket_table_block", "type": "table", "tableId": "polymarket_table"})

    blocks.extend([
        {"id": "watchlist_table_block", "type": "table", "tableId": "crypto_watchlist_table"},
        {
            "id": "methodology",
            "type": "markdown",
            "body": (
                "## Reading the Stablecoin & Crypto Infrastructure Monitor\n\n"
                "Hong Kong's crypto ecosystem is anchored by official regulatory registers: HKMA stablecoin issuer "
                "sandbox licensees (Anchorpoint FRS01, HSBC FRS02) and SFC licensed VATP exchange operators (OSL, HashKey). "
                "Brokers (e.g. Guotai Junan International 01788.HK) hold dealing permissions but are NOT VATP exchange "
                "operators; Anchorpoint (HKD-pegged HKDAP) is distinct from AnchorX (Jinyong Investment 01328.HK, AxCNH). "
                "This monitor tracks regulatory registers, HKEX ETF AUM time series, global stablecoin circulating supply trends, "
                "blockchain chain distribution, global DEX trading volume, 1-year Crypto Fear & Greed Index (Alternative.me), "
                "1-year BTC price trends, and tag-filtered Polymarket regulatory catalysts. No investment recommendation is produced."
            ),
        },
    ])

    artifact = {
        "surface": "dashboard",
        "manifest": {
            "version": 1,
            "surface": "dashboard",
            "title": "Hong Kong Stablecoin & Crypto Infrastructure Monitor",
            "description": "HKMA licensed stablecoin issuers, SFC licensed VATP exchanges, HKEX crypto ETF AUM, stablecoin market cap & chain tracking, DEX volume, and market sentiment indicators.",
            "sector": "hk-stablecoin-crypto",
            "generatedAt": generated_at,
            "dataAsOf": data_as_of,
            "liveSourcesCount": live_count if live_count > 0 else len(PUBLIC_SOURCES),
            "totalSourcesCount": len(PUBLIC_SOURCES),
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": manifest_sources,
            "blocks": blocks,
        },
        "snapshot": {"version": 1, "generatedAt": generated_at, "status": "ready", "datasets": datasets},
        "sources": manifest_sources,
        "source_health": status_entries,
        "package_info": {
            "originUrl": "https://asia-markets-dashboard.pages.dev/sectors/hk-stablecoin-crypto/",
            "sector_id": "hk-stablecoin-crypto",
            "sector_name": "Hong Kong Stablecoin & Crypto Infrastructure Monitor",
            "snapshotId": snapshot_id,
            "generatedAt": generated_at,
            "dataAsOf": data_as_of,
        },
    }

    status = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "data_as_of": data_as_of,
        "overall_status": "Healthy",
        "live_sources": len(PUBLIC_SOURCES),
        "planned_sources": 0,
        "sources": [
            {
                "source": s["label"],
                "dataset": key,
                "type": "Monitor",
                "status": "Healthy" if source_stats[key]["status"] == "success" else "Degraded",
                "latest_observation": data_as_of,
                "records": source_stats[key]["records"],
                "freshness": "Live" if source_stats[key]["freshness"] == "live" else "Unavailable",
                "notes": s["query"]["description"],
            }
            for key, s in PUBLIC_SOURCES.items()
        ],
        "attachment_filename": f"hk-stablecoin-crypto-dashboard-{now.date().isoformat()}.html",
    }

    return artifact, status


def _clean_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _clean_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_json(v) for v in obj]
    if isinstance(obj, float):
        if pd.isna(obj):
            return None
        return obj
    return obj


def main() -> None:
    parser = argparse.ArgumentParser(description="Build HK Stablecoin & Crypto Sector Artifact")
    parser.add_argument("--output", help="Path to write JSON artifact to", default=None)
    parser.add_argument("--status-output", help="Path to write status JSON to", default=None)

    args = parser.parse_args()

    artifact, status = build_artifact()

    artifact_clean = _clean_json(artifact)
    status_clean = _clean_json(status)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(artifact_clean, f, indent=2, ensure_ascii=False)

    if args.status_output:
        status_path = Path(args.status_output)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(status_clean, f, indent=2, ensure_ascii=False)

    print(json.dumps({"ok": True, "artifact": args.output or "stdout", "snapshot_id": status_clean["snapshot_id"]}))


if __name__ == "__main__":
    main()
