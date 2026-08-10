"""Airport weather-risk layer for airline hub airports.

Uses the free Open-Meteo archive and forecast APIs (no API key) to build
daily weather observations for each airline hub airport, plus monthly
disruption-flag aggregates (heavy-rain days, high-wind days, fog days).
The layer is a risk/execution variable: weather can shift utilization,
cancellations and revenue timing, but it is not a deterministic earnings
forecast and is intentionally kept separate from company ASK/RPK models.

The archive API serves ERA5-based historical weather (typically available
with a short publication lag) and the forecast API with ``past_days`` covers
the most recent days; both are snapshot observations without an issuer
announcement date, so rows are labelled ``snapshot_observation`` and the
retrieval time is retained.  HKO warning history for Hong Kong is already
carried by the local-consumer weather layer; this module is the mainland-plus-
HKIA hub complement.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from ..config import (
    AIRLINE_WEATHER_HUBS,
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    NORMALIZED_DIR,
    OPENMETEO_ARCHIVE_URL,
    OPENMETEO_FORECAST_URL,
    WEATHER_HEAVY_RAIN_MM,
    WEATHER_HIGH_WIND_KMH,
    WMO_CODE_LABELS,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_weather_risk.csv"
MONTHLY_OUTPUT_PATH = NORMALIZED_DIR / "airline_weather_risk_monthly.csv"
DATASET_ID = "airline_weather_risk"

DAILY_COLUMNS = [
    "dataset_id",
    "airport",
    "airport_label",
    "observation_date",
    "temperature_2m_max_c",
    "temperature_2m_min_c",
    "precipitation_sum_mm",
    "wind_speed_10m_max_kmh",
    "weather_code",
    "weather_label",
    "heavy_rain_day",
    "high_wind_day",
    "fog_day",
    "source_api",
    "point_in_time_status",
    "source_quality",
    "raw_snapshot_path",
    "retrieved_at",
]

MONTHLY_COLUMNS = [
    "dataset_id",
    "airport",
    "airport_label",
    "observation_month",
    "days_observed",
    "heavy_rain_days",
    "high_wind_days",
    "fog_days",
    "max_precipitation_mm",
    "mean_precipitation_mm",
    "max_wind_kmh",
    "mean_max_temp_c",
    "disruption_flag",
    "source_note",
    "retrieved_at",
]

ARCHIVE_DAILY_VARS = (
    "temperature_2m_max,temperature_2m_min,precipitation_sum,"
    "wind_speed_10m_max,weather_code"
)
FORECAST_DAILY_VARS = "precipitation_sum,wind_speed_10m_max,weather_code"


def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(
        url,
        params=params,
        headers=DEFAULT_HEADERS,
        timeout=max(DEFAULT_TIMEOUT, 30),
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise ValueError(f"Open-Meteo error for {url}: {payload.get('reason')}")
    return payload


def _weather_label(code: float | None) -> str | None:
    if code is None or pd.isna(code):
        return None
    return WMO_CODE_LABELS.get(int(code), f"wmo_{int(code)}")


def _disruption_flags(
    precipitation: float | None,
    wind: float | None,
    weather_label: str | None,
) -> tuple[bool, bool, bool]:
    heavy_rain = precipitation is not None and precipitation >= WEATHER_HEAVY_RAIN_MM
    high_wind = wind is not None and wind >= WEATHER_HIGH_WIND_KMH
    fog = weather_label in ("fog", "depositing_rime_fog")
    return heavy_rain, high_wind, fog


def fetch_airline_weather_risk(
    *,
    archive_start: str | None = None,
    days_back: int = 45,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch daily weather for all hubs and persist daily + monthly panels.

    ``archive_start`` defaults to 2020-01-01 (COVID baseline era included for
    disruption-rate context); ``days_back`` controls the forecast-API window
    that covers the most recent days not yet in the archive.  The daily panel
    is deduplicated by (airport, observation_date) keeping the latest source.
    """
    retrieved = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date()
    archive_start_date = archive_start or "2020-01-01"
    archive_end = today - timedelta(days=days_back)
    forecast_start = today - timedelta(days=days_back)

    daily_frames: list[pd.DataFrame] = []
    for airport, hub in AIRLINE_WEATHER_HUBS.items():
        params = {
            "latitude": hub["latitude"],
            "longitude": hub["longitude"],
            "daily": ARCHIVE_DAILY_VARS,
            "timezone": "Asia/Shanghai",
        }
        archive: dict[str, Any] | None = None
        if archive_end >= pd.Timestamp(archive_start_date).date():
            archive = _get_json(
                OPENMETEO_ARCHIVE_URL,
                {
                    **params,
                    "start_date": archive_start_date,
                    "end_date": archive_end.isoformat(),
                },
            )
        forecast: dict[str, Any] | None = None
        try:
            forecast = _get_json(
                OPENMETEO_FORECAST_URL,
                {
                    "latitude": hub["latitude"],
                    "longitude": hub["longitude"],
                    "daily": FORECAST_DAILY_VARS,
                    "timezone": "Asia/Shanghai",
                    "past_days": days_back,
                    "forecast_days": 3,
                },
            )
        except Exception as exc:  # forecast is optional; archive may suffice
            logger.warning("Open-Meteo forecast failed for %s: %s", airport, exc)

        raw_path = save_raw_snapshot(
            f"airline_weather_risk_{airport.lower()}",
            {"archive": archive, "forecast": forecast},
            file_ext="json",
            source_url=OPENMETEO_ARCHIVE_URL,
        )

        daily_frames.append(
            _archive_to_daily(
                airport,
                hub["label"],
                archive,
                raw_path,
                retrieved,
            )
        )
        if forecast is not None:
            daily_frames.append(
                _forecast_to_daily(
                    airport,
                    hub["label"],
                    forecast,
                    raw_path,
                    retrieved,
                )
            )

    non_empty_frames = [frame for frame in daily_frames if not frame.empty]
    if not non_empty_frames:
        raise ValueError("No Open-Meteo rows fetched for any hub")
    daily = pd.concat(non_empty_frames, ignore_index=True)
    if daily.empty:
        raise ValueError("No Open-Meteo rows fetched for any hub")
    daily = daily.drop_duplicates(
        subset=["airport", "observation_date"], keep="last"
    ).reindex(columns=DAILY_COLUMNS)
    daily = daily.sort_values(["airport", "observation_date"]).reset_index(drop=True)
    daily.to_csv(OUTPUT_PATH, index=False)

    monthly = _build_monthly(daily, retrieved)
    monthly.to_csv(MONTHLY_OUTPUT_PATH, index=False)
    return daily, monthly


