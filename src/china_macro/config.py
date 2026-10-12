"""Explicit series definitions; never infer an expected universe from output."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data/normalized/china_macro"
ARTIFACT_DIR = ROOT / "apps/asia-markets-dashboard/.generated"
NBS_BASE = "https://data.stats.gov.cn/dg/website/publicrelease/web/external"
EM_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# id, Chinese, English, unit, frequency, period scope, owning source
_SERIES = [
    ("pmi", "制造业 PMI", "Manufacturing PMI", "index", "M", "month", "nbs"),
    ("nonmanufacturing_pmi", "非制造业商务活动指数", "Non-manufacturing activity", "index", "M", "month", "nbs"),
    ("services_pmi", "服务业商务活动指数", "Services activity", "index", "M", "month", "nbs"),
    ("construction_pmi", "建筑业商务活动指数", "Construction activity", "index", "M", "month", "nbs"),
    ("pmi_production", "PMI 生产", "PMI production", "index", "M", "month", "nbs"),
    ("pmi_new_orders", "PMI 新订单", "PMI new orders", "index", "M", "month", "nbs"),
    ("pmi_inventory", "PMI 产成品库存", "PMI finished-goods inventory", "index", "M", "month", "nbs"),
    ("pmi_export_orders", "PMI 新出口订单", "PMI new export orders", "index", "M", "month", "nbs"),
    ("industrial_yoy", "规上工业增加值同比", "Industrial value-added YoY", "%", "M", "month", "nbs"),
    ("retail_yoy", "社会消费品零售总额同比", "Retail sales YoY", "%", "M", "month", "eastmoney"),
    ("retail", "社会消费品零售总额", "Retail sales", "CNY bn", "M", "month", "eastmoney"),
    ("gdp_yoy", "GDP 累计同比", "GDP year-to-date YoY", "%", "Q", "ytd", "eastmoney"),
    ("gdp", "GDP 累计现价金额", "GDP year-to-date nominal value", "CNY bn", "Q", "ytd", "eastmoney"),
    ("cpi_yoy", "CPI 同比", "CPI YoY", "%", "M", "month", "eastmoney"),
    ("cpi_mom", "CPI 环比", "CPI MoM", "%", "M", "month", "eastmoney"),
    ("core_cpi_yoy", "核心 CPI 同比", "Core CPI YoY", "%", "M", "month", "nbs"),
    ("ppi_yoy", "PPI 同比", "PPI YoY", "%", "M", "month", "eastmoney"),
    ("industrial_profit_yoy", "规上工业利润累计同比", "Industrial profits YTD YoY", "%", "M", "ytd", "nbs"),
    ("industrial_profit", "规上工业利润累计金额", "Industrial profits YTD", "CNY bn", "M", "ytd", "nbs"),
    ("m2_yoy", "M2 同比", "M2 YoY", "%", "M", "month", "eastmoney"),
    ("m1_yoy", "M1 同比（2025年新口径）", "M1 YoY (2025 definition)", "%", "M", "month", "eastmoney"),
    ("m1_legacy_yoy", "M1 同比（旧口径）", "M1 YoY (legacy definition)", "%", "M", "month", "eastmoney"),
    ("new_loans", "人民币新增贷款", "New RMB loans", "CNY bn", "M", "month", "eastmoney"),
    ("tsf_flow", "社会融资规模增量", "Aggregate financing flow", "CNY bn", "M", "month", "pbc"),
    ("tsf_government", "社融：政府债券净融资", "AFRE government bond financing", "CNY bn", "M", "month", "pbc"),
    ("tsf_rmb_loans", "社融：实体经济人民币贷款", "AFRE RMB loans to real economy", "CNY bn", "M", "month", "pbc"),
    ("tsf_stock_yoy", "社会融资规模存量同比", "Aggregate financing stock YoY", "%", "M", "month", "pbc"),
    ("tsf_stock", "社会融资规模存量", "Aggregate financing stock", "CNY bn", "M", "month", "pbc"),
    ("household_loan_balance", "住户人民币贷款余额", "Household RMB loan balance", "CNY bn", "M", "month", "pbc"),
    ("corporate_loan_balance", "企事业单位人民币贷款余额", "Corporate RMB loan balance", "CNY bn", "M", "month", "pbc"),
    ("property_investment_yoy", "房地产开发投资累计同比", "Property investment YTD YoY", "%", "M", "ytd", "nbs"),
    ("property_sales_area_yoy", "商品房销售面积累计同比", "Property sales area YTD YoY", "%", "M", "ytd", "nbs"),
    ("property_sales_value_yoy", "商品房销售额累计同比", "Property sales value YTD YoY", "%", "M", "ytd", "nbs"),
    ("property_starts_yoy", "房屋新开工面积累计同比", "Property new starts YTD YoY", "%", "M", "ytd", "nbs"),
    ("property_completions_yoy", "房屋竣工面积累计同比", "Property completions YTD YoY", "%", "M", "ytd", "nbs"),
    ("fai_yoy", "固定资产投资累计同比（不含农户）", "Fixed investment YTD YoY", "%", "M", "ytd", "nbs"),
    ("manufacturing_investment_yoy", "制造业投资累计同比", "Manufacturing investment YTD YoY", "%", "M", "ytd", "nbs"),
    ("infrastructure_investment_yoy", "基础设施投资累计同比（不含电力）", "Infrastructure investment YTD YoY (ex utilities)", "%", "M", "ytd", "nbs"),
    ("infrastructure_investment_incl_utilities_yoy", "基础设施投资累计同比（2026年含公用事业口径）", "Infrastructure investment YTD YoY (2026 incl utilities)", "%", "M", "ytd", "nbs"),
    ("exports_yoy", "出口同比（美元口径）", "Exports YoY (USD)", "%", "M", "month", "eastmoney"),
    ("imports_yoy", "进口同比（美元口径）", "Imports YoY (USD)", "%", "M", "month", "eastmoney"),
    ("exports", "出口金额", "Exports", "USD bn", "M", "month", "eastmoney"),
    ("imports", "进口金额", "Imports", "USD bn", "M", "month", "eastmoney"),
    ("shibor_on", "Shibor 隔夜", "Shibor overnight", "%", "D", "day", "rates"),
    ("shibor_1w", "Shibor 1周", "Shibor 1 week", "%", "D", "day", "rates"),
    ("dr007", "DR007 存款类机构7天回购", "DR007 depository repo rate", "%", "D", "day", "rates"),
    ("lpr_1y", "LPR 1年", "1-year LPR", "%", "M", "day", "eastmoney"),
    ("lpr_5y", "LPR 5年以上", "5-year LPR", "%", "M", "day", "eastmoney"),
    ("usdcny_fix", "美元兑人民币中间价", "USD/CNY central parity", "CNY/USD", "D", "day", "rates"),
    ("cgb_1y", "中国国债收益率 1年", "China government yield 1Y", "%", "D", "day", "chinabond"),
    ("cgb_10y", "中国国债收益率 10年", "China government yield 10Y", "%", "D", "day", "chinabond"),
]
SERIES = {
    row[0]: dict(zip(("id", "zh", "en", "unit", "frequency", "scope", "owner"), row))
    for row in _SERIES
}
DERIVED = [
    ("orders_inventory", "PMI 新订单 − 产成品库存", "PMI orders minus finished-goods inventory", "pp", "M", "month", "derived"),
    ("production_consumption", "工业同比 − 零售同比", "Industrial minus retail YoY", "pp", "M", "month", "derived"),
    ("m1_m2", "M1 − M2 同比（可比新口径）", "M1 minus M2 YoY (comparable definition)", "pp", "M", "month", "derived"),
    ("tsf_ex_government", "社融增量扣除政府债券", "AFRE flow excluding government bonds", "CNY bn", "M", "month", "derived"),
    ("trade_balance", "贸易差额（美元）", "Trade balance (USD)", "USD bn", "M", "month", "derived"),
    ("exports_yoy_3m", "出口同比：3个月均值", "Exports YoY: 3-month average", "%", "M", "month", "derived"),
    ("imports_yoy_3m", "进口同比：3个月均值", "Imports YoY: 3-month average", "%", "M", "month", "derived"),
    ("curve_10y_1y", "国债 10年 − 1年收益率", "Government yield 10Y minus 1Y", "bp", "D", "day", "derived"),
    ("household_loan_change", "住户贷款余额月度变化（非官方新增贷款）", "Monthly household loan balance change (not official new lending)", "CNY bn", "M", "month", "derived"),
    ("corporate_loan_change", "企事业贷款余额月度变化（非官方新增贷款）", "Monthly corporate loan balance change (not official new lending)", "CNY bn", "M", "month", "derived"),
]
for row in DERIVED:
    SERIES[row[0]] = dict(zip(("id", "zh", "en", "unit", "frequency", "scope", "owner"), row))

GROUPS = [
    ("activity", "景气与需求", "Activity & demand", [
        ("PMI", ["pmi", "nonmanufacturing_pmi", "services_pmi", "construction_pmi"]),
        ("PMI details", ["pmi_production", "pmi_new_orders", "pmi_inventory", "pmi_export_orders"]),
        ("Orders / inventory", ["orders_inventory"]),
        ("Production / consumption", ["industrial_yoy", "retail_yoy"]),
        ("Production / consumption spread", ["production_consumption"]),
        ("GDP (YTD)", ["gdp_yoy"]),
    ]),
    ("inflation", "通胀与盈利", "Inflation & profits", [
        ("Consumer / producer prices", ["cpi_yoy", "core_cpi_yoy", "ppi_yoy"]),
        ("CPI MoM", ["cpi_mom"]),
        ("Industrial profits (YTD)", ["industrial_profit_yoy"]),
    ]),
    ("credit", "信用与流动性", "Credit & liquidity", [
        ("Money growth (new M1 definition)", ["m1_yoy", "m2_yoy"]),
        ("M1 / M2 spread", ["m1_m2"]),
        ("Legacy M1 (not comparable)", ["m1_legacy_yoy"]),
        ("Financing flows", ["tsf_flow", "tsf_government", "tsf_ex_government", "new_loans"]),
        ("Financing stock growth", ["tsf_stock_yoy"]),
        ("Borrower balances", ["household_loan_balance", "corporate_loan_balance"]),
        ("Borrower balance changes", ["household_loan_change", "corporate_loan_change"]),
    ]),
    ("property", "地产与投资", "Property & investment", [
        ("Property (YTD)", ["property_investment_yoy", "property_sales_area_yoy", "property_sales_value_yoy", "property_starts_yoy", "property_completions_yoy"]),
        ("Investment (YTD)", ["fai_yoy", "manufacturing_investment_yoy", "infrastructure_investment_yoy", "infrastructure_investment_incl_utilities_yoy"]),
    ]),
    ("trade", "外需", "External demand", [
        ("Trade growth", ["exports_yoy", "imports_yoy"]),
        ("Trade growth: 3-month averages", ["exports_yoy_3m", "imports_yoy_3m"]),
        ("Trade balance", ["trade_balance"]),
        ("Trade value", ["exports", "imports"]),
    ]),
    ("rates", "利率与汇率", "Rates & FX", [
        ("Money-market rates", ["dr007", "shibor_on", "shibor_1w"]),
        ("Loan prime rates", ["lpr_1y", "lpr_5y"]),
        ("Government yields", ["cgb_1y", "cgb_10y"]),
        ("Yield curve", ["curve_10y_1y"]),
        ("RMB fixing", ["usdcny_fix"]),
    ]),
]
