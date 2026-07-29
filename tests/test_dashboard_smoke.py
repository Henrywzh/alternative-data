from __future__ import annotations

from streamlit.testing.v1 import AppTest

from dashboard.sections.overview import _format_as_of


def test_overview_as_of_dates_use_consistent_iso_format() -> None:
    assert _format_as_of("2026-07-17 00:00:00") == "2026-07-17"
    assert _format_as_of("2026-07-18") == "2026-07-18"
    assert _format_as_of("2026-06") == "2026-06-01"


def test_dashboard_overview_renders_real_chart_and_lineage_table(monkeypatch) -> None:
    monkeypatch.setenv("DATA_SOURCE", "local")

    app = AppTest.from_file("dashboard/app.py", default_timeout=90).run()

    assert not app.exception
    assert len(app.get("plotly_chart")) >= 5
    assert len(app.dataframe) >= 2
    assert "Artificial Analysis" in [button.label for button in app.button]
    assert "OpenRouter Intelligence" in [button.label for button in app.button]
    assert "OpenRouter Workloads" in [button.label for button in app.button]
    assert all("pulse-signal-card" not in str(markdown.value) for markdown in app.markdown)
    assert any("not an other-provider bucket" in str(caption.value) for caption in app.caption)
    rendered_markdown = "\n".join(str(markdown.value) for markdown in app.markdown)
    assert "AI Usage &amp; Economics" in rendered_markdown
    assert "Demand &amp; Adoption" in rendered_markdown


def test_sidebar_highlight_updates_with_selected_page(monkeypatch) -> None:
    monkeypatch.setenv("DATA_SOURCE", "local")
    app = AppTest.from_file("dashboard/app.py", default_timeout=90).run()

    next(button for button in app.button if button.label == "Vercel AI").click().run()

    overview = next(button for button in app.button if button.label == "Overview")
    vercel = next(button for button in app.button if button.label == "Vercel AI")
    assert app.session_state["main_section"] == "Vercel AI"
    assert overview.proto.type == "secondary"
    assert vercel.proto.type == "primary"


def test_model_deep_link_is_removed_outside_openrouter_models(monkeypatch) -> None:
    monkeypatch.setenv("DATA_SOURCE", "local")
    app = AppTest.from_file("dashboard/app.py", default_timeout=90)
    app.query_params["model"] = "xiaomi/mimo-v2.5"

    app.run()

    assert not app.exception
    assert "model" not in app.query_params


def test_openrouter_intelligence_hides_official_market_panel(monkeypatch) -> None:
    monkeypatch.setenv("DATA_SOURCE", "local")
    app = AppTest.from_file("dashboard/app.py", default_timeout=120)
    app.session_state["main_section"] = "OpenRouter Intelligence"

    app.run()

    assert not app.exception
    rendered_markdown = "\n".join(str(markdown.value) for markdown in app.markdown)
    assert "Tracks model and provider usage" in rendered_markdown
    assert "Official Daily Market Volume" not in rendered_markdown
    assert "Context Length Usage" not in rendered_markdown
    assert "Modality Rankings" not in rendered_markdown
    assert "App Rankings & Trends" not in rendered_markdown
    assert any("‘Other’ is not the missing-provider gap" in str(caption.value) for caption in app.caption)


def test_openrouter_workloads_contains_context_modality_and_apps(monkeypatch) -> None:
    monkeypatch.setenv("DATA_SOURCE", "local")
    app = AppTest.from_file("dashboard/app.py", default_timeout=120)
    app.session_state["main_section"] = "OpenRouter Workloads"

    app.run()

    assert not app.exception
    rendered_markdown = "\n".join(str(markdown.value) for markdown in app.markdown)
    assert "Context Length Usage" in rendered_markdown
    assert "Modality Rankings" in rendered_markdown
    assert "App Rankings & Trends" in rendered_markdown
    assert "Provider Revenue &amp; Token Volume" not in rendered_markdown


def test_provider_incident_section_renders_live_history_and_coverage(monkeypatch) -> None:
    monkeypatch.setenv("DATA_SOURCE", "local")
    app = AppTest.from_file("dashboard/app.py", default_timeout=90)
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
    app = AppTest.from_file("dashboard/app.py", default_timeout=90)
    app.session_state["dashboard_area"] = "Adoption"
    app.session_state["main_section"] = "AI Hiring Demand"
    app.session_state["dashboard_view_Adoption"] = "AI Hiring Demand"

    app.run()

    assert not app.exception
    # Macro signal, intensity, cohort, role/seniority heatmap, and concentration
    # chart should all render when the fixture is populated.
    assert len(app.get("plotly_chart")) >= 5
    assert len(app.dataframe) == 3
