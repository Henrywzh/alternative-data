import fs from "node:fs";
import path from "node:path";

import { appRoot, attachmentNames, LIVE_SECTORS, PLANNED_SECTORS, readStatus } from "./sectors.mjs";
import { STATUS_ZH } from "./status-zh.mjs";

const dist = path.join(appRoot, "dist");

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#39;");

const css = fs.readFileSync(path.join(appRoot, "src", "styles", "global.css"), "utf8");

function layout({ title, description, body, lang = "en", homeHref = "/", statusHref = "/data-status/", languageHref = "/zh/", languageLabel = "简体中文" }) {
  // Blocking, runs before <style> so a stored preference applies before
  // first paint (no flash of the wrong theme). Absent localStorage entry
  // means "no manual choice yet" -- left to the prefers-color-scheme media
  // query in global.css, not defaulted to light here.
  const themeInitScript = `<script>(function(){try{var t=localStorage.getItem('am-theme');if(t==='dark'||t==='light')document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>`;
  const themeToggleScript = `<script>(function(){
    var btn = document.getElementById('theme-toggle');
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
      btn.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
    }
    apply(current());
    btn.addEventListener('click', function(){ apply(current() === 'dark' ? 'light' : 'dark'); });
  })();</script>`;

  return `<!doctype html>
<html lang="${lang}">
  <head>
    <meta charset="UTF-8" />
    ${themeInitScript}
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
      <nav aria-label="Primary"><a href="${homeHref}">${lang === "zh-CN" ? "板块" : "Sectors"}</a><a href="${statusHref}">${lang === "zh-CN" ? "数据状态" : "Data status"}</a><a href="${languageHref}">${languageLabel}</a><button type="button" class="theme-toggle" id="theme-toggle" aria-label="Toggle dark mode">☾</button></nav>
    </header>
    <main>${body}</main>
    <footer><span>${lang === "zh-CN" ? "已发布的研究快照" : "Published research snapshots"}</span><span>${lang === "zh-CN" ? "不构成投资建议" : "Not investment advice"}</span></footer>
    ${themeToggleScript}
  </body>
</html>`;
}

// The sector roster lives in ../sectors.json (see scripts/sectors.mjs). Live
// sectors each have a status JSON written by their Python artifact builder;
// planned sectors are research-only placeholders that render as non-clickable
// rows, the same treatment the original three placeholders had before any
// dashboard existed for them.
const live = LIVE_SECTORS.map((sector) => ({ ...sector, status: readStatus(sector) }));
const planned = PLANNED_SECTORS;

const latestGeneratedAt = live.reduce((max, sector) => (sector.status.generated_at > max ? sector.status.generated_at : max), live[0].status.generated_at);
const totalLiveMeasures = live.reduce((sum, sector) => sum + sector.status.live_sources, 0);

function sectorRow({ code, name, state, detail, href, action, isLive }) {
  return `
      <a class="sector-row${isLive ? " sector-row-live" : ""}" href="${href}" aria-label="${escapeHtml(name)}: ${escapeHtml(action)}">
        <span class="sector-code">${code}</span>
        <span class="sector-main"><strong>${escapeHtml(name)}</strong><small>${escapeHtml(detail)}</small></span>
        <span class="sector-state"><i aria-hidden="true"></i>${escapeHtml(state)}</span>
        <span class="sector-action">${escapeHtml(action)}<b aria-hidden="true">↗</b></span>
      </a>`;
}

