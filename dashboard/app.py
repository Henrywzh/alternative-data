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
    openrouter,
    vercel_ai,
    ramp,
    provider_adoption,
    artificial_analysis,
    semiconductor,
    minerals,
    google_trends,
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
    "OpenRouter Intelligence",
    "OpenRouter Models",
    "Vercel AI",
    "Ramp",
    "Artificial Analysis",
    "Provider Adoption",
    "Semiconductor Analysis",
    "Google Trends Signal",
    "Minerals",
)


SECTION_DOMAIN_MAP = {
    "OpenRouter Intelligence": ("rankings", "apps", "compute_availability"),
    "OpenRouter Models": ("rankings", "apps", "compute_availability"),
    "Vercel AI": ("vercel_ai",),
    "Ramp": ("ramp",),
    "Artificial Analysis": ("artificial_analysis",),
    "Provider Adoption": ("provider_adoption",),
    "Semiconductor Analysis": ("semiconductor_memory", "semiconductor_proxies", "taiwan_semiconductor_revenue"),
    "Google Trends Signal": (),
    # Self-contained, like Google Trends — loads its own data, no registry domain.
    "Minerals": (),
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


def select_main_section() -> str:
    label = "Dashboard section"
    if hasattr(st, "segmented_control"):
        selected = st.segmented_control(label, MAIN_SECTIONS, default=MAIN_SECTIONS[0])
        return str(selected or MAIN_SECTIONS[0])
    return str(st.radio(label, MAIN_SECTIONS, horizontal=True))


@st.cache_data(ttl=3600)
def load_domain_state_cached(
    base_dir: Path,
    domain: str,
    domain_signature: tuple[tuple[str, int, int], ...],
    data_sha: str | None = None,
) -> tuple[dict[str, DatasetLoadResult], FreshnessInfo, list[CheckResult]]:
    # Both are cache keys only: domain_signature catches local edits (mtimes
    # change), data_sha catches remote pushes on Streamlit Cloud (mtimes don't).
    _ = (domain_signature, data_sha)
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
    "OpenRouter Intelligence": openrouter.render,
    # Keep startup compatible with a Streamlit process that has briefly
    # retained the pre-explorer module during a rolling redeploy.
    "OpenRouter Models": getattr(openrouter, "render_models", openrouter.render),
    "Vercel AI": vercel_ai.render,
    "Ramp": ramp.render,
    "Artificial Analysis": artificial_analysis.render,
    "Provider Adoption": provider_adoption.render,
    "Semiconductor Analysis": semiconductor.render,
    "Google Trends Signal": google_trends.render,
    "Minerals": minerals.render,
}


def main() -> None:
    st.set_page_config(page_title="Alternative Data Dashboard", layout="wide", page_icon="📊")
    inject_css()

    data_sha = remote.latest_data_sha() if remote.remote_enabled() else None

    selector_col, refresh_col = st.columns([5, 1], vertical_alignment="bottom")
    with selector_col:
        selected_section = select_main_section()
    with refresh_col:
        if st.button("🔄 Refresh data", width="stretch"):
            st.cache_data.clear()
            st.rerun()
        if data_sha:
            st.caption(f"Data `{data_sha[:7]}`")

    selected_domains = section_domains(selected_section)
    domain_states = {
        domain: load_domain_state_cached(
            BASE_DIR, domain, build_domain_signature(BASE_DIR, domain), data_sha=data_sha
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

    render_header(freshness)
    st.caption("Only the selected dashboard section is loaded, which keeps Streamlit Cloud restarts lighter and faster.")

    renderer = SECTION_RENDERERS.get(selected_section)
    if renderer is not None:
        renderer(domain_states, datasets)

    render_checks(checks)


if __name__ == "__main__":
    main()
