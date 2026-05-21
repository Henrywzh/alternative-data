from __future__ import annotations

import inspect
from pathlib import Path
import sys
import re
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import matplotlib

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parent.parent
    src_root = repo_root / "src"
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(src_root))

from dashboard.checks import CheckResult, run_checks
from dashboard.data import (
    DOMAIN_ORDER,
    DATASET_REGISTRY,
    DatasetLoadResult,
    FreshnessInfo,
    dataset_source_for_domain,
    domain_dataset_ids,
    load_domain_datasets,
    load_latest_manifest,
)
from openrouter_revenue import (
    build_price_context,
    build_conservative_provider_economics,
    estimate_usage_revenue,
    summarize_economics_coverage,
)
from semiconductor_memory_data.sources.config import AI_DEMAND_PPI_WEIGHTS


BASE_DIR = Path(__file__).resolve().parent.parent

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

NPM_CATEGORY_LABELS = {
    "core_sdk": "Core SDK",
    "agent_sdk": "Agent SDK",
    "cli": "CLI",
    "legacy_sdk": "Legacy SDK",
}

BIG_TECH_ORGS = ["openai", "google", "anthropic", "meta", "mistralai", "deepseek", "qwen", "moonshotai"]
MAIN_SECTIONS = (
    "OpenRouter Intelligence",
    "Artificial Analysis",
    "AI Frontier & HBM",
    "GitHub Trending",
    "Provider Adoption",
    "Semiconductor Analysis",
)
SECTION_DOMAIN_MAP = {
    "OpenRouter Intelligence": ("rankings", "apps", "compute_availability"),
    "Artificial Analysis": ("artificial_analysis",),
    "AI Frontier & HBM": ("ai_frontier",),
    "GitHub Trending": ("github",),
    "Provider Adoption": ("provider_adoption",),
    "Semiconductor Analysis": ("semiconductor_memory",),
}
REVENUE_CACHE_VERSION = "2026-04-23-historical-revenue-fallback-v1"
AI_DEMAND_PPI_COMPONENT_COLUMNS = {
    "PCU33443344": "ppi_component_pcu33443344_rebased",
    "PCU33423342": "ppi_component_pcu33423342_rebased",
    "PCU335313335313": "ppi_component_pcu335313335313_rebased",
    "PCU334111334111": "ppi_component_pcu334111334111_rebased",
    "PCU3341123341121": "ppi_component_pcu3341123341121_rebased",
}
AI_DEMAND_PPI_LABELS = {
    "PCU33443344": "Semiconductors and Other Electronic Components",
    "PCU33423342": "Communications Equipment",
    "PCU334111334111": "Electronic Computers and Servers",
    "PCU3341123341121": "Storage Devices",
    "PCU335313335313": "Switchgear and Power Distribution Equipment",
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def format_metric(value: float, metric_unit: str | None = None) -> str:
    if pd.isna(value):
        return "-"
    if metric_unit == "share":
        return f"{value:.2f}%"
    abs_v = abs(value)
    if abs_v >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.2f}T"
    if abs_v >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if abs_v >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs_v >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.0f}"


WEEKLY_MONTHLY_OTHER_PROVIDERS = {
    "Tngtech",
    "Others",
    "OpenRouter",
    "Microsoft",
    "NousResearch",
    "NVIDIA",
    "Arcee AI",
}

DAILY_OTHER_PROVIDERS = {
    "Microsoft",
    "Meta (Llama)",
    "Mistral AI",
}

US_PROVIDER_ORDER = [
    "OpenAI",
    "Anthropic",
    "Google",
    "Meta (Llama)",
    "xAI (Grok)",
    "Microsoft",
]
CHINA_PROVIDER_ORDER = [
    "DeepSeek",
    "Alibaba (Qwen)",
    "智谱AI (Z.ai)",
    "Moonshot AI",
    "MiniMax",
    "Xiaomi",
    "Tencent",
    "StepFun",
]


def order_provider_columns(pivot_df: pd.DataFrame) -> pd.DataFrame:
    """Apply dashboard-wide provider order for token/revenue displays."""
    if pivot_df.empty:
        return pivot_df.copy()

    columns = list(pivot_df.columns)
    ordered: list[object] = []

    for provider in US_PROVIDER_ORDER + CHINA_PROVIDER_ORDER:
        if provider in columns:
            ordered.append(provider)

    known = set(US_PROVIDER_ORDER + CHINA_PROVIDER_ORDER + ["Others"])
    other_named = sorted((col for col in columns if col not in known), key=lambda value: str(value).casefold())
    ordered.extend(other_named)

    if "Others" in columns:
        ordered.append("Others")

    return pivot_df.loc[:, ordered]


def regroup_provider_pivot_for_display(pivot_df: pd.DataFrame, granularity: str) -> pd.DataFrame:
    """Fold selected provider labels into a display-only Others bucket."""
    if pivot_df.empty:
        return pivot_df.copy()

    if granularity in {"weekly", "monthly"}:
        targets = WEEKLY_MONTHLY_OTHER_PROVIDERS
    elif granularity == "daily":
        targets = DAILY_OTHER_PROVIDERS
    else:
        raise ValueError(f"Unsupported granularity: {granularity}")

    target_keys = {target.casefold() for target in targets}
    matched_cols = [col for col in pivot_df.columns if str(col).casefold() in target_keys]
    if not matched_cols:
        return order_provider_columns(pivot_df.copy())

    kept_cols = [col for col in pivot_df.columns if col not in matched_cols]
    regrouped = pivot_df[kept_cols].copy()
    regrouped["Others"] = pivot_df[matched_cols].sum(axis=1)
    return order_provider_columns(regrouped)


