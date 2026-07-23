import re
import requests
from bs4 import BeautifulSoup
import pandas as pd
from typing import Dict, Any

from ..config import HSE28_NEW_PROPERTIES_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot

def fetch_28hse_new_projects() -> pd.DataFrame:
    response = requests.get(HSE28_NEW_PROPERTIES_URL, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()

    raw_path = save_raw_snapshot("hse28_new_projects", response.text, file_ext="html", source_url=HSE28_NEW_PROPERTIES_URL)

    soup = BeautifulSoup(response.text, 'html.parser')
    cards = soup.find_all('div', class_=re.compile(r'item\b|property_item'))

    records = []
    for c in cards:
        title_a = c.find('a', class_=re.compile(r'title|header'))
        if not title_a:
            title_a = c.find('a', href=re.compile(r'/new-properties/'))

        if title_a:
            title = title_a.get_text(strip=True)
            if title and title != "關閉" and len(title) > 1:
                district_elem = c.find(['span', 'div'], class_=re.compile(r'district|location|area'))
                district = district_elem.get_text(strip=True) if district_elem else None

                text = c.get_text()
                units_match = re.search(r'(\d+)\s*(伙|個單位|個|夥|units)', text, re.IGNORECASE)
                units = int(units_match.group(1)) if units_match else None

                records.append({
                    'project_name': title,
                    'location_district': district,
                    'estimated_total_units': units,
                    'source_platform': '28Hse'
                })

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.drop_duplicates(subset=['project_name']).reset_index(drop=True)
    df.attrs['raw_snapshot'] = str(raw_path)
    df.attrs['source_url'] = HSE28_NEW_PROPERTIES_URL
    return df
