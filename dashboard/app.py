from __future__ import annotations

from pathlib import Path
import sys
import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import matplotlib

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

    manifests = sorted(raw_dir.rglob("manifest.json"))
    if not manifests:
        return tuple()

    latest = max(manifests, key=lambda p: p.stat().st_mtime_ns)
    stat = latest.stat()
    return ((str(latest.relative_to(base_dir)), stat.st_mtime_ns, stat.st_size),)


def build_domain_signature(base_dir: Path, domain: str) -> tuple[tuple[str, int, int], ...]:
    return build_normalized_signature(base_dir, domain) + build_manifest_signature(base_dir, domain)


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


def rankings_week_context(datasets: dict[str, DatasetLoadResult]) -> dict[str, str | bool | None]:
    top_models = datasets.get("top_models")
    market_share = datasets.get("market_share")
    programming = datasets.get("categories_programming")

    model_week = top_models.latest_date if top_models else None
    market_share_week = market_share.latest_date if market_share else None
    programming_week = programming.latest_date if programming else None

    return {
        "model_week": model_week,
        "market_share_week": market_share_week,
        "programming_week": programming_week,
        "model_scraped_at": top_models.latest_scraped_at if top_models else None,
        "market_share_scraped_at": market_share.latest_scraped_at if market_share else None,
        "programming_scraped_at": programming.latest_scraped_at if programming else None,
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
    limit: int = 20,
) -> pd.DataFrame:
    if latest_hf_models.empty or not provider_display_name or provider_display_name == "All":
        return pd.DataFrame(columns=["Provider", "Model", "30d Downloads", "All-Time Downloads", "Daily (Est)", "Likes", "Last Modified"])

    table = latest_hf_models[latest_hf_models["provider_display_name"] == provider_display_name].copy()
    if table.empty:
        return pd.DataFrame(columns=["Provider", "Model", "30d Downloads", "All-Time Downloads", "Daily (Est)", "Likes", "Last Modified"])

    table = table.sort_values(
        ["hf_downloads_30d", "hf_downloads_all_time"],
        ascending=[False, False],
        na_position="last",
    ).head(limit)

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
        }
    return {
        "value_column": "downloads_30d",
        "downloads_title": "Hugging Face Trailing 30d Downloads",
        "downloads_axis": "Downloads (30d)",
        "downloads_hover": "30d downloads",
        "share_title": "Hugging Face Download Share (30d)",
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
        top["Others"] = pivot_df[other_cols].sum(axis=1)
    return top


@st.cache_data(ttl=3600)
def load_domain_state_cached(
    base_dir: Path,
    domain: str,
    domain_signature: tuple[tuple[str, int, int], ...],
) -> tuple[dict[str, DatasetLoadResult], FreshnessInfo, list[CheckResult]]:
    _ = domain_signature
    datasets = load_domain_datasets(domain, base_dir=base_dir)
    freshness = load_latest_manifest(base_dir=base_dir, datasets=datasets)
    checks = run_checks(datasets, freshness, base_dir=base_dir)
    return datasets, freshness, checks


# --- OpenRouter Provider Mapping ---
OPENROUTER_PROVIDER_MAP = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "meta": "Meta (Llama)",
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
) -> dict[str, object]:
    views: dict[str, object] = {}

    for dataset_id in ["top_models", "categories_programming"]:
        result = datasets.get(dataset_id)
        if not result or result.frame.empty:
            views[dataset_id] = {"weeks": [], "pivot_top": pd.DataFrame()}
            continue
        frame = result.frame.copy()
        frame["week_start_date"] = frame["week_start_date"].astype(str)
        pivot = (
            frame.pivot_table(index="week_start_date", columns="entity_id", values="metric_value", aggfunc="sum")
            .fillna(0)
            .sort_index()
        )
        views[dataset_id] = {
            "weeks": sorted(frame["week_start_date"].unique(), reverse=True),
            "pivot_top": _top_n_with_others(pivot, top_n_count=15),
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

    app_result = datasets.get("app_top_models_daily_snapshot")
    use_daily = False
    if not app_result or app_result.frame.empty:
        app_result = datasets.get("app_usage_daily")
        use_daily = True

    if app_result and not app_result.frame.empty:
        frame = app_result.frame.copy()
        date_col = "usage_date" if use_daily else "snapshot_date"
        model_col = "model_permaslug"
        value_col = "total_tokens"
        frame[date_col] = frame[date_col].astype(str)
        pivot = (
            frame.pivot_table(index=date_col, columns=model_col, values=value_col, aggfunc="sum")
            .fillna(0)
            .sort_index()
        )
        views["app_usage"] = {
            "date_col": date_col,
            "value_col": value_col,
            "days": sorted(frame[date_col].unique(), reverse=True),
            "pivot_top": _top_n_with_others(pivot, top_n_count=15),
        }
    else:
        views["app_usage"] = {"date_col": "usage_date", "value_col": "total_tokens", "days": [], "pivot_top": pd.DataFrame()}

    # --- Revenue Estimator Logic ---
    activity_res = datasets.get("app_usage_daily")
    macro_res = datasets.get("top_models")
    pricing_res = datasets.get("raw_openrouter_models")

    if activity_res and not activity_res.frame.empty and pricing_res and not pricing_res.frame.empty:
        pricing = pricing_res.frame.copy()
        
        # Get latest pricing per model
        latest_pricing = pricing.sort_values("snapshot_ts").groupby("model_id").tail(1)
        pricing_model_ids = set(latest_pricing["model_id"].tolist())
        
        def normalize_slug(slug):
            slug_str = str(slug)
            if not slug_str or slug_str.lower() in ["nan", "none", "null"]:
                return slug_str
            
            # 1. Strip common tags
            slug_str = re.sub(r':(free|beta|alpha|online|chat|search)$', '', slug_str)
            
            if slug_str in pricing_model_ids:
                return slug_str
            
            # 2. Universal Date Stripping (e.g., -20250807, -2025-08-07, -04-02)
            # We look for dash followed by 4-8 digits, OR YYYY-MM-DD, OR MM-DD
            pattern = r'-(\d{4,8}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2})$'
            base = re.sub(pattern, '', slug_str)
            if base in pricing_model_ids:
                return base
                
            # 3. Vendor Fallbacks
            if base.startswith("anthropic/claude-"):
                m = re.match(r'anthropic/claude-([\d\.]+)-(opus|sonnet|haiku)', base)
                if m:
                    permuted = f"anthropic/claude-{m.group(2)}-{m.group(1)}"
                    if permuted in pricing_model_ids: return permuted
            
            if base.startswith("qwen/qwen"):
                # Handle qwen3.6-plus -> qwen-plus if required, but first check base
                if base in pricing_model_ids: return base
                # generic plus/max fallback
                if "plus" in base and "qwen/qwen-plus" in pricing_model_ids: return "qwen/qwen-plus"
                if "max" in base and "qwen/qwen-max" in pricing_model_ids: return "qwen/qwen-max"
                
            return base if base in pricing_model_ids else slug_str
            
        def process_revenue_df(df, slug_col, tokens_col, date_col, is_macro=False):
            df["fuzzy_slug"] = df[slug_col].apply(normalize_slug)
            df_cols = [c for c in df.columns if c not in ["pricing_prompt", "pricing_completion", "top_provider_id", "model_id"]]
            
            merged = df[df_cols].merge(
                latest_pricing[["model_id", "pricing_prompt", "pricing_completion", "top_provider_id"]],
                left_on="fuzzy_slug", right_on="model_id", how="inner"
            )
            merged = merged[(merged["pricing_prompt"].notna()) & (merged["pricing_prompt"] >= 0)].copy()
            if merged.empty:
                return pd.DataFrame()
                
            if not is_macro and "prompt_tokens" in merged.columns and "completion_tokens" in merged.columns and merged["prompt_tokens"].notna().any():
                merged["revenue_usd"] = (
                    (merged["prompt_tokens"] * merged["pricing_prompt"].astype(float)) +
                    (merged["completion_tokens"] * merged["pricing_completion"].astype(float))
                )
            else:
                merged["revenue_usd"] = (
                    (merged[tokens_col] * 0.977 * merged["pricing_prompt"].astype(float)) +
                    (merged[tokens_col] * 0.023 * merged["pricing_completion"].astype(float))
                )
                
            merged["provider_label"] = merged.apply(
                lambda x: _derive_provider_name(x["model_id"], x["top_provider_id"]), axis=1
            )
            
            merged["usage_date_dt"] = pd.to_datetime(merged[date_col], errors="coerce")
            merged = merged.dropna(subset=["usage_date_dt"])
            merged = merged[merged["revenue_usd"] > 0].copy()
            if merged.empty:
                return pd.DataFrame()
            merged["usage_date_str"] = merged["usage_date_dt"].dt.strftime('%Y-%m-%d')
            merged["usage_week"] = merged["usage_date_dt"].dt.to_period('W').dt.start_time.dt.strftime('%Y-%m-%d')
            merged["usage_month"] = merged["usage_date_dt"].dt.strftime('%Y-%m')
            return merged
        
        # 1. Micro Scope (Daily)
        activity = activity_res.frame.copy()
        merged_daily = process_revenue_df(activity, "model_permaslug", "total_tokens", "usage_date")
        pivot_rev_daily = pd.DataFrame()
        if not merged_daily.empty:
            pivot_rev_daily = (
                merged_daily.pivot_table(index="usage_date_str", columns="provider_label", values="revenue_usd", aggfunc="sum")
                .fillna(0).sort_index()
            )

        # --- Smart-Scaling Revenue Engine (Hybrid) ---
        # Strategy: 
        # 1. Precise Model Revenue (Tier 1): Use top_models.csv with fuzzy pricing.
        # 2. Market-Share Top-Up (Tier 2): Use market_share totals to 'scale up' to full platform volume.
        
        pivot_rev_weekly = pd.DataFrame()
        pivot_rev_monthly = pd.DataFrame()
        
        market_share_res = datasets.get("market_share")
        if macro_res and not macro_res.frame.empty and market_share_res and not market_share_res.frame.empty:
            macro_df = macro_res.frame.copy()
            share_df = market_share_res.frame.copy()
            pricing_df = latest_pricing.copy()
            
            # Helper: Align Sundays to the following Monday
            def _align_to_monday(dt_series):
                dts = pd.to_datetime(dt_series, errors="coerce")
                # If Sunday (weekday 6), shift by 1 day
                # Then take to_period('W').start_time to get the stable Monday
                return dts.apply(lambda d: (d + pd.Timedelta(days=1)) if d.weekday() == 6 else d).dt.to_period('W').dt.start_time.dt.strftime('%Y-%m-%d')

            # 1. Normalize Dates (Unified)
            macro_df["usage_week"] = _align_to_monday(macro_df["week_start_date"])
            share_df["usage_week"] = _align_to_monday(share_df["week_start_date"])
            
            # 2. Pre-compute Fuzzy Pricing Map
            pricing_df["fuzzy_id"] = pricing_df["model_id"].apply(_fuzzy_normalize_model_id)
            pricing_df["avg_p"] = (pricing_df["pricing_prompt"] * 0.977) + (pricing_df["pricing_completion"] * 0.023)
            # Take the highest price for a fuzzy match (optimistic, works for Opus vs Sonnet)
            fuzzy_prices = pricing_df.groupby("fuzzy_id")["avg_p"].max().to_dict()
            
            # 3. Provider Benchmarks (Fallback)
            pricing_df["provider_prefix"] = pricing_df["model_id"].apply(lambda x: str(x).split("/")[0] if "/" in str(x) else "Others")
            prov_benchmarks = pricing_df[pricing_df["avg_p"] > 0].groupby("provider_prefix")["avg_p"].median().to_dict()
            global_avg_p = pricing_df[pricing_df["avg_p"] > 0]["avg_p"].median()
            
            # 4. Tier 1: Precise Model Summation
            macro_dedup = macro_df.drop_duplicates(subset=["usage_week", "entity_id"])
            macro_dedup["fuzzy_id"] = macro_dedup["entity_id"].apply(_fuzzy_normalize_model_id)
            
            def get_precise_p(row):
                 fuzzy_id = row.get("fuzzy_id")
                 if fuzzy_id in fuzzy_prices:
                     return fuzzy_prices[fuzzy_id]
                 
                 parent_id = row.get("parent_entity_id")
                 fallback_key = str(parent_id) if pd.notna(parent_id) else ""
                 return prov_benchmarks.get(fallback_key, global_avg_p)
            
            macro_dedup["model_price"] = macro_dedup.apply(get_precise_p, axis=1)
            macro_dedup["revenue_usd"] = macro_dedup["metric_value"] * macro_dedup["model_price"]
            
            # Aggregated Tier 1 (Week, Provider)
            tier1_agg = macro_dedup.groupby(["usage_week", "parent_entity_id"]).agg({
                "metric_value": "sum",
                "revenue_usd": "sum"
            }).reset_index()
            
            # 5. Tier 2: Market Share Top-Up
            share_dedup = share_df.drop_duplicates(subset=["usage_week", "entity_id"])
            
            # Join T1 to Share
            combined = share_dedup.merge(
                tier1_agg, 
                left_on=["usage_week", "entity_id"], 
                right_on=["usage_week", "parent_entity_id"],
                how="left"
            ).fillna(0)
            
            def calculate_hybrid_rev(row):
                total_share_tokens = float(row["metric_value_x"])
                tier1_tokens = float(row["metric_value_y"])
                tier1_rev = float(row["revenue_usd"])
                
                # Delta tokens not captured in Tier 1
                delta_tokens = max(0, total_share_tokens - tier1_tokens)
                
                # Pricing for the delta: Use a 'Representativeness Guard'
                prov_id = str(row["entity_id"]).lower()
                prov_median = prov_benchmarks.get(prov_id, global_avg_p)

                if tier1_tokens > 0:
                    vwap = tier1_rev / tier1_tokens
                    # Rule: If Tier 1 is very cheap (e.g. GPT-OSS), use the provider median for the delta.
                    # If Tier 1 is premium (e.g. Opus), use the premium VWAP for the delta.
                    delta_p = max(vwap, prov_median)
                else:
                    delta_p = prov_median
                
                return tier1_rev + (delta_tokens * delta_p)
            
            combined["final_revenue"] = combined.apply(calculate_hybrid_rev, axis=1)
            
            # Formatting and Pivoting
            combined["usage_date_dt"] = pd.to_datetime(combined["usage_week"])
            combined["usage_month"] = combined["usage_date_dt"].dt.strftime('%Y-%m')
            combined["provider_label"] = combined["entity_id"].apply(lambda x: _derive_provider_name(f"{x}/model", None))
            
            pivot_rev_weekly = (
                combined.pivot_table(index="usage_week", columns="provider_label", values="final_revenue", aggfunc="sum")
                .fillna(0).sort_index()
            )
            
            # --- Gap-Fill Interpolation ---
            # OpenRouter's Market Share chart is hard-capped at Top 9 + 'Others'.
            # When a priority provider drops below rank 9, their revenue is 0.
            # We fill these gaps with linear interpolation (max 4 consecutive weeks).
            # Non-Big-Tech providers are NOT interpolated to avoid phantom noise.
            BIG_TECH_DISPLAY = [
                "OpenAI", "Anthropic", "Google", "Meta (Llama)", "DeepSeek",
                "Alibaba (Qwen)", "智谱AI (Z.ai)", "Moonshot AI", "xAI (Grok)",
                "Mistral AI", "Microsoft",
            ]
            for col in BIG_TECH_DISPLAY:
                if col in pivot_rev_weekly.columns:
                    # Replace zeros with NaN so interpolate can bridge them
                    s = pivot_rev_weekly[col].replace(0, float('nan'))
                    # Interpolate only interior gaps (not leading/trailing NaN)
                    s = s.interpolate(method='linear', limit=4, limit_area='inside')
                    pivot_rev_weekly[col] = s.fillna(0)
            
            pivot_rev_monthly = (
                combined.pivot_table(index="usage_month", columns="provider_label", values="final_revenue", aggfunc="sum")
                .fillna(0).sort_index()
            )
            # Same interpolation for monthly (max 2 month gap)
            for col in BIG_TECH_DISPLAY:
                if col in pivot_rev_monthly.columns:
                    s = pivot_rev_monthly[col].replace(0, float('nan'))
                    s = s.interpolate(method='linear', limit=2, limit_area='inside')
                    pivot_rev_monthly[col] = s.fillna(0)
        
        # Fallback if both datasets are empty
        if pivot_rev_weekly.empty and not merged_daily.empty:
            pivot_rev_weekly = merged_daily.pivot_table(index="usage_week", columns="provider_label", values="revenue_usd", aggfunc="sum").fillna(0).sort_index()
        if pivot_rev_monthly.empty and not merged_daily.empty:
            pivot_rev_monthly = merged_daily.pivot_table(index="usage_month", columns="provider_label", values="revenue_usd", aggfunc="sum").fillna(0).sort_index()
        
        views["revenue_estimator"] = {
            "pivot_rev": pivot_rev_daily,
            "pivot_rev_daily": pivot_rev_daily,
            "pivot_rev_weekly": pivot_rev_weekly,
            "pivot_rev_monthly": pivot_rev_monthly,
            "total_revenue": merged_daily["revenue_usd"].sum() if not merged_daily.empty else 0,
            "has_activity": not activity.empty,
            "merged_count": len(merged_daily) if not merged_daily.empty else 0
        }
    else:
        views["revenue_estimator"] = {
            "pivot_rev": pd.DataFrame(), 
            "total_revenue": 0,
            "has_activity": activity_res and not activity_res.frame.empty if activity_res else False,
            "merged_count": 0
        }

    return views


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

    pypi_result = datasets.get("pypi_downloads_daily")
    npm_result = datasets.get("npm_downloads_daily")
    hf_result = datasets.get("huggingface_models_daily")

    pypi = pypi_result.frame.copy() if pypi_result and pypi_result.frame is not None else pd.DataFrame()
    pypi = pypi[pypi["with_mirrors"] == False].copy() if not pypi.empty else pypi
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

    github_candidates_result = datasets.get("github_repo_candidates_daily")
    github_rollup_result = datasets.get("github_repo_rollup_daily")
    github_signals_result = datasets.get("github_provider_signals_daily")
    github_candidates = github_candidates_result.frame.copy() if github_candidates_result and github_candidates_result.frame is not None else pd.DataFrame()
    github_rollup = github_rollup_result.frame.copy() if github_rollup_result and github_rollup_result.frame is not None else pd.DataFrame()
    github_signals = github_signals_result.frame.copy() if github_signals_result and github_signals_result.frame is not None else pd.DataFrame()

    if not github_candidates.empty and provider_order:
        github_candidates = github_candidates[github_candidates["provider_display_name"].isin(provider_order)].copy()
        github_candidates["repo_created_date"] = github_candidates["repo_created_date"].astype(str)
    if not github_rollup.empty and provider_order:
        github_rollup = github_rollup[github_rollup["provider_display_name"].isin(provider_order)].copy()
        github_rollup["signal_date"] = github_rollup["signal_date"].astype(str)
    if not github_signals.empty and provider_order:
        github_signals = github_signals[github_signals["provider_display_name"].isin(provider_order)].copy()
        github_signals["signal_date"] = github_signals["signal_date"].astype(str)

    latest_github_date = github_candidates["repo_created_date"].max() if not github_candidates.empty else None

    views["github_candidates"] = github_candidates
    views["github_rollup"] = github_rollup
    views["github_signals"] = github_signals
    views["latest_github_date"] = latest_github_date

    if not github_candidates.empty:
        candidates_daily = (
            github_candidates.groupby(["repo_created_date", "provider_display_name"], dropna=False)["repo_full_name"]
            .nunique()
            .reset_index(name="repo_candidates")
        )
    else:
        candidates_daily = pd.DataFrame(columns=["repo_created_date", "provider_display_name", "repo_candidates"])

    if not github_rollup.empty:
        rollup_daily = (
            github_rollup.groupby(["signal_date", "provider_display_name"], dropna=False)
            .agg(
                signal_repos=("repo_full_name", "nunique"),
                manifest_repos=("has_manifest_dependency", "sum"),
                import_repos=("has_code_import", "sum"),
                env_repos=("has_env_var", "sum"),
                model_repos=("has_model_name", "sum"),
            )
            .reset_index()
        )
    else:
        rollup_daily = pd.DataFrame(
            columns=["signal_date", "provider_display_name", "signal_repos", "manifest_repos", "import_repos", "env_repos", "model_repos"]
        )

    views["candidates_daily"] = candidates_daily
    views["rollup_daily"] = rollup_daily
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


@st.cache_data(ttl=3600)
def compute_semiconductor_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    views: dict[str, object] = {}
    
    regime_result = datasets.get("semiconductor_memory_regime_monthly")
    images_result = datasets.get("adata_marketwatch_images")
    
    regime_df = regime_result.frame.copy() if regime_result and not regime_result.frame.empty else pd.DataFrame()
    images_df = images_result.frame.copy() if images_result and not images_result.frame.empty else pd.DataFrame()
    
    if not regime_df.empty:
        regime_df["month"] = regime_df["month"].astype(str)
        regime_df = regime_df.sort_values("month")
        
        # Simple extraction of Hynix/Micron counts if not already present or for focus
        # In reality the DatasetRecord might already have some of this, but let's ensure focus
        if "raw_text" in regime_df.columns:
            regime_df["hynix_mentions"] = regime_df["raw_text"].str.count("Hynix").fillna(0)
            regime_df["micron_mentions"] = regime_df["raw_text"].str.count("Micron").fillna(0)
        else:
            regime_df["hynix_mentions"] = 0
            regime_df["micron_mentions"] = 0

        latest_month = regime_df["month"].max()
        latest_data = regime_df[regime_df["month"] == latest_month].iloc[0]
    else:
        latest_month = None
        latest_data = pd.Series()
        
    views["regime_df"] = regime_df
    views["latest_month"] = latest_month
    views["latest_data"] = latest_data
    
    if not images_df.empty:
        images_df["month"] = images_df["month"].astype(str)
        
    views["images_df"] = images_df
    
    return views


@st.cache_data(ttl=3600)
def compute_compute_availability_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    views: dict[str, object] = {}

    # 1. AWS Spot Prices
    spot_result = datasets.get("raw_aws_spot_price_history")
    if spot_result and not spot_result.frame.empty:
        df = spot_result.frame.copy()
        df["price_timestamp"] = pd.to_datetime(df["price_timestamp"], errors="coerce")
        df = df.sort_values("price_timestamp")
        views["spot_df"] = df
    else:
        views["spot_df"] = pd.DataFrame()

    # 2. Lambda Inventory
    lambda_result = datasets.get("raw_lambda_instance_types")
    if lambda_result and not lambda_result.frame.empty:
        df = lambda_result.frame.copy()
        df["snapshot_ts"] = pd.to_datetime(df["snapshot_ts"], errors="coerce")
        latest_ts = df["snapshot_ts"].max()
        views["lambda_latest"] = df[df["snapshot_ts"] == latest_ts].copy()
    else:
        views["lambda_latest"] = pd.DataFrame()

    # 3. OpenRouter Models (Growth & Pricing)
    models_result = datasets.get("raw_openrouter_models")
    if models_result and not models_result.frame.empty:
        df = models_result.frame.copy()
        df["snapshot_ts"] = pd.to_datetime(df["snapshot_ts"], errors="coerce")
        latest_ts = df["snapshot_ts"].max()
        views["models_latest"] = df[df["snapshot_ts"] == latest_ts].copy()
        
        # Historical growth
        growth = df.groupby("snapshot_ts")["model_id"].nunique().reset_index().rename(columns={"model_id": "model_count"})
        views["models_growth"] = growth
    else:
        views["models_latest"] = pd.DataFrame()
        views["models_growth"] = pd.DataFrame()

    return views


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def inject_css() -> None:
    st.markdown(
        f"""
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
        """,
        unsafe_allow_html=True,
    )


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
        delta_cls  = "kpi-delta-up" if wow_pct >= 0 else "kpi-delta-down"
        delta_icon = "↑" if wow_pct >= 0 else "↓"
        delta_html = f'<div class="{delta_cls}">{delta_icon} {abs(wow_pct):.1f}% WoW</div>'
    else:
        delta_html = f'<div class="kpi-delta-flat">—</div>'

    tokens_fmt   = format_metric(total_latest) if total_latest is not None else "—"
    leader_label = f"{leader_author} ({leader_pct:.1f}%)" if leader_author and leader_pct else leader_author or "—"
    model_label  = top_model or "—"
    # truncate long model names
    if len(model_label) > 28:
        model_label = model_label[:26] + "…"

    st.markdown(
        f"""
        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-label">Total Tokens (Latest Model Week)</div>
            <div class="kpi-value">{tokens_fmt}</div>
            {delta_html}
          </div>
          <div class="kpi-card">
            <div class="kpi-label">WoW Change</div>
            <div class="kpi-value">{"+" if wow_pct and wow_pct >= 0 else ""}{f"{wow_pct:.1f}%" if wow_pct is not None else "—"}</div>
            <div class="kpi-delta-flat">vs prior week</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Top Model</div>
            <div class="kpi-value" style="font-size:1.1rem;">{model_label}</div>
            <div class="kpi-delta-flat">by tokens this week</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Market Leader</div>
            <div class="kpi-value" style="font-size:1.1rem;">{leader_label}</div>
            <div class="kpi-delta-flat">latest market-share week</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    warning = rankings_bucket_warning(week_context)
    if warning:
        st.markdown(f'<div class="rankings-warning">{warning}</div>', unsafe_allow_html=True)


def render_rankings_semantics_note(datasets: dict[str, DatasetLoadResult]) -> None:
    context = rankings_week_context(datasets)
    model_week = context["model_week"] or "n/a"
    programming_week = context["programming_week"] or model_week
    market_share_week = context["market_share_week"] or "n/a"

    st.markdown(
        f"""
        <div class="rankings-note">
          <strong>OpenRouter week semantics</strong><br>
          Top Models and Programming are grouped by <strong>week starting</strong> dates.
          Market Share is grouped by <strong>week ending</strong> dates.
          These latest completed buckets can differ by up to 6 days on the same scrape.<br><br>
          <span style="color:{MUTED};">
            Latest completed model week: {model_week} ·
            Latest completed programming week: {programming_week} ·
            Latest completed market-share week: {market_share_week}
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_top_models_chart(datasets: dict[str, DatasetLoadResult], openrouter_views: dict[str, object]) -> None:
    st.markdown('<div class="section-title">Top Models — Weekly Token Usage (Week Starting)</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="section-subtitle">Completed weekly buckets aligned to week start dates from OpenRouter rankings.</div>',
        unsafe_allow_html=True,
    )
    result = datasets.get("top_models")
    if not result or not render_dataset_guard(result):
        return

    tm = result.frame.copy()
    tm["week_start_date"] = tm["week_start_date"].astype(str)
    st.markdown(
        f'<div class="status-caption">Latest completed model week: {result.latest_date or "n/a"} · Scraped: {format_scraped_at_display(result.latest_scraped_at)}</div>',
        unsafe_allow_html=True,
    )
    
    # --- Period Selector & Total ---
    weeks = openrouter_views["top_models"]["weeks"]
    sel_week = st.selectbox("Analyze week starting", options=weeks, index=0, key="tm_week_sel")
    week_total = tm[tm["week_start_date"] == sel_week]["metric_value"].sum()
    st.markdown(
        f'<div class="kpi-card" style="margin-bottom:1rem; max-width: 300px;">'
        f'<div class="kpi-label">Total Tokens ({sel_week})</div>'
        f'<div class="kpi-value" style="font-size: 1.5rem;">{format_metric(week_total)}</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    fig = make_stacked_bar(openrouter_views["top_models"]["pivot_top"], MODEL_COLORS, y_title="Tokens")
    st.plotly_chart(fig, use_container_width=True, theme=None)


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
        f'<div class="kpi-card" style="margin-bottom:1rem; max-width: 300px;">'
        f'<div class="kpi-label">Total Tokens ({sel_ms_wk})</div>'
        f'<div class="kpi-value" style="font-size: 1.5rem;">{format_metric(ms_wk_total)}</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    chart_col, legend_col = st.columns([2, 1], gap="large")

    with chart_col:
        fig = make_stacked_bar(openrouter_views["market_share"]["pivot_pct_top"], MODEL_COLORS, y_title="Share (%)", pct=True)
        fig.update_yaxes(range=[0, 100])
        st.plotly_chart(fig, use_container_width=True, theme=None)

    with legend_col:
        ms_latest  = ms[ms["week_start_date"] == sel_ms_wk].groupby("entity_id", as_index=False)["metric_value"].sum()
        wk_total   = ms_latest["metric_value"].sum()
        ms_named   = ms_latest[ms_latest["entity_id"].str.lower() != "others"].sort_values("metric_value", ascending=False)
        cum_total  = ms[ms["entity_id"].str.lower() != "others"].groupby("entity_id")["metric_value"].sum()

        st.markdown(f'<div style="font-weight:700;font-size:1rem;margin-bottom:0.8rem;">Week: {sel_ms_wk} Leaders</div>', unsafe_allow_html=True)
        rows_html = '<div class="ms-legend">'
        for rank_i, (_, row) in enumerate(ms_named.head(8).iterrows()):
            color  = MODEL_COLORS[rank_i % len(MODEL_COLORS)]
            author = row["entity_id"]
            pct_v  = row["metric_value"] / wk_total * 100 if wk_total > 0 else 0
            cum_v  = format_metric(cum_total.get(author, 0))
            rows_html += f"""
            <div class="ms-row">
              <span style="color:{MUTED};font-size:0.72rem;min-width:16px;">{rank_i+1}</span>
              <span class="ms-dot" style="background:{color};"></span>
              <span class="ms-name">{author}</span>
              <span class="ms-tokens">{cum_v}</span>
              <span class="ms-pct">{pct_v:.1f}%</span>
            </div>"""
        rows_html += "</div>"
        st.markdown(rows_html, unsafe_allow_html=True)

    st.markdown("---")


def render_revenue_estimator(datasets: dict[str, DatasetLoadResult], openrouter_views: dict[str, object]) -> None:
    rev_data = openrouter_views.get("revenue_estimator", {})
    pivot_rev = rev_data.get("pivot_rev", pd.DataFrame())
    total_revenue = rev_data.get("total_revenue", 0)

    st.markdown('<div class="section-title">Provider Revenue Estimator (Experimental)</div>', unsafe_allow_html=True)
    
    if pivot_rev.empty:
        if rev_data.get("has_activity"):
            st.warning("Granular activity data exists, but no pricing metadata matched these models. Check if pricing snapshots are up to date.")
        else:
            st.info("No granular activity data available for revenue estimation. Run 'activity-daily-update' to populate.")
        return

    # Total Revenue Metric
    st.markdown(
        f"""
        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-label">Est. Aggregate Revenue</div>
            <div class="kpi-value">${total_revenue:,.0f}</div>
            <div class="kpi-delta-up">↑ Based on Top 50 Models</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Provider Coverage</div>
            <div class="kpi-value">{len(pivot_rev.columns)}</div>
            <div class="kpi-delta-flat">active providers</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="section-subtitle">Estimated Revenue by Provider (USD)</div>', unsafe_allow_html=True)
    
    pivot_monthly = rev_data.get("pivot_rev_monthly", pd.DataFrame())
    pivot_weekly  = rev_data.get("pivot_rev_weekly", pd.DataFrame())
    pivot_daily   = rev_data.get("pivot_rev_daily", pd.DataFrame())

    tab_month, tab_week, tab_day = st.tabs(["Monthly", "Weekly", "Daily"])
    
    def _render_rev_chart(pivot_df, date_title):
        if pivot_df.empty:
            st.info(f"No {date_title.lower()} data available.")
            return
        fig = go.Figure()
        for i, provider_name in enumerate(pivot_df.columns):
            fig.add_trace(
                go.Scatter(
                    x=pivot_df.index,
                    y=pivot_df[provider_name],
                    name=provider_name,
                    mode="lines+markers",
                    stackgroup="one",
                    line=dict(width=0.5, color=MODEL_COLORS[i % len(MODEL_COLORS)]),
                    hovertemplate=f"<b>{provider_name}</b><br>%{{x}}<br>$%{{y:,.2f}}<extra></extra>",
                )
            )
        fig.update_layout(
            template="plotly_white",
            xaxis_title=date_title,
            yaxis_title="Revenue (USD)",
            legend=dict(orientation="h", y=-0.2),
            height=400,
            margin=dict(l=0, r=0, t=20, b=80),
        )
        st.plotly_chart(fig, use_container_width=True, theme=None)

    with tab_month:
        _render_rev_chart(pivot_monthly, "Usage Month")
    with tab_week:
        _render_rev_chart(pivot_weekly, "Usage Week (Starting)")
    with tab_day:
        _render_rev_chart(pivot_daily, "Usage Date")
        
    st.caption(
        "Note: Revenue is estimated via a Hybrid Smart-Scaling model (Tier 1: precise model-level pricing via fuzzy matching; "
        "Tier 2: market-share top-up for long-tail volume). "
        "⚠️ OpenRouter's Market Share chart is platform-capped at Top 9 providers per week. "
        "When a major provider falls outside the Top 9, their weekly revenue is estimated via linear interpolation "
        "between observed data points (max 4-week gap). Interpolated periods may be less accurate. "
        "Actual payouts may vary. Daily chart: micro-logs (6 weeks). Weekly/Monthly: macro-market share (12 months)."
    )
    st.markdown("---")


def render_leaderboard(datasets: dict[str, DatasetLoadResult]) -> None:
    st.markdown('<div class="section-title">Model Leaderboard</div>', unsafe_allow_html=True)
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


def render_programming_chart(datasets: dict[str, DatasetLoadResult], openrouter_views: dict[str, object]) -> None:
    st.markdown('<div class="section-title">Programming — Weekly Token Usage (Week Starting)</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Coding-only weekly rankings from OpenRouter, aligned to week start dates.</div>',
        unsafe_allow_html=True,
    )
    result = datasets.get("categories_programming")
    if not result or not render_dataset_guard(result):
        return

    frame = result.frame.copy()
    frame["week_start_date"] = frame["week_start_date"].astype(str)
    st.markdown(
        f'<div class="status-caption">Latest completed programming week: {result.latest_date or "n/a"} · Scraped: {format_scraped_at_display(result.latest_scraped_at)}</div>',
        unsafe_allow_html=True,
    )

    weeks = openrouter_views["categories_programming"]["weeks"]
    sel_week = st.selectbox("Analyze programming week starting", options=weeks, index=0, key="prog_week_sel")
    week_total = frame[frame["week_start_date"] == sel_week]["metric_value"].sum()
    st.markdown(
        f'<div class="kpi-card" style="margin-bottom:1rem; max-width: 300px;">'
        f'<div class="kpi-label">Programming Tokens ({sel_week})</div>'
        f'<div class="kpi-value" style="font-size: 1.5rem;">{format_metric(week_total)}</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    fig = make_stacked_bar(openrouter_views["categories_programming"]["pivot_top"], MODEL_COLORS, y_title="Tokens")
    st.plotly_chart(fig, use_container_width=True, theme=None)


def render_app_usage_chart(datasets: dict[str, DatasetLoadResult], openrouter_views: dict[str, object]) -> None:
    st.markdown('<div class="section-title">App Intelligence — Model Usage Snapshots</div>', unsafe_allow_html=True)

    # prefer app_top_models_daily_snapshot, fall back to app_usage_daily
    result = datasets.get("app_top_models_daily_snapshot")
    is_wtd = True
    if not result or result.frame.empty:
        result = datasets.get("app_usage_daily")
        is_wtd = False

    if not result or not render_dataset_guard(result):
        return

    frame = result.frame.copy()

    date_col = openrouter_views["app_usage"]["date_col"]
    val_col = openrouter_views["app_usage"]["value_col"]

    frame[date_col] = frame[date_col].astype(str)

    # --- Period Selector & Total ---
    days = openrouter_views["app_usage"]["days"]
    sel_day = st.selectbox("Analyze day", options=days, index=0, key="app_day_sel")
    day_total = frame[frame[date_col] == sel_day][val_col].sum()
    
    label = f"Running Week Total (as of {sel_day})" if is_wtd else f"Total Daily Tokens ({sel_day})"
    st.markdown(
        f'<div class="kpi-card" style="margin-bottom:1rem; max-width: 350px;">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value" style="font-size: 1.5rem;">{format_metric(day_total)}</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    fig = make_stacked_bar(openrouter_views["app_usage"]["pivot_top"], MODEL_COLORS, y_title="Tokens", height=340)
    st.plotly_chart(fig, use_container_width=True, theme=None)
    
    if is_wtd:
        st.caption("*Note: Snapshot totals represent cumulative usage for the current week (Week-to-Date) as reported at the time of the crawl.*")


def render_apps_tables(datasets: dict[str, DatasetLoadResult]) -> None:
    st.markdown('<div class="section-title">App Rankings & Trends</div>', unsafe_allow_html=True)

    tabs = st.tabs(["Global Rankings", "Trending Apps", "Monitored Apps"])

    with tabs[0]:
        result = datasets.get("apps_global_ranking_snapshots")
        if result and render_dataset_guard(result):
            frame = result.frame.copy()
            periods = sorted(frame["period"].dropna().astype(str).unique().tolist())
            period  = st.selectbox("Period", options=periods, index=0 if periods else None, key="lb_period")
            if period:
                frame = frame[frame["period"] == period]
            latest_date = frame["snapshot_date"].max()
            latest = frame[frame["snapshot_date"] == latest_date].sort_values("rank").head(25)
            tbl = latest[["rank", "app_name", "categories", "tokens"]].copy()
            total_top25 = tbl["tokens"].sum()
            
            summary_col, _ = st.columns([1, 2])
            with summary_col:
                st.markdown(
                    f'<div class="kpi-card" style="margin-bottom:1rem;">'
                    f'<div class="kpi-label">Tokens in Top 25 ({latest_date})</div>'
                    f'<div class="kpi-value" style="font-size: 1.5rem;">{format_metric(total_top25)}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                
            tbl["tokens"] = tbl["tokens"].map(format_metric)
            st.dataframe(tbl.fillna(""), use_container_width=True, hide_index=True)

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
            st.dataframe(tbl.fillna(""), use_container_width=True, hide_index=True)

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
                latest_meta[["app_name", "app_id", "origin_url", "categories", "description"]].fillna(""),
                use_container_width=True,
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
                    f'<div class="kpi-card" style="margin-bottom:1rem; max-width: 300px;">'
                    f'<div class="kpi-label">Cumulative Selection Usage</div>'
                    f'<div class="kpi-value" style="font-size: 1.5rem;">{format_metric(app_total)}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                
                pivot_u = (
                    usage.pivot_table(index="usage_date", columns="model_permaslug", values="total_tokens", aggfunc="sum")
                    .fillna(0)
                    .sort_index()
                )
                top_m = pivot_u.sum().nlargest(15).index.tolist()
                pivot_u = pivot_u[top_m]
                fig_u = make_stacked_bar(pivot_u, MODEL_COLORS, y_title="Tokens", height=300)
                st.plotly_chart(fig_u, use_container_width=True, theme=None)


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
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Top Gainer ({period_label})</div>'
            f'<div class="kpi-value" style="font-size: 1.3rem;">{top_repo["name"] if top_repo is not None else "—"}</div>'
            f'<div class="kpi-delta-up">+{format_metric(top_repo["stars_today"]) if top_repo is not None else "0"} stars</div>'
            f'</div>',
            unsafe_allow_html=True
        )
    with col2:
        total_gained = latest_df["stars_today"].sum()
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Total Stars Gained (Top 15)</div>'
            f'<div class="kpi-value">{format_metric(total_gained)}</div>'
            f'<div class="kpi-delta-flat">across trending list</div>'
            f'</div>',
            unsafe_allow_html=True
        )
    with col3:
        unique_repos = df["name"].nunique()
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Unique Repos Tracked</div>'
            f'<div class="kpi-value">{unique_repos}</div>'
            f'<div class="kpi-delta-flat">in history</div>'
            f'</div>',
            unsafe_allow_html=True
        )

    # --- Charts & Leaderboard ---
    chart_tab, list_tab = st.tabs(["Historical Growth", "Latest Leaderboard"])

    with chart_tab:
        # Plot top 5 growth over time
        pivot_h = period_view["history_top5"]
        if not pivot_h.empty:
            fig = go.Figure()
            for i, repo_name in enumerate(pivot_h.columns):
                fig.add_trace(go.Scatter(
                    x=pivot_h.index,
                    y=pivot_h[repo_name],
                    name=repo_name,
                    mode='lines+markers',
                    line=dict(width=3, color=MODEL_COLORS[i % len(MODEL_COLORS)]),
                    hovertemplate=f"<b>{repo_name}</b><br>%{{x}}<br>%{{y:,.0f}} stars gained<extra></extra>"
                ))
            
            fig.update_layout(
                template="plotly_white",
                title=f"Star Growth - Top 5 {period_label} Repos",
                xaxis_title="Scrape Date",
                yaxis_title="Stars Gained",
                legend=dict(orientation="h", y=-0.2),
                height=400,
                margin=dict(l=0, r=0, t=40, b=80)
            )
            st.plotly_chart(fig, use_container_width=True)
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
    github_candidates_result = datasets.get("github_repo_candidates_daily")
    github_rollup_result = datasets.get("github_repo_rollup_daily")
    github_signals_result = datasets.get("github_provider_signals_daily")

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

    github_candidates = provider_views["github_candidates"]
    github_rollup = provider_views["github_rollup"]
    github_signals = provider_views["github_signals"]
    latest_github_date = provider_views["latest_github_date"]
    latest_hf_date = provider_views["latest_hf_date"]
    latest_hf = provider_views["latest_hf"]
    hf_grouped = provider_views["hf_grouped"]
    latest_hf_models = provider_views["latest_hf_models"]

    top_download_row = latest_pypi.sort_values("downloads", ascending=False).iloc[0] if not latest_pypi.empty else None
    total_latest_downloads = latest_pypi["downloads"].sum() if not latest_pypi.empty else 0
    latest_candidate_count = (
        github_candidates[github_candidates["repo_created_date"] == latest_github_date]["repo_full_name"].nunique()
        if latest_github_date and not github_candidates.empty
        else 0
    )
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
            f'<div class="kpi-label">Latest GH Candidates</div>'
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

    hf_downloads_tab, hf_share_tab, hf_models_tab, pypi_downloads_tab, pypi_share_tab, npm_downloads_tab, npm_share_tab, github_tab, summary_tab = st.tabs(
        ["HF Downloads", "HF Share", "HF Models", "PyPI Downloads", "PyPI Share", "npm Downloads", "npm Share", "GitHub Signals", "Latest Summary"]
    )

    hf_metric = st.segmented_control(
        "Hugging Face metric",
        options=["Trailing 30d", "All-time"],
        default="Trailing 30d",
        key="provider_adoption_hf_metric",
    )
    hf_metric_config = resolve_hf_metric_config(hf_metric)

    with hf_downloads_tab:
        if hf_result is None or hf_result.frame.empty or hf_grouped.empty:
            st.info("No Hugging Face model data available yet.")
        else:
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
            fig = go.Figure()
            for i, provider_name in enumerate(pivot_hf.columns):
                fig.add_trace(
                    go.Scatter(
                        x=pivot_hf.index,
                        y=pivot_hf[provider_name],
                        name=provider_name,
                        mode="lines+markers",
                        line=dict(width=3, color=MODEL_COLORS[i % len(MODEL_COLORS)]),
                        hovertemplate=f"<b>{provider_name}</b><br>%{{x}}<br>%{{y:,.0f}} {hf_metric_config['downloads_hover']}<extra></extra>",
                    )
                )
            fig.update_layout(
                template="plotly_white",
                title=hf_metric_config["downloads_title"],
                xaxis_title="Date",
                yaxis_title=hf_metric_config["downloads_axis"],
                legend=dict(orientation="h", y=-0.2),
                height=360,
                margin=dict(l=0, r=0, t=40, b=80),
            )
            st.plotly_chart(fig, use_container_width=True, theme=None)

    with hf_share_tab:
        if hf_result is None or hf_result.frame.empty or hf_grouped.empty:
            st.info("No Hugging Face model data available yet.")
        else:
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
                make_stacked_bar(
                    pivot_share * 100,
                    MODEL_COLORS,
                    title=hf_metric_config["share_title"],
                    y_title="Share",
                    pct=True,
                    height=340,
                ),
                use_container_width=True,
                theme=None,
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
                    limit=20,
                )
                st.caption(f"Showing top 20 models for {selected_hf_provider} by trailing 30d downloads.")
                st.dataframe(table.fillna("-"), use_container_width=True, hide_index=True)

    with pypi_downloads_tab:
        pivot_downloads = (
            pypi_grouped.pivot_table(index="download_date", columns="provider_display_name", values="downloads", aggfunc="last")
            .fillna(0)
            .sort_index()
        )
        fig = go.Figure()
        for i, provider_name in enumerate(pivot_downloads.columns):
            fig.add_trace(
                go.Scatter(
                    x=pivot_downloads.index,
                    y=pivot_downloads[provider_name],
                    name=provider_name,
                    mode="lines+markers",
                    line=dict(width=3, color=MODEL_COLORS[i % len(MODEL_COLORS)]),
                    hovertemplate=f"<b>{provider_name}</b><br>%{{x}}<br>%{{y:,.0f}} downloads<extra></extra>",
                )
            )
        fig.update_layout(
            template="plotly_white",
            title="PyPI Daily Download History (Without Mirrors)",
            xaxis_title="Date",
            yaxis_title="Downloads",
            legend=dict(orientation="h", y=-0.2),
            height=360,
            margin=dict(l=0, r=0, t=40, b=80),
        )
        st.plotly_chart(fig, use_container_width=True, theme=None)

    with pypi_share_tab:
        totals = pypi_grouped.groupby("download_date")["downloads"].sum().rename("total").reset_index()
        share = pypi_grouped.merge(totals, on="download_date", how="left")
        share["share"] = share["downloads"] / share["total"].where(share["total"] != 0)
        pivot_share = (
            share.pivot_table(index="download_date", columns="provider_display_name", values="share", aggfunc="last")
            .fillna(0)
            .sort_index()
        )
        st.plotly_chart(
            make_stacked_bar(
                pivot_share * 100,
                MODEL_COLORS,
                title="PyPI Daily Download Share (Without Mirrors)",
                y_title="Share",
                pct=True,
                height=340,
            ),
            use_container_width=True,
            theme=None,
        )

    with npm_downloads_tab:
        if npm_result is None or npm_result.frame.empty or npm_grouped.empty:
            st.info("No npm provider data available yet.")
        else:
            pivot_downloads = (
                npm_grouped.pivot_table(index="download_date", columns="provider_display_name", values="downloads", aggfunc="last")
                .fillna(0)
                .sort_index()
            )
            fig = go.Figure()
            for i, provider_name in enumerate(pivot_downloads.columns):
                fig.add_trace(
                    go.Scatter(
                        x=pivot_downloads.index,
                        y=pivot_downloads[provider_name],
                        name=provider_name,
                        mode="lines+markers",
                        line=dict(width=3, color=MODEL_COLORS[i % len(MODEL_COLORS)]),
                        hovertemplate=f"<b>{provider_name}</b><br>%{{x}}<br>%{{y:,.0f}} downloads<extra></extra>",
                    )
                )
            fig.update_layout(
                template="plotly_white",
                title=f"{NPM_CATEGORY_LABELS.get(selected_npm_category, selected_npm_category)} npm Daily Download History",
                xaxis_title="Date",
                yaxis_title="Downloads",
                legend=dict(orientation="h", y=-0.2),
                height=360,
                margin=dict(l=0, r=0, t=40, b=80),
            )
            st.plotly_chart(fig, use_container_width=True, theme=None)

    with npm_share_tab:
        if npm_result is None or npm_result.frame.empty or npm_grouped.empty:
            st.info("No npm provider data available yet.")
        else:
            totals = npm_grouped.groupby("download_date")["downloads"].sum().rename("total").reset_index()
            share = npm_grouped.merge(totals, on="download_date", how="left")
            share["share"] = share["downloads"] / share["total"].where(share["total"] != 0)
            pivot_share = (
                share.pivot_table(index="download_date", columns="provider_display_name", values="share", aggfunc="last")
                .fillna(0)
                .sort_index()
            )
            st.plotly_chart(
                make_stacked_bar(
                    pivot_share * 100,
                    MODEL_COLORS,
                    title=f"{NPM_CATEGORY_LABELS.get(selected_npm_category, selected_npm_category)} npm Daily Download Share",
                    y_title="Share",
                    pct=True,
                    height=340,
                ),
                use_container_width=True,
                theme=None,
            )

    with github_tab:
        if github_candidates.empty or github_rollup.empty:
            st.info("No GitHub provider signal data available yet.")
        else:
            candidates_daily = provider_views["candidates_daily"]
            rollup_daily = provider_views["rollup_daily"]

            col_left, col_right = st.columns(2)
            with col_left:
                pivot_candidates = (
                    candidates_daily.pivot_table(
                        index="repo_created_date",
                        columns="provider_display_name",
                        values="repo_candidates",
                        aggfunc="last",
                    )
                    .fillna(0)
                    .sort_index()
                )
                fig_candidates = go.Figure()
                for i, provider_name in enumerate(pivot_candidates.columns):
                    fig_candidates.add_trace(
                        go.Scatter(
                            x=pivot_candidates.index,
                            y=pivot_candidates[provider_name],
                            name=provider_name,
                            mode="lines+markers",
                            line=dict(width=3, color=MODEL_COLORS[i % len(MODEL_COLORS)]),
                            hovertemplate=f"<b>{provider_name}</b><br>%{{x}}<br>%{{y:,.0f}} repos<extra></extra>",
                        )
                    )
                fig_candidates.update_layout(
                    template="plotly_white",
                    title="GitHub New Repo Candidates by Day",
                    xaxis_title="Date",
                    yaxis_title="Repos",
                    legend=dict(orientation="h", y=-0.25),
                    height=340,
                    margin=dict(l=0, r=0, t=40, b=80),
                )
                st.plotly_chart(fig_candidates, use_container_width=True, theme=None)

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
                fig_signals = go.Figure()
                for i, provider_name in enumerate(pivot_signals.columns):
                    fig_signals.add_trace(
                        go.Scatter(
                            x=pivot_signals.index,
                            y=pivot_signals[provider_name],
                            name=provider_name,
                            mode="lines+markers",
                            line=dict(width=3, color=MODEL_COLORS[i % len(MODEL_COLORS)]),
                            hovertemplate=f"<b>{provider_name}</b><br>%{{x}}<br>%{{y:,.0f}} repos<extra></extra>",
                        )
                    )
                fig_signals.update_layout(
                    template="plotly_white",
                    title="GitHub Signal-Bearing Repos by Day",
                    xaxis_title="Date",
                    yaxis_title="Repos",
                    legend=dict(orientation="h", y=-0.25),
                    height=340,
                    margin=dict(l=0, r=0, t=40, b=80),
                )
                st.plotly_chart(fig_signals, use_container_width=True, theme=None)

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

        if latest_github_date and not github_candidates.empty:
            latest_candidates = (
                github_candidates[github_candidates["repo_created_date"] == latest_github_date]
                .groupby("provider_display_name", dropna=False)["repo_full_name"]
                .nunique()
                .rename("GH Candidates")
                .reset_index()
                .rename(columns={"provider_display_name": "Provider"})
            )
            summary = summary.merge(latest_candidates, on="Provider", how="left")

        if latest_github_date and not github_rollup.empty:
            latest_rollup = github_rollup[github_rollup["signal_date"] == latest_github_date].copy()
            rollup_summary = (
                latest_rollup.groupby("provider_display_name", dropna=False)
                .agg(
                    **{
                        "GH Signals": ("repo_full_name", "nunique"),
                        "Import Repos": ("has_code_import", "sum"),
                    }
                )
                .reset_index()
                .rename(columns={"provider_display_name": "Provider"})
            )
            summary = summary.merge(rollup_summary, on="Provider", how="left")

        # Sort: priority to HF 30d, otherwise PyPI
        sort_col = "HF 30d Downloads" if "HF 30d Downloads" in summary.columns else "Latest PyPI Downloads"
        summary = summary.sort_values(sort_col, ascending=False) if sort_col in summary.columns else summary

        display_date = latest_github_date or latest_npm_date or latest_pypi_date
        st.caption(f"Latest provider snapshot: {display_date or 'n/a'}")
        st.dataframe(summary.fillna("-"), use_container_width=True, hide_index=True)


def render_semiconductor_section(datasets: dict[str, DatasetLoadResult], semi_views: dict[str, object]) -> None:
    regime_df = semi_views.get("regime_df", pd.DataFrame())
    images_df = semi_views.get("images_df", pd.DataFrame())

    if regime_df.empty:
        st.warning("No semiconductor memory data available.")
        return

    # --- Header with Month Selector ---
    h_col1, h_col2 = st.columns([2, 1])
    with h_col1:
        st.markdown('<div class="section-title">Market Intelligence Hub</div>', unsafe_allow_html=True)
    with h_col2:
        available_months = sorted(regime_df["month"].unique(), reverse=True)
        selected_month = st.selectbox("Analysis Snapshot", available_months, index=0)

    current_data = regime_df[regime_df["month"] == selected_month].iloc[0]
    current_images = images_df[images_df["month"] == selected_month] if not images_df.empty else pd.DataFrame()

    # --- KPIs with Lag Handling ---
    ppi_val = current_data.get("fred_ppi_value")
    ppi_mom = current_data.get("fred_ppi_mom_pct")
    nand_regime = current_data.get("nand_regime_label", "n/a")
    dram_regime = current_data.get("dram_regime_label", "n/a")

    # PPI Fallback: find latest available PPI if current month is blank
    ppi_display_val = "—"
    ppi_sub_label = "report period"
    
    if pd.notna(ppi_val):
        ppi_display_val = f"{ppi_val:.1f}"
    else:
        # Search backwards for last valid PPI
        valid_ppi_df = regime_df[regime_df["month"] <= selected_month].dropna(subset=["fred_ppi_value"]).sort_values("month")
        if not valid_ppi_df.empty:
            last_record = valid_ppi_df.iloc[-1]
            ppi_display_val = f"{last_record['fred_ppi_value']:.1f}"
            ppi_sub_label = f"As of {last_record['month']}"

    delta_html = ""
    if pd.notna(ppi_mom):
        delta_cls = "kpi-delta-up" if ppi_mom >= 0 else "kpi-delta-down"
        delta_icon = "↑" if ppi_mom >= 0 else "↓"
        delta_html = f'<div class="{delta_cls}">{delta_icon} {abs(ppi_mom):.1f}% MoM</div>'
    else:
        delta_html = f'<div class="kpi-delta-flat">{ppi_sub_label}</div>'

    # Regime Styling logic — handle "LLM PENDING"
    def get_regime_style(label: str) -> str:
        label_up = str(label).upper()
        if "PENDING" in label_up:
            return 'class="regime-pending"'
        if label_up == 'SHORTAGE':
            return f'style="color:{RED};"'
        if label_up == 'OVERSUPPLY':
            return f'style="color:{GREEN};"'
        return ""

    st.markdown(
        f"""
        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-label">Month Selector</div>
            <div class="kpi-value">{selected_month}</div>
            <div class="kpi-delta-flat">active snapshot</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Semiconductor PPI</div>
            <div class="kpi-value">{ppi_display_val}</div>
            {delta_html}
          </div>
          <div class="kpi-card">
            <div class="kpi-label">NAND Regime</div>
            <div class="kpi-value regime-value" {get_regime_style(nand_regime)}>
                {nand_regime}
            </div>
            <div class="kpi-delta-flat">market condition</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">DRAM Regime</div>
            <div class="kpi-value regime-value" {get_regime_style(dram_regime)}>
                {dram_regime}
            </div>
            <div class="kpi-delta-flat">market condition</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --- Main Content ---
    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown(f'<div class="section-title">Latest Report Analysis ({selected_month})</div>', unsafe_allow_html=True)
        if not current_images.empty:
            for _, row in current_images.head(2).iterrows():
                img_path = BASE_DIR / row["local_path"]
                if img_path.exists():
                    st.image(str(img_path), caption=f"{row['image_type'].title()} - {row['month']}")
                else:
                    st.caption(f"Image not found: {row['local_path']}")
        else:
            st.info(f"No captured images available for the {selected_month} report.")

    with col2:
        st.markdown('<div class="section-title">Narrative Highlights</div>', unsafe_allow_html=True)
        st.markdown(f"**NAND Supply:** {current_data.get('narrative_nand_supply', '—')}")
        st.markdown(f"**NAND Price:** {current_data.get('narrative_nand_price', '—')}")
        st.markdown("---")
        st.markdown(f"**DRAM Supply:** {current_data.get('narrative_dram_supply', '—')}")
        st.markdown(f"**DRAM Price:** {current_data.get('narrative_dram_price', '—')}")
        
        st.markdown('<div class="section-title">Key Mentions Focus</div>', unsafe_allow_html=True)
        hynix_m = current_data.get("hynix_mentions", 0)
        micron_m = current_data.get("micron_mentions", 0)
        hbm_m = current_data.get("mentions_hbm", False)
        
        m_col1, m_col2, m_col3 = st.columns(3)
        m_col1.metric("SK Hynix", int(hynix_m))
        m_col2.metric("Micron", int(micron_m))
        m_col3.metric("HBM Mention", "Yes" if hbm_m else "No")

    # --- Archive & History ---
    hist_tab1, hist_tab2 = st.tabs(["📊 Performance Trends", "📜 Commentary Archive"])
    
    with hist_tab1:
        trend_col1, trend_col2 = st.columns(2)
        with trend_col1:
            fig_ppi = go.Figure()
            fig_ppi.add_trace(go.Scatter(
                x=regime_df["month"], y=regime_df["fred_ppi_value"],
                mode="lines+markers", name="PPI Value",
                line=dict(color=ACCENT, width=3)
            ))
            fig_ppi.update_layout(title="Semiconductor PPI Trend", template="plotly_white", height=350, margin=dict(l=0, r=0, t=40, b=10))
            st.plotly_chart(fig_ppi, use_container_width=True)

        with trend_col2:
            fig_mentions = go.Figure()
            fig_mentions.add_trace(go.Scatter(x=regime_df["month"], y=regime_df["hynix_mentions"], mode="lines", name="SK Hynix", line=dict(color="#00B5A4")))
            fig_mentions.add_trace(go.Scatter(x=regime_df["month"], y=regime_df["micron_mentions"], mode="lines", name="Micron", line=dict(color="#FF7849")))
            fig_mentions.update_layout(title="Mention Momentum", template="plotly_white", height=350, margin=dict(l=0, r=0, t=40, b=10))
            st.plotly_chart(fig_mentions, use_container_width=True)

    with hist_tab2:
        st.markdown('<div class="section-title">Monthly Narrative Comparison</div>', unsafe_allow_html=True)
        archive_df = regime_df.sort_values("month", ascending=False).head(12)[["month", "narrative_nand_supply", "narrative_dram_supply"]]
        archive_df.columns = ["Month", "NAND Supply Analysis", "DRAM Supply Analysis"]
        st.dataframe(archive_df.fillna("—"), use_container_width=True, hide_index=True)


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
        f"""
        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-label">Innovation Velocity</div>
            <div class="kpi-value">{velocity:.1f}d</div>
            <div class="kpi-delta-flat">Avg SOTA cycle</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Frontier Context Floor</div>
            <div class="kpi-value">{format_metric(range_avg_context)}</div>
            <div class="kpi-delta-up">↑ High Demand</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Peak Intelligence (GPQA)</div>
            <div class="kpi-value">{range_max_gpqa:.1%}</div>
            <div class="kpi-delta-flat">selected range</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Peak Agents (SWE-bench)</div>
            <div class="kpi-value">{range_max_swe:.1%}</div>
            <div class="kpi-delta-flat">verified coding</div>
          </div>
        </div>
        """,
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
        st.plotly_chart(fig_sota, use_container_width=True, theme=None)

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
        st.plotly_chart(fig_ctx, use_container_width=True, theme=None)

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
            use_container_width=True,
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


def render_compute_availability_section(datasets: dict[str, DatasetLoadResult], compute_views: dict[str, object]) -> None:
    spot_df = compute_views.get("spot_df", pd.DataFrame())
    lambda_latest = compute_views.get("lambda_latest", pd.DataFrame())
    models_latest = compute_views.get("models_latest", pd.DataFrame())
    models_growth = compute_views.get("models_growth", pd.DataFrame())

    st.markdown('<div class="section-title">Hardware & Compute Availability</div>', unsafe_allow_html=True)

    # --- KPI Row ---
    kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
    
    with kpi_col1:
        # Protect against empty data or missing columns
        if not lambda_latest.empty and "instance_type_name" in lambda_latest.columns:
            stock_val = lambda_latest["instance_type_name"].nunique()
            stock_count = int(stock_val.max() if hasattr(stock_val, "max") else stock_val)
        else:
            stock_count = 0
            
        st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">Lambda GPU Stock</div>
                <div class="kpi-value">{stock_count}</div>
                <div class="kpi-delta-flat">instance types</div>
            </div>
        """, unsafe_allow_html=True)

    with kpi_col2:
        if not spot_df.empty and "instance_type" in spot_df.columns and "spot_price" in spot_df.columns:
            p5_data = spot_df[spot_df["instance_type"].str.contains("p5", na=False)]
            avg_val = p5_data["spot_price"].mean()
            avg_p5 = float(avg_val.max() if hasattr(avg_val, "max") else avg_val) if not p5_data.empty else 0
        else:
            avg_p5 = 0

        st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">Avg P5 Spot Price</div>
                <div class="kpi-value">${avg_p5:.2f}</div>
                <div class="kpi-delta-flat">per hour</div>
            </div>
        """, unsafe_allow_html=True)

    with kpi_col3:
        if not models_latest.empty and "model_id" in models_latest.columns:
            m_val = models_latest["model_id"].nunique()
            model_count = int(m_val.max() if hasattr(m_val, "max") else m_val)
        else:
            model_count = 0

        st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">Direct Model Access</div>
                <div class="kpi-value">{model_count}</div>
                <div class="kpi-delta-flat">OpenRouter catalog</div>
            </div>
        """, unsafe_allow_html=True)

    with kpi_col4:
        # Deep cleaning: select column, drop any NAs, force to float, compute mean
        if not models_latest.empty and "pricing_prompt" in models_latest.columns:
            # If duplicated, take only the first one to be safe
            p_col = models_latest["pricing_prompt"]
            if isinstance(p_col, pd.DataFrame):
                p_col = p_col.iloc[:, 0]
            
            # Filter for valid positive pricing (exclude -1.0 and special markers)
            p_clean = pd.to_numeric(p_col, errors="coerce").dropna()
            p_valid = p_clean[p_clean > 0]
            
            p_avg = p_valid.mean()
            avg_pricing = float(p_avg) * 1e6 if pd.notna(p_avg) else 0
        else:
            avg_pricing = 0

        st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">Avg Prompt Pricing</div>
                <div class="kpi-value">${avg_pricing:.2f}</div>
                <div class="kpi-delta-flat">per 1M tokens</div>
            </div>
        """, unsafe_allow_html=True)

    # --- Main Visuals ---
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown('<div class="section-subtitle">AWS Spot Price History (H100/P5 Watchlist)</div>', unsafe_allow_html=True)
        if not spot_df.empty:
            fig_spot = go.Figure()
            for instance in spot_df["instance_type"].unique():
                inst_data = spot_df[spot_df["instance_type"] == instance]
                for az in inst_data["availability_zone"].unique():
                    az_data = inst_data[inst_data["availability_zone"] == az]
                    fig_spot.add_trace(go.Scatter(
                        x=az_data["price_timestamp"],
                        y=az_data["spot_price"],
                        name=f"{instance} ({az})",
                        mode="lines",
                        hovertemplate="<b>%{x}</b><br>$%{y:.2f}/hr<extra></extra>"
                    ))
            fig_spot.update_layout(
                title="AWS Spot Price History ($/hr)",
                template="plotly_white",
                height=400,
                margin=dict(l=0, r=0, t=40, b=10),
                legend=dict(orientation="h", y=-0.2)
            )
            st.plotly_chart(fig_spot, use_container_width=True, theme=None)
        else:
            st.info("No AWS Spot pricing data available.")

    with col_right:
        st.markdown('<div class="section-subtitle">Lambda Cloud Availability Listing</div>', unsafe_allow_html=True)
        if not lambda_latest.empty:
            display_lambda = lambda_latest[[
                "instance_type_name", "gpu_type", "gpu_count", "region"
            ]].copy()
            display_lambda.columns = ["Instance", "GPU Type", "Count", "Region"]
            st.dataframe(display_lambda, use_container_width=True, hide_index=True)
        else:
            st.info("No Lambda Cloud inventory data available.")

    # --- Bottom Row ---
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
            st.plotly_chart(fig_growth, use_container_width=True, theme=None)

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
            st.plotly_chart(fig_scatter, use_container_width=True, theme=None)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # 1. Immediate call to set_page_config
    st.set_page_config(page_title="Alternative Data Dashboard", layout="wide", page_icon="📊")
    
    # 2. Startup logging for deployment debugging
    print("Main script execution started: alternative-data dashboard")
    
    inject_css()

    # 3. Load per-domain cached state
    openrouter_datasets, openrouter_freshness, openrouter_checks = load_domain_state_cached(
        BASE_DIR, "rankings", build_domain_signature(BASE_DIR, "rankings")
    )
    apps_datasets, apps_freshness, apps_checks = load_domain_state_cached(
        BASE_DIR, "apps", build_domain_signature(BASE_DIR, "apps")
    )
    github_datasets, github_freshness, github_checks = load_domain_state_cached(
        BASE_DIR, "github", build_domain_signature(BASE_DIR, "github")
    )
    provider_datasets, provider_freshness, provider_checks = load_domain_state_cached(
        BASE_DIR, "provider_adoption", build_domain_signature(BASE_DIR, "provider_adoption")
    )
    semi_datasets, semi_freshness, semi_checks = load_domain_state_cached(
        BASE_DIR, "semiconductor_memory", build_domain_signature(BASE_DIR, "semiconductor_memory")
    )
    benchmark_datasets, benchmark_freshness, benchmark_checks = load_domain_state_cached(
        BASE_DIR, "ai_frontier", build_domain_signature(BASE_DIR, "ai_frontier")
    )
    compute_datasets, compute_freshness, compute_checks = load_domain_state_cached(
        BASE_DIR, "compute_availability", build_domain_signature(BASE_DIR, "compute_availability")
    )

    datasets = {
        **openrouter_datasets,
        **apps_datasets,
        **github_datasets,
        **provider_datasets,
        **semi_datasets,
        **benchmark_datasets,
        **compute_datasets,
    }
    freshness = FreshnessInfo(
        latest_scraped_at=max(
            [value for value in [
                openrouter_freshness.latest_scraped_at,
                apps_freshness.latest_scraped_at,
                github_freshness.latest_scraped_at,
                provider_freshness.latest_scraped_at,
                semi_freshness.latest_scraped_at,
                benchmark_freshness.latest_scraped_at,
                compute_freshness.latest_scraped_at,
            ] if value],
            default=None,
        ),
        latest_run_id=next(
            (value for value in [
                openrouter_freshness.latest_run_id,
                apps_freshness.latest_run_id,
                github_freshness.latest_run_id,
                provider_freshness.latest_run_id,
                semi_freshness.latest_run_id,
                benchmark_freshness.latest_run_id,
            ] if value),
            None,
        ),
        latest_manifest_path=next(
            (value for value in [
                openrouter_freshness.latest_manifest_path,
                apps_freshness.latest_manifest_path,
                github_freshness.latest_manifest_path,
                provider_freshness.latest_manifest_path,
                semi_freshness.latest_manifest_path,
                benchmark_freshness.latest_manifest_path,
            ] if value),
            None,
        ),
        latest_manifest_scraped_at=max(
            [value for value in [
                openrouter_freshness.latest_manifest_scraped_at,
                apps_freshness.latest_manifest_scraped_at,
                github_freshness.latest_manifest_scraped_at,
                provider_freshness.latest_manifest_scraped_at,
                semi_freshness.latest_manifest_scraped_at,
                benchmark_freshness.latest_manifest_scraped_at,
            ] if value],
            default=None,
        ),
    )
    checks = openrouter_checks + apps_checks + github_checks + provider_checks + semi_checks + benchmark_checks

    openrouter_views = compute_openrouter_views({**openrouter_datasets, **apps_datasets, **compute_datasets})
    github_views = compute_github_views(github_datasets)
    provider_views = compute_provider_adoption_views(provider_datasets)
    semi_views = compute_semiconductor_views(semi_datasets)
    benchmark_views = compute_llm_benchmark_views(benchmark_datasets)
    compute_views = compute_compute_availability_views(compute_datasets)

    render_header(freshness)
    
    main_tabs = st.tabs(["OpenRouter Intelligence", "AI Frontier & HBM", "HW & Compute", "GitHub Trending", "Provider Adoption", "Semiconductor Analysis"])
    
    with main_tabs[0]:
        render_rankings_semantics_note(datasets)
        render_kpi_row(datasets, openrouter_views)
        render_top_models_chart(datasets, openrouter_views)
        render_market_share_section(datasets, openrouter_views)
        render_leaderboard(datasets)
        render_revenue_estimator(datasets, openrouter_views)
        render_programming_chart(datasets, openrouter_views)
        render_app_usage_chart(datasets, openrouter_views)
        render_apps_tables(datasets)
    
    with main_tabs[1]:
        render_ai_frontier_section(datasets, benchmark_views)

    with main_tabs[2]:
        render_compute_availability_section(datasets, compute_views)

    with main_tabs[3]:
        render_github_trending_section(datasets, github_views)

    with main_tabs[4]:
        render_provider_adoption_section(datasets, provider_views)
        
    with main_tabs[5]:
        render_semiconductor_section(datasets, semi_views)
        
    render_checks(checks)


if __name__ == "__main__":
    main()
