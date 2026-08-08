"""Free daily USD/CNY and USD/HKD reference rates for airline research.

The ECB publishes daily reference rates against EUR.  We derive the two
airline-relevant pairs from the same day's CNY, HKD and USD observations so
that USD fuel benchmarks can be translated consistently into reporting
currencies.  The ECB endpoint does not expose a full historical release
vintage, so the observation date and retrieval timestamp are both retained.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, ECB_REFERENCE_RATES_URL, NORMALIZED_DIR
from ..storage import save_raw_snapshot

FX_RATE_COLUMNS = [
    "dataset_id",
    "frequency",
    "observation_date",
    "pair",
    "base_currency",
    "quote_currency",
    "value",
    "unit",
    "source_release_date",
    "retrieved_at",
    "source_name",
    "source_url",
    "source_reference_currency",
]


def parse_ecb_reference_rates_csv(
    payload: bytes,
    *,
    source_url: str,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse ECB CSV data and derive USD/CNY and USD/HKD rates."""
    frame = pd.read_csv(io.BytesIO(payload))
    required = {"TIME_PERIOD", "CURRENCY", "CURRENCY_DENOM", "OBS_VALUE"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"ECB FX CSV is missing columns: {sorted(missing)}")

    frame = frame.loc[
        frame["CURRENCY"].isin(["USD", "CNY", "HKD"])
        & frame["CURRENCY_DENOM"].eq("EUR")
    ].copy()
    frame["observation_date"] = pd.to_datetime(frame["TIME_PERIOD"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame["eur_rate"] = pd.to_numeric(frame["OBS_VALUE"], errors="coerce")
    frame = frame.dropna(subset=["observation_date", "eur_rate"])
    if frame.empty:
        raise ValueError("ECB FX CSV contained no usable EUR reference rates")

    pivot = frame.pivot_table(
        index="observation_date",
        columns="CURRENCY",
        values="eur_rate",
        aggfunc="last",
    )
    if not {"USD", "CNY", "HKD"}.issubset(pivot.columns):
        raise ValueError("ECB FX CSV must contain USD, CNY and HKD EUR reference rates")
    pivot = pivot.dropna(subset=["USD", "CNY", "HKD"])
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for observation_date, values in pivot.iterrows():
        for pair, quote_currency in (("USD_CNY", "CNY"), ("USD_HKD", "HKD")):
            rows.append(
                {
                    "dataset_id": "airline_fx_rates",
                    "frequency": "daily",
                    "observation_date": observation_date,
                    "pair": pair,
                    "base_currency": "USD",
                    "quote_currency": quote_currency,
                    "value": float(values[quote_currency] / values["USD"]),
                    "unit": "quote currency per USD",
                    "source_release_date": None,
                    "retrieved_at": retrieved,
                    "source_name": "European Central Bank reference exchange rates",
                    "source_url": source_url,
                    "source_reference_currency": "EUR",
                }
            )
    return pd.DataFrame(rows, columns=FX_RATE_COLUMNS).sort_values(
        ["observation_date", "pair"]
    ).reset_index(drop=True)


def fetch_ecb_airline_fx_rates() -> pd.DataFrame:
    """Fetch the ECB daily reference rates and persist a tidy history."""
    response = requests.get(
        ECB_REFERENCE_RATES_URL,
        headers=DEFAULT_HEADERS,
        timeout=max(DEFAULT_TIMEOUT, 30),
    )
    response.raise_for_status()
    raw_path = save_raw_snapshot(
        "ecb_airline_fx_rates",
        response.content,
        file_ext="csv",
        source_url=ECB_REFERENCE_RATES_URL,
    )
    result = parse_ecb_reference_rates_csv(
        response.content,
        source_url=ECB_REFERENCE_RATES_URL,
    )
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = ECB_REFERENCE_RATES_URL

    path = NORMALIZED_DIR / "airline_fx_rates.parquet"
    existing = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=FX_RATE_COLUMNS)
    merged = result.copy() if existing.empty else pd.concat([existing, result], ignore_index=True)
    merged = merged.drop_duplicates(
        subset=["frequency", "observation_date", "pair"],
        keep="last",
    ).sort_values(["frequency", "observation_date", "pair"])
    merged.reset_index(drop=True).to_parquet(path, index=False)
    return merged.reset_index(drop=True)

