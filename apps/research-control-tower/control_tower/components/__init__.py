"""Reusable, read-only UI components for Research Control Tower V1.

The package initializer is the approved Task 6 style boundary; a separate
``styles.py`` is intentionally deferred so the exact plan path contract stays
unchanged.
"""

from __future__ import annotations

import streamlit as st


LIGHT_TOKENS = r"""
:root {
  --ct-bg: #f8fafc;
  --ct-surface: #ffffff;
  --ct-surface-muted: #f1f5f9;
  --ct-ink: #0f172a;
  --ct-muted: #64748b;
  --ct-border: #e2e8f0;
  --ct-accent: #2563eb;
  --ct-hard: #0f766e;
  --ct-provisional: #b45309;
  --ct-thesis: #7c3aed;
  --ct-observed: #2563eb;
  --ct-warning: #b45309;
  --ct-danger: #b91c1c;
  --ct-radius: 14px;
}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
  background-color: #ffffff !important;
  color: #0f172a !important;
}
section[data-testid="stSidebar"] {
  background-color: #f8fafc !important;
  color: #0f172a !important;
}
"""

DARK_TOKENS = r"""
:root {
  --ct-bg: #0e1117;
  --ct-surface: #161b22;
  --ct-surface-muted: #252b36;
  --ct-ink: #f0f2f6;
  --ct-muted: #94a3b8;
  --ct-border: #334155;
  --ct-accent: #3b82f6;
  --ct-hard: #14b8a6;
  --ct-provisional: #f59e0b;
  --ct-thesis: #a855f7;
  --ct-observed: #3b82f6;
  --ct-warning: #f59e0b;
  --ct-danger: #ef4444;
  --ct-radius: 14px;
}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
  background-color: #0e1117 !important;
  color: #f0f2f6 !important;
}
section[data-testid="stSidebar"] {
  background-color: #161b22 !important;
  color: #f0f2f6 !important;
}
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
  color: #f0f2f6 !important;
}
.stApp button[kind="secondary"] {
  background-color: #1f2937 !important;
  border-color: #334155 !important;
  color: #f0f2f6 !important;
}
.stApp button[kind="secondary"] [data-testid="stMarkdownContainer"] p {
  color: #f0f2f6 !important;
}
section[data-testid="stSidebar"] button[kind="headerNoPadding"] [data-testid="stIconMaterial"],
section[data-testid="stSidebar"] button[kind="headerNoPadding"] span {
  color: #f0f2f6 !important;
}
section[data-testid="stSidebar"] label[data-baseweb="radio"] p {
  color: #f0f2f6 !important;
}
[data-testid="stExpander"] label,
[data-testid="stExpander"] [data-testid="stWidgetLabel"] p {
  color: #f0f2f6 !important;
}
[data-testid="stExpander"] summary {
  background-color: #1c2430 !important;
  border-color: #334155 !important;
  color: #f0f2f6 !important;
}
[data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] p,
[data-testid="stExpander"] summary [data-testid="stIconMaterial"] {
  color: #f0f2f6 !important;
}
[data-baseweb="select"] > div {
  background-color: #1f2937 !important;
  border-color: #334155 !important;
  color: #f0f2f6 !important;
}
[data-baseweb="select"] > div * {
  color: #f0f2f6 !important;
}
[data-testid="stExpander"] [data-testid="stSlider"] p {
  color: #94a3b8 !important;
}
[data-baseweb="popover"],
[data-testid="stSelectboxVirtualDropdown"],
[role="option"] {
  background-color: #161b22 !important;
  color: #f0f2f6 !important;
}
[data-baseweb="popover"] [role="option"]:hover,
[data-baseweb="popover"] [role="option"][aria-selected="true"] {
  background-color: #253247 !important;
}
[data-baseweb="popover"] [role="option"] * {
  color: #f0f2f6 !important;
}
[data-testid="stAlertContainer"] {
  background-color: rgba(245, 158, 11, .12) !important;
  color: #f6c453 !important;
}
[data-testid="stAlertContainer"] [data-testid="stMarkdownContainer"] p {
  color: #f6c453 !important;
}
.stTabs [data-baseweb="tab-list"] {
  background-color: transparent !important;
  border-bottom-color: #334155 !important;
}
.stTabs [data-baseweb="tab"] {
  color: #94a3b8 !important;
  background-color: transparent !important;
}
.stTabs [data-baseweb="tab"]:hover {
  color: #f0f2f6 !important;
}
.stTabs [aria-selected="true"] {
  color: #3b82f6 !important;
  border-bottom-color: #3b82f6 !important;
}
.stTabs [data-baseweb="tab-highlight"] {
  background-color: #3b82f6 !important;
}
.stTabs [data-baseweb="tab-border"] {
  background-color: #334155 !important;
}
/* No --gdg-* block here on purpose.
 *
 * st.dataframe renders through glide-data-grid, which paints its cells to a
 * canvas from Streamlit's own theme, not from CSS custom properties. The
 * variables were being set on the element -- computed style confirmed
 * --gdg-bg-cell: #161b22 -- and the table still drew white on a dark page.
 *
 * So the tables stay light in dark mode, and there is no CSS fix. The two
 * routes that do work, neither of them a small edit:
 *   1. Pass a pandas Styler. Colours land, but Streamlit then formats
 *      numbers through the Styler instead of the grid's column config, so
 *      0.0045 renders as 0.004460. Every table needs its own .format().
 *   2. Render the app's own HTML tables and drop st.dataframe. 26 call
 *      sites across company.py, ai_bottlenecks.py and source_health.py.
 */
"""

