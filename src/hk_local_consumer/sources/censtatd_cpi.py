"""C&SD Composite Consumer Price Index -- headline + COICOP category breakdown.

Two tables, same theme (54, "CPI"), same MDT_ static-file pattern as
``cnsd_retail.py``:

- ``510-60001`` -- headline Composite/A/B/C CPI (base 2019/20=100), monthly
  since October 1974, no category dimension.
- ``510-60003`` -- the same basis indices broken out by COICOP category
  (Food, Housing, Transport, ...), monthly only since 2005 -- thirty years
  shorter history than the headline table. Confirmed directly (not assumed
  from a third-party summary): an earlier claim that this pair of tables
  lived under ids ``520-83001``/``520-83001`` was wrong -- those ids do not
  exist on CenStatD's API.

Only the Composite (``CC_CM_1920``) series is fetched from each table --
the A/B/C basis indices (lower/middle/upper spending-basket variants) exist
in the same tables but are not currently surfaced on this dashboard.
"""

from __future__ import annotations

import logging

import pandas as pd

from ..config import (
    CENSTATD_CPI_CATEGORY_TABLE_ID,
    CENSTATD_CPI_HEADLINE_TABLE_ID,
    CENSTATD_CPI_THEME_ID,
)
from ..storage import save_raw_snapshot
from ._censtatd_common import (
    classification_labels,
    drop_suppressed,
    fetch_mdt_csv,
    fetch_sd_lang,
    fetch_table_lang,
    provisional_flags,
)

logger = logging.getLogger(__name__)

_STAT_VAR = "CC_CM_1920"
_STAT_PRES = "Raw_1dp_idx_n"

HEADLINE_COLUMNS = ["date", "value", "is_provisional"]
CATEGORY_COLUMNS = ["date", "category", "value", "is_provisional"]


def _monthly_index_rows(df: pd.DataFrame, sd_lang: dict) -> pd.DataFrame:
    df = drop_suppressed(df, sd_lang)
    df = df[df["MM"].notna()].copy()
    df["is_provisional"] = provisional_flags(df, sd_lang)
    df["date"] = pd.to_datetime(
        df["CCYY"].astype(int).astype(str) + "-" + df["MM"].astype(int).astype(str).str.zfill(2) + "-01"
    ).dt.strftime("%Y-%m-%d")
    return df


def fetch_cpi_headline() -> pd.DataFrame:
    """Monthly Composite CPI (base 2019/20=100), since October 1974."""
    try:
        raw = fetch_mdt_csv(CENSTATD_CPI_THEME_ID, CENSTATD_CPI_HEADLINE_TABLE_ID, _STAT_VAR, _STAT_PRES)
        sd_lang = fetch_sd_lang()
    except Exception as exc:
        logger.warning(f"Network fetch failed for C&SD headline CPI ({exc}).")
        return pd.DataFrame(columns=HEADLINE_COLUMNS)

    monthly = _monthly_index_rows(raw, sd_lang)
    monthly = monthly.rename(columns={"obs_value": "value"})
    result = monthly[HEADLINE_COLUMNS].sort_values("date").reset_index(drop=True)

    if result.empty:
        return pd.DataFrame(columns=HEADLINE_COLUMNS)

    source_url = (
        f"https://www.censtatd.gov.hk/data/MDT_{CENSTATD_CPI_THEME_ID}_"
        f"{CENSTATD_CPI_HEADLINE_TABLE_ID}_{_STAT_VAR}_{_STAT_PRES}.csv"
    )
    raw_path = save_raw_snapshot("censtatd_cpi_headline", result.to_dict(orient="records"), file_ext="json", source_url=source_url)
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = source_url
    return result


def fetch_cpi_by_category() -> pd.DataFrame:
    """Monthly Composite CPI by COICOP category, since 2005 only."""
    try:
        raw = fetch_mdt_csv(CENSTATD_CPI_THEME_ID, CENSTATD_CPI_CATEGORY_TABLE_ID, _STAT_VAR, _STAT_PRES)
        lang = fetch_table_lang(CENSTATD_CPI_CATEGORY_TABLE_ID)
        sd_lang = fetch_sd_lang()
    except Exception as exc:
        logger.warning(f"Network fetch failed for C&SD CPI by category ({exc}).")
        return pd.DataFrame(columns=CATEGORY_COLUMNS)

    labels = classification_labels(lang, "COICOP")

    monthly = _monthly_index_rows(raw, sd_lang)
    monthly = monthly.rename(columns={"obs_value": "value"})
    # COICOP arrives as a float code (1.0); label-dict keys are strings.
    monthly["category"] = monthly["COICOP"].apply(
        lambda v: None if pd.isna(v) else labels.get(str(int(v)))
    )
    monthly = monthly.dropna(subset=["category"])
    result = monthly[CATEGORY_COLUMNS].sort_values(["category", "date"]).reset_index(drop=True)

    if result.empty:
        return pd.DataFrame(columns=CATEGORY_COLUMNS)

    source_url = (
        f"https://www.censtatd.gov.hk/data/MDT_{CENSTATD_CPI_THEME_ID}_"
        f"{CENSTATD_CPI_CATEGORY_TABLE_ID}_{_STAT_VAR}_{_STAT_PRES}.csv"
    )
    raw_path = save_raw_snapshot("censtatd_cpi_by_category", result.to_dict(orient="records"), file_ext="json", source_url=source_url)
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = source_url
    return result
