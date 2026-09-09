"""Shared bilingual labels for global market-regime presentation."""

REGIME_SERIES_LABELS = {
    "brent": "Brent",
    "us10y": "US 10Y",
    "us2y": "US 2Y",
    "vix": "VIX",
    "hy_oas": "HY OAS",
}
REGIME_SERIES_LABELS_ZH = {
    "brent": "布伦特原油",
    "us10y": "美国10年期",
    "us2y": "美国2年期",
    "vix": "VIX",
    "hy_oas": "高收益债利差",
}
REGIME_DIST_LABELS_ZH = {
    "Above target": "高于目标区间",
    "Inside target": "位于目标区间",
    "Below target": "低于目标区间",
}
FOMC_DIST_LABELS_ZH = {
    "Hike": "加息",
    "Hold": "维持",
    "Cut": "降息",
}
COT_LABELS_ZH = {
    "Rising": "上升",
    "Falling": "下降",
    "Range": "整理",
    "Historical high": "历史高位",
    "Extreme": "极端水平",
    "Unknown": "未知",
    "tff_leveraged_money": "金融期货杠杆资金",
    "disagg_managed_money": "商品管理资金",
}
REGIME_EXPOSURE_LABELS = {
    "sp500": ("S&P 500", "标普500"),
    "ndx": ("Nasdaq 100", "纳斯达克100"),
    "csi300": ("CSI 300", "沪深300"),
    "csi500": ("CSI 500", "中证500"),
    "hsi": ("Hang Seng Index", "恒生指数"),
    "hstech": ("Hang Seng TECH", "恒生科技"),
    "nikkei225": ("Nikkei 225", "日经225"),
    "kospi": ("KOSPI", "韩国综合指数"),
}
REGIME_RETURN_HORIZONS = (
    ("return_1d_pct", "1 session", "1个交易日"),
    ("return_5d_pct", "5 sessions", "5个交易日"),
    ("return_20d_pct", "20 sessions", "20个交易日"),
)
REGIME_DOMAIN_LABELS = {
    "inflation_supply": ("Inflation / supply", "通胀／供给"),
    "rates_policy": ("Rates / policy", "利率／政策"),
    "financial_stress": ("Financial stress", "金融压力"),
}
REGIME_INDICATOR_LABELS = {
    "brent": ("Brent crude", "布伦特原油"),
    "us10y": ("US 10-year yield", "美国10年期国债收益率"),
    "hike_prob": ("Atlanta Fed SOFR probability", "Atlanta Fed SOFR概率"),
    "fomc_hike": ("Polymarket FOMC hike odds", "Polymarket FOMC加息赔率"),
    "credit_vix": ("HY OAS + VIX sync stress", "高收益债利差与VIX同步压力"),
}
REGIME_FRESHNESS_LABELS_ZH = {
    "Current session": "当前交易日",
    "Last session": "上一交易日",
    "Current release": "最新发布",
    "Recent": "近期",
    "Stale": "过期",
    "Unavailable": "不可用",
    "Invalid": "无效",
}
REGIME_FRESHNESS_OK = {
    "Current session",
    "Last session",
    "Current release",
    "Recent",
}
