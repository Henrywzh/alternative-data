// Chinese translations for source-health / source-coverage row content
// (dataset name, source label, notes), keyed by each source's own English
// "dataset" field so a lookup works regardless of which table it renders
// in. Shared between build-static-hub.mjs (the site-wide /data-status
// page) and package-dashboard.mjs (each sector's own embedded
// source_health_table / active_signals_table / coverage_table) -- both
// read from the same underlying source_health / source_coverage(_active|
// _planned) datasets, so duplicating this dictionary per-script would just
// invite the two copies to drift.
export const STATUS_ZH = {
  type: {
    Measure: "指标",
    Event: "事件",
    Catalog: "目录",
    Snapshot: "快照",
    Context: "背景",
  },
  status: {
    Healthy: "健康",
    Planned: "计划中",
    "Catalog only": "仅目录",
    Degraded: "已降级",
    "No data this run": "本次运行无数据",
  },
  freshness: {
    Live: "实时",
    "Live at build time": "构建时实时",
    "Same-day snapshot": "当日快照",
    "Snapshot (irregular updates)": "快照（不定期更新）",
    "stale/unreachable": "过期/无法访问",
    "Content parser pending": "内容解析待完成",
    "Endpoint returns no data": "接口未返回数据",
    "Footprint snapshot (most brands: 1-2 dated snapshots so far, not yet a trend)":
      "足迹快照（大部分品牌目前仅有1-2个存有日期的快照，尚未构成趋势）",
  },
  rows: {
    "Centaline CCL": {
      dataset: "中原CCL",
      source: "中原城市领先指数（CCL）",
      notes: "最新观察值已发布，未标注为临时值。",
    },
    "Midland MHPI": {
      dataset: "美联MHPI",
      source: "美联市场洞察 — MHPI",
      notes: "最新观察值已发布，未标注为临时值。",
    },
    "Midland Confidence Index": {
      dataset: "美联信心指数",
      source: "美联市场洞察 — 信心指数",
      notes: "最新观察值已发布，未标注为临时值。",
    },
    "RVD Residential Price Index": {
      dataset: "差饷物业估价署住宅价格指数",
      source: "差饷物业估价署 — 私人住宅价格指数",
      notes: "最新观察值为临时值。",
    },
    "RVD Residential Rental Index": {
      dataset: "差饷物业估价署住宅租金指数",
      source: "差饷物业估价署 — 私人住宅租金指数",
      notes: "最新观察值为临时值。",
    },
    "EPI / ERI": {
      dataset: "EPI / ERI",
      source: "28Hse",
      notes: "28Hse EPI / ERI 历史指数；详见上方图表/表格。",
    },
    "Centaline / Midland / 28Hse transactions": {
      dataset: "中原 / 美联 / 28Hse 成交",
      source: "代理行成交",
      notes: "已去重的代理行成交数据；详见上方图表/表格。",
    },
    "Monthly facts + ASP series": {
      dataset: "月度事实 + ASP 系列",
      source: "土地注册处",
      notes: "土地注册处月度统计（JSON）；详见上方图表/表格。",
    },
    "Monthly digest + project lifecycle": {
      dataset: "月度摘要 + 项目生命周期",
      source: "屋宇署",
      notes: "屋宇署月度摘要 / 项目生命周期；详见上方图表/表格。",
    },
    "First-hand residential project documents": {
      dataset: "一手住宅项目文件",
      source: "SRPE",
      notes: "当前发现代码尚未提取销售、单位、价单或去化等事实。",
    },
    "HKO Severe Weather & FRED FX": {
      dataset: "香港天文台恶劣天气与FRED汇率",
      source: "香港天文台恶劣天气警告与FRED汇率",
      notes: "每月八号或以上风球及红色/黑色暴雨警告时长，并列港元/人民币汇率。",
    },
    "Immigration Passenger Clearance": {
      dataset: "出入境旅客通关",
      source: "香港入境事务处每日旅客流量",
      notes: "覆盖17个管制站的香港居民及内地访客每日通关量。",
    },
    "SGE Gold Benchmark": {
      dataset: "上海黄金交易所黄金基准价",
      source: "上海黄金交易所上午/下午基准价",
      notes: "每日上午/下午基准价。",
    },
    "AFCD Wholesale Food Prices": {
      dataset: "农渔护理署食品批发价格",
      source: "农渔护理署鲜活食品批发价格",
      notes: "5类31种商品；按同日市场读数取平均。",
    },
    "HK Consumer Ticker Valuations": {
      dataset: "香港消费股估值",
      source: "百度股市通港股估值",
      notes: "仅提供市盈率（TTM）、市净率和市值；该接口没有股息率指标。",
    },
    "Retail Sales Value/Volume Index": {
      dataset: "零售业销货价值/数量指数",
      source: "政府统计处零售业销货价值/数量指数",
      notes: "25个零售类别，自2004年起按月统计。",
    },
    "Restaurant Receipts & Purchases Survey": {
      dataset: "餐饮业收益及购货额调查",
      source: "政府统计处季度餐饮业收益及购货额调查",
      notes: "仅提供全行业购货额；未公布分类型购货额。",
    },
    "HK Retail/F&B Store Counts": {
      dataset: "香港零售/餐饮店铺数量",
      source: "香港零售/餐饮店铺数量抓取器",
      notes: "11家公司共计10,788个跟踪地点。",
    },
    "Online Price Watch": {
      dataset: "网上价格监测",
      source: "香港消费者委员会",
      notes: "接口需要重新核验后才能上线。",
    },
    clp_electricity: {
      dataset: "CLP电力",
      source: "中华电力香港售电披露",
      notes: "按住宅、商业、基础设施及公共服务、制造业拆分季度售电量（GWh），并包括AI数据中心需求增长。",
    },
    towngas_proxy: {
      dataset: "煤气消费代理指标",
      source: "政府统计处香港能源统计（煤气消费）",
      notes: "按用户类型（住宅、商业、工业）统计月度煤气消费量，单位为太焦耳（TJ）；作为煤气垄断经营的运营代理指标。",
    },
    hko_temperature: {
      dataset: "香港天文台气温",
      source: "香港天文台每日平均气温",
      notes: "每日平均气温（°C）及月度平均值；是空调电力负荷的主要物理驱动因素。",
    },
    power_assets_segments: {
      dataset: "电能实业地理分部",
      source: "电能实业地理分部报告",
      notes: "半年度地理分部报告（收入、分部利润、合营/联营公司应占业绩），按香港电灯、英国、澳洲及其他地区拆分。",
    },
    labour_force_monthly: {
      dataset: "劳动力月度数据",
      source: "政府统计处劳动力、就业、失业及就业不足统计",
      notes: "每月三个月移动平均系列；年度估计另行保留。",
    },
    labour_demand_by_industry: {
      dataset: "按行业划分的职位空缺",
      source: "政府统计处按行业划分的职位空缺统计",
      notes: "按季劳动力需求调查；不包括公务员职位空缺。",
    },
    nominal_wage_index_by_industry: {
      dataset: "名义工资及薪金指数",
      source: "政府统计处工资及薪金指数",
      notes: "政府统计处发布的工资及薪金指数；与就业收入中位数并非同一指标。",
    },
    wage_payroll_indices: {
      dataset: "工资及薪金指数",
      source: "政府统计处工资及薪金指数",
      notes: "政府统计处发布的工资及薪金指数；与就业收入中位数并非同一指标。",
    },
    median_earnings_by_industry: {
      dataset: "行业就业收入中位数",
      source: "政府统计处每月就业收入中位数",
      notes: "每月就业收入中位数；主趋势图采用三个月移动平均系列。",
    },
    talent_policy_supply_panel: {
      dataset: "人才政策流量数据",
      source: "劳工处及入境事务处人才政策公开数据",
      notes: "申请、批准及优秀人才计划配额是政策流量指标，不是实际抵港或就业人数。",
    },
    mtr_patronage: {
      dataset: "港铁客流",
      source: "港铁公司投资者关系月度客流",
      notes: "按铁路服务统计月度客流及日均客流：本地、机场快线、跨境（罗湖及落马洲）、轻铁及巴士、高速铁路。",
    },
    cathay_hkia_traffic: {
      dataset: "香港机场及国泰航空客流",
      source: "民航处香港机场月度航空交通及国泰航空投资者关系客运数据（PDF）",
      notes: "香港机场飞机升降量、旅客量、货运吨数，以及国泰旅客量、RPK、ASK和客座率（%）；按月直接读取国泰投资者关系交通数据PDF（每月网址确定）。",
    },
    china_airline_traffic: {
      dataset: "中国上市航空公司运营数据",
      source: "中国上市航空公司月度运营数据",
      notes: "中国国航、南方航空、东方航空和春秋航空的月度旅客量、ASK、RPK及客座率，按国内、国际和地区航线拆分。",
    },
    hkt_operating_drivers: {
      dataset: "香港电讯运营驱动因素",
      source: "香港电讯信托及香港电讯有限公司（6823.HK）业绩公告",
      notes: "半年度主要运营驱动因素：移动后付费/预付费客户、消费者宽带线路、收费电视客户基础，以及后付费期末ARPU和FTTH覆盖率；从香港电讯业绩公告文本中提取。",
    },
    smartone_operating_drivers: {
      dataset: "数码通运营驱动因素",
      source: "数码通电讯集团（0315.HK）业绩简报",
      notes: "半年度移动后付费客户数、后付费ARPU趋势，以及5G相对4G的ARPU比率，来自数码通业绩简报。",
    },
    hutchison_telecom_operating_drivers: {
      dataset: "和记电讯运营驱动因素",
      source: "和记电讯香港控股（0215.HK，“3香港”）业绩公告",
      notes: "半年度主要表现指标：后付费/预付费客户、月度后付费流失率、后付费毛ARPU与净ARPU，以及5G渗透率。",
    },
    numbering_plan: {
      dataset: "号码规划",
      source: "OFCA号码规划（移动号码段分配）",
      notes: "按运营商统计移动号码段分配，涵盖4家持牌移动网络运营商及MVNO；这是容量/覆盖代理指标，不是客户数或时间序列指标（详见表格说明）。",
    },
    linkreit_fundamentals: {
      dataset: "领展REIT基本面",
      source: "领展（0823.HK）投资者关系披露",
      notes: "领展每基金单位NAV、DPU、出租率和租金调幅。",
    },
    championreit_fundamentals: {
      dataset: "冠君产业信托基本面",
      source: "冠君产业信托（2778.HK）财务披露",
      notes: "花园道三号及朗豪坊办公/零售组合的每单位NAV、DPU、出租率和租金调幅。",
    },
    fortunereit_fundamentals: {
      dataset: "置富产业信托基本面",
      source: "置富产业信托（0778.HK）财务披露",
      notes: "香港新界零售组合的每单位NAV、DPU、出租率和租金调幅。",
    },
    prosperityreit_fundamentals: {
      dataset: "泓富产业信托基本面",
      source: "泓富产业信托（0808.HK）财务披露",
      notes: "分散式办公及工业组合的每单位NAV、DPU、出租率和租金调幅。",
    },
    sunlightreit_fundamentals: {
      dataset: "阳光房地产基金基本面",
      source: "阳光房地产基金（0435.HK）财务披露",
      notes: "办公及零售组合的每单位NAV、DPU、出租率和租金调幅。",
    },
    regalreit_fundamentals: {
      dataset: "富豪产业信托基本面",
      source: "富豪产业信托（1881.HK）酒店表现披露",
      notes: "酒店组合的运营指标：出租率（%）、平均每日房价（ADR，港元）、RevPAR（港元）、DPU及每单位NAV。",
    },
    reit_price_akshare: {
      dataset: "香港REITs每日现货报价及历史",
      source: "香港REITs每日现货报价及历史（akshare）",
      notes: "香港6只REIT的每日现货价格、涨跌幅及OHLC日线历史。",
    },
  },
};
