from pathlib import Path
import sys

import pandas as pd


APP_DIR = Path(__file__).resolve().parents[2] / "apps" / "asia-markets-streamlit"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from am.events_consensus import (  # noqa: E402
    _priority_band,
    _priority_legend,
    _style_timeline_frame,
    _timeline_frame,
)


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


def test_priority_bands_use_the_existing_risk_score_scale() -> None:
    assert _priority_band(70) == "high"
    assert _priority_band(69.9) == "medium"
    assert _priority_band(50) == "medium"
    assert _priority_band(49.9) == "low"
    assert _priority_band(None) == "unknown"


def test_provider_importance_one_always_gets_high_priority() -> None:
    assert _priority_band(40, provider_importance=1) == "high"
    assert _priority_band(40, provider_importance="1") == "high"
    assert _priority_band(69.9, provider_importance=0) == "medium"


def test_priority_legend_explains_provider_override() -> None:
    assert "provider 1 or score ≥70" in _priority_legend("en")
    assert "数据商1或评分≥70" in _priority_legend("zh")


def test_timeline_exposes_bilingual_priority_labels() -> None:
    events = pd.DataFrame(
        [
            {
                "scheduled_at_utc": "2026-09-18T12:30:00Z",
                "country": "US",
                "title": "High event",
                "snapshot_stage": "watch",
                "risk_score": 80,
                "verification_status": "third_party_consensus",
            },
            {
                "scheduled_at_utc": "2026-09-19T12:30:00Z",
                "country": "CN",
                "title": "Medium event",
                "snapshot_stage": "watch",
                "risk_score": 60,
                "verification_status": "third_party_consensus",
            },
            {
                "scheduled_at_utc": "2026-09-20T12:30:00Z",
                "country": "KR",
                "title": "Low event",
                "snapshot_stage": "watch",
                "risk_score": 40,
                "verification_status": "third_party_consensus",
            },
        ]
    )

    english = _timeline_frame(events, language="en", timezone_name="UTC")
    chinese = _timeline_frame(events, language="zh", timezone_name="UTC")

    assert english["Priority"].tolist() == ["🔴 High", "🟠 Medium", "⚪ Low"]
    assert chinese["重要性"].tolist() == ["🔴 高", "🟠 中", "⚪ 低"]


def test_provider_high_priority_is_styled_even_when_score_is_below_high_band() -> None:
    events = pd.DataFrame(
        [
            {
                "scheduled_at_utc": "2026-09-18T12:30:00Z",
                "importance": 1,
                "risk_score": 40,
            }
        ]
    )
    view = _timeline_frame(events, language="en", timezone_name="UTC")

    assert view["Priority"].tolist() == ["🔴 High"]
    html = _style_timeline_frame(
        view,
        language="en",
        provider_importance=events["importance"],
    ).to_html()
    assert "#fee2e2" in html


def test_timeline_priority_cells_are_colored() -> None:
    events = pd.DataFrame(
        [
            {"scheduled_at_utc": "2026-09-18T12:30:00Z", "risk_score": 80},
            {"scheduled_at_utc": "2026-09-19T12:30:00Z", "risk_score": 60},
            {"scheduled_at_utc": "2026-09-20T12:30:00Z", "risk_score": 40},
        ]
    )
    view = _timeline_frame(events, language="en", timezone_name="UTC")
    html = _style_timeline_frame(view, language="en").to_html()

    assert "#fee2e2" in html
    assert "#fef3c7" in html
    assert "#f1f5f9" in html
