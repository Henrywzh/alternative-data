import importlib.util
import json
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
    assert unemployment == "3.7%"
    assert unemployment_date == "30 Jun 2026"

    population_value, population_date = asia_app.latest_metric_reading(
        population,
        "csd_population",
        "mid_year_population_thousands",
        "number",
        label_en="Population ('000)",
        label_zh="人口（千人）",
        language="en",
    )[1:]
    assert population_value == "7,510.8"
    assert population_date == "01 Dec 2025"

    resident_flow, flow_date = asia_app.latest_series_reading(
        population,
        "immd_net_flow_chart",
        "HK Resident Net Flow",
        "number",
        "en",
    )
    assert resident_flow == "-9,576"
    assert flow_date == "30 Jul 2026"

    labour_frame, labour_title, labour_latest, labour_range, labour_note = asia_app.sparkline_context(
        labour,
        asia_app.OVERVIEW_PULSE_CONFIG["labour"]["sparkline"],
        "en",
    )
    assert len(labour_frame) > 1
    assert labour_title == "Unemployment rate history"
    assert labour_latest == "3.7%"
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
