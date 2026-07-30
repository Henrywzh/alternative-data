import io
import requests
import pandas as pd
from typing import Tuple

from ..config import (
    RVD_PRICE_1_4M_URL,
    RVD_RENTAL_1_3M_URL,
    RVD_OFFICE_RENTAL_2_3M_URL,
    RVD_RETAIL_3_2M_URL,
    DEFAULT_HEADERS,
)
from ..storage import save_raw_snapshot

def _parse_rvd_monthly_csv(csv_content: str) -> pd.DataFrame:
    """
    Parse official RVD monthly CSV (1.4M or 1.3M) dynamically matching column headers.
    """
    lines = [line for line in csv_content.strip().split('\n') if line.strip()]

    header_idx = -1
    for idx, line in enumerate(lines[:10]):
        if 'Month' in line or 'Class A' in line:
            header_idx = idx
            break

    if header_idx == -1:
        return pd.DataFrame()

    df_raw = pd.read_csv(io.StringIO('\n'.join(lines[header_idx:])))

    col_map = {}
    for col in df_raw.columns:
        c_clean = str(col).strip()
        if c_clean == 'Month':
            col_map[col] = 'date_raw'
        elif c_clean in {'Class A', 'Class B', 'Class C', 'Class D', 'Class E'}:
            col_map[col] = c_clean.lower().replace(' ', '_')
        elif c_clean in {
            'Class A - Remarks', 'Class B - Remarks', 'Class C - Remarks',
            'Class D - Remarks', 'Class E - Remarks',
        }:
            col_map[col] = c_clean.lower().replace(' ', '_').replace(' - ', '_')
        elif c_clean in ['All Classes', 'Overall']:
            col_map[col] = 'overall'
        elif c_clean in ['All Classes - Remarks', 'Overall - Remarks']:
            col_map[col] = 'overall_remarks'

    df_renamed = df_raw.rename(columns=col_map)

    records = []
    for _, row in df_renamed.iterrows():
        date_str = str(row.get('date_raw', '')).strip()
        if not date_str or date_str.lower() in ['month', 'nan']:
            continue

        overall_val = row.get('overall')
        remark_columns = [column for column in df_renamed.columns if str(column).endswith('_remarks')]
        is_prov = any('P' in str(row.get(column, '')).upper() for column in remark_columns)

        parts = date_str.split('-')
        if len(parts) == 2:
            mm, yyyy = parts[0].zfill(2), parts[1]
            if not mm.isdigit() or not yyyy.isdigit():
                continue
            iso_date = f"{yyyy}-{mm}-01"

            def clean_val(v):
                if pd.isna(v): return None
                v_clean = str(v).replace('P', '').replace(',', '').strip()
                try:
                    return float(v_clean)
                except ValueError:
                    return None

            records.append({
                'date': iso_date,
                'is_provisional': is_prov,
                'class_a': clean_val(row.get('class_a')),
                'class_b': clean_val(row.get('class_b')),
                'class_c': clean_val(row.get('class_c')),
                'class_d': clean_val(row.get('class_d')),
                'class_e': clean_val(row.get('class_e')),
                'overall': clean_val(overall_val),
                'source_agency': 'Rating and Valuation Department'
            })

    expected_columns = ['date', 'is_provisional', 'class_a', 'class_b', 'class_c', 'class_d', 'class_e', 'overall', 'source_agency']
    df_res = pd.DataFrame(records, columns=expected_columns)
    if not df_res.empty:
        if df_res['date'].duplicated().any():
            return pd.DataFrame(columns=expected_columns)
        df_res = df_res.sort_values('date').reset_index(drop=True)
    return df_res

def fetch_rvd_price_index() -> pd.DataFrame:
    r = requests.get(RVD_PRICE_1_4M_URL, headers=DEFAULT_HEADERS, timeout=15)
    r.raise_for_status()
    raw_path = save_raw_snapshot("rvd_price_1_4M", r.text, file_ext="csv", source_url=RVD_PRICE_1_4M_URL)
    df = _parse_rvd_monthly_csv(r.text)
    df.attrs.update(raw_snapshot=str(raw_path), source_url=RVD_PRICE_1_4M_URL)
    return df

def fetch_rvd_rental_index() -> pd.DataFrame:
    r = requests.get(RVD_RENTAL_1_3M_URL, headers=DEFAULT_HEADERS, timeout=15)
    r.raise_for_status()
    raw_path = save_raw_snapshot("rvd_rental_1_3M", r.text, file_ext="csv", source_url=RVD_RENTAL_1_3M_URL)
    df = _parse_rvd_monthly_csv(r.text)
    df.attrs.update(raw_snapshot=str(raw_path), source_url=RVD_RENTAL_1_3M_URL)
    return df


def _parse_rvd_commercial_csv(csv_content: str, sector: str) -> pd.DataFrame:
    """Parse RVD office/retail files to a long, metric-labelled contract."""
    lines = [line for line in csv_content.strip().splitlines() if line.strip()]
    header_idx = next((i for i, line in enumerate(lines[:10]) if "Month" in line), -1)
    columns = ["date", "segment", "metric", "value", "is_provisional", "source_agency"]
    if header_idx < 0:
        return pd.DataFrame(columns=columns)
    raw = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])))
    value_columns = [str(col) for col in raw.columns if str(col).strip() != "Month" and "Remarks" not in str(col)]
    rows = []
    for _, row in raw.iterrows():
        date_raw = str(row.get("Month", "")).strip()
        parts = date_raw.split("-")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        date = f"{parts[1]}-{parts[0].zfill(2)}-01"
        for column in value_columns:
            value = str(row.get(column, "")).replace("P", "").replace(",", "").strip()
            try:
                numeric = float(value)
            except ValueError:
                continue
            remarks_column = f"{column} - Remarks"
            is_provisional = "P" in str(row.get(remarks_column, "")).upper()
            if sector == "office":
                metric = "rental_index"
            else:
                metric = "rental_index" if column.strip().lower() == "rents" else "price_index"
            rows.append(
                {
                    "date": date,
                    "segment": column.strip().lower().replace(" ", "_"),
                    "metric": metric,
                    "value": numeric,
                    "is_provisional": is_provisional,
                    "source_agency": "Rating and Valuation Department",
                }
            )
    result = pd.DataFrame(rows, columns=columns)
    if not result.empty:
        if result.duplicated(subset=["date", "segment", "metric"]).any():
            return pd.DataFrame(columns=columns)
        result = result.sort_values(["metric", "segment", "date"]).reset_index(drop=True)
    return result


def _fetch_rvd_commercial_index(url: str, source_name: str, sector: str) -> pd.DataFrame:
    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()
    raw_path = save_raw_snapshot(source_name, response.text, file_ext="csv", source_url=url)
    result = _parse_rvd_commercial_csv(response.text, sector)
    result.attrs.update(raw_snapshot=str(raw_path), source_url=url)
    return result


def fetch_rvd_office_rental_index() -> pd.DataFrame:
    return _fetch_rvd_commercial_index(RVD_OFFICE_RENTAL_2_3M_URL, "rvd_office_rental_2_3M", "office")


def fetch_rvd_retail_rental_index() -> pd.DataFrame:
    return _fetch_rvd_commercial_index(RVD_RETAIL_3_2M_URL, "rvd_retail_3_2M", "retail")

def run_rvd_ingestion() -> Tuple[pd.DataFrame, pd.DataFrame]:
    return fetch_rvd_price_index(), fetch_rvd_rental_index()
