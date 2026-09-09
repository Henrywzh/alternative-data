import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "apps" / "asia-markets-streamlit" / "app.py"
APP_SPEC = importlib.util.spec_from_file_location("asia_markets_streamlit_app", APP_PATH)
assert APP_SPEC and APP_SPEC.loader
asia_app = importlib.util.module_from_spec(APP_SPEC)
APP_SPEC.loader.exec_module(asia_app)

ARTIFACT_ROOT = REPO_ROOT / "apps" / "asia-markets-dashboard" / ".generated"


def _artifact(slug: str) -> dict:
    return json.loads((ARTIFACT_ROOT / f"{slug}-artifact.json").read_text(encoding="utf-8"))


def test_cross_asset_heatmap_keeps_selected_order_and_missing_values_blank() -> None:
    returns = pd.DataFrame(
        [
            {
                "exposure_id": "sp500",
                "date": "2026-09-03",
                "return_1d_pct": 0.25,
                "return_5d_pct": 1.5,
                "return_20d_pct": 3.0,
            },
            {
                "exposure_id": "hstech",
                "date": "2026-09-04",
                "return_1d_pct": -1.25,
                "return_5d_pct": None,
                "return_20d_pct": -4.0,
            },
            {
                "exposure_id": "hstech",
                "date": "invalid",
                "return_1d_pct": 99.0,
                "return_5d_pct": 99.0,
                "return_20d_pct": 99.0,
            },
        ]
    )

    heatmap = asia_app.cross_asset_return_heatmap_frame(
        returns,
        ["hstech", "sp500", "hstech"],
        "zh",
    )

    assert len(heatmap) == 6
    assert heatmap["exposure"].drop_duplicates().tolist() == ["恒生科技", "标普500"]
    assert heatmap["horizon"].drop_duplicates().tolist() == [
        "1个交易日",
        "5个交易日",
        "20个交易日",
    ]
    missing = heatmap[
        heatmap["exposure_id"].eq("hstech")
        & heatmap["horizon"].eq("5个交易日")
    ].iloc[0]
    assert pd.isna(missing["return_pct"])
    assert missing["as_of"] == "2026-09-04"
    assert (
        heatmap[
            heatmap["exposure_id"].eq("hstech")
            & heatmap["horizon"].eq("1个交易日")
        ]["return_pct"].iloc[0]
        == -1.25
    )

    english = asia_app.cross_asset_return_heatmap_frame(
        returns,
        ["hstech", "sp500"],
        "en",
    )
    assert english["exposure"].drop_duplicates().tolist() == [
        "Hang Seng TECH",
        "S&P 500",
    ]
    assert english["horizon"].drop_duplicates().tolist() == [
        "1 session",
        "5 sessions",
        "20 sessions",
    ]


def test_cross_asset_heatmap_figure_uses_symmetric_zero_scale_and_nan_gaps() -> None:
    returns = pd.DataFrame(
        [
            {
                "exposure_id": "sp500",
                "date": "2026-09-03",
                "return_1d_pct": 1.0,
                "return_5d_pct": None,
                "return_20d_pct": 4.0,
            },
            {
                "exposure_id": "hstech",
                "date": "2026-09-04",
                "return_1d_pct": -2.0,
                "return_5d_pct": -5.0,
                "return_20d_pct": 2.0,
            },
        ]
    )

    fig = asia_app.build_cross_asset_return_heatmap_figure(
        returns,
        ["sp500", "hstech"],
        "en",
    )

    assert fig is not None
    trace = fig.data[0]
    assert trace.zmin == -5.0
    assert trace.zmax == 5.0
    assert trace.zmid == 0
    assert trace.hoverongaps is False
    assert pd.isna(trace.z[0][1])
    assert list(trace.y) == ["S&P 500", "Hang Seng TECH"]
    assert {annotation.font.color for annotation in fig.layout.annotations} == {
        "#111827"
    }


def test_localized_source_health_keeps_current_observation_values() -> None:
    current = {
        "snapshot": {
            "generatedAt": "2026-08-30T00:00:00Z",
            "datasets": {
                "source_health": [
                    {
                        "source": "Official source",
                        "status": "Degraded",
                        "latest_observation": "2026-07-31",
                        "records": 12,
                    }
                ]
            }
        }
    }
    labels = {
        "snapshot": {
            "generatedAt": "2026-08-30T00:00:00Z",
            "datasets": {
                "source_health": [
                    {
                        "source": "官方来源",
                        "status": "需留意",
                        "latest_observation": "2026-05-31",
                        "records": 8,
                    }
                ]
            }
        }
    }

    frame = asia_app.localized_source_health_frame(current, labels, "zh")

    assert frame.iloc[0]["source"] == "官方来源"
    assert frame.iloc[0]["status"] == "需留意"
    assert frame.iloc[0]["latest_observation"] == "2026-07-31"
    assert frame.iloc[0]["records"] == 12


