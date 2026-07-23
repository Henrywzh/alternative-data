import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.resolve(here, "..");
const dist = path.join(appRoot, "dist");
const statusPath = path.join(appRoot, "src", "data", "dashboard-status.json");
const status = JSON.parse(fs.readFileSync(statusPath, "utf8"));

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#39;");

const css = fs.readFileSync(path.join(appRoot, "src", "styles", "global.css"), "utf8");

function layout({ title, description, body, lang = "en", homeHref = "/", statusHref = "/data-status/", languageHref = "/zh/", languageLabel = "简体中文" }) {
  const chinese = lang === "zh-CN";
  return `<!doctype html>
<html lang="${lang}">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width" />
    <meta name="description" content="${escapeHtml(description)}" />
    <meta name="robots" content="noindex, nofollow" />
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <style>${css}</style>
    <title>${escapeHtml(title)}</title>
  </head>
  <body>
    <header class="site-header">
      <a class="brand" href="${homeHref}" aria-label="Asia Markets home">
        <span class="brand-mark" aria-hidden="true">AM</span>
        <span>Asia Markets</span>
      </a>
      <nav aria-label="Primary"><a href="${homeHref}">${chinese ? "板块" : "Sectors"}</a><a href="${statusHref}">${chinese ? "数据状态" : "Data status"}</a><a href="${languageHref}">${languageLabel}</a></nav>
    </header>
    <main>${body}</main>
    <footer><span>Published research snapshots</span><span>Not investment advice</span></footer>
  </body>
</html>`;
}

const sectors = [
  ["01", "Hong Kong Real Estate", status.overall_status, `${status.live_sources} live measures · data through ${status.data_as_of}`, "/sectors/hk-real-estate/", "Open monitor", true],
  ["02", "Stablecoin & Crypto", "Research ready", "Source map and company coverage complete; dashboard not yet published.", "#future-sectors", "Planned", false],
  ["03", "Commercial Aerospace", "Research ready", "Company and signal framework complete; dashboard not yet published.", "#future-sectors", "Planned", false],
  ["04", "Consumer Trends", "Research", "Company list established; source access remains uneven.", "#future-sectors", "Planned", false],
];

const sectorRows = sectors.map(([code, name, state, detail, href, action, live]) => `
      <a class="sector-row${live ? " sector-row-live" : ""}" href="${href}" aria-label="${escapeHtml(name)}: ${escapeHtml(action)}">
        <span class="sector-code">${code}</span>
        <span class="sector-main"><strong>${escapeHtml(name)}</strong><small>${escapeHtml(detail)}</small></span>
        <span class="sector-state"><i aria-hidden="true"></i>${escapeHtml(state)}</span>
        <span class="sector-action">${escapeHtml(action)}<b aria-hidden="true">↗</b></span>
      </a>`).join("");

const homeBody = `
  <section class="workspace-intro"><div><p class="eyebrow">Research monitors / 2026</p><h1>Sector signals,<br />with the source trail intact.</h1></div>
    <div class="intro-meta"><span>Latest release</span><strong>${escapeHtml(status.generated_at.slice(0, 10))}</strong><span>HK real estate snapshot</span><code>${escapeHtml(status.snapshot_id)}</code></div>
  </section>
  <section class="sector-index" aria-labelledby="sector-heading"><div class="section-heading"><h2 id="sector-heading">Sector index</h2><p>Published surfaces first; research-only sectors remain clearly labeled.</p></div><div class="sector-list">${sectorRows}
  </div></section>
  <section class="release-panel" id="future-sectors"><div><p class="eyebrow">Portable release</p><h2>Take the real-estate monitor offline.</h2><p>The hosted page and the downloadable HTML are generated from the same validated snapshot and contain identical dashboard bytes.</p></div>
    <div class="release-actions"><a class="primary-action" href="/exports/${escapeHtml(status.attachment_filename)}" download>Download offline HTML</a><a class="text-action" href="/data-status/">Inspect source status →</a></div>
  </section>`;

const sourceRows = status.sources.map((source) => `<tr><td><strong>${escapeHtml(source.dataset)}</strong><small>${escapeHtml(source.source)}</small></td><td>${escapeHtml(source.type)}</td><td><span class="status-label${source.status === "Healthy" ? " status-good" : ""}">${escapeHtml(source.status)}</span></td><td>${escapeHtml(source.latest_observation)}</td><td>${escapeHtml(source.records || "—")}</td><td><strong>${escapeHtml(source.freshness)}</strong><small>${escapeHtml(source.notes)}</small></td></tr>`).join("");
const statusBody = `
  <section class="status-intro"><div><p class="eyebrow">Release control</p><h1>Data status</h1><p>One compact view of what is live, partial, catalog-only, or still planned.</p></div>
    <dl class="status-summary"><div><dt>Overall</dt><dd class="healthy">${escapeHtml(status.overall_status)}</dd></div><div><dt>Data as of</dt><dd>${escapeHtml(status.data_as_of)}</dd></div><div><dt>Generated</dt><dd>${escapeHtml(status.generated_at.replace("T", " ").slice(0, 19))} UTC</dd></div><div><dt>Snapshot</dt><dd><code>${escapeHtml(status.snapshot_id)}</code></dd></div></dl>
  </section>
  <section class="status-table-section"><div class="section-heading"><h2>HK real-estate coverage</h2><p>Catalog discovery is not counted as a live market measure.</p></div><div class="table-wrap"><table><thead><tr><th>Source / dataset</th><th>Type</th><th>Status</th><th>Latest</th><th>Rows</th><th>Freshness / caveat</th></tr></thead><tbody>${sourceRows}</tbody></table></div></section>`;

