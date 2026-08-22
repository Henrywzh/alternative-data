"""Universe definition for US Sector and Sub-industry ETFs.

Curated from GICS taxonomy to include:
1. 11 Core GICS Level-1 Sector ETFs (Hot layer)
2. High-liquidity, pure-play Industry / Sub-industry ETFs (Warm drill-down layer)
Zero duplicate fallbacks.
"""

from __future__ import annotations

from typing import Any

# 11 Core GICS Sector ETFs
US_SECTOR_ETFS: list[dict[str, Any]] = [
    {
        "ticker": "XLK",
        "name_en": "Technology Select Sector SPDR",
        "name_zh": "科技精选行业ETF",
        "sector": "Information Technology",
        "sector_zh": "信息科技",
        "expense_ratio": 0.0008,
        "description_zh": "覆盖苹果、微软、英伟达等全球科技龙头",
    },
    {
        "ticker": "XLF",
        "name_en": "Financial Select Sector SPDR",
        "name_zh": "金融精选行业ETF",
        "sector": "Financials",
        "sector_zh": "金融",
        "expense_ratio": 0.0008,
        "description_zh": "覆盖摩根大通、伯克希尔哈撒韦、Visa等",
    },
    {
        "ticker": "XLV",
        "name_en": "Health Care Select Sector SPDR",
        "name_zh": "医疗保健精选行业ETF",
        "sector": "Health Care",
        "sector_zh": "医疗健康",
        "expense_ratio": 0.0008,
        "description_zh": "覆盖礼来、联合健康、强生等制药与医疗设备巨头",
    },
    {
        "ticker": "XLY",
        "name_en": "Consumer Discretionary Select Sector SPDR",
        "name_zh": "可选消费精选行业ETF",
        "sector": "Consumer Discretionary",
        "sector_zh": "可选消费",
        "expense_ratio": 0.0008,
        "description_zh": "覆盖亚马逊、特斯拉、家得宝等零售与汽车龙头",
    },
    {
        "ticker": "XLC",
        "name_en": "Communication Services Select Sector SPDR",
        "name_zh": "通信服务精选行业ETF",
        "sector": "Communication Services",
        "sector_zh": "通信服务",
        "expense_ratio": 0.0008,
        "description_zh": "覆盖Meta、谷歌、奈飞等互联网与媒体平台",
    },
    {
        "ticker": "XLI",
        "name_en": "Industrial Select Sector SPDR",
        "name_zh": "工业精选行业ETF",
        "sector": "Industrials",
        "sector_zh": "工业制造",
        "expense_ratio": 0.0008,
        "description_zh": "覆盖卡特彼勒、GE、波音、霍尼韦尔等装备制造",
    },
    {
        "ticker": "XLE",
        "name_en": "Energy Select Sector SPDR",
        "name_zh": "能源精选行业ETF",
        "sector": "Energy",
        "sector_zh": "传统能源",
        "expense_ratio": 0.0008,
        "description_zh": "覆盖埃克森美孚、雪佛龙等上游油气巨头",
    },
    {
        "ticker": "XLP",
        "name_en": "Consumer Staples Select Sector SPDR",
        "name_zh": "主要消费精选行业ETF",
        "sector": "Consumer Staples",
        "sector_zh": "日常消费",
        "expense_ratio": 0.0008,
        "description_zh": "覆盖宝洁、好市多、可口可乐、沃尔玛等必需消费",
    },
    {
        "ticker": "XLU",
        "name_en": "Utilities Select Sector SPDR",
        "name_zh": "公用事业精选行业ETF",
        "sector": "Utilities",
        "sector_zh": "公用事业",
        "expense_ratio": 0.0008,
        "description_zh": "覆盖NextEra、南方电力等高股息电网与能源设施",
    },
    {
        "ticker": "XLB",
        "name_en": "Materials Select Sector SPDR",
        "name_zh": "材料精选行业ETF",
        "sector": "Materials",
        "sector_zh": "基础材料",
        "expense_ratio": 0.0008,
        "description_zh": "覆盖林德气体、自由港铜金、陶氏等原材料巨头",
    },
    {
        "ticker": "XLRE",
        "name_en": "Real Estate Select Sector SPDR",
        "name_zh": "房地产精选行业ETF",
        "sector": "Real Estate",
        "sector_zh": "房地产",
        "expense_ratio": 0.0008,
        "description_zh": "覆盖普洛斯、Equinix数据中心、美国电塔等REITs",
    },
]

