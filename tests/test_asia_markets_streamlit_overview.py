import importlib.util
import json
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "apps" / "asia-markets-streamlit" / "app.py"
APP_SPEC = importlib.util.spec_from_file_location("asia_markets_streamlit_app", APP_PATH)
assert APP_SPEC and APP_SPEC.loader
asia_app = importlib.util.module_from_spec(APP_SPEC)
APP_SPEC.loader.exec_module(asia_app)

ARTIFACT_ROOT = REPO_ROOT / "apps" / "asia-markets-dashboard" / ".generated"


def _artifact(slug: str) -> dict:
    return json.loads((ARTIFACT_ROOT / f"{slug}-artifact.json").read_text(encoding="utf-8"))


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
        "percent",
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