fs.rmSync(dist, { recursive: true, force: true });
fs.mkdirSync(dist, { recursive: true });
fs.mkdirSync(path.join(dist, "data-status"), { recursive: true });
fs.writeFileSync(path.join(dist, "index.html"), layout({ title: "Asia Markets — Research Monitors", description: "Source-backed Asia market research dashboards and published data snapshots.", body: homeBody }));
fs.writeFileSync(path.join(dist, "data-status", "index.html"), layout({ title: "Data Status — Asia Markets", description: "Freshness, coverage and release metadata for Asia Markets dashboards.", body: statusBody }));
fs.writeFileSync(path.join(dist, "404.html"), layout({ title: "Not found — Asia Markets", description: "The requested page was not found.", body: "<section class=\"status-intro\"><div><p class=\"eyebrow\">404</p><h1>Page not found</h1><p><a class=\"text-action\" href=\"/\">Return to the sector index →</a></p></div></section>" }));

const zhSourceNames = {
  "Centaline City Leading Index (CCL)": "中原城市领先指数（CCL）",
  "Midland Realty Market Insight — MHPI": "美联物业市场资讯 — MHPI",
  "Midland Realty Market Insight — Confidence Index": "美联物业市场资讯 — 信心指数",
  "Rating and Valuation Department — Private Domestic Price Index": "差饷物业估价署 — 私人住宅售价指数",
  "Rating and Valuation Department — Private Domestic Rental Index": "差饷物业估价署 — 私人住宅租金指数",
  "Agency transactions": "代理成交",
  "Buildings Department": "屋宇署",
  "Land Registry": "土地注册处",
};
const zhDatasetNames = {
  "Centaline CCL": "中原 CCL",
  "Midland MHPI": "美联 MHPI",
  "Midland Confidence Index": "美联信心指数",
  "RVD Residential Price Index": "RVD 住宅价格指数",
  "RVD Residential Rental Index": "RVD 住宅租金指数",
  "Centaline / Midland / 28Hse transactions": "中原 / 美联 / 28Hse 成交",
  "First-hand residential project documents": "一手住宅项目文件",
  "Registered sale and purchase facts": "注册买卖事实",
  "Approvals, starts and occupation permits": "审批、开工及入伙纸",
};
const zhType = { Measure: "指标", Catalog: "目录" };
const zhStatus = { Healthy: "健康", Planned: "计划中", "Catalog only": "仅目录" };
const zhFreshness = (value) => String(value).replace("old", "前").replace("Not ingested", "尚未采集").replace("Content parser pending", "内容解析器待完成");
const zhNotes = (value) => String(value)
  .replace("Latest observation is published without a provisional flag.", "最新观测已发布，未标记 provisional。")
  .replace("Latest observation is provisional.", "最新观测为 provisional。")
  .replace("High-value index source; endpoint and history contract still require validation.", "高价值指数来源；仍需验证 endpoint 与历史数据契约。")
  .replace("Target is a deduplicated near-real-time transaction activity measure.", "目标是去重后的近实时成交活动指标。")
  .replace("Current discovery code does not yet extract sales, units, price lists, or absorption facts.", "当前发现代码尚未提取销售、单位数、价单或吸纳事实。")
  .replace("Current code discovers releases; fact extraction and point-in-time semantics remain pending.", "当前代码可发现发布内容；事实提取与时点语义仍待完成。")
  .replace("Monthly digest discovery exists; structured project facts are not yet extracted.", "已有月度摘要发现；结构化项目事实尚未提取。");
