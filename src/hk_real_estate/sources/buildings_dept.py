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


def _period_from_row(values: list[str], current_year: str | None, current_period: str | None) -> tuple[str | None, str | None, str | None]:
    # Date labels are in the first columns.  Searching every numeric cell can
    # mistake a building-cost value such as 2009 for the row's year.
    text = " ".join(value for value in values[:3] if value)
    year_match = re.search(r"\b(20\d{2})\b", text)
    month_match = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", text, re.I)
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
        current_period = f"{current_year}-01-01"
    return current_year, current_period, text


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


def fetch_buildings_dept_monthly_stats() -> pd.DataFrame:
    """Fetch public section-1 Excel tables and extract scratch rows."""
    index = requests.get(BD_MONTHLY_DIGESTS_URL, headers=DEFAULT_HEADERS, timeout=30)
    index.raise_for_status()
    links = BeautifulSoup(index.text, "html.parser").find_all("a", href=True)
    records: list[dict] = []
    raw_paths: list[str] = []
    available = {a["href"].split("/")[-1] for a in links if re.search(r"Md1[1-7]\.xls$", a["href"], re.I)}
    if not available:
        available = {f"Md1{i}.xls" for i in range(1, 8)}
    for filename in sorted(available):
        url = f"{BD_MONTHLY_DIGEST_XLS_BASE}/{filename}"
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
        response.raise_for_status()
        raw_path = save_raw_snapshot("buildings_dept_monthly", response.content, file_ext="xls", source_url=url)
        raw_paths.append(str(raw_path))
        table_id = f"1.{int(filename[2:4]) - 10}"
        frame = _read_xls(response.content)
        current_year = None
        current_period = None
        for _, row in frame.iterrows():
            values = [_cell_text(value) for value in row.tolist()]
            nonempty = [value for value in values if value]
            if not nonempty:
                continue
            current_year, current_period, _ = _period_from_row(values, current_year, current_period)
            if not current_period:
                continue
            numeric = []
            for value in values:
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
                "source_agency": "Hong Kong Buildings Department",
                "source_file": filename,
            })
    result = pd.DataFrame(records)
    result.attrs.update(raw_snapshot=json.dumps(raw_paths), source_url=BD_MONTHLY_DIGESTS_URL)
    return result
