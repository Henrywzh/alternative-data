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
  },
  charts: {
    weather_trend: ["月度极端天气干扰时长 (小时)", "按月汇总的八号及以上热带气旋信号与红/黑色暴雨警告警告持续时间。", "月份", "小时"],
    fx_trend: ["港元 / 人民币交叉汇率 (月均)", "基于美联储 FRED 数据库发布的 DEXHKUS 与 DEXCHUS 每日汇率计算。", "月份", "人民币 / 100 港元"],
    travel_trend: ["陆路口岸每日人流 (7日移动平均)", "入境事务处发布的每日出入境旅客统计；北上为香港居民出境，南下为内地访客入境。", "日期", "人次"],
  },
  tables: {
    gold_table: {
      title: "周生生金价与原料成本对冲快照",
      subtitle: "周生生官方发布的足金首饰卖出价与伦敦金美元现货价对比。",
      columns: { date: "日期", chow_sang_sang_retail_hkd_tael: "周生生零售价 (港元/两)", spot_gold_usd_oz: "现货黄金 (美元/盎司)", implied_gold_cost_hkd_tael: "推算原料成本 (港元/两)", markup_pct: "溢价比例 (%)" },
    },
  },
  sources: {
    hko_signals: "香港天文台警告及信号数据库",
    fred_fx: "美联储 FRED 数据库 (DEXHKUS & DEXCHUS)",
    immd_passenger: "入境事务处每日出入境旅客流量统计",
    gold_price: "周生生官方金价 & 伦敦金现货市场",
  },
  snapshotBody: (artifact) =>
    `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody:
    "## 如何阅读本 dashboard\n\n本界面整合物理天气干扰、汇率环境、出入境流量与零售金价溢价等代理指标，以评估香港本地零售与餐饮业的宏观受压情况。",
};

const HK_UTILITIES_ZH = {
  title: "香港公用事业与基础设施监测",
  description: "中电控股（CLP）季度售电量拆解、中华煤气（Towngas）代理数据、香港天文台日均气温与电能实业（Power Assets）分部业绩快照。",
  cards: {
    clp_card: { label: "中电香港售电量 (GWh)", description: "季度中电香港本地售电总量；季环比与同比变动。", cadence: "季环比" },
    towngas_card: { label: "煤气代理消费量 (TJ)", description: "政府统计处月度全港煤气消费总量；月环比与同比变动。", cadence: "月环比" },
    hko_temp_card: { label: "天文台月均气温 (°C)", description: "香港天文台录得的月度平均气温；月环比与同比变动。", cadence: "月环比" },
  },
  charts: {
    clp_sector_chart: ["中电香港售电量按行业拆解 (GWh)", "季度售电量拆解为住宅、商业、基础设施与公共服务及制造行业。", "季度", "售电量 (GWh)"],
    towngas_user_chart: ["煤气代理消费量按用户类别拆解 (TJ)", "月度全港煤气消费总量拆解为住宅、商业及工业用户。", "月份", "消费量 (TJ)"],
    hko_temp_chart: ["香港天文台日均气温走势 (°C)", "每日平均气温与月度平均气温线，反映夏日用电负荷的物理驱动因素。", "日期", "气温 (°C)"],
  },
  tables: {
    power_assets_table: {
      title: "电能实业（Power Assets）按地理区域划分的分部业绩",
      subtitle: "半年度分部财务数据（收入与分部溢利），覆盖港灯投资、英国、澳洲及其他地区。",
      columns: { period: "期间", revenue_hkei_hkdm: "港灯收入 (百万港元)", profit_hkei_hkdm: "港灯溢利 (百万港元)", revenue_uk_hkdm: "英国收入 (百万港元)", profit_uk_hkdm: "英国溢利 (百万港元)", revenue_total_hkdm: "总收入 (百万港元)", segment_profit_total_hkdm: "总分部溢利 (百万港元)" },
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
  cards: {},
  charts: {},
  tables: {},
  sources: {
    linkreit_fundamentals: "领展房产基金（0823.HK）投资者关系披露",
    championreit_fundamentals: "冠君产业信托（2778.HK）财务披露",
    fortunereit_fundamentals: "置富产业信托（0778.HK）财务披露",
    prosperityreit_fundamentals: "繁荣产业信托（0808.HK）财务披露",
    sunlightreit_fundamentals: "阳光房地产基金（0435.HK）财务披露",
    regalreit_fundamentals: "富豪产业信托（1881.HK）酒店业绩披露",
  },
  snapshotBody: (artifact) => `**数据快照：** \`${artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。`,
  methodologyBody: "## 如何阅读本 dashboard\n\n各 REIT 涵盖不同物业类别（领展/置富为零售，冠君/阳光/繁荣为写字楼及零售，富豪为酒店）。富豪产业信托关注酒店指标（出租率、平均房价 ADR、RevPAR），其他 REIT 关注出租率与租金检讨调升率。本 dashboard 不提供股票排名、预测或投资建议。",
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
      card.metrics.forEach((metric, index) => {
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
  if (artifact.sources) {
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
  const runtime = await import(`file://${join(dirname(deliveryScript), "runtime.mjs")}`);
  verifyPortableArtifactStructure = runtime.verifyPortableArtifactStructure;
} catch (error) {
  process.stdout.write(`[package-dashboard] Portable builder unavailable (${error.message}); skipping dashboard packaging.\n`);
  process.exit(0);
}

for (const sector of SECTORS) {
  const statusPath = join(distDir, sector.statusFile);
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
