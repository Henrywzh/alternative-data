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
    "custody_fee",
    "premium_regime",
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
        "management_fee": 0.0015,
        "custody_fee": 0.0005,
        "premium_regime": "domestic",
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
        "management_fee": 0.0015,
        "custody_fee": 0.0005,
        "premium_regime": "domestic",
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
        "management_fee": 0.0015,
        "custody_fee": 0.0005,
        "premium_regime": "domestic",
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
        "management_fee": 0.0015,
        "custody_fee": 0.0005,
        "premium_regime": "domestic",
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
        "custody_fee": 0.0005,
        "premium_regime": "domestic",
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
        "management_fee": 0.0015,
        "custody_fee": 0.0005,
        "premium_regime": "domestic",
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
        "management_fee": 0.0015,
        "custody_fee": 0.0005,
        "premium_regime": "domestic",
        "inception_date": "2016-09-29",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": False,
        "underlying_timezone": "Asia/Shanghai",
    },
    {
        "exposure_id": "csi1000",
        "index_id": "000852.SH",
        "fund_id": "159845",
        "ticker": "159845.SZ",
        "fund_name": "华夏中证1000ETF",
        "venue": "SZ",
        "currency": "CNY",
        "wrapper_type": "domestic",
        "management_fee": 0.0015,
        "custody_fee": 0.0005,
        "premium_regime": "domestic",
        "inception_date": "2021-11-05",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": False,
        "underlying_timezone": "Asia/Shanghai",
    },
    {
        "exposure_id": "csi1000",
        "index_id": "000852.SH",
        "fund_id": "560010",
        "ticker": "560010.SH",
        "fund_name": "广发中证1000ETF",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "domestic",
        "management_fee": 0.0015,
        "custody_fee": 0.0005,
        "premium_regime": "domestic",
        "inception_date": "2021-08-05",
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
        "custody_fee": 0.001,
        "premium_regime": "domestic",
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
        "management_fee": 0.0015,
        "custody_fee": 0.0005,
        "premium_regime": "domestic",
        "inception_date": "2020-11-16",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": False,
        "underlying_timezone": "Asia/Shanghai",
    },
    {
        "exposure_id": "growth",
        "index_id": "000688.SH",
        "fund_id": "588080",
        "ticker": "588080.SH",
        "fund_name": "易方达上证科创板50ETF",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "domestic",
        "management_fee": 0.0015,
        "custody_fee": 0.0005,
        "premium_regime": "domestic",
        "inception_date": "2020-09-28",
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
        "custody_fee": 0.0015,
        "premium_regime": "connect",
        "inception_date": "2021-05-12",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "Asia/Hong_Kong",
    },
    {
        "exposure_id": "hstech",
        "index_id": "HSTECH",
        "fund_id": "513130",
        "ticker": "513130.SH",
        "fund_name": "华泰柏瑞恒生科技ETF(QDII)",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.002,
        "custody_fee": 0.0005,
        "premium_regime": "connect",
        "inception_date": "2021-05-24",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "Asia/Hong_Kong",
    },
    {
        "exposure_id": "hstech",
        "index_id": "HSTECH",
        "fund_id": "513010",
        "ticker": "513010.SH",
        "fund_name": "易方达恒生科技ETF(QDII)",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.002,
        "custody_fee": 0.0005,
        "premium_regime": "connect",
        "inception_date": "2021-02-09",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "Asia/Hong_Kong",
    },
    # --- Hang Seng Index ---
    {
        "exposure_id": "hsi",
        "index_id": "HSI",
        "fund_id": "159920",
        "ticker": "159920.SZ",
        "fund_name": "华夏恒生ETF(QDII)",
        "venue": "SZ",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.006,
        "custody_fee": 0.0015,
        "premium_regime": "connect",
        "inception_date": "2012-08-09",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "Asia/Hong_Kong",
    },
    {
        "exposure_id": "hsi",
        "index_id": "HSI",
        "fund_id": "513660",
        "ticker": "513660.SH",
        "fund_name": "华夏恒生通ETF",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.005,
        "custody_fee": 0.001,
        "premium_regime": "connect",
        "inception_date": "2018-06-15",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "Asia/Hong_Kong",
    },
    # --- Nasdaq 100 ---
    {
        "exposure_id": "ndx",
        "index_id": "NDX",
        "fund_id": "159941",
        "ticker": "159941.SZ",
        "fund_name": "广发纳斯达克100ETF(QDII)",
        "venue": "SZ",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.008,
        "custody_fee": 0.002,
        "premium_regime": "quota",
        "inception_date": "2015-01-30",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "America/New_York",
    },
    {
        "exposure_id": "ndx",
        "index_id": "NDX",
        "fund_id": "513100",
        "ticker": "513100.SH",
        "fund_name": "国泰纳斯达克100ETF(QDII)",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.006,
        "custody_fee": 0.002,
        "premium_regime": "quota",
        "inception_date": "2013-05-15",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "America/New_York",
    },
    {
        "exposure_id": "ndx",
        "index_id": "NDX",
        "fund_id": "513300",
        "ticker": "513300.SH",
        "fund_name": "华夏纳斯达克ETF(QDII)",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.006,
        "custody_fee": 0.002,
        "premium_regime": "quota",
        "inception_date": "2020-03-13",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "America/New_York",
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
        "custody_fee": 0.002,
        "premium_regime": "quota",
        "inception_date": "2013-12-05",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "America/New_York",
    },
    {
        # Replaces 513310, which was filed here as "景顺长城标普500ETF(QDII)"
        # but is actually 中韩半导体ETF华泰柏瑞 -- a China/Korea semiconductor
        # fund. It returned +271% over two years against the S&P 500's +38%,
        # correlating 0.13 with the index it was supposed to track and 0.72
        # with domestic growth. See reconcile_registry_names below.
        # management_fee is unknown rather than guessed: the two akshare
        # endpoints that carry it are both broken upstream, and a guessed fee
        # is what put a semiconductor fund in this cohort. The hold score
        # drops the component and renormalises the rest.
        "exposure_id": "sp500",
        "index_id": "SPX",
        "fund_id": "159655",
        "ticker": "159655.SZ",
        "fund_name": "标普500ETF华夏",
        "venue": "SZ",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.006,
        "custody_fee": 0.0015,
        "premium_regime": "quota",
        "inception_date": "2022-10-25",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "America/New_York",
    },
    {
        "exposure_id": "sp500",
        "index_id": "SPX",
        "fund_id": "513650",
        "ticker": "513650.SH",
        "fund_name": "南方标普500ETF(QDII)",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.006,
        "custody_fee": 0.0015,
        "premium_regime": "quota",
        "inception_date": "2020-06-05",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "America/New_York",
    },
    {
        # 标普港股通低波红利. Largest and most traded of the HK dividend
        # wrappers, and the only one currently quoted at a premium -- which is
        # the entry-cost signal doing its job: you pay up for the liquid one.
        "exposure_id": "hk_dividend",
        "index_id": "CSHKDIV",
        "fund_id": "513630",
        "ticker": "513630.SH",
        "fund_name": "港股低波红利ETF摩根",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "connect",
        "management_fee": 0.005,
        "custody_fee": 0.001,
        "premium_regime": "connect",
        "inception_date": "2023-12-08",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": True,
        "underlying_timezone": "Asia/Hong_Kong",
    },
    {
        # 恒生高股息低波. Charges 0.20% all-in against 0.58-0.60% for every
        # other HK dividend wrapper -- 40bp a year, the largest and most
        # certain difference in the cohort.
        "exposure_id": "hk_dividend",
        "index_id": "CSHKDIV",
        "fund_id": "159545",
        "ticker": "159545.SZ",
        "fund_name": "恒生红利低波ETF易方达",
        "venue": "SZ",
        "currency": "CNY",
        "wrapper_type": "connect",
        "management_fee": 0.0015,
        "custody_fee": 0.0005,
        "premium_regime": "connect",
        "inception_date": "2024-04-15",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": True,
        "underlying_timezone": "Asia/Hong_Kong",
    },
    {
        # 恒生港股通高股息率. The only one with a pre-2024 record, so the only
        # one that has traded through a different regime.
        "exposure_id": "hk_dividend",
        "index_id": "CSHKDIV",
        "fund_id": "513690",
        "ticker": "513690.SH",
        "fund_name": "港股红利ETF博时",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "connect",
        "management_fee": 0.005,
        "custody_fee": 0.001,
        "premium_regime": "connect",
        "inception_date": "2021-05-20",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": True,
        "underlying_timezone": "Asia/Hong_Kong",
    },
    {
        "exposure_id": "hk_internet",
        "index_id": "931637",
        "fund_id": "159792",
        "ticker": "159792.SZ",
        "fund_name": "港股通互联网ETF富国",
        "venue": "SZ",
        "currency": "CNY",
        "wrapper_type": "connect",
        "management_fee": 0.0015,
        "custody_fee": 0.0005,
        "premium_regime": "connect",
        "inception_date": "2021-09-28",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": True,
        "underlying_timezone": "Asia/Hong_Kong",
    },
    {
        "exposure_id": "hk_internet",
        "index_id": "931637",
        "fund_id": "513040",
        "ticker": "513040.SH",
        "fund_name": "港股通互联网ETF易方达",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "connect",
        "management_fee": 0.0015,
        "custody_fee": 0.0005,
        "premium_regime": "connect",
        "inception_date": "2023-06-12",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": True,
        "underlying_timezone": "Asia/Hong_Kong",
    },
    {
        "exposure_id": "hk_internet",
        "index_id": "931637",
        "fund_id": "520650",
        "ticker": "520650.SH",
        "fund_name": "港股通互联网ETF南方",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "connect",
        "management_fee": 0.0015,
        "custody_fee": 0.0005,
        "premium_regime": "connect",
        "inception_date": "2025-11-10",
        "aum": None,
        "is_qdii": False,
        "is_cross_border": True,
        "underlying_timezone": "Asia/Hong_Kong",
    },
    # --- Nikkei 225 (QDII) ---
    {
        "exposure_id": "nikkei225",
        "index_id": "N225",
        "fund_id": "513520",
        "ticker": "513520.SH",
        "fund_name": "华夏野村日经225ETF(QDII)",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.0020,
        "custody_fee": 0.0005,
        "premium_regime": "qdii",
        "inception_date": "2019-06-25",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "Asia/Tokyo",
    },
    {
        "exposure_id": "nikkei225",
        "index_id": "N225",
        "fund_id": "513000",
        "ticker": "513000.SH",
        "fund_name": "易方达日兴日经225ETF(QDII)",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.0020,
        "custody_fee": 0.0005,
        "premium_regime": "qdii",
        "inception_date": "2019-06-25",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "Asia/Tokyo",
    },
    # --- CN-KR Semiconductor (QDII) ---
    {
        "exposure_id": "kr_semis",
        "index_id": "931643",
        "fund_id": "513310",
        "ticker": "513310.SH",
        "fund_name": "华泰柏瑞中韩半导体ETF(QDII)",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.0080,
        "custody_fee": 0.0015,
        "premium_regime": "qdii",
        "inception_date": "2022-01-20",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        # The index straddles two sessions: KRX closes 14:30 CST, half an hour
        # before Shanghai, so the wrapper's own close is the later of the two
        # and Asia/Shanghai is the binding one. The Korean leg is 30 minutes
        # stale at the close, which is small next to the HK mismatch.
        "underlying_timezone": "Asia/Shanghai",
    },
    # --- France CAC 40 (QDII) ---
    {
        "exposure_id": "cac40",
        "index_id": "CAC40",
        "fund_id": "513080",
        "ticker": "513080.SH",
        "fund_name": "华安法国CAC40ETF(QDII)",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "qdii",
        # Issuer-published, not the hand-typed 0.80/0.20 this used to carry.
        "management_fee": 0.0050,
        "custody_fee": 0.0015,
        "premium_regime": "qdii",
        "inception_date": "2020-05-29",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "Europe/Paris",
    },
    # --- Germany DAX (QDII) ---
    {
        "exposure_id": "dax",
        "index_id": "DAX",
        "fund_id": "513030",
        "ticker": "513030.SH",
        "fund_name": "华安德国(DAX)ETF(QDII)",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.0080,
        "custody_fee": 0.0020,
        "premium_regime": "qdii",
        "inception_date": "2014-09-05",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "Europe/Berlin",
    },
    # --- UK FTSE 100 (QDII) ---
    # No wrapper. 513970 was registered here as 建信富时100ETF(QDII); the
    # exchange calls it 恒生消费ETF景顺, a Hang Seng consumer fund with three
    # siblings and nothing to do with the FTSE 100. There is no A-share FTSE
    # 100 tracker to put in its place: across 1594 listed ETFs the only 富时
    # funds are 富时A50, which is Chinese large caps. The ftse100 exposure
    # keeps its Yahoo index series; 20 of 37 exposures already carry no
    # wrapper, so this is the normal shape for one, not a gap to fill.
    # --- Saudi Arabia (QDII) ---
    {
        "exposure_id": "saudi",
        "index_id": "KSA",
        "fund_id": "159329",
        "ticker": "159329.SZ",
        "fund_name": "南方沙特ETF(QDII)",
        "venue": "SZ",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.0050,
        "custody_fee": 0.0010,
        "premium_regime": "qdii",
        "inception_date": "2024-06-24",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "Asia/Riyadh",
    },
    {
        "exposure_id": "saudi",
        "index_id": "KSA",
        "fund_id": "520830",
        "ticker": "520830.SH",
        "fund_name": "华泰柏瑞沙特ETF(QDII)",
        "venue": "SH",
        "currency": "CNY",
        "wrapper_type": "qdii",
        "management_fee": 0.0050,
        "custody_fee": 0.0010,
        "premium_regime": "qdii",
        "inception_date": "2024-06-24",
        "aum": None,
        "is_qdii": True,
        "is_cross_border": True,
        "underlying_timezone": "Asia/Riyadh",
    },
)