def grouped_revenue_token_pivots(
    rev_data: dict[str, object],
    tok_data: dict[str, object],
    granularity: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return revenue/token pivots after applying the display grouping for one granularity."""
    rev_key = {
        "daily": "pivot_rev_daily",
        "weekly": "pivot_rev_weekly",
        "monthly": "pivot_rev_monthly",
    }[granularity]
    tok_key = {
        "daily": "pivot_daily",
        "weekly": "pivot_weekly",
        "monthly": "pivot_monthly",
    }[granularity]
    return (
        regroup_provider_pivot_for_display(rev_data.get(rev_key, pd.DataFrame()), granularity),
        regroup_provider_pivot_for_display(tok_data.get(tok_key, pd.DataFrame()), granularity),
    )


def build_normalized_signature(base_dir: Path, domain: str | None = None) -> tuple[tuple[str, int, int], ...]:
    """Return a stable fingerprint of normalized dashboard inputs for cache invalidation."""
    normalized = base_dir / "data" / "normalized"
    tracked_roots = [normalized] if domain is None else [normalized / dataset_source_for_domain(domain)]
    signature: list[tuple[str, int, int]] = []
    for root in tracked_roots:
        if not root.exists():
            continue
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            stat = path.stat()
            signature.append((str(path.relative_to(base_dir)), stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


def build_manifest_signature(base_dir: Path, domain: str) -> tuple[tuple[str, int, int], ...]:
    raw_dir = base_dir / "data" / "raw" / dataset_source_for_domain(domain)
    if not raw_dir.exists():
        return tuple()

    manifests = sorted(raw_dir.glob("*/manifest.json"))
    if not manifests:
        return tuple()

    latest = max(manifests, key=lambda p: p.stat().st_mtime_ns)
    stat = latest.stat()
    return ((str(latest.relative_to(base_dir)), stat.st_mtime_ns, stat.st_size),)


def build_domain_signature(base_dir: Path, domain: str) -> tuple[tuple[str, int, int], ...]:
    return build_normalized_signature(base_dir, domain) + build_manifest_signature(base_dir, domain)


def section_domains(section: str) -> tuple[str, ...]:
    return SECTION_DOMAIN_MAP[section]


def select_main_section() -> str:
    label = "Dashboard section"
    if hasattr(st, "segmented_control"):
        selected = st.segmented_control(label, MAIN_SECTIONS, default=MAIN_SECTIONS[0])
        return str(selected or MAIN_SECTIONS[0])
    return str(st.radio(label, MAIN_SECTIONS, horizontal=True))


def render_dataset_guard(result: DatasetLoadResult, show_subheader: bool = False) -> bool:
    if show_subheader:
        st.subheader(result.label)
    if result.source_path is None:
        st.error(f"No file found for {result.dataset_id}.")
        return False
    if result.frame.empty:
        st.warning("Dataset is present but empty.")
        return False
    return True


def default_range(values: list[str]) -> tuple[str, str]:
    if not values:
        return ("", "")
    start_index = max(0, len(values) - 30)
    return values[start_index], values[-1]


def domain_ranges(datasets: dict[str, DatasetLoadResult]) -> dict[str, tuple[str | None, str | None]]:
    ranges: dict[str, tuple[str | None, str | None]] = {}
    for domain, ids in DOMAIN_ORDER.items():
        first_dates  = [datasets[d].first_date  for d in ids if datasets[d].first_date]
        latest_dates = [datasets[d].latest_date for d in ids if datasets[d].latest_date]
        ranges[domain] = (
            min(first_dates)  if first_dates  else None,
            max(latest_dates) if latest_dates else None,
        )
    return ranges


def format_scraped_at_display(value: str | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(timestamp):
        return str(value)
    return timestamp.strftime("%Y-%m-%d %H:%M UTC")


def dataframe_for_display(frame: pd.DataFrame, missing_text: str = "") -> pd.DataFrame:
    """Fill display placeholders only for text-like columns to preserve numeric Arrow types."""
    display = frame.copy()
    if display.empty:
        return display
    for column in display.columns:
        series = display[column]
        if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            display[column] = series.where(series.notna(), missing_text)
        elif pd.api.types.is_datetime64_any_dtype(series):
            display[column] = series.astype("string").where(series.notna(), missing_text)
    return display


def rankings_week_context(datasets: dict[str, DatasetLoadResult]) -> dict[str, str | bool | None]:
    top_models = datasets.get("top_models")
    market_share = datasets.get("market_share")

    model_week = top_models.latest_date if top_models else None
    market_share_week = market_share.latest_date if market_share else None

    return {
        "model_week": model_week,
        "market_share_week": market_share_week,
        "model_scraped_at": top_models.latest_scraped_at if top_models else None,
        "market_share_scraped_at": market_share.latest_scraped_at if market_share else None,
        "has_divergent_weeks": bool(model_week and market_share_week and model_week != market_share_week),
    }


def rankings_bucket_warning(context: dict[str, str | bool | None]) -> str | None:
    if not context.get("has_divergent_weeks"):
        return None
    return (
        "Model rankings use week starting dates, while market share uses week ending dates. "
        "The latest completed buckets can differ by up to 6 days on the same scrape."
    )


def prepare_hf_models_table(
    latest_hf_models: pd.DataFrame,
    *,
    provider_display_name: str | None,
    metric_label: str = "Trailing 30d",
    limit: int = 20,
) -> pd.DataFrame:
    if latest_hf_models.empty or not provider_display_name or provider_display_name == "All":
        return pd.DataFrame(columns=["Provider", "Model", "30d Downloads", "All-Time Downloads", "Daily (Est)", "Likes", "Last Modified"])

    table = latest_hf_models[latest_hf_models["provider_display_name"] == provider_display_name].copy()
    if table.empty:
        return pd.DataFrame(columns=["Provider", "Model", "30d Downloads", "All-Time Downloads", "Daily (Est)", "Likes", "Last Modified"])

    if metric_label == "Daily (Est)":
        sort_columns = ["hf_downloads_daily_est", "hf_downloads_all_time"]
    elif metric_label == "All-time":
        sort_columns = ["hf_downloads_all_time", "hf_downloads_30d"]
    else:
        sort_columns = ["hf_downloads_30d", "hf_downloads_all_time"]

    table = table.sort_values(sort_columns, ascending=[False, False], na_position="last").head(limit)

    return table.rename(
        columns={
            "provider_display_name": "Provider",
            "model_id": "Model",
            "hf_downloads_30d": "30d Downloads",
            "hf_downloads_all_time": "All-Time Downloads",
            "hf_downloads_daily_est": "Daily (Est)",
            "hf_likes": "Likes",
            "hf_last_modified": "Last Modified",
        }
    )[
        ["Provider", "Model", "30d Downloads", "All-Time Downloads", "Daily (Est)", "Likes", "Last Modified"]
    ]


def resolve_hf_metric_config(metric_label: str) -> dict[str, str]:
    if metric_label == "All-time":
        return {
            "value_column": "downloads_all_time",
            "downloads_title": "Hugging Face All-Time Downloads",
            "downloads_axis": "Downloads (All-Time)",
            "downloads_hover": "all-time downloads",
            "share_title": "Hugging Face Download Share (All-Time)",
            "models_caption_metric": "all-time downloads",
        }
    if metric_label == "Daily (Est)":
        return {
            "value_column": "downloads_daily_est",
            "downloads_title": "Hugging Face Daily Downloads (Est)",
            "downloads_axis": "Downloads (Daily Est)",
            "downloads_hover": "estimated daily downloads",
            "share_title": "Hugging Face Download Share (Daily Est)",
            "models_caption_metric": "estimated daily downloads",
        }
    return {
        "value_column": "downloads_30d",
        "downloads_title": "Hugging Face Trailing 30d Downloads",
        "downloads_axis": "Downloads (30d)",
        "downloads_hover": "30d downloads",
        "share_title": "Hugging Face Download Share (30d)",
        "models_caption_metric": "trailing 30d downloads",
    }


def make_stacked_bar(
    pivot_df: pd.DataFrame,
    colors: list[str],
    title: str = "",
    y_title: str = "",
    pct: bool = False,
    height: int = 380,
) -> go.Figure:
    fig = go.Figure()
    for i, col in enumerate(pivot_df.columns):
        fig.add_trace(go.Bar(
            name=col,
            x=pivot_df.index,
            y=pivot_df[col],
            marker_color=colors[i % len(colors)],
            hovertemplate=f"<b>{col}</b><br>%{{x}}<br>%{{y:,.2f}}<extra></extra>",
        ))
    layout: dict = dict(
        barmode="stack",
        template="plotly_white",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color=TEXT, size=12),
        legend=dict(orientation="h", y=-0.18, font=dict(size=11)),
        xaxis=dict(gridcolor=GRID, tickcolor=TICK, showgrid=False, tickfont=dict(size=11)),
        yaxis=dict(gridcolor=GRID, tickcolor=TICK, title=y_title, tickfont=dict(size=11)),
        height=height,
        margin=dict(l=0, r=0, t=40 if title else 10, b=80),
    )
    if title:
        layout["title"] = dict(text=title, font=dict(size=14, color=TEXT))
    fig.update_layout(**layout)
    if pct:
        fig.update_yaxes(ticksuffix="%")
    return fig


def make_stacked_area_chart(
    pivot_df: pd.DataFrame,
    display_index: list,
    colors: list[str],
    x_title: str = "",
    y_title: str = "",
    height: int = 400,
    value_format: str = ",.2f",
    hover_prefix: str = "",
    hover_suffix: str = "",
) -> go.Figure:
    """Stacked area chart factory for time-series metrics."""
    fig = go.Figure()
    suffix = f" {hover_suffix}" if hover_suffix else ""
    for i, col in enumerate(pivot_df.columns):
        fig.add_trace(go.Scatter(
            x=display_index, y=pivot_df[col], name=col,
            mode="lines+markers", stackgroup="one",
            line=dict(width=0.5, color=colors[i % len(colors)]),
            hovertemplate=f"<b>{col}</b><br>%{{x}}<br>{hover_prefix}%{{y:{value_format}}}{suffix}<extra></extra>",
        ))
    fig.update_layout(
        template="plotly_white", xaxis_title=x_title, yaxis_title=y_title,
        legend=dict(orientation="h", y=-0.2), height=height,
        margin=dict(l=0, r=0, t=20, b=80),
    )
    return fig


def make_line_chart(
    pivot_df: pd.DataFrame,
    colors: list[str],
    title: str = "",
    y_title: str = "",
    x_title: str = "Date",
    hover_suffix: str = "",
    height: int = 360,
) -> go.Figure:
    """Line chart factory — mirrors make_stacked_bar for time-series line charts."""
    fig = go.Figure()
    suffix = f" {hover_suffix}" if hover_suffix else ""
    for i, col in enumerate(pivot_df.columns):
        fig.add_trace(go.Scatter(
            x=pivot_df.index,
            y=pivot_df[col],
            name=col,
            mode="lines+markers",
            line=dict(width=3, color=colors[i % len(colors)]),
            hovertemplate=f"<b>{col}</b><br>%{{x}}<br>%{{y:,.0f}}{suffix}<extra></extra>",
        ))
    layout: dict = dict(
        template="plotly_white",
        xaxis_title=x_title,
        yaxis_title=y_title,
        legend=dict(orientation="h", y=-0.2),
        height=height,
        margin=dict(l=0, r=0, t=40, b=80),
    )
    if title:
        layout["title"] = title
    fig.update_layout(**layout)
    return fig


def kpi_card_html(
    label: str,
    value: str,
    delta: str = "",
    delta_class: str = "flat",
    card_style: str = "",
    value_style: str = "",
) -> str:
    """Return a single .kpi-card HTML block. Wrap multiple cards in a .kpi-grid div."""
    card_attr = f' style="{card_style}"' if card_style else ""
    value_attr = f' style="{value_style}"' if value_style else ""
    delta_html = f'<div class="kpi-delta-{delta_class}">{delta}</div>' if delta else ""
    return (
        f'<div class="kpi-card"{card_attr}>'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value"{value_attr}>{value}</div>'
        f'{delta_html}'
        f'</div>'
    )


def kpi_grid_html(*cards: str) -> str:
    """Wrap kpi_card_html() outputs in a .kpi-grid container."""
    return '<div class="kpi-grid">' + "".join(cards) + "</div>"


def _top_n_with_others(pivot_df: pd.DataFrame, *, top_n_count: int = 15, exclude_others_named: bool = False, pct: bool = False) -> pd.DataFrame:
    if pivot_df.empty:
        return pivot_df.copy()

    if exclude_others_named:
        named_cols = [c for c in pivot_df.columns if str(c).lower() != "others"]
        other_cols = [c for c in pivot_df.columns if str(c).lower() == "others"]
        top_n_named = pivot_df[named_cols].sum().nlargest(top_n_count).index.tolist()
        rest_cols = [c for c in named_cols if c not in top_n_named] + other_cols
        base = pivot_df.copy()
        if pct:
            row_totals = base.sum(axis=1)
            base = base.div(row_totals, axis=0).mul(100).fillna(0)
        top = base[top_n_named].copy()
        if rest_cols:
            top["Others"] = base[rest_cols].sum(axis=1)
        return top

    top_n_cols = pivot_df.sum().nlargest(top_n_count).index.tolist()
    other_cols = [c for c in pivot_df.columns if c not in top_n_cols]
    top = pivot_df[top_n_cols].copy()
    if other_cols:
        existing_others = top["Others"].copy() if "Others" in top.columns else 0
        top["Others"] = existing_others + pivot_df[other_cols].sum(axis=1)
    return top


def market_share_legend_rows(frame: pd.DataFrame, week_label: str, limit: int = 8) -> pd.DataFrame:
    """Build selected-week market-share legend rows with same-window tokens and shares."""
    week_rows = frame[frame["week_start_date"] == week_label].groupby("entity_id", as_index=False)["metric_value"].sum()
    week_total = float(week_rows["metric_value"].sum())
    named = week_rows[week_rows["entity_id"].str.lower() != "others"].sort_values("metric_value", ascending=False).head(limit).copy()
    if named.empty:
        return named.assign(share_pct=pd.Series(dtype=float))
    named["share_pct"] = named["metric_value"] / week_total * 100 if week_total > 0 else 0.0
    return named


@st.cache_data(ttl=3600)
def load_domain_state_cached(
    base_dir: Path,
    domain: str,
    domain_signature: tuple[tuple[str, int, int], ...],
) -> tuple[dict[str, DatasetLoadResult], FreshnessInfo, list[CheckResult]]:
    _ = domain_signature
    datasets = load_domain_datasets(domain, base_dir=base_dir)
    freshness = load_latest_manifest(base_dir=base_dir, datasets=datasets, scan_raw_manifests=False)
    # Streamlit Cloud can briefly serve mixed app/checker versions during deploys.
    # Prefer the narrowed domain-aware API when present, but keep the app bootable
    # if an older dashboard.checks module is still resident.
    if "expected_dataset_ids" in inspect.signature(run_checks).parameters:
        checks = run_checks(datasets, freshness, base_dir=base_dir, expected_dataset_ids=domain_dataset_ids(domain))
    else:
        checks = run_checks(datasets, freshness, base_dir=base_dir)
    return datasets, freshness, checks


# --- OpenRouter Provider Mapping ---
OPENROUTER_PROVIDER_MAP = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "meta": "Meta (Llama)",
    "meta-llama": "Meta (Llama)",
    "mistralai": "Mistral AI",
    "cohere": "Cohere",
    "qwen": "Alibaba (Qwen)",
    "z-ai": "智谱AI (Z.ai)",
    "deepseek": "DeepSeek",
    "google-palm": "Google (PaLM)",
    "perplexity": "Perplexity",
    "nvidia": "NVIDIA",
    "databricks": "Databricks",
    "pygmalionai": "Pygmalion AI",
    "bytedance-seed": "ByteDance (Seed)",
    "liquid": "Liquid AI",
    "arcee-ai": "Arcee AI",
    "stepfun": "StepFun",
    "kwaipilot": "Kwai (Kwailab)",
    "rekaai": "Reka AI",
    "xiaomi": "Xiaomi",
    "minimax": "MiniMax",
    "tencent": "Tencent",
    "x-ai": "xAI (Grok)",
    "01-ai": "01.AI (Yi)",
    "upstage": "Upstage",
    "together-ai": "Together AI",
    "microsoft": "Microsoft",
    "openrouter": "OpenRouter",
    "moonshotai": "Moonshot AI",
    "zhipu": "智谱AI (Z.ai)",
}


def _derive_provider_name(model_id: str, official_provider: str | None) -> str:
    """Derives a provider name from the model ID if the official provider is missing."""
    if pd.notna(official_provider) and str(official_provider).strip() != "" and str(official_provider) != "nan":
        # Check if official_provider is a number (like 262144 from historical bug)
        try:
            val = float(official_provider)
            if val > 1000: # Likely context length or other numeric metadata leak
                pass # fall through to derivation
            else:
                return str(official_provider)
        except (ValueError, TypeError):
            return str(official_provider)
    
    if pd.isna(model_id) or not isinstance(model_id, str):
        return "Unknown"
        
    if "/" in model_id:
        slug_prefix = model_id.split("/")[0].lower()
        return OPENROUTER_PROVIDER_MAP.get(slug_prefix, slug_prefix.capitalize())
    
    return "Unknown"



def _fuzzy_normalize_model_id(model_id: str) -> str:
    """Normalize model IDs to match between rankings and pricing table."""
    val = str(model_id).lower()
    # Strip date suffixes like -20260217
    val = re.sub(r"-(202[0-9]{5}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2})$", "", val)
    # Strip modifiers
    val = val.replace(":thinking", "").replace(":beta", "").replace(":free", "").replace(":online", "")
    
    parts = val.split("/")
    if len(parts) < 2:
        return val
        
    provider, model = parts[0], parts[1]
    # Tokenize model part
    tokens = re.findall(r"[a-z0-9.]+", model)
    # Join sorted to handle order swaps (e.g. claude-4.6-sonnet vs claude-sonnet-4.6)
    normalized_model = "".join(sorted(tokens))
    return f"{provider}/{normalized_model}"


@st.cache_data(ttl=3600)
def compute_openrouter_views(
    datasets: dict[str, DatasetLoadResult],
    revenue_cache_version: str = REVENUE_CACHE_VERSION,
) -> dict[str, object]:
    _ = revenue_cache_version
    views: dict[str, object] = {}

    top_models_result = datasets.get("top_models")
    market_share_result = datasets.get("market_share")
    if not top_models_result or top_models_result.frame.empty:
        views["top_models"] = {"weeks": [], "pivot_total": pd.DataFrame()}
    else:
        top_frame = top_models_result.frame.copy()
        top_frame["week_start_date"] = top_frame["week_start_date"].astype(str)
        top_totals = (
            top_frame.groupby("week_start_date", as_index=True)["metric_value"]
            .sum()
            .rename("top_models")
            .sort_index()
        )
        merged_totals = top_totals.to_frame()
        total_source = "top_models"
        if market_share_result and not market_share_result.frame.empty:
            market_frame = market_share_result.frame.copy()
            market_totals = _market_share_weekly_totals(market_frame)
            merged_totals = merged_totals.join(market_totals, how="outer")

            def _select_total(row: pd.Series) -> float:
                top_value = pd.to_numeric(pd.Series([row.get("top_models")]), errors="coerce").iloc[0]
                share_value = pd.to_numeric(pd.Series([row.get("market_share")]), errors="coerce").iloc[0]
                if pd.isna(share_value):
                    return float(top_value) if pd.notna(top_value) else np.nan
                if pd.isna(top_value):
                    return float(share_value)
                if share_value >= top_value * 0.80:
                    return float(share_value)
                return float(top_value)

            def _select_source(row: pd.Series) -> str:
                top_value = pd.to_numeric(pd.Series([row.get("top_models")]), errors="coerce").iloc[0]
                share_value = pd.to_numeric(pd.Series([row.get("market_share")]), errors="coerce").iloc[0]
                if pd.isna(share_value):
                    return "top_models"
                if pd.isna(top_value):
                    return "market_share"
                return "market_share" if share_value >= top_value * 0.80 else "top_models"

            merged_totals["selected_source"] = merged_totals.apply(_select_source, axis=1)
            merged_totals["Total Tokens"] = merged_totals.apply(_select_total, axis=1)
            previous_total = np.nan
            for index, row in merged_totals.sort_index().iterrows():
                if row["selected_source"] == "market_share" and pd.isna(row.get("top_models")) and pd.notna(previous_total):
                    share_value = pd.to_numeric(pd.Series([row.get("market_share")]), errors="coerce").iloc[0]
                    if pd.notna(share_value) and share_value < previous_total * 0.80:
                        merged_totals.at[index, "Total Tokens"] = np.nan
                        merged_totals.at[index, "selected_source"] = "suppressed_incomplete_market_share"
                        continue
                if pd.notna(row.get("Total Tokens")):
                    previous_total = float(row["Total Tokens"])
            total_source = "hybrid"
        else:
            merged_totals["selected_source"] = "top_models"
            merged_totals["Total Tokens"] = merged_totals["top_models"]

        pivot_total = merged_totals[["Total Tokens"]].dropna().sort_index()
        views["top_models"] = {
            "weeks": sorted(pivot_total.index.astype(str).tolist(), reverse=True),
            "pivot_total": pivot_total,
            "total_source": total_source,
            "source_by_week": merged_totals.get("selected_source", pd.Series(dtype="string")).to_dict(),
        }

    result = datasets.get("market_share")
    if result and not result.frame.empty:
        frame = result.frame.copy()
        frame["week_start_date"] = frame["week_start_date"].astype(str)
        pivot = (
            frame.pivot_table(index="week_start_date", columns="entity_id", values="metric_value", aggfunc="sum")
            .fillna(0)
            .sort_index()
        )
        views["market_share"] = {
            "weeks": sorted(frame["week_start_date"].unique(), reverse=True),
            "pivot_pct_top": _top_n_with_others(pivot, top_n_count=15, exclude_others_named=True, pct=True),
        }
    else:
        views["market_share"] = {"weeks": [], "pivot_pct_top": pd.DataFrame()}

    views.update(_compute_revenue_views(datasets))
    return views


def _week_start(series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(series, errors="coerce")
    return (dates - pd.to_timedelta(dates.dt.weekday, unit="D")).dt.normalize().dt.strftime("%Y-%m-%d")


def _align_rankings_week_to_monday(series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(series, errors="coerce")
    dates = dates.apply(lambda value: value + pd.Timedelta(days=1) if pd.notna(value) and value.weekday() == 6 else value)
    return (dates - pd.to_timedelta(dates.dt.weekday, unit="D")).dt.normalize().dt.strftime("%Y-%m-%d")


def _market_share_weekly_totals(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype="float64", name="market_share")
    market = frame.copy()
    original_dates = pd.to_datetime(market["week_start_date"].astype(str), errors="coerce")
    market["original_week_start_date"] = original_dates.dt.normalize()
    market["week_start_date"] = _align_rankings_week_to_monday(market["week_start_date"].astype(str))
    market["metric_value"] = pd.to_numeric(market["metric_value"], errors="coerce")
    totals = (
        market.dropna(subset=["original_week_start_date", "week_start_date"])
        .groupby(["week_start_date", "original_week_start_date"], as_index=False)["metric_value"]
        .sum()
    )
    if totals.empty:
        return pd.Series(dtype="float64", name="market_share")
    totals["is_aligned_monday"] = totals["original_week_start_date"].dt.strftime("%Y-%m-%d") == totals["week_start_date"]
    totals = totals.sort_values(
        ["week_start_date", "is_aligned_monday", "metric_value", "original_week_start_date"],
        ascending=[True, False, False, False],
    )
    return (
        totals.drop_duplicates(subset=["week_start_date"], keep="first")
        .set_index("week_start_date")["metric_value"]
        .rename("market_share")
        .sort_index()
    )


def _period_coverage(frame: pd.DataFrame, period_column: str, date_column: str, expected_days: int) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[period_column, "observed_days", "expected_days", "is_partial_period"])
    coverage = (
        frame.groupby(period_column)[date_column]
        .nunique()
        .rename("observed_days")
        .reset_index()
        .sort_values(period_column)
    )
    coverage["expected_days"] = expected_days
    coverage["is_partial_period"] = coverage["observed_days"] < coverage["expected_days"]
    return coverage


def _scale_partial_week_values(
    modern_frame: pd.DataFrame,
    pivot_raw: pd.DataFrame,
    week_column: str,
    provider_column: str,
    value_column: str,
    date_column: str,
) -> pd.DataFrame:
    if pivot_raw.empty:
        return pivot_raw

    pivot = pivot_raw.copy()
    days_per_week = (
        modern_frame.groupby([week_column, provider_column])[date_column]
        .nunique()
        .rename("days_present")
    )
    first_week = pivot.index.min()
    first_week_dt = pd.Timestamp(first_week)
    next_week = (first_week_dt + pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    first_week_rows = modern_frame[modern_frame[week_column] == first_week].copy()
    next_week_rows = modern_frame[modern_frame[week_column] == next_week].copy()

    if not next_week_rows.empty:
        for provider in pivot.columns:
            provider_first_rows = first_week_rows[first_week_rows[provider_column] == provider]
            if provider_first_rows.empty:
                continue
            observed_weekdays = set(provider_first_rows[date_column].dt.weekday.astype(int).tolist())
            if 0 < len(observed_weekdays) < 7:
                missing_weekdays = set(range(7)) - observed_weekdays
                provider_next_rows = next_week_rows[next_week_rows[provider_column] == provider]
                bridged_missing = provider_next_rows[
                    provider_next_rows[date_column].dt.weekday.isin(missing_weekdays)
                ][value_column].sum()
                if bridged_missing > 0:
                    observed_total = provider_first_rows[value_column].sum()
                    pivot.loc[first_week, provider] = observed_total + bridged_missing

    for week in pivot.index:
        for provider in pivot.columns:
            try:
                days_present = days_per_week.loc[(week, provider)]
            except KeyError:
                continue
            if 0 < days_present < 7:
                if week == first_week and pivot.loc[week, provider] > 0:
                    provider_first_rows = modern_frame[
                        (modern_frame[week_column] == week) & (modern_frame[provider_column] == provider)
                    ]
                    observed_total = provider_first_rows[value_column].sum()
                    if pivot.loc[week, provider] > observed_total:
                        continue
                pivot.loc[week, provider] *= 7 / days_present
    return pivot.sort_index()


def _revenue_pivots_from_economics(economics: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if economics.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    priced = economics[economics["estimated_revenue"].notna()].copy()
    if priced.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    priced["usage_date_dt"] = pd.to_datetime(priced["usage_date"], errors="coerce")
    priced = priced.dropna(subset=["usage_date_dt"])
    priced["usage_date_str"] = priced["usage_date_dt"].dt.strftime("%Y-%m-%d")
    priced["usage_week"] = _week_start(priced["usage_date_dt"])
    priced["usage_month"] = priced["usage_date_dt"].dt.strftime("%Y-%m")
    priced["provider_label"] = priced["provider_name"].fillna(priced["provider_slug"])
    daily = priced.pivot_table(index="usage_date_str", columns="provider_label", values="estimated_revenue", aggfunc="sum").fillna(0).sort_index()
    weekly = priced.pivot_table(index="usage_week", columns="provider_label", values="estimated_revenue", aggfunc="sum").fillna(0).sort_index()
    monthly = priced.pivot_table(index="usage_month", columns="provider_label", values="estimated_revenue", aggfunc="sum").fillna(0).sort_index()
    return daily, weekly, monthly


def _is_xiaomi_mimo_backpricing_hazard(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=bool, index=frame.index)
    usage_date = pd.to_datetime(frame.get("usage_date"), errors="coerce").dt.strftime("%Y-%m-%d")
    provider = frame.get("entity_id", frame.get("provider_slug", pd.Series("", index=frame.index))).astype("string").str.lower()
    model = frame.get("model_permaslug", pd.Series("", index=frame.index)).astype("string").str.lower()
    return (
        provider.eq("xiaomi")
        & usage_date.between("2026-03-19", "2026-04-05")
        & model.str.startswith("xiaomi/mimo-v2-", na=False)
    )


def _compute_revenue_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    """Dashboard-oriented provider tokens and revenue with legacy fallback stitching."""
    provider_res = datasets.get("provider_daily_activity")
    model_activity_res = datasets.get("openrouter_model_activity")
    market_share_res = datasets.get("market_share")
    pricing_res = datasets.get("raw_openrouter_models")
    macro_res = datasets.get("top_models")

    provider_activity = provider_res.frame.copy() if provider_res and not provider_res.frame.empty else pd.DataFrame()
    model_activity = (
        model_activity_res.frame.copy() if model_activity_res and not model_activity_res.frame.empty else pd.DataFrame()
    )
    pricing = pricing_res.frame.copy() if pricing_res and not pricing_res.frame.empty else pd.DataFrame()

    economics = build_conservative_provider_economics(
        provider_activity,
        pricing,
        model_activity=model_activity,
    )
    pivot_rev_daily = pd.DataFrame()
    pivot_rev_weekly = pd.DataFrame()
    pivot_rev_monthly = pd.DataFrame()

    pivot_tok_daily = pd.DataFrame()
    pivot_tok_weekly_modern = pd.DataFrame()
    pivot_tok_monthly_modern = pd.DataFrame()
    weekly_coverage = pd.DataFrame()
    monthly_coverage = pd.DataFrame()
    if not provider_activity.empty:
        modern_tok = provider_activity.copy()
        modern_tok["usage_date_dt"] = pd.to_datetime(modern_tok["usage_date"], errors="coerce")
        modern_tok = modern_tok.dropna(subset=["usage_date_dt"]).copy()
        modern_tok["usage_date_str"] = modern_tok["usage_date_dt"].dt.strftime("%Y-%m-%d")
        modern_tok["usage_week"] = _week_start(modern_tok["usage_date_dt"])
        modern_tok["usage_month"] = modern_tok["usage_date_dt"].dt.strftime("%Y-%m")
        modern_tok["provider_label"] = modern_tok["entity_name"].fillna(modern_tok["entity_id"])
        modern_tok["total_tokens"] = pd.to_numeric(modern_tok["total_tokens"], errors="coerce")
        pivot_tok_daily = modern_tok.pivot_table(index="usage_date_str", columns="provider_label", values="total_tokens", aggfunc="sum").fillna(0).sort_index()
        pivot_tok_weekly_modern_raw = modern_tok.pivot_table(index="usage_week", columns="provider_label", values="total_tokens", aggfunc="sum").fillna(0)
        pivot_tok_weekly_modern = _scale_partial_week_values(
            modern_tok,
            pivot_tok_weekly_modern_raw,
            "usage_week",
            "provider_label",
            "total_tokens",
            "usage_date_dt",
        )
        pivot_tok_monthly_modern = modern_tok.pivot_table(index="usage_month", columns="provider_label", values="total_tokens", aggfunc="sum").fillna(0).sort_index()
        weekly_coverage = _period_coverage(modern_tok, "usage_week", "usage_date_str", 7)
        monthly_expected = modern_tok.assign(
            expected_days=modern_tok["usage_date_dt"].dt.days_in_month
        ).groupby("usage_month", as_index=False)["expected_days"].max()
        monthly_coverage = (
            modern_tok.groupby("usage_month")["usage_date_str"].nunique().rename("observed_days").reset_index()
            .merge(monthly_expected, on="usage_month", how="left")
        )
        monthly_coverage["is_partial_period"] = monthly_coverage["observed_days"] < monthly_coverage["expected_days"]

    pivot_tok_weekly_legacy = pd.DataFrame()
    tok_legacy = pd.DataFrame()
    if market_share_res and not market_share_res.frame.empty:
        share = market_share_res.frame.copy()
        share["usage_week"] = _align_rankings_week_to_monday(share["week_start_date"])
        share = share.dropna(subset=["usage_week"]).copy()
        share = share.drop_duplicates(subset=["usage_week", "entity_id"])
        tok_legacy = share[["usage_week", "entity_id", "metric_value"]].copy()
        tok_legacy["provider_label"] = tok_legacy["entity_id"].apply(lambda x: _derive_provider_name(f"{x}/model", None))
        pivot_tok_weekly_legacy = (
            tok_legacy.pivot_table(index="usage_week", columns="provider_label", values="metric_value", aggfunc="sum")
            .fillna(0)
            .sort_index()
        )
        if not pivot_tok_weekly_modern.empty:
            first_modern_week = pivot_tok_weekly_modern.index.min()
            pivot_tok_weekly_legacy = pivot_tok_weekly_legacy[pivot_tok_weekly_legacy.index < first_modern_week]

    pivot_tok_weekly = pd.concat([pivot_tok_weekly_legacy, pivot_tok_weekly_modern]).fillna(0).sort_index()
    pivot_tok_weekly = pivot_tok_weekly.groupby(level=0).sum() if not pivot_tok_weekly.empty else pivot_tok_weekly

    tok_legacy_m = pd.DataFrame()
    if not pivot_tok_weekly_legacy.empty:
        legacy_month_index = pd.to_datetime(pivot_tok_weekly_legacy.index, errors="coerce").strftime("%Y-%m")
        tok_legacy_m = pivot_tok_weekly_legacy.copy()
        tok_legacy_m.index = legacy_month_index
        tok_legacy_m = tok_legacy_m.groupby(level=0).sum().sort_index()
    pivot_tok_monthly = pd.concat([tok_legacy_m, pivot_tok_monthly_modern]).fillna(0).sort_index()
    pivot_tok_monthly = pivot_tok_monthly.groupby(level=0).sum() if not pivot_tok_monthly.empty else pivot_tok_monthly

    big_tech_display = [
        "OpenAI", "Anthropic", "Google", "Meta (Llama)", "DeepSeek",
        "Alibaba (Qwen)", "智谱AI (Z.ai)", "Moonshot AI", "xAI (Grok)",
        "Mistral AI", "Microsoft",
    ]
    if not pivot_tok_weekly.empty:
        for column in big_tech_display:
            if column in pivot_tok_weekly.columns:
                interpolated = pivot_tok_weekly[column].replace(0, float("nan")).interpolate(
                    method="linear", limit=4, limit_area="inside"
                )
                pivot_tok_weekly[column] = interpolated.fillna(0)

    modern_pivot_daily = pd.DataFrame()
    modern_pivot_weekly = pd.DataFrame()
    modern_pivot_monthly = pd.DataFrame()
    if not provider_activity.empty:
        modern_df = provider_activity.copy()
        modern_df = modern_df[~_is_xiaomi_mimo_backpricing_hazard(modern_df)].copy()
        modern_with_price = (
            estimate_usage_revenue(
                modern_df,
                pricing,
                slug_strategy="canonical",
                pricing_strategy="provider_fallback",
            )
            if not modern_df.empty
            else pd.DataFrame()
        )
        if "estimated_revenue" in modern_with_price.columns:
            modern_with_price = modern_with_price[modern_with_price["estimated_revenue"].notna()].copy()
        if not modern_with_price.empty:
            modern_with_price["revenue_usd"] = pd.to_numeric(modern_with_price["estimated_revenue"], errors="coerce")
            modern_with_price["usage_date_dt"] = pd.to_datetime(modern_with_price["usage_date"], errors="coerce")
            modern_with_price = modern_with_price.dropna(subset=["usage_date_dt"])
            modern_with_price = modern_with_price[modern_with_price["revenue_usd"] > 0].copy()
            modern_with_price["usage_date_str"] = modern_with_price["usage_date_dt"].dt.strftime("%Y-%m-%d")
            modern_with_price["usage_week"] = _week_start(modern_with_price["usage_date_dt"])
            modern_with_price["usage_month"] = modern_with_price["usage_date_dt"].dt.strftime("%Y-%m")
            modern_with_price["provider_label"] = modern_with_price["entity_name"].fillna(modern_with_price["provider_slug"])

            modern_pivot_daily = (
                modern_with_price.pivot_table(index="usage_date_str", columns="provider_label", values="revenue_usd", aggfunc="sum")
                .fillna(0).sort_index()
            )
            modern_pivot_weekly_raw = (
                modern_with_price.pivot_table(index="usage_week", columns="provider_label", values="revenue_usd", aggfunc="sum")
                .fillna(0)
            )
            modern_pivot_weekly = _scale_partial_week_values(
                modern_with_price,
                modern_pivot_weekly_raw,
                "usage_week",
                "provider_label",
                "revenue_usd",
                "usage_date_dt",
            )
            modern_pivot_monthly = (
                modern_with_price.pivot_table(index="usage_month", columns="provider_label", values="revenue_usd", aggfunc="sum")
                .fillna(0).sort_index()
            )
            pivot_rev_daily = modern_pivot_daily

    coverage_summary = summarize_economics_coverage(economics)

    if macro_res and not macro_res.frame.empty and market_share_res and not market_share_res.frame.empty:
        macro_df = macro_res.frame.copy()
        share_df = market_share_res.frame.copy()
        macro_df["usage_week"] = _align_rankings_week_to_monday(macro_df["week_start_date"].astype(str))
        share_df["usage_week"] = _align_rankings_week_to_monday(share_df["week_start_date"].astype(str))

        macro_usage = macro_df.copy()
        macro_usage["usage_date"] = macro_usage["usage_week"]
        macro_usage["model_permaslug"] = macro_usage["entity_id"]
        macro_usage["provider_slug"] = macro_usage["parent_entity_id"]
        macro_usage["provider_name"] = macro_usage["parent_entity_name"].fillna(macro_usage["parent_entity_id"])
        macro_usage["total_tokens"] = pd.to_numeric(macro_usage["metric_value"], errors="coerce")
        macro_usage["prompt_tokens"] = 0.0
        macro_usage["completion_tokens"] = 0.0
        macro_usage["reasoning_tokens"] = np.nan

        macro_priced = estimate_usage_revenue(
            macro_usage[[
                "usage_date", "provider_slug", "provider_name", "model_permaslug",
                "total_tokens", "prompt_tokens", "completion_tokens", "reasoning_tokens",
            ]],
            pricing,
            slug_strategy="canonical",
            pricing_strategy="provider_fallback",
        )
        macro_priced = macro_priced[macro_priced["estimated_revenue"].notna()].copy()
        macro_priced["revenue_usd"] = pd.to_numeric(macro_priced["estimated_revenue"], errors="coerce")
        tier1_agg = (
            macro_priced.groupby(["usage_date", "provider_slug"], as_index=False)
            .agg(metric_value=("total_tokens", "sum"), revenue_usd=("revenue_usd", "sum"))
            .rename(columns={"usage_date": "usage_week"})
        )

        price_context = build_price_context(pricing)
        provider_benchmarks = {
            provider: values.get("pricing_blended", np.nan)
            for provider, values in price_context.provider_lookup.items()
            if pd.notna(values.get("pricing_blended", np.nan))
        }
        global_avg_price = (
            price_context.global_stats.get("pricing_blended", np.nan)
            if price_context.global_stats is not None
            else np.nan
        )

        share_dedup = share_df.drop_duplicates(subset=["usage_week", "entity_id"]).copy()
        combined = share_dedup.merge(
            tier1_agg,
            left_on=["usage_week", "entity_id"],
            right_on=["usage_week", "provider_slug"],
            how="left",
        ).fillna({"metric_value_y": 0.0, "revenue_usd": 0.0})

        def _legacy_hybrid_revenue(row: pd.Series) -> float:
            total_share_tokens = float(row.get("metric_value_x", 0.0))
            tier1_tokens = float(row.get("metric_value_y", 0.0))
            tier1_revenue = float(row.get("revenue_usd", 0.0))
            delta_tokens = max(0.0, total_share_tokens - tier1_tokens)
            provider_slug = str(row.get("entity_id", "")).lower()
            provider_median = provider_benchmarks.get(provider_slug, global_avg_price)
            if tier1_tokens > 0:
                vwap = tier1_revenue / tier1_tokens if tier1_tokens else 0.0
                delta_price = max(vwap, provider_median) if pd.notna(provider_median) else vwap
            else:
                delta_price = provider_median if pd.notna(provider_median) else 0.0
            return tier1_revenue + (delta_tokens * delta_price)

        combined["final_revenue"] = combined.apply(_legacy_hybrid_revenue, axis=1)
        combined["provider_label"] = combined["entity_id"].apply(lambda value: _derive_provider_name(f"{value}/model", None))
        combined["usage_date_dt"] = pd.to_datetime(combined["usage_week"], errors="coerce")
        combined["usage_month"] = combined["usage_date_dt"].dt.strftime("%Y-%m")

        pivot_rev_weekly_legacy = (
            combined.pivot_table(index="usage_week", columns="provider_label", values="final_revenue", aggfunc="sum")
            .fillna(0).sort_index()
        )
        pivot_rev_weekly_legacy = pivot_rev_weekly_legacy[pivot_rev_weekly_legacy.index <= "2026-01-05"]

        pivot_rev_monthly_legacy = (
            combined.pivot_table(index="usage_month", columns="provider_label", values="final_revenue", aggfunc="sum")
            .fillna(0).sort_index()
        )
        pivot_rev_monthly_legacy = pivot_rev_monthly_legacy[pivot_rev_monthly_legacy.index <= "2026-01"]

        pivot_rev_weekly = pd.concat([pivot_rev_weekly_legacy, modern_pivot_weekly]).fillna(0).sort_index()
        pivot_rev_weekly = pivot_rev_weekly.groupby(level=0).sum()

        if not modern_pivot_monthly.empty:
            modern_months = set(modern_pivot_monthly.index)
            legacy_only = pivot_rev_monthly_legacy[~pivot_rev_monthly_legacy.index.isin(modern_months)]
            overlap_months = pivot_rev_monthly_legacy[pivot_rev_monthly_legacy.index.isin(modern_months)]
            pivot_rev_monthly = pd.concat([
                legacy_only,
                overlap_months.add(modern_pivot_monthly, fill_value=0),
                modern_pivot_monthly.loc[~modern_pivot_monthly.index.isin(overlap_months.index)],
            ])
            pivot_rev_monthly = pivot_rev_monthly.sort_index().groupby(level=0).sum()
        else:
            pivot_rev_monthly = pivot_rev_monthly_legacy

        for column in big_tech_display:
            if column in pivot_rev_weekly.columns:
                interpolated = pivot_rev_weekly[column].replace(0, float("nan")).interpolate(
                    method="linear", limit=4, limit_area="inside"
                )
                pivot_rev_weekly[column] = interpolated.fillna(0)
            if column in pivot_rev_monthly.columns:
                interpolated = pivot_rev_monthly[column].replace(0, float("nan")).interpolate(
                    method="linear", limit=2, limit_area="inside"
                )
                pivot_rev_monthly[column] = interpolated.fillna(0)
    else:
        if pivot_rev_daily.empty and pivot_rev_weekly.empty and pivot_rev_monthly.empty:
            pivot_rev_daily, pivot_rev_weekly, pivot_rev_monthly = _revenue_pivots_from_economics(economics)

    return {
        "revenue_estimator": {
            "pivot_rev": pivot_rev_daily,
            "pivot_rev_daily": pivot_rev_daily,
            "pivot_rev_weekly": pivot_rev_weekly,
            "pivot_rev_monthly": pivot_rev_monthly,
            "total_revenue": float(pivot_rev_daily.sum().sum()) if not pivot_rev_daily.empty else 0,
            "has_activity": not provider_activity.empty,
            "merged_count": len(economics),
            "economics": economics,
            "coverage": coverage_summary,
        },
        "token_volume": {
            "pivot_daily": pivot_tok_daily,
            "pivot_weekly": pivot_tok_weekly,
            "pivot_monthly": pivot_tok_monthly,
            "weekly_coverage": weekly_coverage,
            "monthly_coverage": monthly_coverage,
        },
    }


@st.cache_data(ttl=3600)
def compute_github_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, dict[str, object]]:
    views: dict[str, dict[str, object]] = {}
    for dataset_id in ["github_trending_daily", "github_trending_weekly", "github_trending_monthly"]:
        result = datasets.get(dataset_id)
        if not result or result.frame.empty:
            views[dataset_id] = {"latest_date": None, "latest_df": pd.DataFrame(), "history_top5": pd.DataFrame()}
            continue

        df = result.frame.copy()
        df["scrape_date"] = df["scrape_date"].astype(str)
        latest_date = df["scrape_date"].max()
        latest_df = df[df["scrape_date"] == latest_date].copy()
        latest_df["stars_today"] = pd.to_numeric(latest_df["stars_today"], errors="coerce").fillna(0)
        latest_df = latest_df.sort_values("stars_today", ascending=False)
        top_5_names = latest_df.head(5)["name"].tolist()
        hist_df = df[df["name"].isin(top_5_names)].copy()
        history_top5 = (
            hist_df.pivot_table(index="scrape_date", columns="name", values="stars_today", aggfunc="sum").fillna(0)
            if not hist_df.empty
            else pd.DataFrame()
        )
        views[dataset_id] = {
            "latest_date": latest_date,
            "latest_df": latest_df,
            "history_top5": history_top5,
        }
    return views


@st.cache_data(ttl=3600)
def compute_provider_adoption_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    views: dict[str, object] = {}
    # Mistral and Qwen don't publish meaningful PyPI/npm packages; exclude from those charts.
    _PYPI_NPM_EXCLUDE = {"Mistral", "Qwen"}

    pypi_result = datasets.get("pypi_downloads_daily")
    npm_result = datasets.get("npm_downloads_daily")
    hf_result = datasets.get("huggingface_models_daily")

    pypi = pypi_result.frame.copy() if pypi_result and pypi_result.frame is not None else pd.DataFrame()
    pypi = pypi[pypi["with_mirrors"] == False].copy() if not pypi.empty else pypi
    pypi = pypi[~pypi["provider_display_name"].isin(_PYPI_NPM_EXCLUDE)].copy() if not pypi.empty else pypi
    if not pypi.empty:
        pypi_grouped = pypi.groupby(["download_date", "provider_display_name"], dropna=False)["downloads"].sum().reset_index()
        pypi_grouped["download_date"] = pypi_grouped["download_date"].astype(str)
        latest_pypi_date = pypi_grouped["download_date"].max()
        latest_pypi = pypi_grouped[pypi_grouped["download_date"] == latest_pypi_date].copy()
    else:
        pypi_grouped = pd.DataFrame(columns=["download_date", "provider_display_name", "downloads"])
        latest_pypi_date = None
        latest_pypi = pd.DataFrame(columns=["download_date", "provider_display_name", "downloads"])

    npm = npm_result.frame.copy() if npm_result and npm_result.frame is not None else pd.DataFrame()
    if not npm.empty:
        npm = npm[~npm["provider_display_name"].isin(_PYPI_NPM_EXCLUDE)].copy()
        npm["download_date"] = npm["download_date"].astype(str)
        npm["package_category"] = npm["package_category"].astype(str)
        npm_categories = sorted(category for category in npm["package_category"].dropna().unique().tolist() if category and category != "<NA>")
        npm_grouped_all = (
            npm.groupby(["package_category", "download_date", "provider_display_name"], dropna=False)["downloads"].sum().reset_index()
        )
        latest_npm_date = npm_grouped_all["download_date"].max()
        latest_npm_all = npm_grouped_all[npm_grouped_all["download_date"] == latest_npm_date].copy()
    else:
        npm_grouped_all = pd.DataFrame(columns=["package_category", "download_date", "provider_display_name", "downloads"])
        latest_npm_date = None
        latest_npm_all = pd.DataFrame(columns=["package_category", "download_date", "provider_display_name", "downloads"])
        npm_categories = []

    hf = hf_result.frame.copy() if hf_result and hf_result.frame is not None else pd.DataFrame()
    if not hf.empty:
        hf["download_date"] = hf["download_date"].astype(str)
        hf_grouped = (
            hf.groupby(["download_date", "provider_display_name"], dropna=False)
            .agg(
                downloads_30d=("hf_downloads_30d", "sum"),
                downloads_all_time=("hf_downloads_all_time", "sum"),
                downloads_daily_est=("hf_downloads_daily_est", lambda values: values.sum(min_count=1)),
                likes=("hf_likes", "sum"),
            )
            .reset_index()
        )
        latest_hf_date = hf_grouped["download_date"].max()
        latest_hf = hf_grouped[hf_grouped["download_date"] == latest_hf_date].copy()
        latest_hf_models = hf[hf["download_date"] == latest_hf_date].copy()
    else:
        hf_grouped = pd.DataFrame(columns=["download_date", "provider_display_name", "downloads_30d", "downloads_all_time", "downloads_daily_est", "likes"])
        latest_hf_date = None
        latest_hf = pd.DataFrame(columns=["download_date", "provider_display_name", "downloads_30d", "downloads_all_time", "downloads_daily_est", "likes"])
        latest_hf_models = pd.DataFrame(
            columns=["provider_display_name", "model_id", "hf_downloads_30d", "hf_downloads_all_time", "hf_downloads_daily_est", "hf_likes", "hf_last_modified"]
        )

    all_providers = set()
    if not latest_pypi.empty:
        all_providers.update(latest_pypi["provider_display_name"].dropna().unique())
    if not latest_npm_all.empty:
        all_providers.update(latest_npm_all["provider_display_name"].dropna().unique())
    if not latest_hf.empty:
        all_providers.update(latest_hf["provider_display_name"].dropna().unique())

    provider_order = sorted(list(all_providers))

    views["pypi_grouped"] = pypi_grouped
    views["latest_pypi_date"] = latest_pypi_date
    views["latest_pypi"] = latest_pypi
    views["npm_grouped"] = npm_grouped_all
    views["latest_npm_date"] = latest_npm_date
    views["latest_npm"] = latest_npm_all
    views["npm_categories"] = npm_categories
    views["hf_grouped"] = hf_grouped
    views["latest_hf_date"] = latest_hf_date
    views["latest_hf"] = latest_hf
    views["latest_hf_models"] = latest_hf_models
    views["provider_order"] = provider_order

    github_adoption_result = datasets.get("github_provider_adoption_daily")
    github_adoption = (
        github_adoption_result.frame.copy()
        if github_adoption_result and github_adoption_result.frame is not None
        else pd.DataFrame()
    )

    if not github_adoption.empty and provider_order:
        github_adoption = github_adoption[github_adoption["provider_display_name"].isin(provider_order)].copy()
        github_adoption["signal_date"] = github_adoption["signal_date"].astype(str)

    latest_github_date = github_adoption["signal_date"].max() if not github_adoption.empty else None

    views["github_adoption"] = github_adoption
    views["latest_github_date"] = latest_github_date

    if not github_adoption.empty:
        candidates_daily = (
            github_adoption.groupby(["signal_date"], dropna=False)["github_new_repo_count"]
            .max()
            .reset_index(name="repo_candidates")
            .rename(columns={"signal_date": "repo_created_date"})
        )
    else:
        candidates_daily = pd.DataFrame(columns=["repo_created_date", "repo_candidates"])
    latest_github_candidate_count = (
        int(candidates_daily[candidates_daily["repo_created_date"] == latest_github_date]["repo_candidates"].max())
        if latest_github_date and not candidates_daily.empty
        else 0
    )

    if not github_adoption.empty:
        rollup_daily = github_adoption[
            [
                "signal_date",
                "provider_display_name",
                "github_signal_repo_count",
                "github_manifest_repo_count",
                "github_import_repo_count",
                "github_env_repo_count",
                "github_model_repo_count",
            ]
        ].rename(
            columns={
                "github_signal_repo_count": "signal_repos",
                "github_manifest_repo_count": "manifest_repos",
                "github_import_repo_count": "import_repos",
                "github_env_repo_count": "env_repos",
                "github_model_repo_count": "model_repos",
            }
        )
    else:
        rollup_daily = pd.DataFrame(
            columns=["signal_date", "provider_display_name", "signal_repos", "manifest_repos", "import_repos", "env_repos", "model_repos"]
        )

    views["candidates_daily"] = candidates_daily
    views["rollup_daily"] = rollup_daily
    views["latest_github_candidate_count"] = latest_github_candidate_count
    return views


@st.cache_data(ttl=3600)
def compute_llm_benchmark_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    views: dict[str, object] = {}
    result = datasets.get("llm_benchmarks")
    if not result or result.frame.empty:
        return {"models_df": pd.DataFrame(), "sota_peaks": pd.DataFrame(), "innovation_velocity": 0, "frontier_avg": {}}

    df = result.frame.copy()
    df["release_date"] = pd.to_datetime(df["release_date"], errors="coerce")
    df = df.dropna(subset=["release_date"]).sort_values("release_date")
    
    # 1. Compute Running Max SOTA for GPQA
    df["gpqa_sota"] = df["gpqa"].cummax().fillna(0)
    sota_peaks = df[df["gpqa"] >= df["gpqa_sota"]].copy()
    
    # 2. Innovation Velocity (Days between SOTA breaks)
    sota_peaks["days_since_prev"] = sota_peaks["release_date"].diff().dt.days
    velocity = sota_peaks["days_since_prev"].tail(5).mean() if len(sota_peaks) >= 2 else 0

    # 3. Frontier Level (Top 5% metrics)
    threshold = df["gpqa"].quantile(0.95) if not df.empty else 0
    frontier_df = df[df["gpqa"] >= threshold].copy()
    
    frontier_avg = {
        "context_window": frontier_df["context_window"].mean() if not frontier_df.empty else 0,
        "gpqa": frontier_df["gpqa"].mean() if not frontier_df.empty else 0,
        "swe_bench": frontier_df["swe_bench"].mean() if not frontier_df.empty else 0,
        "max_gpqa": df["gpqa"].max(),
        "max_swe": df["swe_bench"].max(),
        "threshold": threshold,
    }

    views["models_df"] = df
    views["sota_peaks"] = sota_peaks
    views["innovation_velocity"] = velocity
    views["frontier_avg"] = frontier_avg
    return views


def _quarter_sort_value(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})-q([1-4])", str(value).lower())
    if not match:
        return (9999, 9)
    return (int(match.group(1)), int(match.group(2)))


def _frontier_pivot(
    frame: pd.DataFrame,
    *,
    group_column: str,
    max_groups: int | None = None,
) -> pd.DataFrame:
    required = {"release_date", "intelligence_index", group_column}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()
    work = frame.dropna(subset=["release_date", "intelligence_index", group_column]).copy()
    if work.empty:
        return pd.DataFrame()
    work["release_date"] = pd.to_datetime(work["release_date"], errors="coerce")
    work = work.dropna(subset=["release_date"])
    if work.empty:
        return pd.DataFrame()
    if max_groups is not None:
        top_groups = (
            work.groupby(group_column)["intelligence_index"]
            .max()
            .sort_values(ascending=False)
            .head(max_groups)
            .index
        )
        work = work[work[group_column].isin(top_groups)]
    pivot = (
        work.pivot_table(index="release_date", columns=group_column, values="intelligence_index", aggfunc="max")
        .sort_index()
        .cummax()
        .ffill()
    )
    return pivot


ARTIFICIAL_ANALYSIS_PROVIDER_COUNTRIES = {
    "ai2": "United States",
    "anthropic": "United States",
    "arcee": "United States",
    "aws": "United States",
    "azure": "United States",
    "databricks": "United States",
    "google": "United States",
    "ibm": "United States",
    "liquidai": "United States",
    "meta": "United States",
    "nvidia": "United States",
    "openai": "United States",
    "perplexity": "United States",
    "reka-ai": "United States",
    "servicenow": "United States",
    "snowflake": "United States",
    "xai": "United States",
    "alibaba": "China",
    "baidu": "China",
    "bytedance_seed": "China",
    "china-mobile": "China",
    "deepseek": "China",
    "inclusionai": "China",
    "kimi": "China",
    "kwaikat": "China",
    "longcat": "China",
    "minimax": "China",
    "nanbeige": "China",
    "stepfun": "China",
    "xiaomi": "China",
    "zai": "China",
}


def _artificial_analysis_country_label(row: pd.Series) -> str | None:
    raw_country = row.get("creator_country")
    if pd.notna(raw_country):
        normalized = str(raw_country).strip().lower()
        if normalized in {"us", "usa", "united states", "united states of america"}:
            return "United States"
        if normalized in {"cn", "china", "prc", "people's republic of china"}:
            return "China"

    raw_slug = row.get("creator_slug")
    if pd.isna(raw_slug):
        return None
    return ARTIFICIAL_ANALYSIS_PROVIDER_COUNTRIES.get(str(raw_slug).strip().lower())


def _china_catchup_lag(frontier_by_country: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "us_breakthrough_date",
        "us_intelligence_index",
        "china_catchup_date",
        "lag_months",
        "status",
    ]
    if frontier_by_country.empty or not {"United States", "China"}.issubset(frontier_by_country.columns):
        return pd.DataFrame(columns=columns)

    work = frontier_by_country[["United States", "China"]].copy().sort_index()
    work.index = pd.to_datetime(work.index, errors="coerce")
    work = work[work.index.notna()]
    if work.empty:
        return pd.DataFrame(columns=columns)

    latest_date = work.index.max()
    previous_us_frontier = float("-inf")
    rows: list[dict[str, object]] = []
    for breakthrough_date, values in work.iterrows():
        us_score = values.get("United States")
        if pd.isna(us_score) or float(us_score) <= previous_us_frontier:
            continue
        previous_us_frontier = float(us_score)
        future_china = work.loc[work.index > breakthrough_date]
        caught = future_china[future_china["China"] >= previous_us_frontier]
        if caught.empty:
            catchup_date = pd.NaT
            horizon_date = latest_date
            status = "not_yet_caught"
        else:
            catchup_date = caught.index[0]
            horizon_date = catchup_date
            status = "caught_up"
        lag_months = (horizon_date - breakthrough_date).days / 30.4375
        rows.append(
            {
                "us_breakthrough_date": breakthrough_date.date().isoformat(),
                "us_intelligence_index": previous_us_frontier,
                "china_catchup_date": None if pd.isna(catchup_date) else catchup_date.date().isoformat(),
                "lag_months": float(lag_months),
                "status": status,
            }
        )

    return pd.DataFrame(rows, columns=columns)


def _frontier_points_with_metadata(
    frame: pd.DataFrame,
    frontier_pivot: pd.DataFrame,
    *,
    group_column: str,
) -> pd.DataFrame:
    columns = ["release_date", "country_label", "intelligence_index", "model_name", "creator_name"]
    required = {"release_date", "intelligence_index", group_column, "model_name", "creator_name"}
    if frame.empty or frontier_pivot.empty or not required.issubset(frame.columns):
        return pd.DataFrame(columns=columns)

    source = frame.dropna(subset=["release_date", "intelligence_index", group_column]).copy()
    source["release_date"] = pd.to_datetime(source["release_date"], errors="coerce")
    source = source.dropna(subset=["release_date"])
    if source.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for group_name in frontier_pivot.columns:
        group_rows = source[source[group_column] == group_name].copy()
        if group_rows.empty:
            continue
        group_rows = group_rows.sort_values(["release_date", "intelligence_index"], ascending=[True, False])
        group_rows = group_rows.drop_duplicates(subset=["release_date"], keep="first")
        for release_date, intelligence_index in frontier_pivot[group_name].dropna().items():
            candidates = group_rows[
                (group_rows["release_date"] <= release_date)
                & (group_rows["intelligence_index"] == intelligence_index)
            ].sort_values("release_date")
            if candidates.empty:
                continue
            active = candidates.iloc[-1]
            rows.append(
                {
                    "release_date": pd.Timestamp(release_date),
                    "country_label": group_name,
                    "intelligence_index": float(intelligence_index),
                    "model_name": active.get("model_name"),
                    "creator_name": active.get("creator_name"),
                }
            )

    return pd.DataFrame(rows, columns=columns)


@st.cache_data(ttl=3600)
def compute_artificial_analysis_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    views: dict[str, object] = {}
    models_result = datasets.get("artificial_analysis_models_daily")
    capex_result = datasets.get("artificial_analysis_capex_quarterly")

    models = models_result.frame.copy() if models_result and not models_result.frame.empty else pd.DataFrame()
    capex = capex_result.frame.copy() if capex_result and not capex_result.frame.empty else pd.DataFrame()
    if not models.empty and "as_of_date" in models.columns:
        latest_as_of = models["as_of_date"].dropna().astype(str).max()
        models_latest = models[models["as_of_date"].astype(str) == latest_as_of].copy()
    else:
        latest_as_of = None
        models_latest = pd.DataFrame()

    if not capex.empty:
        capex = capex.sort_values("quarter_id", key=lambda series: series.map(_quarter_sort_value))
        company_cols = ["microsoft", "google", "meta", "amazon", "oracle", "apple"]
        capex_pivot = (
            capex[["quarter_label", *company_cols]]
            .set_index("quarter_label")
            .rename(
                columns={
                    "microsoft": "Microsoft",
                    "google": "Google",
                    "meta": "Meta",
                    "amazon": "Amazon",
                    "oracle": "Oracle",
                    "apple": "Apple",
                }
            )
        )
        latest_capex_total = float(capex_pivot.iloc[-1].sum()) if not capex_pivot.empty else np.nan
    else:
        capex_pivot = pd.DataFrame()
        latest_capex_total = np.nan

    frontier_by_lab = _frontier_pivot(models_latest, group_column="creator_name", max_groups=10)

    price_models = pd.DataFrame()
    if not models_latest.empty:
        price_models = models_latest.dropna(subset=["release_date", "price_1m_blended_3_to_1", "intelligence_index"]).copy()
        price_models["release_date"] = pd.to_datetime(price_models["release_date"], errors="coerce")
        price_models = price_models.dropna(subset=["release_date"]).sort_values("release_date")
        price_models = price_models[
            [
                "release_date",
                "model_name",
                "creator_name",
                "intelligence_index",
                "price_1m_blended_3_to_1",
                "median_output_tokens_per_second",
            ]
        ]

    country_models = models_latest.copy()
    if not country_models.empty:
        country_models["country_label"] = country_models.apply(_artificial_analysis_country_label, axis=1)
        country_models = country_models[country_models["country_label"].isin(["United States", "China"])]
    else:
        country_models["country_label"] = pd.Series(dtype="string")
    frontier_by_country = _frontier_pivot(country_models, group_column="country_label")
    frontier_by_country_points = _frontier_points_with_metadata(
        country_models,
        frontier_by_country,
        group_column="country_label",
    )
    china_catchup_lag = _china_catchup_lag(frontier_by_country)

    openness_models = models_latest.copy()
    if not openness_models.empty:
        openness_models["openness_label"] = openness_models.apply(_artificial_analysis_openness_label, axis=1)
        openness_models = openness_models.dropna(subset=["openness_label"])
    else:
        openness_models["openness_label"] = pd.Series(dtype="string")
    open_vs_proprietary = _frontier_pivot(openness_models, group_column="openness_label")

    views["models_latest"] = models_latest
    views["latest_as_of"] = latest_as_of
    views["capex_pivot"] = capex_pivot
    views["latest_capex_total"] = latest_capex_total
    views["frontier_by_lab_pivot"] = frontier_by_lab
    views["price_models"] = price_models
    views["frontier_by_country_pivot"] = frontier_by_country
    views["frontier_by_country_points"] = frontier_by_country_points
    views["china_catchup_lag"] = china_catchup_lag
    views["open_vs_proprietary_pivot"] = open_vs_proprietary
    return views


def _artificial_analysis_openness_label(row: pd.Series) -> str | None:
    raw_bool = row.get("is_open_weights")
    if isinstance(raw_bool, bool):
        return "Open Weights" if raw_bool else "Proprietary"
    if pd.notna(raw_bool):
        lowered = str(raw_bool).strip().lower()
        if lowered in {"true", "1", "yes"}:
            return "Open Weights"
        if lowered in {"false", "0", "no"}:
            return "Proprietary"
    category = row.get("open_source_categorization")
    if pd.isna(category):
        return None
    return "Open Weights" if "open" in str(category).lower() else "Proprietary"


@st.cache_data(ttl=3600)
def compute_semiconductor_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    views: dict[str, object] = {}

    regime_result = datasets.get("semiconductor_memory_regime_monthly")
    fred_result = datasets.get("fred_semiconductor_ppi")
    regime_df = regime_result.frame.copy() if regime_result and not regime_result.frame.empty else pd.DataFrame()
    fred_df = fred_result.frame.copy() if fred_result and not fred_result.frame.empty else pd.DataFrame()

    if not regime_df.empty:
        regime_df["month"] = regime_df["month"].astype(str)
        regime_df = regime_df.sort_values("month")

        latest_month = regime_df["month"].max()
        latest_data = regime_df[regime_df["month"] == latest_month].iloc[0]
        proxy_df = regime_df.dropna(subset=["fred_ppi_value"]).copy()
        component_columns = [
            column for column in AI_DEMAND_PPI_COMPONENT_COLUMNS.values()
            if column in regime_df.columns
        ]
        if component_columns:
            base_candidates = regime_df.dropna(subset=["fred_ppi_value", *component_columns]).copy()
        else:
            base_candidates = proxy_df
        base_month = base_candidates["month"].iloc[0] if not base_candidates.empty else None
        latest_proxy_month = proxy_df["month"].max() if not proxy_df.empty else None
        latest_proxy_data = (
            proxy_df[proxy_df["month"] == latest_proxy_month].iloc[0]
            if latest_proxy_month is not None and not proxy_df.empty
            else pd.Series(dtype="object")
        )
    else:
        latest_month = None
        latest_data = pd.Series(dtype="object")
        proxy_df = pd.DataFrame()
        component_columns = []
        base_month = None
        latest_proxy_month = None
        latest_proxy_data = pd.Series(dtype="object")

    latest_fred_month = None
    latest_fred_series_names: list[str] = []
    if not fred_df.empty:
        fred_df["date"] = pd.to_datetime(fred_df["date"], errors="coerce")
        fred_df = fred_df.dropna(subset=["date"]).copy()
        if not fred_df.empty:
            fred_df["month"] = fred_df["date"].dt.strftime("%Y-%m")
            latest_fred_month = fred_df["month"].max()
            latest_month_rows = fred_df[fred_df["month"] == latest_fred_month].copy()
            latest_fred_series_names = sorted(
                latest_month_rows["series_name"].fillna(latest_month_rows["series_id"]).astype(str).unique().tolist()
            )

    views["regime_df"] = regime_df
    views["latest_month"] = latest_month
    views["latest_data"] = latest_data
    views["proxy_df"] = proxy_df
    views["component_columns"] = component_columns
    views["base_month"] = base_month
    views["latest_proxy_month"] = latest_proxy_month
    views["latest_proxy_data"] = latest_proxy_data
    views["latest_fred_month"] = latest_fred_month
    views["latest_fred_series_names"] = latest_fred_series_names

    return views


@st.cache_data(ttl=3600)
def compute_compute_availability_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    # NOTE: Legacy function name. After removing AWS Spot + Lambda Cloud sources, this
    # now only surfaces OpenRouter catalog growth + latest-snapshot views used by the
    # Compute Evolution section on the OpenRouter tab.
    views: dict[str, object] = {}

    models_result = datasets.get("raw_openrouter_models")
    if models_result and not models_result.frame.empty:
        df = models_result.frame.copy()
        df["snapshot_ts"] = pd.to_datetime(df["snapshot_ts"], errors="coerce")
        df = df.dropna(subset=["snapshot_ts", "model_id"]).sort_values(["snapshot_ts", "model_id"]).reset_index(drop=True)

        if df.empty:
            views["models_latest"] = pd.DataFrame()
            views["models_growth"] = pd.DataFrame()
            views["models_history_start"] = None
            views["models_history_end"] = None
            return views

        snapshot_groups = list(df.groupby("snapshot_ts", sort=True))
        max_snapshot_size = max(group["model_id"].nunique() for _, group in snapshot_groups)
        full_snapshot_threshold = max_snapshot_size * 0.8

        current_catalog: dict[str, pd.Series] = {}
        growth_rows: list[dict[str, object]] = []

        for snapshot_ts, group in snapshot_groups:
            snapshot_rows = (
                group.drop_duplicates(subset=["model_id"], keep="last")
                .sort_values("model_id")
                .reset_index(drop=True)
            )

            if snapshot_rows["model_id"].nunique() >= full_snapshot_threshold:
                current_catalog = {
                    str(row["model_id"]): row.copy()
                    for _, row in snapshot_rows.iterrows()
                }
            else:
                for _, row in snapshot_rows.iterrows():
                    current_catalog[str(row["model_id"])] = row.copy()

            growth_rows.append({"snapshot_ts": snapshot_ts, "model_count": len(current_catalog)})

        latest_ts = snapshot_groups[-1][0]
        latest_models = pd.DataFrame(current_catalog.values()).sort_values("model_id").reset_index(drop=True)

        views["models_latest"] = latest_models
        views["models_growth"] = pd.DataFrame(growth_rows)
        views["models_history_start"] = snapshot_groups[0][0]
        views["models_history_end"] = latest_ts
    else:
        views["models_latest"] = pd.DataFrame()
        views["models_growth"] = pd.DataFrame()
        views["models_history_start"] = None
        views["models_history_end"] = None

    return views


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

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
        .rankings-note {{
            background: rgba(37, 99, 235, 0.06);
            border: 1px solid rgba(37, 99, 235, 0.14);
            border-radius: 10px;
            padding: 0.9rem 1rem;
            margin: 0.35rem 0 1.15rem 0;
            color: {TEXT};
            font-size: 0.92rem;
            line-height: 1.5;
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

        /* ---- Leaderboard Cards ---- */
        .lb-card {{
            display: flex;
            align-items: center;
            gap: 1rem;
            background: {CARD};
            border: 1px solid {BORDER};
            border-radius: 10px;
            padding: 0.8rem 1rem;
            margin-bottom: 0.6rem;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .lb-card:hover {{ transform: translateY(-1px); box-shadow: 0 4px 6px -1px rgba(0,0,0,0.08); }}
        .lb-rank {{
            width: 28px;
            height: 28px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: {SIDEBAR};
            color: {MUTED};
            border-radius: 50%;
            font-size: 0.85rem;
            font-weight: 800;
        }}
        .lb-rank-top {{ background: {ACCENT}; color: white; }}
        .lb-model {{ flex: 1; }}
        .lb-model-name {{ font-size: 0.92rem; font-weight: 700; color: {TEXT}; line-height: 1.2; }}
        .lb-model-author {{ font-size: 0.72rem; color: {MUTED}; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }}
        .lb-tokens {{ font-weight: 700; font-size: 0.95rem; color: {TEXT}; }}
        
        /* ---- Badges ---- */
        .lb-badge-up   {{ font-size: 0.7rem; font-weight: 800; color: {GREEN}; background: rgba(22, 163, 74, 0.1); padding: 2px 6px; border-radius: 4px; min-width: 32px; text-align: center; }}
        .lb-badge-down {{ font-size: 0.7rem; font-weight: 800; color: {RED};   background: rgba(220, 38, 38, 0.1); padding: 2px 6px; border-radius: 4px; min-width: 32px; text-align: center; }}
        .lb-badge-flat {{ font-size: 0.7rem; font-weight: 800; color: {MUTED}; background: rgba(107, 114, 128, 0.1); padding: 2px 6px; border-radius: 4px; min-width: 32px; text-align: center; }}
        .lb-badge-new  {{ font-size: 0.65rem; font-weight: 900; color: white;   background: {ACCENT}; padding: 2px 6px; border-radius: 4px; }}

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


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def render_header(freshness: FreshnessInfo) -> None:
    updated = freshness.latest_scraped_at or "Unknown"
    st.markdown(
        f"""
        <div style="margin-bottom:1.2rem;">
          <h1 style="font-size:1.9rem;font-weight:800;color:{TEXT};margin:0 0 0.2rem 0;">
            Alternative Data Dashboard
          </h1>
          <span style="color:{MUTED};font-size:0.88rem;">
            Last updated: {updated}
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_row(datasets: dict[str, DatasetLoadResult], openrouter_views: dict[str, object]) -> None:
    tm_result = datasets.get("top_models")
    ms_result = datasets.get("market_share")
    week_context = rankings_week_context(datasets)

    # --- top models KPIs ---
    total_latest = None
    wow_pct      = None
    top_model    = None

    if tm_result and not tm_result.frame.empty:
        tm = tm_result.frame.copy()
        tm["week_start_date"] = tm["week_start_date"].astype(str)
        sorted_weeks = sorted(tm["week_start_date"].unique())
        if sorted_weeks:
            latest_wk = sorted_weeks[-1]
            total_latest = tm[tm["week_start_date"] == latest_wk]["metric_value"].sum()
            tm_latest_named = (
                tm[
                    (tm["week_start_date"] == latest_wk) &
                    (tm["entity_id"].str.lower() != "others") &
                    (tm["entity_id"].str.contains("/", na=False))
                ]
                .groupby("entity_id", as_index=False)["metric_value"]
                .sum()
                .sort_values("metric_value", ascending=False)
            )
            top_model = tm_latest_named.iloc[0]["entity_id"] if not tm_latest_named.empty else None
            if len(sorted_weeks) >= 2:
                prev_wk    = sorted_weeks[-2]
                total_prev = tm[tm["week_start_date"] == prev_wk]["metric_value"].sum()
                if total_prev > 0:
                    wow_pct = (total_latest - total_prev) / total_prev * 100

    # --- market share leader ---
    leader_author = None
    leader_pct    = None

    if ms_result and not ms_result.frame.empty:
        ms = ms_result.frame.copy()
        ms["week_start_date"] = ms["week_start_date"].astype(str)
        latest_ms_wk = ms["week_start_date"].max()
        ms_latest    = ms[ms["week_start_date"] == latest_ms_wk].groupby("entity_id", as_index=False)["metric_value"].sum()
        ms_latest_named = ms_latest[ms_latest["entity_id"].str.lower() != "others"].copy()
        if not ms_latest_named.empty:
            ms_total = ms_latest["metric_value"].sum()
            ms_latest_named = ms_latest_named.sort_values("metric_value", ascending=False)
            leader_author = ms_latest_named.iloc[0]["entity_id"]
            if ms_total > 0:
                leader_pct = ms_latest_named.iloc[0]["metric_value"] / ms_total * 100

    # --- render ---
    if wow_pct is not None:
        tok_delta_cls  = "up" if wow_pct >= 0 else "down"
        tok_delta_text = f"{'↑' if wow_pct >= 0 else '↓'} {abs(wow_pct):.1f}% WoW"
    else:
        tok_delta_cls, tok_delta_text = "flat", "—"

    tokens_fmt   = format_metric(total_latest) if total_latest is not None else "—"
    leader_label = f"{leader_author} ({leader_pct:.1f}%)" if leader_author and leader_pct else leader_author or "—"
    model_label  = top_model or "—"
    if len(model_label) > 28:
        model_label = model_label[:26] + "…"
    wow_str = f"{'+'  if wow_pct and wow_pct >= 0 else ''}{f'{wow_pct:.1f}%' if wow_pct is not None else '—'}"

    st.markdown(
        kpi_grid_html(
            kpi_card_html("Total Tokens (Latest Model Week)", tokens_fmt, delta=tok_delta_text, delta_class=tok_delta_cls),
            kpi_card_html("WoW Change", wow_str, delta="vs prior week"),
            kpi_card_html("Top Model", model_label, delta="by tokens this week", value_style="font-size:1.1rem;"),
            kpi_card_html("Market Leader", leader_label, delta="latest market-share week", value_style="font-size:1.1rem;"),
        ),
        unsafe_allow_html=True,
    )

    warning = rankings_bucket_warning(week_context)
    if warning:
        st.markdown(f'<div class="rankings-warning">{warning}</div>', unsafe_allow_html=True)


def render_rankings_semantics_note(datasets: dict[str, DatasetLoadResult]) -> None:
    context = rankings_week_context(datasets)
    model_week = context["model_week"] or "n/a"
    market_share_week = context["market_share_week"] or "n/a"

    st.markdown(
        f"""
        <div class="rankings-note">
          <strong>OpenRouter week semantics</strong><br>
          Top Models are grouped by <strong>week starting</strong> dates.
          Market Share is grouped by <strong>week ending</strong> dates.
          These latest completed buckets can differ by up to 6 days on the same scrape.<br><br>
          <span style="color:{MUTED};">
            Latest completed model week: {model_week} ·
            Latest completed market-share week: {market_share_week}
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_top_models_chart(datasets: dict[str, DatasetLoadResult], openrouter_views: dict[str, object]) -> None:
    st.markdown('<div class="section-title">Total Weekly Tokens</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="section-subtitle">Completed weekly OpenRouter token-usage buckets. Uses Market Share totals when they remain directionally complete, and falls back to Top Models when the Market Share feed undercounts recent weeks.</div>',
        unsafe_allow_html=True,
    )
    top_view = openrouter_views.get("top_models", {})
    total_source = top_view.get("total_source", "top_models")
    pivot_total = top_view.get("pivot_total", pd.DataFrame())
    latest_week = pivot_total.index.max() if not pivot_total.empty else "n/a"
    latest_source = top_view.get("source_by_week", {}).get(latest_week, total_source)
    result = datasets.get("market_share") if latest_source == "market_share" else datasets.get("top_models")
    if latest_source == "hybrid":
        result = datasets.get("top_models")
    if not result or not render_dataset_guard(result):
        return
    st.markdown(
        f'<div class="status-caption">Total source: {total_source} · Latest plotted week: {latest_week} · Latest-week source: {latest_source} · Scraped: {format_scraped_at_display(result.latest_scraped_at)}</div>',
        unsafe_allow_html=True,
    )

    fig = make_line_chart(
        pivot_total,
        [ACCENT],
        y_title="Tokens",
        x_title="Usage Week (Starting)",
        hover_suffix="tokens",
    )
    st.plotly_chart(fig, width="stretch", theme=None)


def render_market_share_section(datasets: dict[str, DatasetLoadResult], openrouter_views: dict[str, object]) -> None:
    st.markdown('<div class="section-title">Market Share — Token Distribution by Author (Week Ending)</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="section-subtitle">Completed weekly buckets aligned to week end dates from OpenRouter rankings.</div>',
        unsafe_allow_html=True,
    )
    result = datasets.get("market_share")
    if not result or not render_dataset_guard(result):
        return

    ms = result.frame.copy()
    ms["week_start_date"] = ms["week_start_date"].astype(str)
    st.markdown(
        f'<div class="status-caption">Latest completed market-share week: {result.latest_date or "n/a"} · Scraped: {format_scraped_at_display(result.latest_scraped_at)}</div>',
        unsafe_allow_html=True,
    )

    # --- Period Selector ---
    ms_weeks = openrouter_views["market_share"]["weeks"]
    sel_ms_wk = st.selectbox("Analyze week ending", options=ms_weeks, index=0, key="ms_week_sel")
    ms_wk_total = ms[ms["week_start_date"] == sel_ms_wk]["metric_value"].sum()
    st.markdown(
        kpi_card_html(f"Total Tokens ({sel_ms_wk})", format_metric(ms_wk_total),
                      card_style="margin-bottom:1rem; max-width:300px", value_style="font-size:1.5rem"),
        unsafe_allow_html=True,
    )

    chart_col, legend_col = st.columns([2, 1], gap="large")

    with chart_col:
        fig = make_stacked_bar(openrouter_views["market_share"]["pivot_pct_top"], MODEL_COLORS, y_title="Share (%)", pct=True)
        fig.update_yaxes(range=[0, 100])
        st.plotly_chart(fig, width="stretch", theme=None)

    with legend_col:
        ms_named = market_share_legend_rows(ms, sel_ms_wk, limit=8)

        st.markdown(f'<div style="font-weight:700;font-size:1rem;margin-bottom:0.8rem;">Week: {sel_ms_wk} Leaders</div>', unsafe_allow_html=True)
        rows_html = '<div class="ms-legend">'
        for rank_i, (_, row) in enumerate(ms_named.head(8).iterrows()):
            color  = MODEL_COLORS[rank_i % len(MODEL_COLORS)]
            author = row["entity_id"]
            pct_v  = row["share_pct"]
            week_v = format_metric(row["metric_value"])
            rows_html += f"""
            <div class="ms-row">
              <span style="color:{MUTED};font-size:0.72rem;min-width:16px;">{rank_i+1}</span>
              <span class="ms-dot" style="background:{color};"></span>
              <span class="ms-name">{author}</span>
              <span class="ms-tokens">{week_v}</span>
              <span class="ms-pct">{pct_v:.1f}%</span>
            </div>"""
        rows_html += "</div>"
        st.markdown(rows_html, unsafe_allow_html=True)

    st.markdown("---")


def render_revenue_estimator(datasets: dict[str, DatasetLoadResult], openrouter_views: dict[str, object]) -> None:
    rev_data = openrouter_views.get("revenue_estimator", {})
    pivot_rev = rev_data.get("pivot_rev", pd.DataFrame())
    total_revenue = rev_data.get("total_revenue", 0)
    coverage = rev_data.get("coverage", {})

    st.markdown('<div class="section-title">Provider Revenue Estimator</div>', unsafe_allow_html=True)
    
    if pivot_rev.empty:
        st.info("No priced provider activity is available for conservative revenue estimation yet.")
        return

    st.markdown(
        kpi_grid_html(
            kpi_card_html("Observed Priced Revenue", f"${total_revenue:,.0f}", delta="matched model pricing only"),
            kpi_card_html("Provider Coverage", str(len(pivot_rev.columns)), delta="active priced providers"),
            kpi_card_html("Priced Token Coverage", f"{coverage.get('priced_token_coverage', 0):.1%}", delta="of observed provider tokens"),
            kpi_card_html("Split Token Coverage", f"{coverage.get('split_token_coverage', 0):.1%}", delta="prompt/completion known or inferred"),
        ),
        unsafe_allow_html=True,
    )

    st.markdown('<div class="section-subtitle">Estimated Revenue by Provider (USD)</div>', unsafe_allow_html=True)

    pivot_monthly = regroup_provider_pivot_for_display(rev_data.get("pivot_rev_monthly", pd.DataFrame()), "monthly")
    pivot_weekly  = regroup_provider_pivot_for_display(rev_data.get("pivot_rev_weekly", pd.DataFrame()), "weekly")
    pivot_daily   = regroup_provider_pivot_for_display(rev_data.get("pivot_rev_daily", pd.DataFrame()), "daily")

    tab_week, tab_month, tab_day = st.tabs(["Weekly", "Monthly", "Daily"])
    
    def _render_rev_chart(pivot_df, date_title):
        if pivot_df.empty:
            st.info(f"No {date_title.lower()} data available.")
            return
        # Label the current month as MTD in the X-axis for clarity
        today_month = datetime.now().strftime("%Y-%m")
        display_index = [
            f"{d} (MTD)" if date_title == "Usage Month" and str(d) == today_month else d
            for d in pivot_df.index
        ]
        st.plotly_chart(
            make_stacked_area_chart(
                pivot_df,
                display_index,
                MODEL_COLORS,
                x_title=date_title,
                y_title="Revenue (USD)",
                hover_prefix="$",
            ),
            width="stretch", theme=None,
        )

    with tab_week:
        if pivot_weekly.empty:
            st.info("No weekly data available.")
        else:
            today_month = datetime.now().strftime("%Y-%m")
            display_index = [str(d) for d in pivot_weekly.index]
            fig_week = make_stacked_area_chart(
                pivot_weekly,
                display_index,
                MODEL_COLORS,
                x_title="Usage Week (Starting)",
                y_title="Revenue (USD)",
                hover_prefix="$",
            )
            st.plotly_chart(fig_week, width="stretch", theme=None)
            st.caption(
                "Weekly revenue combines legacy Market Share plus Top Models fallback estimates before mid-January 2026, "
                "then switches to observed provider activity with pricing fallbacks."
            )
    with tab_month:
        _render_rev_chart(pivot_monthly, "Usage Month")
    with tab_day:
        _render_rev_chart(pivot_daily, "Usage Date")
        
    st.caption(
        "Methodology: dashboard revenue uses a hybrid estimate. Legacy weekly history starts from Market Share provider totals, "
        "prices the ranked model subset, and tops up uncovered provider volume with provider/global blended pricing benchmarks. "
        "Modern daily history uses observed provider/model activity with OpenRouter pricing plus provider/global fallbacks when exact as-of matches are unavailable. "
        "Models whose OpenRouter slug ends in :free are included in token volume and zero-rated for revenue."
    )
    st.markdown("---")


def render_leaderboard(datasets: dict[str, DatasetLoadResult]) -> None:
    st.markdown('<div class="section-title">Model Leaderboard — Weekly</div>', unsafe_allow_html=True)
    result = datasets.get("top_models")
    if not result or not render_dataset_guard(result):
        return

    tm = result.frame.copy()
    tm["week_start_date"] = tm["week_start_date"].astype(str)
    sorted_weeks = sorted(tm["week_start_date"].unique())
    if len(sorted_weeks) < 1:
        st.info("Not enough weekly data for leaderboard.")
        return

    latest_wk = sorted_weeks[-1]
    prev_wk   = sorted_weeks[-2] if len(sorted_weeks) >= 2 else None
    st.caption(f"Showing week starting {latest_wk} vs previous week")

    def _agg_named(frame: pd.DataFrame) -> pd.DataFrame:
        """Aggregate by entity_id, excluding catch-all 'Others' buckets."""
        named = frame[
            (frame["entity_id"].str.lower() != "others") &
            (frame["entity_id"].str.contains("/", na=False))
        ]
        return (
            named.groupby("entity_id", as_index=False)["metric_value"]
            .sum()
            .sort_values("metric_value", ascending=False)
            .reset_index(drop=True)
        )

    latest_agg = _agg_named(tm[tm["week_start_date"] == latest_wk])
    latest_agg["curr_rank"] = range(1, len(latest_agg) + 1)

    if prev_wk:
        prev_agg = _agg_named(tm[tm["week_start_date"] == prev_wk])
        prev_agg["prev_rank"] = range(1, len(prev_agg) + 1)
        rank_map = dict(zip(prev_agg["entity_id"], prev_agg["prev_rank"]))
    else:
        rank_map = {}

    # extract author from entity_id (format: "author/model-name")
    def split_entity(eid: str):
        parts = eid.split("/", 1)
        return (parts[0], parts[1]) if len(parts) == 2 else ("", eid)

    top10 = latest_agg.head(10)
    cards = []
    for _, row in top10.iterrows():
        eid    = row["entity_id"]
        author, model_name = split_entity(eid)
        tokens = format_metric(row["metric_value"])
        rank   = row["curr_rank"]
        prev_r = rank_map.get(eid)

        if prev_r is None:
            badge = '<span class="lb-badge-new">NEW</span>'
        else:
            delta = prev_r - rank  # positive → moved up
            if delta > 0:
                badge = f'<span class="lb-badge-up">↑{delta}</span>'
            elif delta < 0:
                badge = f'<span class="lb-badge-down">↓{abs(delta)}</span>'
            else:
                badge = '<span class="lb-badge-flat">—</span>'

        rank_cls   = "lb-rank lb-rank-top" if rank <= 3 else "lb-rank"
        model_disp = model_name[:32] + "…" if len(model_name) > 32 else model_name

        cards.append(
            f"""<div class="lb-card">
              <div class="{rank_cls}">{rank}</div>
              <div class="lb-model">
                <div class="lb-model-name">{model_disp}</div>
                <div class="lb-model-author">{author}</div>
              </div>
              <div class="lb-tokens">{tokens}</div>
              {badge}
            </div>"""
        )

    col_a, col_b = st.columns(2, gap="large")
    with col_a:
        st.markdown("".join(cards[:5]), unsafe_allow_html=True)
    with col_b:
        st.markdown("".join(cards[5:]), unsafe_allow_html=True)


def render_token_volume_chart(openrouter_views: dict[str, object]) -> None:
    """Stacked area chart: raw token consumption by provider over time (daily/weekly/monthly)."""
    st.markdown('<div class="section-title">Token Volume by Provider</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Token volume by provider across OpenRouter. '
        'Legacy (pre-Jan 2026): provider-level history from weekly Market Share rankings. '
        'Modern (2026+): observed daily logs for tracked priority providers, with the first partial modern week bridged from the following week for continuity.</div>',
        unsafe_allow_html=True,
    )

    tok_data = openrouter_views.get("token_volume", {})
    pivot_daily = regroup_provider_pivot_for_display(tok_data.get("pivot_daily", pd.DataFrame()), "daily")
    pivot_weekly = regroup_provider_pivot_for_display(tok_data.get("pivot_weekly", pd.DataFrame()), "weekly")
    pivot_monthly = regroup_provider_pivot_for_display(tok_data.get("pivot_monthly", pd.DataFrame()), "monthly")

    if pivot_weekly.empty and pivot_daily.empty:
        st.info("No token volume data available.")
        return

    # --- KPI Row ---
    latest_tok_total, tok_wow_pct, dominant_provider = None, None, None
    if not pivot_weekly.empty:
        latest_row = pivot_weekly.iloc[-1]
        latest_tok_total = float(latest_row.sum())
        if len(pivot_weekly) >= 2:
            prev_total = float(pivot_weekly.iloc[-2].sum())
            if prev_total > 0:
                tok_wow_pct = (latest_tok_total - prev_total) / prev_total * 100
        if latest_tok_total > 0:
            dominant_provider = latest_row.idxmax()

    if tok_wow_pct is not None:
        tok_delta_cls  = "up" if tok_wow_pct >= 0 else "down"
        tok_delta_text = f"{'↑' if tok_wow_pct >= 0 else '↓'} {abs(tok_wow_pct):.1f}% WoW"
    else:
        tok_delta_cls, tok_delta_text = "flat", "—"

    coverage = "Legacy + observed modern" if not pivot_weekly.empty and pivot_weekly.index[0] < "2026" else "Observed modern"
    wow_str = f"{'+'  if tok_wow_pct and tok_wow_pct >= 0 else ''}{f'{tok_wow_pct:.1f}%' if tok_wow_pct is not None else '—'}"

    st.markdown(
        kpi_grid_html(
            kpi_card_html("Total Tokens (Latest Week)", format_metric(latest_tok_total) if latest_tok_total else "—", delta=tok_delta_text, delta_class=tok_delta_cls),
            kpi_card_html("WoW Change", wow_str, delta="vs prior week"),
            kpi_card_html("Dominant Provider", dominant_provider or "—", delta="by token share this week"),
            kpi_card_html("Data Coverage", coverage, delta="legacy + smoothed modern seam"),
        ),
        unsafe_allow_html=True,
    )

    tab_week, tab_month, tab_day = st.tabs(["Weekly", "Monthly", "Daily"])

    def _render_tok_chart(pivot_df: pd.DataFrame, date_title: str) -> None:
        if pivot_df.empty:
            st.info(f"No {date_title.lower()} token data available.")
            return
        today_month = datetime.now().strftime("%Y-%m")
        display_index = [
            f"{d} (MTD)" if date_title == "Usage Month" and str(d) == today_month else d
            for d in pivot_df.index
        ]
        st.plotly_chart(
            make_stacked_area_chart(
                pivot_df,
                display_index,
                MODEL_COLORS,
                x_title=date_title,
                y_title="Tokens",
                value_format=",.0f",
                hover_suffix="tokens",
            ),
            width="stretch", theme=None,
        )

    with tab_week:
        _render_tok_chart(pivot_weekly, "Usage Week (Starting)")
    with tab_month:
        _render_tok_chart(pivot_monthly, "Usage Month")
    with tab_day:
        _render_tok_chart(pivot_daily, "Usage Date")

    st.caption(
        "Legacy (pre-Jan 2026): weekly/monthly token views come from provider-level Market Share history, "
        "so they reflect providers visible in OpenRouter's author-share chart rather than only the surviving top-model cutoff. "
        "Modern (post-Jan 2026): daily token views come from exact per-provider logs, but only for the configured priority providers, "
        "not the full OpenRouter provider universe, so some providers may still be missing from the chart. Partial periods are observed totals."
    )


def render_token_revenue_comparison(openrouter_views: dict[str, object]) -> None:
    """Sanity-check table: implied avg price = Revenue / Tokens, by provider and period."""
    with st.expander("📊 Revenue ÷ Token Accuracy Check (implied $/token)", expanded=False):
        st.markdown(
            "Divides estimated revenue by token volume for each provider to derive an **implied average price per token**. "
            "Compare against known model pricing to spot estimation errors, while remembering that revenue includes only conservatively priced observed rows.",
            unsafe_allow_html=True,
        )
        rev_data = openrouter_views.get("revenue_estimator", {})
        tok_data = openrouter_views.get("token_volume", {})

        rev_weekly, tok_weekly = grouped_revenue_token_pivots(rev_data, tok_data, "weekly")
        rev_monthly, tok_monthly = grouped_revenue_token_pivots(rev_data, tok_data, "monthly")

        tab_w, tab_m = st.tabs(["Weekly", "Monthly"])

        def _comparison_table(rev_piv: pd.DataFrame, tok_piv: pd.DataFrame, period_label: str) -> None:
            if rev_piv.empty or tok_piv.empty:
                st.info(f"Not enough data for {period_label} comparison.")
                return
            # Align columns and index
            common_cols = [col for col in rev_piv.columns if col in set(tok_piv.columns)]
            common_idx  = sorted(set(rev_piv.index)   & set(tok_piv.index))
            if not common_cols or not common_idx:
                st.info("No overlapping providers/periods between revenue and token data.")
                return
            rev_a = rev_piv.loc[common_idx, common_cols]
            tok_a = tok_piv.loc[common_idx, common_cols]
            # Implied price per token ($/token); multiply by 1e6 → $/M tokens for readability
            implied = (rev_a / tok_a.replace(0, float('nan'))).fillna(0) * 1e6
            # Show latest 12 periods
            display = implied.tail(12).round(4)
            # Colour: values outside [0.001, 10] $/M tokens are suspicious
            st.dataframe(
                display.style.background_gradient(axis=None, cmap="RdYlGn_r", vmin=0, vmax=5),
                width="stretch",
            )
            st.caption(
                f"Values in **$/M tokens** (implied avg price). "
                f"Typical range: $0.10–$5/M for mainstream models. "
                f"Very high values suggest token undercount; very low values suggest revenue undercount."
            )

        with tab_w:
            _comparison_table(rev_weekly, tok_weekly, "weekly")
        with tab_m:
            _comparison_table(rev_monthly, tok_monthly, "monthly")


def render_apps_tables(datasets: dict[str, DatasetLoadResult]) -> None:
    st.markdown('<div class="section-title">App Rankings & Trends</div>', unsafe_allow_html=True)

    tabs = st.tabs(["Global Rankings", "Trending Apps", "Monitored Apps"])

    with tabs[0]:
        result = datasets.get("apps_global_ranking_snapshots")
        if result and render_dataset_guard(result):
            frame = result.frame.copy()
            periods = sorted(frame["period"].dropna().astype(str).unique().tolist())
            _week_idx = next((i for i, p in enumerate(periods) if "week" in p.lower()), 0)
            period  = st.selectbox("Period", options=periods, index=_week_idx if periods else None, key="lb_period")
            if period:
                frame = frame[frame["period"] == period]
            latest_date = frame["snapshot_date"].max()
            latest = frame[frame["snapshot_date"] == latest_date].sort_values("rank").head(25)
            tbl = latest[["rank", "app_name", "categories", "tokens"]].copy()
            total_top25 = tbl["tokens"].sum()
            
            summary_col, _ = st.columns([1, 2])
            with summary_col:
                st.markdown(
                    kpi_card_html(f"Tokens in Top 25 ({latest_date})", format_metric(total_top25),
                                  card_style="margin-bottom:1rem", value_style="font-size:1.5rem"),
                    unsafe_allow_html=True,
                )
                
            tbl["tokens"] = tbl["tokens"].map(format_metric)
            st.dataframe(dataframe_for_display(tbl, ""), width="stretch", hide_index=True)

    with tabs[1]:
        result = datasets.get("apps_trending_snapshots")
        if result and render_dataset_guard(result):
            frame = result.frame.copy()
            latest_date = frame["snapshot_date"].max()
            latest = frame[frame["snapshot_date"] == latest_date].sort_values("rank").head(25)
            st.caption(f"Snapshot: {latest_date}")
            tbl = latest[["rank", "app_name", "categories", "tokens", "growth_percent"]].copy()
            tbl["tokens"] = tbl["tokens"].map(lambda v: "-" if pd.isna(v) else format_metric(v))
            tbl["growth_percent"] = tbl["growth_percent"].map(
                lambda v: "-" if pd.isna(v) else f"{v:,.0f}%"
            )
            st.dataframe(dataframe_for_display(tbl, ""), width="stretch", hide_index=True)

    with tabs[2]:
        meta_result  = datasets.get("app_metadata_snapshots")
        usage_result = datasets.get("app_usage_daily")
        if meta_result and render_dataset_guard(meta_result):
            latest_date   = meta_result.latest_date
            latest_meta   = meta_result.frame.copy()
            if latest_date:
                latest_meta = latest_meta[latest_meta["scrape_date"] == latest_date]
            st.caption(f"Metadata snapshot: {latest_date or 'n/a'}")
            st.dataframe(
                dataframe_for_display(
                    latest_meta[["app_name", "app_id", "origin_url", "categories", "description"]],
                    "",
                ),
                width="stretch",
                hide_index=True,
            )

        if usage_result and render_dataset_guard(usage_result, show_subheader=False):
            usage = usage_result.frame.copy()
            app_names = sorted(usage["app_name"].dropna().astype(str).unique().tolist())
            selected  = st.multiselect("Apps", options=app_names, default=app_names[:3], key="mon_apps")
            if selected:
                usage = usage[usage["app_name"].isin(selected)]
            if not usage.empty:
                app_total = usage["total_tokens"].sum()
                st.markdown(
                    kpi_card_html("Cumulative Selection Usage", format_metric(app_total),
                                  card_style="margin-bottom:1rem; max-width:300px", value_style="font-size:1.5rem"),
                    unsafe_allow_html=True,
                )
                
                pivot_u = (
                    usage.pivot_table(index="usage_date", columns="model_permaslug", values="total_tokens", aggfunc="sum")
                    .fillna(0)
                    .sort_index()
                )
                top_m = pivot_u.sum().nlargest(15).index.tolist()
                pivot_u = pivot_u[top_m]
                fig_u = make_stacked_bar(pivot_u, MODEL_COLORS, y_title="Tokens", height=300)
                st.plotly_chart(fig_u, width="stretch", theme=None)


def render_github_trending_section(datasets: dict[str, DatasetLoadResult], github_views: dict[str, dict[str, object]]) -> None:
    st.markdown('<div class="section-title">GitHub Trending Repositories</div>', unsafe_allow_html=True)
    
    # 1. Period Selector
    period_label = st.radio("Trending period", options=["Daily", "Weekly", "Monthly"], horizontal=True, label_visibility="collapsed")
    dataset_id = f"github_trending_{period_label.lower()}"
    
    result = datasets.get(dataset_id)
    if not result or not render_dataset_guard(result):
        return

    df = result.frame.copy()
    if df.empty:
        st.info(f"No data available for {period_label.lower()}.")
        return

    period_view = github_views[dataset_id]
    latest_date = period_view["latest_date"]
    latest_df = period_view["latest_df"]

    # --- KPIs ---
    top_repo = latest_df.iloc[0] if not latest_df.empty else None
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            kpi_card_html(f"Top Gainer ({period_label})",
                          top_repo["name"] if top_repo is not None else "—",
                          delta=f"+{format_metric(top_repo['stars_today']) if top_repo is not None else '0'} stars",
                          delta_class="up", value_style="font-size:1.3rem"),
            unsafe_allow_html=True,
        )
    with col2:
        total_gained = latest_df["stars_today"].sum()
        st.markdown(
            kpi_card_html("Total Stars Gained (Top 15)", format_metric(total_gained),
                          delta="across trending list"),
            unsafe_allow_html=True,
        )
    with col3:
        unique_repos = df["name"].nunique()
        st.markdown(
            kpi_card_html("Unique Repos Tracked", str(unique_repos), delta="in history"),
            unsafe_allow_html=True,
        )

    # --- Charts & Leaderboard ---
    chart_tab, list_tab = st.tabs(["Historical Growth", "Latest Leaderboard"])

    with chart_tab:
        pivot_h = period_view["history_top5"]
        if not pivot_h.empty:
            st.plotly_chart(
                make_line_chart(pivot_h, MODEL_COLORS,
                                title=f"Star Growth - Top 5 {period_label} Repos",
                                x_title="Scrape Date", y_title="Stars Gained",
                                hover_suffix="stars gained", height=400),
                width="stretch",
            )
        else:
            st.info("Not enough historical data to show growth.")

    with list_tab:
        st.markdown(f'<div style="font-weight:700;font-size:1.1rem;margin-bottom:1rem;">Top Gaining Repositories ({latest_date})</div>', unsafe_allow_html=True)
        
        cols = st.columns(2)
        for i, (_, row) in enumerate(latest_df.head(10).iterrows()):
            col_idx = i % 2
            with cols[col_idx]:
                description = str(row.get('description', ''))
                if description in ['nan', 'None', 'NULL']:
                    description = ""
                
                desc_display = (description[:100] + '...') if len(description) > 100 else description
                
                st.markdown(
                    f"""<div class="lb-card">
                      <div class="lb-rank {'lb-rank-top' if i < 3 else ''}">{i+1}</div>
                      <div class="lb-model">
                        <div class="lb-model-name"><a href="{row['link']}" target="_blank">{row['name']}</a></div>
                        <div class="lb-model-author">{row['author']}</div>
                        <div style="font-size:0.75rem; color:{MUTED}; margin-top:2px;">{desc_display}</div>
                      </div>
                      <div class="lb-tokens" style="color:{GREEN};">+{format_metric(row['stars_today'])}</div>
                      <div style="font-size:0.7rem; color:{MUTED}; min-width:50px; text-align:right;">Total: {format_metric(row['total_stars'])}</div>
                    </div>""",
                    unsafe_allow_html=True
                )


def render_provider_adoption_section(datasets: dict[str, DatasetLoadResult], provider_views: dict[str, object]) -> None:
    st.markdown('<div class="section-title">Provider Adoption</div>', unsafe_allow_html=True)
    st.caption("Scraped GitHub, PyPI, npm, and Hugging Face activity by provider")

    pypi_result = datasets.get("pypi_downloads_daily")
    npm_result = datasets.get("npm_downloads_daily")
    hf_result = datasets.get("huggingface_models_daily")

    if not pypi_result or not render_dataset_guard(pypi_result):
        st.info("Run the provider-adoption pipeline to populate GitHub, PyPI, npm, and Hugging Face scraped data.")
        return

    pypi = pypi_result.frame.copy()
    pypi = pypi[pypi["with_mirrors"] == False].copy()
    if pypi.empty:
        st.info("No PyPI provider data available yet.")
        return

    pypi_grouped = provider_views["pypi_grouped"]
    latest_pypi_date = provider_views["latest_pypi_date"]
    latest_pypi = provider_views["latest_pypi"]
    npm_grouped_all = provider_views["npm_grouped"]
    latest_npm_date = provider_views["latest_npm_date"]
    latest_npm_all = provider_views["latest_npm"]
    npm_categories = provider_views["npm_categories"]
    provider_order = provider_views["provider_order"]
    if not provider_order:
        st.info("No provider rows available yet.")
        return

    github_adoption = provider_views["github_adoption"]
    latest_github_date = provider_views["latest_github_date"]
    latest_hf_date = provider_views["latest_hf_date"]
    latest_hf = provider_views["latest_hf"]
    hf_grouped = provider_views["hf_grouped"]
    latest_hf_models = provider_views["latest_hf_models"]

    top_download_row = latest_pypi.sort_values("downloads", ascending=False).iloc[0] if not latest_pypi.empty else None
    total_latest_downloads = latest_pypi["downloads"].sum() if not latest_pypi.empty else 0
    latest_candidate_count = provider_views["latest_github_candidate_count"]
    top_hf_row = latest_hf.sort_values("downloads_30d", ascending=False).iloc[0] if not latest_hf.empty else None

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Top PyPI Provider</div>'
            f'<div class="kpi-value" style="font-size: 1.1rem;">{top_download_row["provider_display_name"] if top_download_row is not None else "—"}</div>'
            f'<div class="kpi-delta-flat">latest daily downloads</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Latest PyPI Downloads</div>'
            f'<div class="kpi-value" style="font-size: 1.5rem;">{format_metric(total_latest_downloads)}</div>'
            f'<div class="kpi-delta-flat">{latest_pypi_date or "n/a"}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Top Hugging Face</div>'
            f'<div class="kpi-value" style="font-size: 1.1rem;">{top_hf_row["provider_display_name"] if top_hf_row is not None else "—"}</div>'
            f'<div class="kpi-delta-flat">by 30d downloads</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Latest GH Candidate Pool</div>'
            f'<div class="kpi-value" style="font-size: 1.5rem;">{format_metric(latest_candidate_count)}</div>'
            f'<div class="kpi-delta-flat">{latest_github_date or "n/a"}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    selected_npm_category = "core_sdk"
    if npm_categories:
        selected_npm_category = st.selectbox(
            "npm package category",
            options=npm_categories,
            index=npm_categories.index("core_sdk") if "core_sdk" in npm_categories else 0,
            format_func=lambda value: NPM_CATEGORY_LABELS.get(value, value.replace("_", " ").title()),
            key="provider_adoption_npm_category",
        )

    npm_grouped = (
        npm_grouped_all[npm_grouped_all["package_category"] == selected_npm_category].copy()
        if not npm_grouped_all.empty
        else pd.DataFrame(columns=["package_category", "download_date", "provider_display_name", "downloads"])
    )
    latest_npm = (
        latest_npm_all[latest_npm_all["package_category"] == selected_npm_category].copy()
        if not latest_npm_all.empty
        else pd.DataFrame(columns=["package_category", "download_date", "provider_display_name", "downloads"])
    )

    # HF/PyPI/npm each combine downloads + share into a single tab
    hf_tab, hf_models_tab, pypi_tab, npm_tab, github_tab, summary_tab = st.tabs(
        ["HF", "HF Models", "PyPI", "npm", "GitHub Signals", "Latest Summary"]
    )

    hf_metric = st.segmented_control(
        "Hugging Face metric",
        options=["Trailing 30d", "Daily (Est)", "All-time"],
        default="Trailing 30d",
        key="provider_adoption_hf_metric",
    )
    hf_metric_config = resolve_hf_metric_config(hf_metric)

    with hf_tab:
        if hf_result is None or hf_result.frame.empty or hf_grouped.empty:
            st.info("No Hugging Face model data available yet.")
        else:
            # Downloads trend
            pivot_hf = (
                hf_grouped.pivot_table(
                    index="download_date",
                    columns="provider_display_name",
                    values=hf_metric_config["value_column"],
                    aggfunc="last",
                )
                .fillna(0)
                .sort_index()
            )
            st.plotly_chart(
                make_line_chart(
                    pivot_hf, MODEL_COLORS,
                    title=hf_metric_config["downloads_title"],
                    y_title=hf_metric_config["downloads_axis"],
                    hover_suffix=hf_metric_config["downloads_hover"],
                ),
                width="stretch", theme=None,
            )
            # Market share (stacked bar)
            value_column = hf_metric_config["value_column"]
            totals = hf_grouped.groupby("download_date")[value_column].sum().rename("total").reset_index()
            share = hf_grouped.merge(totals, on="download_date", how="left")
            share["share"] = share[value_column] / share["total"].where(share["total"] != 0)
            pivot_share = (
                share.pivot_table(index="download_date", columns="provider_display_name", values="share", aggfunc="last")
                .fillna(0)
                .sort_index()
            )
            st.plotly_chart(
                make_stacked_bar(pivot_share * 100, MODEL_COLORS,
                                 title=hf_metric_config["share_title"], y_title="Share", pct=True, height=340),
                width="stretch", theme=None,
            )

    with hf_models_tab:
        if hf_result is None or hf_result.frame.empty or latest_hf_models.empty:
            st.info("No Hugging Face model snapshot available yet.")
        else:
            available_providers = sorted(
                provider for provider in latest_hf_models["provider_display_name"].dropna().astype(str).unique().tolist() if provider
            )
            selected_hf_provider = st.selectbox(
                "Hugging Face provider",
                options=["All"] + available_providers,
                index=0,
                key="provider_adoption_hf_provider",
            )
            st.caption(f"Latest HF snapshot: {latest_hf_date or 'n/a'}")
            if selected_hf_provider == "All":
                st.info("Choose a provider to view its top 20 Hugging Face models.")
            else:
                table = prepare_hf_models_table(
                    latest_hf_models,
                    provider_display_name=selected_hf_provider,
                    metric_label=hf_metric,
                    limit=20,
                )
                st.caption(
                    f"Showing top 20 models for {selected_hf_provider} by {hf_metric_config['models_caption_metric']}."
                )
                st.dataframe(dataframe_for_display(table, "-"), width="stretch", hide_index=True)

    with pypi_tab:
        # Downloads trend
        pivot_downloads = (
            pypi_grouped.pivot_table(index="download_date", columns="provider_display_name", values="downloads", aggfunc="last")
            .fillna(0)
            .sort_index()
        )
        st.plotly_chart(
            make_line_chart(pivot_downloads, MODEL_COLORS,
                            title="PyPI Daily Download History (Without Mirrors)",
                            y_title="Downloads", hover_suffix="downloads"),
            width="stretch", theme=None,
        )
        # Market share
        totals = pypi_grouped.groupby("download_date")["downloads"].sum().rename("total").reset_index()
        share = pypi_grouped.merge(totals, on="download_date", how="left")
        share["share"] = share["downloads"] / share["total"].where(share["total"] != 0)
        pivot_share = (
            share.pivot_table(index="download_date", columns="provider_display_name", values="share", aggfunc="last")
            .fillna(0)
            .sort_index()
        )
        st.plotly_chart(
            make_stacked_bar(pivot_share * 100, MODEL_COLORS,
                             title="PyPI Daily Download Share (Without Mirrors)",
                             y_title="Share", pct=True, height=340),
            width="stretch", theme=None,
        )

    with npm_tab:
        if npm_result is None or npm_result.frame.empty or npm_grouped.empty:
            st.info("No npm provider data available yet.")
        else:
            _npm_label = NPM_CATEGORY_LABELS.get(selected_npm_category, selected_npm_category)
            # Downloads trend
            pivot_downloads = (
                npm_grouped.pivot_table(index="download_date", columns="provider_display_name", values="downloads", aggfunc="last")
                .fillna(0)
                .sort_index()
            )
            st.plotly_chart(
                make_line_chart(pivot_downloads, MODEL_COLORS,
                                title=f"{_npm_label} npm Daily Download History",
                                y_title="Downloads", hover_suffix="downloads"),
                width="stretch", theme=None,
            )
            # Market share
            totals = npm_grouped.groupby("download_date")["downloads"].sum().rename("total").reset_index()
            share = npm_grouped.merge(totals, on="download_date", how="left")
            share["share"] = share["downloads"] / share["total"].where(share["total"] != 0)
            pivot_share = (
                share.pivot_table(index="download_date", columns="provider_display_name", values="share", aggfunc="last")
                .fillna(0)
                .sort_index()
            )
            st.plotly_chart(
                make_stacked_bar(pivot_share * 100, MODEL_COLORS,
                                 title=f"{_npm_label} npm Daily Download Share",
                                 y_title="Share", pct=True, height=340),
                width="stretch", theme=None,
            )

    with github_tab:
        if github_adoption.empty:
            st.info("No GitHub provider signal data available yet.")
        else:
            candidates_daily = provider_views["candidates_daily"]
            rollup_daily = provider_views["rollup_daily"]

            col_left, col_right = st.columns(2)
            with col_left:
                pivot_candidates = (
                    candidates_daily.set_index("repo_created_date")[["repo_candidates"]]
                    .rename(columns={"repo_candidates": "Scanned Repo Pool"})
                    .fillna(0)
                    .sort_index()
                )
                st.plotly_chart(
                    make_line_chart(pivot_candidates, MODEL_COLORS,
                                    title="GitHub Scanned New Repo Pool by Day",
                                    y_title="Repos", hover_suffix="repos", height=340),
                    width="stretch", theme=None,
                )

            with col_right:
                pivot_signals = (
                    rollup_daily.pivot_table(
                        index="signal_date",
                        columns="provider_display_name",
                        values="signal_repos",
                        aggfunc="last",
                    )
                    .fillna(0)
                    .sort_index()
                )
                st.plotly_chart(
                    make_line_chart(pivot_signals, MODEL_COLORS,
                                    title="GitHub Signal-Bearing Repos by Day",
                                    y_title="Repos", hover_suffix="repos", height=340),
                    width="stretch", theme=None,
                )

    with summary_tab:
        pypi_window = pypi_grouped.copy()
        pypi_window["download_date"] = pd.to_datetime(pypi_window["download_date"], errors="coerce")
        latest_pypi_ts = pd.to_datetime(latest_pypi_date, errors="coerce")
        trailing_start = latest_pypi_ts - pd.Timedelta(days=6) if pd.notna(latest_pypi_ts) else None

        if trailing_start is not None:
            window = pypi_window[pypi_window["download_date"] >= trailing_start].copy()
        else:
            window = pypi_window.copy()

        pypi_7d = (
            window.groupby("provider_display_name", dropna=False)["downloads"].mean().rename("PyPI 7d Avg").reset_index()
            if not window.empty
            else pd.DataFrame(columns=["provider_display_name", "PyPI 7d Avg"])
        )
        latest_pypi_summary = latest_pypi.rename(
            columns={
                "provider_display_name": "Provider",
                "downloads": "Latest PyPI Downloads",
            }
        )[["Provider", "Latest PyPI Downloads"]]

        summary = latest_pypi_summary.merge(
            pypi_7d.rename(columns={"provider_display_name": "Provider"}),
            on="Provider",
            how="left",
        )

        npm_window = npm_grouped.copy()
        npm_window["download_date"] = pd.to_datetime(npm_window["download_date"], errors="coerce")
        latest_npm_ts = pd.to_datetime(latest_npm_date, errors="coerce")
        npm_trailing_start = latest_npm_ts - pd.Timedelta(days=6) if pd.notna(latest_npm_ts) else None
        if npm_trailing_start is not None:
            npm_window = npm_window[npm_window["download_date"] >= npm_trailing_start].copy()

        if not latest_npm.empty:
            cat_summary = latest_npm[latest_npm["package_category"] == selected_npm_category].copy()
            if not cat_summary.empty:
                cat_summary = cat_summary.rename(columns={"provider_display_name": "Provider", "downloads": "npm Daily (Selected)"})[["Provider", "npm Daily (Selected)"]]
                summary = summary.merge(cat_summary, on="Provider", how="left")

        if not latest_hf.empty:
            hf_sum = latest_hf.rename(columns={
                "provider_display_name": "Provider",
                "downloads_30d": "HF 30d Downloads",
                "downloads_all_time": "HF All-Time Downloads",
                "downloads_daily_est": "HF Daily (Est)",
                "likes": "HF Likes"
            })[["Provider", "HF 30d Downloads", "HF All-Time Downloads", "HF Daily (Est)", "HF Likes"]]
            summary = summary.merge(hf_sum, on="Provider", how="left")

        if latest_github_date and not provider_views["rollup_daily"].empty:
            latest_rollup = provider_views["rollup_daily"]
            latest_rollup = latest_rollup[latest_rollup["signal_date"] == latest_github_date].copy()
            rollup_summary = latest_rollup.rename(
                columns={
                    "provider_display_name": "Provider",
                    "signal_repos": "GH Signals",
                    "import_repos": "Import Repos",
                }
            )[["Provider", "GH Signals", "Import Repos"]]
            summary = summary.merge(rollup_summary, on="Provider", how="left")

        # Sort: priority to HF 30d, otherwise PyPI
        sort_col = "HF 30d Downloads" if "HF 30d Downloads" in summary.columns else "Latest PyPI Downloads"
        summary = summary.sort_values(sort_col, ascending=False) if sort_col in summary.columns else summary

        display_date = latest_github_date or latest_npm_date or latest_pypi_date
        st.caption(f"Latest provider snapshot: {display_date or 'n/a'}")
        st.dataframe(dataframe_for_display(summary, "-"), width="stretch", hide_index=True)


def render_semiconductor_section(datasets: dict[str, DatasetLoadResult], semi_views: dict[str, object]) -> None:
    regime_df = semi_views.get("regime_df", pd.DataFrame())
    component_columns = semi_views.get("component_columns", [])
    base_month = semi_views.get("base_month")
    latest_proxy_month = semi_views.get("latest_proxy_month")
    latest_proxy_data = semi_views.get("latest_proxy_data", pd.Series(dtype="object"))
    latest_fred_month = semi_views.get("latest_fred_month")
    latest_fred_series_names = semi_views.get("latest_fred_series_names", [])

    if regime_df.empty:
        st.warning("No semiconductor memory data available.")
        return

    st.markdown('<div class="section-title">Market Intelligence Hub</div>', unsafe_allow_html=True)

    active_month = latest_proxy_month or semi_views.get("latest_month")
    current_data = latest_proxy_data if not latest_proxy_data.empty else semi_views.get("latest_data", pd.Series(dtype="object"))

    # --- PPI cards with lag handling ---
    ppi_val = current_data.get("fred_ppi_value")
    ppi_mom = current_data.get("fred_ppi_mom_pct")
    ppi_trend = current_data.get("fred_ppi_3m_trend")

    ppi_display_val = "—"
    if pd.notna(ppi_val):
        ppi_display_val = f"{ppi_val:.1f}"

    if pd.notna(ppi_mom):
        ppi_delta_cls = "up" if ppi_mom >= 0 else "down"
        ppi_delta_text = f"{'↑' if ppi_mom >= 0 else '↓'} {abs(ppi_mom):.1f}% MoM"
    else:
        ppi_delta_cls, ppi_delta_text = "flat", "latest complete basket month"

    trend_display_val = f"{ppi_trend:.1f}" if pd.notna(ppi_trend) else "—"
    snapshot_delta = "latest complete basket month"
    if latest_fred_month and active_month and latest_fred_month > active_month:
        updated_count = len(latest_fred_series_names)
        noun = "series" if updated_count != 1 else "series"
        snapshot_delta = f"Using {active_month}; {latest_fred_month} has {updated_count} updated {noun}, but the basket is incomplete"

    st.markdown(
        kpi_grid_html(
            kpi_card_html("Snapshot Month", active_month or "—", delta=snapshot_delta, delta_class="flat"),
            kpi_card_html("AI Demand PPI", ppi_display_val, delta=ppi_delta_text, delta_class=ppi_delta_cls),
            kpi_card_html("3M Trend", trend_display_val, delta="rebased index average", delta_class="flat"),
            kpi_card_html("Proxy Base Month", base_month or "—", delta=f"{len(AI_DEMAND_PPI_WEIGHTS)} weighted PPIs", delta_class="flat"),
        ),
        unsafe_allow_html=True,
    )

    st.markdown(
        "[ADATA Industrial Market Watch](https://industrial.adata.com/en/edm)",
        unsafe_allow_html=False,
    )
    weight_note = ", ".join(
        f"{AI_DEMAND_PPI_LABELS.get(series_id, series_id)}: {int(weight * 100)}%"
        for series_id, weight in AI_DEMAND_PPI_WEIGHTS.items()
    )
    st.caption(
        "AI Demand PPI is a weighted basket rebased to 100 at the first common month. "
        f"Weights: {weight_note}"
    )
    if latest_fred_month and active_month and latest_fred_month > active_month:
        st.info(
            f"Latest raw PPI updates reach {latest_fred_month}, but the weighted AI Demand PPI remains on {active_month} "
            "until all five component series have updated for the same month."
        )

    _ppi_range = st.radio(
        "Time range",
        options=["YTD", "1yr", "2yr", "5yr", "All"],
        index=2,
        horizontal=True,
        key="semi_ppi_range",
    )
    _now = datetime.now()
    _cutoffs = {
        "YTD": f"{_now.year}-01",
        "1yr": (_now - pd.DateOffset(months=12)).strftime("%Y-%m"),
        "2yr": (_now - pd.DateOffset(months=24)).strftime("%Y-%m"),
        "5yr": (_now - pd.DateOffset(months=60)).strftime("%Y-%m"),
    }
    _cutoff = _cutoffs.get(_ppi_range)
    _plot_df = regime_df[regime_df["month"] >= _cutoff].copy() if _cutoff else regime_df.copy()

    proxy_pivot = _plot_df[["month", "fred_ppi_value"]].set_index("month").rename(columns={"fred_ppi_value": "AI Demand PPI"})
    st.plotly_chart(
        make_line_chart(proxy_pivot, [ACCENT], title="AI Demand PPI Trend", y_title="Rebased Index", x_title="Month", height=350),
        width="stretch",
    )

    available_component_columns = [column for column in component_columns if column in _plot_df.columns]
    if available_component_columns:
        component_labels = {
            AI_DEMAND_PPI_COMPONENT_COLUMNS[series_id]: AI_DEMAND_PPI_LABELS.get(series_id, series_id)
            for series_id in AI_DEMAND_PPI_WEIGHTS
        }
        component_pivot = _plot_df[["month", *available_component_columns]].set_index("month").rename(columns=component_labels)
        st.plotly_chart(
            make_line_chart(
                component_pivot,
                MODEL_COLORS[:len(component_pivot.columns)],
                title="Component PPIs (Rebased)",
                y_title="Rebased Index",
                x_title="Month",
                height=380,
            ),
            width="stretch",
        )


def render_artificial_analysis_section(datasets: dict[str, DatasetLoadResult], aa_views: dict[str, object]) -> None:
    models_latest = aa_views.get("models_latest", pd.DataFrame())
    capex_pivot = aa_views.get("capex_pivot", pd.DataFrame())
    frontier_by_lab = aa_views.get("frontier_by_lab_pivot", pd.DataFrame())
    price_models = aa_views.get("price_models", pd.DataFrame())
    frontier_by_country = aa_views.get("frontier_by_country_pivot", pd.DataFrame())
    frontier_by_country_points = aa_views.get("frontier_by_country_points", pd.DataFrame())
    china_catchup_lag = aa_views.get("china_catchup_lag", pd.DataFrame())
    open_vs_proprietary = aa_views.get("open_vs_proprietary_pivot", pd.DataFrame())

    if models_latest.empty and capex_pivot.empty:
        st.warning("No Artificial Analysis data available.")
        return

    st.markdown('<div class="section-title">Artificial Analysis Trends</div>', unsafe_allow_html=True)
    latest_as_of = aa_views.get("latest_as_of") or "-"
    peak_intelligence = models_latest["intelligence_index"].max() if not models_latest.empty else np.nan
    median_price = price_models["price_1m_blended_3_to_1"].median() if not price_models.empty else np.nan
    latest_capex_total = aa_views.get("latest_capex_total", np.nan)

    st.markdown(
        kpi_grid_html(
            kpi_card_html("Snapshot Date", str(latest_as_of), delta=f"{len(models_latest)} models"),
            kpi_card_html("Peak Intelligence", f"{peak_intelligence:.1f}" if pd.notna(peak_intelligence) else "-", delta="latest API snapshot"),
            kpi_card_html("Median Blended Price", f"${median_price:.2f}" if pd.notna(median_price) else "-", delta="per 1M tokens"),
            kpi_card_html("Latest Capex Quarter", f"${latest_capex_total:,.1f}B" if pd.notna(latest_capex_total) else "-", delta="tracked companies"),
        ),
        unsafe_allow_html=True,
    )

    capex_tab, frontier_tab, price_tab, country_tab, openness_tab = st.tabs(
        ["Capex", "Frontier Intelligence", "Inference Price", "Country", "Open vs Proprietary"]
    )

    with capex_tab:
        st.markdown('<div class="section-subtitle">Capital Expenditure by Major Tech Companies, Over Time</div>', unsafe_allow_html=True)
        if capex_pivot.empty:
            st.info("Capital expenditure data is not available yet.")
        else:
            st.plotly_chart(
                make_stacked_bar(
                    capex_pivot,
                    ["#00A4EF", "#34A853", "#0089F4", "#FF9900", "#F80000", "#6B7280"],
                    y_title="Capital Expenditure (USD billions)",
                    height=430,
                ),
                width="stretch",
                theme=None,
            )

    with frontier_tab:
        st.markdown('<div class="section-subtitle">Frontier Language Model Intelligence, Over Time</div>', unsafe_allow_html=True)
        if frontier_by_lab.empty:
            st.info("Frontier intelligence data is not available yet.")
        else:
            st.plotly_chart(
                make_line_chart(
                    frontier_by_lab,
                    MODEL_COLORS,
                    y_title="Artificial Analysis Intelligence Index",
                    x_title="Release Date",
                    height=430,
                ),
                width="stretch",
                theme=None,
            )

    with price_tab:
        st.markdown('<div class="section-subtitle">Language Model Inference Price</div>', unsafe_allow_html=True)
        if price_models.empty:
            st.info("Inference price data is not available yet.")
        else:
            fig_price = go.Figure()
            for i, (creator, creator_df) in enumerate(price_models.groupby("creator_name", dropna=True)):
                fig_price.add_trace(
                    go.Scatter(
                        x=creator_df["release_date"],
                        y=creator_df["price_1m_blended_3_to_1"],
                        mode="markers",
                        name=str(creator),
                        marker=dict(
                            size=np.clip(creator_df["intelligence_index"].fillna(5) * 0.45, 6, 20),
                            color=MODEL_COLORS[i % len(MODEL_COLORS)],
                            opacity=0.75,
                            line=dict(width=1, color="white"),
                        ),
                        text=creator_df["model_name"],
                        customdata=creator_df[["intelligence_index", "median_output_tokens_per_second"]],
                        hovertemplate=(
                            "<b>%{text}</b><br>%{x|%Y-%m-%d}<br>"
                            "Blended price: $%{y:.3f} / 1M tokens<br>"
                            "Intelligence: %{customdata[0]:.1f}<br>"
                            "Output speed: %{customdata[1]:.1f} tok/s<extra></extra>"
                        ),
                    )
                )
            fig_price.update_layout(
                template="plotly_white",
                xaxis_title="Release Date",
                yaxis_title="Blended Price ($ / 1M tokens)",
                height=430,
                margin=dict(l=0, r=0, t=20, b=80),
                legend=dict(orientation="h", y=-0.22),
            )
            st.plotly_chart(fig_price, width="stretch", theme=None)

    with country_tab:
        st.markdown('<div class="section-subtitle">Frontier Language Model Intelligence: US vs China</div>', unsafe_allow_html=True)
        if frontier_by_country.empty:
            st.info("No US or China provider-country matches are available in the current Artificial Analysis snapshot.")
        else:
            country_colors = {"United States": "#2563EB", "China": "#DC2626"}
            fig_country = go.Figure()
            for country in frontier_by_country.columns:
                country_points = frontier_by_country_points[
                    frontier_by_country_points["country_label"] == country
                ].sort_values("release_date")
                if country_points.empty:
                    fig_country.add_trace(
                        go.Scatter(
                            x=frontier_by_country.index,
                            y=frontier_by_country[country],
                            mode="lines+markers",
                            name=str(country),
                            line=dict(width=3, color=country_colors.get(str(country), MODEL_COLORS[0])),
                        )
                    )
                    continue
                fig_country.add_trace(
                    go.Scatter(
                        x=country_points["release_date"],
                        y=country_points["intelligence_index"],
                        mode="lines+markers",
                        name=str(country),
                        line=dict(width=3, color=country_colors.get(str(country), MODEL_COLORS[0])),
                        customdata=country_points[["model_name", "creator_name"]],
                        hovertemplate=(
                            "<b>%{customdata[0]}</b><br>"
                            "%{customdata[1]} - %{fullData.name}<br>"
                            "%{x|%Y-%m-%d}<br>"
                            "Intelligence: %{y:.1f}<extra></extra>"
                        ),
                    )
                )
            fig_country.update_layout(
                template="plotly_white",
                xaxis_title="Release Date",
                yaxis_title="Artificial Analysis Intelligence Index",
                legend=dict(orientation="h", y=-0.2),
                height=430,
                margin=dict(l=0, r=0, t=40, b=80),
            )
            st.plotly_chart(fig_country, width="stretch", theme=None)
            st.markdown('<div class="section-subtitle">China Catch-Up Lag to US Frontier Breakthroughs</div>', unsafe_allow_html=True)
            if china_catchup_lag.empty:
                st.info("Catch-up lag requires both United States and China frontier series.")
            else:
                lag_plot = china_catchup_lag.copy()
                lag_plot["catchup_label"] = lag_plot["china_catchup_date"].fillna("Not yet caught")
                fig_lag = go.Figure(
                    go.Scatter(
                        x=pd.to_datetime(lag_plot["us_breakthrough_date"], errors="coerce"),
                        y=lag_plot["lag_months"],
                        mode="lines+markers",
                        line=dict(width=3, color="#DC2626", dash="solid"),
                        marker=dict(
                            size=10,
                            color=np.where(lag_plot["status"] == "caught_up", "#DC2626", "#9CA3AF"),
                            symbol=np.where(lag_plot["status"] == "caught_up", "circle", "x"),
                        ),
                        customdata=lag_plot[["us_intelligence_index", "catchup_label", "status"]],
                        hovertemplate=(
                            "<b>US breakthrough %{x}</b><br>"
                            "US intelligence: %{customdata[0]:.1f}<br>"
                            "China catch-up: %{customdata[1]}<br>"
                            "Lag: %{y:.1f} months<br>"
                            "Status: %{customdata[2]}<extra></extra>"
                        ),
                    )
                )
                fig_lag.update_layout(
                    template="plotly_white",
                    xaxis_title="US Breakthrough Date",
                    yaxis_title="Months Until China Catch-Up",
                    height=320,
                    margin=dict(l=0, r=0, t=20, b=80),
                    showlegend=False,
                )
                st.plotly_chart(fig_lag, width="stretch", theme=None)

    with openness_tab:
        st.markdown('<div class="section-subtitle">Progress in Open Weights vs. Proprietary Intelligence</div>', unsafe_allow_html=True)
        if open_vs_proprietary.empty:
            st.info("The current Artificial Analysis API snapshot does not expose open-weight categorization fields.")
        else:
            st.plotly_chart(
                make_line_chart(
                    open_vs_proprietary,
                    ["#071846", "#6467F4"],
                    y_title="Artificial Analysis Intelligence Index",
                    x_title="Release Date",
                    height=430,
                ),
                width="stretch",
                theme=None,
            )


def render_ai_frontier_section(datasets: dict[str, DatasetLoadResult], benchmark_views: dict[str, object]) -> None:
    models_df = benchmark_views.get("models_df", pd.DataFrame())
    sota_peaks = benchmark_views.get("sota_peaks", pd.DataFrame())
    frontier_avg = benchmark_views.get("frontier_avg", {})
    velocity = benchmark_views.get("innovation_velocity", 0)

    if models_df.empty:
        st.warning("No LLM benchmark data available. Run 'cli update' for llm_benchmark_data.")
        return

    # --- Header & Filter ---
    h_col1, h_col2 = st.columns([2, 1])
    with h_col1:
        st.markdown('<div class="section-title">AI Frontier & Intelligence Dynamics</div>', unsafe_allow_html=True)
    with h_col2:
        min_date = models_df["release_date"].min().date()
        max_date = models_df["release_date"].max().date()
        default_start = max_date - pd.Timedelta(days=365)
        date_range = st.date_input(
            "Analysis Period",
            value=(max(min_date, default_start), max_date),
            min_value=min_date,
            max_value=max_date,
        )

    if len(date_range) == 2:
        start_date, end_date = date_range
        filtered_df = models_df[
            (models_df["release_date"].dt.date >= start_date) & 
            (models_df["release_date"].dt.date <= end_date)
        ].copy()
    else:
        filtered_df = models_df.copy()

    # Re-calculate KPIs for filtered range
    range_max_gpqa = filtered_df["gpqa"].max()
    range_max_swe = filtered_df["swe_bench"].max()
    range_avg_context = filtered_df[filtered_df["gpqa"] >= filtered_df["gpqa"].quantile(0.95)]["context_window"].mean() if not filtered_df.empty else 0

    # --- KPI Row ---
    st.markdown(
        kpi_grid_html(
            kpi_card_html("Innovation Velocity", f"{velocity:.1f}d", delta="Avg SOTA cycle"),
            kpi_card_html("Frontier Context Floor", format_metric(range_avg_context), delta="↑ High Demand", delta_class="up"),
            kpi_card_html("Peak Intelligence (GPQA)", f"{range_max_gpqa:.1%}", delta="selected range"),
            kpi_card_html("Peak Agents (SWE-bench)", f"{range_max_swe:.1%}", delta="verified coding"),
        ),
        unsafe_allow_html=True,
    )

    # --- Charts ---
    c_col1, c_col2 = st.columns(2)

    with c_col1:
        # SOTA Progress Chart
        st.markdown('<div class="section-subtitle" style="margin-top:1rem;">Intelligence SOTA Path (GPQA)</div>', unsafe_allow_html=True)
        fig_sota = go.Figure()
        
        # All models (smaller)
        fig_sota.add_trace(go.Scatter(
            x=filtered_df["release_date"], y=filtered_df["gpqa"],
            mode="markers", name="Other Models",
            marker=dict(size=6, color=MUTED, opacity=0.3),
            hovertemplate="<b>%{text}</b><br>%{x}<br>Score: %{y:.3f}<extra></extra>",
            text=filtered_df["name"]
        ))
        
        # SOTA line (Peaks)
        range_sota = sota_peaks[
            (sota_peaks["release_date"].dt.date >= start_date) & 
            (sota_peaks["release_date"].dt.date <= end_date)
        ]
        fig_sota.add_trace(go.Scatter(
            x=range_sota["release_date"], y=range_sota["gpqa"],
            mode="lines+markers", name="SOTA Peaks",
            line=dict(color=ACCENT, width=3, shape="hv"),
            marker=dict(size=10, symbol="star", color=ACCENT),
            hovertemplate="<b>SOTA: %{text}</b><br>%{x}<br>Score: %{y:.3f}<extra></extra>",
            text=range_sota["name"]
        ))
        
        fig_sota.update_layout(
            title="Intelligence SOTA Path (GPQA)",
            template="plotly_white", 
            height=380, 
            margin=dict(l=0, r=0, t=40, b=40), 
            legend=dict(orientation="h", y=-0.2)
        )
        st.plotly_chart(fig_sota, width="stretch", theme=None)

    with c_col2:
        # Context Window Scaling
        st.markdown('<div class="section-subtitle" style="margin-top:1rem;">Memory Demand: Context Window Scaling</div>', unsafe_allow_html=True)
        
        # Highlight Big Tech
        def get_color(org):
            org_lower = str(org).lower()
            for tech in BIG_TECH_ORGS:
                if tech in org_lower:
                    return ACCENT
            return MUTED

        filtered_df["color"] = filtered_df["organization"].apply(get_color)
        filtered_df["size"] = (filtered_df["gpqa"] * 15).fillna(5)
        
        fig_ctx = go.Figure()
        fig_ctx.add_trace(go.Scatter(
            x=filtered_df["release_date"], y=filtered_df["context_window"],
            mode="markers",
            marker=dict(
                size=filtered_df["size"],
                color=filtered_df["color"],
                opacity=0.6,
                line=dict(width=1, color="white")
            ),
            text=filtered_df["name"],
            customdata=filtered_df["organization"],
            hovertemplate="<b>%{text}</b> (%{customdata})<br>%{x}<br>Context: %{y:,.0f} tokens<extra></extra>"
        ))
        
        fig_ctx.update_layout(
            title="Context Window Scaling",
            template="plotly_white", 
            height=380, 
            margin=dict(l=0, r=0, t=40, b=40),
            yaxis=dict(type="log", title="Tokens (Log Scale)")
        )
        st.plotly_chart(fig_ctx, width="stretch", theme=None)

    # --- Frontier Leaderboard ---
    st.markdown('<div class="section-title">Frontier Intelligence Leaderboard</div>', unsafe_allow_html=True)
    table_df = filtered_df.sort_values("gpqa", ascending=False).head(30)[
        ["name", "organization", "release_date", "gpqa", "swe_bench", "context_window"]
    ].copy()
    
    table_df = table_df.rename(columns={
        "name": "Model",
        "organization": "Organization",
        "release_date": "Date",
        "gpqa": "GPQA",
        "swe_bench": "SWE-bench",
        "context_window": "Context"
    })
    
    table_df["Date"] = table_df["Date"].dt.date
    table_df["Context"] = table_df["Context"].apply(lambda x: format_metric(x) if pd.notna(x) else "-")
    
    if table_df.empty:
        st.info("No leaderboard entries for the selected range.")
    else:
        st.dataframe(
            table_df.style.format({
                "GPQA": "{:.2%}",
                "SWE-bench": "{:.2%}"
            }).background_gradient(subset=["GPQA"], cmap="Blues"),
            width="stretch",
            hide_index=True
        )


def render_checks(checks: list[CheckResult]) -> None:
    ok_count   = sum(1 for c in checks if c.status == "ok")
    warn_count = sum(1 for c in checks if c.status == "warning")
    err_count  = sum(1 for c in checks if c.status == "error")

    label = f"Data Health — {ok_count} ok · {warn_count} warning · {err_count} error"
    with st.expander(label, expanded=(err_count > 0)):
        for chk in checks:
            css = f"chk-{chk.status}"
            domain_label = "" if chk.domain == "global" else f"[{chk.domain}] "
            st.markdown(
                f'<div class="{css}">{domain_label}{chk.title}</div>'
                f'<div style="color:{MUTED};margin-bottom:0.8rem;font-size:0.85rem;">{chk.detail}</div>',
                unsafe_allow_html=True,
            )


def render_compute_evolution_section(compute_views: dict[str, object]) -> None:
    """Render the OpenRouter catalog-growth + context-vs-pricing pair inside the OpenRouter tab.

    NOTE: Previously this was `render_compute_availability_section` with AWS Spot + Lambda
    Cloud KPIs and panels. Those sources were removed; only the two OpenRouter catalog
    charts survived and were moved out of the now-deleted HW & Compute tab.
    """
    models_latest = compute_views.get("models_latest", pd.DataFrame())
    models_growth = compute_views.get("models_growth", pd.DataFrame())
    models_history_start = compute_views.get("models_history_start")
    models_history_end = compute_views.get("models_history_end")

    st.markdown('<div class="section-title">Compute Evolution</div>', unsafe_allow_html=True)
    row2_col1, row2_col2 = st.columns(2)

    with row2_col1:
        st.markdown('<div class="section-subtitle">OpenRouter Model Catalog Growth</div>', unsafe_allow_html=True)
        if not models_growth.empty:
            fig_growth = go.Figure()
            fig_growth.add_trace(go.Scatter(
                x=models_growth["snapshot_ts"],
                y=models_growth["model_count"],
                fill='tozeroy',
                line=dict(color=ACCENT, width=3)
            ))
            fig_growth.update_layout(
                title="Model Catalog Growth",
                template="plotly_white",
                height=350,
                margin=dict(l=0, r=0, t=40, b=10)
            )
            st.plotly_chart(fig_growth, width="stretch", theme=None)
            if models_history_start is not None and models_history_end is not None:
                start_label = pd.Timestamp(models_history_start).strftime("%Y-%m-%d")
                end_label = pd.Timestamp(models_history_end).strftime("%Y-%m-%d")
                st.caption(
                    f"History reflects the normalized OpenRouter catalog snapshots currently on disk ({start_label} to {end_label})."
                )

    with row2_col2:
        st.markdown('<div class="section-subtitle">Context Window vs. Pricing Prompt</div>', unsafe_allow_html=True)
        if not models_latest.empty:
            # Filter for positive pricing to avoid log-scale errors
            plot_df = models_latest[models_latest["pricing_prompt"] > 0].copy()
            
            fig_scatter = go.Figure()
            fig_scatter.add_trace(go.Scatter(
                x=plot_df["context_length"],
                y=plot_df["pricing_prompt"] * 1e6,
                mode="markers",
                marker=dict(
                    size=10,
                    color=ACCENT,
                    opacity=0.5,
                    line=dict(width=1, color="white")
                ),
                text=plot_df["model_id"],
                hovertemplate="<b>%{text}</b><br>Context: %{x:,.0f}<br>Price: $%{y:.2f}/1M<extra></extra>"
            ))
            fig_scatter.update_layout(
                title="Price vs. Context",
                template="plotly_white",
                height=400,
                xaxis_title="Context Length",
                yaxis_title="Price per 1M Tokens ($)",
                yaxis_type="log",
                margin=dict(l=0, r=0, t=40, b=10)
            )
            st.plotly_chart(fig_scatter, width="stretch", theme=None)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # 1. Immediate call to set_page_config
    st.set_page_config(page_title="Alternative Data Dashboard", layout="wide", page_icon="📊")
    
    # 2. Startup logging for deployment debugging
    
    inject_css()

    selected_section = select_main_section()
    selected_domains = section_domains(selected_section)
    domain_states = {
        domain: load_domain_state_cached(BASE_DIR, domain, build_domain_signature(BASE_DIR, domain))
        for domain in selected_domains
    }

    datasets: dict[str, DatasetLoadResult] = {}
    _all_freshness: list[FreshnessInfo] = []
    checks: list[CheckResult] = []
    for domain_datasets, domain_freshness, domain_checks in domain_states.values():
        datasets.update(domain_datasets)
        _all_freshness.append(domain_freshness)
        checks.extend(domain_checks)

    freshness = FreshnessInfo(
        latest_scraped_at=max(
            (f.latest_scraped_at for f in _all_freshness if f.latest_scraped_at), default=None,
        ),
        latest_run_id=next(
            (f.latest_run_id for f in _all_freshness if f.latest_run_id), None,
        ),
        latest_manifest_path=next(
            (f.latest_manifest_path for f in _all_freshness if f.latest_manifest_path), None,
        ),
        latest_manifest_scraped_at=max(
            (f.latest_manifest_scraped_at for f in _all_freshness if f.latest_manifest_scraped_at), default=None,
        ),
    )

    render_header(freshness)
    st.caption("Only the selected dashboard section is loaded, which keeps Streamlit Cloud restarts lighter and faster.")

    if selected_section == "OpenRouter Intelligence":
        openrouter_views = compute_openrouter_views(
            {
                **domain_states["rankings"][0],
                **domain_states["apps"][0],
                **domain_states["compute_availability"][0],
            },
            revenue_cache_version=REVENUE_CACHE_VERSION,
        )
        compute_views = compute_compute_availability_views(domain_states["compute_availability"][0])
        render_rankings_semantics_note(datasets)
        render_kpi_row(datasets, openrouter_views)
        render_top_models_chart(datasets, openrouter_views)
        render_market_share_section(datasets, openrouter_views)
        render_leaderboard(datasets)
        render_revenue_estimator(datasets, openrouter_views)
        render_token_volume_chart(openrouter_views)
        render_token_revenue_comparison(openrouter_views)
        render_compute_evolution_section(compute_views)
        render_apps_tables(datasets)
    elif selected_section == "Artificial Analysis":
        aa_views = compute_artificial_analysis_views(domain_states["artificial_analysis"][0])
        render_artificial_analysis_section(datasets, aa_views)
    elif selected_section == "AI Frontier & HBM":
        benchmark_views = compute_llm_benchmark_views(domain_states["ai_frontier"][0])
        render_ai_frontier_section(datasets, benchmark_views)
    elif selected_section == "GitHub Trending":
        github_views = compute_github_views(domain_states["github"][0])
        render_github_trending_section(datasets, github_views)
    elif selected_section == "Provider Adoption":
        provider_views = compute_provider_adoption_views(domain_states["provider_adoption"][0])
        render_provider_adoption_section(datasets, provider_views)
    elif selected_section == "Semiconductor Analysis":
        semi_views = compute_semiconductor_views(domain_states["semiconductor_memory"][0])
        render_semiconductor_section(datasets, semi_views)
        
    render_checks(checks)


if __name__ == "__main__":
    main()
