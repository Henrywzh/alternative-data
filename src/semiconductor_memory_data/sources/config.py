from __future__ import annotations

# ---------------------------------------------------------------------------
# FRED series registry
# ---------------------------------------------------------------------------

AI_DEMAND_PPI_WEIGHTS: dict[str, float] = {
    "PCU33443344": 0.40,
    "PCU33423342": 0.25,
    "PCU335313335313": 0.20,
    "PCU334111334111": 0.10,
    "PCU3341123341121": 0.05,
}

FRED_SERIES: dict[str, str] = {
    "PCU33443344": "PCU33443344",
    "PCU33423342": "PCU33423342",
    "PCU335313335313": "PCU335313335313",
    "PCU334111334111": "PCU334111334111",
    "PCU3341123341121": "PCU3341123341121",
}

# ---------------------------------------------------------------------------
# ADATA keyword patterns for mention detection (applied to full report text)
# ---------------------------------------------------------------------------

KEYWORD_PATTERNS: dict[str, str] = {
    "mentions_hbm":                  r"\bHBM\b",
    "mentions_csp":                  r"\bCSP\b|\bcloud service provider\b",
    "mentions_server":               r"\bserver\b",
    "mentions_ddr4":                 r"\bDDR4\b",
    "mentions_reallocate_capacity":  r"\bcapacity.{0,30}realloc|\bconvert.{0,20}capacity",
    "mentions_shortage":             r"\bshortage\b|\btight supply\b|\bundersupply\b",
    "mentions_oversupply":           r"\boversupply\b|\bexcess supply\b|\bglut\b",
}

# Section heading keywords used to scope regime-label derivation
NAND_SECTION_KEYWORDS: tuple[str, ...] = ("NAND", "Flash", "NAND Flash")
DRAM_SECTION_KEYWORDS: tuple[str, ...] = ("DRAM", "Memory")

# ---------------------------------------------------------------------------
# ADATA EDM URL constants
# ---------------------------------------------------------------------------

ADATA_LIST_BASE_URL = "https://industrial.adata.com/en/edm"
ADATA_REPORT_BASE_URL = "https://industrial.adata.com/en/edm/MarketWatch_"
ADATA_IMAGE_CDN_BASE = "https://industrial-ad.adata.com"
ADATA_MAX_PAGES = 12

USER_AGENT = "alternative-data-semiconductor-memory/0.1"
