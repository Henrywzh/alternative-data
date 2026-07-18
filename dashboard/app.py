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
import yfinance as yf

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parent.parent
    src_root = repo_root / "src"
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(src_root))

from dashboard import remote
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

from dashboard.theme import (ACCENT, BG, SIDEBAR, CARD, BORDER, TEXT, MUTED, GREEN, RED, YELLOW, GRID, TICK, MODEL_COLORS, inject_css)
from dashboard.components import (format_metric, _empty_dataset_frame, _styler_applymap_compat, WEEKLY_MONTHLY_OTHER_PROVIDERS, DAILY_OTHER_PROVIDERS, US_PROVIDER_ORDER, CHINA_PROVIDER_ORDER, order_provider_columns, regroup_provider_pivot_for_display, render_dataset_guard, format_scraped_at_display, dataframe_for_display, make_stacked_bar, make_stacked_area_chart, make_line_chart, kpi_card_html, kpi_grid_html, _top_n_with_others)
from dashboard.sections import (
    overview,
    openrouter,
    vercel_ai,
    ramp,
    provider_adoption,
    artificial_analysis,
    semiconductor,
    minerals,
    google_trends,
    provider_incidents,
    ai_hiring,
)

# Backward-compatible re-exports for tests/scratch that import from dashboard.app.
from dashboard.sections.openrouter import (  # noqa: F401
    compute_openrouter_views,
    compute_compute_availability_views,
    _compute_revenue_views,
    _derive_provider_name,
    grouped_revenue_token_pivots,
    rankings_week_context,
    rankings_bucket_warning,
)
from dashboard.sections.provider_adoption import (  # noqa: F401
    compute_provider_adoption_views,
    prepare_hf_models_table,
    resolve_hf_metric_config,
)
from dashboard.sections.artificial_analysis import compute_artificial_analysis_views  # noqa: F401
from dashboard.sections.semiconductor import compute_semiconductor_views  # noqa: F401


BASE_DIR = Path(__file__).resolve().parent.parent


MAIN_SECTIONS = (
    "Overview",
    "OpenRouter Intelligence",
    "OpenRouter Models",
    "OpenRouter Workloads",
    "Vercel AI",
    "Ramp",
    "Artificial Analysis",
    "Provider Adoption",
    "AI Hiring Demand",
    "Semiconductor Analysis",
    "Google Trends Signal",
    "Minerals",
    "Provider Incidents",
)


SECTION_DESCRIPTIONS = {
    "Overview": "Cross-market pulse across AI usage, enterprise adoption, developer activity, model quality, and infrastructure.",
    "OpenRouter Intelligence": "Tracks model and provider usage, estimated revenue, task leaders, market coverage, and catalog economics.",
    "OpenRouter Models": "Explore OpenRouter companies and models by activity, pricing, context window, release date, capabilities, and public-app usage.",
    "OpenRouter Workloads": "Tracks request context lengths, modality mix, and the public apps generating OpenRouter traffic.",
    "Vercel AI": "Tracks model and lab usage share across Vercel AI Gateway, with modality and metric-level rankings.",
    "Ramp": "Tracks business AI adoption, spend intensity, vendor mix, model mix, company segments, and employment signals.",
    "Artificial Analysis": "Compares frontier-model intelligence, coding and math quality, speed, pricing, context, and lab-level progress.",
    "Provider Adoption": "Tracks package downloads, GitHub implementation signals, Hugging Face activity, and provider momentum.",
    "AI Hiring Demand": "Tracks AI job-posting share, company hiring pipelines, role mix, openings, closures, and source coverage.",
    "Semiconductor Analysis": "Tracks AI-infrastructure demand through memory pricing, production, trade, revenue, and release-lag indicators.",
    "Google Trends Signal": "Tracks search-interest changes for AI products and providers across time and geography.",
    "Minerals": "Tracks strategic mineral prices, supply signals, and market conditions relevant to compute infrastructure.",
    "Provider Incidents": "Tracks provider-reported outages, affected components, duration, status updates, and source coverage.",
}


SECTION_DOMAIN_MAP = {
    "Overview": ("overview",),
    "OpenRouter Intelligence": ("openrouter_intelligence", "compute_availability", "openrouter_official_market"),
    "OpenRouter Models": ("openrouter_model_explorer", "openrouter_catalog"),
    "OpenRouter Workloads": ("openrouter_workloads", "apps"),
    "Vercel AI": ("vercel_ai",),
    "Ramp": ("ramp",),
    "Artificial Analysis": ("artificial_analysis",),
    "Provider Adoption": ("provider_adoption",),
    "Semiconductor Analysis": ("semiconductor_memory", "semiconductor_proxies", "taiwan_semiconductor_revenue"),
    "Google Trends Signal": (),
    # Self-contained, like Google Trends — loads its own data, no registry domain.
    "Minerals": (),
    "Provider Incidents": ("provider_incidents",),
    "AI Hiring Demand": ("ai_hiring",),
}


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


def _clear_model_query_param() -> None:
    if hasattr(st, "query_params") and st.query_params.get("model") is not None:
        del st.query_params["model"]


def _set_main_section(section: str) -> None:
    st.session_state["main_section"] = section
    if section != "OpenRouter Models":
        _clear_model_query_param()


