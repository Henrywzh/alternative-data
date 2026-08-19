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
#  * China size: CSI 300 / 500 / 1000 / 2000
#  * China style: Dividend / Growth-Innovation
#  * HK: Hang Seng Tech
#  * Global: S&P 500 (mandatory)
#
# ``risk_character`` is a *structural* label (core / cyclical-ish / ...).
# The dynamic regime (what is actually leading now) is computed from market
# data in relative_strength, never hard-coded here.
EXPOSURES = (
    {
        "exposure_id": "csi300",
        "label": "CSI 300",
        "region": "China",
        "size": "Large",
        "style": "Broad",
        "risk_character": "Core",
        "index_id": "000300.SH",
    },
    {
        "exposure_id": "csi500",
        "label": "CSI 500",
        "region": "China",
        "size": "Mid",
        "style": "Broad",
        "risk_character": "Cyclical-ish",
        "index_id": "000905.SH",
    },
    {
        "exposure_id": "csi1000",
        "label": "CSI 1000",
        "region": "China",
        "size": "Small",
        "style": "Broad",
        "risk_character": "Higher beta",
        "index_id": "000852.SH",
    },
    {
        "exposure_id": "csi2000",
        "label": "CSI 2000",
        "region": "China",
        "size": "Micro",
        "style": "Broad",
        "risk_character": "Highest beta",
        "index_id": "932000.CSI",
    },
    {
        "exposure_id": "dividend",
        "label": "Dividend",
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
        "label": "Growth / Innovation",
        "region": "China",
        "size": "Mixed",
        "style": "Growth",
        "risk_character": "Risk-on-ish",
        "index_id": "000688.SH",
    },
    {
        "exposure_id": "hstech",
        "label": "Hang Seng Tech",
        "region": "HK / China",
        "size": "Large / Mid",
        "style": "Tech / Growth",
        "risk_character": "High beta",
        "index_id": "HSTECH",
    },
    {
        "exposure_id": "sp500",
        "label": "S&P 500",
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
