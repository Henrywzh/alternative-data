from __future__ import annotations

# ---------------------------------------------------------------------------
# FRED series registry
# ---------------------------------------------------------------------------

FRED_SERIES: dict[str, str] = {
    "PCU334413334413": "Producer Price Index: Semiconductor Manufacturing",
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
