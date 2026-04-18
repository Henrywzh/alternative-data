from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd


def to_datetime(series: pd.Series, *, utc: bool = False) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=utc)


def to_date_string(series: pd.Series) -> pd.Series:
    values = pd.to_datetime(series, errors="coerce")
    return values.dt.strftime("%Y-%m-%d")


def clean_model_id(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip()


def clean_text(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip()


def to_filter_list(values: str | Iterable[str] | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [values]
    return [value for value in values if value is not None]


def percentile_rank(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    mask = numeric.notna()
    ranked = pd.Series(np.nan, index=series.index, dtype="float64")
    if mask.any():
        ranked.loc[mask] = numeric.loc[mask].rank(method="average", pct=True)
    return ranked


def mean_of_available(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    if not columns:
        return pd.Series(dtype="float64")
    return frame[columns].mean(axis=1, skipna=True)
