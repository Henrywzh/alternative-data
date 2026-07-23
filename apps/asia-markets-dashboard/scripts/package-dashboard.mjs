#!/usr/bin/env node

import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const generatedDir = join(projectRoot, ".generated");
const artifactPath = join(generatedDir, "hk-real-estate-artifact.json");
const artifactZhPath = join(generatedDir, "hk-real-estate-artifact-zh.json");
const portablePath = join(generatedDir, "hk-real-estate-dashboard.html");
const portableZhPath = join(generatedDir, "hk-real-estate-dashboard-zh.html");
const statusPath = join(projectRoot, "src/data/dashboard-status.json");
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

const ZH = {
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
};

function localizeArtifact(input) {
  const artifact = JSON.parse(JSON.stringify(input));
  artifact.manifest.title = "香港房地产市场监测";
  artifact.manifest.description = "基于来源的住宅价格、租金和市场信心指标快照。";
  artifact.manifest.cards.forEach((card) => {
    const copy = ZH.cards[card.id];
    if (!copy) return;
    card.description = copy.description;
    card.metrics.forEach((metric, index) => {
      if (index === 0) metric.label = copy.label;
      if (index === 1) metric.label = copy.cadence;
      if (index === 2) metric.label = "同比";
    });
  });
  artifact.manifest.charts.forEach((chart) => {
    const copy = ZH.charts[chart.id];
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
    const copy = ZH.tables[table.id];
    if (!copy) return;
    table.title = copy.title;
    table.subtitle = copy.subtitle;
    table.columns.forEach((column) => {
      if (copy.columns[column.field]) column.label = copy.columns[column.field];
    });
  });
  artifact.manifest.sources = artifact.manifest.sources.map((source) => ({
    ...source,
    label: ZH.sources[source.id] || source.label,
  }));
  artifact.sources = artifact.sources.map((source) => ({
    ...source,
    label: ZH.sources[source.id] || source.label,
    query: source.query ? {
      ...source.query,
      description: source.query.description
        ? `构建时从公开来源读取并校验 ${ZH.sources[source.id] || source.label}。`
        : source.query.description,
    } : source.query,
  }));
  const snapshot = artifact.manifest.blocks.find((block) => block.id === "snapshot_context");
  if (snapshot) {
    snapshot.body = `**数据快照：** \`${artifact.snapshot.datasets.kpi_ccl?.[0]?.snapshot_id || artifact.package_info.snapshotId}\` · 生成于 ${artifact.manifest.generatedAt}。这是已发布快照，不是实时连接；RVD 标记为 provisional 的观测可能会修订。`;
  }
  const methodology = artifact.manifest.blocks.find((block) => block.id === "methodology");
  if (methodology) {
    methodology.body = "## 如何阅读本 dashboard\n\n不同发布方的指数基期不同。请在重设基准图中比较方向，不要直接比较原始数值水平。覆盖表区分实时指标、来源目录和计划中的采集工作。本 dashboard 不提供股票排名、预测或投资建议。";
  }
  artifact.package_info.originUrl = "https://asia-markets-dashboard.pages.dev/sectors/hk-real-estate/zh/";
  return artifact;
}

function addNavigation(html, locale) {
  const chinese = locale === "zh";
  const home = chinese ? "https://asia-markets-dashboard.pages.dev/zh/" : "https://asia-markets-dashboard.pages.dev/";
  const languageHref = chinese
    ? "https://asia-markets-dashboard.pages.dev/sectors/hk-real-estate/"
    : "https://asia-markets-dashboard.pages.dev/sectors/hk-real-estate/zh/";
  const backLabel = chinese ? "← 返回主 dashboard" : "← Back to main dashboard";
  const languageLabel = chinese ? "English" : "简体中文";
  const css = `<style>.am-dashboard-nav{position:fixed;top:12px;left:12px;z-index:1000;display:flex;gap:8px;align-items:center;font:500 12px/1.2 system-ui,-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif}.am-dashboard-nav a{display:inline-flex;align-items:center;min-height:30px;padding:0 10px;border:1px solid rgba(128,128,128,.35);border-radius:999px;background:rgba(255,255,255,.94);color:#1f2937;text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,.08)}.am-dashboard-nav a:hover{background:#f2f4f7}@media(prefers-color-scheme:dark){.am-dashboard-nav a{background:rgba(25,25,25,.94);color:#f3f4f6;border-color:rgba(255,255,255,.25)}}</style>`;
  const nav = `<nav class="am-dashboard-nav" aria-label="Dashboard navigation"><a href="${home}">${backLabel}</a><a href="${languageHref}">${languageLabel}</a></nav>`;
  return html.replace("</head>", `${css}</head>`).replace("<body>", `<body>${nav}`);
}