function buildHomeBody({ lang }) {
  const chinese = lang === "zh-CN";
  const rows = [
    ...live.map((sector) => sectorRow({
      code: sector.code,
      name: chinese ? sector.nameZh : sector.nameEn,
      state: chinese ? "健康" : sector.status.overall_status,
      detail: chinese
        ? `${sector.status.live_sources} 个实时指标 · 数据截至 ${sector.status.data_as_of}`
        : `${sector.status.live_sources} live measures · data through ${sector.status.data_as_of}`,
      href: chinese ? `/zh/${sector.route}/` : `/${sector.route}/`,
      action: chinese ? "打开监测" : "Open monitor",
      isLive: true,
    })),
    ...planned.map((sector) => sectorRow({
      code: sector.code,
      name: chinese ? sector.nameZh : sector.nameEn,
      state: chinese ? sector.stateZh : sector.stateEn,
      detail: chinese ? sector.detailZh : sector.detailEn,
      href: "#future-sectors",
      action: chinese ? "计划中" : "Planned",
      isLive: false,
    })),
  ].join("");

  return `
  <section class="workspace-intro"><div><p class="eyebrow">${chinese ? "研究监测 / 2026" : "Research monitors / 2026"}</p><h1>${chinese ? "板块信号，<br />保留完整来源链。" : "Sector signals,<br />with the source trail intact."}</h1></div>
    <div class="intro-meta"><span>${chinese ? "最新发布" : "Latest release"}</span><strong>${escapeHtml(latestGeneratedAt.slice(0, 10))}</strong><span>${chinese ? `${totalLiveMeasures} 个实时指标 · ${live.length} 个已发布板块` : `${totalLiveMeasures} live measures across ${live.length} published sectors`}</span></div>
  </section>
  <section class="sector-index" aria-labelledby="sector-heading"><div class="section-heading"><h2 id="sector-heading">${chinese ? "板块目录" : "Sector index"}</h2><p>${chinese ? "先展示已发布页面；仅研究板块会明确标记。" : "Published surfaces first; research-only sectors remain clearly labeled."}</p></div><div class="sector-list">${rows}
  </div></section>
  <section class="release-panel" id="future-sectors"><div><p class="eyebrow">${chinese ? "可携带发布" : "Portable release"}</p><h2>${chinese ? "把监测带到线下。" : "Take these monitors offline."}</h2><p>${chinese ? "线上页面与可下载 HTML 来自同一个已校验快照，dashboard 文件字节完全一致。" : "Each hosted page and its downloadable HTML are generated from the same validated snapshot and contain identical dashboard bytes."}</p></div>
    <div class="release-actions">${live.map((sector) => {
      const names = attachmentNames(sector, sector.status);
      const attachment = chinese ? names.zh : names.en;
      return `<a class="primary-action" href="/exports/${escapeHtml(attachment)}" download>${chinese ? `下载${sector.nameZh}离线 HTML` : `Download ${sector.nameEn} HTML`}</a>`;
    }).join("")}<a class="text-action" href="${chinese ? "/zh/data-status/" : "/data-status/"}">${chinese ? "查看数据状态 →" : "Inspect source status →"}</a></div>
  </section>`;
}


function translateStatusValue(value, kind) {
  if (kind === "freshness") {
    const match = /^(\d+)d old$/.exec(value);
    if (match) return match[1] === "0" ? "当日" : `已过${match[1]}天`;
  }
  return STATUS_ZH[kind]?.[value] ?? value;
}

function localizeStatusRow(source) {
  const translated = STATUS_ZH.rows[source.dataset] ?? {};
  return {
    ...source,
    dataset: translated.dataset ?? source.dataset,
    source: translated.source ?? source.source,
    type: translateStatusValue(source.type, "type"),
    status: translateStatusValue(source.status, "status"),
    freshness: translateStatusValue(source.freshness, "freshness"),
    notes: translated.notes ?? source.notes,
  };
}

