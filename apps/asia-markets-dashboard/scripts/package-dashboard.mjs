#!/usr/bin/env node

import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { appRoot as projectRoot, attachmentNames, LIVE_SECTORS } from "./sectors.mjs";
import { STATUS_ZH } from "./status-zh.mjs";

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

// --- Chart/table data-value localization --------------------------------
//
// localizeArtifact() (below) only rewrites chart titles/subtitles/axis
// labels and table column headers -- static config text. It does NOT touch
// the actual row values inside artifact.snapshot.datasets, so any chart or
// table that renders a categorical field's raw string value (a color-legend
// entry, a bar-chart x-axis category, a table cell) shows whatever English
// string the Python builder baked into the dataset, regardless of locale.
// The helpers below patch known offending fields in-place on the (already
// cloned) zh artifact. Only fields verified to hold a small, closed set of
// translatable category/status strings are touched here -- ticker codes,
// company/REIT/product names, and other proper nouns are deliberately left
// alone (see per-sector comments for why).

// Shared across every sector: the "real-time source health" and "coverage"
// tables use the same status/type/freshness/dataset/source/notes vocabulary
// everywhere they appear (currently hk-real-estate and hk-local-consumer).
// Reuses STATUS_ZH -- the same dictionary build-static-hub.mjs applies to
// the site-wide /data-status page -- instead of a second, sector-page-local
// copy: an earlier local copy here (STATUS_VALUE_ZH/TYPE_VALUE_ZH/
// FRESHNESS_VALUE_ZH) had already drifted out of sync with it (missing
// "stale/unreachable", "Live", "Live at build time", ...) and never
// translated `dataset`/`source`/`notes` at all, leaving every row's own
// label and explanatory text in English regardless of locale.
function translateFreshnessValue(value) {
  if (typeof value !== "string") return value;
  if (STATUS_ZH.freshness[value]) return STATUS_ZH.freshness[value];
  const dayMatch = /^(\d+)d old$/.exec(value);
  return dayMatch ? `${dayMatch[1]} 天前` : value;
}
const HEALTH_COVERAGE_DATASET_IDS = [
  "source_health",
  "source_coverage",
  "source_coverage_active",
  "source_coverage_planned",
];
function localizeHealthCoverageDatasets(artifact) {
  HEALTH_COVERAGE_DATASET_IDS.forEach((datasetId) => {
    const rows = artifact.snapshot?.datasets?.[datasetId];
    if (!Array.isArray(rows)) return;
    rows.forEach((row) => {
      if (!row || typeof row !== "object") return;
      const translated = STATUS_ZH.rows[row.dataset] ?? {};
      if (translated.dataset) row.dataset = translated.dataset;
      if (translated.source) row.source = translated.source;
      if (translated.notes) row.notes = translated.notes;
      if (STATUS_ZH.status[row.status]) row.status = STATUS_ZH.status[row.status];
      if (STATUS_ZH.type[row.type]) row.type = STATUS_ZH.type[row.type];
      if (row.freshness) row.freshness = translateFreshnessValue(row.freshness);
    });
  });
}

// HKO warning names combine a fixed signal type with a free-form typhoon
// name (e.g. "Typhoon Signal 8 (RAGASA)") -- a lookup table alone can't
// cover every future typhoon name, so this parses the pattern instead.
const HKO_SIGNAL_STATIC_ZH = {
  "Black Rainstorm": "黑色暴雨警告信号",
  "Red Rainstorm": "红色暴雨警告信号",
};
const HKO_SIGNAL_NUMBER_ZH = {
  1: "一号戒备信号",
  3: "三号强风信号",
  8: "八号烈风或暴风信号",
  9: "九号烈风或暴风风力增强信号",
  10: "十号飓风信号",
};
function translateHkoSignalName(value) {
  if (typeof value !== "string") return value;
  if (HKO_SIGNAL_STATIC_ZH[value]) return HKO_SIGNAL_STATIC_ZH[value];
  const match = /^Typhoon Signal (\d+)(?: \((.+)\))?$/.exec(value);
  if (!match) return value;
  const numberLabel = HKO_SIGNAL_NUMBER_ZH[match[1]] || `${match[1]}号信号`;
  return match[2] ? `${numberLabel}（${match[2]}）` : numberLabel;
}

// Applies a per-sector `dataLabels` map (datasetId -> field -> translation)
// to artifact.snapshot.datasets. A translation may be a plain {en: zh}
// lookup object, or a function for values that combine a fixed vocabulary
// with a variable part (see translateHkoSignalName above).
function localizeDataLabels(artifact, dataLabels) {
  if (!dataLabels) return;
  Object.entries(dataLabels).forEach(([datasetId, fieldMap]) => {
    const rows = artifact.snapshot?.datasets?.[datasetId];
    if (!Array.isArray(rows)) return;
    rows.forEach((row) => {
      if (!row || typeof row !== "object") return;
      Object.entries(fieldMap).forEach(([field, translation]) => {
        const current = row[field];
        if (typeof current !== "string") return;
        if (typeof translation === "function") {
          row[field] = translation(current);
        } else if (translation[current]) {
          row[field] = translation[current];
        }
      });
    });
  });
}

// hk-local-consumer: C&SD retail-sales-by-outlet-type categories (official
// C&SD Chinese terminology).
const RETAIL_CATEGORY_ZH = {
  "All retail outlet": "所有零售店铺",
  "Consumer durable goods": "耐用消费品",
  "Department stores": "百货公司",
  Fuels: "燃料",
  "Other consumer goods": "其他消费品",
  Supermarkets: "超级市场",
};
// hk-local-consumer: C&SD restaurant-receipts sub-sectors. "全部食肆" matches
// the wording already used for the same concept in restaurant_snapshot_table's
// zh subtitle above.
const RESTAURANT_SUBSECTOR_ZH = {
  "All restaurants": "全部食肆",
  Bars: "酒吧",
  "Chinese restaurants": "中式餐馆",
  "Fast food shops": "快餐店",
  "Miscellaneous eating and drinking places": "其他饮食场所",
  "Non-Chinese restaurants": "非中式餐馆",
};

// hk-real-estate: Buildings Department region / permit-stage / property-
// category vocabulary, shared between bd_supply_pipeline_chart and
// bd_supply_detail_table (two different dataset ids, same vocabulary).
const BD_REGION_ZH = {
  "Hong Kong Island": "香港島",
  Kowloon: "九龍",
  "New Territories": "新界",
};
const BD_PERMIT_STAGE_ZH = {
  "Demolition Consents": "拆卸同意书 (Md52)",
  "Plans Approved": "图则已批准 (Md53)",
  "Consent to Commence": "同意开工书 (Md54)",
  "Notice of Commencement Received": "开工通知 (Md55)",
  "Occupation Permits (OP) Issued": "入伙纸 (Md56)",
};
const BD_PROPERTY_CATEGORY_ZH = {
  Domestic: "住宅",
  "Non-domestic": "非住宅",
  Unknown: "未分类（来源未提供用途）",
};
// hk-local-consumer: fehd_district_density's district_name (FEHD's own
// 19-district code list, per LP_Restaurants_EN.XML's <DIST_CODE> table).
const FEHD_DISTRICT_ZH = {
  Eastern: "东区",
  "Wan Chai": "湾仔",
  Southern: "南区",
  Islands: "离岛",
  "Central/Western": "中西区",
  "Food Truck": "美食车",
  "Kwun Tong": "观塘",
  "Kowloon City": "九龙城",
  "Wong Tai Sin": "黄大仙",
  "Yau Tsim": "油尖",
  "Mong Kok": "旺角",
  "Sham Shui Po": "深水埗",
  "Kwai Tsing": "葵青",
  "Tsuen Wan": "荃湾",
  "Tuen Mun": "屯门",
  "Yuen Long": "元朗",
  "Tai Po": "大埔",
  North: "北区",
  "Sha Tin": "沙田",
  "Sai Kung": "西贡",
};
// hk-real-estate: agency_transactions_pulse_table's primary_source_agency.
const AGENCY_NAME_ZH = {
  "Centaline Property Agency": "中原地产",
  "Midland Realty": "美联物业",
  "28Hse": "28Hse",
};

// hk-local-consumer: immigration_checkpoint_table's control-point names
// (official HK Immigration Department Chinese names) and arrival/departure.
const CONTROL_POINT_ZH = {
  Airport: "机场",
  "China Ferry Terminal": "中国客运码头",
  "Express Rail Link West Kowloon": "西九龙站（高铁）",
  "Harbour Control": "港口管制（维港）",
  "Heung Yuen Wai": "香园围",
  "Hong Kong-Zhuhai-Macao Bridge": "港珠澳大桥",
  "Kai Tak Cruise Terminal": "启德邮轮码头",
  "Lo Wu": "罗湖",
  "Lok Ma Chau": "落马洲",
  "Lok Ma Chau Spur Line": "落马洲支线",
  "Macao Ferry Terminal": "澳门客运码头",
  "Man Kam To": "文锦渡",
  "Sha Tau Kok": "沙头角",
  "Shenzhen Bay": "深圳湾",
};
const DIRECTION_ZH = { Arrival: "入境", Departure: "出境" };
// hk-local-consumer: fuel grade for consumer_council_oilprice (company
// names -- Esso, PetroChina, Caltex, Sinopec, Shell -- are brand names,
// left untranslated to match the rest of this file's company-name policy).
const FUEL_TYPE_ZH = {
  "Standard Petrol": "普通汽油",
  "Premium Petrol": "高级汽油",
};
// hk-local-consumer: Consumer Council complaint categories, shared across
// consumer_council_complaints_chart/_history_table (same 47-category
// vocabulary; the redundant "latest period" table this once also served
// was removed since consumer_council_complaints_history_table subsumes it).
const CONSUMER_COMPLAINT_CATEGORY_ZH = {
  "Agency Services": "代理服务",
  "Baby Products": "婴儿用品",
  "Bank and Financial Services": "银行及金融服务",
  "Beauty Services": "美容服务",
  "Broadcasting Services": "广播服务",
  "Cars & Car Services": "汽车及汽车服务",
  "Clothing & Apparel": "服装",
  "Computer Products": "电脑产品",
  "Decoration/Renovation Services": "装修服务",
  "Education Matters": "教育事务",
  "Elderly Care": "长者护理",
  "Electrical Appliances": "电器",
  "Food & Entertainment Services": "饮食及娱乐服务",
  "Foods & Drinks": "食品及饮料",
  Fuel: "燃油",
  "Funeral Services": "殡仪服务",
  "Furniture & Fixtures": "家具及装置",
  "Household Products/Services": "家居用品／服务",
  Insurance: "保险",
  "Jewellery & Watches": "珠宝及钟表",
  "Lawyer & Legal Services": "律师及法律服务",
  "Local Accommodation": "本地住宿",
  "Medical & Health Devices": "医疗及保健仪器",
  "Medical Services": "医疗服务",
  "Medicine & Health Foods": "药物及保健食品",
  "Miscellaneous Goods": "其他货品",
  "Miscellaneous Services": "其他服务",
  "Online Services & eCommerce Platforms": "网上服务及电子商贸平台",
  "Optical Products/Services": "眼镜产品／服务",
  "Personal Care Products": "个人护理产品",
  "Pets & Pet Services": "宠物及宠物服务",
  "Photo Taking/Finishing": "摄影及晒相服务",
  "Photographic Equipment": "摄影器材",
  Properties: "物业",
  "Public Utilities": "公用事业",
  "Publishing / Educational Materials": "出版／教育材料",
  "Recreation & Health Clubs": "康乐及健身会所",
  "Shopping Mall, Chain Store and Reward Program": "商场、连锁店及奖赏计划",
  "Sporting Goods": "体育用品",
  "Storage, Postal & Courier Services": "仓储、邮政及速递服务",
  "Telecommunication Equipment": "电讯器材",
  "Telecommunication Services": "电讯服务",
  "Time Sharing": "分时使用（度假村）",
  Toys: "玩具",
  "Transportation Services": "交通服务",
  "Travel Matters": "旅游事务",
  "Wedding Services": "婚嫁服务",
};

// --- Per-sector Chinese localization -----------------------------------

