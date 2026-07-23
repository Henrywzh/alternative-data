import re
import os
import time
import requests
from bs4 import BeautifulSoup
import pandas as pd
from typing import Dict, Any

from ..config import HSE28_ESTATE_INDEX_URL, HSE28_NEW_PROPERTIES_URL, DEFAULT_HEADERS
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


def _parse_hkd_amount(value: str) -> float | None:
    value = value.replace(",", "").replace("$", "").strip()
    match = re.search(r"([\d.]+)\s*(億|萬元?)?", value)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2) or ""
    if unit == "億":
        return amount * 100_000_000
    if unit in {"萬", "萬元"}:
        return amount * 10_000
    return amount


def _parse_28hse_transaction_table(html: str, source_url: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for row in soup.select("#latest_3months_or_landreg_result tr[unit-id]"):
        link = row.select_one("a[href]")
        if not link:
            continue
        labels = [item.get_text(" ", strip=True) for item in row.select(".labels .label")]
        date_value = next((item for item in labels if re.fullmatch(r"\d{4}-\d{2}-\d{2}", item)), None)
        transaction_kind = next((item for item in labels if "成交" in item), None)
        area_text = row.select_one("td:nth-of-type(2)").get_text(" ", strip=True) if row.select_one("td:nth-of-type(2)") else ""
        price_node = row.select_one(".transaction_detail_price_buy, .transaction_detail_price_rent")
        unit_price_node = row.select_one(".unit_price")
        header = row.select_one(".header")
        header_text = header.get_text(" ", strip=True) if header else ""
        estate_name = header_text.split("|", 1)[0].strip() if "|" in header_text else None
        deal_match = re.search(r"deal-(\d+)", link.get("href", ""), re.I)
        source_record_id = row.get("unit-id") or (deal_match.group(1) if deal_match else link.get("href"))
        records.append(
            {
                "source_record_id": source_record_id,
                "estate_name": estate_name,
                "property_text": link.get("title") or link.get_text(" ", strip=True),
                "date": date_value,
                "transaction_date": date_value,
                "transaction_kind": transaction_kind,
                "room_type": next((item for item in labels if "房" in item), None),
                "saleable_area_sqft": _parse_hkd_amount(area_text.replace("實", "").replace("呎", "")),
                "price_hkd": _parse_hkd_amount(price_node.get_text(" ", strip=True)) if price_node else None,
                "unit_price_hkd_sqft": _parse_hkd_amount(unit_price_node.get_text(" ", strip=True)) if unit_price_node else None,
                "source_url": link.get("href"),
                "source_platform": "28Hse",
                "source_page": source_url,
            }
        )
    return pd.DataFrame(records)


def fetch_28hse_transaction_pilot(*, max_estates: int | None = None) -> pd.DataFrame:
    """Fetch recent transaction rows for the first page of 28Hse estates.

    This is intentionally a bounded pilot, not a crawler.  The index page
    currently exposes popular estates as detail links; each detail page has a
    server-rendered recent transaction table.
    """
    max_estates = max_estates or int(os.getenv("HK_REALESTATE_HSE28_MAX_ESTATES", "20"))
    index = requests.get(HSE28_ESTATE_INDEX_URL, headers=DEFAULT_HEADERS, timeout=30)
    index.raise_for_status()
    index_raw = save_raw_snapshot("hse28_estate_index", index.text, file_ext="html", source_url=HSE28_ESTATE_INDEX_URL)
    soup = BeautifulSoup(index.text, "html.parser")
    urls = []
    for link in soup.select('a[href*="/estate/detail/"]'):
        href = link.get("href")
        if href and href not in urls:
            urls.append(href)
        if len(urls) >= max_estates:
            break

    frames = []
    for url in urls:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
        response.raise_for_status()
        save_raw_snapshot("hse28_estate_detail", response.text, file_ext="html", source_url=url)
        frames.append(_parse_28hse_transaction_table(response.text, url))
        time.sleep(float(os.getenv("HK_REALESTATE_HSE28_DELAY", "0.15")))

    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not result.empty:
        result = result.drop_duplicates(subset=["source_record_id", "source_page"]).reset_index(drop=True)
    result.attrs.update(raw_snapshot=str(index_raw), source_url=HSE28_ESTATE_INDEX_URL)
    return result
