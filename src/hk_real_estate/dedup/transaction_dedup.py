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
    c_price = ""
    if pd.notna(price_hkd):
        try:
            # Agency payloads alternate between numeric values and display
            # strings such as "$12,500,000".  Rejecting punctuation before
            # parsing silently erased the price from the identity hash.
            c_price = f"{float(str(price_hkd).replace(',', '').replace('$', '').strip()):.0f}"
        except (TypeError, ValueError):
            c_price = ""
    
    key_str = f"{c_estate}|{c_floor}|{c_unit}|{c_date}|{c_price}"
    return hashlib.md5(key_str.encode('utf-8')).hexdigest()

def deduplicate_agency_transactions(transaction_dfs: List[pd.DataFrame]) -> pd.DataFrame:
    """
    Deduplicate transaction feeds across multiple property agencies (28Hse, Midland, Centaline).
    Returns a unified near-real-time transaction activity dataset with cross-agency record IDs.

    As of 2026-07-24 this is genuinely fed by three independent, real,
    per-transaction agency sources (not just 28Hse):
      - ``sources.hse28.fetch_28hse_transaction_pilot`` (server-rendered
        estate detail pages).
      - ``sources.midland_transactions.fetch_midland_transaction_pilot``
        (reverse-engineered ``data.midland.com.hk/info/v1/transactions/
        buildings/<building_id>`` API; needs an anonymous Bearer token
        obtained from any midland.com.hk page visit's ``token`` cookie).
      - ``sources.centaline_transactions.fetch_centaline_transaction_pilot``
        (reverse-engineered ``hk.centanet.com/findproperty/api/
        Transaction/Search`` API; no auth required).
    Ricacorp was investigated in an earlier session and ruled out (no
    scrapable price index or transaction feed). All three wired-in sources
    were verified live against known, real HK developments before being
    added here -- see each source module's docstring for the specific
    verification evidence (real prices, real addresses, byte-identical file
    sizes, etc.). Midland's feed can legitimately come back empty in CI:
    its WAF blocks some data-center IP ranges (see
    ``pipeline.SKIP_MIDLAND_ENV_VAR``), in which case this function still
    dedups whatever sources did succeed rather than failing the whole run.
    """
    if not transaction_dfs:
        return pd.DataFrame()
        
    combined = pd.concat([df for df in transaction_dfs if not df.empty], ignore_index=True)
    if combined.empty:
        return pd.DataFrame()

    dedup_ids = []
    for _, row in combined.iterrows():
        # NOTE: after pd.concat(), every column exists on every row (filled
        # with NaN for sources that don't natively produce it), so a plain
        # ``row.get(key, fallback)`` never falls through -- the key is
        # always "present" (as NaN), so pandas.Series.get returns the NaN,
        # not the fallback. Confirmed directly:
        # ``pd.Series({'floor_level': np.nan, 'room_type': '2Room'}).get('floor_level', 'fallback')``
        # returns ``nan``, not ``'fallback'``. hse28.py never populates
        # floor_level/unit_flat (only room_type), so without an explicit
        # notna check every 28Hse row silently hashed with floor="" and
        # could never cross-match a genuinely identical Centaline/Midland
        # transaction. Same defect shape applied to transaction_date/date.
        floor_level = row.get('floor_level')
        floor = floor_level if pd.notna(floor_level) else row.get('room_type', '')
        transaction_date = row.get('transaction_date')
        transaction_date = transaction_date if pd.notna(transaction_date) else row.get('date', '')
        d_id = generate_dedup_hash(
            estate_name=row.get('estate_name', ''),
            floor=floor,
            unit=row.get('unit_flat', ''),
            transaction_date=transaction_date,
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
