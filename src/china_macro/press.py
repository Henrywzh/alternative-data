"""Official release fallback and infrastructure-investment history."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import pandas as pd

from .normalize import clean, observation

INDEX = "https://www.stats.gov.cn/sj/zxfb/"
CALENDAR = "https://www.stats.gov.cn/xw/tjxw/tzgg/202512/t20251224_1962137.html"
# Source URLs, not hard-coded readings. These original/migrated archive
# releases fill holes beyond the recent index's retained pagination.
HISTORICAL_INVESTMENT_RELEASES = [
    "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1900596.html",
    "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1900656.html",
    "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1900681.html",
    "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1900720.html",
    "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202006/t20200615_1767731.html",
    "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1900782.html",
    "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1900823.html",
    "https://www.stats.gov.cn/sj/sjjd/202302/t20230202_1896394.html",
    "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1900872.html",
    "https://www.stats.gov.cn/sj/sjjd/202302/t20230202_1896420.html",
    "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1900934.html",
    "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202101/t20210118_1812460.html",
    "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202103/t20210315_1814763.html",
    "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901048.html",
    "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901100.html",
    "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901127.html",
    "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901156.html",
    "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901192.html",
    "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901219.html",
    "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202207/t20220715_1886446.html",
    "https://www.stats.gov.cn/sj/zxfb/202307/t20230715_1941270.html",
    "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202501/t20250117_1958329.html",
    "https://www.stats.gov.cn/sj/zxfbhjd/202507/t20250715_1960412.html",
    "https://www.stats.gov.cn/sj/zxfb/202601/t20260119_1962326.html",
]


def parse_release(text, url, captured, *, published_at=None):
    text = re.sub(r"\s+", "", text)
    # Reference period comes from the release headline, NOT URL publication month.
    annual = re.match(r"(20\d{2})年全国固定资产投资", text)
    half_year = re.match(r"(20\d{2})年上半年全国固定资产投资", text)
    match = re.search(r"(20\d{2})年(?:1[—–－-])?(\d{1,2})月", text)
    if annual:
        date = f"{annual[1]}-12-01"
    elif half_year:
        date = f"{half_year[1]}-06-01"
    elif match:
        date = f"{match[1]}-{int(match[2]):02}-01"
    else:
        return clean([])
    release = re.search(r"/t(\d{8})_", url)
    released_at = published_at or (pd.to_datetime(release[1]).strftime("%Y-%m-%d") if release else None)
    patterns = {
        "core_cpi_yoy": r"核心CPI[^。；]{0,40}?同比(?:涨幅)?(?:由[^。；]{0,20}?)?(上涨|下降|增长|回升至|回落至)(\d+(?:\.\d+)?)%",
        "infrastructure_investment_yoy": r"基础设施投资[（(]不含电力、热力、燃气及水(?:的)?生产和供应业[）)][^。；]{0,25}?(增长|下降)(\d+(?:\.\d+)?)%",
        "industrial_yoy": r"规模以上工业增加值同比(?:实际)?(增长|下降)(\d+(?:\.\d+)?)%",
    }
    if pd.Timestamp(date).year >= 2026:
        patterns["infrastructure_investment_incl_utilities_yoy"] = r"基础设施投资[（(]口径详见附注1[）)][^。；]{0,25}?(增长|下降)(\d+(?:\.\d+)?)%"
    elif "投资数据" in text[:100]:
        # Pre-2026 NBS investment commentary uses the same ex-utilities series
        # but sometimes abbreviates the name. Never apply to general macro text.
        patterns["infrastructure_investment_yoy"] = r"基础设施投资(?:[（(]不含电力、热力、燃气及水(?:的)?生产和供应业[）)])?(?:同比|比上年)?(增长|下降)(\d+(?:\.\d+)?)%"
    rows = []
    for metric, pattern in patterns.items():
        match_value = re.search(pattern, text)
        if not match_value:
            continue
        sign = -1 if match_value[1] == "下降" else 1
        row = observation(metric, date, sign * float(match_value[2]), "National Bureau of Statistics (official release)", url, captured,
                          release_date=released_at)
        if row:
            rows.append(row)
    return clean(rows)


def parse_release_html(html, url, captured):
    page = BeautifulSoup(html, "html.parser")
    for node in page.select("script, style, nav"):
        node.decompose()
    # Information-disclosure pages have a generic <title> and a dated h2.
    # Without it, the first date in the body can be a comparison/revision year.
    headline = page.select_one(".xxgkNbXqTitle") or page.select_one("title")
    body = page.select_one(".TRS_Editor") or page
    text = (headline.get_text() if headline else "") + body.get_text(" ", strip=True)
    visible = page.get_text(" ", strip=True)
    published = re.search(r"(20\d{2})/(\d{2})/(\d{2})", visible)
    if not published:
        published = re.search(r"成文日期\s*(20\d{2})年(\d{2})月(\d{2})日", visible)
    return parse_release(text, url, captured, published_at="-".join(published.groups()) if published else None)


def releases(fetch, captured, *, backfill=False):
    # Recent pages suffice for ongoing refresh; full history is an explicit backfill.
    count = 160 if backfill else 4
    def index_links(item):
        index, page = item
        url = index + (f"index_{page}.html" if page else "")
        response = fetch.get(url)
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
        return [urljoin(index, a["href"]) for a in soup.select("a[href]")
                if any(word in a.get_text() for word in ["居民消费价格", "固定资产投资", "规模以上工业增加值", "CPI和PPI", "CPI 和 PPI"])
                and re.search(r"/t20\d{6}_", urljoin(index, a["href"]))]
    links = set(HISTORICAL_INVESTMENT_RELEASES)
    with ThreadPoolExecutor(max_workers=3) as pool:
        pages = [(INDEX, page) for page in range(count)] + [("https://www.stats.gov.cn/sj/sjjd/", page) for page in range(60 if backfill else 3)]
        for future in as_completed([pool.submit(index_links, item) for item in pages]):
            try:
                links.update(future.result())
            except Exception:
                continue  # Fetcher records the failed URL; keep successful pages.
    links = sorted(url for url in links if "/t2015" not in url)
    def read(url):
        response = fetch.get(url)
        response.encoding = "utf-8"
        return parse_release_html(response.text, url, captured).to_dict("records")
    rows = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(read, url): url for url in links}
        for future in as_completed(futures):
            try:
                rows.extend(future.result())
            except Exception as error:
                fetch.failures.append({"url": futures[future], "error": f"Release parse: {type(error).__name__}: {str(error)[:160]}"})
    if not rows:
        raise ValueError("No recognized official NBS releases")
    return clean(sorted(rows, key=lambda row: (row["release_date"] or "", row["source_url"])))
