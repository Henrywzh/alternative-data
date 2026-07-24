import hashlib
import re
import pandas as pd
from typing import List, Dict, Any, Optional

def normalize_text_token(val: Any) -> str:
    if pd.isna(val) or val is None:
        return ""
    text = str(val).lower().strip()
    text = re.sub(r'[\s\-_,\.]+', '', text)
    return text

def generate_dedup_hash(estate_name: Any, floor: Any, unit: Any, transaction_date: Any, price_hkd: Any) -> str:
    c_estate = normalize_text_token(estate_name)
    c_floor = normalize_text_token(floor)
    c_unit = normalize_text_token(unit)
    c_date = str(transaction_date).strip() if pd.notna(transaction_date) else ""
    c_price = f"{float(price_hkd):.0f}" if pd.notna(price_hkd) and str(price_hkd).replace('.','').isdigit() else ""
    
    key_str = f"{c_estate}|{c_floor}|{c_unit}|{c_date}|{c_price}"
    return hashlib.md5(key_str.encode('utf-8')).hexdigest()

def deduplicate_agency_transactions(transaction_dfs: List[pd.DataFrame]) -> pd.DataFrame:
    """
    Deduplicate transaction feeds across multiple property agencies (28Hse, Midland, Centaline).
    Returns a unified near-real-time transaction activity dataset with cross-agency record IDs.
    """
    if not transaction_dfs:
        return pd.DataFrame()
        
    combined = pd.concat([df for df in transaction_dfs if not df.empty], ignore_index=True)
    if combined.empty:
        return pd.DataFrame()

    dedup_ids = []
    for _, row in combined.iterrows():
        d_id = generate_dedup_hash(
            estate_name=row.get('estate_name', ''),
            floor=row.get('floor_level', row.get('room_type', '')),
            unit=row.get('unit_flat', ''),
            transaction_date=row.get('transaction_date', row.get('date', '')),
            price_hkd=row.get('price_hkd', '')
        )
        dedup_ids.append(d_id)
        
    combined['dedup_transaction_id'] = dedup_ids
    
    # Group by dedup_transaction_id to merge multi-agency postings
    deduped_records = []
    grouped = combined.groupby('dedup_transaction_id')
    
    for dedup_id, group in grouped:
        first = group.iloc[0]
        agencies = list(group['source_platform'].dropna().unique()) if 'source_platform' in group.columns else []
        record_ids = list(group['source_record_id'].dropna().unique()) if 'source_record_id' in group.columns else []
        
        rec = {
            'dedup_transaction_id': dedup_id,
            'date': first.get('date', first.get('transaction_date')),
            'transaction_date': first.get('transaction_date', first.get('date')),
            'estate_name': first.get('estate_name'),
            'saleable_area_sqft': first.get('saleable_area_sqft'),
            'price_hkd': first.get('price_hkd'),
            'unit_price_hkd_sqft': first.get('unit_price_hkd_sqft'),
            'primary_source_agency': agencies[0] if agencies else 'Property Agency',
            'matched_agency_count': len(agencies),
            'source_agencies': "|".join(agencies),
            'source_record_ids': "|".join([str(r) for r in record_ids]),
        }
        deduped_records.append(rec)
        
    res_df = pd.DataFrame(deduped_records)
    if not res_df.empty:
        res_df = res_df.sort_values('transaction_date', ascending=False).reset_index(drop=True)
    return res_df
