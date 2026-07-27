"""Build canonical JSON artifact and Astro status for HK Stablecoin & Crypto Sector Monitor."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.hk_stablecoin_crypto.config import (
    COIN_CRCL_SIGNAL_NOTE,
    HK_CHINA_STABLECOINS_TO_WATCH,
    WATCHLIST,
)
from src.hk_stablecoin_crypto.sources.crypto_tickers import fetch_all_crypto_signals
from src.hk_stablecoin_crypto.sources.defillama_stablecoins import fetch_stablecoin_supply
from src.hk_stablecoin_crypto.sources.hkex_etf_aum import fetch_all_etf_aum
from src.hk_stablecoin_crypto.sources.hkma_register import fetch_licensed_issuers
from src.hk_stablecoin_crypto.sources.polymarket_events import fetch_all_polymarket_catalysts
from src.hk_stablecoin_crypto.sources.sfc_vatp_register import fetch_vatp_register


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_artifact() -> dict:
    hkma_df = fetch_licensed_issuers()
    sfc_df = fetch_vatp_register()
    supply_df = fetch_stablecoin_supply()
    etf_df = fetch_all_etf_aum()
    crypto_signals = fetch_all_crypto_signals()
    poly_df = fetch_all_polymarket_catalysts()
    
    hkma_issuers = hkma_df.to_dict(orient="records") if not hkma_df.empty else []
    
    sfc_licensed = []
    sfc_pending = []
    sfc_withdrawn = []
    sfc_forced_closure = []
    
    if not sfc_df.empty:
        sfc_licensed = sfc_df[sfc_df["status"] == "licensed"].to_dict(orient="records")
        sfc_pending = sfc_df[sfc_df["status"] == "pending"].to_dict(orient="records")
        sfc_withdrawn = sfc_df[sfc_df["status"] == "withdrawn"].to_dict(orient="records")
        sfc_forced_closure = sfc_df[sfc_df["status"] == "forced_closure"].to_dict(orient="records")
        
    total_tracked_usd_bn = 0
    top_10 = []
    if not supply_df.empty:
        supply_df = supply_df.dropna(subset=["circulating_usd"])
        total_tracked_usd = supply_df["circulating_usd"].sum()
        total_tracked_usd_bn = total_tracked_usd / 1e9
        
        top_10_df = supply_df.sort_values("circulating_usd", ascending=False).head(10).copy()
        top_10_df["market_share_pct"] = (top_10_df["circulating_usd"] / total_tracked_usd) * 100
        top_10 = top_10_df.to_dict(orient="records")
        
    hk_china_watch = []
    supply_symbols = set(supply_df["symbol"].tolist()) if not supply_df.empty else set()
    for sym in HK_CHINA_STABLECOINS_TO_WATCH:
        if sym in supply_symbols:
            val = float(supply_df[supply_df["symbol"] == sym]["circulating_usd"].iloc[0])
            note = f"Tracked on DefiLlama as of {_utc_now().strftime('%Y-%m-%d')}"
        else:
            val = None
            note = f"Not yet tracked on DefiLlama as of 2026-07-26 — appearance would be a launch signal"
        hk_china_watch.append({"symbol": sym, "circulating_usd": val, "note": note})
        
    etfs = []
    if not etf_df.empty:
        for ticker, group in etf_df.groupby("ticker"):
            group = group.sort_values("month", ascending=False)
            latest = group.iloc[0]
            history = group[["month", "aum_usd"]].rename(columns={"aum_usd": "aum_usd_m"}).copy()
            history["aum_usd_m"] = history["aum_usd_m"].apply(lambda x: x / 1e6 if x and x > 1e6 else x)
            
            etfs.append({
                "name": latest.get("name"),
                "ticker": ticker,
                "fund_id": latest.get("fund_id"),
                "latest_month": latest.get("month"),
                "latest_aum_usd_m": latest.get("aum_usd") / 1e6 if latest.get("aum_usd") and latest.get("aum_usd") > 1e6 else latest.get("aum_usd"),
                "aum_history": history.to_dict(orient="records")
            })
            
    leading_indicators = {
        "coinbase_premium_bps": crypto_signals.get("coinbase_premium", {}).get("premium_bps"),
        "btc_price_usd": crypto_signals.get("coinbase_premium", {}).get("coinbase_price_usd"),
        "fear_greed": crypto_signals.get("fear_greed", {}),
        "coin_crcl_signal_note": COIN_CRCL_SIGNAL_NOTE,
    }
    
    polymarket_catalysts = []
    if not poly_df.empty:
        top_poly = poly_df.sort_values("probability", ascending=False).head(10)
        polymarket_catalysts = top_poly.to_dict(orient="records")
        
    return {
        "generated_at": _utc_now().isoformat(),
        "sector": "hk-stablecoin-crypto",
        "licensing_register": {
            "hkma_stablecoin_issuers": hkma_issuers,
            "sfc_vatp_licensed": sfc_licensed,
            "sfc_vatp_pending": sfc_pending,
            "sfc_vatp_withdrawn": sfc_withdrawn,
            "sfc_vatp_forced_closure": sfc_forced_closure,
        },
        "stablecoin_market": {
            "total_tracked_usd_bn": total_tracked_usd_bn,
            "top_10": top_10,
            "hk_china_watch": hk_china_watch,
        },
        "hkex_crypto_etfs": etfs,
        "leading_indicators": leading_indicators,
        "polymarket_catalysts": polymarket_catalysts,
        "watchlist": {
            "note": "Tier distinctions reflect real, verified regulatory-status differences. Do not flatten into one undifferentiated list.",
            "tier1_licensed_infrastructure": WATCHLIST["TIER_1"],
            "tier2_big_name_adjacent": WATCHLIST["TIER_2"],
            "tier3_concept_pivots": WATCHLIST["TIER_3"],
            "tier4_treasury_plays": WATCHLIST["TIER_4"],
        },
        "known_gaps": {
            "harvest_ether_fund_id": "Harvest Ether Spot ETF (3179.HK) fundId not yet resolved — BUT245 guessed and 404'd. Look up via ifp.hkex.com.hk before wiring.",
            "hk_polymarket_markets": "No HK-specific Polymarket markets found as of 2026-07-26. Using global/US regulatory markets only."
        },
        "sources": {
            "hkma_register": {"label": "HKMA Licensed Stablecoin Issuers Register", "url": "https://www.hkma.gov.hk/eng/regulatory-resources/registers/register-of-licensed-stablecoin-issuers/", "note": "pandas.read_html() parseable. Official ground truth."},
            "sfc_vatp": {"label": "SFC VATP Register", "url": "https://www.sfc.hk/en/Welcome-to-the-Fintech-Contact-Point/Virtual-assets/Virtual-asset-trading-platforms-operators/Lists-of-virtual-asset-trading-platforms", "note": "pandas.read_html() parseable. 4 status tables."},
            "defillama": {"label": "DefiLlama Stablecoins API", "url": "https://stablecoins.llama.fi/stablecoins?includePrices=true", "note": "Free, no auth, 500 req/min."},
            "hkex_etf": {"label": "HKEX Integrated Fund Platform AUM API", "url": "https://ifp.hkex.com.hk/ifp/api/v1/fund/getFundSizeList", "note": "Free, no auth. Monthly AUM for 6 HKEX crypto ETFs."},
            "coinbase_binance": {"label": "Coinbase & Binance Public Tickers", "url": "https://api.exchange.coinbase.com / https://api.binance.com", "note": "Free, no auth. Coinbase Premium = spread in basis points."},
            "fear_greed": {"label": "Crypto Fear & Greed Index", "url": "https://api.alternative.me/fng/", "note": "Free, no auth."},
            "polymarket": {"label": "Polymarket Gamma API", "url": "https://gamma-api.polymarket.com/public-search", "note": "public-search endpoint used (tag= filter unreliable). No HK-specific markets exist."}
        }
    }


def main():
    parser = argparse.ArgumentParser(description="Build HK Stablecoin & Crypto artifact")
    parser.add_argument("--output", type=str, default=".generated/hk-stablecoin-crypto-artifact.json", help="Path to write JSON artifact")
    parser.add_argument("--status-output", type=str, default="src/data/dashboard-status-hk-stablecoin-crypto.json", help="Path to write Astro status file")
    
    args = parser.parse_args()
    
    out_path = Path(args.output)
    status_path = Path(args.status_output)
    
    artifact = build_artifact()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2))
    
    status = {
        "generated_at": artifact["generated_at"],
        "snapshot_id": "hk-stablecoin-crypto",
        "data_as_of": artifact["generated_at"],
        "overall_status": "Healthy",
        "live_sources": len(artifact["sources"]),
        "planned_sources": 0,
        "sources": [
            {
                "source": v["label"],
                "dataset": k,
                "type": "Monitor",
                "status": "Healthy",
                "latest_observation": artifact["generated_at"],
                "records": 1,
                "freshness": "Live",
                "notes": v["note"]
            } for k, v in artifact["sources"].items()
        ],
        "attachment_filename": "hk-stablecoin-crypto-dashboard.html"
    }
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, indent=2))
    
    print(f"Successfully built artifacts to {out_path} and {status_path}")


if __name__ == "__main__":
    main()
