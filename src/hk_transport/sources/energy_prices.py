"""Free daily and weekly crude/jet-fuel benchmarks for airline research.

The EIA workbook is used instead of a paid Platts/Argus feed.  It contains
WTI, Brent and U.S. Gulf Coast kerosene-type jet fuel spot prices.  Rows keep
both the market observation date and the workbook release date so a later
revision or delayed publication cannot be mistaken for information that was
available at the observation date.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, EIA_SPOT_PRICES_URLS, NORMALIZED_DIR
from ..storage import save_raw_snapshot

ENERGY_PRICE_COLUMNS = [
    "dataset_id",
    "frequency",
    "observation_date",
    "series_id",
    "series_name",
    "metric",
    "value",
    "unit",
    "currency",
    "price_basis",
    "source_release_date",
    "retrieved_at",
    "source_name",
    "source_url",
]

_SHEET_CONFIG = {
    "Data 1": {
        1: ("RWTC", "WTI spot price", "USD per barrel"),
        2: ("RBRTE", "Brent spot price", "USD per barrel"),
    },
    "Data 6": {
        1: (
            "EER_EPJK_PF4_RGC_DPG",
            "U.S. Gulf Coast kerosene-type jet fuel spot price",
            "USD per gallon",
        ),
    },
}


def _parse_release_date(contents: pd.DataFrame) -> str | None:
    for _, row in contents.iterrows():
        values = [str(value).strip() for value in row.tolist() if pd.notna(value)]
        if not values:
            continue
        if values[0].lower().startswith("release date") and len(values) > 1:
            parsed = pd.to_datetime(values[1], errors="coerce")
            if pd.notna(parsed):
                return parsed.strftime("%Y-%m-%d")
    return None


def _parse_date(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def parse_eia_spot_price_workbook(
    payload: bytes,
    *,
    frequency: str,
    source_url: str,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse EIA's ``PET_PRI_SPT_S1_[D|W].xls`` workbook."""
    if frequency not in {"daily", "weekly"}:
        raise ValueError("frequency must be 'daily' or 'weekly'")

    workbook = pd.ExcelFile(io.BytesIO(payload))
    if "Contents" not in workbook.sheet_names:
        raise ValueError("EIA spot-price workbook is missing the Contents sheet")
    contents = pd.read_excel(io.BytesIO(payload), sheet_name="Contents", header=None)
    release_date = _parse_release_date(contents)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []

    for sheet_name, series_config in _SHEET_CONFIG.items():
        if sheet_name not in workbook.sheet_names:
            raise ValueError(f"EIA spot-price workbook is missing {sheet_name}")
        frame = pd.read_excel(io.BytesIO(payload), sheet_name=sheet_name, header=None)
        if frame.empty or frame.shape[1] < 2:
            continue
        for value_column, (series_id, series_name, unit) in series_config.items():
            if value_column >= frame.shape[1]:
                raise ValueError(f"EIA {sheet_name} is missing value column {value_column}")
            for _, record in frame.iloc[3:].iterrows():
                observation_date = _parse_date(record.iloc[0])
                value = pd.to_numeric(record.iloc[value_column], errors="coerce")
                if observation_date is None or pd.isna(value):
                    continue
                rows.append(
                    {
                        "dataset_id": "airline_energy_prices",
                        "frequency": frequency,
                        "observation_date": observation_date,
                        "series_id": series_id,
                        "series_name": series_name,
                        "metric": "spot_price",
                        "value": float(value),
                        "unit": unit,
                        "currency": "USD",
                        "price_basis": "FOB spot",
                        "source_release_date": release_date,
                        "retrieved_at": retrieved,
                        "source_name": "U.S. Energy Information Administration",
                        "source_url": source_url,
                    }
                )

    result = pd.DataFrame(rows, columns=ENERGY_PRICE_COLUMNS)
    if result.empty:
        return result
    result = result.drop_duplicates(subset=["frequency", "observation_date", "series_id"], keep="last")
    return result.sort_values(["observation_date", "series_id"]).reset_index(drop=True)


def fetch_eia_spot_prices(
    *,
    frequency: str = "daily",
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch and parse the latest EIA daily or weekly spot-price workbook."""
    if frequency not in EIA_SPOT_PRICES_URLS:
        raise ValueError(f"Unsupported frequency: {frequency}")
    source_url = EIA_SPOT_PRICES_URLS[frequency]
    client = session or requests.Session()
    response = client.get(source_url, headers=DEFAULT_HEADERS, timeout=max(DEFAULT_TIMEOUT, 30))
    response.raise_for_status()
    raw_path = save_raw_snapshot(
        f"eia_spot_prices_{frequency}",
        response.content,
        file_ext="xls",
        source_url=source_url,
    )
    result = parse_eia_spot_price_workbook(
        response.content,
        frequency=frequency,
        source_url=source_url,
    )
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = source_url
    return result


def fetch_eia_airline_energy_prices() -> pd.DataFrame:
    """Fetch daily and weekly EIA benchmarks into one tidy frame."""
    frames = [fetch_eia_spot_prices(frequency=frequency) for frequency in ("daily", "weekly")]
    result = pd.concat(frames, ignore_index=True).sort_values(
        ["frequency", "observation_date", "series_id"]
    ).reset_index(drop=True)
    if result.empty:
        return result

    # Keep one row per source-release vintage.  Re-running the collector on
    # the same EIA release updates retrieved_at but does not create a second
    # economic observation; a revised workbook release remains preserved.
    path = NORMALIZED_DIR / "airline_energy_prices.parquet"
    existing = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=ENERGY_PRICE_COLUMNS)
    merged = result.copy() if existing.empty else pd.concat([existing, result], ignore_index=True)
    merged = merged.drop_duplicates(
        subset=["frequency", "observation_date", "series_id", "source_release_date"],
        keep="last",
    ).sort_values(["frequency", "observation_date", "series_id", "source_release_date"])
    merged = merged.reset_index(drop=True)
    merged.to_parquet(path, index=False)
    return merged