const HK_REAL_ESTATE_ZH = {
  title: "香港房地产市场监测",
  description: "基于来源的住宅价格、租金和市场信心指标快照。",
  cards: {
    ccl_card: { description: "最新发布指数；周环比与同比变动。", metricLabels: ["CCL", "周环比", "同比"] },
    mhpi_card: { description: "最新发布指数；周环比与同比变动。", metricLabels: ["MHPI", "周环比", "同比"] },
    rvd_price_card: { description: "官方月度指数；月环比与同比变动。", metricLabels: ["RVD 价格", "月环比", "同比"] },
    rvd_rent_card: { description: "官方月度指数；月环比与同比变动。", metricLabels: ["RVD 租金", "月环比", "同比"] },
    srpe_attributable_sales_card: { description: "已追踪项目中，按上市公司持股比例计算的最新月度合约销售额；单位为百万港元。", metricLabels: ["可归属销售 (百万港元)", "月环比", "同比"] },
    srpe_sales_units_card: { description: "已追踪项目在 SRPE 交易登记册最新月份记录的成交单位总数。", metricLabels: ["成交单位（总数）", "月环比", "同比"] },
    srpe_sell_through_card: { description: "各已追踪项目最新可用快照的加权销售率；有效单位除以项目公布总单位数。", metricLabels: ["销售率 (%)", "项目阶段"] },
    srpe_projects_card: { description: "通过试点登记表连接到上市公司持股比例的 SRPE 项目阶段数。", metricLabels: ["已追踪项目阶段"] },
  },
  charts: {
    ccl_trend: ["中原城市领先指数（CCL）", "发布方周度指数；最新点可能早于构建日期。", "周", "指数"],
    mhpi_trend: ["美联物业价格指数（MHPI）", "美联物业发布的香港整体周度指数。", "周", "指数"],
    rvd_trend: ["官方住宅价格与租金指数", "差饷物业估价署全类别月度指数；保留已审阅数据中的 provisional 标记。", "月份", "价格指数", "租金指数"],
    rvd_rent_trend: ["RVD 租金指数（配套视图）", "与价格图表使用相同的月度观测，以租金作为主序列。", "月份", "租金指数", "价格指数"],
    rebased_trend: ["五年跨来源走势", "各序列在窗口内首个可用月份重设为 100；不同来源的原始水平不可直接比较。", "月份", "重设基准指数"],
    confidence_trend: ["美联物业信心指数", "辅助性的市场情绪指标，不是住宅价格指标。", "周", "信心指数"],
    hkma_mortgage_rate_mix_chart: ["香港金管局住宅按揭利率计划组合 (%)", "新批按揭中，按 HIBOR 定价与最优惠利率（P按）定价的占比。", "月份", "占比 (%)", "利率计划"],
    cnsd_construction_value_chart: ["政府统计处建筑工程总值 (百万港元)", "主要承建商季度建筑工程总值——供应端管道指标。", "季度", "百万港元"],
    censtatd_land_disposals_chart: ["政府卖地（按方式划分，平方米）", "按公开拍卖／招标与私人协约方式批地划分的季度卖地面积——供应端管道指标。", "季度", "面积 (平方米)", "方式"],
    hkma_ltv_chart: ["香港金管局平均按揭成数 (%)", "新批按揭的平均贷款成数（LTV）。", "月份", "按揭成数 (%)"],
    hkma_credit_quality_chart: ["香港金管局按揭信贷质素 (%)", "拖欠比率及重订还款安排贷款比率——真实的信贷周期风险指标。", "月份", "%", "指标"],
    epi_eri_chart: ["28Hse 屋苑价格及租金指数 (EPI / ERI)", "2016年至今全港屋苑周度价格及租金指数。", "周", "指数", "指数"],
    landreg_asp_chart: ["土地注册处 — 买卖合约 (ASP)", "每月 ASP 宗数，全部楼宇单位与住宅单位对比。", "月份", "ASP 宗数", "系列"],
    bd_supply_pipeline_chart: ["屋宇署 — 房屋供应管道（当月）", "按审批阶段及地区划分的住宅单位数——未来房屋供应的领先指标。", "审批阶段", "住宅单位数", "地区"],
    bd_supply_floor_area_chart: ["屋宇署 — 各审批阶段实用楼面面积（当月）", "住宅与非住宅实用楼面面积对比，全港各区合计。", "审批阶段", "实用楼面面积 (平方米)", "物业类别"],
    bd_supply_history_units_chart: ["屋宇署 — 历史住房供应管道", "官方 PDF 档案中的月度住宅单位数：同意开工、开工通知及入伙纸阶段。", "月份", "住宅单位数", "审批阶段"],
    bd_supply_history_counts_chart: ["屋宇署 — 历史批准／同意书宗数", "官方汇总表已发布的月度项目或同意书宗数；Md55 没有相应宗数栏位。", "月份", "项目／同意书宗数", "审批阶段"],
    hkma_applications_chart: ["香港金管局新批按揭申请宗数", "每月新批住宅按揭贷款申请宗数。", "月份", "申请宗数"],
    hkma_loan_amount_chart: ["香港金管局按揭贷款金额 (百万港元)", "已批出贷款总额、二手市场占比及提取贷款金额，按月。一手/预售楼花及转按明细见下方表格。", "月份", "百万港元", "类别"],
    residential_price_rebased_chart: ["住宅价格周期 — 五年比较", "CCL、MHPI、CCI 及 EPI 分别以窗口内首个可用月份重设为 100；原始发布方水平见下方图表。", "月份", "重设基准价格指数", "系列"],
    residential_rent_rebased_chart: ["住宅租金周期 — 五年比较", "CRI、RVD 租金及 ERI 与价格分开重设为 100；原始水平及租金回报率见下方。", "月份", "重设基准租金指数", "系列"],
    cci_trend: ["中原 CCI — 住宅价格指数", "月度整体 CCI 历史；CCI 是价格指数，不是情绪指标。", "月份", "指数"],
    cri_trend: ["中原 CRI — 住宅租金指数", "来自中原标准化数据契约的月度整体 CRI 历史。", "月份", "租金指数"],
    cri_yield_trend: ["中原 CRI 租金回报率", "月度租金回报率配套序列；不是租金水平。", "月份", "回报率 (%)"],
    csi_trend: ["中原 CSI — 市场情绪", "周度市场情绪历史；目前历史 payload 仅提供住宅价格／租金情绪字段。", "周", "情绪指数", "指标"],
    rvd_office_trend: ["商业地产 — RVD 写字楼租金", "按等级划分的私人写字楼月度租金指数；数据集保留 provisional 标记。", "月份", "租金指数", "等级"],
    rvd_retail_trend: ["商业地产 — RVD 零售租金／价格", "私人零售月度租金及价格指数；数据集保留 provisional 标记。", "月份", "指数", "指标／分类"],
    srpe_developer_sales_chart: ["SRPE — 可归属一手住宅合约销售额最高的开发商", "按上市公司持股比例计算的每月可归属合约销售额；图表显示试点观察期累计销售额最高的三家开发商，单位为百万港元。", "月份", "可归属销售 (百万港元)", "", "开发商"],
    srpe_project_sell_through_chart: ["SRPE — 销售率最高的项目阶段", "根据唯一有效成交单位计算每月累计销售率；图表显示试点观察期累计可归属销售额最高的三个阶段，表格仍保留全部登记阶段。", "月份", "销售率 (%)", "", "项目阶段"],
    shkp_leading_contract_sales_chart: ["新鸿基项目活动 — 原始合约销售额", "候选阶段的 SRPE 原始合约活动（百万港元），不是新鸿基可归属收入。", "月份", "原始合约活动 (百万港元)"],
    shkp_leading_active_units_chart: ["新鸿基项目活动 — 月末有效单位", "各候选阶段月末有效单位合计；覆盖范围与 ownership 状态见下方表格。", "月份", "月末有效单位"],
    shkp_leading_coverage_chart: ["新鸿基项目活动 — SRPE 登记册覆盖", "显示有登记册覆盖的候选阶段数；阶段最后一次观察之后标为未覆盖，不代表零成交。", "月份", "已覆盖阶段数"],
  },
  blocks: {
    market_regime_intro: "## 市场周期总览\n\n以时间序列为主：比较住宅价格、租金、活动、信贷、供应及商业地产，不把单一快照当成趋势。",
    residential_sources_section: "## 住宅来源历史\n\n原始发布方水平与上方重设基准走势分开，方便核对来源定义。",
    activity_financing_section: "## 成交活动与融资\n\n成交、按揭申请、贷款金额及信贷质素使用相容的独立时间序列。",
    supply_commercial_section: "## 供应与商业地产\n\n供应历史及官方写字楼／零售租金序列与住宅价格、租金分开。",
    srpe_developer_signals_section: "## 住宅开发商销售信号\n\nSRPE 项目阶段交易登记册通过明确的持股登记表连接到上市开发商。这里是合约销售指标，不等同于会计确认收入或现金回款。",
    shkp_leading_indicators_section: "## 新鸿基项目活动监测\n\n候选阶段只代表 SRPE 原始合约活动领先指标；在取得日期有界的 ownership interval 前，不视为新鸿基可归属销售或已确认收入。",
    shkp_hk_financial_bridge_section: "## 新鸿基香港业务财务桥接\n\n这是一张证据／监测表，不是合成的香港收入时间序列。集团及分部披露可能包含合营企业及联营公司的份额；financial-data 实际值目前缺少完整原始公告日期；共识只有当前快照。销售／交付时序行保留 SRPE 原始活动、财报交付证据及预计完工窗口，不做阶段收入分配。",
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
    hkma_mortgage_activity_table: {
      title: "香港金管局按揭市场活动",
      subtitle: "月度新申请宗数、批出贷款及提取贷款金额（显示最新一期）。",
      columns: {
        date: "月份",
        new_applications_count: "新申请宗数",
        approved_loans_amount_mhkd: "批出贷款 (百万港元)",
        approved_primary_presales_amount_mhkd: "一手楼花 (百万港元)",
        approved_secondary_amount_mhkd: "二手 (百万港元)",
        approved_refinancing_amount_mhkd: "转按 (百万港元)",
        drawn_down_amount_mhkd: "已提取贷款 (百万港元)",
      },
    },
    agency_transactions_pulse_table: {
      title: "代理行成交脉动",
      subtitle: "28Hse、美联及中原放盘去重后的近期成交记录。",
      columns: {
        transaction_date: "日期",
        estate_name: "屋苑",
        saleable_area_sqft: "面积 (平方呎)",
        price_hkd: "成交价 (港元)",
        unit_price_hkd_sqft: "港元 / 平方呎",
        primary_source_agency: "主要来源代理行",
        matched_agency_count: "匹配代理行数",
      },
    },
    hse28_new_projects_table: {
      title: "新推出住宅项目",
      subtitle: "28Hse 新盘目录。",
      columns: { project_name: "项目名称", location_district: "地区", estimated_total_units: "预计单位数", estimated_move_in_year: "预计入伙年份" },
    },
    midland_top_estates_table: {
      title: "成交量最活跃屋苑（美联）",
      subtitle: "根据美联物业数据，近期成交最活跃的屋苑。",
      columns: { estate_name: "屋苑", region_name: "地区", district_name: "分区", transaction_count: "成交宗数" },
    },
    bd_supply_detail_table: {
      title: "房屋供应管道 — 明细",
      subtitle: "当月各审批阶段、地区及物业类别的项目数与楼面面积。",
      columns: {
        permit_stage: "审批阶段",
        region: "地区",
        property_category: "类别",
        total_projects_count: "项目数",
        total_domestic_units: "住宅单位数",
        total_usable_floor_area_sqm: "实用楼面面积 (平方米)",
      },
    },
    bd_monthly_stats_table: {
      title: "屋宇署月报摘要（原始统计）",
      subtitle: "月报第一节表格的原始摘录；行标签及数值保持原文。",
      columns: { date: "月份", table_id: "表格", row_label: "行", values: "数值" },
    },
    srpe_latest_project_snapshot_table: {
      title: "SRPE — 最新项目销售快照",
      subtitle: "每个已明确登记阶段的最新可用观测；上方 KPI 与开发商图表已按持股比例调整销售额。",
      columns: {
        developer: "开发商",
        project_name: "项目阶段",
        latest_period: "最新月份",
        sales_units_gross: "当月成交单位（总数）",
        cumulative_unique_active_units: "有效累计已售单位",
        total_residential_properties: "已公布总单位数",
        sell_through_pct: "销售率 (%)",
        weighted_avg_transaction_price_hkd: "加权平均成交价 (港元)",
        ownership_pct: "持股比例 (%)",
      },
    },
    shkp_leading_phase_latest_table: {
      title: "新鸿基项目活动 — 最新阶段快照",
      subtitle: "仅为领先指标；交付栏是财报／预计窗口／屋宇署快照证据；在日期有界的 ownership interval 获批准前，任何行都不会视为新鸿基可归属销售或阶段收入。",
      columns: {
        srpe_development_id: "SRPE 阶段",
        development_name: "发展项目",
        phase_name: "期数",
        candidate_status: "候选状态",
        latest_period: "最新月份",
        sales_units_gross: "原始 PASP 单位数",
        raw_contract_sales_hkd: "原始销售额 (港元)",
        active_units_eom: "月末有效单位",
        published_inventory_units: "已公布库存",
        sell_through_pct_eom: "月末销售率 (%)",
        ownership_review_status: "Ownership 审核",
        month_status: "月份状态",
        coverage_end: "登记册覆盖结束",
        handover_disclosure_status: "交付证据",
        completion_window: "完工窗口",
        bd_occupation_status: "屋宇署入伙纸快照",
      },
    },
    shkp_28hse_reconciliation_table: {
      title: "28Hse ↔ SRPE 对账覆盖",
      subtitle: "只允许 exact-unique alias 匹配；不匹配代表覆盖／身份缺口，不代表零库存。",
      columns: {
        row_side: "来源侧",
        hse28_project_name: "28Hse 项目",
        srpe_development_id: "SRPE 阶段",
        srpe_phase_name: "SRPE 期数",
        hse28_status: "28Hse 状态",
        hse28_total_units: "28Hse 总单位",
        hse28_remaining_units: "28Hse 余货",
        hse28_sold_units: "28Hse 已售",
        srpe_active_units_eom: "SRPE 月末有效单位",
        srpe_published_inventory_units: "SRPE 已公布库存",
        match_status: "匹配状态",
        coverage_note: "覆盖说明",
      },
    },
    shkp_hk_financial_bridge_table: {
      title: "新鸿基 — 香港业务财务桥接",
      subtitle: "官方集团／分部事实、香港 recurring portfolio、0016.HK 实际值、共识及 PIT 诊断；不同 row type 不应直接相加。",
      columns: {
        row_type: "行类型",
        period: "期间",
        period_type: "期间类型",
        layer: "数据层",
        geography: "地域",
        asset_class: "资产类别",
        metric: "指标",
        statistic: "统计量",
        value: "数值",
        comparison_value: "对比数值",
        difference_pct: "差异 (%)",
        unit: "单位",
        currency: "货币",
        status: "状态",
        point_in_time_quality: "PIT 质量",
        model_use: "模型用途",
        source: "来源",
        caveat: "限制",
      },
    },
  },
  sources: {
    centaline_ccl: "中原城市领先指数（CCL）",
    centaline_cci: "中原 CCI — 住宅价格指数",
    centaline_cri: "中原 CRI — 住宅租金指数",
    centaline_csi: "中原 CSI — 市场情绪",
    midland_mhpi: "美联物业市场资讯 — MHPI",
    midland_confidence: "美联物业市场资讯 — 信心指数",
    rvd_price: "差饷物业估价署 — 私人住宅售价指数",
    rvd_rent: "差饷物业估价署 — 私人住宅租金指数",
    rvd_office: "差饷物业估价署 — 写字楼租金指数",
    rvd_retail: "差饷物业估价署 — 零售租金／价格指数",
    cross_source: "跨来源标准化比较",
    source_registry: "香港房地产 dashboard 来源登记表",
    hkma_mortgage: "香港金管局住宅按揭统计调查",
    cnsd_construction: "政府统计处建筑工程总值统计",
    censtatd_land_disposals: "政府统计处表 E704 — 政府卖地统计",
    hse28_epi_eri: "28Hse 屋苑价格及租金指数",
    landreg_monthly: "土地注册处月度统计",
    bd_supply: "屋宇署房屋供应管道",
    agency_transactions: "代理行成交（28Hse／美联／中原）",
    hse28_new_projects: "28Hse 新盘目录",
    bd_monthly_digest: "屋宇署月报摘要",
    srpe_sales: "一手住宅物业销售资讯电子平台（SRPE）",
    shkp_financial_bridge: "新鸿基香港业务财务桥接",
    shkp_sales_handover_bridge: "新鸿基销售／交付／收入时序桥接",
  },
  snapshotBody: (artifact) =>
    `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。这是已发布快照，不是实时连接；RVD 标记为 provisional 的观测可能会修订。`,
  methodologyBody:
    "## 如何阅读本 dashboard\n\n不同发布方的指数基期不同。请在重设基准图中比较方向，不要直接比较原始数值水平。覆盖表区分实时指标、来源目录和计划中的采集工作。本 dashboard 不提供股票排名、预测或投资建议。",
  dataLabels: {
    shkp_hk_financial_bridge: {
      row_type: {
        official_disclosed_fact: "官方披露事实",
        hk_recurring_portfolio_fact: "香港 recurring portfolio 事实",
        financial_data_actual: "financial-data 实际值",
        consensus_snapshot: "共识快照",
        reconciliation: "对账",
        vintage_diagnostic: "PIT 诊断",
        coverage_diagnostic: "覆盖诊断",
        sales_handover_phase_summary: "销售／交付阶段摘要",
        sales_handover_annual_diagnostic: "销售／收入年度诊断",
      },
      geography: { group: "集团", hong_kong: "香港" },
      asset_class: {
        property_business: "地产业务",
        residential_development: "住宅开发",
        property_investment: "投资物业",
        company: "公司整体",
      },
    },
    hkma_mortgage_rate_mix: {
      series: {
        "HIBOR-based (%)": "H按 (HIBOR)",
        "Best Lending Rate (%)": "P按 (最优惠利率)",
        "Fixed-rate (%)": "定息按揭",
        "Other (%)": "其他",
        "HIBOR": "H按 (HIBOR)",
        "BLR (Prime)": "P按 (最优惠利率)",
        "Fixed": "定息按揭",
        "Other": "其他",
      },
    },
    hkma_credit_quality_history: {
      series: {
        "Delinquency Ratio (%)": "拖欠比率 (%)",
        "Rescheduled Loan Ratio (%)": "重订还款安排比率 (%)",
      },
    },
    landreg_asp_history: {
      series: {
        "All Building Units ASP": "全部楼宇单位 ASP",
        "Residential Units ASP": "住宅单位 ASP",
      },
    },
    bd_supply_pipeline: {
      region: BD_REGION_ZH,
      permit_stage: BD_PERMIT_STAGE_ZH,
    },
    bd_supply_detail: {
      region: BD_REGION_ZH,
      permit_stage: BD_PERMIT_STAGE_ZH,
      property_category: BD_PROPERTY_CATEGORY_ZH,
    },
    agency_transactions_pulse: {
      primary_source_agency: AGENCY_NAME_ZH,
    },
    rebased_five_year: {
      // CCL/MHPI are kept as their own index brand acronyms (matching
      // ccl_card/mhpi_card above, which don't translate them either); RVD's
      // two series are translated to match the RVD 价格/RVD 租金 wording
      // already used by rvd_price_card/rvd_rent_card on this same page.
      series: { "RVD Price": "RVD 价格", "RVD Rent": "RVD 租金" },
    },
    residential_price_rebased: {
      series: { CCL: "CCL", MHPI: "MHPI", CCI: "CCI", EPI: "EPI" },
    },
    residential_rent_rebased: {
      series: { CRI: "CRI", "RVD Rent": "RVD 租金", ERI: "ERI" },
    },
    csi_history: {
      series: { residential_price: "住宅价格情绪", residential_rental: "住宅租金情绪" },
    },
    rvd_office_history: {
      series: { "Grade A": "甲级", "Grade B": "乙级", "Grade C": "丙级", Overall: "整体" },
    },
    rvd_retail_history: {
      series: { "Rents Overall": "整体租金", "Prices Overall": "整体价格", Rents: "租金", Prices: "价格" },
    },
    censtatd_land_disposals_area: {
      series: { "Public Auction/Tender": "公开拍卖／招标", "Private Treaty Grant": "私人协约方式批地" },
    },
    source_health: {
      source: {
        "Sales of First-hand Residential Properties Electronic Platform (SRPE)": "一手住宅物业销售资讯电子平台（SRPE）",
      },
      dataset: {
        "SRPE phase-level first-hand sales signals": "SRPE 项目阶段一手住宅销售信号",
      },
      notes: {
        "Six explicitly registered phases; attributable sales use the ownership registry and sell-through uses unique active units.": "覆盖六个明确登记的项目阶段；可归属销售额使用持股登记表，销售率使用唯一有效成交单位。",
      },
    },
    source_coverage: {
      source: { "SRPE pilot": "SRPE 试点" },
      dataset: {
        "Phase-level first-hand sales signals": "项目阶段一手住宅销售信号",
        "Full developer / project coverage": "完整开发商／项目覆盖",
      },
      notes: {
        "Sales of First-hand Residential Properties Electronic Platform (SRPE); see the chart/table above.": "一手住宅物业销售资讯电子平台（SRPE）；详见上方图表及表格。",
        "The dashboard currently covers six explicit pilot phases; broader developer and phase coverage still requires registry expansion and backfill.": "目前 dashboard 覆盖六个明确登记的试点阶段；更广泛的开发商及项目阶段覆盖仍需扩展登记表和历史回补。",
      },
    },
    srpe_developer_monthly_sales: {
      developer: {
        "Henderson Land": "恒基兆业地产",
        "Sun Hung Kai Properties": "新鸿基地产",
        "New World Development": "新世界发展",
        "MTR Corporation": "香港铁路",
        "Sino Land": "信和置业",
      },
    },
    srpe_project_sell_through: {
      developer: {
        "Henderson Land": "恒基兆业地产",
        "Sun Hung Kai Properties": "新鸿基地产",
        "New World Development": "新世界发展",
        "MTR Corporation": "香港铁路",
        "Sino Land": "信和置业",
      },
      project_name: {
        "Grand Victoria — Phase 1": "维港滙 — 第一期",
        "NOVO LAND — Phase 2A": "NOVO LAND — 第2A期",
        "NOVO LAND — Phase 3B": "NOVO LAND — 第3B期",
        "PARK YOHO NAPOLI": "峻峦 Napoli",
        "The Henley II": "The Henley II",
        "PAVILIA FARM III": "柏傲庄 III",
        "Blue Coast": "扬海 Blue Coast",
      },
      project_short_name: {
        "NOVO 2A": "NOVO 第2A期",
        "NOVO 3B": "NOVO 第3B期",
        "PARK YOHO": "峻峦",
      },
    },
    srpe_latest_project_snapshot: {
      developer: {
        "Henderson Land": "恒基兆业地产",
        "Sun Hung Kai Properties": "新鸿基地产",
        "New World Development": "新世界发展",
        "MTR Corporation": "香港铁路",
        "Sino Land": "信和置业",
      },
      project_name: {
        "Grand Victoria — Phase 1": "维港滙 — 第一期",
        "NOVO LAND — Phase 2A": "NOVO LAND — 第2A期",
        "NOVO LAND — Phase 3B": "NOVO LAND — 第3B期",
        "PARK YOHO NAPOLI": "峻峦 Napoli",
        "The Henley II": "The Henley II",
        "PAVILIA FARM III": "柏傲庄 III",
        "Blue Coast": "扬海 Blue Coast",
      },
    },
  },
};

