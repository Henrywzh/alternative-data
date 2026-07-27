import re
import json
import requests
from bs4 import BeautifulSoup
import pandas as pd
from typing import Dict, Any

from ..config import LANDREG_MONTHLY_JSON_BASE, LANDREG_MONTHLY_URL, LANDREG_PRESS_RELEASES_URL, DEFAULT_HEADERS
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


def _number(value: object) -> float | None:
    if value is None:
        return None
    text = re.sub(r"[^0-9.\-]", "", str(value))
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _month_date(item: dict) -> str | None:
    try:
        return f"{int(item['Year']):04d}-{int(item['Month']):02d}-01"
    except (KeyError, TypeError, ValueError):
        return None


def _clean_t6_region(description: str) -> str | None:
    """Clean a t6 region description into a plain district name.

    Real t6 `Description` values look like "Number of Hong Kong transactions"
    or, for the grand-total row, "Total Number of transactions" -- the naive
    ``.replace(" transactions", "")`` alone left "Number of " on every row
    (e.g. "Number of Hong Kong") and turned the grand total into a
    district-looking "Total Number of". Strip both prefixes; map the total
    row to an explicit, non-district sentinel instead.
    """
    cleaned = description.replace(" transactions", "").replace("Number of ", "").strip()
    if cleaned == "Total" or description.strip().lower().startswith("total number of"):
        return "All regions"
    return cleaned or None


def fetch_landreg_monthly_statistics() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch the public monthly JSON tables behind Land Registry's page.

    The site publishes the tables as first-party JSON under ``/json``.  This
    is deliberately a light long-form parse: descriptions are kept verbatim so
    the schema does not pretend to have a stable semantic taxonomy yet.
    """
    page = requests.get(LANDREG_MONTHLY_URL, headers=DEFAULT_HEADERS, timeout=30)
    page.raise_for_status()
    tables: dict[str, object] = {}
    for table_name in ("t1", "t2", "t3", "t6"):
        response = requests.get(
            f"{LANDREG_MONTHLY_JSON_BASE}/{table_name}.json",
            headers=DEFAULT_HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        tables[table_name] = response.json()

    raw_path = save_raw_snapshot(
        "landreg_monthly_statistics",
        json.dumps({"page_html": page.text, "tables": tables}, ensure_ascii=False),
        file_ext="json",
        source_url=LANDREG_MONTHLY_URL,
    )

    facts: list[dict] = []
    for table_name in ("t1", "t2", "t6"):
        for item_index, item in enumerate(tables.get(table_name, [])):
            if not isinstance(item, dict):
                continue
            period = _month_date(item)
            description = item.get("Description")
            if not period or not description:
                continue
            facts.append(
                {
                    "source_record_id": f"{table_name}-{item_index}",
                    "date": period,
                    "table_id": table_name,
                    "statistic_name": str(description),
                    "units": _number(item.get("Units")),
                    "consideration_million": _number(item.get("Consideration (nearest $ million)")),
                    "region": _clean_t6_region(str(description)) if table_name == "t6" else None,
                    "source_agency": "Hong Kong Land Registry",
                    "basis": "registration_receipt_month",
                }
            )

    series: list[dict] = []
    for item in tables.get("t3", []):
        if not isinstance(item, dict):
            continue
        period = _month_date(item)
        if not period:
            continue
        series.append(
            {
                "date": period,
                "all_building_units_asp": _number(item.get("Total Number of Urban & New Territories deeds received for registration (ASP Building Units)")),
                "residential_units_asp": _number(item.get("Number of ASP for Residential Building Units")),
                "all_asp_12m_moving_average": _number(item.get("12-month moving average for all ASP")),
                "source_agency": "Hong Kong Land Registry",
                "basis": "registration_receipt_month",
            }
        )

    facts_df = pd.DataFrame(facts)
    series_df = pd.DataFrame(series)
    for frame in (facts_df, series_df):
        frame.attrs.update(raw_snapshot=str(raw_path), source_url=LANDREG_MONTHLY_URL)
    return facts_df, series_df