def build_metadata_frame() -> pd.DataFrame:
    """Return the ETF registry as a normalized frame."""
    return pd.DataFrame(ETF_REGISTRY, columns=WRAPPER_COLUMNS)


# What the exchange's own name for a fund must contain for it to belong to an
# exposure. The registry above is hand-maintained, so nothing stopped a
# semiconductor ETF sitting in the S&P 500 cohort for as long as nobody
# eyeballed a chart. Reconciling against the venue's naming is the check that
# does not depend on anyone eyeballing anything.
EXPOSURE_NAME_TOKENS: dict[str, tuple[str, ...]] = {
    "csi300": ("沪深300",),
    "csi500": ("中证500",),
    "csi1000": ("中证1000",),
    "dividend": ("红利",),
    "growth": ("科创50", "科创板50"),
    "hstech": ("恒生科技",),
    "hsi": ("恒生",),
    "hk_dividend": ("红利", "高股息", "股息"),
    "hk_internet": ("互联网",),
    "ndx": ("纳指", "纳斯达克"),
    "nikkei225": ("日经", "Nikkei"),
    # Not a bare 半导体: this check exists because 513310 was once filed as an
    # S&P 500 tracker, and a token that matches every semiconductor fund is
    # exactly the token that would have let that through.
    "kr_semis": ("中韩半导体",),
    "dax": ("德国", "DAX"),
    "cac40": ("法国", "CAC40", "CAC"),
    "dow": ("道琼斯", "道指", "Dow"),
    "russell2000": ("罗素2000", "罗素"),
    "kospi": ("韩国", "KOSPI"),
    "twii": ("台湾", "加权指数", "TAIEX"),
    # ftse100 carries no wrapper today (see config.py), so this token has
    # nothing to reconcile against. It is kept so that a future FTSE 100
    # ETF cannot be filed here without passing the same name check.
    "ftse100": ("英国", "富时100", "FTSE"),
    "saudi": ("沙特", "Saudi", "中东"),
    "sp500": ("标普500",),
}


