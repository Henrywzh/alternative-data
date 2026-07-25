#!/usr/bin/env node

import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const generatedDir = join(projectRoot, ".generated");
const distDir = join(projectRoot, "dist");

function findPortableBuilder() {
  if (process.env.DATA_ANALYTICS_PORTABLE_BUILDER) {
    return resolve(process.env.DATA_ANALYTICS_PORTABLE_BUILDER);
  }
  const base = join(
    process.env.CODEX_HOME || join(homedir(), ".codex"),
    "plugins/cache/openai-curated-remote/data-analytics"
  );
  if (!existsSync(base)) {
    throw new Error(
      "Data Analytics portable builder was not found. Set DATA_ANALYTICS_PORTABLE_BUILDER to deliver_portable_artifact.mjs."
    );
  }
  const candidates = readdirSync(base, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) =>
      join(base, entry.name, "skills/build-report/scripts/deliver_portable_artifact.mjs")
    )
    .filter(existsSync)
    .sort()
    .reverse();
  if (!candidates.length) {
    throw new Error("No installed Data Analytics portable builder version contains the delivery script.");
  }
  return candidates[0];
}

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

// --- Per-sector Chinese localization -----------------------------------

const HK_REAL_ESTATE_ZH = {
  title: "香港房地产市场监测",
  description: "基于来源的住宅价格、租金和市场信心指标快照。",
  cards: {
    ccl_card: { description: "最新发布指数；周环比与同比变动。", metricLabels: ["CCL", "周环比", "同比"] },
    mhpi_card: { description: "最新发布指数；周环比与同比变动。", metricLabels: ["MHPI", "周环比", "同比"] },
    rvd_price_card: { description: "官方月度指数；月环比与同比变动。", metricLabels: ["RVD 价格", "月环比", "同比"] },
    rvd_rent_card: { description: "官方月度指数；月环比与同比变动。", metricLabels: ["RVD 租金", "月环比", "同比"] },
  },
  charts: {
    ccl_trend: ["中原城市领先指数（CCL）", "发布方周度指数；最新点可能早于构建日期。", "周", "指数"],
    mhpi_trend: ["美联物业价格指数（MHPI）", "美联物业发布的香港整体周度指数。", "周", "指数"],
    rvd_trend: ["官方住宅价格与租金指数", "差饷物业估价署全类别月度指数；保留已审阅数据中的 provisional 标记。", "月份", "价格指数", "租金指数"],
    rvd_rent_trend: ["RVD 租金指数（配套视图）", "与价格图表使用相同的月度观测，以租金作为主序列。", "月份", "租金指数", "价格指数"],
    rebased_trend: ["五年跨来源走势", "各序列在窗口内首个可用月份重设为 100；不同来源的原始水平不可直接比较。", "月份", "重设基准指数"],
    confidence_trend: ["美联物业信心指数", "辅助性的市场情绪指标，不是住宅价格指标。", "周", "信心指数"],
  },
  tables: {
    source_health_table: {
      title: "实时来源健康度",
      subtitle: "以上指标的构建时校验结果。",
      columns: { dataset: "数据集", status: "状态", latest_observation: "最新日期", records: "记录数", freshness: "新鲜度", notes: "备注" },
    },
    coverage_table: {
      title: "覆盖范围与下一步采集目标",
      subtitle: "来源目录发现不会被当作市场指标。",
      columns: { source: "来源", dataset: "数据集", type: "类型", status: "状态", freshness: "新鲜度", notes: "范围 / 限制" },
    },
  },
  sources: {
    centaline_ccl: "中原城市领先指数（CCL）",
    midland_mhpi: "美联物业市场资讯 — MHPI",
    midland_confidence: "美联物业市场资讯 — 信心指数",
    rvd_price: "差饷物业估价署 — 私人住宅售价指数",
    rvd_rent: "差饷物业估价署 — 私人住宅租金指数",
    cross_source: "跨来源标准化比较",
    source_registry: "香港房地产 dashboard 来源登记表",
  },
  snapshotBody: (artifact) =>
    `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。这是已发布快照，不是实时连接；RVD 标记为 provisional 的观测可能会修订。`,
  methodologyBody:
    "## 如何阅读本 dashboard\n\n不同发布方的指数基期不同。请在重设基准图中比较方向，不要直接比较原始数值水平。覆盖表区分实时指标、来源目录和计划中的采集工作。本 dashboard 不提供股票排名、预测或投资建议。",
};