def _archive_to_daily(
    airport: str,
    label: str,
    archive: dict[str, Any] | None,
    raw_path: str | None,
    retrieved: str,
) -> pd.DataFrame:
    if not archive or "daily" not in archive:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    daily = archive["daily"]
    rows: list[dict[str, Any]] = []
    for i, date in enumerate(daily.get("time", [])):
        weather_label = _weather_label(_safe(daily, "weather_code", i))
        precipitation = _safe(daily, "precipitation_sum", i)
        wind = _safe(daily, "wind_speed_10m_max", i)
        heavy_rain, high_wind, fog = _disruption_flags(
            precipitation, wind, weather_label
        )
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "airport": airport,
                "airport_label": label,
                "observation_date": date,
                "temperature_2m_max_c": _safe(daily, "temperature_2m_max", i),
                "temperature_2m_min_c": _safe(daily, "temperature_2m_min", i),
                "precipitation_sum_mm": precipitation,
                "wind_speed_10m_max_kmh": wind,
                "weather_code": _safe(daily, "weather_code", i),
                "weather_label": weather_label,
                "heavy_rain_day": heavy_rain,
                "high_wind_day": high_wind,
                "fog_day": fog,
                "source_api": "openmeteo_archive",
                "point_in_time_status": "snapshot_observation",
                "source_quality": "openmeteo_era5_based_archive",
                "raw_snapshot_path": raw_path,
                "retrieved_at": retrieved,
            }
        )
    return pd.DataFrame(rows, columns=DAILY_COLUMNS)


