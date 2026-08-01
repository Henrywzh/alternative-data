"""Stage 1 execution pipeline for HK Stablecoin & Crypto Sector."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .sources.crypto_tickers import fetch_all_crypto_signals
from .sources.defillama_stablecoins import fetch_stablecoin_supply
from .sources.hkex_etf_aum import fetch_all_etf_aum
from .sources.hkexnews_announcements import fetch_hkexnews_announcements
from .sources.hkma_news import fetch_hkma_news
from .sources.hkma_register import fetch_licensed_issuers
from .sources.polymarket_events import fetch_all_polymarket_catalysts
from .sources.sfc_news import fetch_sfc_news
from .sources.sfc_vatp_register import fetch_vatp_register
from .sources.watchlist_price import fetch_watchlist_spot_quotes

logger = logging.getLogger(__name__)

QUALITY_SPECS = {
    "hkma_licensed_issuers": {
        "kind": "register",
        "required": ["issuer", "licence_number", "effective_date", "fetched_at"],
        "max_age_days": 7,
    },
    "sfc_vatp_register": {
        "kind": "register",
        "required": ["platform_name", "status", "fetched_at"],
        "max_age_days": 7,
    },
    "stablecoin_supply": {
        "kind": "measure",
        "required": ["name", "symbol", "circulating_usd", "fetched_at"],
        "max_age_days": 1,
    },
    "hkex_etf_aum": {
        "kind": "measure",
        "required": ["month", "aum_usd", "fund_id"],
        "max_age_days": 35,
    },
    "crypto_signals": {
        "kind": "realtime",
        "required": ["fetched_at"],
        "max_age_days": 1,
    },
    "polymarket_catalysts": {
        "kind": "event_feed",
        "required": ["title", "fetched_at"],
        "max_age_days": 1,
    },
    "sfc_news": {
        "kind": "event_feed",
        "required": ["news_ref_no", "issue_date", "title", "source", "fetched_at"],
        "max_age_days": 1,
    },
    "hkma_news": {
        "kind": "event_feed",
        "required": ["news_ref_no", "issue_date", "title", "source", "fetched_at"],
        "max_age_days": 1,
    },
    "hkexnews_announcements": {
        "kind": "event_feed",
        "required": ["ticker", "date_time", "title", "news_id", "fetched_at"],
        "max_age_days": 1,
    },
    "watchlist_price": {
        "kind": "measure",
        "required": ["ticker", "date", "latest_price_hkd", "fetched_at"],
        "max_age_days": 3,
    },
}


def _validate_hkma_register(df: pd.DataFrame) -> bool:
    """Assert Anchorpoint and HSBC are present."""
    if isinstance(df, dict) or df.empty:
        return False
    issuers = df["issuer"].str.lower().tolist()
    has_anchorpoint = any("anchorpoint" in str(i) for i in issuers)
    has_hsbc = any("hsbc" in str(i) or "hongkong and shanghai" in str(i) for i in issuers)
    return has_anchorpoint and has_hsbc


def _validate_sfc_register(df: pd.DataFrame) -> bool:
    """Assert OSL and HashKey are in licensed status."""
    if isinstance(df, dict) or df.empty:
        return False
    licensed = df[df["status"] == "licensed"]["platform_name"].str.lower().tolist()
    has_osl = any("osl" in str(p) for p in licensed)
    has_hashkey = any("hashkey" in str(p) for p in licensed)
    return has_osl and has_hashkey


def run_stage_1_pipeline() -> dict[str, Any]:
    """Execute Stage 1 ready-to-build ingestion for HK Stablecoin & Crypto."""
    results = {}

    try:
        logger.info("Ingesting HKMA licensed issuers...")
        hkma_df = fetch_licensed_issuers()
        if not _validate_hkma_register(hkma_df):
            logger.warning("HKMA register validation failed (missing Anchorpoint/HSBC)")
        results["hkma_licensed_issuers"] = hkma_df
    except Exception as exc:
        logger.exception("HKMA ingestion failed")
        results["hkma_licensed_issuers"] = {"error": str(exc)}

    try:
        logger.info("Ingesting SFC VATP register...")
        sfc_df = fetch_vatp_register()
        if not _validate_sfc_register(sfc_df):
            logger.warning("SFC VATP register validation failed (missing OSL/HashKey)")
        results["sfc_vatp_register"] = sfc_df
    except Exception as exc:
        logger.exception("SFC VATP ingestion failed")
        results["sfc_vatp_register"] = {"error": str(exc)}

    try:
        logger.info("Ingesting DefiLlama stablecoin supply...")
        results["stablecoin_supply"] = fetch_stablecoin_supply()
    except Exception as exc:
        logger.exception("DefiLlama ingestion failed")
        results["stablecoin_supply"] = {"error": str(exc)}

    try:
        logger.info("Ingesting HKEX ETF AUM...")
        results["hkex_etf_aum"] = fetch_all_etf_aum()
    except Exception as exc:
        logger.exception("HKEX ETF AUM ingestion failed")
        results["hkex_etf_aum"] = {"error": str(exc)}

    try:
        logger.info("Ingesting crypto market signals...")
        results["crypto_signals"] = fetch_all_crypto_signals()
    except Exception as exc:
        logger.exception("Crypto signals ingestion failed")
        results["crypto_signals"] = {"error": str(exc)}

    try:
        logger.info("Ingesting Polymarket catalysts...")
        results["polymarket_catalysts"] = fetch_all_polymarket_catalysts()
    except Exception as exc:
        logger.exception("Polymarket ingestion failed")
        results["polymarket_catalysts"] = {"error": str(exc)}

    try:
        logger.info("Ingesting SFC news...")
        results["sfc_news"] = fetch_sfc_news()
    except Exception as exc:
        logger.exception("SFC news ingestion failed")
        results["sfc_news"] = {"error": str(exc)}

    try:
        logger.info("Ingesting HKMA news...")
        results["hkma_news"] = fetch_hkma_news()
    except Exception as exc:
        logger.exception("HKMA news ingestion failed")
        results["hkma_news"] = {"error": str(exc)}

    try:
        logger.info("Ingesting HKEXnews company announcements...")
        results["hkexnews_announcements"] = fetch_hkexnews_announcements()
    except Exception as exc:
        logger.exception("HKEXnews announcements ingestion failed")
        results["hkexnews_announcements"] = {"error": str(exc)}

    try:
        logger.info("Ingesting watchlist spot quotes...")
        results["watchlist_price"] = fetch_watchlist_spot_quotes()
    except Exception as exc:
        logger.exception("Watchlist price ingestion failed")
        results["watchlist_price"] = {"error": str(exc)}

    return results
