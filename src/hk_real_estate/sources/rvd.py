import io
import requests
import pandas as pd
from typing import Tuple

from ..config import RVD_PRICE_1_4M_URL, RVD_RENTAL_1_3M_URL, DEFAULT_HEADERS
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

def run_rvd_ingestion() -> Tuple[pd.DataFrame, pd.DataFrame]:
    return fetch_rvd_price_index(), fetch_rvd_rental_index()
