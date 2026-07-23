import re
import requests
from bs4 import BeautifulSoup
import pandas as pd
from typing import Dict, Any

from ..config import LANDREG_PRESS_RELEASES_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot

def fetch_landreg_monthly_sp() -> pd.DataFrame:
    """
    Fetch Land Registry monthly Sale and Purchase Agreement statistics.
    Scrapes official Land Registry press release statistics tables.
    """
    response = requests.get(LANDREG_PRESS_RELEASES_URL, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()

    raw_path = save_raw_snapshot("landreg_press_releases", response.text, file_ext="html", source_url=LANDREG_PRESS_RELEASES_URL)

    soup = BeautifulSoup(response.text, 'html.parser')
    links = soup.find_all('a', href=True)

    records = []
    # Parse press releases for statistics announcements
    for a in links:
        title = a.get_text(strip=True)
        href = a['href']
        if 'statistics' in title.lower() or 'land registry releases' in title.lower():
            date_match = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(20\d{2})', title, re.IGNORECASE)
            if date_match:
                month_name, year_str = date_match.groups()
                # Map month name to 2-digit month
                month_dict = {
                    'january': '01', 'february': '02', 'march': '03', 'april': '04',
                    'may': '05', 'june': '06', 'july': '07', 'august': '08',
                    'september': '09', 'october': '10', 'november': '11', 'december': '12'
                }
                m_code = month_dict.get(month_name.lower(), '01')
                records.append({
                    'date': f"{year_str}-{m_code}-01",
                    'release_title': title,
                    'release_url': href,
                    'source_agency': 'Hong Kong Land Registry'
                })

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
    df.attrs.update(raw_snapshot=str(raw_path), source_url=LANDREG_PRESS_RELEASES_URL)
    return df