def select_main_section() -> str:
    current = str(st.session_state.get("main_section", MAIN_SECTIONS[0]))
    if current not in MAIN_SECTIONS:
        current = MAIN_SECTIONS[0]
        st.session_state["main_section"] = current

    def nav_button(label: str) -> None:
        st.button(
            label,
            key=f"sidebar_nav_{label}",
            type="primary" if current == label else "secondary",
            width="stretch",
            on_click=_set_main_section,
            args=(label,),
        )

    with st.sidebar:
        st.markdown(
            '<div class="sidebar-brand">Alternative Data</div>'
            '<div class="sidebar-brand-subtitle">Research dashboard</div>',
            unsafe_allow_html=True,
        )
        nav_button("Overview")
        st.markdown('<div class="sidebar-group-label">AI Usage</div>', unsafe_allow_html=True)
        for label in ("OpenRouter Intelligence", "OpenRouter Models", "OpenRouter Workloads", "Vercel AI"):
            nav_button(label)
        st.markdown('<div class="sidebar-group-label">Adoption</div>', unsafe_allow_html=True)
        for label in ("Ramp", "Provider Adoption", "AI Hiring Demand"):
            nav_button(label)
        st.markdown('<div class="sidebar-group-label">Analysis</div>', unsafe_allow_html=True)
        nav_button("Artificial Analysis")
        st.markdown('<div class="sidebar-group-label">Infrastructure</div>', unsafe_allow_html=True)
        for label in ("Semiconductor Analysis", "Minerals"):
            nav_button(label)
        st.markdown('<div class="sidebar-group-label">Signals</div>', unsafe_allow_html=True)
        for label in ("Google Trends Signal", "Provider Incidents"):
            nav_button(label)

    return current


@st.cache_data(ttl=3600, max_entries=8)
def load_domain_state_cached(
    base_dir: Path,
    domain: str,
    domain_signature: tuple[tuple[str, int, int], ...],
    data_sha: str | None = None,
) -> tuple[dict[str, DatasetLoadResult], FreshnessInfo, list[CheckResult]]:
    # Both are cache keys only: domain_signature catches local edits (mtimes
    # change), data_sha catches remote pushes on Streamlit Cloud (mtimes don't).
    _ = (domain_signature, data_sha)
    datasets = load_domain_datasets(domain, base_dir=base_dir, data_sha=data_sha)
    freshness = load_latest_manifest(base_dir=base_dir, datasets=datasets, scan_raw_manifests=False)
    # Streamlit Cloud can briefly serve mixed app/checker versions during deploys.
    # Prefer the narrowed domain-aware API when present, but keep the app bootable
    # if an older dashboard.checks module is still resident.
    if "expected_dataset_ids" in inspect.signature(run_checks).parameters:
        checks = run_checks(datasets, freshness, base_dir=base_dir, expected_dataset_ids=domain_dataset_ids(domain))
    else:
        checks = run_checks(datasets, freshness, base_dir=base_dir)
    return datasets, freshness, checks


def render_header(freshness: FreshnessInfo, section: str) -> None:
    updated = freshness.latest_scraped_at or "Unknown"
    updated_display = format_scraped_at_display(updated) if updated != "Unknown" else updated
    description = SECTION_DESCRIPTIONS.get(section, "Alternative datasets for monitoring AI markets and infrastructure.")
    st.markdown(
        f"""
        <div class="page-heading">
          <div class="page-eyebrow">Alternative Data Dashboard</div>
          <h1>
            {section}
          </h1>
          <div class="page-description">{description}</div>
          <div class="page-freshness">Latest available update: {updated_display}</div>
        </div>
        """,
        unsafe_allow_html=True,
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


SECTION_RENDERERS = {
    "Overview": overview.render,
    "OpenRouter Intelligence": openrouter.render,
    # Keep startup compatible with a Streamlit process that has briefly
    # retained the pre-explorer module during a rolling redeploy.
    "OpenRouter Models": getattr(openrouter, "render_models", openrouter.render),
    "OpenRouter Workloads": getattr(openrouter, "render_workloads", openrouter.render),
    "Vercel AI": vercel_ai.render,
    "Ramp": ramp.render,
    "Artificial Analysis": artificial_analysis.render,
    "Provider Adoption": provider_adoption.render,
    "Semiconductor Analysis": semiconductor.render,
    "Google Trends Signal": google_trends.render,
    "Minerals": minerals.render,
    "Provider Incidents": provider_incidents.render,
    "AI Hiring Demand": ai_hiring.render,
}


def main() -> None:
    st.set_page_config(
        page_title="Alternative Data Dashboard",
        layout="wide",
        page_icon="📊",
        initial_sidebar_state="expanded",
    )
    inject_css()

    selected_section = select_main_section()
    if selected_section != "OpenRouter Models":
        _clear_model_query_param()
    selected_domains = section_domains(selected_section)
    domain_shas = {
        domain: remote.latest_data_sha(
            f"{remote.DATA_PATH_PREFIX}/{dataset_source_for_domain(domain)}"
        )
        for domain in selected_domains
    } if remote.remote_enabled() else {domain: None for domain in selected_domains}
    with st.sidebar:
        st.divider()
        if st.button("🔄 Refresh data", width="stretch"):
            st.cache_data.clear()
            st.rerun()
        visible_shas = sorted({sha[:7] for sha in domain_shas.values() if sha})
        if visible_shas:
            st.caption(f"Data {' · '.join(f'`{sha}`' for sha in visible_shas)}")

    domain_states = {
        domain: load_domain_state_cached(
            BASE_DIR,
            domain,
            build_domain_signature(BASE_DIR, domain),
            data_sha=domain_shas[domain],
        )
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

    render_header(freshness, selected_section)

    renderer = SECTION_RENDERERS.get(selected_section)
    if renderer is not None:
        renderer(domain_states, datasets)

    render_checks(checks)


if __name__ == "__main__":
    main()