# The fund houses the registry actually names, plus the majors it is likely to
# grow into. Checked in addition to the index token, because the index token
# cannot see a swap: 159329 and 520830 both read 沙特, so the registry carried
# those two issuers crossed for as long as the pair existed and nothing said
# so. An issuer this list does not know is skipped rather than reported -- an
# unrecognised name is an absence, not a contradiction, the same rule the
# exposure check already applies to a fund the spot feed does not mention.
FUND_HOUSE_TOKENS: tuple[str, ...] = (
    "华泰柏瑞", "易方达", "华夏", "南方", "嘉实", "广发", "博时", "国泰",
    "富国", "华安", "建信", "汇添富", "招商", "工银瑞信",
    "中银", "银华", "鹏华", "天弘", "永赢", "景顺长城", "摩根", "汇安",
    "平安", "大成", "浦银安盛", "兴业", "中欧", "交银施罗德", "华宝", "国投瑞银",
)


def _registry_fund_house(name: str) -> str | None:
    """The fund house a registry name states, or None when it names none.

    Longest match wins so 华泰柏瑞 is never read as a bare 华泰, and 景顺长城
    is never read as 景顺.
    """

    matches = [token for token in FUND_HOUSE_TOKENS if token in name]
    if not matches:
        return None
    return max(matches, key=len)


