"""Private, read-only Streamlit shell for Research Control Tower V1."""

from __future__ import annotations

import os
from pathlib import Path
import sys

# Ensure repository root and app root are on sys.path deterministically before
# importing control_tower modules that depend on 'src' or sibling packages.
APP_ROOT = Path(__file__).resolve().parent
REPO_ROOT = APP_ROOT.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import pandas as pd
import streamlit as st

from control_tower.components import inject_styles
from control_tower.models import ControlTowerSnapshot, EventFilters
from control_tower.pages.ai_bottlenecks import render_ai_bottlenecks_page
from control_tower.pages.company import render_company_page
from control_tower.pages.source_health import render_source_health_page
from control_tower.pages.today import render_today_page
from control_tower.pages.unified_timeline import render_timeline_page
from control_tower.repository import ControlTowerRepository, ControlTowerStartupError
from control_tower.config import (
    ArtifactResolutionError,
    artifact_fingerprint,
    resolve_artifact_root,
)


DEFAULT_ARTIFACT_ROOT = APP_ROOT / ".generated"
PAGE_LABELS = ("Today", "Unified Timeline", "AI Bottlenecks", "Company", "Source Health")
HORIZON_OPTIONS = ("7d", "30d", "90d", "long_range", "all")
TIMEZONE_OPTIONS = ("Europe/London", "Asia/Hong_Kong", "Asia/Seoul", "America/New_York", "UTC")
DEFAULT_FOCUS_BASKET_ID = "RESEARCH_STAGE_1_CHINA_INTERNET"
DEFAULT_FOCUS_LABEL = "Stage 1 · China Internet"


def configured_artifact_root() -> Path:
    configured = os.environ.get("CONTROL_TOWER_ARTIFACT_ROOT", "").strip()
    root = Path(configured) if configured else DEFAULT_ARTIFACT_ROOT
    # Resolve a publication pointer exactly once.  The returned direct
    # generation root is then used for both fingerprinting and repository
    # loading, so a concurrent CURRENT switch cannot mix generations.
    return resolve_artifact_root(root).artifact_root


@st.cache_data(show_spinner=False)
def load_snapshot_cached(
    artifact_root_str: str,
    fingerprint: tuple[tuple[str, int, int, str], ...],
) -> ControlTowerSnapshot:
    """Load one manifest-bound snapshot; ``fingerprint`` is cache invalidation."""

    del fingerprint
    return ControlTowerRepository(Path(artifact_root_str)).load_snapshot()


