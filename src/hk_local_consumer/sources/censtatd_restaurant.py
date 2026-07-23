"""CenStatD quarterly restaurant receipts & purchases survey.

Fetches CenStatD table 625-68003 (receipts and indices by restaurant type,
via the REST_GRP classification variable) and 625-68001 (sector-wide
totals, the only table that also publishes purchases) directly as CSV --
see _censtatd_common.py for how the real file names, classification-code
labels, and suppression flags were discovered and verified against the
live site. The previously configured CNSD_API_BASE_URL endpoint is a
documented dead end (see config.py); this module no longer uses it.
Purchases are only published sector-wide, so per-type rows leave
total_purchases_hkd_m as null rather than guessing a breakdown.
"""

from __future__ import annotations

import logging

import pandas as pd

from ..config import (
    CENSTATD_RESTAURANT_TABLE_ID,
    CENSTATD_RESTAURANT_THEME_ID,
    CENSTATD_RESTAURANT_TOTALS_TABLE_ID,
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

SCHEMA_COLUMNS = [
    "quarter", "date", "sub_sector", "total_receipts_hkd_m", "total_purchases_hkd_m",
    "receipts_value_index", "purchases_value_index", "is_provisional",
]


def _quarter_end_date(ccyy: pd.Series, q: pd.Series) -> pd.Series:
    quarter_end_month = q.astype(int).map({1: 3, 2: 6, 3: 9, 4: 12})
    return pd.to_datetime(ccyy.astype(int).astype(str) + "-" + quarter_end_month.astype(str).str.zfill(2) + "-01") + pd.offsets.MonthEnd(0)


def _by_type_rows(sd_lang: dict, labels: dict[str, str]) -> pd.DataFrame:
    receipts = fetch_mdt_csv(CENSTATD_RESTAURANT_THEME_ID, CENSTATD_RESTAURANT_TABLE_ID, "VAL_RR", "Raw_M_hkd_d")
    value_idx = fetch_mdt_csv(CENSTATD_RESTAURANT_THEME_ID, CENSTATD_RESTAURANT_TABLE_ID, "VAL_IDX_RR", "Raw_1dp_idx_n")

    receipts = drop_suppressed(receipts, sd_lang).rename(columns={"obs_value": "total_receipts_hkd_m"})
    value_idx = drop_suppressed(value_idx, sd_lang)
    value_idx["is_provisional"] = provisional_flags(value_idx, sd_lang)
    value_idx = value_idx.rename(columns={"obs_value": "receipts_value_index"})

    merged = receipts[["REST_GRP", "CCYY", "Q", "total_receipts_hkd_m"]].merge(
        value_idx[["REST_GRP", "CCYY", "Q", "receipts_value_index", "is_provisional"]],
        on=["REST_GRP", "CCYY", "Q"],
        how="outer",
    )
    merged = merged[merged["REST_GRP"].notna() & merged["Q"].notna()]
    merged["sub_sector"] = merged["REST_GRP"].astype(int).astype(str).map(labels)
    merged = merged.dropna(subset=["sub_sector"])
    merged["total_purchases_hkd_m"] = float("nan")
    merged["purchases_value_index"] = float("nan")
    return merged[["CCYY", "Q", "sub_sector", "total_receipts_hkd_m", "total_purchases_hkd_m", "receipts_value_index", "purchases_value_index", "is_provisional"]]


def _totals_row(sd_lang: dict) -> pd.DataFrame:
    receipts = fetch_mdt_csv(CENSTATD_RESTAURANT_THEME_ID, CENSTATD_RESTAURANT_TOTALS_TABLE_ID, "VAL_RR", "Raw_M_hkd_d")
    purchases = fetch_mdt_csv(CENSTATD_RESTAURANT_THEME_ID, CENSTATD_RESTAURANT_TOTALS_TABLE_ID, "VAL_RP", "Raw_M_hkd_d")
    value_idx = fetch_mdt_csv(CENSTATD_RESTAURANT_THEME_ID, CENSTATD_RESTAURANT_TOTALS_TABLE_ID, "VAL_IDX_RR", "Raw_1dp_idx_n")

    receipts = drop_suppressed(receipts, sd_lang).rename(columns={"obs_value": "total_receipts_hkd_m"})
    purchases = drop_suppressed(purchases, sd_lang).rename(columns={"obs_value": "total_purchases_hkd_m"})
    value_idx = drop_suppressed(value_idx, sd_lang)
    value_idx["is_provisional"] = provisional_flags(value_idx, sd_lang)
    value_idx = value_idx.rename(columns={"obs_value": "receipts_value_index"})

    merged = receipts[["CCYY", "Q", "total_receipts_hkd_m"]].merge(
        purchases[["CCYY", "Q", "total_purchases_hkd_m"]], on=["CCYY", "Q"], how="outer"
    ).merge(value_idx[["CCYY", "Q", "receipts_value_index", "is_provisional"]], on=["CCYY", "Q"], how="outer")
    merged = merged[merged["Q"].notna()]
    merged["sub_sector"] = "All restaurants"
    merged["purchases_value_index"] = float("nan")
    return merged[["CCYY", "Q", "sub_sector", "total_receipts_hkd_m", "total_purchases_hkd_m", "receipts_value_index", "purchases_value_index", "is_provisional"]]


def fetch_censtatd_restaurant_survey() -> pd.DataFrame:
    """Fetch CenStatD quarterly restaurant receipts (& sector-wide purchases) survey."""
    try:
        lang = fetch_table_lang(CENSTATD_RESTAURANT_TABLE_ID)
        sd_lang = fetch_sd_lang()
        labels = classification_labels(lang, "REST_GRP")
        by_type = _by_type_rows(sd_lang, labels)
        totals = _totals_row(sd_lang)
    except Exception as exc:
        logger.warning(f"Network fetch failed for CenStatD restaurant survey ({exc}).")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    combined = pd.concat([totals, by_type], ignore_index=True)
    combined["quarter"] = combined["CCYY"].astype(int).astype(str) + "-Q" + combined["Q"].astype(int).astype(str)
    combined["date"] = _quarter_end_date(combined["CCYY"], combined["Q"]).dt.strftime("%Y-%m-%d")
    result = combined[SCHEMA_COLUMNS].sort_values(["date", "sub_sector"]).reset_index(drop=True)

    if result.empty:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    source_url = f"https://www.censtatd.gov.hk/data/MDT_{CENSTATD_RESTAURANT_THEME_ID}_{CENSTATD_RESTAURANT_TABLE_ID}_VAL_RR_Raw_M_hkd_d.csv"
    raw_path = save_raw_snapshot("censtatd_restaurant_survey", result.to_dict(orient="records"), file_ext="json", source_url=source_url)
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = source_url
    return result
