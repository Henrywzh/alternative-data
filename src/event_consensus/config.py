"""Configuration for the executor-neutral event/consensus engine."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw" / "event_consensus"
NORMALIZED_DIR = REPO_ROOT / "data" / "normalized" / "event_consensus"
CACHE_DIR = REPO_ROOT / "data" / "cache" / "event_consensus"
LATEST_ARTIFACT_PATH = CACHE_DIR / "events_consensus_latest.json"
EVENT_LEDGER_PATH = NORMALIZED_DIR / "event_snapshots.parquet"
QUOTE_LEDGER_PATH = NORMALIZED_DIR / "market_quote_snapshots.parquet"
COMPONENT_LEDGER_PATH = NORMALIZED_DIR / "official_component_snapshots.parquet"

SCHEMA_VERSION = "1.0"
DEFAULT_COUNTRIES = ("US", "CN", "KR")
DEFAULT_LOOKAHEAD_DAYS = 14
DEFAULT_LOOKBACK_DAYS = 1

# Finnhub's free quote endpoint covers the US instruments in this list. Korea
# and Hong Kong are deliberately absent: the configured free account returns
# HTTP 403 for those markets and must not look like valid coverage.
MARKET_INSTRUMENTS: tuple[dict[str, str], ...] = (
    {"symbol": "SPY", "label": "S&P 500", "asset_class": "US equity"},
    {"symbol": "QQQ", "label": "Nasdaq 100", "asset_class": "US equity"},
    {"symbol": "SOXX", "label": "Semiconductors", "asset_class": "US equity"},
    {"symbol": "IGV", "label": "Software", "asset_class": "US equity"},
    {"symbol": "TLT", "label": "Long Treasuries", "asset_class": "rates"},
    {"symbol": "HYG", "label": "High yield credit", "asset_class": "credit"},
    {"symbol": "GLD", "label": "Gold", "asset_class": "commodity"},
    {"symbol": "USO", "label": "Oil", "asset_class": "commodity"},
    {"symbol": "UUP", "label": "US dollar", "asset_class": "FX"},
)

BLS_COMPONENT_SERIES: tuple[dict[str, str], ...] = (
    {"series_id": "CUSR0000SA0", "event_family": "cpi", "component_id": "headline", "label_en": "Headline CPI", "label_zh": "整体 CPI", "value_kind": "index"},
    {"series_id": "CUSR0000SA0L1E", "event_family": "cpi", "component_id": "core", "label_en": "Core CPI", "label_zh": "核心 CPI", "value_kind": "index"},
    {"series_id": "CUSR0000SAF1", "event_family": "cpi", "component_id": "food", "label_en": "Food CPI", "label_zh": "食品 CPI", "value_kind": "index"},
    {"series_id": "CUSR0000SA0E", "event_family": "cpi", "component_id": "energy", "label_en": "Energy CPI", "label_zh": "能源 CPI", "value_kind": "index"},
    {"series_id": "CUSR0000SAH1", "event_family": "cpi", "component_id": "shelter", "label_en": "Shelter CPI", "label_zh": "住房 CPI", "value_kind": "index"},
    {"series_id": "CES0000000001", "event_family": "payrolls", "component_id": "headline", "label_en": "Total nonfarm payrolls", "label_zh": "非农就业总人数", "value_kind": "payroll_level"},
    {"series_id": "CES0500000003", "event_family": "payrolls", "component_id": "wages", "label_en": "Average hourly earnings", "label_zh": "平均时薪", "value_kind": "level"},
    {"series_id": "CES0500000002", "event_family": "payrolls", "component_id": "hours", "label_en": "Average weekly hours", "label_zh": "平均每周工时", "value_kind": "level"},
    {"series_id": "LNS14000000", "event_family": "payrolls", "component_id": "unemployment", "label_en": "Unemployment rate", "label_zh": "失业率", "value_kind": "rate"},
    {"series_id": "LNS11300000", "event_family": "payrolls", "component_id": "participation", "label_en": "Participation rate", "label_zh": "劳动参与率", "value_kind": "rate"},
    {"series_id": "WPSFD4", "event_family": "ppi", "component_id": "headline", "label_en": "PPI final demand", "label_zh": "PPI 最终需求", "value_kind": "index"},
    {"series_id": "WPSFD41", "event_family": "ppi", "component_id": "final_goods", "label_en": "PPI final-demand goods", "label_zh": "PPI 最终需求商品", "value_kind": "index"},
    {"series_id": "WPSFD42", "event_family": "ppi", "component_id": "final_services", "label_en": "PPI final-demand services", "label_zh": "PPI 最终需求服务", "value_kind": "index"},
    {"series_id": "WPSFD4111", "event_family": "ppi", "component_id": "core", "label_en": "PPI final demand less food, energy and trade services", "label_zh": "剔除食品、能源与贸易服务的 PPI", "value_kind": "index"},
    {"series_id": "WPSID61", "event_family": "ppi", "component_id": "pipeline_processed", "label_en": "Processed goods for intermediate demand", "label_zh": "中间需求已加工商品", "value_kind": "index"},
    {"series_id": "WPSID62", "event_family": "ppi", "component_id": "pipeline_unprocessed", "label_en": "Unprocessed goods for intermediate demand", "label_zh": "中间需求未加工商品", "value_kind": "index"},
    {"series_id": "WPSID63", "event_family": "ppi", "component_id": "pipeline_services", "label_en": "Services for intermediate demand", "label_zh": "中间需求服务", "value_kind": "index"},
)

# Classification is intentionally explicit and inspectable. A title can match
# multiple words; rules are evaluated top-to-bottom and the first match wins.
EVENT_FAMILY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("fomc", ("fed interest rate decision", "fomc", "federal reserve")),
    ("cpi", ("core cpi", "consumer price index", "cpi")),
    ("ppi", ("producer price", "ppi")),
    ("pce", ("pce price", "personal consumption expenditures price")),
    ("payrolls", ("non farm payroll", "nonfarm payroll", "average hourly earnings")),
    ("labour", ("unemployment rate", "jobless claims", "jolts", "employment change")),
    ("gdp", ("gdp growth", "gross domestic product")),
    ("retail_sales", ("retail sales",)),
    ("pmi", ("pmi", "ism manufacturing", "ism services")),
    ("china_activity", ("industrial production", "fixed asset investment")),
    ("trade", ("trade balance", "exports", "imports")),
    ("housing", ("house price", "housing starts", "building permits", "new home sales")),
    ("korea_activity", ("bank of korea", "bok", "south korea")),
)

FAMILY_LABELS: dict[str, tuple[str, str]] = {
    "fomc": ("FOMC / Fed", "美联储 / FOMC"),
    "cpi": ("Consumer inflation", "消费者通胀"),
    "ppi": ("Producer inflation", "生产者通胀"),
    "pce": ("PCE inflation", "PCE 通胀"),
    "payrolls": ("US payrolls", "美国非农就业"),
    "labour": ("Labour market", "劳动力市场"),
    "gdp": ("GDP", "GDP"),
    "retail_sales": ("Retail sales", "零售销售"),
    "pmi": ("PMI / ISM", "PMI / ISM"),
    "china_activity": ("China activity", "中国经济活动"),
    "trade": ("Trade", "贸易"),
    "housing": ("Housing", "房地产与住宅"),
    "korea_activity": ("Korea activity", "韩国经济活动"),
    "other": ("Other macro", "其他宏观"),
}

# These are analysis contracts, not observations. The coarse CPI weights are
# the official December 2025 reference weights (using 2024 spending weights),
# not current-month spending estimates. The UI labels them with their vintage;
# a future collector can add monthly release-table weights without rewriting
# these contracts.
COMPONENT_CONTRACTS: tuple[dict[str, object], ...] = (
    {"event_family": "cpi", "component_id": "headline", "label_en": "Headline CPI", "label_zh": "整体 CPI", "group": "headline", "behavior": "mixed", "weight": 100.0, "weight_as_of": "2025-12 reference", "weight_source_url": "https://www.bls.gov/cpi/tables/relative-importance/2025.htm", "notes_en": "Total basket; decompose before interpreting the policy signal.", "notes_zh": "整体篮子；判断政策含义前必须拆分。"},
    {"event_family": "cpi", "component_id": "core", "label_en": "Core CPI", "label_zh": "核心 CPI", "group": "core", "behavior": "sticky", "weight": 79.919, "weight_as_of": "2025-12 reference", "weight_source_url": "https://www.bls.gov/cpi/tables/relative-importance/2025.htm", "notes_en": "All items less food and energy; reference weight, not current spending.", "notes_zh": "剔除食品与能源；为参考权重，并非当前消费支出。"},
    {"event_family": "cpi", "component_id": "food", "label_en": "Food", "label_zh": "食品", "group": "headline", "behavior": "mixed", "weight": 13.698, "weight_as_of": "2025-12 reference", "weight_source_url": "https://www.bls.gov/cpi/tables/relative-importance/2025.htm", "notes_en": "Separate food at home (8.325%) from food away from home (5.373%).", "notes_zh": "区分家中食品（8.325%）与外出餐饮（5.373%）。"},
    {"event_family": "cpi", "component_id": "energy", "label_en": "Energy", "label_zh": "能源", "group": "headline", "behavior": "short_shock", "weight": 6.383, "weight_as_of": "2025-12 reference", "weight_source_url": "https://www.bls.gov/cpi/tables/relative-importance/2025.htm", "notes_en": "Often a fast commodity shock; gasoline is 2.895% and energy services 3.262%.", "notes_zh": "通常属于快速商品冲击；汽油占2.895%，能源服务占3.262%。"},
    {"event_family": "cpi", "component_id": "shelter", "label_en": "Shelter", "label_zh": "住房", "group": "core_services", "behavior": "sticky", "weight": 35.625, "weight_as_of": "2025-12 reference", "weight_source_url": "https://www.bls.gov/cpi/tables/relative-importance/2025.htm", "notes_en": "Rent and owners' equivalent rent are slow-moving and high persistence.", "notes_zh": "租金与业主等价租金变化较慢、粘性较高。"},
    {"event_family": "cpi", "component_id": "core_goods", "label_en": "Core goods", "label_zh": "核心商品", "group": "core_goods", "behavior": "mixed", "weight": 19.176, "weight_as_of": "2025-12 reference", "weight_source_url": "https://www.bls.gov/cpi/tables/relative-importance/2025.htm", "notes_en": "Commodities less food and energy commodities; inspect vehicles, apparel and household goods.", "notes_zh": "剔除食品与能源商品的核心商品；需查看汽车、服装及家居用品。"},
    {"event_family": "cpi", "component_id": "supercore", "label_en": "Services ex rent of shelter (broad)", "label_zh": "剔除租金住房后的广义服务", "group": "core_services", "behavior": "sticky", "weight": 28.673, "weight_as_of": "2025-12 reference", "weight_source_url": "https://www.bls.gov/cpi/tables/relative-importance/2025.htm", "notes_en": "BLS services less rent of shelter; includes energy services and is an overlapping aggregate, not an additive core bucket.", "notes_zh": "BLS“剔除租金住房后的服务”；包含能源服务，与核心商品/住房不是可直接相加的互斥篮子。"},
    {"event_family": "ppi", "component_id": "headline", "label_en": "Final-demand PPI", "label_zh": "最终需求 PPI", "group": "final_demand", "behavior": "mixed", "weight": None, "weight_as_of": None, "notes_en": "Headline final-demand index; decompose goods, services and pipeline before interpreting persistence.", "notes_zh": "最终需求总指数；判断粘性前先拆分商品、服务与价格链。"},
    {"event_family": "ppi", "component_id": "final_goods", "label_en": "Final-demand goods", "label_zh": "最终需求商品", "group": "final_demand", "behavior": "mixed", "weight": None, "weight_as_of": None, "notes_en": "Separate energy and food from core goods.", "notes_zh": "将能源、食品与核心商品拆分。"},
    {"event_family": "ppi", "component_id": "final_services", "label_en": "Final-demand services", "label_zh": "最终需求服务", "group": "final_demand", "behavior": "sticky", "weight": None, "weight_as_of": None, "notes_en": "Trade margins can be volatile; transport and warehousing may transmit energy shocks.", "notes_zh": "贸易利润率波动较大；运输仓储可能传导能源冲击。"},
    {"event_family": "ppi", "component_id": "core", "label_en": "Final demand ex food, energy and trade services", "label_zh": "剔除食品、能源与贸易服务的最终需求", "group": "core", "behavior": "sticky", "weight": None, "weight_as_of": None, "notes_en": "A persistence lens for the PPI signal; not the same as CPI core.", "notes_zh": "PPI 粘性观察口径；不等同于 CPI 核心。"},
    {"event_family": "ppi", "component_id": "pipeline", "label_en": "Intermediate-demand pipeline", "label_zh": "中间需求价格链", "group": "pipeline", "behavior": "leading", "weight": None, "weight_as_of": None, "notes_en": "Inspect processed, unprocessed and service intermediate demand for pipeline pressure.", "notes_zh": "通过已加工、未加工及服务中间需求观察价格链压力。"},
    {"event_family": "ppi", "component_id": "pipeline_processed", "label_en": "Processed intermediate goods", "label_zh": "已加工中间商品", "group": "pipeline", "behavior": "leading", "weight": None, "weight_as_of": None, "notes_en": "Processed-goods pipeline pressure.", "notes_zh": "已加工商品价格链压力。"},
    {"event_family": "ppi", "component_id": "pipeline_unprocessed", "label_en": "Unprocessed intermediate goods", "label_zh": "未加工中间商品", "group": "pipeline", "behavior": "short_shock", "weight": None, "weight_as_of": None, "notes_en": "More exposed to commodity and supply shocks.", "notes_zh": "更容易受商品及供应冲击影响。"},
    {"event_family": "ppi", "component_id": "pipeline_services", "label_en": "Intermediate-demand services", "label_zh": "中间需求服务", "group": "pipeline", "behavior": "sticky", "weight": None, "weight_as_of": None, "notes_en": "Service-input pressure can precede final-demand services.", "notes_zh": "服务投入压力可能领先于最终需求服务。"},
    {"event_family": "payrolls", "component_id": "headline", "label_en": "Nonfarm payroll change", "label_zh": "非农就业变化", "group": "establishment", "behavior": "coincident", "weight": None, "weight_as_of": None, "notes_en": "Read with two-month revisions, not in isolation.", "notes_zh": "必须结合前两个月修正值，而非孤立解读。"},
    {"event_family": "payrolls", "component_id": "unemployment", "label_en": "Unemployment rate", "label_zh": "失业率", "group": "household", "behavior": "coincident", "weight": None, "weight_as_of": None, "notes_en": "Household survey concept differs from the payroll survey.", "notes_zh": "住户调查口径与机构就业调查不同。"},
    {"event_family": "payrolls", "component_id": "participation", "label_en": "Participation rate", "label_zh": "劳动参与率", "group": "household", "behavior": "structural", "weight": None, "weight_as_of": None, "notes_en": "Explains whether unemployment moved through labour supply.", "notes_zh": "判断失业率变化是否来自劳动力供给。"},
    {"event_family": "payrolls", "component_id": "wages", "label_en": "Average hourly earnings", "label_zh": "平均时薪", "group": "wages", "behavior": "sticky", "weight": None, "weight_as_of": None, "notes_en": "Track MoM, YoY and production/non-supervisory workers.", "notes_zh": "跟踪环比、同比及生产与非管理岗位工资。"},
    {"event_family": "payrolls", "component_id": "hours", "label_en": "Average weekly hours", "label_zh": "平均每周工时", "group": "hours", "behavior": "leading", "weight": None, "weight_as_of": None, "notes_en": "Hours can weaken before firms reduce headcount.", "notes_zh": "企业裁员前，工时可能先走弱。"},
    {"event_family": "fomc", "component_id": "decision", "label_en": "Policy decision", "label_zh": "政策决定", "group": "decision", "behavior": "event", "weight": None, "weight_as_of": None, "notes_en": "Compare with the full pre-event rate distribution, not only a modal outcome.", "notes_zh": "应与会前完整利率分布比较，而非仅看众数结果。"},
    {"event_family": "fomc", "component_id": "statement", "label_en": "Statement changes", "label_zh": "声明变化", "group": "communication", "behavior": "forward", "weight": None, "weight_as_of": None, "notes_en": "Diff growth, inflation, labour and balance-of-risks language.", "notes_zh": "比较增长、通胀、就业与风险平衡措辞。"},
    {"event_family": "fomc", "component_id": "sep", "label_en": "SEP and dots", "label_zh": "经济预测与点阵图", "group": "projections", "behavior": "forward", "weight": None, "weight_as_of": None, "notes_en": "Available only at projection meetings.", "notes_zh": "仅在发布经济预测的会议提供。"},
    {"event_family": "fomc", "component_id": "press_conference", "label_en": "Press conference", "label_zh": "新闻发布会", "group": "communication", "behavior": "forward", "weight": None, "weight_as_of": None, "notes_en": "Separate prepared framing from answers to questions.", "notes_zh": "区分开场陈述与问答信息。"},
    {"event_family": "gdp", "component_id": "consumption", "label_en": "Consumption", "label_zh": "消费", "group": "expenditure", "behavior": "coincident", "weight": None, "weight_as_of": None, "notes_en": "Separate goods and services contributions.", "notes_zh": "区分商品与服务消费贡献。"},
    {"event_family": "gdp", "component_id": "investment", "label_en": "Fixed investment", "label_zh": "固定投资", "group": "expenditure", "behavior": "cyclical", "weight": None, "weight_as_of": None, "notes_en": "Inspect residential and non-residential structures/equipment.", "notes_zh": "查看住宅与非住宅建筑、设备投资。"},
    {"event_family": "gdp", "component_id": "inventories", "label_en": "Inventories", "label_zh": "库存", "group": "expenditure", "behavior": "volatile", "weight": None, "weight_as_of": None, "notes_en": "A large contribution can reverse and need not imply final-demand strength.", "notes_zh": "大幅库存贡献可能反转，并不必然代表最终需求强。"},
    {"event_family": "gdp", "component_id": "net_exports", "label_en": "Net exports", "label_zh": "净出口", "group": "expenditure", "behavior": "volatile", "weight": None, "weight_as_of": None, "notes_en": "Imports can make the GDP contribution counterintuitive.", "notes_zh": "进口变化可能令GDP贡献方向反直觉。"},
    {"event_family": "retail_sales", "component_id": "control", "label_en": "Control group", "label_zh": "控制组", "group": "core", "behavior": "signal", "weight": None, "weight_as_of": None, "notes_en": "More relevant to consumption tracking than the headline alone.", "notes_zh": "相比总项，更适合跟踪消费趋势。"},
    {"event_family": "retail_sales", "component_id": "autos_gas", "label_en": "Autos and gasoline", "label_zh": "汽车与汽油", "group": "volatile", "behavior": "short_shock", "weight": None, "weight_as_of": None, "notes_en": "Price and unit effects can dominate the headline.", "notes_zh": "价格及销量效应可能主导总项。"},
    {"event_family": "pmi", "component_id": "new_orders", "label_en": "New orders", "label_zh": "新订单", "group": "growth", "behavior": "leading", "weight": None, "weight_as_of": None, "notes_en": "Forward demand signal.", "notes_zh": "前瞻需求信号。"},
    {"event_family": "pmi", "component_id": "employment", "label_en": "Employment", "label_zh": "就业", "group": "labour", "behavior": "leading", "weight": None, "weight_as_of": None, "notes_en": "Useful before official labour releases but not directly comparable.", "notes_zh": "可在官方就业数据前提供线索，但口径不可直接等同。"},
    {"event_family": "pmi", "component_id": "prices", "label_en": "Prices paid", "label_zh": "购进价格", "group": "inflation", "behavior": "leading", "weight": None, "weight_as_of": None, "notes_en": "Pipeline inflation signal with sector-specific interpretation.", "notes_zh": "价格链通胀信号，需按行业解释。"},
    {"event_family": "china_activity", "component_id": "industry", "label_en": "Industrial production", "label_zh": "工业增加值", "group": "activity", "behavior": "coincident", "weight": None, "weight_as_of": None, "notes_en": "Compare manufacturing, mining and utilities.", "notes_zh": "比较制造业、采矿业及公用事业。"},
    {"event_family": "china_activity", "component_id": "retail", "label_en": "Retail sales", "label_zh": "社会消费品零售", "group": "activity", "behavior": "coincident", "weight": None, "weight_as_of": None, "notes_en": "Separate goods categories and catering where available.", "notes_zh": "在可用时拆分商品类别与餐饮。"},
    {"event_family": "china_activity", "component_id": "fai", "label_en": "Fixed-asset investment", "label_zh": "固定资产投资", "group": "investment", "behavior": "structural", "weight": None, "weight_as_of": None, "notes_en": "Separate infrastructure, manufacturing and property investment.", "notes_zh": "区分基建、制造业及房地产投资。"},
)

SCENARIO_TEMPLATES: dict[str, tuple[dict[str, str], ...]] = {
    "cpi": (
        {"scenario": "hot", "label_en": "Broad/sticky upside surprise", "label_zh": "广泛且粘性的上行意外", "rates": "bearish", "usd": "bullish", "spy": "bearish", "qqq": "bearish", "soxx": "bearish", "sk_hynix": "bearish", "gold": "ambiguous", "invalidation_en": "Upside is concentrated in energy or another reversible shock.", "invalidation_zh": "上行主要集中于能源或其他可逆短期冲击。"},
        {"scenario": "soft", "label_en": "Broad core disinflation", "label_zh": "广泛核心通胀降温", "rates": "bullish", "usd": "bearish", "spy": "bullish", "qqq": "bullish", "soxx": "bullish", "sk_hynix": "bullish", "gold": "mixed", "invalidation_en": "Growth data simultaneously deteriorate enough to raise earnings risk.", "invalidation_zh": "增长数据同步显著恶化并抬升盈利风险。"},
    ),
    "ppi": (
        {"scenario": "hot", "label_en": "Services/pipeline upside surprise", "label_zh": "服务及价格链上行意外", "rates": "bearish", "usd": "bullish", "spy": "bearish", "qqq": "bearish", "soxx": "bearish", "sk_hynix": "bearish", "gold": "ambiguous", "invalidation_en": "The move is entirely volatile trade margins or energy.", "invalidation_zh": "变化完全来自波动较大的贸易利润率或能源。"},
    ),
    "payrolls": (
        {"scenario": "hot", "label_en": "Strong jobs plus sticky wages", "label_zh": "就业强劲且工资粘性", "rates": "bearish", "usd": "bullish", "spy": "mixed", "qqq": "mixed", "soxx": "mixed", "sk_hynix": "mixed", "gold": "bearish", "invalidation_en": "Headline strength is offset by negative revisions and fewer hours.", "invalidation_zh": "强劲总项被下修及工时下降抵消。"},
        {"scenario": "soft", "label_en": "Orderly cooling", "label_zh": "有序降温", "rates": "bullish", "usd": "bearish", "spy": "bullish", "qqq": "bullish", "soxx": "bullish", "sk_hynix": "bullish", "gold": "mixed", "invalidation_en": "Unemployment jumps through layoffs rather than participation.", "invalidation_zh": "失业率因裁员而非参与率上升而跳升。"},
    ),
    "fomc": (
        {"scenario": "hawkish", "label_en": "Higher-for-longer repricing", "label_zh": "更高更久重新定价", "rates": "bearish", "usd": "bullish", "spy": "bearish", "qqq": "bearish", "soxx": "bearish", "sk_hynix": "bearish", "gold": "bearish", "invalidation_en": "Press conference reverses the statement/dot interpretation.", "invalidation_zh": "发布会推翻市场对声明或点阵图的初步解读。"},
        {"scenario": "dovish", "label_en": "Earlier/easier path", "label_zh": "更早或更宽松路径", "rates": "bullish", "usd": "bearish", "spy": "bullish", "qqq": "bullish", "soxx": "bullish", "sk_hynix": "bullish", "gold": "bullish", "invalidation_en": "Easing is driven by a material growth or credit accident.", "invalidation_zh": "宽松由重大增长或信用事故驱动。"},
    ),
    "retail_sales": (
        {"scenario": "broad_strength", "label_en": "Broad control-group strength", "label_zh": "控制组广泛走强", "rates": "bearish", "usd": "bullish", "spy": "bullish", "qqq": "mixed", "soxx": "mixed", "sk_hynix": "mixed", "gold": "bearish", "invalidation_en": "Headline strength comes only from autos, gasoline prices or an unrevised seasonal factor.", "invalidation_zh": "总项强劲仅来自汽车、汽油价格或不稳定季调。"},
        {"scenario": "broad_weakness", "label_en": "Broad control-group weakness", "label_zh": "控制组广泛走弱", "rates": "bullish", "usd": "bearish", "spy": "bearish", "qqq": "mixed", "soxx": "bearish", "sk_hynix": "bearish", "gold": "mixed", "invalidation_en": "Weakness is concentrated in volatile categories or follows an upward revision.", "invalidation_zh": "疲弱集中于波动项目，或前值同时被上修。"},
    ),
    "gdp": (
        {"scenario": "final_demand_up", "label_en": "Final demand stronger than headline", "label_zh": "最终需求强于总项", "rates": "bearish", "usd": "bullish", "spy": "bullish", "qqq": "mixed", "soxx": "bullish", "sk_hynix": "bullish", "gold": "bearish", "invalidation_en": "Nominal strength is paired with a larger inflation deflator surprise.", "invalidation_zh": "名义增长强劲但同时伴随更高通胀平减指数。"},
        {"scenario": "inventory_headline", "label_en": "Headline boosted by inventories/net exports", "label_zh": "库存或净出口推高总项", "rates": "mixed", "usd": "mixed", "spy": "mixed", "qqq": "mixed", "soxx": "mixed", "sk_hynix": "mixed", "gold": "mixed", "invalidation_en": "Consumption and fixed investment also accelerate.", "invalidation_zh": "消费与固定投资也同步加速。"},
    ),
    "pmi": (
        {"scenario": "orders_up_prices_down", "label_en": "Orders improve, prices cool", "label_zh": "订单改善、价格降温", "rates": "mixed", "usd": "mixed", "spy": "bullish", "qqq": "bullish", "soxx": "bullish", "sk_hynix": "bullish", "gold": "mixed", "invalidation_en": "Employment and output remain in contraction.", "invalidation_zh": "就业与产出仍处于收缩。"},
        {"scenario": "prices_up_orders_down", "label_en": "Prices rise, orders weaken", "label_zh": "价格上升、订单走弱", "rates": "bearish", "usd": "mixed", "spy": "bearish", "qqq": "bearish", "soxx": "bearish", "sk_hynix": "bearish", "gold": "ambiguous", "invalidation_en": "The price move is confined to one supply-shock sector.", "invalidation_zh": "价格上升仅集中在一个供应冲击行业。"},
    ),
    "china_activity": (
        {"scenario": "broad_acceleration", "label_en": "Industry, consumption and FAI accelerate", "label_zh": "工业、消费与投资同步加速", "rates": "mixed", "usd": "bearish", "spy": "mixed", "qqq": "mixed", "soxx": "bullish", "sk_hynix": "bullish", "gold": "mixed", "invalidation_en": "Acceleration is state-led while property and private demand deteriorate.", "invalidation_zh": "加速主要由国有部门驱动，而地产与私人需求恶化。"},
        {"scenario": "broad_slowdown", "label_en": "Broad activity slowdown", "label_zh": "经济活动广泛放缓", "rates": "bullish", "usd": "bullish", "spy": "bearish", "qqq": "mixed", "soxx": "bearish", "sk_hynix": "bearish", "gold": "mixed", "invalidation_en": "Policy impulse or credit data turn decisively before the activity release.", "invalidation_zh": "政策脉冲或信用数据在活动数据前已明显转强。"},
    ),
    "housing": (
        {"scenario": "supply_demand_up", "label_en": "Permits, starts and sales strengthen", "label_zh": "许可、开工与销售同步改善", "rates": "bearish", "usd": "mixed", "spy": "bullish", "qqq": "mixed", "soxx": "mixed", "sk_hynix": "mixed", "gold": "bearish", "invalidation_en": "Mortgage rates or builder incentives make the improvement temporary.", "invalidation_zh": "按揭利率或开发商激励使改善不可持续。"},
    ),
}