def test_localized_source_health_rejects_a_different_snapshot() -> None:
    current = {
        "snapshot": {
            "generatedAt": "2026-08-30T00:00:00Z",
            "datasets": {
                "source_health": [
                    {
                        "source": "Current official source",
                        "status": "Healthy",
                        "latest_observation": "2026-07-31",
                        "records": 12,
                    }
                ]
            },
        }
    }
    stale_labels = {
        "snapshot": {
            "generatedAt": "2026-08-01T00:00:00Z",
            "datasets": {
                "source_health": [
                    {
                        "source": "过时来源标签",
                        "status": "健康",
                        "latest_observation": "2026-05-31",
                        "records": 8,
                    }
                ]
            },
        }
    }

    frame = asia_app.localized_source_health_frame(current, stale_labels, "zh")

    assert frame.iloc[0]["source"] == "Current official source"
    assert frame.iloc[0]["latest_observation"] == "2026-07-31"


def test_overview_configuration_is_bounded() -> None:
    assert all(len(config.get("metrics", ())) <= 3 for config in asia_app.OVERVIEW_PULSE_CONFIG.values())
    assert len(asia_app.OVERVIEW_FEATURED_CHARTS) <= 2


def test_overview_helpers_read_real_artifact_values_and_dates() -> None:
    labour = _artifact("hk-labour-market")
    population = _artifact("hk-population-migration")

    label, unemployment, unemployment_date = asia_app.latest_metric_reading(
        labour,
        "kpi_labour_force",
        "unemployment_rate",
        "fraction",
        label_en="Unemployment rate",
        label_zh="失业率",
        language="en",
    )
    assert label == "Unemployment rate"
    _labour_kpi = labour["snapshot"]["datasets"]["kpi_labour_force"][-1]
    assert unemployment == f"{_labour_kpi['unemployment_rate']:.1%}"
    assert unemployment_date == datetime.strptime(
        _labour_kpi["observation_date"], "%Y-%m-%d"
    ).strftime("%d %b %Y")

    population_value, population_date = asia_app.latest_metric_reading(
        population,
        "csd_population",
        "mid_year_population_thousands",
        "number",
        label_en="Population ('000)",
        label_zh="人口（千人）",
        language="en",
    )[1:]
    # Derived from the artifact for the same reason as the net-flow reading
    # below: CSD both publishes new periods and revises published ones, so a
    # frozen literal goes stale from two directions. This pair was stale both
    # ways at once -- it asserted 7,510.8 / Dec 2025 while the artifact had
    # advanced to 2026-06 and revised Dec 2025 down to 7,508.7. The reader is
    # still under test: it must reproduce exactly what the artifact holds.
    _population_rows = population["snapshot"]["datasets"]["csd_population"]
    _latest_population = max(_population_rows, key=lambda row: row["period"])
    assert population_value == f"{_latest_population['mid_year_population_thousands']:,.1f}"
    assert population_date == datetime.strptime(
        _latest_population["period"], "%Y-%m"
    ).strftime("%d %b %Y")

    resident_flow, flow_date = asia_app.latest_series_reading(
        population,
        "immd_net_flow_chart",
        "HK Resident Net Flow",
        "number",
        "en",
    )
    # Derived from the artifact rather than frozen: this series is a daily
    # reading that moves with every refresh, so a hardcoded literal only
    # records which day the expectation was written (it was stale at -9,576
    # while the artifact had already advanced to 2026-08-07). The reader is
    # still under test -- it must reproduce exactly what the artifact holds.
    _flow_rows = [
        row
        for row in population["snapshot"]["datasets"]["immd_net_flow_history"]
        if row["series"] == "HK Resident Net Flow"
    ]
    _latest_flow = max(_flow_rows, key=lambda row: row["date"])
    assert resident_flow == f"{int(_latest_flow['value']):,}"
    assert flow_date == datetime.strptime(_latest_flow["date"], "%Y-%m-%d").strftime("%d %b %Y")

    labour_frame, labour_title, labour_latest, labour_range, labour_note = asia_app.sparkline_context(
        labour,
        asia_app.OVERVIEW_PULSE_CONFIG["labour"]["sparkline"],
        "en",
    )
    assert len(labour_frame) > 1
    assert labour_title == "Unemployment rate history"
    assert labour_latest == unemployment
    assert "–" in labour_range
    assert labour_note == "Monthly rolling-three-month rate"


