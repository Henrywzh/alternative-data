import fs from "node:fs";
import path from "node:path";

import { appRoot, attachmentNames, LIVE_SECTORS, PLANNED_SECTORS, readStatus } from "./sectors.mjs";

const dist = path.join(appRoot, "dist");

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#39;");

const css = fs.readFileSync(path.join(appRoot, "src", "styles", "global.css"), "utf8");

function layout({ title, description, body, lang = "en", homeHref = "/", statusHref = "/data-status/", languageHref = "/zh/", languageLabel = "简体中文" }) {
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
      <nav aria-label="Primary"><a href="${homeHref}">${lang === "zh-CN" ? "板块" : "Sectors"}</a><a href="${statusHref}">${lang === "zh-CN" ? "数据状态" : "Data status"}</a><a href="${languageHref}">${languageLabel}</a></nav>
    </header>
    <main>${body}</main>
    <footer><span>${lang === "zh-CN" ? "已发布的研究快照" : "Published research snapshots"}</span><span>${lang === "zh-CN" ? "不构成投资建议" : "Not investment advice"}</span></footer>
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

const STATUS_ZH = {
  type: {
    Measure: "指标",
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
