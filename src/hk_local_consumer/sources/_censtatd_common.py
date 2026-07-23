"""Shared fetch/parse helpers for CenStatD "web table" data files.

CenStatD's interactive table viewer (web_table.html) is JS-rendered, but the
underlying per-series CSV files it loads are plain, unauthenticated static
files -- verified by reading censtatd.gov.hk/js/cnds_cdm.js's
getMdtFilename(), which builds each file as:

    MDT_<theme_id>_<table_id>_<stat_var>_<stat_pres>.csv

served from CENSTATD_DATA_BASE_URL. The valid (stat_var, stat_pres) pairs
for a table are declared in its table_<table_id>_comp.json; classification
code -> label lookups (e.g. which OUTLET_TYPE/REST_GRP code means what) live
in table_<table_id>_lang.json's cv_list; and the shared suppression-flag
meanings (which sd_value codes mean "not available" vs "provisional") live
in sd_lang.json. All three were fetched and inspected directly against
live tables (620-67002/620-67003/625-68001/625-68003) before writing this.
"""

from __future__ import annotations

import io
import logging
import re
from typing import Any

import pandas as pd
import requests

from ..config import CENSTATD_DATA_BASE_URL, DEFAULT_HEADERS

logger = logging.getLogger(__name__)

_sd_lang_cache: dict[str, Any] | None = None


def fetch_mdt_csv(theme_id: str, table_id: str, stat_var: str, stat_pres: str) -> pd.DataFrame:
    filename_stat_pres = stat_pres.replace("%", "percent").replace("/", "slash")
    filename = f"MDT_{theme_id}_{table_id}_{stat_var}_{filename_stat_pres}.csv"
    url = f"{CENSTATD_DATA_BASE_URL}/{filename}"
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text))


def fetch_table_lang(table_id: str) -> dict[str, Any]:
    url = f"{CENSTATD_DATA_BASE_URL}/en/table_{table_id}_lang.json"
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_sd_lang() -> dict[str, Any]:
    global _sd_lang_cache
    if _sd_lang_cache is None:
        url = f"{CENSTATD_DATA_BASE_URL}/en/sd_lang.json"
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        resp.raise_for_status()
        _sd_lang_cache = resp.json()
    return _sd_lang_cache


def _clean_label(raw: str) -> str:
    return re.sub(r"<[^>]+>", "", raw).strip()


def classification_labels(lang_json: dict[str, Any], cv_name: str) -> dict[str, str]:
    """Map a classification variable's codes (e.g. OUTLET_TYPE "32") to their label."""
    cv = lang_json["cv_list"][cv_name]
    labels: dict[str, str] = {}
    for ccg in cv.get("ccg_list", {}).values():
        for code, info in ccg.get("cc_list", {}).items():
            labels[code] = _clean_label(info["def_class_code_desc"])
    return labels


def _sd_lookup(sd_value: Any, sd_lang: dict[str, Any]) -> dict[str, Any] | None:
    if pd.isna(sd_value):
        return None
    return sd_lang.get(str(int(sd_value)))


def drop_suppressed(df: pd.DataFrame, sd_lang: dict[str, Any], sd_col: str = "sd_value") -> pd.DataFrame:
    suppressed = df[sd_col].apply(lambda sd: bool((_sd_lookup(sd, sd_lang) or {}).get("obs_value_suppressed") == "1"))
    return df[~suppressed].copy()


def provisional_flags(df: pd.DataFrame, sd_lang: dict[str, Any], sd_col: str = "sd_value") -> pd.Series:
    return df[sd_col].apply(lambda sd: (_sd_lookup(sd, sd_lang) or {}).get("sd_symbol") == "p")
