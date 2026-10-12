"""Official PBC annual Excel histories and comparable M1 back series."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO, StringIO
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import pandas as pd

from .normalize import clean, observation
from .sources import Fetcher

PBC_ROOT = "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html"
M1_URL = "https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/2026011509294440745/index.html"


def pbc_period(value) -> str | None:
    # Preserve the original string: float(2026.10) loses October's zero.
    match = re.fullmatch(r"\s*(\d{4})[.年/-](\d{1,2})(?:月)?\s*", str(value))
    if not match or not 1 <= int(match[2]) <= 12:
        return None
    return f"{match[1]}-{int(match[2]):02}-01"


def ordered_months(values):
    """Excel numeric 2026.10 becomes 2026.1: a full Jan-Dec header disambiguates."""
    dates = {index: pbc_period(value) for index, value in enumerate(values) if pbc_period(value)}
    if len(dates) == 12 and len({date[:4] for date in dates.values()}) == 1 and next(iter(dates.values()))[5:7] == "01":
        year = next(iter(dates.values()))[:4]
        return {index: f"{year}-{month:02}-01" for month, index in enumerate(dates, 1)}
    return dates


def parse_afre(table: pd.DataFrame, url: str, captured: str) -> pd.DataFrame:
    rows = []
    title = " ".join(str(x) for x in table.iloc[:4].to_numpy().ravel())
    if "增量" in title:
        headers = next((i for i in range(min(14, len(table))) if any("社会融资规模增量" == str(x).strip() for x in table.iloc[i])), None)
        if headers is None:
            raise ValueError("Unrecognized AFRE flow header")
        mapping = {"社会融资规模增量": "tsf_flow", "人民币贷款": "tsf_rmb_loans", "政府债券": "tsf_government"}
        # Stop at the first table boundary after the monthly rows. Some annual
        # workbooks append revised tables and a percentage-composition table;
        # reading those with the primary amount header corrupts the history.
        indexes = []
        for index in range(headers + 1, len(table)):
            if pbc_period(table.iloc[index, 0]):
                indexes.append(index)
            elif indexes:
                break
        primary = table.iloc[indexes]
        date_mapping = ordered_months(primary.iloc[:, 0].tolist())
        for offset, (_, item) in enumerate(primary.iterrows()):
            date = date_mapping.get(offset)
            if not date:
                continue
            for col, label in enumerate(table.iloc[headers]):
                metric = mapping.get(str(label).strip())
                if metric:
                    row = observation(metric, date, item.iloc[col], "People's Bank of China", url, captured, scale=.1)
                    if row:
                        rows.append(row)
    elif "存量" in title:
        date_row = next((i for i in range(min(10, len(table))) if sum(pbc_period(x) is not None for x in table.iloc[i]) >= 1), None)
        total_row = next((i for i in range(len(table)) if str(table.iloc[i, 0]).strip() == "社会融资规模存量"), None)
        if date_row is None or total_row is None:
            raise ValueError("Unrecognized AFRE stock layout")
        scale = 1000 if "万亿元" in title else .1
        for col, date in ordered_months(table.iloc[date_row].tolist()).items():
            if not date:
                continue
            for metric, offset, factor in [("tsf_stock", 0, scale), ("tsf_stock_yoy", 1, 1)]:
                if col + offset >= table.shape[1]:
                    continue
                row = observation(metric, date, table.iloc[total_row, col + offset], "People's Bank of China", url, captured, scale=factor)
                if row:
                    rows.append(row)
    else:
        raise ValueError("Not an AFRE table")
    return clean(rows)


def loan_balances(fetch: Fetcher, captured: str, *, backfill=False) -> pd.DataFrame:
    soup = BeautifulSoup(fetch.get(PBC_ROOT).content, "html.parser")
    years = {}
    for anchor in soup.select("a[href]"):
        match = re.search(r"(20\d{2})年统计数据", anchor.get_text())
        if match and int(match[1]) >= 2015 and (backfill or int(match[1]) >= pd.Timestamp(captured).year - 1):
            years[int(match[1])] = urljoin(PBC_ROOT, anchor["href"])
    def year_rows(year_url):
        page = BeautifulSoup(fetch.get(year_url).content, "html.parser")
        links = [urljoin(year_url, a["href"]) for a in page.select("a[href]") if "金融机构信贷收支统计" in a.get_text()]
        if not links:
            return []
        page_url = links[0]
        page = BeautifulSoup(fetch.get(page_url).content, "html.parser")
        urls = [urljoin(page_url, a["href"]) for a in page.select("a[href]") if re.search(r"\.xlsx?$", a["href"], re.I)
                and a.parent.parent.get_text(" ", strip=True).startswith("金融机构人民币信贷收支表")]
        if not urls:
            return []
        url = sorted(set(urls), reverse=True)[0]
        table = pd.read_excel(BytesIO(fetch.get(url).content), header=None, dtype=object)
        date_row = next((i for i in range(min(10, len(table))) if sum(pbc_period(x) is not None for x in table.iloc[i]) >= 1), None)
        if date_row is None:
            return []
        rows = []
        for _, item in table.iterrows():
            name = str(item.iloc[0])
            metric = "household_loan_balance" if "住户贷款" in name else "corporate_loan_balance" if "企（事）业单位贷款" in name or "企(事)业单位贷款" in name else None
            if not metric:
                continue
            for col, date in ordered_months(table.iloc[date_row].tolist()).items():
                row = observation(metric, date, item.iloc[col], "People's Bank of China (RMB credit funds)", url, captured, scale=.1)
                if row:
                    rows.append(row)
        return rows
    rows = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed([pool.submit(year_rows, url) for url in years.values()]):
            try:
                rows.extend(future.result())
            except Exception:
                continue  # failed URLs recorded by Fetcher, no fabricated rows
    if not rows:
        raise ValueError("No official borrower loan balance history")
    return clean(rows)


def afre(fetch: Fetcher, captured: str, *, backfill: bool) -> pd.DataFrame:
    soup = BeautifulSoup(fetch.get(PBC_ROOT).content, "html.parser")
    current_year = pd.Timestamp(captured).year
    years = {}
    for anchor in soup.select("a[href]"):
        match = re.search(r"(20\d{2})年统计数据", anchor.get_text())
        if match and (backfill or int(match[1]) == current_year) and int(match[1]) >= 2015:
            years[int(match[1])] = urljoin(PBC_ROOT, anchor["href"])
    if not years:
        raise ValueError("PBC yearly catalog is empty")

    def fetch_year(year_url):
        page = BeautifulSoup(fetch.get(year_url).content, "html.parser")
        links = [urljoin(year_url, a["href"]) for a in page.select("a[href]") if "社会融资规模" in a.get_text()]
        if not links:
            return []
        page_url = links[0]
        page = BeautifulSoup(fetch.get(page_url).content, "html.parser")
        candidates = {"flow": [], "stock": []}
        for anchor in page.select("a[href]"):
            if not re.search(r"\.xlsx?(?:\?|$)", anchor["href"], re.I):
                continue
            context = anchor.parent.parent.get_text(" ", strip=True)
            kind = "flow" if "增量" in context else "stock" if "存量" in context else None
            if kind:
                candidates[kind].append(urljoin(page_url, anchor["href"]))
        rows = []
        for urls in candidates.values():
            if not urls:
                continue
            url = sorted(set(urls), reverse=True)[0]
            table = pd.read_excel(BytesIO(fetch.get(url).content), header=None, dtype=object)
            rows.extend(parse_afre(table, url, captured).to_dict("records"))
        return rows

    rows = []
    errors = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed([pool.submit(fetch_year, url) for _, url in sorted(years.items())]):
            try:
                rows.extend(future.result())
            except Exception as error:
                errors.append(type(error).__name__)
    if not rows:
        raise ValueError(f"PBC AFRE empty: {errors}")
    return clean(rows)


def comparable_m1(fetch: Fetcher, captured: str) -> pd.DataFrame:
    response = fetch.get(M1_URL)
    response.encoding = "utf-8"
    rows = []
    for table in pd.read_html(StringIO(response.text)):
        for i in range(len(table) - 2):
            if "同比增速" not in str(table.iloc[i + 2, 0]):
                continue
            for col, value in enumerate(table.iloc[i]):
                date = pbc_period(value)
                if not date or not date.startswith("2024-"):
                    continue
                number = str(table.iloc[i + 2, col]).replace("%", "")
                row = observation("m1_yoy", date, number, "People's Bank of China (revised M1 definition)", M1_URL, captured,
                                  definition="2024 comparable back series under January 2025 M1 definition")
                if row:
                    rows.append(row)
    if not rows:
        raise ValueError("Missing official comparable M1 back series")
    return clean(rows)