const HK_LOCAL_CONSUMER_ZH = {
  title: "香港本地消费监测",
  description: "极端天气干扰时长、港元/人民币汇率、跨境出入境人流（北上/南下）、黄金原料成本、零售销售、餐饮收益及消费股估值的来源快照。",
  cards: {
    northbound_card: { description: "每日经陆路口岸（不含机场及邮轮/渡轮码头）出境的香港居民人次（7日移动平均）；日环比与同比变动。", metricLabels: ["北上7日均值（陆路口岸）", "日环比", "同比"] },
    southbound_card: { description: "每日内地访客入境人次（7日移动平均）；日环比与同比变动。", metricLabels: ["南下7日均值", "日环比", "同比"] },
    weather_card: { description: "月度八号及以上风球与红/黑色暴雨警告总持续时长；同比变动。", metricLabels: ["极端天气干扰 (小时/月)", "同比"] },
    fx_card: { description: "基于 FRED 每日报价计算的月度平均港元/人民币交叉汇率；月环比与同比变动。", metricLabels: ["人民币 / 100 港元", "月环比", "同比"] },
    gold_card: { description: "上海黄金交易所 PM 基准定盘价（人民币/克）；日环比与同比变动。", metricLabels: ["黄金 PM 基准价 (人民币/克)", "日环比", "同比"] },
    median_pe_card: { description: "本地消费观察名单各公司历史市盈率的中位数。", metricLabels: ["市盈率中位数 (TTM)"] },
    retail_card: { description: "政府统计处零售销售价值指数（全部零售店铺）；月环比与同比变动。", metricLabels: ["零售销售指数", "月环比", "同比"] },
    restaurant_card: { description: "全行业季度餐饮收益（百万港元）；季环比与同比变动。", metricLabels: ["餐饮收益 (百万港元)", "季环比", "同比"] },
  },
  charts: {
    severe_weather_trend: ["月度极端天气干扰时长 (小时)", "按月汇总的八号及以上热带气旋警告与红/黑色暴雨警告持续时间。", "月份", "小时"],
    immigration_trend: ["跨境旅客流量 (7日移动平均)", "入境事务处发布的每日客流：北上为香港居民经陆路口岸出境，南下为内地访客经全部口岸入境。", "日期", "人次/日 (7日均值)", "流向"],
    gold_trend: ["上海黄金交易所 PM 基准价", "近7年人民币/克每日定盘价；是香港金饰原料成本的主要参考。", "日期", "人民币 / 克"],
    afcd_category_chart: ["农渔护理署批发价按类别", "今日各类别商品的平均批发价（每公斤）。", "类别", "港元 / 公斤"],
    valuation_pe_chart: ["观察名单历史市盈率对比", "各公司最新的正值历史市盈率；亏损公司不计入此视图。", "公司", "市盈率 (TTM)"],
    retail_trend: ["零售销售价值指数（全部店铺）", "政府统计处月度价值指数，完整已发布历史。", "月份", "价值指数"],
    retail_category_chart: ["零售销售价值指数按类别", "最新发布月份，按零售店铺类型划分。", "类别", "价值指数"],
    restaurant_trend: ["餐饮收益（全部食肆）", "季度全行业收益，百万港元，完整已发布历史。", "季度", "百万港元"],
    restaurant_chart: ["餐饮收益按类型", "最新发布季度，百万港元。", "食肆类型", "百万港元"],
  },
  tables: {
    severe_weather_log_table: {
      title: "近期极端天气警告事件记录",
      subtitle: "近期红/黑色暴雨警告及八号或以上热带气旋警告的开始时间、结束时间及持续时长。",
      columns: { signal_name: "警告信号", start: "开始时间 (HKT)", end: "结束时间 (HKT)", duration_hours: "持续时长 (小时)" },
    },
    afcd_commodity_table: {
      title: "农渔护理署批发价快照",
      subtitle: "同日各商品平均价格，港元/公斤（由官方公布的港元/斤换算）。",
      columns: { category: "类别", commodity_name: "商品", avg_price_hkd_per_kg: "港元 / 公斤", num_readings: "读数个数" },
    },
    valuation_table: {
      title: "消费观察名单估值快照",
      subtitle: "各公司最新历史市盈率、市净率及市值。",
      columns: { company_name: "公司", ticker: "股票代码", pe_ttm: "市盈率 (TTM)", pb_ratio: "市净率", market_cap_hkd_b: "市值 (十亿港元)", date: "截至日期" },
    },
    retail_category_table: {
      title: "零售销售按类别快照",
      subtitle: "最新发布月份；按零售店铺类型划分的价值与销量指数。",
      columns: { category: "类别", sales_value_index: "价值指数", sales_volume_index: "销量指数", date: "截至日期" },
    },
    restaurant_snapshot_table: {
      title: "餐饮收益按类型快照",
      subtitle: "最新发布季度；全行业采购额仅在「全部食肆」合计行显示。",
      columns: { sub_sector: "食肆类型", total_receipts_hkd_m: "收益 (百万港元)", total_purchases_hkd_m: "采购额 (百万港元)", receipts_value_index: "收益价值指数", date: "截至日期" },
    },
    source_health_table: {
      title: "实时来源健康度",
      subtitle: "以上指标的构建时校验结果。",
      columns: { dataset: "数据集", status: "状态", latest_observation: "最新日期", records: "记录数", freshness: "新鲜度", notes: "备注" },
    },
    coverage_table: {
      title: "覆盖范围与下一步采集目标",
      subtitle: "端点存在问题或未经验证的来源在此追踪，而非以占位值展示。",
      columns: { source: "来源", dataset: "数据集", type: "类型", status: "状态", freshness: "新鲜度", notes: "范围 / 限制" },
    },
  },
  sources: {
    afcd_wholesale: "农渔护理署新鲜食品批发价格",
    sge_gold: "上海黄金交易所 AM/PM 基准价",
    hk_valuation: "百度股市通香港股票估值",
    cnsd_retail: "政府统计处零售销售价值/销量指数",
    censtatd_restaurant: "政府统计处季度餐饮收益及采购调查",
    immigration_flow: "入境事务处每日出入境旅客流量统计",
    weather_demand_drivers: "香港天文台警告数据库 & FRED 汇率",
    source_registry: "香港本地消费 dashboard 来源登记表",
  },
  snapshotBody: (artifact) =>
    `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody:
    "## 如何阅读本 dashboard\n\n本界面整合物理天气干扰、汇率环境、出入境流量、零售金价溢价、零售销售、餐饮收益与消费股估值等代理指标，以评估香港本地零售与餐饮业的宏观受压情况。",
};

const HK_UTILITIES_ZH = {
  title: "香港公用事业与基础设施监测",
  description: "中电控股（CLP）季度售电量拆解、中华煤气（Towngas）代理数据、香港天文台日均气温与电能实业（Power Assets）分部业绩快照。",
  cards: {
    clp_card: { description: "季度中电香港本地售电总量、商业售电量及 AI 数据中心用电同比变动。", metricLabels: ["总售电量 (GWh)", "商业售电量 (GWh)", "AI 数据中心同比"] },
    towngas_card: { description: "政府统计处月度全港煤气消费总量，按住宅及商业用户拆解。", metricLabels: ["总耗气量 (TJ)", "住宅耗气量 (TJ)", "商业耗气量 (TJ)"] },
    temp_card: { description: "香港天文台录得的最新日均气温及月度平均气温。", metricLabels: ["最新气温 (°C)", "月均气温 (°C)"] },
    power_assets_card: { description: "电能实业半年度分部收入、分部溢利及合资/联营业绩总额。", metricLabels: ["总分部收入 (百万港元)", "总分部溢利 (百万港元)", "合资/联营业绩 (百万港元)"] },
  },
  charts: {
    clp_sector_chart: ["中电香港售电量按行业拆解 (GWh)", "季度售电量拆解为住宅、商业、基础设施与公共服务及制造行业。", "季度", "售电量 (GWh)"],
    towngas_trend_chart: ["香港煤气消费量走势 (TJ)", "月度全港煤气消费总量拆解为住宅、商业及工业用户。", "月份", "太焦耳 (TJ)"],
    temp_trend_chart: ["香港天文台日均气温走势 (°C)", "每日平均气温历史与月度平均气温线对比。", "日期", "°C"],
  },
  tables: {
    power_assets_geography_table: {
      title: "电能实业（Power Assets）按地理区域划分的分部业绩",
      subtitle: "半年度分部财务数据（2025 上半年），百万港元；「港灯投资」按权益法入账，在本注释下的收入/分部溢利列示为零，其贡献计入合资/联营业绩一栏。",
      columns: { geography: "地区", revenue_hkdm: "分部收入 (百万港元)", segment_profit_hkdm: "分部溢利 (百万港元)", jv_associate_results_hkdm: "合资/联营业绩 (百万港元)" },
    },
  },
  sources: {
    clp_electricity: "中电控股（0002.HK）业绩公告及售电量披露",
    towngas_proxy: "政府统计处能源统计（煤气消费量）",
    hko_temperature: "香港天文台每日平均气温",
    power_assets_segments: "电能实业（0006.HK）中期及全年业绩报告",
  },
  snapshotBody: (artifact) => `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody: "## 如何阅读本 dashboard\n\n售电量与燃气消费量反映香港公用事业核心业务运营水平；日均气温为夏日用电负荷的物理驱动因素。",
};

