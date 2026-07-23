import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import pandas as pd
from typing import Dict, Any

from ..config import SRPE_OPIP_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot

def fetch_srpe_project_documents() -> pd.DataFrame:
    """
    Fetch SRPE OPIP portal and parse available project document search modules.
    """
    response = requests.get(SRPE_OPIP_URL, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()

    raw_path = save_raw_snapshot("srpe_opip_landing", response.text, file_ext="html", source_url=SRPE_OPIP_URL)

    soup = BeautifulSoup(response.text, 'html.parser')
    links = soup.find_all('a', href=True)

    records = []
    for a in links:
        href = a['href']
        text = a.get_text(strip=True)
        if any(action in href for action in ['.do', 'search', 'Brochure', 'Pricelist', 'Transaction']):
            records.append({
                'action_name': text,
                'action_endpoint': urljoin(SRPE_OPIP_URL, href),
                'source_platform': 'SRPE'
            })

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.drop_duplicates(subset=['action_endpoint']).reset_index(drop=True)
    df.attrs.update(raw_snapshot=str(raw_path), source_url=SRPE_OPIP_URL)
    return df
