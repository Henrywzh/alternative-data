import importlib.util
import json
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "apps" / "asia-markets-streamlit" / "app.py"
APP_SPEC = importlib.util.spec_from_file_location("asia_markets_streamlit_app_crypto", APP_PATH)
assert APP_SPEC and APP_SPEC.loader
asia_app = importlib.util.module_from_spec(APP_SPEC)
APP_SPEC.loader.exec_module(asia_app)


def _artifact(language: str = "en") -> dict:
    suffix = "-zh" if language == "zh" else ""
    path = REPO_ROOT / "apps" / "asia-markets-dashboard" / ".generated" / f"hk-stablecoin-crypto-artifact{suffix}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_crypto_attention_chart_contract_is_present_in_both_local_artifacts() -> None:
    expected = {
        "wikipedia_crypto_attention_agent_weekly_chart",
        "wikipedia_crypto_user_attention_monthly_chart",
    }
    for language in ("en", "zh"):
        artifact = _artifact(language)
        chart_ids = {item["id"] for item in artifact["manifest"]["charts"]}
        assert expected <= chart_ids
        assert len(artifact["snapshot"]["datasets"]["wikipedia_crypto_attention_agent_weekly"]) > 0
        assert len(artifact["snapshot"]["datasets"]["wikipedia_crypto_user_attention_monthly"]) > 0


def test_weekly_attention_supports_week_over_week_and_year_over_year_views() -> None:
    frame = pd.DataFrame(
        {
            "series": ["user"] * 54,
            "_date": pd.date_range("2025-01-06", periods=54, freq="7D"),
            "views": list(range(100, 154)),
        }
    )
    wow, wow_label, _ = asia_app.line_view_frame(frame, "views", "series", "WoW %", 52, "pct", "number")
    yoy, yoy_label, _ = asia_app.line_view_frame(frame, "views", "series", "YoY %", 52, "pct", "number")
    assert wow_label == "WoW %"
    assert yoy_label == "YoY %"
    assert len(wow) == 53
    assert len(yoy) == 2
    assert asia_app.view_label("zh", "WoW %") == "周环比 %"


def test_fear_greed_daily_and_rolling_average_views_render() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=120)
    app.session_state["page"] = "crypto"
    app.session_state["language_choice"] = "English"
    app.run()

    assert not app.exception
    metric_view = next(radio for radio in app.radio if radio.label == "Metric")
    assert metric_view.value == "Both"
    assert {metric.label for metric in app.metric} >= {
        "Fear & Greed daily",
        "Fear & Greed 7-day avg",
    }
    metric_view.set_value("7-day rolling average")
    app.run()
    assert not app.exception


def test_crypto_policy_pulse_renders_separate_official_and_expectations_layers() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=120)
    app.session_state["page"] = "crypto"
    app.session_state["language_choice"] = "中文"
    app.run()

    assert not app.exception
    rendered = "\n".join(str(item.value) for item in app.markdown)
    assert "香港监管与政策脉搏" in rendered
    assert "政策时间线" in rendered
    assert any("市场预期" in str(item.label) for item in app.expander)
    assert any("公司公告" in str(item.label) for item in app.expander)
    assert len(app.get("plotly_chart")) >= 6
    assert len(app.dataframe) >= 1
