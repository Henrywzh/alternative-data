// Shared helpers for the dashboard pages: masthead, subtab routing,
// ECharts defaults in the terminal palette, number formats, sparklines and
// sortable tables. Pages load ECharts first, then this file, then their own code.
(function () {
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const P = { text: css('--text'), dim: css('--text-dim'), faint: css('--text-faint'), border: css('--border'), accent: css('--accent'), up: css('--up'), down: css('--down') };
  const FONT = 'ui-monospace, "SF Mono", Menlo, monospace';
  const SERIES = ['#e8a33d', '#60a5fa', '#a78bfa', '#4ade80', '#f472b6', '#22d3ee', '#fbbf24', '#f87171', '#34d399', '#c4b5fd', '#fb923c', '#94a3b8'];
  // One colour per lab or provider everywhere, so OpenAI is the same green on every page.
  const NAMED = {
    openai: '#4ade80', anthropic: '#e8a33d', google: '#60a5fa', deepseek: '#a78bfa', 'x-ai': '#e6e6e6', xai: '#e6e6e6', meta: '#2dd4bf',
    qwen: '#f472b6', alibaba: '#f472b6', 'z.ai': '#22d3ee', 'z-ai': '#22d3ee', zai: '#22d3ee', zhipu: '#22d3ee', moonshot: '#f43f5e', minimax: '#fb923c', tencent: '#94a3b8',
    xiaomi: '#e879f9', mistral: '#fde68a', langchain: '#67e8f9', pydanticai: '#d946ef', cursor: '#cbd5e1', other: '#5a5a5a', others: '#5a5a5a',
  };
  function color(name, i = 0) {
    const key = String(name).toLowerCase();
    for (const [k, c] of Object.entries(NAMED)) if (key.includes(k)) return c;
    return SERIES[i % SERIES.length];
  }

  const PAGES = [
    ['USAGE', [['openrouter', 'OPENROUTER']]],
    ['ADOPTION', [['ramp', 'RAMP'], ['downloads', 'DOWNLOADS']]],
    ['COMPUTE', [['semis', 'SEMIS'], ['gpu', 'GPU RENTAL']]],
  ];
  function masthead(current, asof) {
    const nav = PAGES.map(([g, items]) => `<div class="nav-group"><span>${g}</span>${items.map(([id, l]) =>
      `<a class="nav-item ${id === current ? 'on' : ''}" href="../${id}/">${l}</a>`).join('')}</div>`).join('');
    document.getElementById('masthead').innerHTML =
      `<div class="brand">ALT·DATA<small>AI USAGE · ADOPTION · COMPUTE</small></div><nav class="nav">${nav}</nav>` +
      `<div class="asof">${asof}</div>`;
  }

  const charts = {};
  function base() {
    return {
      animation: false, backgroundColor: 'transparent',
      textStyle: { fontFamily: FONT, fontSize: 10, color: P.dim },
      grid: { left: 54, right: 16, top: 34, bottom: 30 },
      tooltip: { trigger: 'axis', backgroundColor: '#000', borderColor: P.border, textStyle: { color: P.text, fontSize: 11, fontFamily: FONT }, axisPointer: { type: 'line', lineStyle: { color: P.faint, type: 'dashed' } }, confine: true },
      legend: { top: 0, left: 0, textStyle: { color: P.dim, fontSize: 10.5 }, icon: 'roundRect', itemWidth: 10, itemHeight: 3, inactiveColor: '#444' },
      xAxis: { type: 'time', axisLine: { lineStyle: { color: P.border } }, axisTick: { show: false }, axisLabel: { color: P.dim, fontSize: 10, hideOverlap: true }, splitLine: { show: false } },
      yAxis: { type: 'value', scale: true, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: P.dim, fontSize: 10 }, splitLine: { lineStyle: { color: P.border, opacity: 0.5 } } },
    };
  }
  function catAxis(data) { return { type: 'category', data, axisLine: { lineStyle: { color: P.border } }, axisTick: { show: false }, axisLabel: { color: P.dim, fontSize: 10, hideOverlap: true } }; }
  function draw(id, option) {
    const node = document.getElementById(id);
    if (!node || node.offsetParent === null) return;
    (charts[id] ||= echarts.init(node, null, { renderer: 'canvas' })).setOption(option, true);
  }
  window.addEventListener('resize', () => Object.values(charts).forEach((c) => c.resize()));

  const num = (v) => v == null || Number.isNaN(v);
  // Compact numbers: 1.2T, 340B, 5.6M, 12K.
  function compact(v, d = 1) {
    if (num(v)) return '—';
    const a = Math.abs(v);
    for (const [s, u] of [[1e12, 'T'], [1e9, 'B'], [1e6, 'M'], [1e3, 'K']]) if (a >= s) return (v / s).toFixed(d) + u;
    return v.toFixed(a < 10 ? 2 : 0);
  }
  const money = (v, d = 1) => num(v) ? '—' : '$' + compact(v, d);
  const pct = (v, d = 1) => num(v) ? '—' : (v > 0 ? '+' : '') + (v * 100).toFixed(d) + '%';
  const pp = (v, d = 1) => num(v) ? '—' : (v > 0 ? '+' : '') + v.toFixed(d) + 'pp';
  const cls = (v) => num(v) ? 'flat' : v > 0.0005 ? 'up' : v < -0.0005 ? 'down' : 'flat';

  function spark(values, w = 110, h = 20, stroke) {
    const v = values.filter((x) => !num(x)); if (v.length < 2) return '';
    const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
    const pts = values.map((x, i) => num(x) ? null : `${(i / (values.length - 1) * w).toFixed(1)},${(h - 2 - (x - lo) / span * (h - 4)).toFixed(1)}`).filter(Boolean);
    const c = stroke || (v[v.length - 1] >= v[0] ? P.up : P.down);
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline fill="none" stroke="${c}" stroke-width="1.2" points="${pts.join(' ')}"/></svg>`;
  }
  const dot = (c) => `<i style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${c};margin-right:6px"></i>`;

  // Sortable table: cols = [{k, label, fmt(row) -> html, sort(row) -> value, cls(row)}].
  function table(id, rows, cols, state) {
    const [k, dir] = state.sort;
    const col = cols.find((c) => c.k === k) || cols[0];
    const key = col.sort || ((r) => r[col.k]);
    const sorted = [...rows].sort((a, b) => {
      const x = key(a), y = key(b);
      if (typeof x === 'string') return x.localeCompare(y) * dir;
      return ((num(x) ? -Infinity : x) - (num(y) ? -Infinity : y)) * dir;
    });
    document.getElementById(id).innerHTML = `<table><thead><tr>${cols.map((c) => `<th data-k="${c.k}" class="${c.k === k ? 'sorted' : ''}">${c.label}${c.k === k ? (dir > 0 ? ' ▲' : ' ▼') : ''}</th>`).join('')}</tr></thead><tbody>` +
      sorted.map((r) => `<tr>${cols.map((c) => `<td class="${c.cls ? c.cls(r) : ''}">${c.fmt ? c.fmt(r) : r[c.k] ?? '—'}</td>`).join('')}</tr>`).join('') + '</tbody></table>';
    document.querySelectorAll(`#${id} th[data-k]`).forEach((th) => th.onclick = () => {
      const c = th.dataset.k; state.sort = [c, state.sort[0] === c ? -state.sort[1] : -1]; table(id, rows, cols, state);
    });
  }

  // Subtabs: buttons with data-view, sections with id view-<name>; hash-routed.
  function router(renderers, first) {
    const go = (view) => {
      if (!renderers[view]) view = first;
      history.replaceState(null, '', '#' + view);
      document.querySelectorAll('.subtab').forEach((b) => b.classList.toggle('on', b.dataset.view === view));
      document.querySelectorAll('.view').forEach((v) => v.classList.toggle('on', v.id === 'view-' + view));
      renderers[view]();
    };
    document.querySelectorAll('.subtab').forEach((b) => b.onclick = () => go(b.dataset.view));
    window.addEventListener('hashchange', () => go(location.hash.slice(1)));
    go(location.hash.slice(1) || first);
    return go;
  }
  // Segmented control: <div class="seg" id=...><button data-v>; calls after(value).
  function seg(id, state, key, after) {
    document.querySelectorAll(`#${id} button`).forEach((b) => {
      b.classList.toggle('on', b.dataset.v === String(state[key]));
      b.onclick = () => { state[key] = b.dataset.v; document.querySelectorAll(`#${id} button`).forEach((x) => x.classList.toggle('on', x === b)); after(); };
    });
  }
  const load = (url) => fetch(url, { cache: 'no-store' }).then((r) => r.json());

  // Series helpers on {index, series} pivots.
  function rolling(arr, n) {
    return arr.map((_, i) => { if (i < n - 1) return null; const w = arr.slice(i - n + 1, i + 1).filter((x) => !num(x)); return w.length === n ? w.reduce((a, b) => a + b, 0) / n : null; });
  }
  function shares(pivot) {
    const names = Object.keys(pivot.series);
    const totals = pivot.index.map((_, i) => names.reduce((a, n) => a + (pivot.series[n][i] || 0), 0));
    return Object.fromEntries(names.map((n) => [n, pivot.series[n].map((v, i) => totals[i] ? (v || 0) / totals[i] * 100 : null)]));
  }

  window.UI = { P, FONT, color, masthead, base, catAxis, draw, compact, money, pct, pp, cls, spark, dot, table, router, seg, load, rolling, shares, num };
})();
