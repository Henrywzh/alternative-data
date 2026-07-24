import json
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import pandas as pd
from typing import Dict, Any

from ..config import SRPE_OPIP_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot

SRPE_API_BASE = "https://www.srpe.gov.hk/api/SrpeWebService"

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

def fetch_srpe_firsthand_sales_digest() -> pd.DataFrame:
    """
    Fetch SRPE first-hand sales digest: statutory price list filings and transaction register snapshots.

    NOTE: the OPIP portal (``SRPE_OPIP_URL``) is a client-rendered Angular SPA.
    Its server returns the same shell ``index.html`` for any path (verified: a
    nonsense path returns HTTP 200 with byte-identical content to a guessed
    ``*.do`` action path), and the actual search routes
    (``searchDevelopment``, ``transactions``, ``arrangements``, ...) are wired
    up client-side in JS rather than exposed as discoverable server routes we
    can call directly. We have not reverse-engineered the SPA's real XHR
    contract yet, so there is no verified statutory search endpoint to parse
    here. Returning fabricated "digest" rows for unverified endpoint guesses
    would misrepresent stub data as real filings, so this honestly returns an
    empty frame (with only the confirmed live connectivity/version check
    persisted to the raw snapshot) until real search endpoints are found.
    """
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    # Confirm the portal is live and capture its reported build/version. This
    # is a real API call, but it is a connectivity check only -- it does not
    # return any sales/transaction/price-list content.
    try:
        session.get(SRPE_OPIP_URL, timeout=10)
        web_ver = session.post(f"{SRPE_API_BASE}/Settings/getWebVersion", json={"language": "E"}, timeout=10)
        web_ver.raise_for_status()
        ver_info = web_ver.json()
    except Exception:
        ver_info = {}

    save_raw_snapshot(
        "srpe_firsthand_sales_digest_connectivity_check",
        json.dumps({"version_check": ver_info}, ensure_ascii=False),
        file_ext="json",
        source_url=SRPE_OPIP_URL,
    )

    # Honest empty result: no verified statutory sales/price-list/transaction
    # endpoint has been identified for this portal yet.
    return pd.DataFrame(columns=["document_category", "endpoint_url", "source_agency"])
