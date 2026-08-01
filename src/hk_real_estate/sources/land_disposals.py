"""C&SD "Table E704: Disposals of government land" (Lands Department source).

This table lives outside the regular ~574 CenStatD "web table" catalog (no
``tb_code``/MDT_ pattern applies) -- it's part of a separate
subject/publication browsing structure. The real download URL was found by
fetching ``https://www.censtatd.gov.hk/en/data/stat_report/subject/100/report_index.json``
(subject 100) and reading its ``productIndex`` entry for
``Product_Code: "D7000004"``, which gives ``en_file: "D7000004.xlsx"``. The
working download pattern (discovered by testing, not documented anywhere) is

    https://www.censtatd.gov.hk/en/data/stat_report/product/<Product_Code>/att/<en_file>

not ``.../product/<Product_Code>/<en_file>``, which 404s.

The workbook has one sheet ("E704") with a four-level merged-cell header
(method -> district -> use category -> metric) that must be forward-filled
to reconstruct real column labels -- confirmed directly against the live
file, not assumed from a summary (an earlier pass's cited example value,
"2021 Q4 Residential/NT: 47,967 sq.m., HK$50,800m", was actually the Public
auction/tender x Urban area x Commercial cell, not Residential/NT -- this
module's row/column mapping was independently re-derived and checked against
raw cell values before writing this parser).
"""

from __future__ import annotations

import io

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot

LAND_DISPOSALS_PRODUCT_CODE = "D7000004"
LAND_DISPOSALS_URL = (
    "https://www.censtatd.gov.hk/en/data/stat_report/product/"
    f"{LAND_DISPOSALS_PRODUCT_CODE}/att/{LAND_DISPOSALS_PRODUCT_CODE}.xlsx"
)

# First quarterly data row is 2021 Q1; rows advance one quarter at a time
# with no gaps up to the latest published quarter (confirmed against the
# live file: 21 quarterly rows for 2021 Q1 through 2026 Q1 inclusive).
_FIRST_QUARTER_ROW = 21
_FIRST_QUARTER_YEAR = 2021

# Row index of each merged header level (0-indexed, matches the raw sheet).
_METHOD_ROW = 4
_DISTRICT_ROW = 7
_USE_ROW = 10
_METRIC_ROW = 13

_METHOD_LABELS = {
    "公開拍賣／投標": "public_auction_tender",
    "私人協約方式批地": "private_treaty_grant",
}
_DISTRICT_LABELS = {
    "市區": "urban",
    "新界": "new_territories",
}
_USE_LABELS = {
    "工業／貨倉": "industrial_godown",
    "商業": "commercial",
    "商業／住宅": "commercial_residential",
    "住宅": "residential",
    "其他用途": "other_uses",
    "公用事業／團體用途": "public_utility_community",
    "總計": "total",
}
_METRIC_LABELS = {
    "面積(平方米)": "area_sqm",
    "已徵收的地價(百萬元)": "realised_premium_hkd_million",
}

EXPECTED_COLUMNS = [
    "quarter",
    "method",
    "district",
    "use_category",
    "metric",
    "value",
    "source_agency",
]


def _quarter_start_iso(row_offset: int) -> str:
    idx = row_offset - _FIRST_QUARTER_ROW
    year = _FIRST_QUARTER_YEAR + idx // 4
    quarter = idx % 4 + 1
    month = (quarter - 1) * 3 + 1
    return f"{year}-{month:02d}-01"


def _parse_land_disposals(xlsx_bytes: bytes) -> pd.DataFrame:
    raw = pd.read_excel(io.BytesIO(xlsx_bytes), sheet_name="E704", header=None)

    method = raw.iloc[_METHOD_ROW, :].ffill()
    district = raw.iloc[_DISTRICT_ROW, :].ffill()
    use = raw.iloc[_USE_ROW, :].ffill()
    metric = raw.iloc[_METRIC_ROW, :].ffill()

    data_columns = [
        col
        for col in range(2, raw.shape[1])
        if pd.notna(raw.iloc[_METRIC_ROW, col])
    ]

    last_row = raw.shape[0]
    # Quarterly rows run from _FIRST_QUARTER_ROW to the last row that still
    # carries a real quarter-range label in column 1; footnote/source rows
    # below the data have no such label.
    quarter_rows = [
        r
        for r in range(_FIRST_QUARTER_ROW, last_row)
        if isinstance(raw.iloc[r, 1], str) and raw.iloc[r, 1].strip().replace(" ", "").replace("-", "")
        .isdigit()
    ]

    records = []
    for row in quarter_rows:
        quarter_iso = _quarter_start_iso(row)
        for col in data_columns:
            value = raw.iloc[row, col]
            if pd.isna(value):
                continue
            records.append(
                {
                    "quarter": quarter_iso,
                    "method": _METHOD_LABELS.get(str(method[col]).strip(), str(method[col]).strip()),
                    "district": _DISTRICT_LABELS.get(str(district[col]).strip(), str(district[col]).strip()),
                    "use_category": _USE_LABELS.get(str(use[col]).strip(), str(use[col]).strip()),
                    "metric": _METRIC_LABELS.get(str(metric[col]).strip(), str(metric[col]).strip()),
                    "value": float(value),
                    "source_agency": "Lands Department",
                }
            )

    df = pd.DataFrame(records, columns=EXPECTED_COLUMNS)
    if not df.empty:
        df = df.sort_values(["quarter", "method", "district", "use_category", "metric"]).reset_index(drop=True)
    return df


def fetch_land_disposals() -> pd.DataFrame:
    response = requests.get(LAND_DISPOSALS_URL, headers=DEFAULT_HEADERS, timeout=20)
    response.raise_for_status()
    raw_path = save_raw_snapshot(
        "censtatd_land_disposals_e704",
        response.content,
        file_ext="xlsx",
        source_url=LAND_DISPOSALS_URL,
    )
    df = _parse_land_disposals(response.content)
    df.attrs.update(raw_snapshot=str(raw_path), source_url=LAND_DISPOSALS_URL)
    return df