const HK_TRANSPORT_ZH = {
  title: "香港交通与航空监测",
  description: "港铁月度客运量（本地/跨境/高铁）、国泰航空运营数据与香港国际机场流量的来源快照。",
  cards: {
    mtr_card: { description: "港铁月度总客运量，按本地及跨境服务拆解，并附对比 2019 年月均水平的复苏率。", metricLabels: ["总客运量 (千人次)", "本地 (千人次)", "跨境 (千人次)", "较 2019 年均值"] },
    cathay_card: { description: "国泰集团月度载客人数、载客率及香港国际机场客运量，并附对比 2019 年月均水平的复苏率。", metricLabels: ["国泰乘客人数", "载客率 (%)", "机场乘客人数", "较 2019 年均值"] },
  },
  charts: {
    mtr_total_patronage_chart: ["港铁总客运量走势 (2000年至今，千人次)", "26 年月度港铁总客运量数据，完整呈现 2003 年沙士（SARS）冲击（2003 年 4 月低点约 4,880 万人次）及更深、更持久的 2019-22 新冠疫情冲击（2022 年 2 月低点约 7,190 万人次），其后复苏至接近 2019 年疫情前月均水平。", "月份", "千人次"],
    mtr_service_breakdown_chart: ["港铁客运量按服务类型走势 (2018年至今，千人次)", "本地重铁、跨境、高铁、机场快线及轻铁与巴士的月度乘客人次，聚焦近 8 年数据以保持五条曲线清晰可读（完整 26 年总量走势见上图）。", "月份", "千人次"],
    cathay_passengers_chart: ["国泰集团载客人数走势 (2012年至今)", "13 年月度国泰集团载客人数，呈现新冠疫情期间近乎归零的冲击（由 2018 年 8 月约 328 万人次高点跌至 2020 年 4 月约 1.37 万人次低点，跌幅逾 99.5%）及其后的多年复苏。", "月份", "乘客人数"],
    cathay_load_factor_chart: ["国泰集团载客率走势 (%)", "月度载客率——相较于原始载客人数，更能反映国泰自身运力利用率与定价能力，因其已扣除国泰当时投放的运力规模。", "月份", "载客率 (%)"],
    cathay_capacity_demand_chart: ["国泰集团运力与需求对比 (ASK 对比 RPK，千单位)", "可用座位公里（投放运力）与收益乘客公里（实际填补需求）对比——两线差距与旁边载客率图表互为镜像。", "月份", "千单位"],
    hkia_passengers_chart: ["香港国际机场总客运量走势", "香港国际机场（民航处数据）全部航空公司合计的月度总客运量，较国泰专属图表更能反映航空需求的整体水平。", "月份", "乘客人数"],
  },
  tables: {},
  sources: {
    mtr_patronage: "港铁公司投资者关系月度客运量",
    cathay_hkia_traffic: "民航处香港国际机场月度流量 & 国泰航空数据",
  },
  snapshotBody: (artifact) => `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody: "## 如何阅读本 dashboard\n\n港铁客运量按服务类型拆解（本地重铁、跨境及高铁）；机场与国泰数据反映国际与区域航空客货运复苏进度。",
};

const HK_TELECOM_ZH = {
  title: "香港电讯监测",
  description: "香港电讯（HKT）、数码通（SmarTone）及和记电讯（3 HK）的半年度用户与 ARPU 披露数据，以及通讯办全运营商手机号码段配额快照。",
  cards: {
    hkt_card: { description: "半年度后付费退出 ARPU 及后付费用户数（千户）；半年环比变动。", metricLabels: ["后付费 ARPU (港元)", "后付费用户数 (千户)", "半年环比"] },
    smartone_card: { description: "半年度后付费 ARPU 及后付费用户数（千户）；同比变动。", metricLabels: ["后付费 ARPU (港元)", "后付费用户数 (千户)", "同比"] },
    hutchison_card: { description: "半年度后付费毛 ARPU 与净 ARPU；半年环比变动。", metricLabels: ["后付费毛 ARPU (港元)", "后付费净 ARPU (港元)", "半年环比"] },
  },
  charts: {
    hkt_arpu_chart: ["香港电讯后付费退出 ARPU 走势 (港元)", "半年度后付费退出 ARPU，取自香港电讯自身业绩公告的叙述文本。", "期间", "港元"],
    smartone_arpu_chart: ["数码通后付费 ARPU 与用户数走势", "半年度后付费 ARPU（港元）及后付费用户基础（千户）。", "期间", "港元"],
    hutchison_arpu_chart: ["和记电讯（3 HK）后付费毛/净 ARPU 对比", "半年度后付费毛 ARPU 与净 ARPU（港元）——三家运营商中披露最细的单用户经济数据。", "期间", "港元"],
  },
  tables: {
    numbering_plan_table: {
      title: "通讯办按运营商划分的手机号码段配额",
      subtitle: "覆盖全部 4 家持牌移动网络运营商及虚拟运营商的粗略结构性代理指标。",
      columns: { allocatee: "运营商 / 持牌人", num_blocks: "号码段数量", total_numbers_allocated: "已分配号码数" },
    },
  },
  sources: {
    hkt_operating_drivers: "香港电讯信托及香港电讯有限公司（6823.HK）业绩公告",
    smartone_operating_drivers: "数码通电讯控股（0315.HK）业绩简报",
    hutchison_telecom_operating_drivers: "和记电讯香港控股（0215.HK，「3 HK」）业绩公告",
    numbering_plan: "通讯事务管理局办公室编号计划（手机号码段配额）",
  },
  snapshotBody: (artifact) => `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody:
    "## 如何阅读本 dashboard\n\n三家运营商的后付费 ARPU 与用户数均取自其各自的 HKEX 业绩公告或投资者简报叙述文本，半年度更新。",
};