def test_transport_exposes_expanded_airline_signals_and_six_carrier_labels() -> None:
    transport = _artifact("hk-transport")
    chart_ids = {item["id"] for item in transport["manifest"]["charts"]}
    expected_charts = {
        "china_airline_region_by_carrier_chart",
        "china_airline_cargo_chart",
        "china_airline_freight_load_factor_chart",
        "china_airline_fleet_total_chart",
        "china_airline_fleet_net_change_chart",
        "china_airline_new_route_chart",
    }
    assert expected_charts <= chart_ids
    assert {"Hainan", "Juneyao"} <= set(asia_app.CHINA_AIRLINE_SERIES_LABELS)
    assert {"Hainan", "Juneyao"} <= set(asia_app.CHINA_AIRLINE_SERIES_LABELS_ZH)

    explorer_options = asia_app.combined_dataset_index({"transport": transport}, "en")
    explorer_dataset_ids = {item[0].split(":", 1)[1] for item in explorer_options}
    assert {
        "china_airline_region_by_carrier_history",
        "china_airline_cargo_history",
        "china_airline_freight_load_factor_history",
        "china_airline_fleet_total_history",
        "china_airline_fleet_net_change_history",
        "china_airline_new_route_history",
        "china_airline_operating_events_latest",
    } <= explorer_dataset_ids

    region_rows = transport["snapshot"]["datasets"]["china_airline_region_by_carrier_history"]
    assert any(row["series"] == "Juneyao · Domestic" for row in region_rows)
    assert any(row["series"] == "Juneyao · Regional" for row in region_rows)


def test_no_sector_pulse_reuses_one_dataset_field_for_two_metrics() -> None:
    """Two metrics on the same (dataset, field) always render the same number.

    latest_metric_reading takes latest_row(frame) and reads row[field]; it has
    no way to select a row by metric name. The market pulse pointed both of its
    metrics at kpi_market's "value" column, because that dataset was long-form
    with one row per metric, and the overview showed "Small / Large z 42.9" --
    the CSI 300 RSI -- while the real z-score sat in the artifact at 1.66.
    """
    for sector_key, config in asia_app.OVERVIEW_PULSE_CONFIG.items():
        # `series` legitimately distinguishes two metrics that share a dataset
        # and field, so it is part of the identity; a source is either a
        # dataset or a chart_id.
        keys = [
            (metric.get("dataset") or metric.get("chart_id"), metric["field"], metric.get("series"))
            for metric in config.get("metrics", ())
        ]
        assert len(keys) == len(set(keys)), f"{sector_key} reuses one source/field/series: {keys}"


def test_market_pulse_fields_exist_and_read_distinct_values() -> None:
    market = _artifact("market-monitor")
    config = asia_app.OVERVIEW_PULSE_CONFIG["market"]
    readings = []
    for metric in config["metrics"]:
        label, value, _date = asia_app.latest_metric_reading(
            market,
            metric["dataset"],
            metric["field"],
            metric["format"],
            label_en=metric["label_en"],
            label_zh=metric["label_zh"],
            language="en",
        )
        assert value != "—", f"{label} did not resolve against the shipped artifact"
        readings.append(value)
    assert len(set(readings)) == len(readings), f"pulse metrics collapsed to the same value: {readings}"


def test_regime_overview_state_is_localized() -> None:
    regime = {
        "snapshot": {
            "datasets": {
                "kpi_regime": [
                    {
                        "observation_date": "2026-09-04",
                        "overall_state": "Escalating",
                    }
                ]
            }
        }
    }
    metric = asia_app.OVERVIEW_PULSE_CONFIG["regime"]["metrics"][0]

    _label, value, _date = asia_app.latest_metric_reading(
        regime,
        metric["dataset"],
        metric["field"],
        metric["format"],
        label_en=metric["label_en"],
        label_zh=metric["label_zh"],
        language="zh",
    )

    assert value == "升级"