function buildStatusBody({ lang }) {
  const chinese = lang === "zh-CN";
  const overall = live.every((sector) => sector.status.overall_status === "Healthy") ? (chinese ? "健康" : "Healthy") : (chinese ? "部分" : "Partial");
  const sections = live.map((sector) => {
    const rows = sector.status.sources.map((source) => {
      const row = chinese ? localizeStatusRow(source) : source;
      return `<tr><td><strong>${escapeHtml(row.dataset)}</strong><small>${escapeHtml(row.source)}</small></td><td>${escapeHtml(row.type)}</td><td><span class="status-label${source.status === "Healthy" ? " status-good" : ""}">${escapeHtml(row.status)}</span></td><td>${escapeHtml(row.latest_observation)}</td><td>${escapeHtml(row.records || "—")}</td><td><strong>${escapeHtml(row.freshness)}</strong><small>${escapeHtml(row.notes)}</small></td></tr>`;
    }).join("");
    return `<section class="status-table-section"><div class="section-heading"><h2>${chinese ? sector.nameZh : sector.nameEn} ${chinese ? "覆盖" : "coverage"}</h2><p>${chinese ? "来源目录发现不计入实时市场指标。" : "Catalog discovery is not counted as a live market measure."}</p></div><div class="table-wrap"><table><thead><tr><th>${chinese ? "来源 / 数据集" : "Source / dataset"}</th><th>${chinese ? "类型" : "Type"}</th><th>${chinese ? "状态" : "Status"}</th><th>${chinese ? "最新日期" : "Latest"}</th><th>${chinese ? "记录数" : "Rows"}</th><th>${chinese ? "新鲜度 / 限制" : "Freshness / caveat"}</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
  }).join("");

  return `
  <section class="status-intro"><div><p class="eyebrow">${chinese ? "发布控制" : "Release control"}</p><h1>${chinese ? "数据状态" : "Data status"}</h1><p>${chinese ? "一页查看实时、部分覆盖、仅目录和计划中的数据。" : "One compact view of what is live, partial, catalog-only, or still planned."}</p></div>
    <dl class="status-summary"><div><dt>${chinese ? "总体" : "Overall"}</dt><dd class="healthy">${escapeHtml(overall)}</dd></div><div><dt>${chinese ? "实时指标" : "Live measures"}</dt><dd>${totalLiveMeasures}</dd></div><div><dt>${chinese ? "生成时间" : "Generated"}</dt><dd>${escapeHtml(latestGeneratedAt.replace("T", " ").slice(0, 19))} UTC</dd></div></dl>
  </section>
  ${sections}`;
}

fs.rmSync(dist, { recursive: true, force: true });
fs.mkdirSync(dist, { recursive: true });
fs.mkdirSync(path.join(dist, "data-status"), { recursive: true });
fs.writeFileSync(path.join(dist, "index.html"), layout({ title: "Asia Markets — Research Monitors", description: "Source-backed Asia market research dashboards and published data snapshots.", body: buildHomeBody({ lang: "en" }) }));
fs.writeFileSync(path.join(dist, "data-status", "index.html"), layout({ title: "Data Status — Asia Markets", description: "Freshness, coverage and release metadata for Asia Markets dashboards.", languageHref: "/zh/data-status/", body: buildStatusBody({ lang: "en" }) }));
fs.writeFileSync(path.join(dist, "404.html"), layout({ title: "Not found — Asia Markets", description: "The requested page was not found.", body: "<section class=\"status-intro\"><div><p class=\"eyebrow\">404</p><h1>Page not found</h1><p><a class=\"text-action\" href=\"/\">Return to the sector index →</a></p></div></section>" }));

fs.mkdirSync(path.join(dist, "zh", "data-status"), { recursive: true });
fs.writeFileSync(path.join(dist, "zh", "index.html"), layout({ lang: "zh-CN", homeHref: "/zh/", statusHref: "/zh/data-status/", languageHref: "/", languageLabel: "English", title: "亚洲市场 — 研究监测", description: "有来源依据的亚洲市场研究 dashboard 与数据快照。", body: buildHomeBody({ lang: "zh-CN" }) }));
fs.writeFileSync(path.join(dist, "zh", "data-status", "index.html"), layout({ lang: "zh-CN", homeHref: "/zh/", statusHref: "/zh/data-status/", languageHref: "/data-status/", languageLabel: "English", title: "数据状态 — 亚洲市场", description: "亚洲市场 dashboard 的新鲜度、覆盖范围与发布信息。", body: buildStatusBody({ lang: "zh-CN" }) }));

const publicRoot = path.join(appRoot, "public");
fs.cpSync(publicRoot, dist, { recursive: true });
console.log(`Static hub written to ${dist}`);