const HK_LOCAL_CONSUMER_ZH = {
  title: "香港本地消费监测",
  description: "极端天气干扰时长、港元/人民币汇率、跨境出入境人流（北上/南下）、黄金原料成本、零售销售、餐饮收益及消费股估值的来源快照。",
  blocks: {
    demand_signals_section: "## 消费需求信号\n\n跨境旅客流量为主打需求信号；天气为影响人流的控制变量。",
    prices_inflation_section: "## 物价与通胀\n\n综合消费物价指数（总体及分类）、汽车燃油、黄金及超市价格监察指数。",
    retail_fnb_section: "## 零售与餐饮活动\n\n官方零售销售及餐饮收益数据、各区持牌食肆密度及店铺足迹追踪。",
    complaints_section: "## 消费者投诉\n\n消费者委员会各类别投诉宗数。",
    valuations_section: "## 消费股估值\n\n消费观察名单市盈率、市净率及市值——仅供参考，不构成股票排名或投资建议。",
    sources_methodology_section: "## 数据来源与方法",
  },
  cards: {
    northbound_card: { description: "每日经陆路口岸（不含机场及邮轮/渡轮码头）出境的香港居民人次（7日移动平均）；日环比与同比变动。", metricLabels: ["北上7日均值（陆路口岸）", "日环比", "同比"] },
    southbound_card: { description: "每日内地访客入境人次（7日移动平均）；日环比与同比变动。", metricLabels: ["南下7日均值", "日环比", "同比"] },
    weather_card: { description: "月度八号及以上风球与红/黑色暴雨警告总持续时长；同比变动。", metricLabels: ["极端天气干扰 (小时/月)", "同比"] },
    fx_card: { description: "基于 FRED 每日报价计算的月度平均港元/人民币交叉汇率；月环比与同比变动。", metricLabels: ["人民币 / 100 港元", "月环比", "同比"] },
    gold_card: { description: "上海黄金交易所 PM 基准定盘价（人民币/克）；日环比与同比变动。", metricLabels: ["黄金 PM 基准价 (人民币/克)", "日环比", "同比"] },
    median_pe_card: { description: "本地消费观察名单各公司历史市盈率的中位数。", metricLabels: ["市盈率中位数 (TTM)"] },
    retail_card: { description: "政府统计处零售销售价值指数（全部零售店铺）；月环比与同比变动。", metricLabels: ["零售销售指数", "月环比", "同比"] },
    cpi_card: { description: "综合消费物价指数（2019/20年基期＝100）；月环比与同比变动。", metricLabels: ["综合消费物价指数", "月环比", "同比"] },
    fehd_card: { description: "食物环境卫生署最新食肆牌照名录快照：全港持牌食肆（普通食肆／小食食肆／海上食肆）总数。", metricLabels: ["持牌食肆总数"] },
    restaurant_card: { description: "全行业季度餐饮收益（百万港元）；季环比与同比变动。", metricLabels: ["餐饮收益 (百万港元)", "季环比", "同比"] },
    store_footprint_card: { description: "11家香港上市零售、珠宝、餐饮及消费品公司的门店/网点数量追踪总数。", metricLabels: ["已追踪网点总数"] },
  },
  charts: {
    severe_weather_trend: ["月度极端天气干扰时长 (小时)", "按月汇总的八号及以上热带气旋警告与红/黑色暴雨警告持续时间；图表默认显示可用历史中的最近十年。", "月份", "小时"],
    immigration_trend: ["跨境旅客流量 (7日移动平均)", "入境事务处发布的每日客流：北上为香港居民经陆路口岸出境，南下为内地访客经全部口岸入境；图表默认显示可用历史中的最近十年。", "日期", "人次/日 (7日均值)", "流向"],
    gold_trend: ["上海黄金交易所 PM 基准价（毛利成本参考）", "人民币/克每日定盘价；图表默认显示可用历史中的最近十年（若数据不足十年则显示全部），作为香港金饰原料成本的辅助参考。", "日期", "人民币 / 克"],
    valuation_pe_chart: ["观察名单历史市盈率对比", "各公司最新的正值历史市盈率；亏损公司不计入此视图。", "公司", "市盈率 (TTM)"],
    retail_trend: ["零售销售价值指数（全部店铺）", "政府统计处月度价值指数，完整已发布历史。", "月份", "价值指数"],
    cpi_trend: ["综合消费物价指数", "月度综合消费物价指数（2019/20年基期＝100），1974年10月至今完整已发布历史。", "月份", "指数 (2019/20＝100)"],
    cpi_by_category_chart: ["消费物价指数按类别 — 食品、房屋与交通", "2005年至今的月度分类指数（历史长度较综合指数短）。", "月份", "指数 (2019/20＝100)", "类别"],
    fehd_district_chart: ["各区持牌食肆数目", "食环署今日食肆牌照名录快照；已合并全部牌照类型。", "地区", "持牌食肆数目"],
    retail_category_chart: ["零售销售价值指数按类别", "最新发布月份，按零售店铺类型划分。", "类别", "价值指数"],
    restaurant_trend: ["餐饮收益（全部食肆）", "季度全行业收益，百万港元，完整已发布历史。", "季度", "百万港元"],
    restaurant_chart: ["餐饮收益按类型", "最新发布季度，百万港元。", "食肆类型", "百万港元"],
    store_footprint_chart: ["各公司追踪门店/网点数量", "各公司最新的门店足迹快照（各公司单位不直接可比，详见备注）。", "公司", "门店总数"],
    consumer_council_oilprice_chart: ["各大油公司现金折扣对比 (港元/升)", "美孚、中石油、壳牌、中石化及埃索的每升现金折扣。", "油公司", "折扣 (港元/升)"],
    consumer_council_oilprice_net_chart: ["各大油公司实际油价对比 (港元/升)", "同日美孚、中石油、壳牌、中石化及埃索的每升实际油价。", "油公司", "实际油价 (港元/升)"],
    consumer_council_oilprice_history_chart: ["普通汽油实际油价走势", "现金折扣后的每日普通汽油实际油价（不含燃油税）；图表默认显示可用历史中的最近十年。", "月份", "港元 / 升（不含税）", "油公司"],
    consumer_council_complaints_chart: ["消费者委员会投诉类别排行", "最新一期十大投诉类别（按投诉宗数）。", "类别", "投诉宗数"],
    consumer_council_complaints_history_chart: ["消费者委员会投诉类别历史", "每个已发布期间的投诉类别历史；只使用官方提供的期间值，不推算同比。", "发布期间", "投诉宗数", "类别"],
    valuation_market_cap_trend: ["消费观察名单市值走势", "来源提供的每日市值观察；图表默认显示可用历史中的最近十年。", "日期", "市值（十亿港元）", "公司"],
    immigration_checkpoint_trend: ["主要出入境管制站客流走势", "按最新 7 日平均客流选出的五个管制站/方向；图表默认显示可用历史中的最近十年。", "日期", "人次（7 日均值）", "管制站 / 方向"],
    severe_weather_daily_trend: ["每日极端天气干扰时长", "按警告时段跨午夜拆分后的每日持续时长；图表默认显示可用历史中的最近十年。", "月份", "小时", "警告类型"],
  },
  tables: {
    severe_weather_log_table: {
      title: "近期极端天气警告事件记录",
      subtitle: "近期红/黑色暴雨警告及八号或以上热带气旋警告的开始时间、结束时间及持续时长。",
      columns: { signal_name: "警告信号", start: "开始时间 (HKT)", end: "结束时间 (HKT)", duration_hours: "持续时长 (小时)" },
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
    active_signals_table: {
      title: "已跟踪数据信号",
      subtitle: "已有实时、经校验数据支撑上方卡片/图表/表格的来源。",
      columns: { source: "来源", dataset: "数据集", type: "类型", status: "状态", freshness: "新鲜度", notes: "范围 / 限制" },
    },
    coverage_table: {
      title: "覆盖范围与下一步采集目标",
      subtitle: "端点存在问题或未经验证的来源在此追踪，而非以占位值展示。",
      columns: { source: "来源", dataset: "数据集", type: "类型", status: "状态", freshness: "新鲜度", notes: "范围 / 限制" },
    },
    store_footprint_table: {
      title: "香港零售/餐饮门店数量快照",
      subtitle: "各公司最新追踪的门店/网点数量——门店足迹快照，尚未构成趋势（大部分公司目前仅有1-2个存有日期的快照）。",
      columns: {
        company: "公司",
        stock_code: "股票代码",
        sector: "行业",
        total_stores: "门店总数",
        regions_tracked: "追踪地区/市场数",
        snapshot_date: "快照日期",
      },
    },
    consumer_council_oilprice_table: {
      title: "消委会油价计算机 — 油价及折扣",
      subtitle: "香港各大油公司每日油价、现金折扣及实际油价（每升）。",
      columns: {
        company: "油公司",
        fuel_type: "油品",
        walkin_discount_hkd: "现金折扣 (港元/升)",
        discounted_price_hkd: "实际油价 (港元/升)",
      },
    },
    consumer_council_oilprice_wow_table: {
      title: "汽车燃油实际油价 — 近7日变动",
      subtitle: "扣除现金折扣及不含燃油税的每日实际油价，与七个日历日前比较。",
      columns: {
        company: "油公司",
        fuel_type: "油品",
        net_price_ex_duty_hkd: "实际油价 (港元/升，不含燃油税)",
        wow_change: "7日变动 (%)",
        date: "数据日期",
      },
    },
    consumer_council_complaints_history_table: {
      title: "消费者委员会投诉类别 — 全部可得期间",
      subtitle: "官方 API 提供的每个类别及期间数据；2026年数据不视为全年总数。",
      columns: { period: "期间", category: "类别", amount: "投诉宗数" },
    },
    immigration_checkpoint_table: {
      title: "出入境管制站明细",
      subtitle: "最新日期的旅客通关量，按管制站及方向划分。",
      columns: {
        control_point: "管制站",
        direction: "方向",
        hk_residents: "香港居民",
        mainland_visitors: "内地访客",
        other_visitors: "其他访客",
        total: "总计",
      },
    },
  },
  sources: {
    sge_gold: "上海黄金交易所 AM/PM 基准价",
    hk_valuation: "百度股市通香港股票估值",
    cnsd_retail: "政府统计处零售销售价值/销量指数",
    censtatd_cpi: "政府统计处综合消费物价指数",
    fehd_licensed_premises: "食物环境卫生署持牌食肆名录",
    censtatd_restaurant: "政府统计处季度餐饮收益及采购调查",
    immigration_flow: "入境事务处每日出入境旅客流量统计",
    weather_demand_drivers: "香港天文台警告数据库 & FRED 汇率",
    source_registry: "香港本地消费 dashboard 来源登记表",
    hk_store_footprint: "香港零售/餐饮店铺数量抓取器",
    consumer_council_oilprice: "消费者委员会油价计算机",
    consumer_council_complaints: "消费者委员会投诉数据接口",
  },
  snapshotBody: (artifact) =>
    `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody:
    "## 如何阅读本 dashboard\n\n跨境人流（北上/南下）为本 dashboard 主打的消费需求信号。黄金为金饰原料成本的辅助参考。本界面整合物理天气干扰、汇率环境、出入境流量、零售金价溢价、零售销售、餐饮收益、综合消费物价指数与消费股估值等代理指标，以评估香港本地零售与餐饮业的宏观受压情况。「已跟踪数据信号」列出已有实时数据支撑的来源；「覆盖范围与下一步采集目标」追踪端点仍存在问题或未经验证的来源。",
  dataLabels: {
    immigration_trend_history: { flow_type: { Northbound: "北上", Southbound: "南下" } },
    retail_category_snapshot: { category: RETAIL_CATEGORY_ZH },
    retail_category_chart: { category: RETAIL_CATEGORY_ZH },
    restaurant_snapshot: { sub_sector: RESTAURANT_SUBSECTOR_ZH },
    restaurant_chart: { sub_sector: RESTAURANT_SUBSECTOR_ZH },
    severe_weather_log: { signal_name: translateHkoSignalName },
    consumer_council_oilprice: { fuel_type: FUEL_TYPE_ZH },
    consumer_council_complaints: { category: CONSUMER_COMPLAINT_CATEGORY_ZH },
    consumer_council_complaints_chart: { category: CONSUMER_COMPLAINT_CATEGORY_ZH },
    consumer_council_complaints_history_chart: { category: CONSUMER_COMPLAINT_CATEGORY_ZH },
    immigration_checkpoint_snapshot: { control_point: CONTROL_POINT_ZH, direction: DIRECTION_ZH },
    censtatd_cpi_by_category_history: {
      series: {
        "Food and non-alcoholic beverages": "食品及非酒精饮品",
        "Housing, water, electricity, gas and other fuels": "房屋、水电煤及其他燃料",
        Food: "食品及非酒精饮品",
        "Housing & Utilities": "房屋、水电煤及其他燃料",
        "Transport": "交通",
      },
    },
    fehd_district_density: { district_name: FEHD_DISTRICT_ZH },
  },
};

const HK_UTILITIES_ZH = {
  title: "香港公用事业与基础设施监测",
  description: "中电控股（CLP）季度售电量拆解、中华煤气（Towngas）代理数据、香港天文台日均气温、电能实业（Power Assets）分部业绩、渠务署污水流量/实验室数据及水务署停水通告。",
  cards: {
    clp_card: { description: "季度中电香港本地售电总量、商业售电量及 AI 数据中心用电同比变动。", metricLabels: ["总售电量 (GWh)", "商业售电量 (GWh)", "AI 数据中心同比"] },
    towngas_card: { description: "政府统计处月度全港煤气消费总量，按住宅及商业用户拆解。", metricLabels: ["总耗气量 (TJ)", "住宅耗气量 (TJ)", "商业耗气量 (TJ)"] },
    temp_card: { description: "香港天文台录得的最新日均气温及月度平均气温。", metricLabels: ["最新气温 (°C)", "月均气温 (°C)"] },
    power_assets_card: { description: "电能实业半年度分部收入、分部溢利及合资/联营业绩总额。", metricLabels: ["总分部收入 (百万港元)", "总分部溢利 (百万港元)", "合资/联营业绩 (百万港元)"] },
    water_suspension_card: { description: "水务署当前计划及紧急停水事件资料。", metricLabels: ["目前通告", "资料行数", "近七日紧急通告"] },
  },
  charts: {
    clp_sector_chart: ["中电香港售电量按行业拆解 (GWh)", "季度售电量拆解为住宅、商业、基础设施与公共服务及制造行业。", "季度", "售电量 (GWh)"],
    towngas_trend_chart: ["香港煤气消费量走势 (TJ)", "月度全港煤气消费总量拆解为住宅、商业及工业用户；图表默认显示可用历史中的最近十年。", "月份", "太焦耳 (TJ)"],
    temp_trend_chart: ["香港天文台月均气温走势 (°C)", "按香港天文台每日平均气温计算的月度平均；图表默认显示可用历史中的最近十年，日频来源数据在数据层保留。", "月份", "°C"],
    sewage_flow_chart: ["各污水处理厂报告污水流量（月度总和）", "按每月可用污水处理厂汇总每日最终排放流量；来源仍为日度，覆盖会随时间改变，按厂历史仍保留在数据集中。", "月份", "报告每日流量 (立方米/日)"],
  },
  tables: {
    power_assets_geography_table: {
      title: "电能实业（Power Assets）按地理区域划分的分部业绩",
      subtitle: "半年度分部财务数据（2025 上半年），百万港元；「港灯投资」按权益法入账，在本注释下的收入/分部溢利列示为零，其贡献计入合资/联营业绩一栏。",
      columns: { summary: "地理分部摘要" },
    },
    sewage_latest_lab_table: {
      title: "各污水处理厂最新流量及实验室观测",
      subtitle: "每间污水处理厂的最新可用记录；表内展示核心实验室字段，其他来源稀疏字段仍保留在数据集中，不作填补。",
      columns: { summary: "污水处理厂及最新指标" },
    },
    water_suspension_events_table: {
      title: "当前停水通告",
      subtitle: "水务署当前计划/紧急停水通告，包括未来已排期事件；表内展示核心时间及状态，地址和原因仍保留在数据集中。这是事件快照，不是用水消费时间序列。",
      columns: { summary: "通告摘要" },
    },
  },
  sources: {
    clp_electricity: "中电控股（0002.HK）业绩公告及售电量披露",
    towngas_proxy: "政府统计处能源统计（煤气消费量）",
    hko_temperature: "香港天文台每日平均气温",
    power_assets_segments: "电能实业（0006.HK）中期及全年业绩报告",
    dsd_sewage_flow_lab: "渠务署每日污水流量及排放水实验室数据",
    wsd_water_suspension: "水务署当前停水通告",
  },
  snapshotBody: (artifact) => `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody: "## 如何阅读本 dashboard\n\n售电量与燃气消费量反映香港公用事业核心业务运营水平；日均气温为夏日用电负荷的物理驱动因素。渠务署污水数据保留日度流量和来源稀疏的最终排放实验室字段，各污水处理厂的覆盖期可能不同。水务署通告是每五分钟更新的当前事件快照，包含计划中的未来停水，不应解读为连续用水消费指标。",
  dataLabels: {
    power_assets_geography: {
      geography: {
        "Investment in HKEI": "港灯投资",
        "United Kingdom": "英国",
        Australia: "澳洲",
        Others: "其他地区",
      },
    },
    clp_sector_history: {
      series: {
        Residential: "住宅",
        Commercial: "商业",
        "Infra & Public": "基础设施及公共服务",
        Manufacturing: "制造业",
      },
    },
    towngas_type_history: {
      series: { Domestic: "住宅", Commercial: "商业", Industrial: "工业" },
    },
    water_suspension_events: {
      water_type: { "Fresh Water": "食水", "Salt Water": "鹹水", "Fresh And Salt Water": "食水及鹹水" },
      nature: { Planned: "计划", Emergency: "紧急" },
      status: { "Supply resumed": "供水已恢复", "Supply being suspended": "供水暂停中", "Suspension not yet started": "停水尚未开始" },
    },
  },
};

const TRANSPORT_DISTRICT_ZH = {
  "CENTRAL & WESTERN": "中西区",
  EASTERN: "东区",
  ISLANDS: "离岛区",
  "KOWLOON CITY": "九龙城区",
  "KWAI TSING": "葵青区",
  "KWUN TONG": "观塘区",
  NORTH: "北区",
  "SAI KUNG": "西贡区",
  "SHA TIN": "沙田区",
  "SHAM SHUI PO": "深水埗区",
  SOUTHERN: "南区",
  "TAI PO": "大埔区",
  "TSUEN WAN": "荃湾区",
  "TUEN MUN": "屯门区",
  "WAN CHAI": "湾仔区",
  "WONG TAI SIN": "黄大仙区",
  "YAU TSIM MONG": "油尖旺区",
  "YUEN LONG": "元朗区",
};
const TRANSPORT_SUMMARY_ZH = {
  "MTR Local": "港铁本地",
  "MTR Airport / LRT / feeder": "港铁机场／轻铁／接驳",
  "Franchised buses": "专营巴士",
  Aircraft: "飞机",
  "Passenger vehicles": "客运车辆",
  "Goods vehicles": "货运车辆",
};
// TRANSPORT_DISTRICT_ZH's keys are upper-case, but upstream Python sources
// disagree on district-name casing (e.g. td_carpark_occupancy_latest_district
// emits "SHA TIN" while hk_parking_current_district emits "Sha Tin") -- a
// case-insensitive lookup keeps both working instead of only whichever
// dataset happens to match the dict's literal casing.
function districtZh(name) {
  return TRANSPORT_DISTRICT_ZH[String(name).toUpperCase()] || name;
}
function translateTransportLatestSummary(value) {
  if (typeof value !== "string") return value;
  let match = /^(.*?): ([\d,.]+) thousand journeys \((\d{4}-\d{2})\)$/.exec(value);
  if (match) return `${TRANSPORT_SUMMARY_ZH[match[1]] || match[1]}：${match[2]} 千人次（${match[3]}）`;
  match = /^(.*?): ([\d,.]+) movements \((\d{4}-\d{2})\)(; provisional estimate)?$/.exec(value);
  if (match) {
    const estimate = match[4] ? "；临时估计" : "";
    return `${TRANSPORT_SUMMARY_ZH[match[1]] || match[1]}：${match[2]} 移动次数（${match[3]}）${estimate}`;
  }
  match = /^(.*?): ([\d.]+)% occupied \((\d+) observed metered spaces\)$/.exec(value);
  if (match) {
    return `${districtZh(match[1])}：${match[2]}% 占用（${match[3]} 个已观测计量车位）`;
  }
  match = /^(.*?): ([\d,]+) exact vacant spaces across (\d+) car parks$/.exec(value);
  if (match) {
    return `${districtZh(match[1])}：${match[2]} 个确切空置车位（共 ${match[3]} 个停车场）`;
  }
  return value;
}

const HK_TRANSPORT_ZH = {
  title: "香港交通与航空监测",
  description: "港铁月度客运量（本地/跨境/高铁）、国泰航空及香港国际机场流量、六家中国上市航空公司客运与货运运营数据、运输署公共交通/私家车/电动车登记、C&SD跨境移动及传感器停车位占用率数据。",
  cards: {
    mtr_card: { description: "港铁月度总客运量，按本地及跨境服务拆解，并附对比 2019 年月均水平的复苏率。", metricLabels: ["总客运量 (千人次)", "本地 (千人次)", "跨境 (千人次)", "较 2019 年均值"] },
    cathay_card: { description: "国泰集团月度载客人数、载客率及香港国际机场客运量，并附对比 2019 年月均水平的复苏率。", metricLabels: ["国泰乘客人数", "载客率 (%)", "机场乘客人数", "较 2019 年均值"] },
    journeys_card: { description: "九巴（运输国际，00062.HK）月度载客人次，以及涵盖各交通模式的全港公共交通总客运量。", metricLabels: ["九巴 (千人次)", "全港合计 (千人次)", "总量按月变动"] },
    fleet_card: { description: "私家车车队存量及电动车占登记车队的比例。", metricLabels: ["登记私家车数目", "电动车占比", "电动车占比变动 (百分点)"] },
    net_growth_card: { description: "私家车月度首次登记净额：首次登记总数减运输署报告的累计取消登记数。", metricLabels: ["首次登记总数", "取消登记数", "首次登记净额"] },
    private_car_first_reg_card: { description: "按厂名及燃料类型划分的私家车月度首次登记；电动车占比是当月流量占比，不是累计车队占比。", metricLabels: ["私家车首次登记", "电动车首次登记", "当月电动车占比"] },
    parking_card: { description: "运输署实时停车场空置快照；只把能提供确切数字的车场计入空置车位总数。", metricLabels: ["确切空置车位", "有确切数字的车场", "数据源车场数"] },
    carpark_occupancy_card: { description: "对运输署传感器计量停车位计算的观测占用率；底层列示空间清单作为分母，无法匹配状态的空间不会计入。", metricLabels: ["占用率", "有状态空间", "列出空间"] },
  },
  charts: {
    mtr_total_patronage_chart: ["港铁总客运量走势 (2000年至今，千人次)", "26 年月度港铁总客运量数据，完整呈现 2003 年沙士（SARS）冲击（2003 年 4 月低点约 4,880 万人次）及更深、更持久的 2019-22 新冠疫情冲击（2022 年 2 月低点约 7,190 万人次），其后复苏至接近 2019 年疫情前月均水平。", "月份", "千人次"],
    mtr_service_breakdown_chart: ["港铁客运量按服务类型走势（最近十年，千人次）", "本地重铁、跨境、高铁、机场快线及轻铁与巴士的月度乘客人次；图表默认显示可用历史中的最近十年（若数据不足十年则显示全部）。完整总量历史见上图。", "月份", "千人次"],
    cathay_passengers_chart: ["国泰集团载客人数走势 (2012年至今)", "13 年月度国泰集团载客人数，呈现新冠疫情期间近乎归零的冲击（由 2018 年 8 月约 328 万人次高点跌至 2020 年 4 月约 1.37 万人次低点，跌幅逾 99.5%）及其后的多年复苏。", "月份", "乘客人数"],
    cathay_load_factor_chart: ["国泰集团载客率走势 (%)", "月度载客率——相较于原始载客人数，更能反映国泰自身运力利用率与定价能力，因其已扣除国泰当时投放的运力规模。", "月份", "载客率 (%)"],
    cathay_capacity_demand_chart: ["国泰集团运力与需求对比 (ASK 对比 RPK，千单位)", "可用座位公里（投放运力）与收益乘客公里（实际填补需求）对比——两线差距与旁边载客率图表互为镜像。", "月份", "千单位"],
    cathay_cargo_tonnage_chart: ["国泰货运量走势", "国泰航空月度货物载运量，来自国泰交通数据公告；香港国际机场全港货运量仍是另一条独立序列。", "月份", "吨"],
    cathay_freight_load_factor_chart: ["国泰货运载运率走势", "国泰航空月度货运载运率；旧报告中的 cargo/mail 字段已按同一概念标准化。", "月份", "货运载运率 (%)"],
    cathay_cargo_capacity_demand_chart: ["国泰货运运力与需求对比 (AFTK 对比 RFTK，千单位)", "可用货运吨公里（AFTK）与收益货运吨公里（RFTK）对比；旧报告中的 cargo/mail 表述已保留为同一指标口径。", "月份", "千单位"],
    cathay_flight_sectors_chart: ["国泰报告航班架次／航段", "国泰月度公告中的航班架次／航段；较早报告使用合计航班数，较新报告将客运与货运航段拆开后再合计，未进行月度补值。", "月份", "航班架次／航段"],
    cathay_fleet_total_chart: ["国泰集团机队规模", "国泰年报及中期报告 Fleet Profile 的期末机队总数，按公司、香港快运、国泰航空货运（Air Hong Kong）及集团合计展示；这是半年／年度序列，不插值成月度数据。", "报告期", "架"],
    hkia_passengers_chart: ["香港国际机场总客运量走势", "香港国际机场（民航处数据）全部航空公司合计的月度总客运量，较国泰专属图表更能反映航空需求的整体水平。", "月份", "乘客人数"],
    china_airline_passengers_chart: ["六家中国上市航空公司客运量走势", "中国国航、南方航空、东方航空、春秋航空、海航控股及吉祥航空月度载客人次。数据按各公司公告披露的集团/合并运营口径。", "月份", "乘客人数"],
    china_airline_ask_chart: ["中国上市航空公司可用座位公里 (ASK)", "各航空公司月度可用座位公里（投放运力）。", "月份", "千单位"],
    china_airline_rpk_chart: ["中国上市航空公司收入乘客公里 (RPK)", "各航空公司月度收入乘客公里（实际填补需求）。", "月份", "千单位"],
    china_airline_load_factor_chart: ["中国上市航空公司载客率走势", "各航空公司月度载客率，按公司整体运营口径计算。", "月份", "%"],
    china_airline_region_split_chart: ["中国上市航空公司客运量按地区拆分", "六家航空公司合计客运量，按国内、国际及地区航线拆分；各公司分项数值见下方最新运营数据表。", "月份", "乘客人数"],
    china_airline_region_by_carrier_chart: ["中国上市航空公司客运量按航空公司及地区拆分", "按航空公司查看最近九年的月度国内、国际及地区航线客运量；来源留空保持缺失，明确横线则保留为零。", "月份", "乘客人数"],
    china_airline_cargo_chart: ["中国上市航空公司货邮运量走势", "六家上市航空公司月度货物及邮件数量，统一换算为吨；不同公司公告的货运合并口径可能略有差异。", "月份", "吨"],
    china_airline_freight_load_factor_chart: ["中国上市航空公司货邮载运率走势", "各公司月度货邮载运率；若官方公告同时披露 RFTK/AFTK，则优先使用公告合计值，否则按统一单位计算。官方源数据超过 100% 的观测保留并视为异常，不作截断。", "月份", "%"],
    china_airline_fleet_total_chart: ["中国上市航空公司机队规模", "月度运营数据公告明确披露的机队总数；没有披露的月份不使用插值填补。", "月份", "架"],
    china_airline_fleet_net_change_chart: ["中国上市航空公司机队月度净变化", "公告披露的引进飞机数减退出／退租飞机数；没有事件公告的月份不自动填零。", "月份", "净增飞机"],
    china_airline_new_route_chart: ["中国上市航空公司新航线事件", "从官方月度公告正文识别的新航线事件月度数量；具体航线文字保留在下方最新事件表。", "月份", "航线事件数"],
    airline_h1_revenue_mae_chart: ["1H KPI 校准 — 收入 MAE", "flat-ASK 校准的收入绝对误差；比较原始数据与官方源恢复加研究插值层。数值越低越好。", "航空公司", "收入 MAE (%)"],
    airline_h1_cost_mae_chart: ["1H KPI 校准 — 经营成本 MAE", "flat-ASK 校准的经营成本绝对误差；比较原始数据与官方源恢复加研究插值层。数值越低越好。", "航空公司", "经营成本 MAE (%)"],
    airline_period_revenue_mae_chart: ["航司 H1 / H2 / FY KPI 校准 — 收入 MAE", "按航空公司及报告期间显示严格来源恢复层的 flat-RPK 收入绝对误差；H2 财务实际值由 FY 减 H1 推导，数值越低越好。", "航空公司", "收入 MAE (%)"],
    airline_source_recovery_chart: ["航司 KPI 来源恢复审计", "比较从缓存官方 PDF 恢复的行数，以及确认源 PDF 未披露的行数。", "审计状态", "行数"],
    airline_h1_revenue_nowcast_chart: ["2026 年上半年收入预测 — 春秋／吉祥", "flat-ASK 基准与分析师对收益率、燃油及非燃油成本调整后的 overlay，单位为百万美元；这是财报前预测，不是实际值。", "航空公司", "收入（百万美元）"],
    airline_h1_profit_nowcast_chart: ["2026 年上半年利润预测 — 春秋／吉祥", "flat-ASK 基准与分析师 overlay，单位为百万美元；正式中报发布后用于对比。", "航空公司", "利润（百万美元）"],
    hk_total_transport_journeys_chart: ["香港公共交通乘客人次——全部交通模式 (千人次)", "全港月度乘客人次，涵盖专营巴士、港铁（重铁、机场快线、轻铁）、香港电车、公共小巴、渡轮及的士。", "月份", "千人次"],
    hk_modal_split_chart: ["香港公共交通乘客人次按交通模式拆分 (千人次)", "专营巴士、铁路（港铁重铁 + 机场快线 + 轻铁 + 电车合计）、公共小巴、渡轮及的士。", "月份", "千人次"],
    hk_franchised_bus_operator_chart: ["香港专营巴士乘客人次按营办商拆分 (千人次)", "九巴（运输国际，00062.HK）、城巴、龙运及新大屿山巴士。新巴并入城巴申报后不再单独列示。", "月份", "千人次"],
    hk_private_car_fleet_ev_share_chart: ["香港私家车车队电动车占比", "电动车占累计登记私家车车队的比例，是车队存量/采用率指标，与下方每月首次登记流量占比不同。", "月份", "电动车占比 (%)"],
    hk_private_car_net_growth_chart: ["香港私家车车队净增长", "月度首次登记净额（首次登记总数减任何原因的取消登记数）——即车队每月净增加量。", "月份", "净新登记数"],
    hk_private_car_ev_make_chart: ["香港私家车电动车首次登记按厂名走势", "月度电动车私家车首次登记：比亚迪、Tesla 及其他电动车厂名合计；这是登记流量，不是累计车队存量。", "月份", "首次登记数"],
    hk_private_car_ev_share_chart: ["每月私家车首次登记中的电动车占比", "每月电动车首次登记数除以全部私家车首次登记数；与上方累计登记车队中的电动车占比不同。", "月份", "电动车占比 (%)"],
    hk_parking_vacancy_history_chart: ["实时停车位空置——确切空置车位", "按参与的私家车小时停车场数据汇总；只有重复采集形成历史后才显示，无法提供确切数字的空置类型不会计入总数。", "时间", "确切空置车位"],
    mttd_passenger_journeys_chart: ["运输署月报表 2.3 乘客人次 (千人次)", "运输署月报表中的港铁本地、港铁机场/轻铁/接驳及专营巴士月度乘客人次；表 2.3 是对上方表 2.1 综合模式总量的另一组营运商/地区拆解。", "月份", "千人次"],
    censtatd_boundary_movements_chart: ["香港跨境移动——C&SD 表 E705", "月度飞机、客运车辆及货运车辆进出境架/辆次；最新 C&SD 单元可能是临时估计，完整 E705 数据另保留船只及客运火车。", "月份", "移动次数"],
    td_carpark_occupancy_chart: ["运输署传感器停车位占用率", "仅使用运输署传感器计量停车位的占用状态及空间清单计算观测占用率；重复轮询后才显示历史，未匹配的状态不会计入分母。", "时间", "占用率 (%)"],
  },
  tables: {
    china_airline_latest_snapshot_table: {
      title: "中国上市航空公司最新运营数据",
      subtitle: "最新可得月份数据，按航空公司及运营地区拆分；“口径”说明公告是集团合并或公司及子公司口径。",
      columns: {
        airline: "航空公司",
        reporting_scope: "披露口径",
        region: "运营地区",
        passengers: "乘客人次（千）",
        ask: "可用座位公里（千）",
        rpk: "收入乘客公里（千）",
        load_factor_pct: "载客率 (%)",
      },
    },
    china_airline_cargo_latest_snapshot_table: {
      title: "中国上市航空公司最新货运数据",
      subtitle: "最新可得月份的货邮量、货运运力/周转量及载运率；单位已按公司公告换算并保留来源异常值。",
      columns: {
        airline: "航空公司",
        reporting_scope: "披露口径",
        cargo_tonnes: "货物／邮件（吨）",
        aftk: "AFTK（百万吨公里）",
        rftk: "RFTK（百万吨公里）",
        freight_load_factor_pct: "货邮载运率 (%)",
        overall_load_factor_pct: "综合载运率 (%)",
      },
    },
    china_airline_operating_events_latest_table: {
      title: "中国上市航空公司最新机队／航线事件",
      subtitle: "最新月度公告中识别出的机队及新航线事件；保留来源摘要，不将事件误读为连续运营序列。",
      columns: {
        airline: "航空公司",
        reporting_scope: "披露口径",
        event_type: "事件类型",
        value: "数值",
        detail: "来源摘要",
      },
    },
    airline_h1_backtest_summary_table: {
      title: "1H KPI 校准摘要",
      subtitle: "官方源恢复加研究插值层的校准结果；收入／成本误差为绝对 MAE，未来插值行不适用于点时财报事件交易。",
      columns: {
        carrier: "航空公司",
        ticker: "代码",
        historical_rows: "评估行数",
        revenue_mae_pct: "收入 MAE (%)",
        cost_mae_pct: "成本 MAE (%)",
        profit_direction_accuracy: "利润方向准确率",
        imputation_rows: "使用插值行数",
        future_imputation_rows: "未来插值行数",
        pit_safe_rows: "PIT 安全行数",
      },
    },
    airline_period_backtest_summary_table: {
      title: "航司 H1 / H2 / FY KPI 校准摘要",
      subtitle: "严格来源恢复校准，并单独显示逻辑假设覆盖；H2 财务实际值由 FY 减 H1 推导。这是校准证据，不是严格的点时交易回测。",
      columns: {
        carrier: "航空公司",
        period: "期间",
        historical_evaluated_rows: "严格评估行数",
        pit_safe_evaluated_rows: "PIT 安全行数",
        logical_assumption_rows: "逻辑假设行数",
        flat_ask_revenue_mae_pct: "Flat-ASK 收入 MAE (%)",
        flat_rpk_revenue_mae_pct: "Flat-RPK 收入 MAE (%)",
        recovery_case_revenue_mae_pct: "春秋 recovery-case MAE (%)",
        flat_ask_cost_mae_pct: "Flat-ASK 成本 MAE (%)",
      },
    },
    airline_source_recovery_audit_table: {
      title: "航司 KPI 来源恢复审计明细",
      subtitle: "官方 PDF 恢复行与确认未披露行；月度运营图表使用来源恢复层，本表记录覆盖证据。",
      columns: {
        status: "状态",
        airline_code: "航司代码",
        month: "月份",
        metric: "指标",
        region: "地区",
        value: "数值",
        recovery_method: "恢复方法",
        reason: "原因",
        announcement_date: "公告日期",
        source_pdf_url: "官方 PDF",
        companion_parser_metrics: "解析器同页指标",
        source_text_metric_present: "源文本含指标",
        source_text_keyword_matches: "源文本关键词",
        parser_metric_present: "解析器已抓取",
        parser_metric_row_count: "解析行数",
        parser_metric_regions: "解析地区",
        disclosure_check: "披露判断",
      },
    },
    hk_private_car_ev_model_table: {
      title: "最新电动车私家车厂名/型号快照",
      subtitle: "最新可得月度详情文件中的电动车私家车厂名/型号组合；月度时间序列使用另一个运输署表 4.1(e)来源。",
      columns: { summary: "厂名／型号摘要" },
    },
    hk_parking_current_district_table: {
      title: "当前各区确切停车位空置",
      subtitle: "按地区汇总当前私家车小时停车场空置；B/C 空置类型及负数不会当作确切空置车位。",
      columns: { summary: "地区摘要" },
    },
    mttd_passenger_journeys_latest_table: {
      title: "运输署表 2.3 最新乘客人次摘要",
      subtitle: "按图表使用的简化分组列示最新可用月份；底层快照仍保留原始地区及营办商维度。",
      columns: { summary: "乘客人次摘要" },
    },
    censtatd_boundary_movements_latest_table: {
      title: "C&SD 表 E705 最新跨境移动摘要",
      subtitle: "最新月度飞机、车辆及其他主要移动总量；来源为临时估计的单元会在摘要中标示。",
      columns: { summary: "移动摘要" },
    },
    td_carpark_occupancy_latest_district_table: {
      title: "传感器停车位按区占用率",
      subtitle: "列示运输署传感器计量停车位的最新按区观测占用率。",
      columns: { summary: "地区占用率" },
    },
  },
  sources: {
    mtr_patronage: "港铁公司投资者关系月度客运量",
    cathay_hkia_traffic: "民航处香港国际机场月度流量 & 国泰航空月度交通数据",
    cathay_fleet: "国泰航空公司年报／中期报告 Fleet Profile",
    china_airline_traffic: "六家中国上市航空公司月度运营数据公告（巨潮资讯）",
    airline_kpi_source_recovery: "中国上市航空公司官方 PDF KPI 恢复审计",
    airline_h1_kpi_backtest: "中国上市航空公司 1H KPI 校准回测",
    airline_period_kpi_backtest: "中国上市航空公司 H1 / H2 / FY KPI 校准",
    hk_passenger_journeys: "运输署《公共交通及运输月报》表 2.1",
    mttd_passenger_journeys: "运输署《公共交通及运输月报》表 2.3",
    censtatd_boundary_movements: "政府统计处表 E705 跨境飞机、船只、车辆及火车移动",
    hk_vehicle_stock: "运输署车辆登记及领牌统计数字 表 4.1(a) 私家车",
    hk_private_car_net_growth: "运输署私家车首次登记净额统计数字 表 4.1(c)",
    hk_private_car_first_reg: "运输署月报表 4.1(e) 私家车按厂名/燃料类型首次登记",
    hk_private_car_first_reg_details: "运输署最新私家车首次登记厂名/型号详情",
    td_parking_vacancy: "运输署实时停车场空置数据",
    td_carpark_occupancy: "运输署传感器计量停车位及实时占用状态",
  },
  snapshotBody: (artifact) => `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody: "## 如何阅读本 dashboard\n\n港铁客运量按服务类型拆解（本地重铁、跨境及高铁）；机场与国泰数据反映国际与区域航空客货运复苏进度。中国上市航司按公告披露的集团／合并口径展示客运、货运及稀疏的机队／新航线事件；事件层没有公告的月份不自动补零。月度运营图表优先使用从官方 PDF 恢复并审核过的 KPI 行；官方源确认未披露的项目保持缺失。1H KPI 校准图比较原始层与恢复／研究插值层，不能当作严格的点时交易回测；未来值插值行不属于 PIT 安全数据。海航为集团合并且包括八家运营航司，吉祥含九元航空。私家车累计车队电动车占比与每月首次登记电动车占比是两个不同指标。停车位空置数据是运输署当前快照；重复运行采集器后才会形成五分钟级历史，不应把无法提供确切数字的停车场当作零空置。传感器停车位占用率来自另一组运输署计量车位数据，使用状态已知的空间作为分母，不代表所有停车场。",
  dataLabels: {
    // Cathay's ASK/RPK series are industry-standard aviation acronyms kept
    // in English even in the zh chart title above -- not translated here,
    // same treatment as REIT ticker codes.
    mtr_service_breakdown_history: {
      series: {
        "Airport Exp": "机场快线",
        Domestic: "本地",
        HSR: "高铁",
        "LR & Bus": "轻铁巴士",
        "X-Boundary": "跨境",
      },
    },
    cathay_cargo_capacity_demand_history: {
      series: { "AFTK ('000)": "AFTK（千单位）", "RFTK ('000)": "RFTK（千单位）" },
    },
    cathay_fleet_total_history: {
      series: { Company: "国泰航空公司", "HK Express": "香港快运", "Air Hong Kong": "国泰航空货运（Air Hong Kong）", "Grand total": "集团合计" },
    },
    china_airline_passengers_history: {
      series: { CS: "南方航空", AC: "中国国航", CE: "东方航空", Spring: "春秋航空", Hainan: "海航控股", Juneyao: "吉祥航空" },
    },
    china_airline_load_factor_history: {
      series: { CS: "南方航空", AC: "中国国航", CE: "东方航空", Spring: "春秋航空", Hainan: "海航控股", Juneyao: "吉祥航空" },
    },
    china_airline_ask_history: {
      series: { CS: "南方航空", AC: "中国国航", CE: "东方航空", Spring: "春秋航空", Hainan: "海航控股", Juneyao: "吉祥航空" },
    },
    china_airline_rpk_history: {
      series: { CS: "南方航空", AC: "中国国航", CE: "东方航空", Spring: "春秋航空", Hainan: "海航控股", Juneyao: "吉祥航空" },
    },
    china_airline_region_split_history: {
      series: { Domestic: "国内", International: "国际", Regional: "地区" },
    },
    china_airline_region_by_carrier_history: {
      series: {
        "AC · Domestic": "中国国航 · 国内", "AC · International": "中国国航 · 国际", "AC · Regional": "中国国航 · 地区",
        "CS · Domestic": "南方航空 · 国内", "CS · International": "南方航空 · 国际", "CS · Regional": "南方航空 · 地区",
        "CE · Domestic": "东方航空 · 国内", "CE · International": "东方航空 · 国际", "CE · Regional": "东方航空 · 地区",
        "Spring · Domestic": "春秋航空 · 国内", "Spring · International": "春秋航空 · 国际", "Spring · Regional": "春秋航空 · 地区",
        "Hainan · Domestic": "海航控股 · 国内", "Hainan · International": "海航控股 · 国际", "Hainan · Regional": "海航控股 · 地区",
        "Juneyao · Domestic": "吉祥航空 · 国内", "Juneyao · International": "吉祥航空 · 国际", "Juneyao · Regional": "吉祥航空 · 地区",
      },
    },
    china_airline_cargo_history: {
      series: {
        AC: "中国国航", CS: "南方航空", CE: "东方航空", Spring: "春秋航空",
        Hainan: "海航控股", Juneyao: "吉祥航空",
      },
    },
    china_airline_freight_load_factor_history: {
      series: {
        AC: "中国国航", CS: "南方航空", CE: "东方航空", Spring: "春秋航空",
        Hainan: "海航控股", Juneyao: "吉祥航空",
      },
    },
    china_airline_fleet_total_history: {
      series: {
        AC: "中国国航", CS: "南方航空", CE: "东方航空", Spring: "春秋航空",
        Hainan: "海航控股", Juneyao: "吉祥航空",
      },
    },
    china_airline_fleet_net_change_history: {
      series: {
        AC: "中国国航", CS: "南方航空", CE: "东方航空", Spring: "春秋航空",
        Hainan: "海航控股", Juneyao: "吉祥航空",
      },
    },
    china_airline_new_route_history: {
      series: {
        AC: "中国国航", CS: "南方航空", CE: "东方航空", Spring: "春秋航空",
        Hainan: "海航控股", Juneyao: "吉祥航空",
      },
    },
    china_airline_latest_snapshot: {
      airline: {
        "Air China": "中国国航",
        "China Southern": "南方航空",
        "China Eastern": "东方航空",
        "Spring Airlines": "春秋航空",
        "Hainan Airlines Holdings": "海航控股",
        "Juneyao Airlines": "吉祥航空",
      },
      reporting_scope: {
        "Group-consolidated operating data": "集团合并运营数据",
        "Company and subsidiaries": "公司及子公司",
        "Hainan group consolidated; includes eight operating carriers": "海航集团合并；包括八家运营航司",
        "Company and Jiuyuan Airlines consolidated": "公司及九元航空合并",
      },
      region: { Domestic: "国内", International: "国际", Regional: "地区", Total: "合计" },
    },
    china_airline_latest_snapshot: {
      airline: {
        "Air China": "中国国航", "China Eastern": "东方航空", "China Southern": "南方航空",
        "Spring Airlines": "春秋航空", "Hainan Airlines Holdings": "海航控股", "Juneyao Airlines": "吉祥航空",
      },
      reporting_scope: {
        "Group-consolidated operating data": "集团合并运营数据",
        "Company and subsidiaries": "公司及子公司",
        "Hainan group consolidated; includes eight operating carriers": "海航集团合并；包括八家运营航司",
        "Company and Jiuyuan Airlines consolidated": "公司及九元航空合并",
      },
      region: { Domestic: "国内", International: "国际", Regional: "地区", Total: "合计" },
    },
    china_airline_cargo_latest_snapshot: {
      airline: {
        "Air China": "中国国航", "China Eastern": "东方航空", "China Southern": "南方航空",
        "Spring Airlines": "春秋航空", "Hainan Airlines Holdings": "海航控股", "Juneyao Airlines": "吉祥航空",
      },
      reporting_scope: {
        "Group-consolidated operating data": "集团合并运营数据",
        "Company and subsidiaries": "公司及子公司",
        "Hainan group consolidated; includes eight operating carriers": "海航集团合并；包括八家运营航司",
        "Company and Jiuyuan Airlines consolidated": "公司及九元航空合并",
      },
    },
    china_airline_operating_events_latest: {
      airline: {
        "Air China": "中国国航", "China Eastern": "东方航空", "China Southern": "南方航空",
        "Spring Airlines": "春秋航空", "Hainan Airlines Holdings": "海航控股", "Juneyao Airlines": "吉祥航空",
      },
      reporting_scope: {
        "Group-consolidated operating data": "集团合并运营数据",
        "Company and subsidiaries": "公司及子公司",
        "Hainan group consolidated; includes eight operating carriers": "海航集团合并；包括八家运营航司",
        "Company and Jiuyuan Airlines consolidated": "公司及九元航空合并",
      },
      event_type: {
        fleet_added_aircraft: "引进飞机",
        fleet_retired_aircraft: "退出／退租飞机",
        fleet_total_aircraft: "机队总数",
        new_route_event_count: "新航线事件数",
      },
    },
    airline_h1_revenue_mae_comparison: {
      carrier: {
        AC: "中国国航", "China Eastern Airlines": "东方航空", CS: "南方航空",
        Hainan: "海航控股", Juneyao: "吉祥航空", Spring: "春秋航空",
      },
      layer: { "Raw observed": "原始观测", "Source recovered + imputed": "官方源恢复 + 研究插值" },
    },
    airline_h1_cost_mae_comparison: {
      carrier: {
        AC: "中国国航", "China Eastern Airlines": "东方航空", CS: "南方航空",
        Hainan: "海航控股", Juneyao: "吉祥航空", Spring: "春秋航空",
      },
      layer: { "Raw observed": "原始观测", "Source recovered + imputed": "官方源恢复 + 研究插值" },
    },
    airline_source_recovery_summary: {
      status_label: {
        "Recovered from official PDF": "从官方 PDF 恢复",
        "Not disclosed in source PDF": "源 PDF 未披露",
      },
    },
    airline_source_recovery_audit: {
      status: {
        recovered_from_cached_official_pdf: "从缓存官方 PDF 恢复",
        not_disclosed_in_source_pdf: "源 PDF 未披露",
      },
      recovery_method: {
        pdf_table_shift_recovery: "PDF 表格错位恢复",
        split_header_continuation: "分拆表头续行恢复",
        pdf_table_shift_recovery_sum_total: "PDF 表格错位合计恢复",
        not_applicable: "不适用",
      },
      region: { Domestic: "国内", International: "国际", Regional: "地区", Total: "合计" },
    },
    hk_total_transport_journeys_history: {
      series: { Total: "总计" },
    },
    hk_modal_split_history: {
      series: {
        Bus: "巴士",
        Rail: "铁路",
        PLB: "小巴",
        Ferry: "渡轮",
        Taxi: "的士",
      },
    },
    hk_franchised_bus_operator_history: {
      series: { KMB: "九巴", Citybus: "城巴", LWB: "龙运", NLB: "新大屿山巴士" },
    },
    hk_private_car_fleet_by_fuel_history: {
      series: { Petrol: "汽油", Electric: "电力", Diesel: "柴油", Other: "其他" },
    },
    hk_private_car_net_growth_history: {
      series: { "Net first registrations": "首次登记净额" },
    },
    hk_private_car_ev_make_history: {
      series: { BYD: "比亚迪", Tesla: "Tesla", "Other EV makes": "其他电动车厂名" },
    },
    mttd_passenger_journeys_history: {
      series: {
        "MTR Local": "港铁本地",
        "MTR Airport / LRT / feeder": "港铁机场／轻铁／接驳",
        "Franchised buses": "专营巴士",
      },
    },
    censtatd_boundary_movements_history: {
      series: {
        Aircraft: "飞机",
        "Passenger vehicles": "客运车辆",
        "Goods vehicles": "货运车辆",
      },
    },
    mttd_passenger_journeys_latest: { summary: translateTransportLatestSummary },
    censtatd_boundary_movements_latest: { summary: translateTransportLatestSummary },
    td_carpark_occupancy_latest_district: { summary: translateTransportLatestSummary },
    hk_parking_current_district: { summary: translateTransportLatestSummary },
  },
};

const HK_TELECOM_ZH = {
  title: "香港电讯监测",
  description: "香港电讯（HKT）、数码通（SmarTone）及和记电讯（3 HK）的半年度用户与 ARPU 披露数据，以及通讯办全运营商手机号码段配额快照。",
  cards: {
    hkt_card: { description: "半年度后付费退出 ARPU 及后付费用户数（千户）；半年环比变动及 FTTH 渗透率。", metricLabels: ["后付费 ARPU (港元)", "后付费用户数 (千户)", "半年环比", "FTTH 渗透率 (%)"] },
    hkt_footprint_card: { description: "香港电讯宽带接入线路数、FTTH 连接数及收费电视用户数（千户）。", metricLabels: ["宽带线路数 (千户)", "FTTH 连接数 (千户)", "收费电视用户数 (千户)", "FTTH 渗透率 (%)"] },
    smartone_card: { description: "半年度后付费 ARPU 及后付费用户数（千户）；同比变动。", metricLabels: ["后付费 ARPU (港元)", "后付费用户数 (千户)", "同比"] },
    hutchison_card: { description: "半年度后付费毛 ARPU 与净 ARPU；半年环比变动。", metricLabels: ["后付费毛 ARPU (港元)", "后付费净 ARPU (港元)", "半年环比"] },
  },
  charts: {
    hkt_arpu_chart: ["香港电讯后付费退出 ARPU 走势 (港元)", "半年度后付费退出 ARPU，取自香港电讯自身业绩公告的叙述文本。", "期间", "港元"],
    hkt_footprint_chart: ["香港电讯宽带及收费电视用户足迹 (千户)", "半年度 FTTH 连接数及收费电视用户数。", "期间", "千户", "指标"],
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
  dataLabels: {
    hkt_footprint_history: { series: { "FTTH connections": "FTTH 连接数", "Pay TV base": "收费电视用户数" } },
  },
};

const LABOUR_INDUSTRY_ZH = {
  "Mining and quarrying": "采矿及采石",
  Manufacturing: "制造业",
  "Electricity and gas supply, and waste management": "电力及燃气供应、废物管理",
  "Construction sites (manual workers only)": "建筑地盘（仅手工工人）",
  "Import/export, wholesale and retail trades": "进出口、批发及零售业",
  "Transportation, storage, postal and courier services": "运输、仓储、邮政及速递服务",
  "Accommodation and food services": "住宿及膳食服务",
  "Information and communications": "资讯及通讯",
  "Financing and insurance": "金融及保险",
  "Real estate": "地产",
  "Professional and business services": "专业及商用服务",
  "Administrative and support services": "行政及支援服务",
  Education: "教育",
  "Social and personal services": "社会及个人服务",
  "Human health and social work services": "人类保健及社会工作服务",
  "Arts, entertainment and recreation": "艺术、娱乐及康乐",
  "Other services": "其他服务",
  Total: "总计",
  "Retail, accommodation and food services": "零售、住宿及膳食服务",
  "Transportation, storage, postal and courier services, information and communications": "运输、仓储、邮政及速递服务、资讯及通讯",
  "Financing, insurance, real estate, professional and business services": "金融、保险、地产、专业及商用服务",
  "Real estate and professional and business services": "地产及专业、商用服务",
  "Public administration, social and personal services": "公共行政、社会及个人服务",
  "Other industries": "其他行业",
  "Transport, storage & courier": "运输、仓储及速递",
  "Transport, storage & ICT": "运输、仓储及资讯通讯",
  "Accommodation & food": "住宿及膳食",
  "Information & communications": "资讯及通讯",
  "Professional/scientific/technical": "专业、科学及技术服务",
  "Professional & business services": "专业及商用服务",
  "Administrative & support services": "行政及支援服务",
  "Health & social work": "医疗及社会工作",
  "Arts, entertainment & recreation": "艺术、娱乐及康乐",
  "Import/export, wholesale & retail": "进出口、批发及零售",
  "Social & personal services": "社会及个人服务",
  "Construction sites": "建筑地盘",
  "Transport, storage & ICT": "运输、仓储、速递及资讯通讯",
  "Retail, accommodation & food": "零售、住宿及膳食",
  "Public admin, social & personal": "公共行政、社会及个人服务",
  "Real estate & professional/business": "地产及专业、商用服务",
  "Finance, insurance, real estate & business": "金融、保险、地产及商用服务",
  "Import/export & wholesale": "进出口及批发",
  "Finance & insurance": "金融及保险",
  "Total vacancies": "职位空缺总数",
  Finance: "金融",
  Health: "医疗",
  Trade: "贸易",
  "Prof & biz": "专业商用",
  Social: "社会",
  "F&B": "住宿餐饮",
  Mfg: "制造",
  Const: "建造",
  "Trans.": "运输通讯",
  "Fin.": "金融",
  Mgrs: "经理",
  "Prof.": "专业",
  "Assoc. prof": "辅专业",
  Sales: "销售服务",
  Elementary: "非技术",
  Retail: "零售业",
  Construction: "建造业",
};

const LABOUR_OCCUPATION_ZH = {
  Total: "总计",
  Managers: "经理",
  Professionals: "专业人员",
  "Associate professionals": "辅专业人员",
  "Clerical support workers": "文书支援人员",
  "Services and sales workers": "服务工作及销售人员",
  "Craft and related trades workers": "工艺及有关人员",
  "Plant and machine operators and assemblers": "机台及机器操作员及装配员",
  "Elementary occupations": "非技术工人",
  "Other occupations": "其他职业",
};

const LABOUR_POLICY_SERIES_ZH = {
  ESLS: "补充劳工",
  GEP: "一般",
  ASMTP: "内地",
  TechTAS: "科技",
  TTPS: "高端",
  IANG: "IANG",
  ASSG: "二代港人",
  QMAS: "优秀",
};

const HK_LABOUR_MARKET_ZH = {
  title: "香港劳动力市场与人才政策",
  description: "劳动力、就业、失业、职位空缺、工资、就业收入及官方人才政策流量的来源快照。",
  cards: {
    labour_force_card: { description: "政府统计处每月三个月移动平均劳动力市场指标；最后一项显示实际观察期。", metricLabels: ["劳动力（千人）", "就业人数（千人）", "失业率", "就业不足率", "观察期"] },
    labour_demand_card: { description: "政府统计处按季职位空缺调查；最后一项显示实际观察期。", metricLabels: ["职位空缺", "就业人数", "职位空缺率", "观察期"] },
    wage_card: { description: "政府统计处行业工资及薪金指数同比变动；名义与实际指标分开显示。", metricLabels: ["名义工资同比", "实际工资同比", "名义薪金同比", "观察期"] },
    income_card: { description: "所有行业就业人士每月就业收入中位数，采用最新三个月移动平均观察值。", metricLabels: ["每月就业收入中位数（港元）", "观察期"] },
    talent_policy_card: { description: "各人才计划的年度申请及批准总数；QMAS 使用官方获配名额（甄选成功个案）作为批准等值指标；申请不等于实际抵港或就业。", metricLabels: ["申请数", "批准数", "优秀人才计划配额", "观察年"] },
  },
  charts: {
    labour_force_chart: ["劳动力、就业及失业人数", "每月三个月移动平均，单位为千人；最新点不是单月估计。", "月份", "千人", "指标"],
    labour_rates_chart: ["失业率及就业不足率", "每月三个月移动平均，数值为百分比。", "月份", "%", "指标"],
    vacancies_by_industry_chart: ["各行业职位空缺比较", "最新政府统计处季度数据；只显示最高层行业组别。", "行业", "职位空缺数"],
    vacancy_industry_history_chart: ["所选行业职位空缺历史", "自 2000 年起的季度历史；点击图例显示或隐藏总数及所选行业序列。上方仍保留最新一期完整行业排名。", "季度", "职位空缺数", "行业"],
    vacancy_rate_chart: ["整体职位空缺率", "政府统计处职位空缺调查的季度整体职位空缺率。", "季度", "%"],
    wage_yoy_chart: ["工资及薪金增长", "总行业工资及薪金指数同比变动；名义与实际指标分开保留。", "季度", "同比变动", "指标"],
    earnings_by_industry_chart: ["各行业每月就业收入中位数", "最新三个月移动平均；合并男女数据。", "行业", "港元"],
    earnings_industry_history_chart: ["所选行业就业收入历史", "自 2008 年起的每月三个月移动平均；点击图例显示或隐藏所选行业。单位为每月港元。", "月份", "港元／月", "行业"],
    occupation_earnings_history_chart: ["所选职业就业收入历史", "自 2016 年起的每月三个月移动平均；点击图例显示或隐藏所选职业。单位为每月港元。", "月份", "港元／月", "职业"],
    talent_policy_received_chart: ["人才政策申请数", "按计划划分的年度申请数；属于政策需求，不是已确认的人口流入或就业。", "年份", "申请数", "计划"],
    talent_policy_approved_chart: ["人才政策批准数", "按计划划分的年度批准数；QMAS 使用官方获配名额（甄选成功个案）作为批准等值指标。批准不等于实际抵港、启动签证或进入劳动力市场。", "年份", "批准数", "计划"],
  },
  tables: {
    earnings_by_occupation_table: {
      title: "各职业每月就业收入中位数",
      subtitle: "最新三个月移动平均；合并男女数据。",
      columns: { occupation: "职业", median_monthly_earnings: "收入中位数（港元）" },
    },
    talent_policy_latest_table: {
      title: "最新年度人才政策流量（按计划）",
      subtitle: "官方年度数字；QMAS 的批准数使用获配名额（甄选成功个案），原始配额另行保留，不等于实际抵港或就业人数。",
      columns: { series: "计划", applications_received: "申请数", applications_approved: "批准数", qmas_quota: "优秀人才计划配额" },
    },
    source_health_table: {
      title: "劳动力市场数据来源健康度",
      subtitle: "本页使用的本地审计快照；日期是数据观察日期，不是抓取日期。",
      columns: { dataset: "数据集", status: "状态", latest_observation: "最新观察日期", records: "记录数", freshness: "刷新模式", notes: "备注" },
    },
  },
  sources: {
    censtatd_labour_force: "政府统计处劳动力、就业、失业及就业不足统计",
    censtatd_labour_demand: "政府统计处按行业划分的职位空缺统计",
    censtatd_wage_payroll: "政府统计处工资及薪金指数",
    censtatd_earnings: "政府统计处每月就业收入中位数",
    talent_policy_open_data: "劳工处及入境事务处人才政策公开数据",
  },
  snapshotBody: (artifact) => `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody: "## 如何阅读本 dashboard\n\n本页将政府统计处劳动力市场数据，与劳工处及入境事务处的人才政策流量数据并列。劳动力及就业收入的月度序列是三个月移动平均；职位空缺与工资／薪金指数为季度数据；人才政策数据为年度数据。QMAS 官方获配名额代表甄选成功个案，并在批准数显示中作为批准等值指标；原始 QMAS 配额字段仍会单独保留。申请、批准及优秀人才计划配额不应解读为已确认抵港、仍在港就业或劳动力参与人数。",
  dataLabels: {
    vacancies_by_industry_latest: { industry: LABOUR_INDUSTRY_ZH },
    vacancy_industry_history: { series: { Total: "职位空缺总数", Social: "社会", Health: "医疗", Trade: "贸易", "Prof & biz": "专业商用", Finance: "金融" } },
    earnings_by_industry_latest: { industry: LABOUR_INDUSTRY_ZH },
    earnings_industry_history: { series: { Total: "总计", Retail: "零售", "F&B": "住宿餐饮", Mfg: "制造", Const: "建造", "Fin.": "金融", "Trans.": "运输通讯" } },
    earnings_by_occupation_latest: { occupation: LABOUR_OCCUPATION_ZH },
    earnings_by_occupation_table: { occupation: LABOUR_OCCUPATION_ZH },
    occupation_earnings_history: { series: { Total: "总计", Mgrs: "经理", "Prof.": "专业", "Assoc. prof": "辅专业", Sales: "销售服务", Elementary: "非技术" } },
    labour_force_history: { series: { "Labour force": "劳动力", Employed: "就业人数", Unemployed: "失业人数" } },
    labour_rate_history: { series: { "Unemployment rate": "失业率", "Underemployment rate": "就业不足率" } },
    vacancy_history: { series: { "Persons engaged": "就业人数", Vacancies: "职位空缺" } },
    wage_yoy_history: { series: { "Nom wage": "名义工资同比", "Real wage": "实际工资同比", "Nom pay": "名义薪金同比", "Real pay": "实际薪金同比" } },
    talent_policy_received_history: { series: LABOUR_POLICY_SERIES_ZH },
    talent_policy_approved_history: { series: LABOUR_POLICY_SERIES_ZH },
    talent_policy_latest: { series: LABOUR_POLICY_SERIES_ZH },
    source_health: {
      dataset: {
        labour_force_monthly: "劳动力月度数据",
        labour_demand_by_industry: "按行业划分的职位空缺",
        wage_payroll_indices: "工资及薪金指数",
        median_earnings_by_industry: "行业就业收入中位数",
        talent_policy_supply_panel: "人才政策流量数据",
      },
    },
  },
};

const HK_REIT_ZH = {
  title: "香港房地产信托（REITs）基本面监测",
  description: "领展（Link REIT）、冠君（Champion REIT）、置富（Fortune REIT）、繁荣（Prosperity REIT）、阳光（Sunlight REIT）及富豪（Regal REIT）的每单位资产净值（NAV）、每基金单位分派（DPU）、出租率、租金检讨调升率及酒店 KPI 快照。",
  cards: {
    linkreit_card: { description: "领展房产基金（0823.HK）最新每单位资产净值、DPU 及出租率/租金检讨调升率披露。", metricLabels: ["领展 NAV (港元)", "每基金单位分派 (港元)", "出租率 (%)", "租金检讨调升率 (%)"] },
    championreit_card: { description: "冠君产业信托（2778.HK）最新每单位资产净值、DPU 及出租率/租金检讨调升率披露。", metricLabels: ["冠君 NAV (港元)", "每基金单位分派 (港元)", "出租率 (%)", "租金检讨调升率 (%)"] },
    fortunereit_card: { description: "置富产业信托（0778.HK）最新每单位资产净值、DPU 及出租率/租金检讨调升率披露。", metricLabels: ["置富 NAV (港元)", "每基金单位分派 (港元)", "出租率 (%)", "租金检讨调升率 (%)"] },
    prosperityreit_card: { description: "繁荣产业信托（0808.HK）最新每单位资产净值、DPU 及出租率/租金检讨调升率披露。", metricLabels: ["繁荣 NAV (港元)", "每基金单位分派 (港元)", "出租率 (%)", "租金检讨调升率 (%)"] },
    sunlightreit_card: { description: "阳光房地产基金（0435.HK）最新每单位资产净值、DPU 及出租率/租金检讨调升率披露。", metricLabels: ["阳光 NAV (港元)", "每基金单位分派 (港元)", "出租率 (%)", "租金检讨调升率 (%)"] },
    regalreit_card: { description: "富豪产业信托（1881.HK）最新每单位资产净值、DPU 及酒店 KPI 披露。", metricLabels: ["富豪 NAV (港元)", "每基金单位分派 (港元)", "酒店出租率 (%)", "RevPAR (港元)"] },
  },
  charts: {
    nav_trend_chart: ["各 REIT 每单位资产净值相对走势（首期 = 100）", "全部六家 REIT（按股票代码）各自每单位资产净值的相对变动，以各自首期观测值重新定为 100——各 REIT 每单位资产净值绝对水平不同（见上方卡片及下方对比表），不宜在同一坐标轴上直接比较原始港元数值。", "期间", "重新定基（首期 = 100）", "股票代码"],
    dpu_trend_chart: ["各 REIT 每基金单位分派相对走势（首期 = 100）", "全部六家 REIT（按股票代码）DPU 的相对变动，以各自首个正数观测值重新定为 100。部分期间（如富豪产业信托 2025 上半年）分派为零属真实披露结果，重新定基后显示为 0，并非数据缺失；绝对港元 DPU 数值见上方对比表。", "期间", "重新定基（首期 = 100）", "股票代码"],
    occupancy_trend_chart: ["写字楼/零售 REIT 出租率走势 (%)", "领展 (0823)、冠君 (2778)、置富 (0778)、繁荣 (0808) 及阳光 (0435)——不含富豪产业信托（其组合为酒店而非写字楼/零售）。", "期间", "出租率 (%)", "股票代码"],
    reversion_trend_chart: ["写字楼/零售 REIT 租金检讨调升率走势 (%)", "续租/新租相对原有租金的调升率，仅限五家写字楼/零售 REIT（按股票代码）。", "期间", "租金检讨调升率 (%)", "股票代码"],
    regal_hotel_kpi_chart: ["富豪产业信托酒店 KPI：出租率、ADR 及 RevPAR", "富豪产业信托的酒店组合指标体系与其余五家写字楼/零售 REIT 完全不同，故不与其合并显示；出租率单位为 %，ADR 及 RevPAR 单位为港元，请以提示框中的具体数值为准。", "期间", "数值（单位不一）", "指标"],
  },
  tables: {
    reit_comparison_table: {
      title: "香港 REIT 基本面对比",
      subtitle: "全部六家 REIT 最新每单位资产净值及 DPU；出租率跨业务类型统一列示（富豪产业信托为酒店出租率）。",
      columns: {
        reit_name: "REIT 名称",
        ticker: "股票代码",
        nav_per_unit_hkd: "每单位资产净值 (港元)",
        dpu_hkd: "每基金单位分派 (港元)",
        occupancy_pct: "出租率 (%)",
        as_of_date: "截至日期",
      },
    },
    reit_spot_summary_table: {
      title: "香港 REITs 市场现货报价",
      subtitle: "每日现货报价、涨跌幅 % 及成交额 (百万港元)。",
      columns: { company_name: "REIT 名称", ticker: "股票代码", latest_price_hkd: "现价 (港元)", change_pct: "涨跌幅 (%)", turnover_hkd_m: "成交额 (百万)" },
    },
  },
  sources: {
    cross_source: "跨来源香港 REIT 官方投资者关系比较",
    linkreit_fundamentals: "领展房产基金（0823.HK）投资者关系披露",
    championreit_fundamentals: "冠君产业信托（2778.HK）财务披露",
    fortunereit_fundamentals: "置富产业信托（0778.HK）财务披露",
    prosperityreit_fundamentals: "繁荣产业信托（0808.HK）财务披露",
    sunlightreit_fundamentals: "阳光房地产基金（0435.HK）财务披露",
    regalreit_fundamentals: "富豪产业信托（1881.HK）酒店业绩披露",
    reit_price_akshare: "香港REITs每日现货报价及历史（akshare）",
  },
  snapshotBody: (artifact) => `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody: "## 如何阅读本 dashboard\n\n五家 REIT（领展、冠君、置富、繁荣、阳光）为写字楼/零售业主，披露出租率与租金检讨调升率；富豪产业信托为酒店类 REIT，披露出租率、平均房价（ADR）及 RevPAR，其酒店指标从不与其余五家的写字楼/零售指标合并显示于同一图表。DPU 在个别期间可能为零（真实披露结果，非数据缺失），此时环比变动留空而非除以零。本 dashboard 不提供股票排名、预测或投资建议。",
  dataLabels: {
    // Only the Regal hotel-KPI chart's metric-name series need translating;
    // nav/dpu/occupancy/reversion charts intentionally color by bare ticker
    // code (0823, 2778, ...) for mobile-legend-width reasons -- those stay
    // untouched, same as reit_name/ticker in reit_comparison below.
    regal_hotel_kpi_history: {
      series: {
        "Occupancy (%)": "出租率 (%)",
        "ADR (HK$)": "平均房价 ADR (港元)",
        "RevPAR (HK$)": "RevPAR (港元)",
      },
    },
    reit_comparison: {
      business_type: { "Office/Retail": "写字楼/零售", Hotel: "酒店" },
    },
  },
};

function localizeArtifact(input, zh) {
  const artifact = JSON.parse(JSON.stringify(input));
  localizeHealthCoverageDatasets(artifact);
  localizeDataLabels(artifact, zh.dataLabels);
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
      if (chart.encodings?.series) chart.encodings.series.label = copy[5] || copy[4] || chart.encodings.series.label;
      if (chart.encodings?.color) chart.encodings.color.label = copy[5] || "序列";
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
  const localizeSourceEntry = (source) => ({
    ...source,
    label: zh.sources[source.id] || source.label,
    query: source.query ? {
      ...source.query,
      description: source.query.description
        ? `构建时从公开来源读取并校验 ${zh.sources[source.id] || source.label}。`
        : source.query.description,
    } : source.query,
  });
  // Both artifact.manifest.sources and the top-level artifact.sources carry
  // an English query.description (e.g. "Hotel portfolio KPIs: occupancy
  // (%), average daily rate (ADR, HK$), RevPAR (HK$), ...") that is
  // user-visible source-attribution text on the rendered page. Only
  // artifact.sources used to have its description localized; manifest.sources
  // was left untouched, which leaked the English description onto zh pages.
  if (artifact.manifest.sources) {
    artifact.manifest.sources = artifact.manifest.sources.map(localizeSourceEntry);
  }
  if (Array.isArray(artifact.sources)) {
    artifact.sources = artifact.sources.map(localizeSourceEntry);
  }
  const snapshot = artifact.manifest.blocks?.find((block) => block.id === "snapshot_context");
  if (snapshot) snapshot.body = zh.snapshotBody(artifact);
  const methodology = artifact.manifest.blocks?.find((block) => block.id === "methodology");
  if (methodology) methodology.body = zh.methodologyBody;
  if (zh.blocks) {
    artifact.manifest.blocks?.forEach((block) => {
      if (zh.blocks[block.id]) block.body = zh.blocks[block.id];
    });
  }
  return artifact;
}

function addYearAwareStaticChartTicks(html, artifact, { locale = "en" } = {}) {
  const charts = new Map((artifact.manifest?.charts || []).map((chart) => [chart.id, chart]));
  const chinese = locale === "zh";
  const monthNames = chinese
    ? ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]
    : ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const parseDate = (value) => {
    const match = /^(\d{4})[-/](\d{1,2})(?:[-/](\d{1,2}))?/.exec(String(value ?? ""));
    if (!match) return null;
    const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3] || 1)));
    return Number.isFinite(date.getTime()) ? date : null;
  };
  const formatMonthYear = (date) => chinese
    ? `${date.getUTCFullYear()}年${monthNames[date.getUTCMonth()]}`
    : `${monthNames[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
  const figurePattern = /(<figure\b[^>]*data-chart-id="([^"]+)"[\s\S]*?<\/figure>)/g;
  const patchedHtml = html.replace(figurePattern, (figure, _ignored, chartId) => {
    const chart = charts.get(chartId);
    const x = chart?.encodings?.x;
    if (!x || x.type !== "temporal") return figure;
    const rows = artifact.snapshot?.datasets?.[chart.dataset];
    const dates = Array.isArray(rows) ? rows.map((row) => parseDate(row?.[x.field])).filter(Boolean) : [];
    if (dates.length < 2) return figure;
    const minTime = Math.min(...dates.map((date) => date.getTime()));
    const maxTime = Math.max(...dates.map((date) => date.getTime()));
    if (!(maxTime > minTime)) return figure;

    return figure.replace(/(<svg\b[^>]*class="portable-static-chart-svg"[^>]*>[\s\S]*?<\/svg>)/g, (svg) => {
      const heightMatch = /\bheight="([\d.]+)"/.exec(svg);
      const height = Number(heightMatch?.[1]);
      if (!Number.isFinite(height)) return svg;
      const ticks = [];
      const textPattern = /<text\b([^>]*)>([\s\S]*?)<\/text>/g;
      let match;
      while ((match = textPattern.exec(svg))) {
        const attrs = match[1];
        const xMatch = /\bx="([\d.]+)"/.exec(attrs);
        const yMatch = /\by="([\d.]+)"/.exec(attrs);
        const text = match[2].replace(/<[^>]+>/g, "").trim();
        if (!xMatch || !yMatch || Number(yMatch[1]) < height - 50 || Number(yMatch[1]) > height - 18) continue;
        if (!/^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/.test(text)) continue;
        if (/\b(?:19|20)\d{2}\b/.test(text)) continue;
        ticks.push({ start: match.index, end: textPattern.lastIndex, x: Number(xMatch[1]), text });
      }
      if (ticks.length < 2) return svg;
      const left = Math.min(...ticks.map((tick) => tick.x));
      const right = Math.max(...ticks.map((tick) => tick.x));
      if (!(right > left)) return svg;
      let output = svg;
      for (const tick of ticks.reverse()) {
        const ratio = (tick.x - left) / (right - left);
        const date = new Date(minTime + ratio * (maxTime - minTime));
        const replacement = formatMonthYear(date);
        const original = output.slice(tick.start, tick.end);
        output = output.slice(0, tick.start) + original.replace(tick.text, replacement) + output.slice(tick.end);
      }
      return output;
    });
  });

  // The static fallback above is what gets emailed or printed, but supported
  // browsers reveal the interactive reader after load. Its shared renderer
  // intentionally formats day-precision temporal ticks as \`5 Jan\`, which is
  // ambiguous on a multi-year chart. Patch only the visible Recharts x-axis
  // ticks after the reader is ready, using the same artifact rows to map each
  // tick's x-position back to its source date. This keeps weekly source
  // cadence intact while making the year visible in both delivery modes.
  const chartMetadata = Object.fromEntries(
    [...charts.entries()].map(([id, chart]) => {
      const x = chart.encodings?.x;
      const rows = artifact.snapshot?.datasets?.[chart.dataset];
      const rawDates = x?.type === "temporal" && Array.isArray(rows)
        ? rows.map((row) => row?.[x.field]).filter((value) => value != null && String(value).trim())
        : [];
      const dates = x?.type === "temporal" && Array.isArray(rows)
        ? rows.map((row) => parseDate(row?.[x.field])).filter(Boolean)
        : [];
      return [
        id,
        {
          xType: x?.type,
          monthGranular: rawDates.length > 0 && rawDates.every((value) => /^\d{4}[-/]\d{1,2}$/.test(String(value))),
          minTime: dates.length ? Math.min(...dates.map((date) => date.getTime())) : null,
          maxTime: dates.length ? Math.max(...dates.map((date) => date.getTime())) : null,
        },
      ];
    }),
  );
  const runtimeScript = [
    '<script data-dashboard-year-aware-axis="true">',
    '(()=>{const charts=',
    JSON.stringify(chartMetadata),
    `,formatDate=(date,monthGranular)=>new Intl.DateTimeFormat(${JSON.stringify(chinese ? "zh-CN" : "en-US")},monthGranular?{month:"short",year:"numeric",timeZone:"UTC"}:{day:"numeric",month:"short",year:"numeric",timeZone:"UTC"}).format(date),patch=()=>{Object.entries(charts).forEach(([chartId,meta])=>{if(!meta||meta.xType!=="temporal"||!(meta.maxTime>meta.minTime))return;const roots=[document.getElementById(chartId),...document.querySelectorAll("figure[data-chart-id=\\"" + chartId + "\\"]")].filter(Boolean);roots.forEach((figure)=>{const ticks=[...figure.querySelectorAll(".recharts-xAxis-tick-labels .recharts-cartesian-axis-tick-value")];const positions=ticks.map((tick)=>Number(tick.getAttribute("x"))).filter(Number.isFinite);if(positions.length<2)return;const left=Math.min(...positions),right=Math.max(...positions);if(!(right>left))return;ticks.forEach((tick)=>{if(tick.dataset.dashboardYearAware==="true")return;const x=Number(tick.getAttribute("x"));if(!Number.isFinite(x))return;const date=new Date(meta.minTime+Math.max(0,Math.min(1,(x-left)/(right-left)))*(meta.maxTime-meta.minTime));tick.textContent=formatDate(date,meta.monthGranular);tick.dataset.dashboardYearAware="true"})})})};const schedule=()=>{patch();requestAnimationFrame(()=>patch())};document.addEventListener("data-analytics-portable-reader-ready",schedule);window.addEventListener("data-analytics-portable-reader-ready",schedule);new MutationObserver(()=>patch()).observe(document.documentElement,{childList:true,subtree:true});schedule()})();`,
    '</script>',
  ].join("");
  const cleanHtml = patchedHtml.replace(
    /<script data-dashboard-year-aware-axis="true">[\s\S]*?<\/script>/g,
    "",
  );
  return cleanHtml.replace("</body>", runtimeScript + "</body>");
}

function addCopyTitleControls(html, artifact, { locale }) {
  const copyLabel = locale === "zh" ? "复制标题" : "Copy title";
  const copiedLabel = locale === "zh" ? "已复制" : "Copied";
  const idToDataset = {};
  for (const item of [
    ...(artifact.manifest?.charts || []),
    ...(artifact.manifest?.tables || []),
    ...(artifact.manifest?.cards || []),
  ]) {
    if (item?.id && item?.dataset) idToDataset[item.id] = item.dataset;
  }
  const css = `<style data-dashboard-copy-title="true">.portable-visual-header{display:flex!important;align-items:flex-start;gap:8px}.portable-visual-header>strong,.portable-visual-header>h1,.portable-visual-header>h2,.portable-visual-header>h3{flex:1}.editable-cell-header{position:relative!important}.editable-cell-header h1,.editable-cell-header h2,.editable-cell-header h3{padding-right:96px}.editable-cell-header .portable-copy-title{position:absolute;top:2px;right:0}.portable-copy-title{flex:0 0 auto;margin:0;padding:3px 8px;border:1px solid var(--portable-border);border-radius:999px;background:transparent;color:var(--portable-muted);font:500 11px/18px ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;cursor:pointer}.portable-copy-title:hover{color:var(--portable-ink);background:var(--portable-surface-subtle)}.portable-copy-title:focus-visible{outline:2px solid var(--portable-accent);outline-offset:2px}</style>`;
  const script = `<script data-dashboard-copy-title-runtime="true">(()=>{const copyLabel=${JSON.stringify(copyLabel)},copiedLabel=${JSON.stringify(copiedLabel)},idToDataset=${JSON.stringify(idToDataset)},enhance=()=>{document.querySelectorAll(".portable-visual-header,.editable-cell-header").forEach((header)=>{if(header.querySelector(".portable-copy-title"))return;const box=header.getBoundingClientRect();if(!box.width||!box.height||getComputedStyle(header).visibility==="hidden")return;const title=header.querySelector("strong,h1,h2,h3");if(!title)return;const artifactEl=header.closest("[data-chart-id],[data-table-id],[data-card-id],[data-artifact-id]");let artifactId=artifactEl?.dataset?.chartId||artifactEl?.dataset?.tableId||artifactEl?.dataset?.cardId||null;if(!artifactId&&artifactEl?.dataset?.artifactId){const raw=artifactEl.dataset.artifactId;const segments=raw.split(":");artifactId=segments[segments.length-1]}const button=document.createElement("button");button.type="button";button.className="portable-copy-title";button.textContent=copyLabel;button.setAttribute("aria-label",copyLabel);button.addEventListener("click",async()=>{const titleText=title.textContent.trim();if(!titleText)return;const dataset=artifactId?idToDataset[artifactId]:null;const text=dataset?(titleText+", "+dataset):titleText;let copied=false;try{await navigator.clipboard.writeText(text);copied=true}catch{const area=document.createElement("textarea");area.value=text;area.setAttribute("readonly","");area.style.position="fixed";area.style.opacity="0";document.body.appendChild(area);area.select();try{copied=document.execCommand("copy")}finally{area.remove()}}button.textContent=copied?copiedLabel:copyLabel;window.setTimeout(()=>{button.textContent=copyLabel},1400)});header.appendChild(button)})};enhance();new MutationObserver(enhance).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:["class","style"]})})();</script>`;
  const cleanHtml = html
    .replace(/<style data-dashboard-copy-title="true">[\s\S]*?<\/style>/g, "")
    .replace(/<script data-dashboard-copy-title-runtime="true">[\s\S]*?<\/script>/g, "");
  return cleanHtml.replace("</head>", css + "</head>").replace("</body>", script + "</body>");
}

function addNavigation(html, { locale, homeEn, homeZh, routeEn, routeZh }) {
  const chinese = locale === "zh";
  const home = chinese ? homeZh : homeEn;
  const languageHref = chinese ? routeEn : routeZh;
  const backLabel = chinese ? "← 返回主 dashboard" : "← Back to main dashboard";
  const languageLabel = chinese ? "English" : "简体中文";
  const css = `<style>.am-dashboard-nav{position:fixed;top:12px;left:12px;z-index:1000;display:flex;gap:8px;align-items:center;font:500 12px/1.2 system-ui,-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif}.am-dashboard-nav a,.am-dashboard-nav button{display:inline-flex;align-items:center;justify-content:center;min-height:30px;padding:0 10px;border:1px solid rgba(128,128,128,.35);border-radius:999px;background:rgba(255,255,255,.94);color:#1f2937;text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,.08);font:inherit;cursor:pointer}.am-dashboard-nav a:hover,.am-dashboard-nav button:hover{background:#f2f4f7}.am-theme-toggle{width:30px;padding:0}@media(prefers-color-scheme:dark){.am-dashboard-nav a,.am-dashboard-nav button{background:rgba(31,35,42,.92);color:#f3f4f6;border-color:rgba(255,255,255,.25)}.am-dashboard-nav a:hover,.am-dashboard-nav button:hover{background:rgba(55,60,68,.92)}}
  /* Manual theme override for the portable renderer's own --portable-* palette
     (see build_portable_artifact.mjs) -- higher specificity than its plain
     :root rules (default and its prefers-color-scheme:dark block), so this
     wins in both directions once data-theme is set; when unset, neither rule
     matches and the renderer's own auto (OS-following) behavior is untouched. */
  :root[data-theme="dark"]{color-scheme:dark;--portable-canvas:#181818;--portable-surface:#212121;--portable-surface-subtle:#2a2a2a;--portable-ink:#dfdfdf;--portable-muted:#cdcdcd;--portable-tertiary:#afafaf;--portable-table-text:#cdcdcd;--portable-border:rgba(255,255,255,.12);--portable-accent:#66b5ff;--portable-positive:#79d996;--portable-positive-bg:rgba(64,180,99,.16);--portable-negative:#ff8583;--portable-negative-bg:rgba(224,74,70,.16);--portable-warning-bg:#302817;--portable-warning-border:#8b6a20}
  :root[data-theme="light"]{color-scheme:light;--portable-canvas:#fff;--portable-surface:#fff;--portable-surface-subtle:#f7f7f7;--portable-ink:#0d0d0d;--portable-muted:#5d5d5d;--portable-tertiary:#8f8f8f;--portable-table-text:#5d5d5d;--portable-border:rgba(13,13,13,.1);--portable-accent:#0285ff;--portable-positive:#00692a;--portable-positive-bg:#edfaf2;--portable-negative:#ba2623;--portable-negative-bg:#fff0f0;--portable-warning-bg:#fff8e6;--portable-warning-border:#e7b84b}
  </style>`;
  // Blocking init (runs before the renderer's own <style>, via <head> insertion
  // below) applies a stored preference before first paint; absent entry means
  // "no manual choice yet", left to the renderer's own prefers-color-scheme
  // behavior. Shares the 'am-theme' localStorage key with the hub pages
  // (build-static-hub.mjs), so one choice, made anywhere on the site, persists
  // everywhere -- the key is scoped per-origin, so it carries across routes.
  const themeInit = `<script>(function(){try{var t=localStorage.getItem('am-theme');if(t==='dark'||t==='light')document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>`;
  const themeToggleScript = `<script>(function(){
    var btn = document.getElementById('am-theme-toggle');
    if (!btn) return;
    function current(){
      var attr = document.documentElement.getAttribute('data-theme');
      if (attr === 'dark' || attr === 'light') return attr;
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    function apply(theme){
      document.documentElement.setAttribute('data-theme', theme);
      try { localStorage.setItem('am-theme', theme); } catch (e) {}
      btn.textContent = theme === 'dark' ? '\\u2600' : '\\u263E';
    }
    apply(current());
    btn.addEventListener('click', function(){ apply(current() === 'dark' ? 'light' : 'dark'); });
  })();</script>`;
  const nav = `<nav class="am-dashboard-nav" aria-label="Dashboard navigation"><a href="${home}">${backLabel}</a><a href="${languageHref}">${languageLabel}</a><button type="button" class="am-theme-toggle" id="am-theme-toggle" aria-label="Toggle dark mode">☾</button></nav>`;
  const localizedHtml = chinese ? html.replace('<html lang="en"', '<html lang="zh-CN"') : html;
  return localizedHtml
    .replace("<head>", `<head>${themeInit}`)
    .replace("</head>", `${css}</head>`)
    .replace("<body>", `<body>${nav}`)
    .replace("</body>", `${themeToggleScript}</body>`);
}

// The portable reader's chart legend is a flex item whose intrinsic width can
// exceed its mobile chart frame when a series name is long.  The frame itself
// is responsive, but the unbounded legend becomes a page-level horizontal
// overflow (rather than an intentional table scroller).  Apply this shared
// constraint before the portable verifier runs, so the check exercises the
// actual mobile layout and every sector benefits from the same fix.
function addResponsivePortableStyles(html) {
  const css = `<style data-dashboard-responsive-overflow="true">
@media screen and (max-width:600px){
  .chart-frame,.chart-body-measure,.chart-legend-wrap,.chart-legend{min-width:0!important;max-width:100%!important}
  .chart-legend{width:100%!important;box-sizing:border-box!important}
  .chart-legend-item,.chart-legend-button{min-width:0!important;max-width:100%!important}
  .chart-legend-button{overflow:hidden!important;text-overflow:ellipsis!important;white-space:nowrap!important}
}
</style>`;
  return html
    .replace(/<style data-dashboard-responsive-overflow="true">[\s\S]*?<\/style>/g, "")
    .replace("</head>", `${css}</head>`);
}

async function deliverPortable({ deliverPortableArtifact, buildPortableArtifact, artifactFile, portableFile, locale }) {
  const failureScreenshot = join(generatedDir, `portable-verification-failure-${locale}.png`);
  const maxAttempts = Math.max(1, Number(process.env.PORTABLE_DELIVERY_RETRIES || 2));
  let lastError = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      return await deliverPortableArtifact({
        inputPath: artifactFile,
        outputPath: portableFile,
        screenshotPath: failureScreenshot,
        readyTimeoutMs: Number(process.env.PORTABLE_READY_TIMEOUT_MS || "30000"),
        actionTimeoutMs: Number(process.env.PORTABLE_ACTION_TIMEOUT_MS || "10000"),
        timeoutMs: Number(process.env.PORTABLE_VERIFY_TIMEOUT_MS || "60000"),
      }, {
        build: (artifact, options) => addResponsivePortableStyles(
          buildPortableArtifact(artifact, options),
        ),
      });
    } catch (error) {
      lastError = error;
    }
  }
  if (lastError?.deliveryResult) {
    process.stderr.write(`${JSON.stringify(lastError.deliveryResult)}\n`);
  } else if (lastError) {
    process.stderr.write(`${lastError.stack || lastError}\n`);
  }
  throw new Error(`Portable dashboard delivery failed (${locale}) after ${maxAttempts} attempt(s).`);
}