def test_regime_daily_brief_prioritizes_driver_nearest_gate_and_rate_move() -> None:
    regime = {
        "snapshot": {
            "datasets": {
                "threshold_monitor": [
                    {
                        "indicator_id": "hike_prob",
                        "label_zh": "近端SOFR高于目标区间概率",
                        "state": "Escalating",
                        "freshness": "Last session",
                        "value": 82.3,
                        "threshold": 65.0,
                        "distance": 17.3,
                        "distance_unit": "pp",
                        "confirmation_progress": 2,
                        "confirmation_required": 2,
                    },
                    {
                        "indicator_id": "us10y",
                        "label_zh": "美国10年期国债收益率",
                        "state": "Normal",
                        "freshness": "Last session",
                        "value": 4.79,
                        "threshold": 4.82,
                        "distance": -3.0,
                        "distance_unit": "bp",
                    },
                    {
                        "indicator_id": "brent",
                        "label_zh": "布伦特原油",
                        "state": "Normal",
                        "freshness": "Last session",
                        "value": 90.0,
                        "threshold": 100.0,
                        "distance": -10.0,
                        "distance_unit": "USD/bbl",
                    },
                    {
                        "indicator_id": "fomc_hike",
                        "label_zh": "下次FOMC加息赔率",
                        "state": "Normal",
                        "freshness": "Current session",
                        "value": 53.2,
                        "threshold": 65.0,
                        "distance": -11.8,
                        "distance_unit": "pp",
                        "change_1obs_pp": 10.3,
                    },
                    {
                        "indicator_id": "credit_vix",
                        "label_zh": "高收益债利差与VIX同步压力",
                        "state": "Normal",
                        "freshness": "Last session",
                        "value": 0.0,
                    },
                ],
                "regime_summary": [
                    {
                        "primary_driver_ids": ["hike_prob"],
                        "breadth_zh": "单一领域",
                        "active_domain_count": 1,
                        "total_domain_count": 3,
                    }
                ],
            }
        }
    }

    brief = {
        item["id"]: item
        for item in asia_app.regime_daily_brief_items(regime, "zh")
    }

    assert list(brief) == [
        "primary_driver",
        "nearest_gate",
        "rate_odds_change",
        "risk_breadth",
    ]
    assert brief["primary_driver"]["value"] == "82.3%"
    assert "近端SOFR" in brief["primary_driver"]["label"]
    assert brief["nearest_gate"]["value"] == "低于 3.0 bp"
    assert "美国10年期" in brief["nearest_gate"]["note"]
    assert "当前 4.79%" in brief["nearest_gate"]["note"]
    assert brief["rate_odds_change"]["value"] == "+10.3 百分点"
    assert brief["risk_breadth"]["value"] == "单一领域"


@pytest.mark.parametrize(
    ("decision_id", "events", "expected_title", "expected_state"),
    [
        ("quiet", [], "无需提醒", "normal"),
        (
            "component_preview",
            [
                {
                    "label_zh": "美国10年期国债收益率",
                    "label_en": "US 10-year Treasury yield",
                    "from_state": "Normal",
                    "to_state": "Watch",
                    "observation_date": "2026-09-03",
                }
            ],
            "记录变化",
            "watch",
        ),
        (
            "defensive_eligible",
            [
                {
                    "label_zh": "信用利差与VIX",
                    "label_en": "Credit and VIX",
                    "from_state": "Watch",
                    "to_state": "Confirmed",
                    "observation_date": "2026-09-03",
                }
            ],
            "符合防守预警",
            "confirmed",
        ),
        ("unavailable", [], "预警决策不可用", "unavailable"),
    ],
)
def test_regime_alert_decision_view_covers_all_decision_states(
    decision_id,
    events,
    expected_title,
    expected_state,
) -> None:
    artifact = {
        "snapshot": {
            "datasets": {
                "alert_status": [
                    {
                        "decision_id": decision_id,
                        "evaluation_current": decision_id != "unavailable",
                        "new_transition_count": len(events),
                        "component_events": events,
                        "confirmed_domain_count": 2
                        if decision_id == "defensive_eligible"
                        else 1,
                        "total_domain_count": 3,
                        "financial_stress_exception": decision_id
                        == "defensive_eligible",
                        "alert_mode": "preview",
                        "last_evaluation_at": "2026-09-03T12:01:00Z"
                        if decision_id != "unavailable"
                        else None,
                    }
                ]
            }
        }
    }

    view = asia_app.regime_alert_decision_view(artifact, "zh")

    assert view["title"] == expected_title
    assert view["visual_state"] == expected_state
    assert "不发送邮件" in view["mode_note"]
    if events:
        assert view["transitions"]
        assert events[0]["label_zh"] in view["transitions"][0]
    if decision_id != "unavailable":
        assert view["evaluated"] == "2026年9月3日 20:01（UTC+8）"


def test_regime_alert_decision_view_fails_closed_without_status() -> None:
    view = asia_app.regime_alert_decision_view(
        {"snapshot": {"datasets": {}}},
        "zh",
    )

    assert view["decision_id"] == "unavailable"
    assert view["title"] == "预警决策不可用"
    assert "缺失" in view["reason"]