def reconcile_registry_names(
    metadata: pd.DataFrame,
    spot: pd.DataFrame,
) -> list[dict[str, str]]:
    """Registry rows whose exposure the venue's own fund name contradicts.

    Empty means every wrapper's exchange name carries a token consistent with
    the exposure it is filed under. A row the spot feed does not mention is
    not a contradiction -- it is an absence -- and is left to coverage
    reporting.
    """
    if metadata.empty or spot.empty or "fund_name" not in spot.columns:
        return []
    exchange_names = {
        str(row.ticker).split(".")[0].zfill(6): str(row.fund_name)
        for row in spot.itertuples()
        if getattr(row, "ticker", None) is not None
    }
    problems: list[dict[str, str]] = []
    for row in metadata.itertuples():
        tokens = EXPOSURE_NAME_TOKENS.get(str(row.exposure_id))
        if not tokens:
            continue
        exchange_name = exchange_names.get(str(row.fund_id).zfill(6))
        if exchange_name is None:
            continue
        matched = any(token in exchange_name for token in tokens)
        # 恒生科技 contains 恒生, so the broad Hang Seng cohort has to exclude
        # the tech index explicitly or a tech wrapper would pass as broad.
        if matched and str(row.exposure_id) == "hsi" and "恒生科技" in exchange_name:
            matched = False
        if not matched:
            problems.append(
                {
                    "exposure_id": str(row.exposure_id),
                    "fund_id": str(row.fund_id),
                    "registry_name": str(row.fund_name),
                    "exchange_name": exchange_name,
                    "reason": "exposure",
                }
            )
            continue
        issuer = _registry_fund_house(str(row.fund_name))
        if issuer is not None and issuer not in exchange_name:
            problems.append(
                {
                    "exposure_id": str(row.exposure_id),
                    "fund_id": str(row.fund_id),
                    "registry_name": str(row.fund_name),
                    "exchange_name": exchange_name,
                    "reason": "issuer",
                }
            )
    return problems
