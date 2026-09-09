"""Sector registry, label dictionaries and overview layout config.

Split out of the former monolithic app.py; behaviour is unchanged.
"""

from __future__ import annotations

from typing import Any


SECTORS: dict[str, dict[str, str]] = {
    "labour": {
        "slug": "hk-labour-market",
        "name_en": "Hong Kong Labour Market & Talent Policy",
        "name_zh": "香港劳动力市场与人才政策",
        "short_en": "Labour Market",
        "short_zh": "劳动力市场",
    },
    "population": {
        "slug": "hk-population-migration",
        "name_en": "Hong Kong Population & Migration",
        "name_zh": "香港人口与迁移流动",
        "short_en": "Population & Migration",
        "short_zh": "人口与迁移",
    },
    "real_estate": {
        "slug": "hk-real-estate",
        "name_en": "Hong Kong Real Estate",
        "name_zh": "香港地产",
        "short_en": "Real Estate",
        "short_zh": "地产",
    },
    "transport": {
        "slug": "hk-transport",
        "name_en": "Hong Kong Transport & Aviation",
        "name_zh": "香港交通与航空",
        "short_en": "Transport & Aviation",
        "short_zh": "交通与航空",
    },
    "crypto": {
        "slug": "hk-stablecoin-crypto",
        "name_en": "Hong Kong Stablecoin & Crypto",
        "name_zh": "香港稳定币与加密资产",
        "short_en": "Stablecoin & Crypto",
        "short_zh": "稳定币与加密资产",
    },
    "aerospace": {
        "slug": "hk-commercial-aerospace",
        "name_en": "Hong Kong Commercial Aerospace",
        "name_zh": "香港商业航天",
        "short_en": "Commercial Aerospace",
        "short_zh": "商业航天",
    },
    "market": {
        "slug": "market-monitor",
        "name_en": "Index & ETF Allocation Monitor",
        "name_zh": "指数与ETF配置监控",
        "short_en": "ETF Monitor",
        "short_zh": "ETF监控",
    },
    "regime": {
        "slug": "global-market-regime",
        "name_en": "Global Market Regime",
        "name_zh": "全球市场状态",
        "short_en": "Market Regime",
        "short_zh": "市场状态",
    },
}

HISTORY_WINDOWS = {
    "10 years": 10,
    "5 years": 5,
    "3 years": 3,
    "1 year": 1,
    "Full history": None,
}

# Display units for the optional ETF activity panel.  The persisted activity
# contract keeps source-native values (actual shares and CNY); only the UI
# converts them into units a reader can scan quickly.
ETF_ACTIVITY_SHARES_PER_WAN = 10_000
ETF_ACTIVITY_CNY_PER_YI = 100_000_000

MONTH_LABELS_ZH = {
    "Jan": "1月",
    "Feb": "2月",
    "Mar": "3月",
    "Apr": "4月",
    "May": "5月",
    "Jun": "6月",
    "Jul": "7月",
    "Aug": "8月",
    "Sep": "9月",
    "Oct": "10月",
    "Nov": "11月",
    "Dec": "12月",
}

PALETTE = [
    "#4285F4",
    "#FF6B6B",
    "#00B5A4",
    "#FF7849",
    "#8B5CF6",
    "#EC4899",
    "#84CC16",
    "#F59E0B",
    "#06B6D4",
    "#9CA3AF",
]

SOURCE_DATASETS = {
    "immd": "immd_daily_traffic",
    "csd": "csd_population",
    "mpfa": "mpfa_claims",
    "ugc": "ugc_students",
    "td": "td_cross_border",
}

CHINA_AIRLINE_SERIES_LABELS = {
    "AC": "Air China",
    "CS": "China Southern",
    "CE": "China Eastern",
    "Spring": "Spring Airlines",
    "Hainan": "Hainan Airlines Holdings",
    "Juneyao": "Juneyao Airlines",
}

CHINA_AIRLINE_SERIES_LABELS_ZH = {
    "AC": "中国国际航空",
    "CS": "中国南方航空",
    "CE": "中国东方航空",
    "Spring": "春秋航空",
    "Hainan": "海航控股",
    "Juneyao": "吉祥航空",
}

CHINA_AIRLINE_REGION_SERIES_LABELS = {
    f"{short} · {region}": f"{label} · {region}"
    for short, label in CHINA_AIRLINE_SERIES_LABELS.items()
    for region in ("Domestic", "International", "Regional")
}
CHINA_AIRLINE_REGION_SERIES_LABELS_ZH = {
    f"{short} · {region}": f"{label} · {region_zh}"
    for short, label in CHINA_AIRLINE_SERIES_LABELS_ZH.items()
    for region, region_zh in (
        ("Domestic", "国内"),
        ("International", "国际"),
        ("Regional", "地区"),
    )
}