function deliverPortable({ artifactFile, portableFile, locale }) {
  const failureScreenshot = join(generatedDir, `portable-verification-failure-${locale}.png`);
  const maxAttempts = Math.max(1, Number(process.env.PORTABLE_DELIVERY_RETRIES || 2));
  let lastDelivery = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const delivery = spawnSync(process.execPath, [
      deliveryScript,
      "--input", artifactFile,
      "--output", portableFile,
      "--screenshot", failureScreenshot,
      "--ready-timeout-ms", process.env.PORTABLE_READY_TIMEOUT_MS || "30000",
      "--action-timeout-ms", process.env.PORTABLE_ACTION_TIMEOUT_MS || "10000",
      "--timeout-ms", process.env.PORTABLE_VERIFY_TIMEOUT_MS || "60000",
    ], { cwd: projectRoot, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
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

if (!existsSync(artifactPath) || !existsSync(statusPath) || !existsSync(distDir)) {
  throw new Error("Run the refresh and static hub build steps before packaging the dashboard.");
}

mkdirSync(generatedDir, { recursive: true });
const deliveryScript = findPortableBuilder();
const portableModuleRoot = dirname(deliveryScript);
const { verifyPortableArtifactStructure } = await import(join(portableModuleRoot, "verify_portable_artifact.mjs"));
const artifact = JSON.parse(readFileSync(artifactPath, "utf8"));
const status = JSON.parse(readFileSync(statusPath, "utf8"));
function packageLocale({ artifact: localeArtifact, artifactFile, portableFile, locale, route, attachment }) {
  writeFileSync(artifactFile, `${JSON.stringify(localeArtifact, null, 2)}\n`, "utf8");
  const receipt = deliverPortable({ artifactFile, portableFile, locale });
  const html = addNavigation(readFileSync(portableFile, "utf8"), locale);
  writeFileSync(portableFile, html, "utf8");
  const structural = verifyPortableArtifactStructure({ artifactPath: artifactFile, htmlPath: portableFile });
  if (!structural?.ok) throw new Error(`Portable dashboard structural verification failed (${locale}): ${JSON.stringify(structural)}`);
  const svgCount = (html.match(/<svg\b/gu) || []).length;
  const expectedCharts = Array.isArray(localeArtifact.manifest?.charts) ? localeArtifact.manifest.charts.length : 0;
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

const dateSuffix = status.attachment_filename.replace(/^hk-real-estate-dashboard-/, "");
const releases = [
  packageLocale({ artifact, artifactFile: artifactPath, portableFile: portablePath, locale: "en", route: "sectors/hk-real-estate", attachment: status.attachment_filename }),
  packageLocale({ artifact: localizeArtifact(artifact), artifactFile: artifactZhPath, portableFile: portableZhPath, locale: "zh", route: "sectors/hk-real-estate/zh", attachment: `hk-real-estate-dashboard-zh-${dateSuffix}` }),
];
const release = { generated_at: status.generated_at, snapshot_id: status.snapshot_id, data_as_of: status.data_as_of, releases };
mkdirSync(join(distDir, "data"), { recursive: true });
writeFileSync(join(distDir, "data/release.json"), `${JSON.stringify(release, null, 2)}\n`, "utf8");
process.stdout.write(`${JSON.stringify({ ok: true, release })}\n`);
