from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_market_monitor_has_internal_events_mode() -> None:
    source = (
        ROOT / "apps" / "asia-markets-streamlit" / "am" / "market_page.py"
    ).read_text(encoding="utf-8")
    assert 'mode_keys = ("markets", "events")' in source
    assert "render_events_consensus(language)" in source


def test_navigation_is_read_only_and_refresh_is_explicit() -> None:
    source = (
        ROOT / "apps" / "asia-markets-streamlit" / "am" / "events_consensus.py"
    ).read_text(encoding="utf-8")
    assert "if refresh:" in source
    assert "_run_manual_refresh()" in source
    assert "run_pipeline(trigger_type=\"manual\", write=True)" in source
