from __future__ import annotations

import io
import importlib.util
import json
from pathlib import Path

import pandas as pd
from openpyxl import Workbook

from src.hk_transport.sources.censtatd_boundary_movements import parse_boundary_movements_workbook
from src.hk_transport.sources.mttd_passenger_journeys import parse_mttd_passenger_journeys_csv
from src.hk_transport.sources.td_carpark_occupancy import parse_td_carpark_occupancy
from src.hk_transport.sources.td_private_car_net_registration import (
    parse_private_car_net_registration_sheet,
)
from src.hk_transport.sources.td_vehicle_fleet_stock import parse_private_car_fleet_sheet


def _load_transport_builder():
    path = Path(__file__).resolve().parents[1] / "apps" / "asia-markets-dashboard" / "scripts" / "build_hk_transport_artifact.py"
    spec = importlib.util.spec_from_file_location("hk_transport_group1_builder", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vehicle_fleet_parser_keeps_private_car_fuel_stock_and_reconciles() -> None:
    columns = 17
    header = [None] * columns
    header[2] = "Private Cars Petrol"
    header[3] = "Petrol Total Registration"
    header[4] = "Petrol Total Licensed"
    header[5] = "Electric"
    header[6] = "Electric Total Registration"
    header[7] = "Electric Total Licensed"
    header[8] = "Diesel"
    header[9] = "Diesel Total Registration"
    header[10] = "Diesel Total Licensed"
    header[11] = "Other"
    header[12] = "Other Total Registration"
    header[13] = "Other Total Licensed"
    header[14] = "Sub-total"
    header[15] = "Total Registration"
    header[16] = "Total Licensed"
    values = [2026, 1, 100, 460, 400, 50, 150, 130, 10, 10, 8, 2, 1, 1, 162, 621, 539]
    frame = pd.DataFrame([header, values])

    result = parse_private_car_fleet_sheet(frame)

    assert result.loc[0, "date"] == "2026-01"
    assert result.loc[0, "electric_total_registered"] == 150
    assert result.loc[0, "all_fuel_total_registered"] == 621


def test_net_registration_parser_keeps_monthly_rows_and_identity() -> None:
    frame = pd.DataFrame(
        [
            ["Table 4.1(c)", None, None, None, None],
            [None, None, "Gross First Registration", "Cumulative Deregistration", "Net First Registration"],
            [2026, 1, 100, 7, 93],
        ]
    )

    result = parse_private_car_net_registration_sheet(frame)

    assert result.to_dict("records") == [
        {
            "date": "2026-01",
            "year": 2026,
            "month": 1,
            "gross_first_registrations": 100.0,
            "deregistrations": 7.0,
            "net_first_registrations": 93.0,
        }
    ]


def test_mttd_parser_preserves_source_grain_and_geography() -> None:
    payload = (
        "YR_MTH,BUS_RAIL,TTD_PTO_CODE,FRANCHISE_TYPE,RAIL_LINE,PAX_HK,PAX_HK_INDI," 
        "PAX_KLN_NT,PAX_KLN_NT_INDI,PAX_CROSS_HARBOUR,PAX_CROSS_HARBOUR_INDI\n"
        "202605,MTRC,MTRC,,Local,100,,, ,25,\n"
        "202605,Fran_Bus,KMB,,, , ,200,,10,\n"
    ).encode()

    result = parse_mttd_passenger_journeys_csv(payload)

    assert len(result) == 2
    assert result.loc[result["bus_rail"].eq("MTRC"), "total_passenger_journeys_k"].item() == 125
    assert result.loc[result["pto_code"].eq("KMB"), "total_passenger_journeys_k"].item() == 210


def test_boundary_parser_reads_monthly_e705_columns() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "E705"
    values = [None] * 53
    values[0] = 2026
    values[1] = 5
    values[3] = 10
    values[5] = 11
    values[7] = 21
    values[34] = 100
    values[36] = 90
    values[38] = 190
    values[41] = 80
    values[43] = 70
    values[45] = 150
    sheet.append(values)
    buffer = io.BytesIO()
    workbook.save(buffer)

    result = parse_boundary_movements_workbook(buffer.getvalue())

    assert result.loc[0, "month"] == "2026-05"
    assert result.loc[0, "aircraft_total"] == 21
    assert result.loc[0, "goods_vehicles_total"] == 190
    assert result.loc[0, "passenger_vehicles_total"] == 150


def test_metered_parking_occupancy_uses_observed_status_as_denominator() -> None:
    spaces = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"ParkingSpaceId": "A1", "District": "CENTRAL"}},
            {"type": "Feature", "properties": {"ParkingSpaceId": "A2", "District": "CENTRAL"}},
            {"type": "Feature", "properties": {"ParkingSpaceId": "B1", "District": "SHA TIN"}},
        ],
    }
    status = (
        "ParkingSpaceId,ParkingMeterStatus,OccupancyStatus,OccupancyDateChanged\n"
        "A1,N,O,07/31/2026 11:17:40 PM\n"
        "A2,N,V,07/31/2026 11:17:40 PM\n"
        "B1,N,O,07/31/2026 11:17:40 PM\n"
    ).encode()

    result = parse_td_carpark_occupancy(
        json.dumps(spaces).encode(),
        status,
        snapshot_at=pd.Timestamp("2026-07-31 23:20:00"),
    )

    all_hk = result[result["district"].eq("All Hong Kong")].iloc[0]
    assert all_hk["sample_size"] == 3
    assert all_hk["occupied_spaces"] == 2
    assert all_hk["vacant_spaces"] == 1
    assert all_hk["occupancy_rate"] == 2 / 3


