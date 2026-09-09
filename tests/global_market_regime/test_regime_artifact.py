"""Integration guards for the Streamlit-only regime artifact."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[2]
BUILDER_PATH = (
    ROOT
    / "apps"
    / "asia-markets-dashboard"
    / "scripts"
    / "build_global_market_regime_artifact.py"
)
APP_PATH = ROOT / "apps" / "asia-markets-streamlit" / "app.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("global_market_regime_artifact", BUILDER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_streamlit_module():
    spec = importlib.util.spec_from_file_location(
        "asia_markets_streamlit_regime_test",
        APP_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _complete_builder_inputs(run_id: str = "run-a"):
    date = "2026-09-03"
    latest = pd.DataFrame(
        [
            {
                "indicator_id": indicator_id,
                "label_en": indicator_id,
                "label_zh": indicator_id,
                "state": "Normal",
                "value": value,
                "observation_date": date,
                "freshness": "Last session",
                "consecutive_breach": 0,
            }
            for indicator_id, value in (
                ("brent", 95.0),
                ("us10y", 4.5),
                ("hike_prob", 40.0),
                ("fomc_hike", 30.0),
                ("credit_vix", 0.0),
            )
        ]
    )
    frames = {
        "fred_observations": pd.DataFrame(
            [{"date": date, "indicator_id": "brent", "value": 95.0, "unit": "USD/bbl"}]
        ),
        "hike_probability": pd.DataFrame(
            [{"date": date, "value": 40.0, "hold_prob": 50.0, "cut_prob": 10.0}]
        ),
        "condition_states": pd.DataFrame(
            [
                {
                    "date": date,
                    "indicator_id": row["indicator_id"],
                    "value": row["value"],
                    "state": "Normal",
                    "breached": False,
                    "consecutive_breach": 0,
                }
                for row in latest.to_dict("records")
            ]
        ),
        "latest_conditions": latest,
        "source_health": pd.DataFrame(
            [
                {
                    "source": "fixture",
                    "series_id": "fixture",
                    "status": "Healthy",
                    "latest_observation": date,
                    "records": 1,
                    "notes": "fixture",
                }
            ]
        ),
        "cross_asset_prices": pd.DataFrame(
            [{"date": date, "exposure_id": "sp500", "close": 100.0}]
        ),
        "cot_history": pd.DataFrame(
            [
                {
                    "date": date,
                    "contract_id": "spx",
                    "label_en": "S&P 500",
                    "label_zh": "标普500",
                    "net": 1,
                    "percentile": 50.0,
                }
            ]
        ),
        "cot_latest": pd.DataFrame(
            [
                {
                    "date": date,
                    "contract_id": "spx",
                    "label_en": "S&P 500",
                    "label_zh": "标普500",
                    "net": 1,
                    "percentile": 50.0,
                }
            ]
        ),
        "fomc_history": pd.DataFrame(
            [{"date": date, "hike_prob": 30.0, "hold_prob": 60.0, "cut_prob": 10.0}]
        ),
    }
    lineages = {name: {"run_id": run_id} for name in frames}
    return frames, lineages


def test_artifact_is_degraded_when_datasets_come_from_different_runs(monkeypatch) -> None:
    builder = _load_builder()
    frames = {
        "fred_observations": pd.DataFrame(
            [{"date": "2026-09-03", "indicator_id": "brent", "value": 95.0, "unit": "USD/bbl"}]
        ),
        "latest_conditions": pd.DataFrame(
            [
                {
                    "indicator_id": "brent",
                    "label_en": "Brent crude",
                    "label_zh": "布伦特原油",
                    "state": "Normal",
                    "value": 95.0,
                    "observation_date": "2026-09-03",
                    "freshness": "Last session",
                }
            ]
        ),
        "source_health": pd.DataFrame(
            [
                {
                    "source": "FRED / EIA",
                    "series_id": "DCOILBRENTEU",
                    "status": "Healthy",
                    "latest_observation": "2026-09-03",
                    "records": 1,
                    "notes": "fixture",
                }
            ]
        ),
    }
    lineages = {
        "fred_observations": {"run_id": "run-a"},
        "latest_conditions": {"run_id": "run-b"},
        "source_health": {"run_id": "run-b"},
    }

    monkeypatch.setattr(
        builder,
        "_load",
        lambda name, derived=False: (
            frames.get(name, pd.DataFrame()),
            lineages.get(name),
        ),
    )

    artifact, status = builder.build_artifact()

    assert artifact["package_info"]["runConsistent"] is False
    assert artifact["snapshot"]["status"] == "partial"
    assert status["overall_status"] == "Degraded"
    assert {
        "regime_summary",
        "domain_summary",
        "threshold_monitor",
        "condition_state_history",
        "state_transition_history",
        "credit_vix_signal_history",
        "cot_history",
        "cross_asset_returns",
        "signal_episodes",
        "threshold_sensitivity",
        "event_forward_returns",
        "event_forward_summary",
        "alert_status",
    } <= set(artifact["snapshot"]["datasets"])


def test_artifact_is_degraded_when_a_required_run_dataset_is_missing(monkeypatch) -> None:
    builder = _load_builder()
    frames = {
        "fred_observations": pd.DataFrame(
            [{"date": "2026-09-03", "indicator_id": "brent", "value": 95.0}]
        ),
        "latest_conditions": pd.DataFrame(
            [
                {
                    "indicator_id": "brent",
                    "state": "Normal",
                    "value": 95.0,
                    "observation_date": "2026-09-03",
                    "freshness": "Last session",
                }
            ]
        ),
    }
    lineages = {
        "fred_observations": {"run_id": "run-a"},
        "latest_conditions": {"run_id": "run-a"},
    }
    monkeypatch.setattr(
        builder,
        "_load",
        lambda name, derived=False: (
            frames.get(name, pd.DataFrame()),
            lineages.get(name),
        ),
    )

    artifact, status = builder.build_artifact()

    assert artifact["package_info"]["runConsistent"] is False
    assert artifact["snapshot"]["status"] == "partial"
    assert status["overall_status"] == "Degraded"


def test_artifact_is_degraded_when_cot_latest_comes_from_another_run(monkeypatch) -> None:
    builder = _load_builder()
    frames, lineages = _complete_builder_inputs()
    lineages["cot_latest"] = {"run_id": "run-b"}
    monkeypatch.setattr(
        builder,
        "_load",
        lambda name, derived=False: (frames.get(name, pd.DataFrame()), lineages.get(name)),
    )

    artifact, status = builder.build_artifact()

    assert artifact["package_info"]["runConsistent"] is False
    assert status["overall_status"] == "Degraded"


def test_artifact_is_degraded_when_any_source_is_degraded(monkeypatch) -> None:
    builder = _load_builder()
    frames, lineages = _complete_builder_inputs()
    frames["source_health"].loc[0, "status"] = "Degraded"
    monkeypatch.setattr(
        builder,
        "_load",
        lambda name, derived=False: (frames.get(name, pd.DataFrame()), lineages.get(name)),
    )

    artifact, status = builder.build_artifact()

    assert artifact["package_info"]["runConsistent"] is True
    assert artifact["snapshot"]["status"] == "partial"
    assert status["overall_status"] == "Degraded"


@pytest.mark.parametrize(
    ("last_decision", "events", "defensive_eligible", "expected_decision"),
    [
        ("quiet", [], False, "quiet"),
        (
            "component_preview",
            [
                {
                    "indicator_id": "us10y",
                    "domain_id": "rates_policy",
                    "label_en": "US 10-year Treasury yield",
                    "label_zh": "美国10年期国债收益率",
                    "from_state": "Normal",
                    "to_state": "Watch",
                    "value": 4.9,
                    "observation_date": "2026-09-03",
                    "event_key": "us10y|Normal|Watch|2026-09-03",
                }
            ],
            False,
            "component_preview",
        ),
        (
            "defensive_eligible",
            [
                {
                    "indicator_id": "credit_vix",
                    "domain_id": "financial_stress",
                    "label_en": "Credit and VIX",
                    "label_zh": "信用利差与VIX",
                    "from_state": "Watch",
                    "to_state": "Confirmed",
                    "value": 1.2,
                    "observation_date": "2026-09-03",
                    "event_key": "credit_vix|Watch|Confirmed|2026-09-03",
                }
            ],
            True,
            "defensive_eligible",
        ),
    ],
)
def test_alert_status_exports_the_last_pipeline_decision(
    last_decision,
    events,
    defensive_eligible,
    expected_decision,
) -> None:
    builder = _load_builder()
    summary = {
        "alert_eligible": True,
        "defensive_alert_eligible": defensive_eligible,
        "breadth_id": "broadening" if defensive_eligible else "narrow",
        "active_domain_ids": ["rates_policy"],
        "confirmed_domain_count": 2 if defensive_eligible else 1,
        "total_domain_count": 3,
        "overall_state": "Confirmed" if defensive_eligible else "Watch",
    }
    domains = pd.DataFrame(
        [
            {"domain_id": "rates_policy", "state": "Confirmed"},
            {
                "domain_id": "financial_stress",
                "state": "Confirmed" if defensive_eligible else "Normal",
            },
        ]
    )
    state = {
        "last_run_id": "run-a",
        "last_evaluation_at": "2026-09-03T12:01:00Z",
        "last_decision": last_decision,
        "last_component_events": events,
        "alert_mode": "preview",
        "last_sent_at": None,
    }

    result = builder._build_alert_status(
        summary,
        domains,
        state,
        latest_run_id="run-a",
    )

    assert result["decision_id"] == expected_decision
    assert result["evaluation_current"] is True
    assert result["new_transition_count"] == len(events)
    assert result["component_events"] == events
    assert result["would_send_in_defensive_mode"] is defensive_eligible
    assert result["should_send"] is False


def test_alert_status_fails_closed_when_evaluation_is_missing_or_old() -> None:
    builder = _load_builder()
    summary = {
        "alert_eligible": True,
        "defensive_alert_eligible": True,
        "confirmed_domain_count": 2,
        "total_domain_count": 3,
    }

    missing = builder._build_alert_status(
        summary,
        pd.DataFrame(),
        {},
        latest_run_id="run-new",
    )
    old = builder._build_alert_status(
        summary,
        pd.DataFrame(),
        {
            "last_run_id": "run-old",
            "last_evaluation_at": "2026-09-02T12:00:00Z",
            "last_decision": "component_preview",
            "last_component_events": [{"indicator_id": "brent"}],
        },
        latest_run_id="run-new",
    )

    assert missing["decision_id"] == "unavailable"
    assert missing["evaluation_current"] is False
    assert old["decision_id"] == "unavailable"
    assert old["evaluation_current"] is False


def test_alert_status_rejects_invalid_time_and_persisted_decision_conflicts() -> None:
    builder = _load_builder()
    summary = {
        "alert_eligible": True,
        "defensive_alert_eligible": False,
        "confirmed_domain_count": 0,
        "total_domain_count": 3,
    }
    event = {
        "indicator_id": "us10y",
        "from_state": "Normal",
        "to_state": "Watch",
        "observation_date": "2026-09-03",
    }
    invalid_time = builder._build_alert_status(
        summary,
        pd.DataFrame(),
        {
            "last_run_id": "run-a",
            "last_evaluation_at": "not-a-time",
            "last_decision": "quiet",
            "last_component_events": [],
        },
        latest_run_id="run-a",
    )
    conflicting = builder._build_alert_status(
        summary,
        pd.DataFrame(),
        {
            "last_run_id": "run-a",
            "last_evaluation_at": "2026-09-03T12:00:00Z",
            "last_decision": "quiet",
            "last_component_events": [event],
        },
        latest_run_id="run-a",
    )

    assert invalid_time["decision_id"] == "unavailable"
    assert invalid_time["evaluation_current"] is False
    assert conflicting["decision_id"] == "unavailable"
    assert conflicting["component_events"] == []


def test_alert_status_boolean_contract_fails_closed() -> None:
    builder = _load_builder()
    result = builder._build_alert_status(
        {
            "alert_eligible": "false",
            "defensive_alert_eligible": float("nan"),
            "confirmed_domain_count": 0,
            "total_domain_count": 3,
        },
        pd.DataFrame(),
        {
            "last_run_id": "run-a",
            "last_evaluation_at": "2026-09-03T12:00:00Z",
            "last_decision": "quiet",
            "last_component_events": [],
        },
        latest_run_id="run-a",
    )

    assert result["alert_eligible"] is False
    assert result["defensive_alert_eligible"] is False
    assert result["decision_id"] == "unavailable"


def test_workflow_does_not_inject_gmail_secrets_in_preview_mode() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "global-market-regime-daily.yml"
    ).read_text(encoding="utf-8")

    assert "--alert-mode preview" in workflow
    assert "GMAIL_SENDER" not in workflow
    assert "GMAIL_APP_PASSWORD" not in workflow
    assert "GMAIL_RECIPIENTS" not in workflow


def test_workflow_pins_external_actions_to_commits() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "global-market-regime-daily.yml"
    ).read_text(encoding="utf-8")
    uses = [
        line.strip().split("@", 1)[1].split()[0]
        for line in workflow.splitlines()
        if "uses: actions/" in line
    ]

    assert uses
    assert all(len(revision) == 40 for revision in uses)
    assert all(set(revision) <= set("0123456789abcdef") for revision in uses)


def test_workflow_scopes_fred_secret_to_fetch_step() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "global-market-regime-daily.yml"
    ).read_text(encoding="utf-8")
    before_fetch, after_fetch = workflow.split(
        "      - name: Fetch and derive regime states", 1
    )
    fetch_step = after_fetch.split("      - name: Build Streamlit artifact", 1)[0]

    assert "FRED_API_KEY:" not in before_fetch
    assert "FRED_API_KEY:" in fetch_step


def test_artifact_write_is_atomic_on_interruption(monkeypatch, tmp_path) -> None:
    builder = _load_builder()
    output = tmp_path / "global-market-regime-artifact.json"
    zh_output = tmp_path / "global-market-regime-artifact-zh.json"
    output.write_text("previous-en", encoding="utf-8")
    zh_output.write_text("previous-zh", encoding="utf-8")
    artifact = {
        "manifest": {"title": "Global Market Regime", "description": "English"},
        "snapshot": {"datasets": {}},
        "sources": [],
    }
    monkeypatch.setattr(
        builder,
        "build_artifact",
        lambda: (artifact, {"snapshot_id": "x", "data_as_of": "2026-09-04"}),
    )
    monkeypatch.setattr(
        builder.sys,
        "argv",
        ["builder", "--output", str(output)],
    )
    real_write_text = Path.write_text

    def interrupted_write(path, payload, *args, **kwargs):
        real_write_text(path, "{", encoding=kwargs.get("encoding", "utf-8"))
        raise OSError("simulated interruption")

    monkeypatch.setattr(Path, "write_text", interrupted_write)

    with pytest.raises(OSError, match="simulated interruption"):
        builder.main()

    assert output.read_text(encoding="utf-8") == "previous-en"
    assert zh_output.read_text(encoding="utf-8") == "previous-zh"


def test_artifact_pair_is_not_partially_published_when_second_write_fails(
    monkeypatch, tmp_path
) -> None:
    builder = _load_builder()
    output = tmp_path / "global-market-regime-artifact.json"
    zh_output = tmp_path / "global-market-regime-artifact-zh.json"
    output.write_text("previous-en", encoding="utf-8")
    zh_output.write_text("previous-zh", encoding="utf-8")
    artifact = {
        "manifest": {"title": "Global Market Regime", "description": "English"},
        "snapshot": {"datasets": {}},
        "sources": [],
    }
    monkeypatch.setattr(
        builder,
        "build_artifact",
        lambda: (artifact, {"snapshot_id": "x", "data_as_of": "2026-09-04"}),
    )
    monkeypatch.setattr(
        builder.sys,
        "argv",
        ["builder", "--output", str(output)],
    )
    real_write_text = Path.write_text
    write_count = 0

    def fail_second_write(path, payload, *args, **kwargs):
        nonlocal write_count
        write_count += 1
        if write_count == 2:
            real_write_text(path, "{", encoding=kwargs.get("encoding", "utf-8"))
            raise OSError("simulated second-write interruption")
        return real_write_text(
            path,
            payload,
            encoding=kwargs.get("encoding", "utf-8"),
        )

    monkeypatch.setattr(Path, "write_text", fail_second_write)

    with pytest.raises(OSError, match="second-write interruption"):
        builder.main()

    assert output.read_text(encoding="utf-8") == "previous-en"
    assert zh_output.read_text(encoding="utf-8") == "previous-zh"


def test_storage_rejects_snapshot_with_invalid_checksum(tmp_path) -> None:
    from global_market_regime.storage import _write_run_dataset, load_latest_with_lineage

    saved = _write_run_dataset(
        tmp_path,
        "fixture",
        pd.DataFrame([{"value": 1.0}]),
        run_id="run-a",
    )
    lineage_path = Path(saved["lineage"])
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    lineage["sha256"] = "0" * 64
    lineage_path.write_text(json.dumps(lineage), encoding="utf-8")

    frame, loaded_lineage = load_latest_with_lineage(tmp_path, "fixture")

    assert frame.empty
    assert loaded_lineage is None


def test_storage_rejects_full_snapshot_without_explicit_scope(tmp_path) -> None:
    from global_market_regime.storage import _write_run_dataset, load_latest_with_lineage

    saved = _write_run_dataset(
        tmp_path,
        "fixture",
        pd.DataFrame([{"value": 1.0}]),
        run_id="run-a",
    )
    lineage_path = Path(saved["lineage"])
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    lineage.pop("run_scope")
    lineage_path.write_text(json.dumps(lineage), encoding="utf-8")

    frame, loaded_lineage = load_latest_with_lineage(
        tmp_path,
        "fixture",
        scope="full",
    )

    assert frame.empty
    assert loaded_lineage is None


def test_artifact_is_degraded_when_a_source_health_row_is_missing(monkeypatch) -> None:
    builder = _load_builder()
    frames, lineages = _complete_builder_inputs()
    monkeypatch.setattr(
        builder,
        "_load",
        lambda name, derived=False: (frames.get(name, pd.DataFrame()), lineages.get(name)),
    )

    artifact, status = builder.build_artifact()

    assert artifact["package_info"]["runConsistent"] is True
    assert artifact["snapshot"]["status"] == "partial"
    assert status["overall_status"] == "Degraded"


def test_overview_kpi_is_unavailable_when_all_conditions_are_stale(monkeypatch) -> None:
    builder = _load_builder()
    frames, lineages = _complete_builder_inputs()
    frames["latest_conditions"]["freshness"] = "Stale"
    monkeypatch.setattr(
        builder,
        "_load",
        lambda name, derived=False: (frames.get(name, pd.DataFrame()), lineages.get(name)),
    )

    artifact, _ = builder.build_artifact()

    assert artifact["snapshot"]["datasets"]["regime_summary"][0]["overall_state"] == "Unavailable"
    assert artifact["snapshot"]["datasets"]["kpi_regime"][0]["overall_state"] == "Unavailable"


def test_zh_artifact_localizes_source_health() -> None:
    builder = _load_builder()
    artifact = {
        "manifest": {"title": "Global Market Regime", "description": "English"},
        "sources": [{"id": "brent", "label": "FRED / EIA · Brent crude"}],
        "snapshot": {
            "datasets": {
                "source_health": [
                    {
                        "source": "FRED / EIA",
                        "series_id": "DCOILBRENTEU",
                        "status": "Healthy",
                        "latest_observation": "2026-09-01",
                        "notes": "Daily Brent crude.",
                    }
                ]
            }
        },
    }

    localized = builder._localized_zh_artifact(artifact)

    row = localized["snapshot"]["datasets"]["source_health"][0]
    assert localized["manifest"]["title"] == "全球市场状态"
    assert row["source"] == "FRED／美国能源信息署"
    assert row["notes"] == "布伦特原油日度数据，截至2026-09-01。"
    assert localized["sources"][0]["label"] == "FRED／美国能源信息署 · 布伦特原油"


def test_zh_artifact_preserves_degraded_source_diagnostic() -> None:
    builder = _load_builder()
    artifact = {
        "manifest": {"title": "Global Market Regime", "description": "English"},
        "sources": [],
        "snapshot": {
            "datasets": {
                "source_health": [
                    {
                        "source": "FRED / EIA",
                        "series_id": "DCOILBRENTEU",
                        "status": "Unavailable",
                        "latest_observation": "—",
                        "notes": "HTTP 503 from upstream.",
                    }
                ]
            }
        },
    }

    localized = builder._localized_zh_artifact(artifact)

    row = localized["snapshot"]["datasets"]["source_health"][0]
    assert row["notes"] == "来源状态异常：HTTP 503 from upstream."


def test_localized_source_health_aligns_by_series_id_not_row_position() -> None:
    app = _load_streamlit_module()
    generated_at = "2026-09-04T00:00:00Z"
    current = {
        "snapshot": {
            "generatedAt": generated_at,
            "datasets": {
                "source_health": [
                    {
                        "series_id": "a",
                        "source": "Source A",
                        "status": "Healthy",
                        "latest_observation": "2026-09-04",
                        "records": 10,
                        "notes": "A",
                    },
                    {
                        "series_id": "b",
                        "source": "Source B",
                        "status": "Degraded",
                        "latest_observation": "2026-09-03",
                        "records": 20,
                        "notes": "B",
                    },
                ]
            },
        }
    }
    localized = {
        "snapshot": {
            "generatedAt": generated_at,
            "datasets": {
                "source_health": [
                    {
                        "series_id": "b",
                        "source": "来源乙",
                        "status": "Healthy",
                        "latest_observation": "old",
                        "records": 999,
                        "notes": "乙",
                    },
                    {
                        "series_id": "a",
                        "source": "来源甲",
                        "status": "Healthy",
                        "latest_observation": "old",
                        "records": 999,
                        "notes": "甲",
                    },
                ]
            },
        }
    }

    result = app.localized_source_health_frame(current, localized, "zh")

    assert result["series_id"].tolist() == ["a", "b"]
    assert result["source"].tolist() == ["来源甲", "来源乙"]
    assert result["status"].tolist() == ["健康", "需留意"]
    assert result["records"].tolist() == [10, 20]


@pytest.mark.parametrize(
    ("language_choice", "expected_labels", "expected_alert_title"),
    [
        (
            "English",
            {"Brent crude", "US 10-year yield", "Next FOMC hike odds"},
            "No alert needed",
        ),
        (
            "中文",
            {"布伦特原油", "美国10年期国债收益率", "下次FOMC加息赔率"},
            "无需提醒",
        ),
    ],
)
def test_streamlit_regime_page_renders_without_exceptions(
    language_choice: str,
    expected_labels: set[str],
    expected_alert_title: str,
) -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=120)
    app.session_state["page"] = "regime"
    app.session_state["language_choice"] = language_choice
    app.run()

    assert not app.exception
    rendered = "\n".join(str(markdown.value) for markdown in app.markdown)
    assert all(label in rendered for label in expected_labels)
    assert expected_alert_title in rendered
