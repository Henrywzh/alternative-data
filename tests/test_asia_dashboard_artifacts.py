"""Tests for the non-Streamlit Asia Markets dashboard artifact builders."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "asia-markets-dashboard"
SCRIPTS = ROOT / "apps" / "asia-markets-dashboard" / "scripts"


def test_labour_policy_approved_history_includes_qmas_selection_cases():
    artifact_path = APP / ".generated" / "hk-labour-market-artifact.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    datasets = artifact["snapshot"]["datasets"]

    qmas_approved = [
        row for row in datasets["talent_policy_approved_history"] if row["series"] == "QMAS"
    ]
    assert len(qmas_approved) == 10
    assert {row["approval_basis"] for row in qmas_approved} == {"quota_allotted"}
    assert {row["date"] for row in qmas_approved} == {
        f"{year}-12-31" for year in range(2016, 2026)
    }
    assert next(row["value"] for row in qmas_approved if row["date"] == "2025-12-31") == 7101

    latest = next(row for row in datasets["talent_policy_latest"] if row["series"] == "QMAS")
    assert latest["applications_approved"] == 7101
    assert latest["qmas_quota"] == 7101
    assert datasets["kpi_talent_policy"][0]["applications_approved"] == 124460


def test_local_consumer_cpi_category_legend_uses_mobile_safe_labels():
    """The portable reader keeps a categorical legend on one row at 390px."""
    artifact = json.loads(
        (APP / ".generated" / "hk-local-consumer-artifact.json").read_text(encoding="utf-8")
    )
    rows = artifact["snapshot"]["datasets"]["censtatd_cpi_by_category_history"]
    assert {row["series"] for row in rows} == {"Food", "Housing & Utilities", "Transport"}
    assert max(len(row["series"]) for row in rows) <= 20


def _load_builder(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_china_airline_traffic_normalizes_clean_parquet(tmp_path):
    builder = _load_builder("build_hk_transport_artifact.py", "transport_builder_loader_test")
    path = tmp_path / "china_airlines_monthly.parquet"
    pd.DataFrame(
        [
            {
                "month": "2026-01",
                "date": "2026-01-01",
                "airline_code": "600029",
                "region": "Domestic",
                "metric": "passengers",
                "value": 123.4,
            }
        ]
    ).to_parquet(path, index=False)

    result = builder.load_china_airline_traffic(path)

    assert list(result.columns) == [
        "month",
        "date",
        "airline_code",
        "airline",
        "region",
        "metric",
        "value",
    ]
    assert result.iloc[0]["airline"] == "China Southern"
    assert result.iloc[0]["value"] == 123.4


def test_china_airline_views_are_wired_into_transport_artifact():
    builder = _load_builder("build_hk_transport_artifact.py", "transport_builder_views_test")
    source = pd.DataFrame(
        [
            {"month": "2026-01", "date": "2026-01-01", "airline_code": "600029", "region": "Total", "metric": "passengers", "value": 100.0},
            {"month": "2026-01", "date": "2026-01-01", "airline_code": "600029", "region": "Total", "metric": "ask", "value": 200.0},
            {"month": "2026-01", "date": "2026-01-01", "airline_code": "600029", "region": "Total", "metric": "rpk", "value": 150.0},
            {"month": "2026-01", "date": "2026-01-01", "airline_code": "600029", "region": "Total", "metric": "passenger_load_factor_pct", "value": 75.0},
            {"month": "2026-01", "date": "2026-01-01", "airline_code": "600029", "region": "Domestic", "metric": "passengers", "value": 80.0},
        ]
    )

    views = builder.build_china_airline_views(source)

    assert set(views) == {
        "china_airline_passengers_history",
        "china_airline_ask_history",
        "china_airline_rpk_history",
        "china_airline_load_factor_history",
        "china_airline_region_split_history",
        "china_airline_latest_snapshot",
    }
    assert views["china_airline_passengers_history"][0]["airline"] == "China Southern"
    assert views["china_airline_ask_history"][0]["value"] == 200.0
    assert views["china_airline_rpk_history"][0]["value"] == 150.0
    assert {row["series"] for row in views["china_airline_ask_history"]} == {"CS"}
    assert views["china_airline_load_factor_history"][0]["value"] == 75.0
    assert views["china_airline_region_split_history"][0]["region"] == "Domestic"
    assert views["china_airline_latest_snapshot"][0]["airline_code"] == "600029"


def test_china_airline_snapshot_table_keeps_structured_columns():
    """The latest airline lookup table must remain tabular, not a text log."""
    artifact_path = APP / ".generated" / "hk-transport-artifact.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    table = next(
        table
        for table in artifact["manifest"]["tables"]
        if table["id"] == "china_airline_latest_snapshot_table"
    )

    assert table["dataset"] == "china_airline_latest_snapshot"
    assert [column["field"] for column in table["columns"]] == [
        "airline",
        "region",
        "passengers",
        "ask",
        "rpk",
        "load_factor_pct",
    ]
    assert "summary" not in table["dataset"]
    assert artifact["snapshot"]["datasets"][table["dataset"]][0]["airline"]


def _regional_rows(metric: str, regions: dict[str, float]) -> list[dict]:
    return [
        {
            "month": "2026-01",
            "date": "2026-01-01",
            "airline_code": "601021",
            "region": region,
            "metric": metric,
            "value": value,
        }
        for region, value in regions.items()
    ]


def test_partial_region_coverage_leaves_a_gap_instead_of_a_derived_total():
    """A carrier with no reported Total must not get one from 2 of 3 regions.

    Spring Airlines publishes only a regional breakdown, so its totals are
    derived. When a page-break artifact dropped one region's ASK, summing the
    remaining two understated ASK and pushed the derived RPK/ASK load factor
    above 100%. The builder now requires all three regions before deriving.
    """
    builder = _load_builder("build_hk_transport_artifact.py", "transport_builder_gate_test")

    complete = pd.DataFrame(
        _regional_rows("ask", {"Domestic": 100.0, "International": 50.0, "Regional": 10.0})
        + _regional_rows("rpk", {"Domestic": 80.0, "International": 40.0, "Regional": 8.0})
    )
    full = builder.build_china_airline_views(complete)
    assert [row["value"] for row in full["china_airline_ask_history"]] == [160.0]
    assert full["china_airline_load_factor_history"][0]["value"] == pytest.approx(80.0)

    # Same data with one ASK region dropped: RPK is still complete, so an
    # ungated sum would divide complete RPK by an understated ASK.
    partial = pd.DataFrame(
        _regional_rows("ask", {"Domestic": 100.0, "Regional": 10.0})
        + _regional_rows("rpk", {"Domestic": 80.0, "International": 40.0, "Regional": 8.0})
    )
    gapped = builder.build_china_airline_views(partial)
    assert gapped["china_airline_ask_history"] == [], "2 of 3 regions must not yield a total"
    assert gapped["china_airline_load_factor_history"] == [], (
        "load factor must be dropped rather than derived from an incomplete ASK"
    )
    # The complete metric is unaffected.
    assert [row["value"] for row in gapped["china_airline_rpk_history"]] == [128.0]


def test_load_transport_monthly_rejects_missing_columns(tmp_path):
    """The shared TD-table loader must not silently accept a truncated schema.

    scripts/scrape_hk_passenger_journeys.py and its two siblings each
    recompute TD's own published subtotals from their parts and refuse to
    write output that doesn't reconcile (see tests/test_hk_transport_scrapers.py
    for the guards themselves) -- this loader's own job is narrower: confirm
    the columns it was told to expect are actually present before the
    builder trusts any of them.
    """
    builder = _load_builder("build_hk_transport_artifact.py", "transport_builder_schema_test")
    path = tmp_path / "hk_passenger_journeys_monthly.parquet"
    pd.DataFrame([{"date": "2026-01", "kmb_k": 100.0}]).to_parquet(path, index=False)

    with pytest.raises(ValueError, match="missing columns"):
        builder.load_passenger_journeys(path)


def test_load_transport_monthly_parses_year_month_date(tmp_path):
    """These three parquets store `date` as a bare "YYYY-MM" string (month
    grain, no day) -- unlike china_airline's full "YYYY-MM-DD" -- so the
    loader must append a day component itself rather than pass the string
    straight to pd.to_datetime.
    """
    builder = _load_builder("build_hk_transport_artifact.py", "transport_builder_date_test")
    path = tmp_path / "hk_private_car_net_growth_monthly.parquet"
    pd.DataFrame(
        [{"date": "2026-03", "gross_first_registrations": 100.0, "deregistrations": 5.0, "net_first_registrations": 95.0}]
    ).to_parquet(path, index=False)

    result = builder.load_net_growth(path)

    assert result.iloc[0]["date"] == pd.Timestamp("2026-03-01")


def test_passenger_journeys_views_are_wired_into_transport_artifact():
    builder = _load_builder("build_hk_transport_artifact.py", "transport_builder_journeys_views_test")
    frame = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-01-01"),
                "kmb_k": 80000.0, "citybus_subtotal_k": 30000.0, "nwfb_k": None,
                "lwb_k": 4000.0, "nlb_k": 3000.0, "bus_subtotal_k": 117000.0,
                "mtr_heavy_rail_k": 150000.0, "airport_express_k": 1200.0,
                "light_rail_k": 13000.0, "tramways_k": 4500.0, "rail_subtotal_k": 168700.0,
                "plb_subtotal_k": 46000.0, "ferry_subtotal_k": 3600.0, "taxis_k": 20500.0,
                "total_k": 355800.0,
            }
        ]
    )

    views = builder.build_passenger_journeys_views(frame)

    assert set(views) == {
        "hk_total_transport_journeys_history",
        "hk_modal_split_history",
        "hk_franchised_bus_operator_history",
    }
    assert views["hk_total_transport_journeys_history"][0]["value"] == 355800.0
    assert {row["series"] for row in views["hk_modal_split_history"]} == {
        "Bus", "Rail", "PLB", "Ferry", "Taxi",
    }
    kmb_row = next(row for row in views["hk_franchised_bus_operator_history"] if row["series"] == "KMB")
    assert kmb_row["value"] == 80000.0
    # nwfb_k is None (folded into Citybus's own reporting since ~2023) -- must
    # not appear as a series in the operator chart, not even as a zero.
    assert "NWFB" not in {row["series"] for row in views["hk_franchised_bus_operator_history"]}


def test_vehicle_stock_and_net_growth_views_are_wired_into_transport_artifact():
    builder = _load_builder("build_hk_transport_artifact.py", "transport_builder_fleet_views_test")
    stock = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-01-01"),
                "petrol_total_registered": 460000.0, "electric_total_registered": 150000.0,
                "diesel_total_registered": 11000.0, "other_total_registered": 100.0,
                "all_fuel_total_registered": 621100.0, "all_fuel_total_licensed": 570000.0,
            }
        ]
    )
    growth = pd.DataFrame(
        [{"date": pd.Timestamp("2026-01-01"), "gross_first_registrations": 3000.0,
          "deregistrations": 10.0, "net_first_registrations": 2990.0}]
    )

    stock_views = builder.build_vehicle_stock_views(stock)
    growth_views = builder.build_net_growth_views(growth)

    assert set(stock_views) == {"hk_private_car_fleet_by_fuel_history"}
    electric_row = next(row for row in stock_views["hk_private_car_fleet_by_fuel_history"] if row["series"] == "Electric")
    assert electric_row["value"] == 150000.0

    assert set(growth_views) == {"hk_private_car_net_growth_history"}
    assert growth_views["hk_private_car_net_growth_history"][0]["value"] == 2990.0


def test_private_car_first_registration_views_build_flow_and_make_series():
    builder = _load_builder("build_hk_transport_artifact.py", "transport_builder_ev_first_reg_views_test")
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-01-01"), "month": "2026-01", "make": "BYD", "fuel_type": "ELECTRIC", "first_reg": 100},
            {"date": pd.Timestamp("2026-01-01"), "month": "2026-01", "make": "TESLA", "fuel_type": "ELECTRIC", "first_reg": 50},
            {"date": pd.Timestamp("2026-01-01"), "month": "2026-01", "make": "TOYOTA", "fuel_type": "PETROL", "first_reg": 350},
            {"date": pd.Timestamp("2026-02-01"), "month": "2026-02", "make": "BYD", "fuel_type": "ELECTRIC", "first_reg": 120},
            {"date": pd.Timestamp("2026-02-01"), "month": "2026-02", "make": "TOYOTA", "fuel_type": "PETROL", "first_reg": 380},
        ]
    )

    views = builder.build_private_car_first_reg_views(frame)

    assert views["kpi_private_car_first_reg"][0]["total_first_reg"] == 500.0
    assert views["kpi_private_car_first_reg"][0]["electric_first_reg"] == 120.0
    assert views["kpi_private_car_first_reg"][0]["ev_share_pct"] == pytest.approx(24.0)
    assert {row["series"] for row in views["hk_private_car_ev_make_history"]} == {"BYD", "Tesla"}
    assert views["hk_private_car_ev_share_history"][-1]["value"] == pytest.approx(24.0)


def test_parking_vacancy_views_exclude_unknown_counts_and_keep_history():
    builder = _load_builder("build_hk_transport_artifact.py", "transport_builder_parking_views_test")
    frame = pd.DataFrame(
        [
            {"snapshot_at": pd.Timestamp("2026-07-31 10:00"), "park_id": "p1", "district_en": "Central", "vehicle_type": "P", "service_category": "HOURLY", "vacancy_type": "A", "vacancy": 10},
            {"snapshot_at": pd.Timestamp("2026-07-31 10:00"), "park_id": "p2", "district_en": "Wan Chai", "vehicle_type": "P", "service_category": "HOURLY", "vacancy_type": "B", "vacancy": 1},
            {"snapshot_at": pd.Timestamp("2026-07-31 10:05"), "park_id": "p1", "district_en": "Central", "vehicle_type": "P", "service_category": "HOURLY", "vacancy_type": "A", "vacancy": 7},
            {"snapshot_at": pd.Timestamp("2026-07-31 10:05"), "park_id": "p2", "district_en": "Wan Chai", "vehicle_type": "P", "service_category": "HOURLY", "vacancy_type": "B", "vacancy": 1},
        ]
    )

    views = builder.build_parking_vacancy_views(frame)

    assert views["kpi_parking"][0]["available_spaces"] == 7
    assert views["kpi_parking"][0]["parks_reporting_exact"] == 1
    assert views["kpi_parking"][0]["parks_with_unknown_count"] == 1
    assert len(views["hk_parking_vacancy_history"]) == 2
    assert "Central" in views["hk_parking_current_district"][0]["summary"]