const HK_COMMERCIAL_AEROSPACE_ZH = {
  title: "香港商业航天监测",
  description: "上交所科创板 IPO 审核状态、Launch Library 2 发射频次、Celestrak 低轨卫星星座数量、商业航天企业专利申请及 Wikipedia 关注度。",
  cards: {
    ipo_race_card: { description: "头部商业火箭企业上交所科创板 IPO 审核状态。", metricLabels: ["蓝箭航天状态", "蓝箭审核号", "中科宇航状态", "中科宇航审核号"] },
    constellations_card: { description: "Celestrak 低轨卫星星座在轨卫星追踪数量。", metricLabels: ["千帆星座 (在轨数)", "吉林一号 (在轨数)", "商业发射总次数"] },
  },
  charts: {
    satellite_count_chart: ["中国商业卫星星座在轨数量", "Celestrak 追踪的千帆 (G60) 及吉林一号星座在轨活跃卫星数。", "星座", "卫星数"],
    patent_count_chart: ["商业火箭企业专利申请估算", "各火箭制造企业专利申请数量估算。", "企业", "专利数"],
    launch_cadence_chart: ["各商业航天企业发射次数统计", "Launch Library 2 追踪的历史商业发射次数。", "发射企业", "发射次数"],
    launch_monthly_chart: ["中国商业航天月度发射次数", "按已配置的中国商业发射服务商统计；没有匹配发射的月份显示为 0，国家队发射不包含在此序列。", "月份", "发射次数"],
    china_launch_monthly_chart: ["中国火箭发射：按项目类别", "展示最新十年的零填充月度序列；规范化发射历史自 1970 年起保留，未匹配的 LL2 候选不计入核验序列。", "月份", "发射次数", "项目类别"],
    china_launch_family_chart: ["按火箭系列统计的已核验发射次数", "按标准化火箭系列统计逐次发射；统计的是火箭发射次数，不是卫星或有效载荷数量。", "火箭系列", "发射次数", "项目类别"],
    satellite_history_chart: ["中国商业卫星星座库存快照", "Celestrak 目录快照；累计至少 8 个独立观察值后才发布为历史图表，追踪目标不一定等同于正在运行的卫星。", "日期", "追踪目标数", "星座"],
    global_space_benchmark_chart: ["全球进入太空的物体数量", "基于 UNOOSA 的年度全球总量，并列显示中国和美国；统计的是物体/有效载荷，不是火箭发射次数。", "年份", "物体数量", "地区"],
    global_object_catalog_monthly_chart: ["全球已编目空间物体发射（月度）", "Celestrak SATCAT 按发射日期统计的最新十年月度序列；Payload 最接近 UNOOSA 基准，火箭体、碎片和未知物体单独列出，不能与 UNOOSA 注册物体直接等同。", "月份", "已编目物体数", "物体类型"],
    wikipedia_attention_agent_weekly_chart: ["航天 Wikipedia 关注度：按周", "从每日访问量汇总的完整周一至周日数据；显示最近 500 个完整周，精选英文 Wikipedia 航天页面篮子按用户、搜索引擎爬虫、自动化程序及全部代理流量分开显示，当前未完成周不纳入。", "周起始日", "页面访问量", "流量代理"],
    wikipedia_attention_agent_monthly_chart: ["航天 Wikipedia 关注度：按流量代理", "按精选英文 Wikipedia 航天页面篮子汇总的月度访问量；用户、搜索引擎爬虫、自动化程序及全部代理流量分开显示。", "月份", "页面访问量", "流量代理"],
    wikipedia_user_attention_monthly_chart: ["航天 Wikipedia 用户访问量：按页面", "精选英文 Wikipedia 航天页面篮子的月度用户访问量；展示可用历史中的最近十年。", "月份", "用户页面访问量", "Wikipedia 页面"],
  },
  tables: {
    ipo_race_table: {
      title: "上交所科创板商业航天 IPO 审核进展",
      subtitle: "头部商业火箭企业审核状态、审核编号及更新日期。",
      columns: { company_en: "英文名称", company_zh: "中文名称", status: "审核状态", audit_num: "审核编号", update_date: "更新日期", exchange: "交易所" },
    },
    upcoming_launches_table: {
      title: "中国商业火箭及卫星发射日程表",
      subtitle: "Launch Library 2 追踪的最新发射窗口（不早于 NET 日期）、发射企业、火箭型号、发射场及状态。",
      columns: { net_date: "目标发射日期 (NET)", provider: "发射企业 / 机构", mission: "任务 / 火箭型号", pad_name: "发射场", orbit: "轨道", status: "状态" },
    },
    china_launch_events_table: {
      title: "已核验中国火箭发射任务明细",
      subtitle: "每行代表一次规范化发射；是否计入由官方一手记录决定，LL2 字段仅在匹配成功时补充。",
      columns: { launch_date: "发射日期", mission_name: "任务 / 载荷", rocket_name: "火箭", program_class: "项目类别", launch_site: "发射场", payload_summary: "载荷摘要", payload_count: "载荷数量", outcome: "结果", ll2_match_status: "LL2 匹配" },
    },
    aerospace_watchlist_table: {
      title: "香港上市商业航天及国防观察名单",
      subtitle: "香港上市航天、卫星及国防供应链公司股票观察名单。",
      columns: { ticker: "股票代码", company_name: "公司名称", category: "类别", notes: "备注" },
    },
    policy_milestones_table: {
      title: "中国商业航天政策推进里程碑",
      subtitle: "中央经济工作会议及政府工作报告政策定位。",
      columns: { date: "日期", event: "政策里程碑" },
    },
    szse_ipo_table: {
      title: "深交所航天相关行业 IPO 项目",
      subtitle: "深交所广义行业分类包含航空、铁路及其他运输设备；原始行业字段保留供复核。",
      columns: { company_name: "公司", board: "板块", status: "状态", industry: "行业分类", update_date: "更新日期", accept_date: "受理日期" },
    },
    faa_kpi_table: {
      title: "FAA 商业航天监管指标",
      subtitle: "美国联邦航空管理局官方累计指标及当前有效授权数量。",
      columns: { metric: "指标", value: "数值", observed_date: "观察日期" },
    },
    usaspending_contracts_table: {
      title: "美国商业航天政府合同发现",
      subtitle: "按关键词发现的联邦政府合同；合同金额不是公司营业收入。",
      columns: { award_id: "合同编号", recipient_name: "收款方", award_amount: "合同金额", awarding_agency: "授予机构", start_date: "开始日期", keyword: "匹配关键词" },
    },
    sec_space_filings_table: {
      title: "上市商业航天公司 SEC 披露",
      subtitle: "官方证券披露事件流；目前仅使用 filing metadata，不推断订单或融资金额。",
      columns: { ticker: "代码", company_name: "公司", form: "表格类型", filing_date: "提交日期", primary_doc_description: "文件说明", filing_url: "披露文件" },
    },
    wikipedia_attention_latest_table: {
      title: "最新 Wikipedia 航天关注度：按页面及流量代理",
      subtitle: "精选英文 Wikipedia 页面篮子的最新完整月份及过去 12 个月访问量；用户及自动化访问量不是独立人数。",
      columns: { page_label: "Wikipedia 页面", topic_group: "主题类别", agent: "流量代理", latest_month: "最新月份", latest_views: "最新访问量", trailing_12m_views: "过去 12 个月访问量" },
    },
  },
  dataLabels: {
    launch_cadence: {
      provider: { LandSpace: "蓝箭航天", "Galactic Energy": "星河动力", "CAS Space": "中科宇航", "Space Pioneer": "天兵科技", "Orienspace": "东方空间", "Deep Blue Aerospace": "深蓝航天", "i-Space": "星际荣耀" },
    },
    launch_cadence_summary: {
      provider: { LandSpace: "蓝箭航天", "Galactic Energy": "星河动力", "CAS Space": "中科宇航", "Space Pioneer": "天兵科技", "Orienspace": "东方空间", "Deep Blue Aerospace": "深蓝航天", "i-Space": "星际荣耀" },
    },
    launch_monthly: {
      provider: { LandSpace: "蓝箭航天", "Galactic Energy": "星河动力", "CAS Space": "中科宇航", "Space Pioneer": "天兵科技", "Orienspace": "东方空间", "Deep Blue Aerospace": "深蓝航天", "i-Space": "星际荣耀" },
    },
    china_launch_monthly: {
      program_class: { national_program: "国家队项目", state_owned_commercial: "国企商业化", commercial_provider: "商业发射服务商" },
    },
    china_launch_family_summary: {
      program_class: { national_program: "国家队项目", state_owned_commercial: "国企商业化", commercial_provider: "商业发射服务商" },
    },
    china_launch_events: {
      program_class: { national_program: "国家队项目", state_owned_commercial: "国企商业化", commercial_provider: "商业发射服务商" },
      outcome_normalized: { Success: "成功", Failure: "失利", Unknown: "未知" },
      ll2_match_status: { matched: "已匹配", unmatched: "未匹配", ambiguous: "有歧义", source_event: "原始事件", not_checked: "未核对" },
    },
    satellite_counts: {
      constellation: { Qianfan: "千帆", Jilin1: "吉林一号", Guowang: "国网" },
    },
    satellite_history: {
      constellation: { Qianfan: "千帆", Jilin1: "吉林一号", Guowang: "国网" },
    },
    global_space_benchmark: {
      entity: { World: "全球", China: "中国", "United States": "美国" },
    },
    global_object_catalog_monthly: {
      object_type: { Payload: "有效载荷", "Rocket body": "火箭体", Debris: "碎片", Unknown: "未知" },
    },
    wikipedia_attention_agent_monthly: {
      agent: { user: "用户", spider: "搜索引擎爬虫", automated: "自动化程序", "all-agents": "全部代理" },
    },
    wikipedia_attention_agent_weekly: {
      agent: { user: "用户", spider: "搜索引擎爬虫", automated: "自动化程序", "all-agents": "全部代理" },
    },
    wikipedia_user_attention_monthly: {
      topic_group: { Company: "公司", Constellation: "星座", Rocket: "火箭", China: "中国", Industry: "行业" },
      page_label: {
        SpaceX: "SpaceX",
        Starlink: "星链",
        "Rocket Lab": "火箭实验室",
        "Falcon 9": "猎鹰9号",
        "New Glenn": "新格伦",
        "Long March": "长征系列运载火箭",
        "Chinese space program": "中国航天计划",
        "Satellite constellation": "卫星星座",
        "Commercial spaceflight": "商业航天",
      },
    },
    wikipedia_attention_latest: {
      agent: { user: "用户", spider: "搜索引擎爬虫", automated: "自动化程序", "all-agents": "全部代理" },
      topic_group: { Company: "公司", Constellation: "星座", Rocket: "火箭", China: "中国", Industry: "行业" },
      page_label: {
        SpaceX: "SpaceX",
        Starlink: "星链",
        "Rocket Lab": "火箭实验室",
        "Falcon 9": "猎鹰9号",
        "New Glenn": "新格伦",
        "Long March": "长征系列运载火箭",
        "Chinese space program": "中国航天计划",
        "Satellite constellation": "卫星星座",
        "Commercial spaceflight": "商业航天",
      },
    },
  },
  sources: {
    sse_star_market_ipo: "上交所科创板 IPO 审核状态",
    launch_library_2: "Launch Library 2 商业发射数据库",
    official_china_launch_records: "中国运载火箭技术研究院 / 中国航天科技集团官方发射记录",
    launch_library_2_national_enrichment: "Launch Library 2 国家队及国企发射字段补充",
    celestrak: "Celestrak NORAD 卫星轨道数据",
    google_patents: "Google Patents 专利搜索",
    szse_aerospace_ipo: "深交所航天相关行业 IPO 项目",
    faa_commercial_space: "美国联邦航空管理局商业航天指标",
    usaspending_contracts: "美国联邦合同支出数据库",
    sec_space_company_filings: "美国证券交易委员会公司披露",
    global_space_benchmark: "UNOOSA / Our World in Data 全球太空活动基准",
    global_object_catalog: "Celestrak SATCAT 全球空间物体编目",
    wikimedia_pageviews: "Wikimedia Wikipedia 页面访问量",
  },
  snapshotBody: (artifact) =>
    `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody:
    "## 如何阅读本 dashboard\n\n中国商业航天板块受两大核心催化剂驱动：上交所科创板 IPO 审核进展（蓝箭航天 #2174、中科宇航 #2180）与低轨卫星星座组网（千帆 G60、吉林一号）。发射比较以官方长征/捷龙记录决定是否计入，现有商业发射服务商序列保持独立；Launch Library 2 只为已匹配的官方任务补充结构化字段。国网 (SatNet) Celestrak 标识未定，列为已知数据缝隙。本 dashboard 不提供股票排名、预测或投资建议。",
};

const HK_STABLECOIN_CRYPTO_ZH = {
  title: "香港稳定币与加密资产基础设施监测",
  description: "金管局持牌稳定币发行人沙盒名单、证监会持牌 VATP 虚拟资产交易平台、港交所加密 ETF 规模时间序列、全球稳定币市值与公链分布、DEX 交易量、加密情绪指数与 BTC 价格长期走势。",
  cards: {
    regulatory_licensing_card: { description: "金管局稳定币沙盒持牌发行人及证监会持牌交易平台。", metricLabels: ["金管局稳定币发行人", "SFC 持牌 VATP", "SFC 申请中 VATP"] },
    crypto_signals_card: { description: "比特币现货价格、Coinbase 溢价价差及情绪指数。", metricLabels: ["比特币价格 (美元)", "Coinbase 溢价 (bps)", "加密情绪指数"] },
    etf_aum_card: { description: "港交所加密现货 ETF 资产规模及全球稳定币总市值。", metricLabels: ["港交所 ETF AUM (百万美元)", "全球稳定币市值 (十亿美元)"] },
    news_pulse_card: { description: "证监会与金管局加密相关监管新闻（近约 13 个月）及观察名单公司公告（近 90 天）。", metricLabels: ["监管新闻条数", "观察名单公司公告数"] },
  },
  charts: {
    etf_aum_history_chart: ["港交所加密现货 ETF 月度 AUM (百万美元)", "香港上市比特币及以太币现货 ETF 基金规模历史。", "月份", "AUM (百万美元)", "代码"],
    stablecoin_history_chart: ["全球稳定币总流通供应量走势 (十亿美元)", "DefiLlama 统计的每日全球锚定资产流通市值月度平均；图表默认显示可用历史中的最近十年。", "月份", "总供应量 (十亿美元)"],
    stablecoin_chain_chart: ["主要区块链公链稳定币供应量分布 (十亿美元)", "DefiLlama 按底层区块链网络（Ethereum、Tron、BSC、Solana 等）统计的稳定币流通市值分布。", "区块链公链", "供应量 (十亿美元)"],
    dex_volume_history_chart: ["全球 DEX 每日交易量走势 (十亿美元/日)", "DefiLlama 统计的全球去中心化交易所每日交易量月度平均；图表默认显示可用历史中的最近十年。", "月份", "DEX 交易量 (十亿美元/日)"],
    fear_greed_history_chart: ["加密情绪指数走势 (Alternative.me)", "Alternative.me 每日加密货币恐慌与贪婪指数月度平均；图表默认显示可用历史中的最近十年 (0=极度恐慌, 100=极度贪婪)。", "月份", "情绪得分"],
    btc_price_history_chart: ["比特币现货价格走势 (美元)", "Binance 每日比特币收盘价的月末值；图表默认显示可用历史中的最近十年。", "月份", "BTC 价格 (美元)"],
    wikipedia_crypto_attention_agent_weekly_chart: ["加密资产 Wikipedia 关注度：按流量代理", "精选英文加密资产／DeFi 页面按日访问量汇总的最近 500 个完整周；用户、搜索引擎爬虫、自动化程序及全部代理流量分开显示，标准化缓存保留更长历史。", "周起始日", "页面访问量", "流量代理"],
    wikipedia_crypto_user_attention_monthly_chart: ["加密资产 Wikipedia 用户关注度：按页面", "精选英文加密资产／DeFi 页面按月用户访问量；在可用范围内显示最近十年。", "月份", "用户页面访问量", "Wikipedia 页面"],
  },
  tables: {
    hkma_issuers_table: {
      title: "香港金管局持牌稳定币沙盒发行人",
      subtitle: "金管局稳定币发行人沙盒官方登记册。",
      columns: { issuer: "发行人名称", licence_number: "牌照编号", effective_date: "生效日期", status: "监管状态" },
    },
    sfc_vatp_table: {
      title: "香港证监会虚拟资产交易平台 (VATP) 登记册",
      subtitle: "涵盖持牌、申请中及已撤回的交易所平台。",
      columns: { platform_name: "平台 / 运营商名称", status: "状态", licensed_date: "牌照 / 申请日期" },
    },
    top_stablecoins_table: {
      title: "全球前十大稳定币流通供应量明细",
      subtitle: "DefiLlama 按锚定市值及全球份额统计的前十大稳定币。",
      columns: { name: "稳定币名称", symbol: "代码", circulating_usd_bn: "供应量 (十亿美元)", market_share_pct: "全球份额 (%)" },
    },
    hkex_etf_table: {
      title: "港交所加密现货 ETF 基金规模摘要",
      subtitle: "各基金最新月度 AUM（嘉实以太币 3179.HK 待查找 fundId）。",
      columns: { ticker: "股票代码", name: "ETF 名称", fund_id: "港交所 Fund ID", latest_month: "最新月份", aum_usd_m: "AUM (百万美元)" },
    },
    polymarket_table: {
      title: "标签筛选的 Polymarket 加密与宏观监管催化剂预测概率",
      subtitle: "通过 Polymarket 按标签筛选（crypto、fed-rates、etf、finance）的实时预测市场概率。",
      columns: { title: "催化事件", probability_pct: "概率 (%)", end_date: "目标日期" },
    },
    crypto_watchlist_table: {
      title: "香港上市加密与稳定币观察名单 (Tiers 1–4)",
      subtitle: "Tier 1 持牌基础设施、Tier 2 大型机构、Tier 3 概念转型、Tier 4 储备配置；如有数据则显示实时股价及日涨跌幅。",
      columns: { tier: "分层", ticker: "股票代码", company_en: "英文名称", company_zh: "中文名称", latest_price_hkd: "股价 (港元)", change_pct: "日涨跌幅 (%)", regulatory_note: "监管状态 / 备注" },
    },
    regulatory_news_table: {
      title: "证监会与金管局监管新闻（加密相关筛选）",
      subtitle: "近约 13 个月内与加密/虚拟资产/稳定币相关的证监会及金管局最新 30 条新闻。",
      columns: { issue_date: "日期", source: "监管机构", title: "标题", news_type: "类型" },
    },
    hkexnews_announcements_table: {
      title: "观察名单公司公告 (香港交易所披露易)",
      subtitle: "近 90 天内香港稳定币与加密观察名单全部公司的最新 30 条公告/披露。",
      columns: { date_time: "日期/时间", ticker: "股票代码", stock_name: "公司名称", title: "公告标题" },
    },
  },
  sources: {
    hkma_register: "香港金管局持牌稳定币发行人登记册",
    sfc_vatp: "香港证监会虚拟资产交易平台登记册",
    defillama: "DefiLlama 稳定币与 DEX 分析 API",
    hkex_etf: "港交所综合基金平台 ETF AUM API",
    coinbase_binance: "Coinbase & Binance 公开行情",
    fear_greed: "加密货币恐慌与贪婪指数 (Alternative.me)",
    polymarket: "Polymarket 预测市场 API (Gamma API)",
    sfc_news: "香港证监会新闻及公告（加密相关筛选）",
    hkma_news: "香港金管局新闻稿（加密相关筛选）",
    hkexnews_announcements: "香港交易所披露易公司公告（观察名单）",
    watchlist_price: "香港观察名单实时股票行情",
    wikimedia_crypto_pageviews: "Wikimedia Wikipedia 加密资产页面访问量",
  },
  snapshotBody: (artifact) =>
    `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody:
    "## 如何阅读本 dashboard\n\n香港加密生态由官方监管登记册锚定：金管局稳定币发行人沙盒（Anchorpoint FRS01、汇丰 FRS02）及证监会持牌 VATP 交易平台（OSL、HashKey）。券商（如国泰君安国际 01788.HK）仅具备虚拟资产交易服务许可，非 VATP 交易所运营商；Anchorpoint（Anchorpoint Financial，港元锚定 HKDAP）与 AnchorX（金涌投资 01328.HK，AxCNH）为不同主体。本 dashboard 跟踪监管登记册、港交所 ETF AUM 时间序列、全球稳定币供应走势、主要公链分布、DEX 交易量、加密情绪指数、BTC 价格长期走势、标签筛选的 Polymarket 催化剂、观察名单实时股价，以及前瞻性的监管新闻与公司公告（证监会、金管局、披露易），让即将发生的催化事件与历史快照并列呈现。本界面不提供投资建议。",
};

