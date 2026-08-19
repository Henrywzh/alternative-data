"""Paths and constants for the market_monitor domain."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

RAW_DIR = REPO_ROOT / "data" / "raw" / "market_monitor"
NORMALIZED_DIR = REPO_ROOT / "data" / "normalized" / "market_monitor"
DERIVED_DIR = REPO_ROOT / "data" / "derived" / "market_monitor"


# Identifiers used across the domain. Exposure groups indexes; index owns
# wrappers; venue keeps the schema open to CN / HK / US listing venues.
EXPOSURE_ID = "exposure_id"
INDEX_ID = "index_id"
FUND_ID = "fund_id"


# V1 tracking universe (source of truth, not derived). Exposures are:
#  * China size: CSI 300 / 500 / 1000 (CSI2000 deferred until stable source)
#  * China style: Dividend / Growth-Innovation
#  * HK: Hang Seng Tech
#  * Global: S&P 500 (mandatory)
#
# ``risk_character`` is a *structural* label (core / cyclical-ish / ...).
# The dynamic regime (what is actually leading now) is computed from market
# data in relative_strength, never hard-coded here.
#
# ``price_source`` names the provider that serves this index, and is the single
# place that says so: the pipeline routes its fetch on it and the dashboard
# attributes source health with it. Both used to encode "everything except
# sp500 comes from Sina", so adding Nasdaq 100 on yfinance credited Sina with
# 501 rows of an index it does not serve -- the same mistake cd09fd40 fixed for
# S&P 500, re-made by the next US index. A per-exposure declaration cannot
# drift that way: a new index has to state where it comes from.
EXPOSURES = (
    {
        "exposure_id": "csi300",
        "price_source": "sina",
        "label": "CSI 300",
        "label_zh": "沪深300",
        "region": "China",
        "size": "Large",
        "style": "Broad",
        "risk_character": "Core",
        "index_id": "000300.SH",
    },
    {
        "exposure_id": "csi500",
        "price_source": "sina",
        "label": "CSI 500",
        "label_zh": "中证500",
        "region": "China",
        "size": "Mid",
        "style": "Broad",
        "risk_character": "Cyclical-ish",
        "index_id": "000905.SH",
    },
    {
        "exposure_id": "csi1000",
        "price_source": "sina",
        "label": "CSI 1000",
        "label_zh": "中证1000",
        "region": "China",
        "size": "Small",
        "style": "Broad",
        "risk_character": "Higher beta",
        "index_id": "000852.SH",
    },
    {
        "exposure_id": "dividend",
        "price_source": "sina",
        "label": "SSE Dividend",
        "label_zh": "上证红利",
        "region": "China",
        "size": "Mixed",
        "style": "Dividend / Value",
        "risk_character": "Defensive-ish",
        # SSE Dividend (上证红利) — Sina carries sh000015 cleanly, whereas
        # CSI Dividend has no viable free intraday/historical feed in V1.
        "index_id": "000015.SH",
    },
    {
        "exposure_id": "growth",
        "price_source": "sina",
        "label": "STAR 50",
        "label_zh": "科创50",
        "region": "China",
        "size": "Mixed",
        "style": "Growth",
        "risk_character": "Risk-on-ish",
        "index_id": "000688.SH",
    },
    {
        "exposure_id": "hstech",
        "price_source": "sina",
        "label": "Hang Seng Tech",
        "label_zh": "恒生科技",
        "region": "HK / China",
        "size": "Large / Mid",
        "style": "Tech / Growth",
        "risk_character": "High beta",
        "index_id": "HSTECH",
    },
    {
        "exposure_id": "hsi",
        "price_source": "sina",
        "label": "Hang Seng Index",
        "label_zh": "恒生指数",
        "region": "HK",
        "size": "Large",
        "style": "Broad",
        "risk_character": "Core",
        "index_id": "HSI",
    },
    {
        "exposure_id": "ndx",
        "price_source": "yfinance",
        "label": "Nasdaq 100",
        "label_zh": "纳斯达克100",
        "region": "US",
        "size": "Large",
        "style": "Tech / Growth",
        "risk_character": "Global core",
        "index_id": "NDX",
    },
    {
        "exposure_id": "sp500",
        "price_source": "yfinance",
        "label": "S&P 500",
        "label_zh": "标普500",
        "region": "US",
        "size": "Large",
        "style": "Broad",
        "risk_character": "Global core",
        "index_id": "SPX",
    },
)


def exposure_by_id(exposure_id: str) -> dict:
    for spec in EXPOSURES:
        if spec["exposure_id"] == exposure_id:
            return spec
    raise KeyError(f"unknown exposure_id: {exposure_id}")


def exposures_by_price_source(source: str) -> tuple[str, ...]:
    """Exposure ids served by one provider, for routing and source health."""
    return tuple(spec["exposure_id"] for spec in EXPOSURES if spec["price_source"] == source)
