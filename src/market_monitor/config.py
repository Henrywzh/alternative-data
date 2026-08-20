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
# ``role`` separates the two kinds of series this pipeline carries.
# "exposure" is something you can actually buy through a tracked ETF wrapper
# and appears on the ETF monitor. "benchmark" exists only as one leg of a
# relative-strength pair -- there is no wrapper cohort for it and it gets no
# technical card -- but it is fetched, normalised and coverage-checked exactly
# like an exposure, so a benchmark cannot silently stop updating.
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
        "price_source": "sina_hk",
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
        "price_source": "sina_hk",
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
        "yf_symbol": "^NDX",
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
        # index_id is the index's own name; yf_symbol is what the provider
        # calls it. Deriving the provider symbol from index_id turned "SPX"
        # into a delisted-ticker warning and an empty frame.
        "yf_symbol": "^GSPC",
    },
    {
        # The only HK dividend index that is live on a route we use. Sina's HK
        # index list carries this one; S&P 港股通低波红利 and 恒生高股息低波 --
        # the indices the three wrappers below actually track -- are on
        # neither Sina's HK list nor the CSI endpoint. The wrapper ranking
        # does not depend on it: premium is measured against each fund's own
        # NAV, and fee/size/age are index-independent.
        "exposure_id": "hk_dividend",
        "price_source": "sina_hk",
        "label": "HK Dividend",
        "label_zh": "港股红利",
        "region": "HK",
        "size": "Broad",
        "style": "Value",
        "risk_character": "Defensive",
        "index_id": "CSHKDIV",
    },
    # --- Benchmarks: relative-strength legs, not investable exposures ---
    # Verified live on 2026-08-20. The obvious alternatives are traps: Sina
    # answers 200 for 中证800成长 (000967) and 中证800价值 (000969) but stopped
    # updating them in 2016 and 2019, so a style pair built on them would have
    # frozen without ever erroring.
    {
        # HK mid cap. 标普香港大型股 correlates 0.98 with the Hang Seng over two
        # years, so the large leg reuses hsi rather than adding a near-duplicate
        # series; this is the half that carries the signal (0.86 correlation,
        # 20pp of relative performance over two years).
        "exposure_id": "hk_midcap",
        "role": "benchmark",
        "price_source": "sina_hk",
        "label": "HK Mid Cap",
        "label_zh": "香港中盘",
        "region": "HK",
        "size": "Mid",
        "style": "Broad",
        "risk_character": "Cyclical-ish",
        "index_id": "CSHKMCS",
    },
    {
        "exposure_id": "hk_hshares",
        "role": "benchmark",
        "price_source": "sina_hk",
        "label": "Hang Seng China Enterprises",
        "label_zh": "恒生中国企业",
        "region": "HK",
        "size": "Large",
        "style": "Broad",
        "risk_character": "Mainland core",
        "index_id": "HSCEI",
    },
    {
        "exposure_id": "chinext",
        "role": "benchmark",
        "price_source": "sina",
        "label": "ChiNext",
        "label_zh": "创业板指",
        "region": "China",
        "size": "Broad",
        "style": "Growth",
        "risk_character": "Offensive",
        "index_id": "399006.SZ",
    },
    {
        "exposure_id": "cn_infotech",
        "role": "benchmark",
        "price_source": "sina",
        "label": "CN Info Tech",
        "label_zh": "全指信息",
        "region": "China",
        "size": "Broad",
        "style": "Sector",
        "risk_character": "Offensive",
        "index_id": "000993.SH",
    },
    {
        "exposure_id": "cn_staples",
        "role": "benchmark",
        "price_source": "sina",
        "label": "CN Consumer Staples",
        "label_zh": "中证主要消费",
        "region": "China",
        "size": "Broad",
        "style": "Sector",
        "risk_character": "Defensive",
        "index_id": "000932.SH",
    },
    {
        "exposure_id": "us_broad",
        "role": "benchmark",
        "price_source": "yfinance",
        "label": "S&P 500 (SPY)",
        "label_zh": "标普500 (SPY)",
        "region": "US",
        "size": "Broad",
        "style": "Broad",
        "risk_character": "Core",
        "index_id": "SPY",
    },
    {
        "exposure_id": "us_equal_weight",
        "role": "benchmark",
        "price_source": "yfinance",
        "label": "S&P 500 equal weight",
        "label_zh": "标普500等权",
        "region": "US",
        "size": "Broad",
        "style": "Broad",
        "risk_character": "Breadth",
        "index_id": "RSP",
    },
    {
        "exposure_id": "us_small",
        "role": "benchmark",
        "price_source": "yfinance",
        "label": "Russell 2000",
        "label_zh": "罗素2000",
        "region": "US",
        "size": "Small",
        "style": "Broad",
        "risk_character": "Core",
        "index_id": "IWM",
    },
    {
        "exposure_id": "us_growth",
        "role": "benchmark",
        "price_source": "yfinance",
        "label": "Russell 1000 Growth",
        "label_zh": "罗素1000成长",
        "region": "US",
        "size": "Broad",
        "style": "Growth",
        "risk_character": "Growth",
        "index_id": "IWF",
    },
    {
        "exposure_id": "us_value",
        "role": "benchmark",
        "price_source": "yfinance",
        "label": "Russell 1000 Value",
        "label_zh": "罗素1000价值",
        "region": "US",
        "size": "Broad",
        "style": "Value",
        "risk_character": "Value",
        "index_id": "IWD",
    },
    {
        "exposure_id": "us_tech",
        "role": "benchmark",
        "price_source": "yfinance",
        "label": "US Technology",
        "label_zh": "美国科技",
        "region": "US",
        "size": "Broad",
        "style": "Broad",
        "risk_character": "Offensive",
        "index_id": "XLK",
    },
    {
        "exposure_id": "us_discretionary",
        "role": "benchmark",
        "price_source": "yfinance",
        "label": "US Consumer Discretionary",
        "label_zh": "美国可选消费",
        "region": "US",
        "size": "Broad",
        "style": "Broad",
        "risk_character": "Offensive",
        "index_id": "XLY",
    },
    {
        "exposure_id": "us_communication",
        "role": "benchmark",
        "price_source": "yfinance",
        "label": "US Communication Services",
        "label_zh": "美国通信服务",
        "region": "US",
        "size": "Broad",
        "style": "Broad",
        "risk_character": "Offensive",
        "index_id": "XLC",
    },
    {
        "exposure_id": "us_staples",
        "role": "benchmark",
        "price_source": "yfinance",
        "label": "US Consumer Staples",
        "label_zh": "美国日常消费",
        "region": "US",
        "size": "Broad",
        "style": "Broad",
        "risk_character": "Defensive",
        "index_id": "XLP",
    },
    {
        "exposure_id": "us_utilities",
        "role": "benchmark",
        "price_source": "yfinance",
        "label": "US Utilities",
        "label_zh": "美国公用事业",
        "region": "US",
        "size": "Broad",
        "style": "Broad",
        "risk_character": "Defensive",
        "index_id": "XLU",
    },
    {
        "exposure_id": "us_healthcare",
        "role": "benchmark",
        "price_source": "yfinance",
        "label": "US Health Care",
        "label_zh": "美国医疗保健",
        "region": "US",
        "size": "Broad",
        "style": "Broad",
        "risk_character": "Defensive",
        "index_id": "XLV",
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


def exposure_role(spec: dict) -> str:
    """"exposure" (investable, has ETF wrappers) or "benchmark" (pair leg only)."""
    return str(spec.get("role", "exposure"))


def investable_exposures() -> tuple[dict, ...]:
    """The exposures the ETF monitor is about, in declaration order."""
    return tuple(spec for spec in EXPOSURES if exposure_role(spec) == "exposure")
