#!/usr/bin/env node

import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
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

// hk-local-consumer: AFCD wholesale-price category names. Reused for both
// the full-name field (category) and its narrow-legend abbreviation
// (category_short) -- the abbreviation only exists because the portable
// renderer can't wrap a multi-series legend onto multiple lines at mobile
// width (see AFCD_CATEGORY_SHORT_LABELS in build_hk_local_consumer_artifact.py);
// translating to short Chinese terms keeps that legend narrow too.
const AFCD_CATEGORY_ZH = {
  "Marine fish": "海鱼",
  "Livestock / Poultry": "家畜/家禽",
  "Freshwater fish": "淡水鱼",
  Vegetables: "蔬菜",
  Eggs: "蛋类",
};
const AFCD_CATEGORY_SHORT_ZH = {
  "FW fish": "淡水鱼",
  "Meat/Poultry": "畜禽",
  Marine: "海鱼",
  Veg: "蔬菜",
  Eggs: "蛋类",
};
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
  "Consent to Commence": "同意开工书",
  "Occupation Permits (OP) Issued": "入伙纸 (OP) 已发出",
  "Plans Approved": "图则已批准",
};
const BD_PROPERTY_CATEGORY_ZH = {
  Domestic: "住宅",
  "Non-domestic": "非住宅",
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
// hk-local-consumer: Consumer Council complaint categories, shared between
// consumer_council_complaints_table and consumer_council_complaints_chart
// (two different dataset ids for the same 47-category vocabulary).
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
    hkma_ltv_chart: ["香港金管局平均按揭成数 (%)", "新批按揭的平均贷款成数（LTV）。", "月份", "按揭成数 (%)"],
    hkma_credit_quality_chart: ["香港金管局按揭信贷质素 (%)", "拖欠比率及重订还款安排贷款比率——真实的信贷周期风险指标。", "月份", "%", "指标"],
    epi_eri_chart: ["28Hse 屋苑价格及租金指数 (EPI / ERI)", "2016年至今全港屋苑周度价格及租金指数。", "周", "指数", "指数"],
    landreg_volume_chart: ["土地注册处 — 已登记买卖合约", "市区及新界合计的每月登记契约总数。", "月份", "已登记契约数"],
    landreg_asp_chart: ["土地注册处 — 买卖合约 (ASP)", "每月 ASP 宗数，全部楼宇单位与住宅单位对比。", "月份", "ASP 宗数", "系列"],
    bd_supply_pipeline_chart: ["屋宇署 — 房屋供应管道（当月）", "按审批阶段及地区划分的住宅单位数——未来房屋供应的领先指标。", "审批阶段", "住宅单位数", "地区"],
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
      columns: { project_name: "项目名称", location_district: "地区", estimated_total_units: "预计单位数" },
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
  },
  sources: {
    centaline_ccl: "中原城市领先指数（CCL）",
    midland_mhpi: "美联物业市场资讯 — MHPI",
    midland_confidence: "美联物业市场资讯 — 信心指数",
    rvd_price: "差饷物业估价署 — 私人住宅售价指数",
    rvd_rent: "差饷物业估价署 — 私人住宅租金指数",
    cross_source: "跨来源标准化比较",
    source_registry: "香港房地产 dashboard 来源登记表",
    hkma_mortgage: "香港金管局住宅按揭统计调查",
    cnsd_construction: "政府统计处建筑工程总值统计",
    hse28_epi_eri: "28Hse 屋苑价格及租金指数",
    landreg_monthly: "土地注册处月度统计",
    bd_supply: "屋宇署房屋供应管道",
    agency_transactions: "代理行成交（28Hse／美联／中原）",
    hse28_new_projects: "28Hse 新盘目录",
    bd_monthly_digest: "屋宇署月报摘要",
  },
  snapshotBody: (artifact) =>
    `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。这是已发布快照，不是实时连接；RVD 标记为 provisional 的观测可能会修订。`,
  methodologyBody:
    "## 如何阅读本 dashboard\n\n不同发布方的指数基期不同。请在重设基准图中比较方向，不要直接比较原始数值水平。覆盖表区分实时指标、来源目录和计划中的采集工作。本 dashboard 不提供股票排名、预测或投资建议。",
  dataLabels: {
    hkma_mortgage_rate_mix: {
      series: {
        "HIBOR-based (%)": "H按 (HIBOR)",
        "Best Lending Rate (%)": "P按 (最优惠利率)",
        "Fixed-rate (%)": "定息按揭",
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
  },
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
    store_footprint_card: { description: "11家香港上市零售、珠宝、餐饮及消费品公司的门店/网点数量追踪总数。", metricLabels: ["已追踪网点总数"] },
  },
  charts: {
    severe_weather_trend: ["月度极端天气干扰时长 (小时)", "按月汇总的八号及以上热带气旋警告与红/黑色暴雨警告持续时间。", "月份", "小时"],
    immigration_trend: ["跨境旅客流量 (7日移动平均)", "入境事务处发布的每日客流：北上为香港居民经陆路口岸出境，南下为内地访客经全部口岸入境。", "日期", "人次/日 (7日均值)", "流向"],
    afcd_category_chart: ["农渔护理署批发价按类别", "今日各类别商品的平均批发价（每公斤）。", "类别", "港元 / 公斤"],
    afcd_category_trend: ["农渔护理署批发价按类别走势（逐日累积）", "由每次流水线运行时抓取的真实同日快照逐日累积而成——农渔护理署的批发价数据源只公布当日读数（未发现历史存档），因此本序列不作回填，初期数据量很薄（可能仅有一天），并会随每次运行新增真实观测值而增长。图例为适配窄屏使用缩写：FW fish=淡水鱼，Meat/Poultry=家畜/家禽，Marine=海鱼，Veg=蔬菜（完整类别名称见上方快照图与表格）。", "日期", "港元 / 公斤", "类别"],
    gold_trend: ["上海黄金交易所 PM 基准价（毛利成本参考）", "近7年人民币/克每日定盘价；作为香港金饰原料成本的辅助参考，与农渔护理署批发食品成本并列展示以供毛利分析——本 dashboard 的主打消费需求图表为上方的跨境人流走势。", "日期", "人民币 / 克"],
    valuation_pe_chart: ["观察名单历史市盈率对比", "各公司最新的正值历史市盈率；亏损公司不计入此视图。", "公司", "市盈率 (TTM)"],
    retail_trend: ["零售销售价值指数（全部店铺）", "政府统计处月度价值指数，完整已发布历史。", "月份", "价值指数"],
    retail_category_chart: ["零售销售价值指数按类别", "最新发布月份，按零售店铺类型划分。", "类别", "价值指数"],
    restaurant_trend: ["餐饮收益（全部食肆）", "季度全行业收益，百万港元，完整已发布历史。", "季度", "百万港元"],
    restaurant_chart: ["餐饮收益按类型", "最新发布季度，百万港元。", "食肆类型", "百万港元"],
    store_footprint_chart: ["各公司追踪门店/网点数量", "各公司最新的门店足迹快照（各公司单位不直接可比，详见备注）。", "公司", "门店总数"],
    consumer_council_oilprice_chart: ["各大油公司现金折扣对比 (港元/升)", "美孚、中石油、壳牌、中石化及埃索的每升现金折扣。", "油公司", "折扣 (港元/升)"],
    consumer_council_oilprice_net_chart: ["各大油公司实际油价对比 (港元/升)", "同日美孚、中石油、壳牌、中石化及埃索的每升实际油价。", "油公司", "实际油价 (港元/升)"],
    consumer_council_complaints_chart: ["消费者委员会投诉类别排行", "最新一期十大投诉类别（按投诉宗数）。", "类别", "投诉宗数"],
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
    consumer_council_complaints_table: {
      title: "消费者委员会投诉类别（最新一期）",
      subtitle: "最新一期全部投诉类别，按投诉宗数排序。",
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
    afcd_wholesale: "农渔护理署新鲜食品批发价格",
    sge_gold: "上海黄金交易所 AM/PM 基准价",
    hk_valuation: "百度股市通香港股票估值",
    cnsd_retail: "政府统计处零售销售价值/销量指数",
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
    "## 如何阅读本 dashboard\n\n跨境人流（北上/南下）为本 dashboard 主打的消费需求信号。黄金为金饰原料成本的辅助参考，与农渔护理署批发食品成本并列展示以供毛利分析，而非独立的主打图表。农渔护理署批发价按类别走势图逐日累积真实观测值（该数据源无历史存档），因此初期数据量很薄，会随时间增长。本界面整合物理天气干扰、汇率环境、出入境流量、零售金价溢价、零售销售、餐饮收益与消费股估值等代理指标，以评估香港本地零售与餐饮业的宏观受压情况。「已跟踪数据信号」列出已有实时数据支撑的来源；「覆盖范围与下一步采集目标」追踪端点仍存在问题或未经验证的来源。",
  dataLabels: {
    immigration_trend_history: { flow_type: { Northbound: "北上", Southbound: "南下" } },
    afcd_category_summary: { category: AFCD_CATEGORY_ZH },
    afcd_commodity_table: { category: AFCD_CATEGORY_ZH },
    afcd_category_trend_history: { category_short: AFCD_CATEGORY_SHORT_ZH },
    retail_category_snapshot: { category: RETAIL_CATEGORY_ZH },
    retail_category_chart: { category: RETAIL_CATEGORY_ZH },
    restaurant_snapshot: { sub_sector: RESTAURANT_SUBSECTOR_ZH },
    restaurant_chart: { sub_sector: RESTAURANT_SUBSECTOR_ZH },
    severe_weather_log: { signal_name: translateHkoSignalName },
    consumer_council_oilprice: { fuel_type: FUEL_TYPE_ZH },
    consumer_council_complaints_table: { category: CONSUMER_COMPLAINT_CATEGORY_ZH },
    consumer_council_complaints_chart: { category: CONSUMER_COMPLAINT_CATEGORY_ZH },
    immigration_checkpoint_snapshot: { control_point: CONTROL_POINT_ZH, direction: DIRECTION_ZH },
  },
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
  },
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
    china_airline_passengers_chart: ["中国上市航空公司客运量走势", "中国国航、南方航空、东方航空及春秋航空月度载客人次。", "月份", "乘客人数"],
    china_airline_ask_chart: ["中国上市航空公司可用座位公里 (ASK)", "各航空公司月度可用座位公里（投放运力）。", "月份", "千单位"],
    china_airline_rpk_chart: ["中国上市航空公司收入乘客公里 (RPK)", "各航空公司月度收入乘客公里（实际填补需求）。", "月份", "千单位"],
    china_airline_load_factor_chart: ["中国上市航空公司载客率走势", "各航空公司月度载客率，按公司整体运营口径计算。", "月份", "%"],
    china_airline_region_split_chart: ["中国上市航空公司客运量按地区拆分", "四家航空公司合计客运量，按国内、国际及地区航线拆分；各公司分项数值见下方最新运营数据表。", "月份", "乘客人数"],
  },
  tables: {
    china_airline_latest_snapshot_table: {
      title: "中国上市航空公司最新运营数据",
      subtitle: "最新可得月份数据，按航空公司及运营地区拆分。",
      columns: {
        airline: "航空公司",
        region: "地区",
        passengers: "乘客人数",
        ask: "可用座位公里 (ASK)",
        rpk: "收入乘客公里 (RPK)",
        load_factor_pct: "载客率 (%)",
        observation_date: "月份",
      },
    },
  },
  sources: {
    mtr_patronage: "港铁公司投资者关系月度客运量",
    cathay_hkia_traffic: "民航处香港国际机场月度流量 & 国泰航空数据",
    china_airline_traffic: "中国国航、南方航空、东方航空及春秋航空月度运营数据公告",
  },
  snapshotBody: (artifact) => `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody: "## 如何阅读本 dashboard\n\n港铁客运量按服务类型拆解（本地重铁、跨境及高铁）；机场与国泰数据反映国际与区域航空客货运复苏进度。",
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
    china_airline_passengers_history: {
      series: { CS: "南方航空", AC: "中国国航", CE: "东方航空", Spring: "春秋航空" },
    },
    china_airline_load_factor_history: {
      series: { CS: "南方航空", AC: "中国国航", CE: "东方航空", Spring: "春秋航空" },
    },
    china_airline_ask_history: {
      series: { CS: "南方航空", AC: "中国国航", CE: "东方航空", Spring: "春秋航空" },
    },
    china_airline_rpk_history: {
      series: { CS: "南方航空", AC: "中国国航", CE: "东方航空", Spring: "春秋航空" },
    },
    china_airline_region_split_history: {
      series: { Domestic: "国内", International: "国际", Regional: "地区" },
    },
    china_airline_latest_snapshot: {
      airline: { "Air China": "中国国航", "China Eastern": "东方航空", "China Southern": "南方航空", "Spring Airlines": "春秋航空" },
      region: { Domestic: "国内", International: "国际", Regional: "地区", Total: "合计" },
    },
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
  return artifact;
}

function addNavigation(html, { locale, homeEn, homeZh, routeEn, routeZh }) {
  const chinese = locale === "zh";
  const home = chinese ? homeZh : homeEn;
  const languageHref = chinese ? routeEn : routeZh;
  const backLabel = chinese ? "← 返回主 dashboard" : "← Back to main dashboard";
  const languageLabel = chinese ? "English" : "简体中文";
  const css = `<style>.am-dashboard-nav{position:fixed;top:12px;left:12px;z-index:1000;display:flex;gap:8px;align-items:center;font:500 12px/1.2 system-ui,-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif}.am-dashboard-nav a{display:inline-flex;align-items:center;min-height:30px;padding:0 10px;border:1px solid rgba(128,128,128,.35);border-radius:999px;background:rgba(255,255,255,.94);color:#1f2937;text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,.08)}.am-dashboard-nav a:hover{background:#f2f4f7}@media(prefers-color-scheme:dark){.am-dashboard-nav a{background:rgba(31,35,42,.92);color:#f3f4f6;border-color:rgba(255,255,255,.25)}.am-dashboard-nav a:hover{background:rgba(55,60,68,.92)}}</style>`;
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

const HK_COMMERCIAL_AEROSPACE_ZH = {
  title: "香港商业航天监测",
  description: "上交所科创板 IPO 审核状态、Launch Library 2 发射频次、Celestrak 低轨卫星星座数量及商业航天企业专利申请统计。",
  cards: {
    ipo_race_card: { description: "头部商业火箭企业上交所科创板 IPO 审核状态。", metricLabels: ["蓝箭航天状态", "蓝箭审核号", "中科宇航状态", "中科宇航审核号"] },
    constellations_card: { description: "Celestrak 低轨卫星星座在轨卫星追踪数量。", metricLabels: ["千帆星座 (在轨数)", "吉林一号 (在轨数)", "商业发射总次数"] },
  },
  charts: {
    satellite_count_chart: ["中国商业卫星星座在轨数量", "Celestrak 追踪的千帆 (G60) 及吉林一号星座在轨活跃卫星数。", "星座", "卫星数"],
    patent_count_chart: ["商业火箭企业专利申请估算", "各火箭制造企业专利申请数量估算。", "企业", "专利数"],
    launch_cadence_chart: ["各商业航天企业发射次数统计", "Launch Library 2 追踪的历史商业发射次数。", "发射企业", "发射次数"],
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
  },
  sources: {
    sse_star_market_ipo: "上交所科创板 IPO 审核状态",
    launch_library_2: "Launch Library 2 商业发射数据库",
    celestrak: "Celestrak NORAD 卫星轨道数据",
    google_patents: "Google Patents 专利搜索",
  },
  snapshotBody: (artifact) =>
    `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody:
    "## 如何阅读本 dashboard\n\n中国商业航天板块受两大核心催化剂驱动：上交所科创板 IPO 审核进展（蓝箭航天 #2174、中科宇航 #2180）与低轨卫星星座组网（千帆 G60、吉林一号）。国网 (SatNet) Celestrak 标识未定，列为已知数据缝隙。本 dashboard 不提供股票排名、预测或投资建议。",
};

const HK_STABLECOIN_CRYPTO_ZH = {
  title: "香港稳定币与加密资产基础设施监测",
  description: "金管局持牌稳定币发行人沙盒名单、证监会持牌 VATP 虚拟资产交易平台、港交所加密 ETF 规模时间序列、全球稳定币市值趋势及 90 天市场走势。",
  cards: {
    regulatory_licensing_card: { description: "金管局稳定币沙盒持牌发行人及证监会持牌交易平台。", metricLabels: ["金管局稳定币发行人", "SFC 持牌 VATP", "SFC 申请中 VATP"] },
    crypto_signals_card: { description: "比特币现货价格、Coinbase 溢价价差及市场情绪指数。", metricLabels: ["比特币价格 (美元)", "Coinbase 溢价 (bps)", "恐慌与贪婪指数"] },
    etf_aum_card: { description: "港交所加密现货 ETF 资产规模及全球稳定币总市值。", metricLabels: ["港交所 ETF AUM (百万美元)", "全球稳定币市值 (十亿美元)"] },
  },
  charts: {
    etf_aum_history_chart: ["港交所加密现货 ETF 月度 AUM (百万美元)", "香港上市比特币及以太币现货 ETF 基金规模历史。", "月份", "AUM (百万美元)", "代码"],
    stablecoin_history_chart: ["全球稳定币总流通供应量趋势 (十亿美元)", "DefiLlama 统计的全球锚定资产流通市值扩张/收缩历史时间序列。", "日期", "总供应量 (十亿美元)"],
    fear_greed_history_chart: ["90 天加密情绪指数走势 (0–100)", "Alternative.me 每日恐慌与贪婪指数时间序列 (0=极度恐慌, 100=极度贪婪)。", "日期", "情绪得分"],
    btc_price_history_chart: ["90 天比特币现货价格走势 (美元)", "Binance 每日比特币收盘价时间序列。", "日期", "BTC 价格 (美元)"],
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
      title: "全球加密监管催化剂预测概率",
      subtitle: "Polymarket 预测市场对关键监管里程碑的实时概率预测。",
      columns: { title: "催化事件", probability_pct: "概率 (%)", end_date: "目标日期" },
    },
    crypto_watchlist_table: {
      title: "香港上市加密与稳定币观察名单 (Tiers 1–4)",
      subtitle: "Tier 1 持牌基础设施、Tier 2 大型机构、Tier 3 概念转型、Tier 4 储备配置。",
      columns: { tier: "分层", ticker: "股票代码", company_en: "英文名称", company_zh: "中文名称", regulatory_note: "监管状态 / 备注" },
    },
  },
  sources: {
    hkma_register: "香港金管局持牌稳定币发行人登记册",
    sfc_vatp: "香港证监会虚拟资产交易平台登记册",
    defillama: "DefiLlama 稳定币 API",
    hkex_etf: "港交所综合基金平台 ETF AUM API",
    coinbase_binance: "Coinbase & Binance 公开行情",
    fear_greed: "加密货币恐慌与贪婪指数",
    polymarket: "Polymarket Gamma 预测市场 API",
  },
  snapshotBody: (artifact) =>
    `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody:
    "## 如何阅读本 dashboard\n\n香港加密生态由官方监管登记册锚定：金管局稳定币发行人沙盒（Anchorpoint FRS01、汇丰 FRS02）及证监会持牌 VATP 交易平台（OSL、HashKey）。券商（如国泰君安国际 01788.HK）仅具备虚拟资产交易服务许可，非 VATP 交易所运营商；Anchorpoint（Anchorpoint Financial，港元锚定 HKDAP）与 AnchorX（金涌投资 01328.HK，AxCNH）为不同主体。本 dashboard 跟踪监管登记册、港交所 ETF AUM 时间序列、全球稳定币供应走势、90 天情绪及价格走势与 Coinbase 溢价信号。本界面不提供投资建议。",
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
  "hk-reit": HK_REIT_ZH,
  "hk-commercial-aerospace": HK_COMMERCIAL_AEROSPACE_ZH,
  "hk-stablecoin-crypto": HK_STABLECOIN_CRYPTO_ZH,
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
  // Both locales: the hub renders a download link per locale, so shipping only
  // the EN file left every ZH link pointing at a 404.
  const attachments = attachmentNames(sector, statusData);
  cpSync(enPortableFile, join(exportsDir, attachments.en));
  cpSync(zhPortableFile, join(exportsDir, attachments.zh));

  process.stdout.write(`[package-dashboard] Completed ${sector.id}.\n`);
}

process.stdout.write("[package-dashboard] All sector dashboards packaged successfully.\n");