def _ensure_session_state() -> None:
    defaults = {
        "ct_page": "Today",
        "page_labels": PAGE_LABELS,
        "ct_theme": "Light",
        "ct_focus_bootstrapped": False,
        "ct_horizon": "30d",
        "ct_basket_ids": (),
        "ct_countries": (),
        "ct_scopes": (),
        "ct_certainty_classes": (),
        "ct_statuses": (),
        "ct_membership_tiers": (),
        "ct_importance": (),
        "ct_confidence_min": 0.0,
        "ct_viewer_timezone": "Europe/London",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _set_page(page: str) -> None:
    st.session_state["ct_page"] = page


def _reset_filters() -> None:
    for key, value in {
        "ct_horizon": "30d",
        "ct_basket_ids": (),
        "ct_countries": (),
        "ct_scopes": (),
        "ct_certainty_classes": (),
        "ct_statuses": (),
        "ct_membership_tiers": (),
        "ct_importance": (),
        "ct_confidence_min": 0.0,
    }.items():
        st.session_state[key] = value


def _values(frame: pd.DataFrame, column: str, *, upper: bool = False) -> list[str]:
    if frame.empty or column not in frame.columns:
        return []
    values = {str(value).strip() for value in frame[column].dropna() if str(value).strip()}
    result = sorted(values)
    return [value.upper() for value in result] if upper else result


def _bootstrap_default_focus(snapshot: ControlTowerSnapshot) -> None:
    """Select Stage 1 once when the published bundle contains the focus basket."""

    if st.session_state["ct_focus_bootstrapped"]:
        return
    basket_ids = set(snapshot.baskets.get("basket_id", pd.Series(dtype="string")).astype("string"))
    if DEFAULT_FOCUS_BASKET_ID in basket_ids and not st.session_state["ct_basket_ids"]:
        st.session_state["ct_basket_ids"] = (DEFAULT_FOCUS_BASKET_ID,)
    st.session_state["ct_focus_bootstrapped"] = True


def _sidebar_navigation() -> None:
    st.sidebar.markdown("### Research Control Tower")
    st.sidebar.caption("Evidence-first review surface")
    st.sidebar.caption(f"Default focus · {DEFAULT_FOCUS_LABEL}")
    for group, pages in (
        ("Review", PAGE_LABELS[:2]),
        ("Research", PAGE_LABELS[2:4]),
        ("Data", PAGE_LABELS[4:]),
    ):
        st.sidebar.markdown(f"**{group}**")
        for page in pages:
            selected = st.session_state["ct_page"] == page
            st.sidebar.button(
                page,
                key=f"ct_nav_{page}",
                type="primary" if selected else "secondary",
                width="stretch",
                on_click=_set_page,
                args=(page,),
            )
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Settings**")
    st.sidebar.radio(
        "Theme",
        options=["Light", "Dark"],
        key="ct_theme",
        horizontal=True,
    )


def _active_filter_summary() -> str:
    parts: list[str] = []
    if st.session_state["ct_horizon"] != "30d":
        label = {"long_range": "Long range", "all": "All"}.get(st.session_state["ct_horizon"], st.session_state["ct_horizon"])
        parts.append(f"horizon={label}")
    for key, label in (
        ("ct_basket_ids", "basket"), ("ct_countries", "country"), ("ct_scopes", "scope"),
        ("ct_certainty_classes", "certainty"), ("ct_statuses", "status"),
        ("ct_membership_tiers", "tier"), ("ct_importance", "importance"),
    ):
        values = st.session_state[key]
        if values:
            display_values = [
                DEFAULT_FOCUS_LABEL if value == DEFAULT_FOCUS_BASKET_ID else str(value)
                for value in values
            ]
            parts.append(f"{label}={','.join(display_values)}")
    confidence = st.session_state["ct_confidence_min"]
    if confidence:
        parts.append(f"confidence≥{confidence:.2f}")
    return " · ".join(parts) if parts else "All filters at default"


def _degraded_label(name: object) -> str:
    labels = {
        "consensus_revisions": "Consensus revisions",
        "consensus_snapshots": "Consensus snapshots",
        "news_filings": "News and filings",
        "source_health": "Source health",
    }
    text = str(name).strip()
    return labels.get(text, text.replace("_", " ").title())


def _filter_controls(snapshot: ControlTowerSnapshot) -> EventFilters:
    basket_options = _values(snapshot.baskets, "basket_id")
    country_options = _values(snapshot.entities, "country", upper=True)
    scope_options = ["company", "basket", "macro", "policy", "index"]
    certainty_options = ["hard", "provisional", "thesis_checkpoint", "observed"]
    status_options = ["scheduled", "confirmed", "observed", "active", "watch", "completed"]
    tier_options = ["core", "read_through", "watch_only"]
    importance_options = ["high", "medium", "low"]

    with st.expander("Filters", expanded=False):
        horizon = st.selectbox("Horizon", HORIZON_OPTIONS, key="ct_horizon", format_func=lambda value: "Long range" if value == "long_range" else "All" if value == "all" else value)
        baskets = st.multiselect("Basket", basket_options, key="ct_basket_ids")
        countries = st.multiselect("Country", country_options, key="ct_countries")
        scopes = st.multiselect("Scope", scope_options, key="ct_scopes")
        certainty = st.multiselect("Certainty", certainty_options, key="ct_certainty_classes", format_func=lambda value: {"thesis_checkpoint": "Thesis window"}.get(value, value.title()))
        statuses = st.multiselect("Status", status_options, key="ct_statuses")
        tiers = st.multiselect("Membership tier", tier_options, key="ct_membership_tiers", format_func=lambda value: value.replace("_", "-"))
        importance = st.multiselect("Importance", importance_options, key="ct_importance")
        confidence_min = st.slider("Minimum confidence", 0.0, 1.0, key="ct_confidence_min", step=0.05)
        st.selectbox("Viewer timezone", TIMEZONE_OPTIONS, key="ct_viewer_timezone")
        st.button("Clear filters", key="ct_clear_filters", on_click=_reset_filters, width="stretch")
        st.caption(
            "Filter applicability · basket, country and membership tier apply "
            "to company events, consensus and filings. Scope hides company "
            "consensus/filings when company is excluded. Status, certainty, "
            "confidence and importance affect the event ledger only. Source "
            "alerts are global."
        )
    # A null confidence bound is useful to the pure API.  Streamlit's slider
    # has no nullable state, so the zero default remains an explicit lower
    # bound and does not change the event universe in V1.
    summary = _active_filter_summary()
    st.markdown(f'<div class="ct-filter-summary">Active filters · {summary}</div>', unsafe_allow_html=True)
    return EventFilters(
        horizon=horizon,
        basket_id=tuple(baskets),
        country=tuple(countries),
        scope=tuple(scopes),
        certainty_class=tuple(certainty),
        status=tuple(statuses),
        membership_tier=tuple(tiers),
        importance=tuple(importance),
        confidence_min=float(confidence_min) if confidence_min else None,
        now_utc=snapshot.now_utc,
    )


def _header(snapshot: ControlTowerSnapshot, timezone: str) -> None:
    try:
        as_of = snapshot.as_of_utc.tz_convert(timezone).strftime("%d %b %Y %H:%M %Z")
    except Exception:
        as_of = snapshot.as_of_utc.strftime("%d %b %Y %H:%M UTC")
    st.markdown('<div class="ct-shell">', unsafe_allow_html=True)
    st.markdown('<div class="ct-header-block"><p class="ct-eyebrow">Private research terminal</p></div>', unsafe_allow_html=True)
    page_slug = "research-control-tower-" + "-".join(
        part for part in st.session_state["ct_page"].casefold().replace("&", "and").split()
        if part
    )
    st.title(f"Research Control Tower · {st.session_state['ct_page']}", anchor=page_slug)
    st.caption(f"As of {as_of} · build {snapshot.build_id} · {snapshot.status}")
    if snapshot.status == "degraded":
        details = "; ".join(f"{_degraded_label(name)}: {reason.replace('_', ' ')}" for name, reason in snapshot.degraded_reasons.items())
        st.warning(f"Degraded data coverage · {details or 'optional source unavailable'}")


def _render_placeholder(page: str) -> None:
    st.info(f"{page} is registered for V1 navigation and will be filled by the next task.")


def main() -> None:
    st.set_page_config(page_title="Research Control Tower", page_icon="⌁", layout="wide", initial_sidebar_state="collapsed")
    _ensure_session_state()
    inject_styles()
    _sidebar_navigation()
    try:
        artifact_root = configured_artifact_root()
        snapshot = load_snapshot_cached(str(artifact_root), artifact_fingerprint(artifact_root))
    except (ArtifactResolutionError, ControlTowerStartupError) as exc:
        st.error(str(exc))
        st.stop()

    _bootstrap_default_focus(snapshot)
    viewer_timezone = st.session_state["ct_viewer_timezone"]
    _header(snapshot, viewer_timezone)
    filters = _filter_controls(snapshot)

    if st.session_state["ct_page"] == "Today":
        render_today_page(snapshot, filters=filters, viewer_timezone=viewer_timezone)
    elif st.session_state["ct_page"] == "Unified Timeline":
        render_timeline_page(snapshot, filters=filters, viewer_timezone=viewer_timezone)
    elif st.session_state["ct_page"] == "AI Bottlenecks":
        render_ai_bottlenecks_page(snapshot, filters=filters, viewer_timezone=viewer_timezone)
    elif st.session_state["ct_page"] == "Company":
        render_company_page(snapshot, filters=filters, viewer_timezone=viewer_timezone)
    elif st.session_state["ct_page"] == "Source Health":
        render_source_health_page(snapshot, viewer_timezone=viewer_timezone)
    else:
        _render_placeholder(st.session_state["ct_page"])
    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