const HK_REIT_ZH = {
  title: "香港房地产信托（REITs）基本面监测",
  description: "领展（Link REIT）、冠君（Champion REIT）、置富（Fortune REIT）、繁荣（Prosperity REIT）、阳光（Sunlight REIT）及富豪（Regal REIT）的每单位资产净值（NAV）、每基金单位分派（DPU）、出租率、租金检讨调升率及酒店 KPI 快照。",
  cards: {
    linkreit_card: { description: "领展房产基金（0823.HK）最新每单位资产净值、DPU 及出租率/租金检讨调升率披露。", metricLabels: ["每单位资产净值 (港元)", "每基金单位分派 (港元)", "出租率 (%)", "租金检讨调升率 (%)"] },
    championreit_card: { description: "冠君产业信托（2778.HK）最新每单位资产净值、DPU 及出租率/租金检讨调升率披露。", metricLabels: ["每单位资产净值 (港元)", "每基金单位分派 (港元)", "出租率 (%)", "租金检讨调升率 (%)"] },
    fortunereit_card: { description: "置富产业信托（0778.HK）最新每单位资产净值、DPU 及出租率/租金检讨调升率披露。", metricLabels: ["每单位资产净值 (港元)", "每基金单位分派 (港元)", "出租率 (%)", "租金检讨调升率 (%)"] },
    prosperityreit_card: { description: "繁荣产业信托（0808.HK）最新每单位资产净值、DPU 及出租率/租金检讨调升率披露。", metricLabels: ["每单位资产净值 (港元)", "每基金单位分派 (港元)", "出租率 (%)", "租金检讨调升率 (%)"] },
    sunlightreit_card: { description: "阳光房地产基金（0435.HK）最新每单位资产净值、DPU 及出租率/租金检讨调升率披露。", metricLabels: ["每单位资产净值 (港元)", "每基金单位分派 (港元)", "出租率 (%)", "租金检讨调升率 (%)"] },
    regalreit_card: { description: "富豪产业信托（1881.HK）最新每单位资产净值、DPU 及酒店 KPI 披露。", metricLabels: ["每单位资产净值 (港元)", "每基金单位分派 (港元)", "酒店出租率 (%)", "RevPAR (港元)"] },
  },
  charts: {
    nav_trend_chart: ["各 REIT 每单位资产净值走势 (港元)", "全部六家 REIT（按股票代码；全名见下方对比表）各自投资者关系披露的每单位资产净值历史。", "期间", "港元 / 单位", "股票代码"],
    dpu_trend_chart: ["各 REIT 每基金单位分派走势 (港元)", "全部六家 REIT（按股票代码）的 DPU 历史；部分期间（如富豪产业信托 2025 上半年）分派为零属真实披露结果，并非数据缺失。", "期间", "港元 / 单位", "股票代码"],
    occupancy_trend_chart: ["写字楼/零售 REIT 出租率走势 (%)", "领展 (0823)、冠君 (2778)、置富 (0778)、繁荣 (0808) 及阳光 (0435)——不含富豪产业信托（其组合为酒店而非写字楼/零售）。", "期间", "出租率 (%)", "股票代码"],
    reversion_trend_chart: ["写字楼/零售 REIT 租金检讨调升率走势 (%)", "续租/新租相对原有租金的调升率，仅限五家写字楼/零售 REIT（按股票代码）。", "期间", "租金检讨调升率 (%)", "股票代码"],
    regal_hotel_kpi_chart: ["富豪产业信托酒店 KPI：出租率、ADR 及 RevPAR", "富豪产业信托的酒店组合指标体系与其余五家写字楼/零售 REIT 完全不同，故不与其合并显示；出租率单位为 %，ADR 及 RevPAR 单位为港元，请以提示框中的具体数值为准。", "期间", "数值（单位不一）", "指标"],
  },
  tables: {
    reit_comparison_table: {
      title: "香港 REIT 基本面对比",
      subtitle: "全部六家 REIT 最新每单位资产净值及 DPU；出租率跨业务类型统一列示（富豪产业信托为酒店出租率）；租金检讨调升率及酒店房价指标在不适用的 REIT 上为空。",
      columns: {
        reit_name: "REIT 名称",
        ticker: "股票代码",
        business_type: "业务类型",
        nav_per_unit_hkd: "每单位资产净值 (港元)",
        dpu_hkd: "每基金单位分派 (港元)",
        occupancy_pct: "出租率 (%)",
        rental_reversion_pct: "租金检讨调升率 (%)",
        average_daily_rate_hkd: "平均房价 ADR (港元)",
        revpar_hkd: "RevPAR (港元)",
        as_of_date: "截至日期",
      },
    },
  },
  sources: {
    linkreit_fundamentals: "领展房产基金（0823.HK）投资者关系披露",
    championreit_fundamentals: "冠君产业信托（2778.HK）财务披露",
    fortunereit_fundamentals: "置富产业信托（0778.HK）财务披露",
    prosperityreit_fundamentals: "繁荣产业信托（0808.HK）财务披露",
    sunlightreit_fundamentals: "阳光房地产基金（0435.HK）财务披露",
    regalreit_fundamentals: "富豪产业信托（1881.HK）酒店业绩披露",
  },
  snapshotBody: (artifact) => `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody: "## 如何阅读本 dashboard\n\n五家 REIT（领展、冠君、置富、繁荣、阳光）为写字楼/零售业主，披露出租率与租金检讨调升率；富豪产业信托为酒店类 REIT，披露出租率、平均房价（ADR）及 RevPAR，其酒店指标从不与其余五家的写字楼/零售指标合并显示于同一图表。DPU 在个别期间可能为零（真实披露结果，非数据缺失），此时环比变动留空而非除以零。本 dashboard 不提供股票排名、预测或投资建议。",
};

function localizeArtifact(input, zh) {
  const artifact = JSON.parse(JSON.stringify(input));
  artifact.manifest.title = zh.title;
  artifact.manifest.description = zh.description;
  if (artifact.manifest.cards) {
    artifact.manifest.cards.forEach((card) => {
      const copy = zh.cards[card.id];
      if (!copy) return;
      card.description = copy.description;
      const labels = copy.metricLabels;
      card.metrics.forEach((metric, index) => {
        if (Array.isArray(labels)) {
          if (labels[index]) metric.label = labels[index];
          return;
        }
        // Legacy shorthand for the common [value, cadence, YoY] card shape.
        if (index === 0) metric.label = copy.label;
        if (index === 1 && copy.cadence) metric.label = copy.cadence;
        if (index === 2) metric.label = "同比";
      });
    });
  }
  if (artifact.manifest.charts) {
    artifact.manifest.charts.forEach((chart) => {
      const copy = zh.charts[chart.id];
      if (!copy) return;
      chart.title = copy[0];
      chart.subtitle = copy[1];
      if (chart.encodings?.x) chart.encodings.x.label = copy[2];
      if (chart.encodings?.y) chart.encodings.y.label = copy[3];
      if (chart.encodings?.tooltip?.[0]) chart.encodings.tooltip[0].label = copy[4] || chart.encodings.tooltip[0].label;
      if (chart.encodings?.color) chart.encodings.color.label = "序列";
      if (chart.comparisonContext?.normalization) chart.comparisonContext.normalization = "首个可用月份 = 100";
    });
  }
  if (artifact.manifest.tables) {
    artifact.manifest.tables.forEach((table) => {
      const copy = zh.tables[table.id];
      if (!copy) return;
      table.title = copy.title;
      table.subtitle = copy.subtitle;
      table.columns.forEach((column) => {
        if (copy.columns[column.field]) column.label = copy.columns[column.field];
      });
    });
  }
  if (artifact.manifest.sources) {
    artifact.manifest.sources = artifact.manifest.sources.map((source) => ({
      ...source,
      label: zh.sources[source.id] || source.label,
    }));
  }
  if (Array.isArray(artifact.sources)) {
    artifact.sources = artifact.sources.map((source) => ({
      ...source,
      label: zh.sources[source.id] || source.label,
      query: source.query ? {
        ...source.query,
        description: source.query.description
          ? `构建时从公开来源读取并校验 ${zh.sources[source.id] || source.label}。`
          : source.query.description,
      } : source.query,
    }));
  }
  const snapshot = artifact.manifest.blocks?.find((block) => block.id === "snapshot_context");
  if (snapshot) snapshot.body = zh.snapshotBody(artifact);
  const methodology = artifact.manifest.blocks?.find((block) => block.id === "methodology");
  if (methodology) methodology.body = zh.methodologyBody;
  return artifact;
}

function addNavigation(html, { locale, homeEn, homeZh, routeEn, routeZh }) {
  const chinese = locale === "zh";
  const home = chinese ? homeZh : homeEn;
  const languageHref = chinese ? routeEn : routeZh;
  const backLabel = chinese ? "← 返回主 dashboard" : "← Back to main dashboard";
  const languageLabel = chinese ? "English" : "简体中文";
  const css = `<style>.am-dashboard-nav{position:fixed;top:12px;left:12px;z-index:1000;display:flex;gap:8px;align-items:center;font:500 12px/1.2 system-ui,-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif}.am-dashboard-nav a{display:inline-flex;align-items:center;min-height:30px;padding:0 10px;border:1px solid rgba(128,128,128,.35);border-radius:999px;background:rgba(255,255,255,.94);color:#1f2937;text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,.08)}.am-dashboard-nav a:hover{background:#f2f4f7}@media(prefers-color-scheme:dark){.am-dashboard-nav a{background:rgba(255,255,255,.94);color:#f3f4f6;border-color:rgba(255,255,255,.25)}}</style>`;
  const nav = `<nav class="am-dashboard-nav" aria-label="Dashboard navigation"><a href="${home}">${backLabel}</a><a href="${languageHref}">${languageLabel}</a></nav>`;
  return html.replace("</head>", `${css}</head>`).replace("<body>", `<body>${nav}`);
}

function spawnDelivery(deliveryScript, args) {
  return new Promise((resolvePromise) => {
    const child = spawn(process.execPath, [deliveryScript, ...args], {
      cwd: projectRoot,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("close", (code) => resolvePromise({ status: code, stdout, stderr }));
    child.on("error", (error) => resolvePromise({ status: 1, stdout, stderr: `${stderr}\n${error.message}` }));
  });
}

async function deliverPortable({ deliveryScript, artifactFile, portableFile, locale }) {
  const failureScreenshot = join(generatedDir, `portable-verification-failure-${locale}.png`);
  const maxAttempts = Math.max(1, Number(process.env.PORTABLE_DELIVERY_RETRIES || 2));
  let lastDelivery = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const delivery = await spawnDelivery(deliveryScript, [
      "--input", artifactFile,
      "--output", portableFile,
      "--screenshot", failureScreenshot,
      "--ready-timeout-ms", process.env.PORTABLE_READY_TIMEOUT_MS || "30000",
      "--action-timeout-ms", process.env.PORTABLE_ACTION_TIMEOUT_MS || "10000",
      "--timeout-ms", process.env.PORTABLE_VERIFY_TIMEOUT_MS || "60000",
    ]);
    lastDelivery = delivery;
    if (delivery.status === 0) {
      const receipt = JSON.parse(delivery.stdout.trim());
      if (receipt.ok && receipt.stages?.verification === "passed") return receipt;
    }
  }
  process.stderr.write(lastDelivery?.stdout || "");
  process.stderr.write(lastDelivery?.stderr || "");
  throw new Error(`Portable dashboard delivery failed (${locale}) after ${maxAttempts} attempt(s).`);
}

const SECTORS = [
  { id: "hk-real-estate", statusFile: "dashboard-status.json", zh: HK_REAL_ESTATE_ZH },
  { id: "hk-local-consumer", statusFile: "dashboard-status-hk-local-consumer.json", zh: HK_LOCAL_CONSUMER_ZH },
  { id: "hk-utilities", statusFile: "dashboard-status-hk-utilities.json", zh: HK_UTILITIES_ZH },
  { id: "hk-transport", statusFile: "dashboard-status-hk-transport.json", zh: HK_TRANSPORT_ZH },
  { id: "hk-telecom", statusFile: "dashboard-status-hk-telecom.json", zh: HK_TELECOM_ZH },
  { id: "hk-reit", statusFile: "dashboard-status-hk-reit.json", zh: HK_REIT_ZH },
];

if (!existsSync(distDir)) {
  throw new Error("Run the static hub build step before packaging dashboards.");
}

mkdirSync(generatedDir, { recursive: true });
let deliveryScript = null;
let verifyPortableArtifactStructure = null;
try {
  deliveryScript = findPortableBuilder();
  const verifyModule = await import(`file://${join(dirname(deliveryScript), "verify_portable_artifact.mjs")}`);
  verifyPortableArtifactStructure = verifyModule.verifyPortableArtifactStructure;
} catch (error) {
  process.stdout.write(`[package-dashboard] Portable builder unavailable (${error.message}); skipping dashboard packaging.\n`);
  process.exit(0);
}

for (const sector of SECTORS) {
  const statusPath = join(projectRoot, "src/data", sector.statusFile);
  if (!existsSync(statusPath)) {
    process.stdout.write(`[package-dashboard] Status file ${sector.statusFile} missing; skipping ${sector.id}.\n`);
    continue;
  }

  const statusData = JSON.parse(readFileSync(statusPath, "utf8"));
  const sectorSlug = sector.id;
  const artifactFile = join(generatedDir, `${sectorSlug}-artifact.json`);
  const zhArtifactFile = join(generatedDir, `${sectorSlug}-artifact-zh.json`);

  if (!existsSync(artifactFile)) {
    process.stdout.write(`[package-dashboard] Artifact file ${artifactFile} missing for ${sector.id}; skipping.\n`);
    continue;
  }

  const rawArtifact = JSON.parse(readFileSync(artifactFile, "utf8"));
  const zhArtifact = localizeArtifact(rawArtifact, sector.zh);
  writeFileSync(zhArtifactFile, JSON.stringify(zhArtifact, null, 2));

  const sectorDistEn = join(distDir, "sectors", sectorSlug);
  const sectorDistZh = join(distDir, "zh", "sectors", sectorSlug);
  mkdirSync(sectorDistEn, { recursive: true });
  mkdirSync(sectorDistZh, { recursive: true });

  const enPortableFile = join(sectorDistEn, "index.html");
  const zhPortableFile = join(sectorDistZh, "index.html");

  process.stdout.write(`[package-dashboard] Delivering ${sector.id} (EN)...\n`);
  await deliverPortable({ deliveryScript, artifactFile, portableFile: enPortableFile, locale: "en" });

  process.stdout.write(`[package-dashboard] Delivering ${sector.id} (ZH)...\n`);
  await deliverPortable({ deliveryScript, artifactFile: zhArtifactFile, portableFile: zhPortableFile, locale: "zh" });

  const routeEn = `/sectors/${sectorSlug}/`;
  const routeZh = `/zh/sectors/${sectorSlug}/`;
  const homeEn = "/";
  const homeZh = "/zh/";

  writeFileSync(
    enPortableFile,
    addNavigation(readFileSync(enPortableFile, "utf8"), { locale: "en", homeEn, homeZh, routeEn, routeZh })
  );
  writeFileSync(
    zhPortableFile,
    addNavigation(readFileSync(zhPortableFile, "utf8"), { locale: "zh", homeEn, homeZh, routeEn, routeZh })
  );

  const exportsDir = join(distDir, "exports");
  mkdirSync(exportsDir, { recursive: true });
  const attachmentFilename = statusData.attachment_filename || `${sectorSlug}-monitor.html`;
  cpSync(enPortableFile, join(exportsDir, attachmentFilename));

  process.stdout.write(`[package-dashboard] Completed ${sector.id}.\n`);
}

process.stdout.write("[package-dashboard] All sector dashboards packaged successfully.\n");
