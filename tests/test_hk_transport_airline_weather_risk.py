from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_weather_risk import (
    MONTHLY_COLUMNS,
    _archive_to_daily,
    _build_monthly,
    _disruption_flags,
    _forecast_to_daily,
)


def test_disruption_flags_apply_thresholds() -> None:
    assert _disruption_flags(30.0, 25.0, "rain_heavy") == (True, False, False)
    assert _disruption_flags(10.0, 55.0, "clear") == (False, True, False)
    assert _disruption_flags(5.0, 20.0, "fog") == (False, False, True)
    assert _disruption_flags(None, None, None) == (False, False, False)


def test_archive_to_daily_maps_weather_rows() -> None:
    archive = {
        "daily": {
            "time": ["2026-06-01", "2026-06-02"],
            "temperature_2m_max": [30.0, 28.0],
            "temperature_2m_min": [22.0, 21.0],
            "precipitation_sum": [40.0, 0.0],
            "wind_speed_10m_max": [60.0, 15.0],
            "weather_code": [95, 0],
        }
    }
    result = _archive_to_daily(
        "PEK", "Beijing Capital", archive, "/raw/path", "2026-08-10T00:00:00+00:00"
    )
    assert len(result) == 2
    first = result.iloc[0]
    assert first["observation_date"] == "2026-06-01"
    assert bool(first["heavy_rain_day"]) is True
    assert bool(first["high_wind_day"]) is True
    assert first["weather_label"] == "thunderstorm"
    assert first["source_api"] == "openmeteo_archive"


def test_forecast_to_daily_keeps_past_days_without_temperature() -> None:
    forecast = {
        "daily": {
            "time": ["2026-08-09"],
            "precipitation_sum": [5.0],
            "wind_speed_10m_max": [12.0],
            "weather_code": [61],
        }
    }
    result = _forecast_to_daily(
        "CAN", "Guangzhou Baiyun", forecast, "/raw/path", "2026-08-10T00:00:00+00:00"
    )
    assert len(result) == 1
    assert result.iloc[0]["temperature_2m_max_c"] is None
    assert result.iloc[0]["weather_label"] == "rain_slight"
    assert bool(result.iloc[0]["heavy_rain_day"]) is False


def test_monthly_aggregate_marks_disruption_flags() -> None:
    daily = pd.DataFrame(
        [
            {
                "airport": "PEK",
                "airport_label": "Beijing Capital",
                "observation_date": "2026-06-01",
                "temperature_2m_max_c": 30.0,
                "precipitation_sum_mm": 30.0,
                "wind_speed_10m_max_kmh": 20.0,
                "heavy_rain_day": True,
                "high_wind_day": False,
                "fog_day": False,
            },
            {
                "airport": "PEK",
                "airport_label": "Beijing Capital",
                "observation_date": "2026-06-02",
                "temperature_2m_max_c": 28.0,
                "precipitation_sum_mm": 5.0,
                "wind_speed_10m_max_kmh": 10.0,
                "heavy_rain_day": False,
                "high_wind_day": False,
                "fog_day": False,
            },
            {
                "airport": "PEK",
                "airport_label": "Beijing Capital",
                "observation_date": "2026-06-03",
                "temperature_2m_max_c": 27.0,
                "precipitation_sum_mm": 45.0,
                "wind_speed_10m_max_kmh": 12.0,
                "heavy_rain_day": True,
                "high_wind_day": False,
                "fog_day": False,
            },
            {
                "airport": "PEK",
                "airport_label": "Beijing Capital",
                "observation_date": "2026-06-04",
                "temperature_2m_max_c": 26.0,
                "precipitation_sum_mm": 60.0,
                "wind_speed_10m_max_kmh": 18.0,
                "heavy_rain_day": True,
                "high_wind_day": False,
                "fog_day": False,
            },
            {
                "airport": "PEK",
                "airport_label": "Beijing Capital",
                "observation_date": "2026-06-05",
                "temperature_2m_max_c": 25.0,
                "precipitation_sum_mm": 55.0,
                "wind_speed_10m_max_kmh": 22.0,
                "heavy_rain_day": True,
                "high_wind_day": False,
                "fog_day": False,
            },
        ]
    )
    result = _build_monthly(daily, "2026-08-10T00:00:00+00:00")
    assert result.columns.tolist() == MONTHLY_COLUMNS
    assert len(result) == 1
    row = result.iloc[0]
    assert row["observation_month"] == "2026-06"
    assert row["heavy_rain_days"] == 4
    assert row["disruption_flag"] == "high"
    assert row["days_observed"] == 5


def test_empty_archive_returns_empty_frame() -> None:
    result = _archive_to_daily(
        "HKG", "Hong Kong International", None, None, "2026-08-10T00:00:00+00:00"
    )
    assert result.empty
