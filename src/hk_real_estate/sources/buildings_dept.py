import re
import json
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import pandas as pd
from typing import Dict, Any

from ..config import BD_MONTHLY_DIGESTS_URL, BD_MONTHLY_DIGEST_XLS_BASE, DEFAULT_HEADERS
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


def _cell_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _period_from_row(
    values: list[str], current_year: str | None, current_period: str | None
) -> tuple[str | None, str | None, str | None, bool]:
    # Date labels are in the first columns.  Searching every numeric cell can
    # mistake a building-cost value such as 2009 for the row's year.
    text = " ".join(value for value in values[:3] if value)
    year_match = re.search(r"\b(20\d{2})\b", text)
    month_match = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", text, re.I)
    # A row that states a year but no month is the table's own annual-total
    # row (e.g. a bare "2024" row above that year's Jan-Dec breakdown) --
    # distinct from a monthly row, which always carries a month even on the
    # row that also happens to restate the year (e.g. "2025: " | "Jan").
    is_annual_row = bool(year_match) and not month_match
    if year_match:
        current_year = year_match.group(1)
    if month_match and current_year:
        month_number = {
            "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
            "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
            "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
        }[month_match.group(1).title()]
        current_period = f"{current_year}-{month_number}-01"
    elif year_match:
        # Stamp the annual-total row on Dec 31 rather than Jan 1 so it can
        # never collide with that same year's real January row (both used
        # to resolve to "YYYY-01-01", producing duplicate dates within the
        # same table -- confirmed on tables 1.1, 1.3, 1.4, and 1.7).
        current_period = f"{current_year}-12-31"
    return current_year, current_period, text, is_annual_row


def _read_xls(content: bytes) -> pd.DataFrame:
    """Read legacy XLS with xlrd when available, soffice otherwise."""
    try:
        return pd.read_excel(BytesIO(content), header=None)
    except ImportError:
        soffice = shutil.which("soffice")
        if not soffice:
            raise
        with tempfile.TemporaryDirectory(prefix="hk_bd_xls_") as temp_dir:
            source = Path(temp_dir) / "digest.xls"
            source.write_bytes(content)
            subprocess.run(
                [soffice, "--headless", "--convert-to", "csv", "--outdir", temp_dir, str(source)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return pd.read_csv(Path(temp_dir) / "digest.csv", header=None)


ALL_MDXX_TABLES = [
    "Md11.xls", "Md12.xls", "Md13.xls", "Md14.xls", "Md15.xls", "Md16.xls", "Md17.xls",
    "Md21.xls", "Md22.xls", "Md23.xls", "Md24.xls", "Md25.xls",
    "Md31.xls", "Md41.xls",
    "Md51.xls", "Md52.xls", "Md53.xls", "Md54.xls", "Md55.xls", "Md56.xls",
]


def fetch_buildings_dept_monthly_stats() -> pd.DataFrame:
    """Fetch all 20 public Mdxx Excel tables, save raw snapshots, and extract section-1 rows."""
    index = requests.get(BD_MONTHLY_DIGESTS_URL, headers=DEFAULT_HEADERS, timeout=30)
    index.raise_for_status()
    links = BeautifulSoup(index.text, "html.parser").find_all("a", href=True)
    records: list[dict] = []
    raw_paths: list[str] = []
    found_hrefs = {a["href"].split("/")[-1] for a in links if re.search(r"Md\d+\.xls$", a["href"], re.I)}
    available = [f for f in ALL_MDXX_TABLES if f in found_hrefs] if found_hrefs else ALL_MDXX_TABLES

    for filename in sorted(available):
        url = f"{BD_MONTHLY_DIGEST_XLS_BASE}/{filename}"
        try:
            response = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
            if response.status_code != 200:
                continue
            raw_path = save_raw_snapshot(f"bd_{filename.replace('.xls', '')}", response.content, file_ext="xls", source_url=url)
            raw_paths.append(str(raw_path))

            # Parse Section 1 summary tables (Md11 - Md17) into monthly stats frame
            if not filename.startswith("Md1"):
                continue

            table_id = f"1.{int(filename[2:4]) - 10}"
            frame = _read_xls(response.content)
            current_year = None
            current_period = None
            for _, row in frame.iterrows():
                values = [_cell_text(value) for value in row.tolist()]
                nonempty = [value for value in values if value]
                if not nonempty:
                    continue
                current_year, current_period, _, is_annual_row = _period_from_row(values, current_year, current_period)
                if not current_period:
                    continue
                numeric = []
                for i, value in enumerate(values):
                    if is_annual_row and i == 0:
                        continue
                    candidate = value.replace(",", "")
                    if candidate and re.fullmatch(r"-?\d+(?:\.\d+)?", candidate):
                        numeric.append(float(candidate))
                if not numeric:
                    continue
                label = " | ".join(value for value in nonempty if not re.fullmatch(r"-?[\d,.]+", value.replace(",", "")))
                records.append({
                    "date": current_period,
                    "table_id": table_id,
                    "row_label": label,
                    "numeric_values": json.dumps(numeric),
                    "period_type": "annual" if is_annual_row else "monthly",
                    "source_agency": "Hong Kong Buildings Department",
                    "source_file": filename,
                })
        except Exception as e:
            print(f"Warning: Failed to fetch/parse BD Mdxx table {filename}: {e}")

    result = pd.DataFrame(records)
    result.attrs.update(raw_snapshot=json.dumps(raw_paths), source_url=BD_MONTHLY_DIGESTS_URL)
    return result
