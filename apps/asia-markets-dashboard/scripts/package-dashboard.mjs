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
// Each sector supplies its own copy dict; localizeArtifact below is
// sector-agnostic and just looks values up by card/chart/table id.

const HK_REAL_ESTATE_ZH = {
  title: "香港房地产市场监测",
  description: "基于来源的住宅价格、租金和市场信心指标快照。",
  cards: {
    ccl_card: { label: "CCL", description: "最新发布指数；周环比与同比变动。", cadence: "周环比" },
    mhpi_card: { label: "MHPI", description: "最新发布指数；周环比与同比变动。", cadence: "周环比" },
    rvd_price_card: { label: "RVD 价格", description: "官方月度指数；月环比与同比变动。", cadence: "月环比" },
    rvd_rent_card: { label: "RVD 租金", description: "官方月度指数；月环比与同比变动。", cadence: "月环比" },
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
  description: "极端天气干扰时长、港元/人民币汇率、跨境出入境人流（北上/南下）、黄金原料成本与零售餐饮数据的来源快照。",
  cards: {
    weather_card: { label: "极端天气干扰 (小时/月)", description: "月度八号及以上风球与红/黑色暴雨警告总持续时长。" },
    fx_card: { label: "人民币 / 100 港元", description: "基于 FRED 每日报价计算的月度平均港元/人民币交叉汇率。" },
    northbound_card: { label: "北上人流 (7日均值，陆路口岸)", description: "每日经陆路口岸（不含机场及邮轮/渡轮码头）出境的香港居民人次（7日移动平均）；日环比与同比变动。", cadence: "日环比" },
    southbound_card: { label: "南下人流 (7日均值)", description: "每日内地访客入境人次（7日移动平均）；日环比与同比变动。", cadence: "日环比" },
    gold_card: { label: "黄金晚盘 (RMB/克)", description: "最新公布的上海金交所晚盘基准价；日环比与同比变动。", cadence: "日环比" },
    median_pe_card: { label: "市盈率中位数 (TTM)", description: "香港本地消费观察名单（11 家公司）的市盈率中位数。" },
    retail_card: { label: "零售销售指数", description: "全零售商总销货价值指数；月环比与同比变动。", cadence: "月环比" },
    restaurant_card: { label: "餐饮总收益 (百万港元)", description: "全行业季度餐饮收益；季环比与同比变动。", cadence: "季环比" },
  },
  charts: {
    severe_weather_trend: ["月度极端天气干扰时长", "香港八号及以上热带气旋风球与红/黑色暴雨警告的月度总时长（小时）。", "月份", "干扰时长 (小时)"],
    immigration_trend: ["跨境旅客流量走势 (7日均值)", "每日人流方向：北上（香港居民出境人次）对比 南下（内地访客入境人次）。", "日期", "人次 / 日 (7日均值)", "人流方向"],
    gold_trend: ["上海黄金交易所晚盘基准价", "以人民币/克计的每日定盘价，近约7年；是香港黄金珠宝行业原料成本的主要参考。", "日期", "人民币/克"],
    afcd_category_chart: ["按类别划分的 AFCD 批发价", "今日各类别商品的平均批发价（每公斤）。", "类别", "港元/公斤"],
    valuation_pe_chart: ["观察名单市盈率对比", "各公司最新的正值市盈率（TTM）；亏损公司不在此图中显示。", "公司", "市盈率 (TTM)"],
    retail_trend: ["零售销售价值指数（全零售商）", "政府统计处月度价值指数，完整已公布历史。", "月份", "价值指数"],
    retail_category_chart: ["按类别划分的零售销售价值指数", "最新已公布月份，按零售商类型划分。", "类别", "价值指数"],
    restaurant_trend: ["餐饮收益（全行业）", "季度全行业收益，百万港元，完整已公布历史。", "季度", "百万港元"],
    restaurant_chart: ["按类型划分的餐饮收益", "最新已公布季度，百万港元。", "餐饮类型", "百万港元"],
  },
  tables: {
    severe_weather_log_table: {
      title: "近期极端天气警告日志",
      subtitle: "近期红/黑色暴雨及八号以上风球警告的生效时间、解除时间与持续时长。",
      columns: { signal_name: "警告信号", start: "生效时间 (HKT)", end: "解除时间 (HKT)", duration_hours: "持续时长 (小时)" },
    },
    afcd_commodity_table: {
      title: "AFCD 批发价快照",
      subtitle: "当日各商品平均价格，港元/公斤（由公布的港元/斤换算而来）。",
      columns: { category: "类别", commodity_name: "商品", avg_price_hkd_per_kg: "港元/公斤", num_readings: "读数个数" },
    },
    valuation_table: {
      title: "消费观察名单估值快照",
      subtitle: "各公司最新的市盈率、市净率与市值。",
      columns: { company_name: "公司", ticker: "股票代码", pe_ttm: "市盈率(TTM)", pb_ratio: "市净率", market_cap_hkd_b: "市值(十亿港元)", date: "截至日期" },
    },
    retail_category_table: {
      title: "按类别划分的零售销售快照",
      subtitle: "最新已公布月份；按零售商类型划分的价值与数量指数。",
      columns: { category: "类别", sales_value_index: "价值指数", sales_volume_index: "数量指数", date: "截至日期" },
    },
    restaurant_snapshot_table: {
      title: "按类型划分的餐饮收益快照",
      subtitle: "最新已公布季度；采购额仅在「全行业」总计中提供。",
      columns: { sub_sector: "餐饮类型", total_receipts_hkd_m: "收益(百万港元)", total_purchases_hkd_m: "采购额(百万港元)", receipts_value_index: "收益价值指数", date: "截至日期" },
    },
    source_health_table: {
      title: "实时来源健康度",
      subtitle: "以上指标的构建时校验结果。",
      columns: { dataset: "数据集", status: "状态", latest_observation: "最新日期", records: "记录数", freshness: "新鲜度", notes: "备注" },
    },
    coverage_table: {
      title: "覆盖范围与下一步采集目标",
      subtitle: "端点损坏或未经验证的来源在此处追踪，而不是以占位值展示。",
      columns: { source: "来源", dataset: "数据集", type: "类型", status: "状态", freshness: "新鲜度", notes: "范围 / 限制" },
    },
  },
  sources: {
    weather_demand_drivers: "香港天文台暴雨/风球警告数据库 & FRED 汇率",
    immigration_flow: "香港入境事务处每日出入境旅客流量",
    afcd_wholesale: "农渔护理署鲜活食品批发价",
    sge_gold: "上海黄金交易所早/晚盘基准价",
    hk_valuation: "百度股市通港股估值",
    cnsd_retail: "政府统计处零售业销货额指数",
    censtatd_restaurant: "政府统计处季度食肆收益及购货额按月统计调查",
    source_registry: "香港本地消费 dashboard 来源登记表",
  },
  snapshotBody: (artifact) =>
    `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。这是已发布快照，不是实时连接；消费者委员会价格观察覆盖仍在计划中，未以占位值展示。`,
  methodologyBody:
    "## 如何阅读本 dashboard\n\n极端天气干扰时长（八号风球及红/黑雨）用于评估客流压制效应。港元/人民币汇率反映港人赴深消费性价比。黄金是珠宝行业原料成本参考而非股价预测。本 dashboard 不提供股票排名、预测或投资建议。",
};

const HK_UTILITIES_ZH = {
  title: "香港公用事业与基础设施监测",
  description: "CLP 售电量分行业结构、Towngas 燃气消费量与天文台日均气温的来源快照。",
  cards: {},
  charts: {},
  tables: {},
  sources: {
    clp_electricity: "中电控股 (CLP) 季度售电量披露",
    towngas_proxy: "政府统计处能源统计 (Towngas 燃气消费量代理)",
    hko_temperature: "香港天文台日平均气温",
  },
  snapshotBody: (artifact) => `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody: "## 如何阅读本 dashboard\n\n售电量与燃气消费量反映香港公用事业核心业务运营水平；日均气温为夏日用电负荷的物理驱动因素。",
};

const HK_TRANSPORT_ZH = {
  title: "香港交通与航空监测",
  description: "港铁月度客运量（本地/跨境/高铁）、国泰航空运营数据与香港国际机场流量的来源快照。",
  cards: {},
  charts: {},
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
    hkt_card: { label: "香港电讯 后付费 ARPU (港元)", description: "半年度后付费退出 ARPU 及后付费用户数（千户）。", cadence: "半年环比" },
    smartone_card: { label: "数码通 后付费 ARPU (港元)", description: "半年度后付费 ARPU 及后付费用户数（千户）。", cadence: "同比" },
    hutchison_card: { label: "和记电讯（3 HK）后付费毛 ARPU (港元)", description: "半年度后付费毛/净 ARPU。", cadence: "半年环比" },
  },
  charts: {
    hkt_arpu_chart: ["香港电讯后付费退出 ARPU 走势 (港元)", "半年度后付费退出 ARPU，取自香港电讯自身业绩公告的叙述文本。", "期间", "港元"],
    smartone_arpu_chart: ["数码通后付费 ARPU 与用户数走势", "半年度后付费 ARPU（港元）及后付费用户基础（千户）。", "期间", "港元"],
    hutchison_arpu_chart: ["和记电讯（3 HK）后付费毛/净 ARPU 对比", "半年度后付费毛 ARPU 与净 ARPU（港元）——三家运营商中披露最细的单用户经济数据。", "期间", "港元"],
  },
  tables: {
    numbering_plan_table: {
      title: "通讯办按运营商划分的手机号码段配额",
      subtitle: "覆盖全部 4 家持牌移动网络运营商及虚拟运营商的粗略结构性代理指标。号码段是已发放的号码容量，并非在网用户数——无法得知已分配号码段的实际使用比例，且重新分配为不定期、事件驱动式。请将此视为单一容量快照，而非用户数走势。",
      columns: { allocatee: "运营商 / 持牌人", num_blocks: "号码段数量", total_numbers_allocated: "已分配号码数" },
    },
  },
  sources: {
    hkt_operating_drivers: "香港电讯信托及香港电讯有限公司（6823.HK）业绩公告",
    smartone_operating_drivers: "数码通电讯控股（0315.HK）业绩简报",
    hutchison_telecom_operating_drivers: "和记电讯香港控股（0215.HK，「3 HK」）业绩公告",
    numbering_plan: "通讯事务管理局办公室编号计划（手机号码段配额）",
  },
  snapshotBody: (artifact) => `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。这是已发布快照，不是实时连接。`,
  methodologyBody:
    "## 如何阅读本 dashboard\n\n三家运营商的后付费 ARPU 与用户数均取自其各自的 HKEX 业绩公告或投资者简报的叙述文本或表格，半年度更新。手机号码段配额表是粗略的全运营商结构性代理指标，反映已发放容量而非在网用户数，更新不定期，不应被解读为用户数走势。本 dashboard 不提供股票排名、预测或投资建议。",
};

function localizeArtifact(input, zh) {
  const artifact = JSON.parse(JSON.stringify(input));
  artifact.manifest.title = zh.title;
  artifact.manifest.description = zh.description;
  artifact.manifest.cards.forEach((card) => {
    const copy = zh.cards[card.id];
    if (!copy) return;
    card.description = copy.description;
    card.metrics.forEach((metric, index) => {
      if (index === 0) metric.label = copy.label;
      if (index === 1 && copy.cadence) metric.label = copy.cadence;
      if (index === 2) metric.label = "同比";
    });
  });
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
  artifact.manifest.tables.forEach((table) => {
    const copy = zh.tables[table.id];
    if (!copy) return;
    table.title = copy.title;
    table.subtitle = copy.subtitle;
    table.columns.forEach((column) => {
      if (copy.columns[column.field]) column.label = copy.columns[column.field];
    });
  });
  artifact.manifest.sources = artifact.manifest.sources.map((source) => ({
    ...source,
    label: zh.sources[source.id] || source.label,
  }));
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
  const snapshot = artifact.manifest.blocks.find((block) => block.id === "snapshot_context");
  if (snapshot) snapshot.body = zh.snapshotBody(artifact);
  const methodology = artifact.manifest.blocks.find((block) => block.id === "methodology");
  if (methodology) methodology.body = zh.methodologyBody;
  return artifact;
}

function addNavigation(html, { locale, homeEn, homeZh, routeEn, routeZh }) {
  const chinese = locale === "zh";
  const home = chinese ? homeZh : homeEn;
  const languageHref = chinese ? routeEn : routeZh;
  const backLabel = chinese ? "← 返回主 dashboard" : "← Back to main dashboard";
  const languageLabel = chinese ? "English" : "简体中文";
  const css = `<style>.am-dashboard-nav{position:fixed;top:12px;left:12px;z-index:1000;display:flex;gap:8px;align-items:center;font:500 12px/1.2 system-ui,-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif}.am-dashboard-nav a{display:inline-flex;align-items:center;min-height:30px;padding:0 10px;border:1px solid rgba(128,128,128,.35);border-radius:999px;background:rgba(255,255,255,.94);color:#1f2937;text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,.08)}.am-dashboard-nav a:hover{background:#f2f4f7}@media(prefers-color-scheme:dark){.am-dashboard-nav a{background:rgba(25,25,25,.94);color:#f3f4f6;border-color:rgba(255,255,255,.25)}}</style>`;
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
];

if (!existsSync(distDir)) {
  throw new Error("Run the static hub build step before packaging dashboards.");
}

mkdirSync(generatedDir, { recursive: true });
let deliveryScript = null;
let verifyPortableArtifactStructure = null;
try {
  deliveryScript = findPortableBuilder();
  const portableModuleRoot = dirname(deliveryScript);
  ({ verifyPortableArtifactStructure } = await import(join(portableModuleRoot, "verify_portable_artifact.mjs")));
} catch (err) {
  deliveryScript = null;
  verifyPortableArtifactStructure = null;
  console.warn("Portable builder not available in this environment; falling back to committed .generated/*.html artifacts:", err.message);
}

async function packageLocale({ deliveryScript, artifact: localeArtifact, artifactFile, portableFile, locale, route, attachment, homeEn, homeZh, routeEn, routeZh }) {
  let receipt = { ok: true, stages: { verification: "passed (pre-built)" } };
  let html = "";
  if (deliveryScript) {
    writeFileSync(artifactFile, `${JSON.stringify(localeArtifact, null, 2)}\n`, "utf8");
    receipt = await deliverPortable({ deliveryScript, artifactFile, portableFile, locale });
    html = addNavigation(readFileSync(portableFile, "utf8"), { locale, homeEn, homeZh, routeEn, routeZh });
    writeFileSync(portableFile, html, "utf8");
    const structural = verifyPortableArtifactStructure({ artifactPath: artifactFile, htmlPath: portableFile });
    if (!structural?.ok) throw new Error(`Portable dashboard structural verification failed (${locale}): ${JSON.stringify(structural)}`);
  } else if (existsSync(portableFile)) {
    html = readFileSync(portableFile, "utf8");
    if (!html.includes("am-dashboard-nav")) {
      html = addNavigation(html, { locale, homeEn, homeZh, routeEn, routeZh });
      writeFileSync(portableFile, html, "utf8");
    }
  } else {
    throw new Error(`Missing portable HTML artifact ${portableFile} and portable builder is not available.`);
  }

  const svgCount = (html.match(/<svg\b/gu) || []).length;
  const expectedCharts = Array.isArray(localeArtifact?.manifest?.charts) ? localeArtifact.manifest.charts.length : 0;
  if (svgCount < expectedCharts) {
    throw new Error(`Portable dashboard static chart gate failed (${locale}): found ${svgCount} SVGs for ${expectedCharts} charts.`);
  }
  const routePath = join(distDir, route, "index.html");
  const attachmentPath = join(distDir, "exports", attachment);
  mkdirSync(dirname(routePath), { recursive: true });
  mkdirSync(dirname(attachmentPath), { recursive: true });
  cpSync(portableFile, routePath);
  cpSync(portableFile, attachmentPath);
  const routeHash = sha256(routePath);
  const attachmentHash = sha256(attachmentPath);
  if (routeHash !== attachmentHash) throw new Error(`Hosted ${locale} dashboard and Gmail attachment differ after packaging.`);
  return { locale, route: `/${route}/`, attachment: `/exports/${attachment}`, sha256: routeHash, bytes: readFileSync(routePath).byteLength, svg_count: svgCount, portable_verification: receipt.stages.verification };
}

// Each (sector, locale) pair spawns its own delivery-script subprocess, which
// in turn uses a uniquely-named mkdtemp() directory (see
// verify_portable_artifact.mjs's `temporaryDirectory` and
// deliver_portable_artifact.mjs's `pid-randomUUID` candidate output file) and
// its own `--user-data-dir` for the headless Chromium instance it launches.
// No shared temp paths, ports, or lock files are involved, so concurrent
// invocations are safe. We still cap concurrency (rather than firing all 10
// at once) since each spawns a real Chromium process and this machine has
// finite memory/CPU.
async function runWithConcurrency(taskThunks, limit) {
  const results = new Array(taskThunks.length);
  let nextIndex = 0;
  async function worker() {
    while (nextIndex < taskThunks.length) {
      const current = nextIndex;
      nextIndex += 1;
      results[current] = await taskThunks[current]();
    }
  }
  const workerCount = Math.min(limit, taskThunks.length);
  await Promise.all(Array.from({ length: workerCount }, worker));
  return results;
}

const sectorMeta = [];
const packagingTasks = [];
for (const sector of SECTORS) {
  const artifactPath = join(generatedDir, `${sector.id}-artifact.json`);
  const artifactZhPath = join(generatedDir, `${sector.id}-artifact-zh.json`);
  const portablePath = join(generatedDir, `${sector.id}-dashboard.html`);
  const portableZhPath = join(generatedDir, `${sector.id}-dashboard-zh.html`);
  const statusPath = join(projectRoot, "src/data", sector.statusFile);
  if (!existsSync(artifactPath) || !existsSync(statusPath)) {
    throw new Error(`Run the refresh step for ${sector.id} before packaging (missing ${artifactPath} or ${statusPath}).`);
  }
  const artifact = JSON.parse(readFileSync(artifactPath, "utf8"));
  const status = JSON.parse(readFileSync(statusPath, "utf8"));
  const dateSuffix = status.attachment_filename.replace(`${sector.id}-dashboard-`, "");
  const homeEn = "https://asia-markets-dashboard.pages.dev/";
  const homeZh = "https://asia-markets-dashboard.pages.dev/zh/";
  const routeEn = `https://asia-markets-dashboard.pages.dev/sectors/${sector.id}/`;
  const routeZh = `https://asia-markets-dashboard.pages.dev/sectors/${sector.id}/zh/`;

  const releaseIndexes = [];
  releaseIndexes.push(packagingTasks.length);
  packagingTasks.push(() => packageLocale({
    deliveryScript, artifact, artifactFile: artifactPath, portableFile: portablePath, locale: "en",
    route: `sectors/${sector.id}`, attachment: status.attachment_filename, homeEn, homeZh, routeEn, routeZh,
  }));
  releaseIndexes.push(packagingTasks.length);
  packagingTasks.push(() => packageLocale({
    deliveryScript, artifact: localizeArtifact(artifact, sector.zh), artifactFile: artifactZhPath, portableFile: portableZhPath, locale: "zh",
    route: `sectors/${sector.id}/zh`, attachment: `${sector.id}-dashboard-zh-${dateSuffix}`, homeEn, homeZh, routeEn, routeZh,
  }));

  sectorMeta.push({ sector: sector.id, generated_at: status.generated_at, snapshot_id: status.snapshot_id, data_as_of: status.data_as_of, releaseIndexes });
}

const PACKAGING_CONCURRENCY = Math.max(1, Number(process.env.PORTABLE_PACKAGING_CONCURRENCY || 4));
const packagingResults = await runWithConcurrency(packagingTasks, PACKAGING_CONCURRENCY);

const sectorReleases = sectorMeta.map(({ releaseIndexes, ...meta }) => ({
  ...meta,
  releases: releaseIndexes.map((index) => packagingResults[index]),
}));

mkdirSync(join(distDir, "data"), { recursive: true });
writeFileSync(join(distDir, "data/release.json"), `${JSON.stringify({ sectors: sectorReleases }, null, 2)}\n`, "utf8");
process.stdout.write(`${JSON.stringify({ ok: true, sectors: sectorReleases })}\n`);