def _forecast_to_daily(
    airport: str,
    label: str,
    forecast: dict[str, Any] | None,
    raw_path: str | None,
    retrieved: str,
) -> pd.DataFrame:
    if not forecast or "daily" not in forecast:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    daily = forecast["daily"]
    rows: list[dict[str, Any]] = []
    today = datetime.now(timezone.utc).date().isoformat()
    for i, date in enumerate(daily.get("time", [])):
        weather_label = _weather_label(_safe(daily, "weather_code", i))
        precipitation = _safe(daily, "precipitation_sum", i)
        wind = _safe(daily, "wind_speed_10m_max", i)
        heavy_rain, high_wind, fog = _disruption_flags(
            precipitation, wind, weather_label
        )
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "airport": airport,
                "airport_label": label,
                "observation_date": date,
                "temperature_2m_max_c": None,
                "temperature_2m_min_c": None,
                "precipitation_sum_mm": precipitation,
                "wind_speed_10m_max_kmh": wind,
                "weather_code": _safe(daily, "weather_code", i),
                "weather_label": weather_label,
                "heavy_rain_day": heavy_rain,
                "high_wind_day": high_wind,
                "fog_day": fog,
                "source_api": (
                    "openmeteo_forecast_past_days"
                    if date <= today
                    else "openmeteo_forecast_future"
                ),
                "point_in_time_status": (
                    "snapshot_observation"
                    if date <= today
                    else "future_forecast_projection"
                ),
                "source_quality": "openmeteo_forecast_model",
                "raw_snapshot_path": raw_path,
                "retrieved_at": retrieved,
            }
        )
    return pd.DataFrame(rows, columns=DAILY_COLUMNS)


def _safe(daily: dict[str, Any], key: str, index: int) -> float | None:
    values = daily.get(key)
    if not values or index >= len(values) or pd.isna(values[index]):
        return None
    return float(values[index])


def _build_monthly(daily: pd.DataFrame, retrieved: str) -> pd.DataFrame:
    daily = daily.copy()
    daily["observation_month"] = pd.to_datetime(
        daily["observation_date"]
    ).dt.to_period("M").astype(str)
    rows: list[dict[str, Any]] = []
    for (airport, month), group in daily.groupby(
        ["airport", "observation_month"]
    ):
        label = group["airport_label"].iloc[0]
        heavy = int(group["heavy_rain_day"].sum())
        windy = int(group["high_wind_day"].sum())
        fog = int(group["fog_day"].sum())
        days = int(len(group))
        max_precip = group["precipitation_sum_mm"].max()
        max_wind = group["wind_speed_10m_max_kmh"].max()
        disruption_flag = (
            "high"
            if heavy >= 4 or windy >= 4
            else "moderate"
            if heavy >= 2 or windy >= 2 or fog >= 4
            else "low"
        )
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "airport": airport,
                "airport_label": label,
                "observation_month": month,
                "days_observed": days,
                "heavy_rain_days": heavy,
                "high_wind_days": windy,
                "fog_days": fog,
                "max_precipitation_mm": max_precip,
                "mean_precipitation_mm": group["precipitation_sum_mm"].mean(),
                "max_wind_kmh": max_wind,
                "mean_max_temp_c": group["temperature_2m_max_c"].mean(),
                "disruption_flag": disruption_flag,
                "source_note": (
                    "Monthly aggregate of Open-Meteo daily weather for the "
                    "airline hub; thresholds are broad aviation-disruption "
                    "proxies (>=25mm rain, >=40km/h wind, fog codes).  "
                    "Weather is a risk/execution variable, not an earnings "
                    "forecast."
                ),
                "retrieved_at": retrieved,
            }
        )
    return pd.DataFrame(rows, columns=MONTHLY_COLUMNS).sort_values(
        ["airport", "observation_month"]
    ).reset_index(drop=True)


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "MONTHLY_OUTPUT_PATH",
    "fetch_airline_weather_risk",
    "source_path",
]