BASE_CSS = r"""
[data-testid="stSidebar"] { border-right: 1px solid var(--ct-border); }
[data-testid="stSidebar"] .sidebar-brand {
  color: var(--ct-ink) !important;
  font-size: 1.05rem;
  font-weight: 800;
  letter-spacing: -0.015em;
  margin-top: 0.25rem;
}
[data-testid="stSidebar"] .sidebar-brand-subtitle {
  color: var(--ct-muted) !important;
  font-size: 0.78rem;
  margin: 0.05rem 0 0.25rem 0;
}
[data-testid="stSidebar"] .sidebar-focus-note {
  color: var(--ct-muted) !important;
  font-size: 0.74rem;
  margin: 0 0 1.05rem 0;
}
[data-testid="stSidebar"] .sidebar-group-label {
  color: var(--ct-muted) !important;
  font-size: 0.68rem;
  font-weight: 750;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin: 1rem 0 0.3rem 0.15rem;
}
[data-testid="stSidebar"] .stButton { margin-bottom: 0.12rem; }
[data-testid="stSidebar"] .stButton > button,
[data-testid="stSidebar"] .stButton > button[kind="secondary"],
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
  justify-content: flex-start;
  min-height: 2.25rem;
  padding: 0.4rem 0.65rem;
  border: 0 !important;
  border-radius: 7px;
  box-shadow: none !important;
  font-size: 0.86rem;
  font-weight: 520;
  color: var(--ct-ink) !important;
}
[data-testid="stSidebar"] .stButton > button,
[data-testid="stSidebar"] .stButton > button[kind="secondary"] {
  background: transparent !important;
}
[data-testid="stSidebar"] .stButton > button p {
  width: 100%;
  text-align: left;
  color: inherit !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
  background: color-mix(in srgb, var(--ct-accent) 8%, transparent) !important;
  color: var(--ct-accent) !important;
  transform: none;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
  background: color-mix(in srgb, var(--ct-accent) 12%, transparent) !important;
  color: var(--ct-accent) !important;
  font-weight: 700;
}
.ct-shell { max-width: 1480px; margin: 0 auto; padding-bottom: 2rem; }
.ct-header-block { margin-bottom: 0.5rem; }
.ct-eyebrow { color: var(--ct-muted); font-size: .72rem; letter-spacing: .12em;
  text-transform: uppercase; font-weight: 700; margin: 0 0 .25rem; }
.ct-subtle { color: var(--ct-muted); font-size: .82rem; }
.ct-flight-deck { display: grid; grid-template-columns: 1.25fr .75fr .9fr .9fr 1.8fr;
  gap: 1px; border: 1px solid var(--ct-border); border-radius: var(--ct-radius);
  overflow: hidden; background: var(--ct-border); margin: .6rem 0 1rem; }
.ct-flight-slot { background: var(--ct-surface); padding: .85rem 1rem; min-width: 0; }
.ct-flight-slot--catalyst { background: color-mix(in srgb, var(--ct-accent) 7%, var(--ct-surface)); }
.ct-metric-label { color: var(--ct-muted); font-size: .72rem; text-transform: uppercase;
  letter-spacing: .08em; font-weight: 700; }
.ct-metric-value { color: var(--ct-ink); font-size: 1.05rem; line-height: 1.25;
  font-weight: 750; margin-top: .25rem; overflow-wrap: anywhere; }
.ct-metric-detail { color: var(--ct-muted); font-size: .77rem; line-height: 1.35;
  margin-top: .28rem; overflow-wrap: anywhere; }
.ct-layout { display: grid; gap: 1.1rem; }
.ct-today-layout { grid-template-columns: minmax(0, 1.9fr) minmax(260px, .9fr); }
.ct-timeline-layout { grid-template-columns: minmax(260px, .8fr) minmax(0, 1.8fr); }
.ct-panel { background: var(--ct-surface); border: 1px solid var(--ct-border);
  border-radius: var(--ct-radius); padding: 1rem 1.05rem; min-width: 0; }
.ct-panel h3 { margin: 0 0 .75rem; font-size: 1rem; color: var(--ct-ink); }
.ct-panel-heading { display: flex; align-items: baseline; justify-content: space-between;
  gap: .7rem; margin-bottom: .7rem; }
.ct-panel-heading h3 { margin: 0; }
.ct-count { color: var(--ct-muted); font-size: .76rem; white-space: nowrap; }
.ct-event-list { display: grid; gap: .65rem; }
.ct-event-row { display: grid; grid-template-columns: 104px minmax(0, 1fr) 250px;
  gap: .9rem; border: 1px solid var(--ct-border); border-left: 3px solid var(--ct-border);
  border-radius: 11px; padding: .78rem .85rem; background: var(--ct-surface); min-width: 0; }
.ct-event-row--hard { border-left-color: var(--ct-hard); }
.ct-event-row--provisional { border-left: 3px dashed var(--ct-provisional); }
.ct-event-row--thesis_checkpoint { border-left: 3px dashed var(--ct-thesis); }
.ct-event-row--observed { border-left-color: var(--ct-observed); }
.ct-event-date { color: var(--ct-ink); font-size: .86rem; font-weight: 750; }
.ct-t-minus { color: var(--ct-accent); font-size: .78rem; font-weight: 750; margin-top: .22rem; }
.ct-event-title { color: var(--ct-ink); font-size: .94rem; font-weight: 750; line-height: 1.32;
  overflow-wrap: anywhere; }
.ct-event-description { color: var(--ct-muted); font-size: .82rem; line-height: 1.42;
  margin-top: .25rem; overflow-wrap: anywhere; }
.ct-event-meta { color: var(--ct-muted); font-size: .75rem; line-height: 1.45;
  min-width: 0; overflow-wrap: anywhere; }
.ct-badges, .ct-chips { display: flex; flex-wrap: wrap; gap: .33rem; margin-top: .48rem; }
.ct-badge, .ct-chip { display: inline-flex; align-items: center; max-width: 100%;
  border: 1px solid var(--ct-border); border-radius: 999px; padding: .18rem .48rem;
  font-size: .69rem; line-height: 1.25; overflow-wrap: anywhere; }
.ct-badge--hard { color: var(--ct-hard); border-color: color-mix(in srgb, var(--ct-hard) 45%, var(--ct-border)); }
.ct-badge--provisional { color: var(--ct-provisional); border-style: dashed; }
.ct-badge--thesis_checkpoint { color: var(--ct-thesis); border-style: dashed; }
.ct-badge--observed { color: var(--ct-observed); }
.ct-badge--warning { color: var(--ct-warning); border-color: color-mix(in srgb, var(--ct-warning) 45%, var(--ct-border)); }
.ct-chip { background: var(--ct-surface-muted); color: var(--ct-ink); }
.ct-source-line { color: var(--ct-muted); font-size: .74rem; line-height: 1.4; margin-top: .36rem; }
.ct-source-line a { color: var(--ct-accent); text-decoration: none; }
.ct-source-line a:hover, .ct-source-line a:focus { text-decoration: underline; }
.ct-watch { border-top: 1px solid var(--ct-border); margin-top: .65rem; padding-top: .55rem; }
.ct-watch summary { color: var(--ct-ink); cursor: pointer; font-size: .78rem; font-weight: 700; }
.ct-watch ul { color: var(--ct-muted); margin: .45rem 0 0 1.1rem; padding: 0; font-size: .78rem; }
.ct-watch li { margin: .2rem 0; overflow-wrap: anywhere; }
.ct-change-list { display: grid; gap: .55rem; }
.ct-change { border-bottom: 1px solid var(--ct-border); padding: .6rem 0; }
.ct-change:last-child { border-bottom: 0; padding-bottom: 0; }
.ct-change-title { color: var(--ct-ink); font-size: .88rem; font-weight: 700; overflow-wrap: anywhere; }
.ct-change-detail { color: var(--ct-muted); font-size: .77rem; line-height: 1.4; margin-top: .18rem; }
.ct-alert-strip { border: 1px solid color-mix(in srgb, var(--ct-warning) 45%, var(--ct-border));
  background: color-mix(in srgb, var(--ct-warning) 8%, var(--ct-surface));
  color: var(--ct-ink); border-radius: 10px; padding: .65rem .75rem; font-size: .78rem;
  line-height: 1.4; margin-top: .5rem; margin-bottom: .5rem; overflow-wrap: anywhere; }
.ct-empty { border: 1px dashed var(--ct-border); border-radius: 10px; color: var(--ct-muted);
  padding: .8rem; font-size: .82rem; }
.ct-timeline-month { color: var(--ct-ink); font-size: 1rem; font-weight: 760; margin: .25rem 0 .55rem; }
.ct-timeline-month:not(:first-child) { margin-top: 1.25rem; }
.ct-catalyst-rail { align-self: start; }
.ct-catalyst-card { border: 1px solid color-mix(in srgb, var(--ct-accent) 32%, var(--ct-border));
  border-radius: var(--ct-radius); background: color-mix(in srgb, var(--ct-accent) 6%, var(--ct-surface));
  padding: .95rem; }
.ct-catalyst-card .ct-event-title { font-size: 1rem; }
.ct-section-spacer { height: .9rem; }
.ct-inline-link { color: var(--ct-accent); text-decoration: none; }
.ct-inline-link:hover, .ct-inline-link:focus { text-decoration: underline; }
.ct-filter-summary { color: var(--ct-muted); font-size: 0.78rem; margin-top: 0.2rem; margin-bottom: 0.6rem; }

/* Hero Header & KPI Cards */
.ct-hero-card { background: var(--ct-surface); border: 1px solid var(--ct-border); border-radius: var(--ct-radius); padding: 1.15rem 1.35rem; margin-bottom: 1rem; }
.ct-hero-top { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.85rem; margin-bottom: 0.6rem; }
.ct-hero-title { font-size: 1.4rem; font-weight: 800; color: var(--ct-ink); margin: 0; display: flex; align-items: center; gap: 0.6rem; }
.ct-hero-ticker { font-size: 0.88rem; font-weight: 750; color: var(--ct-accent); background: color-mix(in srgb, var(--ct-accent) 12%, var(--ct-surface)); padding: 0.2rem 0.55rem; border-radius: 6px; border: 1px solid color-mix(in srgb, var(--ct-accent) 25%, var(--ct-border)); }
.ct-hero-price-box { display: flex; align-items: baseline; gap: 0.65rem; }
.ct-hero-price { font-size: 1.45rem; font-weight: 800; color: var(--ct-ink); }
.ct-hero-change { font-size: 0.86rem; font-weight: 750; padding: 0.18rem 0.48rem; border-radius: 6px; }
.ct-hero-change--up { color: #16a34a; background: rgba(22, 163, 74, 0.12); }
.ct-hero-change--down { color: #dc2626; background: rgba(220, 38, 38, 0.12); }

.ct-kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 0.65rem; margin-top: 0.75rem; }
.ct-kpi-card { background: var(--ct-surface-muted); border: 1px solid var(--ct-border); border-radius: 10px; padding: 0.7rem 0.85rem; }
.ct-kpi-label { font-size: 0.7rem; text-transform: uppercase; font-weight: 700; color: var(--ct-muted); letter-spacing: 0.06em; }
.ct-kpi-value { font-size: 1.12rem; font-weight: 800; color: var(--ct-ink); margin-top: 0.2rem; }
.ct-kpi-sub { font-size: 0.72rem; color: var(--ct-muted); margin-top: 0.12rem; }

/* Financial model & Segment cards */
.ct-segment-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 0.75rem; margin-bottom: 0.9rem; }
.ct-segment-card { background: var(--ct-surface); border: 1px solid var(--ct-border); border-radius: 11px; padding: 0.95rem 1.05rem; }
.ct-segment-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.4rem; }
.ct-segment-title { font-size: 0.92rem; font-weight: 750; color: var(--ct-ink); }
.ct-segment-share { font-size: 0.76rem; font-weight: 700; color: var(--ct-accent); }
.ct-segment-rev { font-size: 1.2rem; font-weight: 800; color: var(--ct-ink); }
.ct-segment-detail { font-size: 0.76rem; color: var(--ct-muted); margin-top: 0.3rem; line-height: 1.4; }

/* Thesis & Pillar cards */
.ct-thesis-grid { display: grid; grid-template-columns: 1fr; gap: 0.85rem; margin-bottom: 1.1rem; }
.ct-thesis-card { background: var(--ct-surface); border: 1px solid var(--ct-border); border-left: 4px solid var(--ct-border); border-radius: 11px; padding: 1rem 1.15rem; }
.ct-thesis-card--bull { border-left-color: #16a34a; background: color-mix(in srgb, #16a34a 4%, var(--ct-surface)); }
.ct-thesis-card--bear { border-left-color: #dc2626; background: color-mix(in srgb, #dc2626 4%, var(--ct-surface)); }
.ct-thesis-card--base { border-left-color: var(--ct-accent); background: color-mix(in srgb, var(--ct-accent) 4%, var(--ct-surface)); }

/* Buyback Tracker */
.ct-buyback-tracker { background: var(--ct-surface); border: 1px solid var(--ct-border); border-radius: 11px; padding: 0.95rem 1.15rem; margin-bottom: 0.9rem; }
.ct-progress-bar-bg { background: var(--ct-surface-muted); border-radius: 999px; height: 9px; width: 100%; overflow: hidden; margin: 0.55rem 0; border: 1px solid var(--ct-border); }
.ct-progress-bar-fill { background: linear-gradient(90deg, var(--ct-accent), #10b981); height: 100%; border-radius: 999px; }

/* State of Play Insights */
.ct-insight-box { background: var(--ct-surface-muted); border: 1px solid var(--ct-border); border-radius: 10px; padding: 0.85rem 1rem; margin-bottom: 0.65rem; }
.ct-insight-title { font-size: 0.88rem; font-weight: 750; color: var(--ct-ink); margin-bottom: 0.25rem; display: flex; align-items: center; gap: 0.4rem; }
.ct-insight-desc { font-size: 0.82rem; color: var(--ct-ink); opacity: 0.9; line-height: 1.45; }

@media (max-width: 1199px) {
  .ct-flight-deck { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ct-flight-slot--catalyst { grid-column: 1 / -1; }
  .ct-today-layout, .ct-timeline-layout { grid-template-columns: 1fr; }
  .ct-catalyst-rail { order: -1; }
  .ct-event-row { grid-template-columns: 104px minmax(0, 1fr); }
  .ct-event-meta { grid-column: 2; }
}
@media (max-width: 759px) {
  .ct-flight-deck { grid-template-columns: 1fr; }
  .ct-flight-slot--catalyst { grid-column: auto; }
  .ct-event-row { grid-template-columns: 1fr; gap: .42rem; }
  .ct-event-meta { grid-column: auto; }
  .ct-panel { padding: .82rem .78rem; }
  .ct-shell { padding-bottom: 1.5rem; }
  section[data-testid="stSidebar"] {
    width: min(78vw, 300px) !important;
    min-width: 0 !important;
    max-width: 78vw;
  }
  [data-testid="stSidebarContent"] { padding: .9rem .6rem; }
}
"""


def get_control_tower_css(theme: str = "Light") -> str:
    tokens = DARK_TOKENS if theme == "Dark" else LIGHT_TOKENS
    return f"<style>\n{tokens}\n{BASE_CSS}\n</style>"


CONTROL_TOWER_CSS = get_control_tower_css("Light")


def inject_styles(theme: str | None = None) -> None:
    """Inject the static stylesheet into the current Streamlit run."""

    if theme is None:
        theme = st.session_state.get("ct_theme", "Light")
    st.markdown(get_control_tower_css(theme), unsafe_allow_html=True)


__all__ = ["CONTROL_TOWER_CSS", "get_control_tower_css", "inject_styles"]