CHINA_AIRLINE_TABLE_LABELS_ZH = {
    "airline": {
        "Air China": "中国国航",
        "China Southern": "南方航空",
        "China Eastern": "东方航空",
        "Spring Airlines": "春秋航空",
        "Hainan Airlines Holdings": "海航控股",
        "Juneyao Airlines": "吉祥航空",
    },
    "reporting_scope": {
        "Group-consolidated operating data": "集团合并运营数据",
        "Company and subsidiaries": "公司及子公司",
        "Hainan group consolidated; includes eight operating carriers": "海航集团合并；包括八家运营航司",
        "Company and Jiuyuan Airlines consolidated": "公司及九元航空合并",
    },
    "event_type": {
        "fleet_added_aircraft": "引进飞机",
        "fleet_retired_aircraft": "退出／退租飞机",
        "fleet_total_aircraft": "机队总数",
        "new_route_event_count": "新航线事件数",
    },
}

MTR_SERIES_LABELS = {
    "Domestic": "Domestic heavy rail",
    "X-Boundary": "Cross-boundary",
    "HSR": "HSR",
    "Airport Exp": "Airport Express",
    "LR & Bus": "Light Rail / Bus",
}

MTR_SERIES_LABELS_ZH = {
    "Domestic": "本地重铁",
    "X-Boundary": "跨境",
    "HSR": "高铁",
    "Airport Exp": "机场快线",
    "LR & Bus": "轻铁／巴士",
}

CRYPTO_ATTENTION_AGENT_LABELS = {
    "user": "User",
    "spider": "Search-engine spider",
    "automated": "Automated",
    "all-agents": "All agents",
}

CRYPTO_ATTENTION_AGENT_LABELS_ZH = {
    "user": "用户",
    "spider": "搜索引擎爬虫",
    "automated": "自动化程序",
    "all-agents": "全部代理",
}

CRYPTO_PAGE_LABELS = {
    "Bitcoin": "Bitcoin",
    "Ethereum": "Ethereum",
    "Cryptocurrency": "Cryptocurrency",
    "Stablecoin": "Stablecoin",
    "Tether": "Tether",
    "USD Coin": "USD Coin",
    "Decentralized finance": "Decentralized finance",
    "Decentralized exchange": "Decentralized exchange",
}

CRYPTO_PAGE_LABELS_ZH = {
    "Bitcoin": "比特币",
    "Ethereum": "以太坊",
    "Cryptocurrency": "加密货币",
    "Stablecoin": "稳定币",
    "Tether": "Tether",
    "USD Coin": "USD Coin",
    "Decentralized finance": "去中心化金融",
    "Decentralized exchange": "去中心化交易所",
}

AEROSPACE_PROGRAM_LABELS = {
    "national_program": "National program",
    "state_owned_commercial": "State-owned commercial",
    "commercial_provider": "Commercial provider",
}

AEROSPACE_PROGRAM_LABELS_ZH = {
    "national_program": "国家队项目",
    "state_owned_commercial": "国企商业化",
    "commercial_provider": "商业发射服务商",
}

AEROSPACE_OBJECT_TYPE_LABELS = {
    "Payload": "Payload",
    "Rocket body": "Rocket body",
    "Debris": "Debris",
    "Unknown": "Unknown",
}

AEROSPACE_OBJECT_TYPE_LABELS_ZH = {
    "Payload": "有效载荷",
    "Rocket body": "火箭体",
    "Debris": "碎片",
    "Unknown": "未知",
}

AEROSPACE_ATTENTION_PAGE_LABELS = {
    "SpaceX": "SpaceX",
    "Starlink": "Starlink",
    "Rocket Lab": "Rocket Lab",
    "Falcon 9": "Falcon 9",
    "New Glenn": "New Glenn",
    "Long March": "Long March",
    "Chinese space program": "Chinese space program",
    "Satellite constellation": "Satellite constellation",
    "Commercial spaceflight": "Commercial spaceflight",
}

AEROSPACE_ATTENTION_PAGE_LABELS_ZH = {
    "SpaceX": "SpaceX",
    "Starlink": "Starlink",
    "Rocket Lab": "Rocket Lab",
    "Falcon 9": "猎鹰9号",
    "New Glenn": "新格伦",
    "Long March": "长征系列运载火箭",
    "Chinese space program": "中国航天计划",
    "Satellite constellation": "卫星星座",
    "Commercial spaceflight": "商业航天飞行",
}