@pytest.mark.parametrize("evaluation_current", ["false", float("nan"), None])
def test_regime_alert_decision_view_rejects_non_boolean_current_flag(
    evaluation_current,
) -> None:
    artifact = {
        "snapshot": {
            "datasets": {
                "alert_status": [
                    {
                        "decision_id": "quiet",
                        "evaluation_current": evaluation_current,
                        "alert_mode": "preview",
                    }
                ]
            }
        }
    }

    view = asia_app.regime_alert_decision_view(artifact, "zh")

    assert view["decision_id"] == "unavailable"


def test_regime_data_warnings_name_stale_inputs_and_degraded_sources() -> None:
    artifact = {
        "snapshot": {
            "status": "ready",
            "datasets": {
                "threshold_monitor": [
                    {
                        "indicator_id": "brent",
                        "label_en": "Brent crude",
                        "label_zh": "布伦特原油",
                        "freshness": "Stale",
                    }
                ],
                "source_health": [
                    {
                        "source": "FRED / EIA",
                        "status": "Degraded",
                    }
                ],
            },
        },
        "package_info": {"runConsistent": True},
    }

    warnings = asia_app.regime_data_warnings(artifact, "zh")

    assert len(warnings) == 2
    assert "布伦特原油" in warnings[0]
    assert "FRED / EIA" in warnings[1]


def test_regime_daily_brief_excludes_stale_rows_and_includes_sofr_gate_boundary() -> None:
    artifact = {
        "snapshot": {
            "status": "ready",
            "datasets": {
                "threshold_monitor": [
                    {
                        "indicator_id": "brent",
                        "label_en": "Brent crude",
                        "label_zh": "布伦特原油",
                        "state": "Normal",
                        "value": 90.0,
                        "threshold": 100.0,
                        "distance": -10.0,
                        "distance_unit": "USD/bbl",
                        "freshness": "Current session",
                    },
                    {
                        "indicator_id": "hike_prob",
                        "label_en": "Near-term SOFR above target",
                        "label_zh": "近端SOFR高于目标区间概率",
                        "state": "Normal",
                        "value": 65.0,
                        "threshold": 65.0,
                        "distance": 0.0,
                        "distance_unit": "pp",
                        "freshness": "Current session",
                    },
                    {
                        "indicator_id": "fomc_hike",
                        "label_en": "Next FOMC hike odds",
                        "label_zh": "下次FOMC加息赔率",
                        "state": "Watch",
                        "value": 70.0,
                        "threshold": 65.0,
                        "distance": 5.0,
                        "distance_unit": "pp",
                        "freshness": "Stale",
                        "change_1obs_pp": 12.0,
                    },
                ],
                "regime_summary": [
                    {
                        "overall_state": "Normal",
                        "primary_driver_ids": ["fomc_hike"],
                        "breadth_en": "No spread",
                        "breadth_zh": "未扩散",
                        "active_domain_count": 0,
                        "total_domain_count": 3,
                    }
                ],
            },
        },
        "package_info": {"runConsistent": True},
    }

    brief = asia_app.regime_daily_brief_items(artifact, "en")
    by_id = {item["id"]: item for item in brief}

    assert "primary_driver" not in by_id
    assert "rate_odds_change" not in by_id
    assert by_id["nearest_gate"]["note"].startswith("Near-term SOFR")
    assert by_id["nearest_gate"]["value"] == "at threshold"


def test_regime_data_warnings_fail_closed_without_source_health() -> None:
    artifact = {
        "snapshot": {
            "status": "ready",
            "datasets": {
                "threshold_monitor": [
                    {
                        "indicator_id": "brent",
                        "label_en": "Brent crude",
                        "label_zh": "布伦特原油",
                        "freshness": "Current session",
                    }
                ]
            },
        },
        "package_info": {"runConsistent": True},
    }

    warnings = asia_app.regime_data_warnings(artifact, "en")

    assert warnings == ["Source-health metadata is unavailable."]


def test_regime_data_warnings_fail_closed_without_decision_freshness() -> None:
    artifact = {
        "snapshot": {
            "status": "ready",
            "datasets": {
                "threshold_monitor": [],
                "source_health": [
                    {"source": "FRED / EIA", "status": "Healthy"}
                ],
            },
        },
        "package_info": {"runConsistent": True},
    }

    warnings = asia_app.regime_data_warnings(artifact, "en")

    assert warnings == ["Decision-input freshness metadata is unavailable."]


def test_regime_stale_row_uses_unavailable_visual_state() -> None:
    assert (
        asia_app.regime_visual_state(
            {"state": "Escalating", "freshness": "Stale"}
        )
        == "Unavailable"
    )
    assert (
        asia_app.regime_visual_state(
            {"state": "Escalating", "freshness": "Current session"}
        )
        == "Escalating"
    )