# High-liquidity Pure-Play Sub-Industry & Thematic ETFs (Drill-down layer)
US_SUB_INDUSTRY_ETFS: list[dict[str, Any]] = [
    # Tech sub-industries
    {
        "ticker": "SMH",
        "name_en": "VanEck Semiconductor ETF",
        "name_zh": "全球半导体芯片ETF",
        "parent_sector": "Information Technology",
        "sub_industry": "Semiconductors",
        "sub_industry_zh": "半导体与芯片",
        "expense_ratio": 0.0035,
    },
    {
        "ticker": "SOXX",
        "name_en": "iShares Semiconductor ETF",
        "name_zh": "费城半导体指数ETF",
        "parent_sector": "Information Technology",
        "sub_industry": "Semiconductors",
        "sub_industry_zh": "半导体与芯片",
        "expense_ratio": 0.0033,
    },
    {
        "ticker": "IGV",
        "name_en": "iShares Expanded Tech-Software Sector ETF",
        "name_zh": "北美软件与SaaS ETF",
        "parent_sector": "Information Technology",
        "sub_industry": "Application & Systems Software",
        "sub_industry_zh": "企业软件与SaaS",
        "expense_ratio": 0.0038,
    },
    {
        "ticker": "CIBR",
        "name_en": "First Trust NASDAQ Cybersecurity ETF",
        "name_zh": "网络安全ETF",
        "parent_sector": "Information Technology",
        "sub_industry": "Cybersecurity",
        "sub_industry_zh": "网络安全",
        "expense_ratio": 0.0058,
    },
    # Health care sub-industries
    {
        "ticker": "XBI",
        "name_en": "SPDR S&P Biotech ETF",
        "name_zh": "标普生物科技ETF",
        "parent_sector": "Health Care",
        "sub_industry": "Biotechnology",
        "sub_industry_zh": "生物医药与基因",
        "expense_ratio": 0.0035,
    },
    {
        "ticker": "IHI",
        "name_en": "iShares U.S. Medical Devices ETF",
        "name_zh": "医疗器械设备ETF",
        "parent_sector": "Health Care",
        "sub_industry": "Medical Devices",
        "sub_industry_zh": "医疗器械与耗材",
        "expense_ratio": 0.0037,
    },
    # Financials sub-industries
    {
        "ticker": "KRE",
        "name_en": "SPDR S&P Regional Banking ETF",
        "name_zh": "标普美国区域银行ETF",
        "parent_sector": "Financials",
        "sub_industry": "Regional Banks",
        "sub_industry_zh": "区域银行",
        "expense_ratio": 0.0035,
    },
    {
        "ticker": "KBE",
        "name_en": "SPDR S&P Bank ETF",
        "name_zh": "标普全美商业银行ETF",
        "parent_sector": "Financials",
        "sub_industry": "Diversified Banks",
        "sub_industry_zh": "大型综合商业银行",
        "expense_ratio": 0.0035,
    },
    # Industrials sub-industries
    {
        "ticker": "ITA",
        "name_en": "iShares U.S. Aerospace & Defense ETF",
        "name_zh": "美国航空航天与军工ETF",
        "parent_sector": "Industrials",
        "sub_industry": "Aerospace & Defense",
        "sub_industry_zh": "军工与航天装备",
        "expense_ratio": 0.0037,
    },
    {
        "ticker": "JETS",
        "name_en": "U.S. Global Jets ETF",
        "name_zh": "全球航空客运ETF",
        "parent_sector": "Industrials",
        "sub_industry": "Passenger Airlines",
        "sub_industry_zh": "商业客运航空",
        "expense_ratio": 0.0060,
    },
    # Energy sub-industries
    {
        "ticker": "XOP",
        "name_en": "SPDR S&P Oil & Gas Exploration & Production ETF",
        "name_zh": "油气开采与勘探ETF",
        "parent_sector": "Energy",
        "sub_industry": "Oil & Gas Exploration",
        "sub_industry_zh": "油气勘探与开采",
        "expense_ratio": 0.0035,
    },
    {
        "ticker": "OIH",
        "name_en": "VanEck Oil Services ETF",
        "name_zh": "油田技术服务ETF",
        "parent_sector": "Energy",
        "sub_industry": "Oilfield Services",
        "sub_industry_zh": "油服与钻井工程",
        "expense_ratio": 0.0035,
    },
    # Materials sub-industries
    {
        "ticker": "GDX",
        "name_en": "VanEck Gold Miners ETF",
        "name_zh": "黄金矿业开采ETF",
        "parent_sector": "Materials",
        "sub_industry": "Gold Mining",
        "sub_industry_zh": "黄金矿产与冶炼",
        "expense_ratio": 0.0051,
    },
    {
        "ticker": "COPX",
        "name_en": "Global X Copper Miners ETF",
        "name_zh": "全球铜矿产业链ETF",
        "parent_sector": "Materials",
        "sub_industry": "Copper Mining",
        "sub_industry_zh": "铜矿采选与精炼",
        "expense_ratio": 0.0065,
    },
    # Consumer Discretionary sub-industries
    {
        "ticker": "XHB",
        "name_en": "SPDR S&P Homebuilders ETF",
        "name_zh": "标普美国房屋建筑商ETF",
        "parent_sector": "Consumer Discretionary",
        "sub_industry": "Homebuilding",
        "sub_industry_zh": "住宅建筑与家居",
        "expense_ratio": 0.0035,
    },
    # Utilities & Clean Energy
    {
        "ticker": "ICLN",
        "name_en": "iShares Global Clean Energy ETF",
        "name_zh": "全球清洁能源ETF",
        "parent_sector": "Utilities",
        "sub_industry": "Renewable Electricity",
        "sub_industry_zh": "新能源与可再生电力",
        "expense_ratio": 0.0039,
    },
]

ALL_US_ETFS: list[dict[str, Any]] = US_SECTOR_ETFS + US_SUB_INDUSTRY_ETFS
US_ETF_TICKERS: list[str] = [item["ticker"] for item in ALL_US_ETFS]
