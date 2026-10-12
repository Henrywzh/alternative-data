"""Official annual release calendar, separate from observation/capture dates."""
from io import StringIO
import re

from bs4 import BeautifulSoup
import pandas as pd

from .press import CALENDAR


def release_calendar(fetch, captured):
    year = pd.Timestamp(captured).year
    url = CALENDAR
    if year != 2026:
        index = "https://www.stats.gov.cn/xw/tjxw/tzgg/"
        page = BeautifulSoup(fetch.get(index).content, "html.parser")
        from urllib.parse import urljoin
        links = [urljoin(index, a["href"]) for a in page.select("a[href]") if str(year) in a.get_text() and "发布日程" in a.get_text()]
        if not links:
            raise ValueError(f"No official {year} release calendar discovered")
        url = links[0]
    response = fetch.get(url)
    response.encoding = "utf-8"
    tables = pd.read_html(StringIO(response.text))
    rows = []
    for table in tables:
        if table.shape[1] != 14:
            continue
        for _, record in table.iterrows():
            name = str(record.iloc[1])
            family = "pmi" if "采购经理" in name else "prices" if "居民消费价格指数月度" in name else "profits" if "工业企业利润" in name else "activity" if name == "国民经济运行情况" else None
            if not family:
                continue
            for month in range(1, 13):
                for day_text in re.findall(r"(\d{1,2})/", str(record.iloc[month + 1])):
                    day = int(day_text)
                    release = pd.Timestamp(year=year, month=month, day=day)
                    reference = release.to_period("M") if family == "pmi" and day > 15 else release.to_period("M") - 1
                    rows.append(dict(family=family, reference_date=reference.to_timestamp().strftime("%Y-%m-%d"), release_date=release.strftime("%Y-%m-%d"), source_url=url))
    if not rows:
        raise ValueError("Unrecognized official release calendar")
    return rows


def family_for(metric):
    if metric.startswith("pmi") or metric in ["services_pmi", "construction_pmi", "nonmanufacturing_pmi", "orders_inventory"]:
        return "pmi"
    if metric in ["cpi_yoy", "core_cpi_yoy", "cpi_mom", "ppi_yoy"]:
        return "prices"
    if metric.startswith("industrial_profit"):
        return "profits"
    if metric.startswith("property_") or "investment" in metric or metric in ["industrial_yoy", "retail_yoy", "retail", "fai_yoy", "gdp", "gdp_yoy", "production_consumption"]:
        return "activity"
    return None
