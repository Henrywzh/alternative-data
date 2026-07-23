"""C&SD monthly retail sales value/volume index by outlet type.

Fetches CenStatD table 620-67002 (value index) and 620-67003 (volume
index) directly as CSV -- see _censtatd_common.py for how the real file
names, classification-code labels, and suppression flags were discovered
and verified against the live site. The previously configured
CNSD_API_BASE_URL endpoint is a documented dead end (see config.py); this
module no longer uses it.
"""

from __future__ import annotations

import logging

import pandas as pd

from ..config import (
    CENSTATD_RETAIL_SALES_TABLE_ID,
    CENSTATD_RETAIL_SALES_THEME_ID,
    CENSTATD_RETAIL_SALES_VOLUME_TABLE_ID,
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

SCHEMA_COLUMNS = ["date", "category", "sales_value_index", "sales_volume_index", "visitor_arrivals_thousands", "is_provisional"]


def _monthly_rows(df: pd.DataFrame, sd_lang: dict, value_col_name: str) -> pd.DataFrame:
    df = drop_suppressed(df, sd_lang)
    df["is_provisional"] = provisional_flags(df, sd_lang)
    # MM is blank for annual-total rows; this dataset is monthly-grained only.
    df = df[df["MM"].notna()]
    df = df.rename(columns={"obs_value": value_col_name})
    # Codes arrive as floats (12.0); label keys from classification_labels
    # are strings (JSON object keys), so normalize to matching string form.
    df["OUTLET_TYPE"] = df["OUTLET_TYPE"].apply(lambda v: "" if pd.isna(v) else str(int(v)))
    return df[["OUTLET_TYPE", "CCYY", "MM", value_col_name, "is_provisional"]]


def fetch_cnsd_retail_sales() -> pd.DataFrame:
    """Fetch C&SD retail sales value/volume index by outlet type, monthly."""
    try:
        value_raw = fetch_mdt_csv(CENSTATD_RETAIL_SALES_THEME_ID, CENSTATD_RETAIL_SALES_TABLE_ID, "VAL_IDX_RS", "Raw_1dp_idx_n")
        volume_raw = fetch_mdt_csv(CENSTATD_RETAIL_SALES_THEME_ID, CENSTATD_RETAIL_SALES_VOLUME_TABLE_ID, "VOL_IDX_RS", "Raw_1dp_idx_n")
        lang = fetch_table_lang(CENSTATD_RETAIL_SALES_TABLE_ID)
        sd_lang = fetch_sd_lang()
    except Exception as exc:
        logger.warning(f"Network fetch failed for C&SD retail sales ({exc}).")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    labels = classification_labels(lang, "OUTLET_TYPE")
    # The blank OUTLET_TYPE code is the classification group's own total row.
    total_desc = lang["cv_list"]["OUTLET_TYPE"]["ccg_list"]["1"].get("total_desc") or "All retail outlet"
    labels[""] = total_desc

    value_df = _monthly_rows(value_raw, sd_lang, "sales_value_index")
    volume_df = _monthly_rows(volume_raw, sd_lang, "sales_volume_index").drop(columns=["is_provisional"])

    merged = value_df.merge(volume_df, on=["OUTLET_TYPE", "CCYY", "MM"], how="left")
    merged["category"] = merged["OUTLET_TYPE"].map(labels)
    merged = merged.dropna(subset=["category"])
    merged["date"] = pd.to_datetime(
        merged["CCYY"].astype(int).astype(str) + "-" + merged["MM"].astype(int).astype(str).str.zfill(2) + "-01"
    ).dt.strftime("%Y-%m-%d")
    merged["visitor_arrivals_thousands"] = None

    result = merged[["date", "category", "sales_value_index", "sales_volume_index", "visitor_arrivals_thousands", "is_provisional"]]
    result = result.sort_values(["date", "category"]).reset_index(drop=True)

    if result.empty:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    source_url = f"https://www.censtatd.gov.hk/data/MDT_{CENSTATD_RETAIL_SALES_THEME_ID}_{CENSTATD_RETAIL_SALES_TABLE_ID}_VAL_IDX_RS_Raw_1dp_idx_n.csv"
    raw_path = save_raw_snapshot("cnsd_retail_sales", result.to_dict(orient="records"), file_ext="json", source_url=source_url)
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = source_url
    return result
