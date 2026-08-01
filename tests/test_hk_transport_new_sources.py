"""Focused tests for the added TD EV-registration and parking feeds."""

from __future__ import annotations

import json

import pandas as pd

from src.hk_transport.sources.td_first_registered_vehicle_details import (
    parse_td_first_registered_vehicle_csv,
)
from src.hk_transport.sources.td_parking_vacancy import parse_td_parking_vacancy
from src.hk_transport.sources.td_private_car_first_reg import parse_td_private_car_first_reg_csv


def test_parse_td_private_car_first_reg_csv_keeps_make_fuel_and_month() -> None:
    payload = (
        "\ufeffYR_MTH,VEHICLE_CLASS_CODE,MAKE,FIRST_REG_STATUS,FIRST_REG_STATUS_REV,FUEL_TYPE_CODE,BODY_TYPE_CODE,FIRST_REG\n"
        "202605,1,BYD,Brand new,,ELECTRIC,4,120\n"
        "202605,1,TESLA,Brand new,,ELECTRIC,4,80\n"
        "202605,2,BYD,Brand new,,ELECTRIC,4,999\n"
    ).encode("utf-8")

    frame = parse_td_private_car_first_reg_csv(payload)

    assert len(frame) == 2
    assert frame["month"].tolist() == ["2026-05", "2026-05"]
    assert set(frame["make"]) == {"BYD", "TESLA"}
    assert frame["first_reg"].sum() == 200


def test_parse_td_first_registered_vehicle_csv_filters_to_private_cars() -> None:
    columns = [
        "Vehicle Class", "Vehicle Make", "Vehicle Model", "Fuel Type",
        "Cylinder Capacity Of Engine (c.c.)", "Rated Power (kW)", "Body Type",
        "First Registration Vehicle Status", "Permitted Gross Vehicle Weight",
        "Number Of Passenger Seats", "Taxable Value (HK$)", "Year Of Manufacture",
    ]
    rows = [
        ["Private Car", "BYD", "SEALION 7", "Electric", "-", "160", "SUV", "A", "-", "5", "300000", "2026"],
        ["Motor Cycle", "HONDA", "CBR", "Petrol", "599", "-", "MOTOR CYCLE", "A", "-", "2", "150000", "2025"],
    ]
    payload = (",".join(columns) + "\n" + "\n".join(",".join(row) for row in rows)).encode("utf-8")

    frame = parse_td_first_registered_vehicle_csv(payload, observation_date=pd.Timestamp("2026-06-01"))

    assert len(frame) == 1
    assert frame.loc[0, "vehicle_model"] == "SEALION 7"
    assert frame.loc[0, "fuel_type"] == "Electric"
    assert frame.loc[0, "observation_date"] == pd.Timestamp("2026-06-01")


def test_parse_td_parking_vacancy_preserves_unknown_and_closed_statuses() -> None:
    vacancy = {
        "car_park": [
            {"park_id": "p1", "vehicle_type": [{"type": "P", "service_category": [{"category": "HOURLY", "vacancy_type": "A", "vacancy": 12, "lastupdate": "2026-07-31 20:00:00"}]}]},
            {"park_id": "p2", "vehicle_type": [{"type": "P", "service_category": [{"category": "HOURLY", "vacancy_type": "B", "vacancy": 1, "lastupdate": "2026-07-31 20:00:00"}]}]},
            {"park_id": "p3", "vehicle_type": [{"type": "P", "service_category": [{"category": "HOURLY", "vacancy_type": "C", "vacancy": 0, "lastupdate": "2026-07-31 20:00:00"}]}]},
        ]
    }
    basic = {
        "car_park": [
            {"park_id": "p1", "name_en": "One", "name_tc": "一", "district_en": "Central", "district_tc": "中西區", "latitude": 22.28, "longitude": 114.16},
            {"park_id": "p2", "name_en": "Two", "name_tc": "二", "district_en": "Wan Chai", "district_tc": "灣仔區", "latitude": 22.28, "longitude": 114.18},
            {"park_id": "p3", "name_en": "Three", "name_tc": "三", "district_en": "Sha Tin", "district_tc": "沙田區", "latitude": 22.38, "longitude": 114.19},
        ]
    }

    frame = parse_td_parking_vacancy(
        json.dumps(vacancy).encode(),
        json.dumps(basic).encode(),
        snapshot_at=pd.Timestamp("2026-07-31 20:05:00"),
    )

    assert len(frame) == 3
    assert set(frame["vacancy_type"]) == {"A", "B", "C"}
    assert frame.loc[frame["park_id"] == "p1", "district_en"].item() == "Central"
    assert frame.loc[frame["park_id"] == "p1", "vacancy"].item() == 12