const HK_POPULATION_MIGRATION_ZH = {
  title: "香港人口、迁移与跨境数据监测",
  description: "入境处高频每日出入境净流量、政府统计处人口估算与净移动、积金局永久离港强积金申索、教资会内地生入学人数及大湾区跨境车流/高铁客流。",
  cards: {
    kpi_total_pop: { description: "政府统计处半年度人口估算。", metricLabels: ["香港总人口 (千人，年中/年终)"] },
    kpi_net_mov: { description: "最新半年度净人口移动（单程证持有人及其他）。", metricLabels: ["净人口移动 (千人)"] },
    kpi_mpfa_claims: { description: "最新季度因永久离开香港而提取的强积金金额。", metricLabels: ["季度强积金永久离港申索金额 (百万港元)"] },
    kpi_ugc_students: { description: "最新学年教资会资助课程内地学生人数。", metricLabels: ["在港大学内地学生人数"] },
    kpi_visitor_arrivals: { description: "最新发布月份，全部地区访客抵港人次总和。", metricLabels: ["访客抵港总人次"] },
  },
  charts: {
    immd_net_flow_chart: ["入境处高频出入境净流量 (日度)", "香港居民净流出/返回 vs 内地访客净留存。", "日期", "净人数"],
    csd_population_chart: ["政府统计处人口与净移动走势", "半年度年中/年终人口估算与净人口移动（均为千人）。", "期间", "千人"],
    mpfa_claims_chart: ["积金局季度永久离港提取金额 (百万港元)", "因永久离开香港而申请提取强积金的涉及金额。", "季度", "百万港元"],
    mpfa_claims_count_chart: ["积金局季度永久离港申索宗数", "永久离港强积金申索宗数，与提取金额分开显示。", "季度", "宗数"],
    ugc_students_chart: ["香港大学内地及其他非本地学生人数", "教资会资助课程的学年度在读学生人数。", "学年度", "学生人数"],
    td_cross_border_chart: ["运输署大湾区跨境车流与高铁客运量", "港珠澳大桥“港车北上”通关车辆数与高铁西九龙站客运量。", "月份", "人次 / 车辆数"],
    visitor_arrivals_chart: ["访客抵港人次 — 内地 vs 世界其他地区", "按地区划分的月度访客抵港人次，归纳为内地与其他地区合计两个系列。", "月份", "访客人次", "地区"],
  },
  tables: {},
  dataLabels: {
    immd_net_flow_history: {
      series: { "HK Resident Net Flow": "香港居民净流量", "Mainland Visitor Net Retention": "内地访客净留存" },
    },
    csd_population_movement_history: {
      series: { Population: "人口", "Net Movement": "净人口移动" },
    },
    ugc_students_comparison_history: {
      series: { "Mainland Students": "内地学生", "Other Non-local Students": "其他非本地学生" },
    },
    td_cross_border_comparison_history: {
      series: { "Northbound HK Vehicles": "港车北上车辆", "Express Rail Passengers": "高铁西九龙客运量" },
    },
    visitor_arrivals_mainland_vs_row: {
      series: { "Mainland China": "中国内地", "Rest of World": "世界其他地区" },
    },
    visitor_arrivals_by_region: {
      region: {
        "Chinese Mainland": "中国内地",
        Taiwan: "台湾",
        Macao: "澳门",
        "North Asia": "北亚",
        "South and Southeast Asia": "南亚及东南亚",
        "Middle East": "中东",
        Europe: "欧洲",
        Africa: "非洲",
        "The Americas": "美洲",
        "Australia, New Zealand and South Pacific": "澳纽及南太平洋",
        "Not identified": "未能识别",
      },
    },
  },
  sources: {
    immd: "香港入境事务处每日出入境旅客流量",
    csd: "政府统计处香港人口估算与净移动",
    mpfa: "积金局季度统计数字",
    ugc: "大学教育资助委员会非本地生统计",
    td: "运输署月度交通统计 Digest",
    visitor_arrivals: "政府统计处访客抵港人次统计（按地区）",
  },
  snapshotBody: (artifact) =>
    `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。这是已发布快照，不是实时连接。`,
  methodologyBody:
    "## 如何阅读本 dashboard\n\n本界面整合了入境处高频日度出入境数据、政府统计处半年度人口与净移动估算、积金局永久离港强积金提取、教资会大学内地生源及运输署大湾区跨境通关数据。保监局内地访客保费统计未有展示：监管机构自 2025 年第一季起暂停发布该系列（正就非本地保单持有人的数据收集范围与准则进行检讨），目前没有可靠的替代数据来源。本 dashboard 不提供投资建议。",
};