const zhSourceRows = status.sources.map((source) => `<tr><td><strong>${escapeHtml(zhDatasetNames[source.dataset] || source.dataset)}</strong><small>${escapeHtml(zhSourceNames[source.source] || source.source)}</small></td><td>${escapeHtml(zhType[source.type] || source.type)}</td><td><span class="status-label${source.status === "Healthy" ? " status-good" : ""}">${escapeHtml(zhStatus[source.status] || source.status)}</span></td><td>${escapeHtml(source.latest_observation)}</td><td>${escapeHtml(source.records || "—")}</td><td><strong>${escapeHtml(zhFreshness(source.freshness))}</strong><small>${escapeHtml(zhNotes(source.notes))}</small></td></tr>`).join("");
const zhHomeBody = `
  <section class="workspace-intro"><div><p class="eyebrow">研究监测 / 2026</p><h1>板块信号，<br />保留完整来源链。</h1></div>
    <div class="intro-meta"><span>最新发布</span><strong>${escapeHtml(status.generated_at.slice(0, 10))}</strong><span>香港房地产快照</span><code>${escapeHtml(status.snapshot_id)}</code></div>
  </section>
  <section class="sector-index" aria-labelledby="sector-heading"><div class="section-heading"><h2 id="sector-heading">板块目录</h2><p>先展示已发布页面；仅研究板块会明确标记。</p></div><div class="sector-list">
    <a class="sector-row sector-row-live" href="/sectors/hk-real-estate/zh/" aria-label="香港房地产：打开监测"><span class="sector-code">01</span><span class="sector-main"><strong>香港房地产</strong><small>${status.live_sources} 个实时指标 · 数据截至 ${escapeHtml(status.data_as_of)}</small></span><span class="sector-state"><i aria-hidden="true"></i>${escapeHtml(zhStatus[status.overall_status] || status.overall_status)}</span><span class="sector-action">打开监测<b aria-hidden="true">↗</b></span></a>
    <a class="sector-row" href="#future-sectors"><span class="sector-code">02</span><span class="sector-main"><strong>稳定币与加密资产</strong><small>来源图谱及公司覆盖已完成；dashboard 尚未发布。</small></span><span class="sector-state"><i aria-hidden="true"></i>研究就绪</span><span class="sector-action">计划中<b aria-hidden="true">↗</b></span></a>
    <a class="sector-row" href="#future-sectors"><span class="sector-code">03</span><span class="sector-main"><strong>商业航天</strong><small>公司及信号框架已完成；dashboard 尚未发布。</small></span><span class="sector-state"><i aria-hidden="true"></i>研究就绪</span><span class="sector-action">计划中<b aria-hidden="true">↗</b></span></a>
    <a class="sector-row" href="#future-sectors"><span class="sector-code">04</span><span class="sector-main"><strong>消费趋势</strong><small>公司列表已建立；来源访问仍不均衡。</small></span><span class="sector-state"><i aria-hidden="true"></i>研究中</span><span class="sector-action">计划中<b aria-hidden="true">↗</b></span></a>
  </div></section>
  <section class="release-panel" id="future-sectors"><div><p class="eyebrow">可携带发布</p><h2>把房地产监测带到线下。</h2><p>线上页面与可下载 HTML 来自同一个已校验快照，dashboard 文件字节完全一致。</p></div>
    <div class="release-actions"><a class="primary-action" href="/exports/hk-real-estate-dashboard-zh-${escapeHtml(status.attachment_filename.replace(/^hk-real-estate-dashboard-/, ""))}" download>下载离线 HTML</a><a class="text-action" href="/zh/data-status/">查看数据状态 →</a></div>
  </section>`;
const zhStatusBody = `
  <section class="status-intro"><div><p class="eyebrow">发布控制</p><h1>数据状态</h1><p>一页查看实时、部分覆盖、仅目录和计划中的数据。</p></div>
    <dl class="status-summary"><div><dt>总体</dt><dd class="healthy">${escapeHtml(zhStatus[status.overall_status] || status.overall_status)}</dd></div><div><dt>数据截至</dt><dd>${escapeHtml(status.data_as_of)}</dd></div><div><dt>生成时间</dt><dd>${escapeHtml(status.generated_at.replace("T", " ").slice(0, 19))} UTC</dd></div><div><dt>快照</dt><dd><code>${escapeHtml(status.snapshot_id)}</code></dd></div></dl>
  </section>
  <section class="status-table-section"><div class="section-heading"><h2>香港房地产覆盖</h2><p>来源目录发现不计入实时市场指标。</p></div><div class="table-wrap"><table><thead><tr><th>来源 / 数据集</th><th>类型</th><th>状态</th><th>最新日期</th><th>记录数</th><th>新鲜度 / 限制</th></tr></thead><tbody>${zhSourceRows}</tbody></table></div></section>`;
fs.mkdirSync(path.join(dist, "zh", "data-status"), { recursive: true });
fs.writeFileSync(path.join(dist, "zh", "index.html"), layout({ lang: "zh-CN", homeHref: "/zh/", statusHref: "/zh/data-status/", languageHref: "/", languageLabel: "English", title: "亚洲市场 — 研究监测", description: "有来源依据的亚洲市场研究 dashboard 与数据快照。", body: zhHomeBody }));
fs.writeFileSync(path.join(dist, "zh", "data-status", "index.html"), layout({ lang: "zh-CN", homeHref: "/zh/", statusHref: "/zh/data-status/", languageHref: "/", languageLabel: "English", title: "数据状态 — 亚洲市场", description: "亚洲市场 dashboard 的新鲜度、覆盖范围与发布信息。", body: zhStatusBody }));

const publicRoot = path.join(appRoot, "public");
fs.cpSync(publicRoot, dist, { recursive: true });
console.log(`Static hub written to ${dist}`);
