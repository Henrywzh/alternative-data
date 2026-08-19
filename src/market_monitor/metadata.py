"""ETF / index metadata: the stable fund universe driving wrapper analysis.

Schema is intentionally venue-general so US/HK/CN ETFs can coexist without a
schema rewrite later:

    exposure_id / index_id / fund_id / ticker / fund_name / venue / currency
    wrapper_type / management_fee / inception_date / aum / is_qdii
    is_cross_border / underlying_timezone

``wrapper_type`` distinguishes domestic-listed (same market, IOPV clean) from
QDII / cross-border wrappers whose premium interpretation differs (NAV lag,
ES futures, FX, quota). The dashboard renders a caveat for cross-border rows.
"""

from __future__ import annotations

import pandas as pd


WRAPPER_COLUMNS = (
    "exposure_id",
    "index_id",
    "fund_id",
    "ticker",
    "fund_name",
    "venue",
    "currency",
    "wrapper_type",
    "management_fee",
    "inception_date",
    "aum",
    "is_qdii",
    "is_cross_border",
    "underlying_timezone",
)


# V1 universe. Fees are indicative annual % of NAV (verify before quoting
# exact numbers in the UI). inception is YYYY-MM-DD.
ETF_REGISTRY = (
    # --- CSI 300 ---
    {
        "exposure_id": "csi300",
        "index_id": "000300.SH",
        "fund_id": "510300",
        "ticker": "510300.SH",
        "fund_name": "华泰柏瑞沪深300ETF",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "domestic",
        "management_fee": 0.005,
        "inception_date": "2012-05-28",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": False,
        "underlying_timezone": "Asia/Shanghai",
    },
    {
        "exposure_id": "csi300",
        "index_id": "000300.SH",
        "fund_id": "510330",
        "ticker": "510330.SH",
        "fund_name": "华夏沪深300ETF",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "domestic",
        "management_fee": 0.005,
        "inception_date": "2012-12-25",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": False,
        "underlying_timezone": "Asia/Shanghai",
    },
    {
        "exposure_id": "csi300",
        "index_id": "000300.SH",
        "fund_id": "159919",
        "ticker": "159919.SZ",
        "fund_name": "嘉实沪深300ETF",
        "venue": "SZ",
        "currency": "CNY",
        "wrapper_type": "domestic",
        "management_fee": 0.005,
        "inception_date": "2012-05-07",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": False,
        "underlying_timezone": "Asia/Shanghai",
    },
    # --- CSI 500 ---
    {
        "exposure_id": "csi500",
        "index_id": "000905.SH",
        "fund_id": "510500",
        "ticker": "510500.SH",
        "fund_name": "南方中证500ETF",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "domestic",
        "management_fee": 0.005,
        "inception_date": "2013-02-06",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": False,
        "underlying_timezone": "Asia/Shanghai",
    },
    {
        "exposure_id": "csi500",
        "index_id": "000905.SH",
        "fund_id": "512500",
        "ticker": "512500.SH",
        "fund_name": "华夏中证500ETF",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "domestic",
        "management_fee": 0.0015,
        "inception_date": "2015-05-05",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": False,
        "underlying_timezone": "Asia/Shanghai",
    },
    {
        "exposure_id": "csi500",
        "index_id": "000905.SH",
        "fund_id": "159922",
        "ticker": "159922.SZ",
        "fund_name": "嘉实中证500ETF",
        "venue": "SZ",
        "currency": "CNY",
        "wrapper_type": "domestic",
        "management_fee": 0.005,
        "inception_date": "2013-02-06",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": False,
        "underlying_timezone": "Asia/Shanghai",
    },
    # --- CSI 1000 ---
    {
        "exposure_id": "csi1000",
        "index_id": "000852.SH",
        "fund_id": "512100",
        "ticker": "512100.SH",
        "fund_name": "南方中证1000ETF",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "domestic",
        "management_fee": 0.005,
        "inception_date": "2016-09-29",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": False,
        "underlying_timezone": "Asia/Shanghai",
    },
    # --- Dividend / Value ---
    {
        "exposure_id": "dividend",
        "index_id": "000015.SH",
        "fund_id": "510880",
        "ticker": "510880.SH",
        "fund_name": "华泰柏瑞上证红利ETF",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "domestic",
        "management_fee": 0.005,
        "inception_date": "2006-11-17",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": False,
        "underlying_timezone": "Asia/Shanghai",
    },
    # --- Growth / Innovation ---
    {
        "exposure_id": "growth",
        "index_id": "000688.SH",
        "fund_id": "588000",
        "ticker": "588000.SH",
        "fund_name": "华夏上证科创板50ETF",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "domestic",
        "management_fee": 0.005,
        "inception_date": "2020-11-16",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": False,
        "underlying_timezone": "Asia/Shanghai",
    },
    # --- Hang Seng Tech ---
    {
        "exposure_id": "hstech",
        "index_id": "HSTECH",
        "fund_id": "513180",
        "ticker": "513180.SH",
        "fund_name": "华夏恒生科技ETF(QDII)",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.005,
        "inception_date": "2021-05-12",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "Asia/Hong_Kong",
    },
    # --- S&P 500 (mandatory; mainland QDII wrappers tracked now) ---
    {
        "exposure_id": "sp500",
        "index_id": "SPX",
        "fund_id": "513500",
        "ticker": "513500.SH",
        "fund_name": "博时标普500ETF(QDII)",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.006,
        "inception_date": "2013-12-05",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "America/New_York",
    },
    {
        "exposure_id": "sp500",
        "index_id": "SPX",
        "fund_id": "513310",
        "ticker": "513310.SH",
        "fund_name": "景顺长城标普500ETF(QDII)",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.0075,
        "inception_date": "2024-11-05",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "America/New_York",
    },
)


def build_metadata_frame() -> pd.DataFrame:
    """Return the ETF registry as a normalized frame."""
    return pd.DataFrame(ETF_REGISTRY, columns=WRAPPER_COLUMNS)
