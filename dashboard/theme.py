from __future__ import annotations

import streamlit as st


# Style 1 (OpenRouter Clean) palette
ACCENT  = "#2563EB"


BG      = "#FFFFFF"


SIDEBAR = "#F7F8FA"


CARD    = "#FFFFFF"


BORDER  = "#E5E7EB"


TEXT    = "#111827"


MUTED   = "#6B7280"


GREEN   = "#16A34A"


RED     = "#DC2626"


YELLOW  = "#D97706"


GRID    = "#F3F4F6"


TICK    = "#9CA3AF"


MODEL_COLORS = [
    "#4285F4", "#FF6B6B", "#00B5A4", "#FF7849",
    "#8B5CF6", "#EC4899", "#84CC16", "#F59E0B",
    "#06B6D4", "#9CA3AF",
]


# Evaluated once at import; color constants are module-level so this is safe.
_DASHBOARD_CSS = f"""
<style>
/* ---- global ---- */
.stApp {{ background: transparent; }}
.block-container {{ padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1360px; }}

        /* ---- KPI cards ---- */
        .kpi-grid {{ display: flex; gap: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; }}
        .kpi-card {{
            flex: 1 1 200px;
            background: rgba(128, 128, 128, 0.05);
            border: 1px solid rgba(128, 128, 128, 0.1);
            border-radius: 8px;
            padding: 1.25rem;
            text-align: left;
            transition: transform 0.2s;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        }}
        .kpi-card:hover {{ transform: translateY(-2px); }}
        .kpi-label {{
            font-size: 0.85rem;
            color: #6B7280;
            font-weight: 500;
            margin-bottom: 0.5rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            margin-bottom: 0.35rem;
            font-weight: 600;
        }}
        .kpi-value {{
            font-size: 2rem;
            font-weight: 800;
            line-height: 1.1;
        }}
        .kpi-delta-up   {{ font-size: 0.82rem; color: {GREEN}; margin-top: 0.2rem; font-weight: 600; }}
        .kpi-delta-down {{ font-size: 0.82rem; color: {RED};   margin-top: 0.2rem; font-weight: 600; }}
        .kpi-delta-flat {{ font-size: 0.82rem; color: {MUTED}; margin-top: 0.2rem; }}

        /* ---- section headers ---- */
        .section-title {{
            font-size: 1.25rem;
            font-weight: 800;
            margin: 2rem 0 1rem 0;
            padding-bottom: 0.45rem;
            border-bottom: 2px solid rgba(128, 128, 128, 0.15);
        }}

        /* ---- Market Share Legend ---- */
        .ms-legend {{ display: flex; flex-direction: column; gap: 0.4rem; margin-top: 0.5rem; }}
        .ms-row {{ display: flex; align-items: center; gap: 0.6rem; padding: 0.35rem 0.5rem; border-radius: 6px; transition: background 0.2s; }}
        .ms-row:hover {{ background: rgba(0,0,0,0.03); }}
        .ms-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
        .ms-name {{ flex: 1; font-size: 0.82rem; font-weight: 500; color: {TEXT}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
        .ms-tokens {{ font-size: 0.78rem; color: {MUTED}; min-width: 50px; text-align: right; }}
        .ms-pct {{ font-size: 0.82rem; font-weight: 700; color: {TEXT}; min-width: 45px; text-align: right; }}

        .section-subtitle {{
            color: {MUTED};
            font-size: 0.9rem;
            margin: -0.55rem 0 0.9rem 0;
        }}
        .status-caption {{
            color: {MUTED};
            font-size: 0.88rem;
            margin: -0.25rem 0 0.9rem 0;
        }}
        .rankings-warning {{
            background: rgba(217, 119, 6, 0.08);
            border: 1px solid rgba(217, 119, 6, 0.16);
            border-radius: 10px;
            padding: 0.85rem 1rem;
            margin: 0 0 1.25rem 0;
            color: {TEXT};
            font-size: 0.9rem;
        }}

        /* ---- Health Checks ---- */
        .chk-ok      {{ color: {GREEN}; font-weight: 700; font-size: 0.9rem; margin-top: 0.5rem; }}
        .chk-warning {{ color: {YELLOW}; font-weight: 700; font-size: 0.9rem; margin-top: 0.5rem; }}
        .chk-error   {{ color: {RED}; font-weight: 700; font-size: 0.9rem; margin-top: 0.5rem; }}

        /* ---- Hide Streamlit elements to lock theme ---- */
        [data-testid="stToolbar"], #MainMenu, footer, header {{ visibility: hidden; display: none !important; }}
        .stDeployButton {{ display: none; }}
        
        /* Force Light Mode variables and color-scheme across ALL components */
        :root {{
            color-scheme: light !important;
            --primary-color: {ACCENT} !important;
            --background-color: {BG} !important;
            --secondary-background-color: {SIDEBAR} !important;
            --text-color: {TEXT} !important;
        }}

        /* Global overrides */
        body, .stApp, .stMain, [data-testid="stHeader"], [data-testid="stAppViewContainer"], [data-testid="stHorizontalBlock"] {{
            background-color: {BG} !important;
            color: {TEXT} !important;
        }}

        /* Sidebar styles */
        [data-testid="stSidebar"], [data-testid="stSidebarContent"], [data-testid="stSidebarUserContent"], [data-testid="stSidebarNavLink"] {{
            background-color: {SIDEBAR} !important;
            color: {TEXT} !important;
        }}

        /* Ensure all text labels and elements use the fixed text color */
        .stMarkdown, p, span, label, div, li, h1, h2, h3 {{
            color: {TEXT} !important;
        }}

        /* Metric overrides */
        [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {{
            color: {TEXT} !important;
        }}
        
        /* Button overrides - Force White/Light Background */
        .stButton > button {{
            background-color: {BG} !important;
            color: {TEXT} !important;
            border: 1px solid {BORDER} !important;
        }}
        .stButton > button:hover {{
            border-color: {ACCENT} !important;
            color: {ACCENT} !important;
        }}

        /* Tabs overrides */
        .stTabs [data-baseweb="tab"] {{
            color: {MUTED} !important;
        }}
        .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {{
            color: {ACCENT} !important;
        }}

/* Plotly background protection */
.js-plotly-plot .main-svg, .plotly .main-svg {{
    background: transparent !important;
}}
</style>
"""


def inject_css() -> None:
    st.markdown(_DASHBOARD_CSS, unsafe_allow_html=True)