// Identity and status-file wiring come from ../sectors.json; only the
// localization dictionaries are packaging-specific and stay here. A sector in
// the roster without an entry below is a hard error rather than a silently
// English-only ZH page.
const ZH_DICTIONARIES = {
  "hk-real-estate": HK_REAL_ESTATE_ZH,
  "hk-local-consumer": HK_LOCAL_CONSUMER_ZH,
  "hk-utilities": HK_UTILITIES_ZH,
  "hk-transport": HK_TRANSPORT_ZH,
  "hk-telecom": HK_TELECOM_ZH,
  "hk-labour-market": HK_LABOUR_MARKET_ZH,
  "hk-reit": HK_REIT_ZH,
  "hk-commercial-aerospace": HK_COMMERCIAL_AEROSPACE_ZH,
  "hk-stablecoin-crypto": HK_STABLECOIN_CRYPTO_ZH,
  "hk-population-migration": HK_POPULATION_MIGRATION_ZH,
  "market-monitor": {
    "Exposure Leadership": "市场领导力",
    "Relative Regime": "相对强弱",
    "Wrapper Selection (Entry Status / Peer Rank / Hold Rank)": "ETF包装选择",
    "Ticker": "代码",
    "Fund": "基金",
    "Premium %": "溢价率 %",
    "Rel Premium %": "相对溢价 %",
    "Entry Status": "入场状态",
    "Spread (bp)": "价差 (bp)",
    "AUM (CNY)": "规模 (人民币)",
    "Peer Rank": "同类排名",
    "Hold Rank": "持有排名",
    "RSI": "RSI",
    "MA20 %": "MA20 %",
    "MA60 %": "MA60 %",
    "DD60 %": "60日回撤 %",
    "Small / Large": "小盘 / 大盘",
    "Mid / Large": "中盘 / 大盘",
    "Growth / Dividend": "成长 / 红利",
    "China / S&P 500": "中国 / 标普500",
    "20D z": "20日z值",
    "5D %": "5日 %",
    "20D %": "20日 %",
    "Trend": "趋势",
  },
};

