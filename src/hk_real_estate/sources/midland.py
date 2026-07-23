import json
import requests
from bs4 import BeautifulSoup
import pandas as pd
from typing import Dict, Any, Tuple

from ..config import MIDLAND_MARKET_INSIGHT_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot

def fetch_midland_payload() -> Dict[str, Any]:
    response = requests.get(MIDLAND_MARKET_INSIGHT_URL, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()

    raw_path = save_raw_snapshot("midland_market_insight", response.text, file_ext="html", source_url=MIDLAND_MARKET_INSIGHT_URL)

    soup = BeautifulSoup(response.text, 'html.parser')
    script_tag = soup.find('script', id='__NEXT_DATA__')
    if not script_tag or not script_tag.string:
        raise ValueError("Could not find __NEXT_DATA__ script tag on Midland Market Insight page.")

    data = json.loads(script_tag.string)
    page_props = data.get('props', {}).get('pageProps', {})
    # The raw HTML remains associated with the parsed outputs in the pipeline.
    page_props['_raw_snapshot'] = str(raw_path)
    page_props['_source_url'] = MIDLAND_MARKET_INSIGHT_URL
    return page_props

def parse_midland_mhpi(page_props: Dict[str, Any]) -> pd.DataFrame:
    raw_list = page_props.get('mrIndexWeekly', [])
    records = []
    for item in raw_list:
        raw_date = item.get('date', '')
        iso_date = raw_date.split('T')[0] if 'T' in raw_date else raw_date
        records.append({
            'date': iso_date,
            'mhpi_overall': item.get('mr_index'),
            'mhpi_hk_island': item.get('mr_index_hk'),
            'mhpi_kowloon': item.get('mr_index_kln'),
            'mhpi_new_territories': item.get('mr_index_nt'),
            'weekly_change_pct_overall': item.get('weekly_perc'),
            'source_agency': 'Midland Realty'
        })
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values('date').reset_index(drop=True)
    return df

def parse_midland_confidence(page_props: Dict[str, Any]) -> pd.DataFrame:
    raw_list = page_props.get('confidenceIndex', [])
    records = []
    for item in raw_list:
        raw_date = item.get('date', '')
        iso_date = raw_date.split('T')[0] if 'T' in raw_date else raw_date
        records.append({
            'date': iso_date,
            'confidence_index': item.get('confidence_index'),
            'confidence_avg_index': item.get('confidence_avg_index'),
            'weekly_change_pct': item.get('weekly_perc'),
            'source_agency': 'Midland Realty'
        })
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values('date').reset_index(drop=True)
    return df

def parse_midland_estate_counts(page_props: Dict[str, Any]) -> pd.DataFrame:
    result_obj = page_props.get('estatesTransactionCount', {})
    items = result_obj.get('result', []) if isinstance(result_obj, dict) else []

    records = []
    for item in items:
        estate_id = item.get('id')
        estate_name = item.get('name')
        region_name = item.get('region', {}).get('name') if isinstance(item.get('region'), dict) else None
        district_name = item.get('district', {}).get('name') if isinstance(item.get('district'), dict) else None

        market_stat = item.get('market_stat', {})
        tx_count = market_stat.get('tx_count') if isinstance(market_stat, dict) else None
        if tx_count is None and isinstance(market_stat, dict):
            tx_count = market_stat.get('monthly', {}).get('tx_count')

        records.append({
            'estate_id': estate_id,
            'estate_name': estate_name,
            'region_name': region_name,
            'district_name': district_name,
            'transaction_count': tx_count,
            'source_agency': 'Midland Realty'
        })
    return pd.DataFrame(records)

def run_midland_ingestion() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    props = fetch_midland_payload()
    outputs = parse_midland_mhpi(props), parse_midland_confidence(props), parse_midland_estate_counts(props)
    for df in outputs:
        df.attrs.update(raw_snapshot=props.get('_raw_snapshot'), source_url=props.get('_source_url'))
    return outputs
