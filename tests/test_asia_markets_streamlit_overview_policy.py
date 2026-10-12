"""Market-first overview: bounded layout and honest publication evidence."""

from pathlib import Path
import sys

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

APP_DIR = Path(__file__).resolve().parents[1] / "apps" / "asia-markets-streamlit"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from am.config import OVERVIEW_PULSE_CONFIG, sector_region
from am.overview import overview_source_summary, sector_source_status, set_app_page
from am.overview_policy import ECONOMIC_SECTORS, economic_observation_rows


def artifact(key, **fields):
    metric = OVERVIEW_PULSE_CONFIG[key]["metrics"][0]
    return {
        "package_info": {"dataAsOf": "2026-10-12", "generatedAt": "2026-10-12"},
        "snapshot": {"datasets": {metric["dataset"]: [
            {"date": "2026-08-01", metric["field"]: 10, **fields},
        ]}},
    }


def test_build_date_and_observation_are_never_promoted_to_publication():
    rows = economic_observation_rows(
        {key: artifact(key) for key in ECONOMIC_SECTORS}, "zh", now="2026-10-12",
    )
    assert len(rows) == 4
    assert all(pd.isna(row["release"]) and not row["recent_release"] for row in rows)


def test_only_known_recent_publication_reorders_economic_rows():
    rows = economic_observation_rows({
        "real_estate": artifact("real_estate", release_date="2026-08-02"),
        "labour": artifact("labour", publication_date="2026-10-03"),
        "transport": artifact("transport", announcement_date="2026-10-08"),
    }, "en", now="2026-10-12")
    assert [row["sector"] for row in rows] == ["transport", "labour", "real_estate"]
    assert [row["recent_release"] for row in rows] == [True, True, False]


@pytest.mark.parametrize("release", ["2026-10-13", "not a date", None])
def test_future_invalid_and_missing_release_are_not_promoted(release):
    rows = economic_observation_rows({"labour": artifact("labour", release_date=release)}, "zh", now="2026-10-12")
    assert pd.isna(rows[0]["release"])
    assert not rows[0]["recent_release"]


def test_daily_immigration_and_missing_measure_are_not_population_release():
    data = artifact("population", release_date="2026-10-10")
    metric = OVERVIEW_PULSE_CONFIG["population"]["metrics"][0]
    data["snapshot"]["datasets"][metric["dataset"]][0][metric["field"]] = None
    data["snapshot"]["datasets"]["immd_net_flow"] = [{"date": "2026-10-12", "release_date": "2026-10-12"}]
    rows = economic_observation_rows({"population": data}, "zh", now="2026-10-12")
    assert rows[0]["value"] == "—"
    assert not rows[0]["recent_release"]


def test_missing_health_is_unknown_not_inferred_from_source_labels():
    data = {"sources": [{"status": "Ready"}], "snapshot": {}}
    summary = overview_source_summary({"labour": data}, {"labour": data})
    assert summary == {"total": 1, "healthy": 0, "attention": 0, "problem": 1, "missing_metadata": 1}
    assert sector_source_status(data, data, "zh") == "健康状态未知"


def test_correct_region_labels_do_not_change_slugs():
    assert sector_region("aerospace", "zh") == "中国／全球背景"
    assert sector_region("crypto", "en") == "Global / Hong Kong policy"
    assert sector_region("market", "zh") == "跨市场"
    assert sector_region("labour", "zh") == "香港"


def test_overview_buttons_use_native_routes(monkeypatch):
    import am.page_registry as registry
    import am.overview as overview

    destination = object()
    calls = []
    monkeypatch.setattr(registry, "build_streamlit_pages", lambda: {"market": destination})
    monkeypatch.setattr(overview.st, "switch_page", calls.append)
    set_app_page("market")
    assert calls == [destination]


def test_overview_switch_runs_after_button_not_inside_callback(monkeypatch):
    import am.overview as overview

    calls = []
    def clicked(label, **kwargs):
        assert "on_click" not in kwargs
        assert label == "ETF"
        return True
    monkeypatch.setattr(overview.st, "button", clicked)
    monkeypatch.setattr(overview, "set_app_page", calls.append)
    overview.overview_page_button("ETF", "open_etf", "market")
    assert calls == ["market"]


@pytest.mark.parametrize("language", ["中文", "English"])
def test_overview_has_two_market_cards_and_four_compact_economic_rows(language):
    app = AppTest.from_file(str(APP_DIR / "app.py"), default_timeout=120)
    app.session_state["language_choice"] = language
    app.run()
    assert not app.exception, [str(error) for error in app.exception]
    html = "\n".join(str(item.value) for item in app.markdown)
    assert html.count('class="am-pulse-title"') == 2
    assert html.count('class="am-economic-row"') == 4
    assert {button.key for button in app.button if str(button.key).startswith("overview_open_")} == {
        "overview_open_regime", "overview_open_market", "overview_open_health",
    }
    assert not app.get("plotly_chart")  # Featured trends remain deliberately blank.


def test_empty_overview_artifacts_render_without_missing_manifest_crash(monkeypatch):
    import am.page_registry as registry

    monkeypatch.setattr(registry, "load_all_sector_artifacts", lambda _language: ({"market": {}}, {}, []))
    app = AppTest.from_file(str(APP_DIR / "app.py"), default_timeout=120).run()
    assert not app.exception, [str(error) for error in app.exception]