const SECTORS = LIVE_SECTORS.map((sector) => {
  const zh = ZH_DICTIONARIES[sector.id];
  if (!zh) {
    throw new Error(`No ZH dictionary for sector "${sector.id}" (add one in package-dashboard.mjs).`);
  }
  return { ...sector, zh };
});

if (!existsSync(distDir)) {
  throw new Error("Run the static hub build step before packaging dashboards.");
}

mkdirSync(generatedDir, { recursive: true });
let deliveryScript = null;
let deliverPortableArtifact = null;
let buildPortableArtifact = null;
let verifyPortableArtifact = null;
try {
  deliveryScript = findPortableBuilder();
  const moduleDir = dirname(deliveryScript);
  const deliveryModule = await import(`file://${deliveryScript}`);
  const builderModule = await import(`file://${join(moduleDir, "build_portable_artifact.mjs")}`);
  const verifyModule = await import(`file://${join(moduleDir, "verify_portable_artifact.mjs")}`);
  deliverPortableArtifact = deliveryModule.deliverPortableArtifact;
  buildPortableArtifact = builderModule.buildPortableArtifact;
  verifyPortableArtifact = verifyModule.verifyPortableArtifact;
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
  await deliverPortable({ deliverPortableArtifact, buildPortableArtifact, artifactFile, portableFile: enPortableFile, locale: "en" });

  process.stdout.write(`[package-dashboard] Delivering ${sector.id} (ZH)...\n`);
  await deliverPortable({ deliverPortableArtifact, buildPortableArtifact, artifactFile: zhArtifactFile, portableFile: zhPortableFile, locale: "zh" });

  const routeEn = `/sectors/${sectorSlug}/`;
  const routeZh = `/zh/sectors/${sectorSlug}/`;
  const homeEn = "/";
  const homeZh = "/zh/";

  const enHtml = addCopyTitleControls(addYearAwareStaticChartTicks(readFileSync(enPortableFile, "utf8"), rawArtifact, { locale: "en" }), rawArtifact, { locale: "en" });
  const zhHtml = addCopyTitleControls(addYearAwareStaticChartTicks(readFileSync(zhPortableFile, "utf8"), zhArtifact, { locale: "zh" }), zhArtifact, { locale: "zh" });
  writeFileSync(
    enPortableFile,
    addNavigation(enHtml, { locale: "en", homeEn, homeZh, routeEn, routeZh })
  );
  writeFileSync(
    zhPortableFile,
    addNavigation(zhHtml, { locale: "zh", homeEn, homeZh, routeEn, routeZh })
  );

  // The delivery helper verifies the responsive HTML before these repo-local
  // additions. Verify the final files too, so navigation, title-copy controls
  // and year-aware axis patches cannot introduce an undetected overflow.
  for (const [portableFile, finalArtifactFile, locale] of [
    [enPortableFile, artifactFile, "en"],
    [zhPortableFile, zhArtifactFile, "zh"],
  ]) {
    await verifyPortableArtifact({
      artifactPath: finalArtifactFile,
      htmlPath: portableFile,
      screenshotPath: join(generatedDir, `portable-verification-failure-${locale}.png`),
      readyTimeoutMs: Number(process.env.PORTABLE_READY_TIMEOUT_MS || "30000"),
      actionTimeoutMs: Number(process.env.PORTABLE_ACTION_TIMEOUT_MS || "10000"),
      timeoutMs: Number(process.env.PORTABLE_VERIFY_TIMEOUT_MS || "60000"),
    });
  }

  const exportsDir = join(distDir, "exports");
  mkdirSync(exportsDir, { recursive: true });
  // Both locales: the hub renders a download link per locale, so shipping only
  // the EN file left every ZH link pointing at a 404.
  const attachments = attachmentNames(sector, statusData);
  cpSync(enPortableFile, join(exportsDir, attachments.en));
  cpSync(zhPortableFile, join(exportsDir, attachments.zh));

  process.stdout.write(`[package-dashboard] Completed ${sector.id}.\n`);
}

process.stdout.write("[package-dashboard] All sector dashboards packaged successfully.\n");
