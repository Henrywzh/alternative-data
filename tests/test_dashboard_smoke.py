from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from dashboard.sections.overview import _format_as_of

# AppTest.from_file() resolves a relative path against whichever frame it
# detects as its caller, which has proven inconsistent between local runs and
# the Linux CI runner (this file passes locally 8/8 but fails to locate
# "dashboard/app.py" in CI). An absolute path removes the ambiguity, matching
# the convention already used in tests/test_asia_markets_streamlit_contracts.py.
APP_PATH = str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py")


def test_overview_as_of_dates_use_consistent_iso_format() -> None:
    assert _format_as_of("2026-07-17 00:00:00") == "2026-07-17"
    assert _format_as_of("2026-07-18") == "2026-07-18"
    assert _format_as_of("2026-06") == "2026-06-01"


def test_dashboard_overview_renders_real_chart_and_lineage_table(monkeypatch) -> None:
    monkeypatch.setenv("DATA_SOURCE", "local")

    app = AppTest.from_file(APP_PATH, default_timeout=90).run()

    assert not app.exception
    assert len(app.get("plotly_chart")) >= 5
    assert len(app.dataframe) >= 2
    assert "Artificial Analysis" in [button.label for button in app.button]
    assert "OpenRouter" in [button.label for button in app.button]
    assert all("pulse-signal-card" not in str(markdown.value) for markdown in app.markdown)
    assert any("not an other-provider bucket" in str(caption.value) for caption in app.caption)
    rendered_markdown = "\n".join(str(markdown.value) for markdown in app.markdown)
    assert "AI Usage &amp; Economics" in rendered_markdown
    assert "Demand &amp; Adoption" in rendered_markdown


def test_sidebar_highlight_updates_with_selected_page(monkeypatch) -> None:
    monkeypatch.setenv("DATA_SOURCE", "local")
    app = AppTest.from_file(APP_PATH, default_timeout=90).run()

    next(button for button in app.button if button.label == "Vercel AI").click().run()

    overview = next(button for button in app.button if button.label == "Overview")
    vercel = next(button for button in app.button if button.label == "Vercel AI")
    assert app.session_state["main_section"] == "Vercel AI"
    assert overview.proto.type == "secondary"
    assert vercel.proto.type == "primary"


def test_model_deep_link_is_removed_outside_unified_openrouter(monkeypatch) -> None:
    monkeypatch.setenv("DATA_SOURCE", "local")
    app = AppTest.from_file(APP_PATH, default_timeout=90)
    app.query_params["model"] = "xiaomi/mimo-v2.5"

    app.run()

    assert not app.exception
    assert "model" not in app.query_params


def test_model_deep_link_is_preserved_on_unified_openrouter(monkeypatch) -> None:
    monkeypatch.setenv("DATA_SOURCE", "local")
    app = AppTest.from_file(APP_PATH, default_timeout=120)
    app.session_state["main_section"] = "OpenRouter"
    app.query_params["model"] = "xiaomi/mimo-v2.5"

    app.run()

    assert not app.exception
    assert app.query_params["model"] in (
        "xiaomi/mimo-v2.5",
        ["xiaomi/mimo-v2.5"],
    )


def _run_openrouter_subpage(monkeypatch, subpage: str | None) -> str:
    monkeypatch.setenv("DATA_SOURCE", "local")
    app = AppTest.from_file(APP_PATH, default_timeout=120)
    app.session_state["main_section"] = "OpenRouter"
    if subpage is not None:
        app.session_state["openrouter_subpage"] = subpage
    app.run()
    assert not app.exception
    return "\n".join(str(markdown.value) for markdown in app.markdown)


def test_unified_openrouter_renders_the_selected_subpage(monkeypatch) -> None:
    """Each sub-page draws its own panels when selected.

    These used to be st.tabs, which renders every body on every run, so one run
    contained all of them.  Only the selected body renders now -- that is what
    lets the other sub-pages' datasets go unread.
    """
    from dashboard.sections.openrouter import UNIFIED_SUBPAGES

    economics = _run_openrouter_subpage(monkeypatch, UNIFIED_SUBPAGES[0])
    assert "Provider Revenue &amp; Token Volume" in economics

    workloads = _run_openrouter_subpage(monkeypatch, UNIFIED_SUBPAGES[4])
    assert "Context Length Usage" in workloads
    assert "Modality Rankings" in workloads
    assert "App Rankings & Trends" in workloads


def test_unified_openrouter_does_not_render_unselected_subpages(monkeypatch) -> None:
    """The point of the selector: an unselected sub-page must not be computed."""
    from dashboard.sections.openrouter import UNIFIED_SUBPAGES

    economics = _run_openrouter_subpage(monkeypatch, UNIFIED_SUBPAGES[0])

    assert "Context Length Usage" not in economics
    assert "App Rankings & Trends" not in economics


def test_provider_incident_section_renders_live_history_and_coverage(monkeypatch) -> None:
    monkeypatch.setenv("DATA_SOURCE", "local")
    app = AppTest.from_file(APP_PATH, default_timeout=90)
    app.session_state["dashboard_area"] = "Signals"
    app.session_state["main_section"] = "Provider Incidents"
    app.session_state["dashboard_view_Signals"] = "Provider Incidents"

    app.run()

    assert not app.exception
    # Weekly activity, provider breakdown, duration scatter, and downtime-by-provider.
    assert len(app.get("plotly_chart")) == 4
    assert len(app.dataframe) == 2


def test_ai_hiring_section_renders_macro_company_and_job_views(monkeypatch) -> None:
    monkeypatch.setenv("DATA_SOURCE", "local")
    app = AppTest.from_file(APP_PATH, default_timeout=90)
    app.session_state["dashboard_area"] = "Adoption"
    app.session_state["main_section"] = "AI Hiring Demand"
    app.session_state["dashboard_view_Adoption"] = "AI Hiring Demand"

    app.run()

    assert not app.exception
    # Macro signal, intensity, cohort, role/seniority heatmap, and concentration
    # chart should all render when the fixture is populated.
    assert len(app.get("plotly_chart")) >= 5
    assert len(app.dataframe) == 3