PAIR_CARD_HEIGHT = 700

def get_pair_heights(h1: int | None, h2: int | None, type1: str = "line", type2: str = "line") -> tuple[int, int]:
    # Default heights if not specified
    def_h1 = h1 if h1 is not None else (400 if type1 == "bar" else 380)
    def_h2 = h2 if h2 is not None else (400 if type2 == "bar" else 380)
    max_h = max(def_h1, def_h2)
    # Card container height = max chart height + padding for header/title/etc.
    # We will use 180px padding which is perfect for headers and radio buttons.
    return max_h + 180, max_h


# Overview is intentionally capped. A new sector can contribute a compact
# pulse row by adding metadata here, but it does not automatically add another
# full chart section to the page.
OVERVIEW_PULSE_CONFIG: dict[str, dict[str, Any]] = {
    "market": {
        "metrics": (
            {
                "dataset": "kpi_market",
                "field": "csi300_rsi",
                "format": "number",
                "label_en": "CSI 300 RSI",
                "label_zh": "沪深300 RSI",
            },
            {
                "dataset": "kpi_market",
                "field": "sp500_rsi",
                "format": "number",
                "label_en": "S&P 500 RSI",
                "label_zh": "标普500 RSI",
            },
            {
                "dataset": "kpi_market",
                "field": "small_large_z",
                "format": "number",
                "label_en": "Small / Large z",
                "label_zh": "小盘/大盘 z",
            },
        ),
        "sparkline": {
            "chart_id": "small_large_regime_chart",
            "series": "Small / Large",
            "title_en": "Small vs Large relative strength",
            "title_zh": "小盘 vs 大盘相对强度",
            "note_en": "20D z-score of the rolling spread",
            "note_zh": "滚动价差的 20 日 z 得分",
            "format": "number",
        },
    },
    "regime": {
        "metrics": (
            {
                "dataset": "kpi_regime",
                "field": "overall_state",
                "format": "regime_state",
                "label_en": "Overall state",
                "label_zh": "总状态",
            },
            {
                "dataset": "kpi_regime",
                "field": "fomc_hike",
                "format": "percent",
                "label_en": "Next FOMC hike %",
                "label_zh": "下次FOMC加息赔率",
            },
            {
                "dataset": "kpi_regime",
                "field": "brent",
                "format": "usd",
                "label_en": "Brent",
                "label_zh": "布伦特原油",
            },
        ),
        "sparkline": {
            "chart_id": "brent_history_chart",
            "series": "brent",
            "title_en": "Brent crude",
            "title_zh": "布伦特原油",
            "note_en": "Daily EIA Europe Brent via FRED",
            "note_zh": "EIA 欧洲布伦特日频，经 FRED",
            "format": "number",
        },
    },
    "labour": {
        "metrics": (
            {
                "dataset": "kpi_labour_force",
                "field": "unemployment_rate",
                "format": "fraction",
                "label_en": "Unemployment rate",
                "label_zh": "失业率",
            },
            {
                "dataset": "kpi_labour_demand",
                "field": "vacancies",
                "format": "number",
                "label_en": "Vacancies",
                "label_zh": "职位空缺",
            },
            {
                "dataset": "kpi_income",
                "field": "median_monthly_earnings",
                "format": "number",
                "label_en": "Median earnings (HK$)",
                "label_zh": "就业收入中位数（港元）",
            },
        ),
        "sparkline": {
            "chart_id": "labour_rates_chart",
            "series": "Unemployment rate",
            "title_en": "Unemployment rate history",
            "title_zh": "失业率历史",
            "note_en": "Monthly rolling-three-month rate",
            "note_zh": "每月三个月移动平均",
            "format": "fraction",
        },
    },
    "population": {
        "metrics": (
            {
                "dataset": "csd_population",
                "field": "mid_year_population_thousands",
                "format": "number",
                "label_en": "Population ('000)",
                "label_zh": "人口（千人）",
            },
            {
                "dataset": "immd_net_flow_history",
                "field": "HK Resident Net Flow",
                "format": "number",
                "series": True,
                "label_en": "HK resident net flow",
                "label_zh": "香港居民净流量",
            },
            {
                "dataset": "immd_net_flow_history",
                "field": "Mainland Visitor Net Retention",
                "format": "number",
                "series": True,
                "label_en": "Mainland visitor net retention",
                "label_zh": "内地访客净留存",
            },
        ),
        "sparkline": {
            "chart_id": "csd_population_chart",
            "series": "Population",
            "title_en": "Population history",
            "title_zh": "人口历史",
            "note_en": "Half-yearly mid/end-year estimate",
            "note_zh": "半年年中／年终估算",
            "format": "number",
        },
    },
    "transport": {
        "metrics": (
            {
                "dataset": "kpi_mtr",
                "field": "latest",
                "format": "number",
                "label_en": "MTR patronage ('000s)",
                "label_zh": "港铁客运量（千人次）",
            },
            {
                "dataset": "kpi_cathay",
                "field": "latest",
                "format": "number",
                "label_en": "Cathay passengers",
                "label_zh": "国泰航空客运量",
            },
            {
                "dataset": "kpi_cathay",
                "field": "load_factor_pct",
                "format": "percent",
                "label_en": "Cathay load factor",
                "label_zh": "国泰航空客座率",
            },
        ),
        "sparkline": {
            "chart_id": "mtr_service_breakdown_chart",
            "series": "Domestic",
            "title_en": "MTR domestic patronage",
            "title_zh": "港铁本地客运量",
            "note_en": "Monthly service breakdown",
            "note_zh": "按月服务类型分拆",
            "format": "number",
        },
    },
    "crypto": {
        "metrics": (
            {
                "dataset": "stablecoin_history",
                "field": "circulating_usd_bn",
                "format": "number",
                "label_en": "Stablecoin supply ($B)",
                "label_zh": "稳定币供应量（十亿美元）",
            },
            {
                "dataset": "dex_volume_history",
                "field": "dex_volume_usd_bn",
                "format": "number",
                "label_en": "DEX volume ($B/day)",
                "label_zh": "DEX 交易量（十亿美元／日）",
            },
            {
                "dataset": "fear_greed_history",
                "field": "score",
                "format": "number",
                "label_en": "Fear & Greed monthly avg",
                "label_zh": "恐惧与贪婪（月均）",
            },
        ),
        "sparkline": {
            "chart_id": "stablecoin_history_chart",
            "series": None,
            "title_en": "Global stablecoin supply",
            "title_zh": "全球稳定币供应量",
            "note_en": "Monthly average of daily circulating supply",
            "note_zh": "每日流通供应量月均值",
            "format": "number",
        },
    },
    "real_estate": {
        "metrics": (
            {
                "dataset": "kpi_ccl",
                "field": "latest",
                "format": "number",
                "label_en": "Centaline CCL",
                "label_zh": "中原城市领先指数（CCL）",
            },
            {
                "dataset": "kpi_mhpi",
                "field": "latest",
                "format": "number",
                "label_en": "Midland MHPI",
                "label_zh": "美联物业价格指数（MHPI）",
            },
            {
                "field": "Overall",
                "format": "number",
                "series": True,
                "chart_id": "rvd_office_trend",
                "label_en": "RVD office rental (Overall)",
                "label_zh": "RVD 写字楼租金（整体）",
            },
        ),
        "sparkline": {
            "chart_id": "ccl_trend",
            "series": None,
            "title_en": "Centaline CCL history",
            "title_zh": "中原城市领先指数历史",
            "note_en": "Weekly publisher-level index",
            "note_zh": "发布者周度指数",
            "format": "number",
        },
    },
    "aerospace": {
        "metrics": (
            {
                "field": "national_program",
                "format": "number",
                "series": True,
                "chart_id": "china_launch_monthly_chart",
                "label_en": "Latest national-program launches",
                "label_zh": "国家队项目最新发射次数",
            },
            {
                "field": "commercial_provider",
                "format": "number",
                "series": True,
                "chart_id": "china_launch_monthly_chart",
                "label_en": "Latest commercial-provider launches",
                "label_zh": "商业发射服务商最新发射次数",
            },
            {
                "field": "Qianfan",
                "format": "number",
                "series": True,
                "chart_id": "satellite_history_chart",
                "label_en": "Qianfan tracked inventory",
                "label_zh": "千帆跟踪目标数",
            },
        ),
        "sparkline": {
            "chart_id": "china_launch_monthly_chart",
            "series": "national_program",
            "title_en": "National launch cadence",
            "title_zh": "国家队发射节奏",
            "note_en": "Monthly verified launch events",
            "note_zh": "每月已核验发射任务",
            "format": "number",
        },
    },
}

# Keep the featured-trend budget explicit, but leave it empty until higher-
# frequency inputs and derived signals have been ingested and validated.
OVERVIEW_FEATURED_CHARTS: tuple[dict[str, Any], ...] = ()

REGIME_STATE_LABELS_ZH = {
    "Normal": "正常",
    "Watch": "观察",
    "Confirmed": "确认",
    "Escalating": "升级",
    "Improving": "缓和",
    "Unavailable": "不可用",
}