def test_transport_builder_wires_group1_views_with_mobile_safe_series_caps() -> None:
    builder = _load_transport_builder()
    dates = pd.to_datetime(["2026-04-01", "2026-05-01"])

    mttd = pd.DataFrame(
        [
            {"date": dates[0], "bus_rail": "MTRC", "rail_line": "Local", "total_passenger_journeys_k": 100},
            {"date": dates[0], "bus_rail": "MTRC", "rail_line": "Airport Express", "total_passenger_journeys_k": 20},
            {"date": dates[0], "bus_rail": "Fran_Bus", "rail_line": "", "total_passenger_journeys_k": 300},
            {"date": dates[1], "bus_rail": "MTRC", "rail_line": "Local", "total_passenger_journeys_k": 110},
            {"date": dates[1], "bus_rail": "MTRC", "rail_line": "Airport Express", "total_passenger_journeys_k": 22},
            {"date": dates[1], "bus_rail": "Fran_Bus", "rail_line": "", "total_passenger_journeys_k": 305},
        ]
    )
    mttd_view = builder.build_mttd_passenger_journey_views(mttd)
    assert {row["series"] for row in mttd_view["mttd_passenger_journeys_history"]} == {
        "MTR Local",
        "MTR Airport / LRT / feeder",
        "Franchised buses",
    }

    boundary = pd.DataFrame(
        {
            "date": dates,
            "aircraft_total": [10, 11],
            "passenger_vehicles_total": [20, 21],
            "goods_vehicles_total": [30, 31],
            "is_estimate": [False, True],
        }
    )
    boundary_view = builder.build_boundary_movement_views(boundary)
    assert {row["series"] for row in boundary_view["censtatd_boundary_movements_history"]} == {
        "Aircraft",
        "Passenger vehicles",
        "Goods vehicles",
    }
    assert sum(row["is_estimate"] for row in boundary_view["censtatd_boundary_movements_history"]) == 3

    occupancy = pd.DataFrame(
        [
            {"snapshot_at": "2026-07-31 10:00", "district": "All Hong Kong", "occupancy_rate": 0.5, "sample_size": 10, "capacity_spaces": 10, "occupied_spaces": 5, "vacant_spaces": 5, "listed_spaces": 10},
            {"snapshot_at": "2026-07-31 10:05", "district": "All Hong Kong", "occupancy_rate": 0.6, "sample_size": 10, "capacity_spaces": 10, "occupied_spaces": 6, "vacant_spaces": 4, "listed_spaces": 10},
            {"snapshot_at": "2026-07-31 10:05", "district": "Central", "occupancy_rate": 0.6, "sample_size": 10, "capacity_spaces": 10, "occupied_spaces": 6, "vacant_spaces": 4, "listed_spaces": 10},
        ]
    )
    occupancy_view = builder.build_carpark_occupancy_views(occupancy)
    assert len(occupancy_view["td_carpark_occupancy_history"]) == 2
    assert occupancy_view["kpi_carpark_occupancy"][0]["occupancy_pct"] == 60.0

    fleet = pd.DataFrame(
        {
            "date": dates,
            "electric_total_registered": [10, 12],
            "all_fuel_total_registered": [100, 120],
        }
    )
    fleet_view = builder.build_vehicle_fleet_ev_share_view(fleet)
    assert len(fleet_view) == 2
    assert fleet_view[-1]["value"] == 10.0
