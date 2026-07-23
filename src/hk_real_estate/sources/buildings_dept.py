import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import pandas as pd
from typing import Dict, Any

from ..config import BD_MONTHLY_DIGESTS_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot

def fetch_buildings_dept_digests() -> pd.DataFrame:
    """
    Fetch Buildings Department monthly digests directory and parse release links.
    """
    response = requests.get(BD_MONTHLY_DIGESTS_URL, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()

    raw_path = save_raw_snapshot("bd_monthly_digests_directory", response.text, file_ext="html", source_url=BD_MONTHLY_DIGESTS_URL)

    soup = BeautifulSoup(response.text, 'html.parser')
    links = soup.find_all('a', href=True)

    records = []
    for a in links:
        href = a['href']
        text = a.get_text(strip=True)
        if re.search(r'20\d{2}\d{2}\.html', href):
            match = re.search(r'(20\d{2})(0[1-9]|1[0-2])', href)
            if match:
                year_str, month_str = match.groups()
                records.append({
                    'date': f"{year_str}-{month_str}-01",
                    'digest_title': text or f"Monthly Digest {year_str}-{month_str}",
                    'digest_url': urljoin(BD_MONTHLY_DIGESTS_URL, href),
                    'source_agency': 'Hong Kong Buildings Department'
                })

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.drop_duplicates(subset=['date']).sort_values('date', ascending=False).reset_index(drop=True)
    df.attrs.update(raw_snapshot=str(raw_path), source_url=BD_MONTHLY_DIGESTS_URL)
    return df
