"""Free, bounded HTTP adapters. No network I/O is performed by Streamlit."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO
import hashlib
import json
import re
from pathlib import Path
from threading import RLock
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import pandas as pd
import requests

from .config import EM_URL, NBS_BASE, ROOT
from .normalize import clean, observation


class Fetcher:
    def __init__(self, run_id: str):
        self.raw_dir = ROOT / "data/raw/china_macro" / run_id
        self._nbs_lock = RLock()
        self._nbs_cache = {}
        self._nbs_session = None
        self.failures = []

    def get(self, url: str, *, params=None, payload=None, form=None, nbs=False):
        if nbs:
            # Reuse the official site's warmed cookie session; concurrent fresh
            # sessions otherwise intermittently receive HTTP-200 WAF HTML.
            with self._nbs_lock:
                key = url + json.dumps([params, payload], sort_keys=True)
                if key not in self._nbs_cache:
                    self._nbs_cache[key] = self._request(url, params=params, payload=payload, nbs=True)
                return self._nbs_cache[key]
        return self._request(url, params=params, payload=payload, form=form)

    def _request(self, url: str, *, params=None, payload=None, form=None, nbs=False):
        headers = {"User-Agent": "Mozilla/5.0", "Referer": url.split("/dg/")[0] if nbs else url}
        if nbs:
            from curl_cffi import requests as curl_requests
            headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36", "Accept": "application/json, text/plain, */*", "Origin": "https://data.stats.gov.cn", "Referer": "https://data.stats.gov.cn/dg/website/page.html#/pc/national/monthData"})
            if self._nbs_session is None:
                self._nbs_session = curl_requests.Session(impersonate="chrome")
                self._nbs_session.get(headers["Referer"], headers=headers, timeout=20)
            client, extra = self._nbs_session, {}
        else:
            client, extra = requests, {}
        last = None
        for _ in range(2):
            try:
                if form is not None:
                    response = client.post(url, data=form, params=params, headers=headers, timeout=20, **extra)
                elif payload is not None:
                    response = client.post(url, json=payload, params=params, headers=headers, timeout=20, **extra)
                else:
                    response = client.get(url, params=params, headers=headers, timeout=20, **extra)
                response.raise_for_status()
                if nbs or url == EM_URL:
                    response.json()  # HTML challenges are failed fetches, not data.
                # Store immutable response bodies outside git; hashes address duplicates.
                self.raw_dir.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256(response.content).hexdigest()
                (self.raw_dir / (digest + ".bin")).write_bytes(response.content)
                return response
            except Exception as error:
                last = error
        self.failures.append({"url": url, "error": type(last).__name__})
        raise RuntimeError(f"Fetch failed: {url}: {type(last).__name__}") from last


EM_REPORTS = {
    "RPT_ECONOMY_CPI": [("cpi_yoy", "NATIONAL_SAME", 1), ("cpi_mom", "NATIONAL_SEQUENTIAL", 1)],
    "RPT_ECONOMY_PPI": [("ppi_yoy", "BASE_SAME", 1)],
    "RPT_ECONOMY_TOTAL_RETAIL": [("retail_yoy", "RETAIL_TOTAL_SAME", 1), ("retail", "RETAIL_TOTAL", .1)],
    "RPT_ECONOMY_INDUS_GROW": [("industrial_yoy", "BASE_SAME", 1)],
    "RPT_ECONOMY_GDP": [("gdp_yoy", "SUM_SAME", 1), ("gdp", "DOMESTICL_PRODUCT_BASE", .1)],
    "RPT_ECONOMY_RMB_LOAN": [("new_loans", "RMB_LOAN", .1)],
    "RPT_ECONOMY_CURRENCY_SUPPLY": [("m2_yoy", "BASIC_CURRENCY_SAME", 1), ("m1_yoy", "CURRENCY_SAME", 1)],
    # Eastmoney customs source-native amounts are thousand USD, not USD bn.
    "RPT_ECONOMY_CUSTOMS": [("exports_yoy", "EXIT_BASE_SAME", 1), ("imports_yoy", "IMPORT_BASE_SAME", 1), ("exports", "EXIT_BASE", 1e-6), ("imports", "IMPORT_BASE", 1e-6)],
    "RPTA_WEB_RATE": [("lpr_1y", "LPR1Y", 1), ("lpr_5y", "LPR5Y", 1)],
}


def eastmoney(fetch: Fetcher, report: str, captured: str) -> pd.DataFrame:
    rows = []
    for page in range(1, 8):
        payload = fetch.get(EM_URL, params={"reportName": report, "columns": "ALL", "pageSize": 2000,
                            "pageNumber": page, "sortColumns": "TRADE_DATE" if report == "RPTA_WEB_RATE" else "REPORT_DATE", "sortTypes": -1}).json()
        result = payload.get("result") or {}
        data = result.get("data") or []
        if not data:
            raise ValueError(f"Empty Eastmoney report {report}, page {page}")
        for item in data:
            date = item.get("TRADE_DATE") or item.get("REPORT_DATE")
            for metric, field, scale in EM_REPORTS[report]:
                # From 2012 the February observation covers January–February.
                # These cumulative fields must NOT replace ordinary months.
                period = pd.Timestamp(date)
                if period.year >= 2012 and period.month == 2:
                    field = {"retail_yoy": "RETAIL_ACCUMULATE_SAME", "retail": "RETAIL_TOTAL_ACCUMULATE",
                             "industrial_yoy": "BASE_ACCUMULATE"}.get(metric, field)
                actual_metric = metric
                if metric == "m1_yoy" and pd.Timestamp(date) < pd.Timestamp("2025-01-01"):
                    actual_metric = "m1_legacy_yoy"
                row = observation(actual_metric, date, item.get(field), "Eastmoney (official statistics mirror)",
                                  "https://data.eastmoney.com/cjsj/", captured, scale=scale)
                if row:
                    rows.append(row)
        if page >= int(result.get("pages", 1)):
            break
    return clean(rows)


# Match complete published display names rather than ambiguous indicator names.
NBS_CATALOGS = {
    "工业>规上工业增加值增长速度": {"规上工业增加值同比增长": "industrial_yoy"},
    "工业>工业企业主要经济指标": {"利润总额累计增长": "industrial_profit_yoy", "利润总额累计值": "industrial_profit"},
    "房地产>房地产开发投资情况": {"房地产投资_累计增长": "property_investment_yoy"},
    "房地产>房地产施工、竣工面积": {"房地产新开工施工面积累计增长": "property_starts_yoy", "房地产竣工面积累计增长": "property_completions_yoy"},
    "房地产>新建商品房销售面积": {"新建商品房销售面积累计增长": "property_sales_area_yoy"},
    "房地产>新建商品房销售额": {"新建商品房销售额累计增长": "property_sales_value_yoy"},
    "固定资产投资 (不含农户)>固定资产投资概况": {"固定资产投资额累计增长": "fai_yoy"},
    "固定资产投资 (不含农户)>按行业分固定资产投资增速（2018-）": {"制造业固定资产投资额累计增长": "manufacturing_investment_yoy"},
    "采购经理指数>制造业采购经理指数": {"制造业采购经理指数": "pmi", "生产指数": "pmi_production", "新订单指数": "pmi_new_orders", "产成品库存指数": "pmi_inventory", "新出口订单指数": "pmi_export_orders"},
    "采购经理指数>非制造业采购经理指数": {"非制造业商务活动指数": "nonmanufacturing_pmi", "建筑业商务活动指数": "construction_pmi", "服务业商务活动指数": "services_pmi"},
}
for _vintage in ["(2021-2025)", "(2026-)"]:
    NBS_CATALOGS["价格指数>居民消费价格分类指数 (上年同月=100)>全国居民消费价格分类指数 (上年同月=100) " + _vintage] = {"不包括食品和能源居民消费价格指数": "core_cpi_yoy"}
# The previous industrial classification remains a separate catalog, same total
# manufacturing investment definition; don't silently lose the pre-2018 history.
NBS_CATALOGS["固定资产投资 (不含农户)>分行业固定资产投资情况 (2012-2017)"] = {"制造业固定资产投资额累计增长": "manufacturing_investment_yoy"}


def compact_name(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("（", "(").replace("）", ")")


def nbs_catalog(fetch: Fetcher, path: str, captured: str, start: str) -> pd.DataFrame:
    def tree(pid):
        return fetch.get(NBS_BASE + "/new/queryIndexTreeAsync", params={"pid": pid, "code": 1}, nbs=True).json().get("data") or []
    roots = tree("")
    if not roots:
        raise ValueError("Missing NBS root")
    root_id = roots[0]["_id"]
    cid = root_id
    for part in path.split(">"):
        candidates = [n for n in tree(cid) if compact_name(n["_name"]) == compact_name(part)]
        if len(candidates) != 1:
            raise ValueError(f"NBS catalog drift: {path}: {part}")
        cid = candidates[0]["_id"]
    indicators = fetch.get(NBS_BASE + "/new/queryIndicatorsByCid", params={"cid": cid, "dt": "", "name": ""}, nbs=True).json().get("data", {}).get("list", [])
    selected = {}
    for indicator in indicators:
        name = compact_name(indicator.get("i_showname", "")).split("(")[0]
        metric = NBS_CATALOGS[path].get(name)
        if metric:
            selected[indicator["_id"]] = (metric, indicator)
    if not selected:
        raise ValueError(f"No recognized NBS indicators: {path}")
    result = fetch.get(NBS_BASE + "/stream/esData", nbs=True, payload={
        "cid": cid, "rootId": root_id, "indicatorIds": list(selected), "showType": "1", "daCatalogId": "",
        "das": [{"text": "全国", "value": "000000000000"}],
        "dts": [pd.Timestamp(start).strftime("%Y%m") + "MM-" + pd.Timestamp(captured).strftime("%Y%m") + "MM"],
    }).json().get("data") or []
    rows = []
    for period in result:
        match = re.fullmatch(r"(\d{4})(\d{2})MM", period.get("code", ""))
        if not match:
            continue
        date = f"{match[1]}-{match[2]}-01"
        for item in period.get("values", []):
            if item.get("_id") not in selected:
                continue
            metric, indicator = selected[item["_id"]]
            row = observation(metric, date, item.get("value"), "National Bureau of Statistics", "https://data.stats.gov.cn/", captured,
                              scale=.1 if indicator.get("du_name") == "亿元" else 1,
                              definition=indicator.get("i_annotation") or indicator.get("i_showname", ""))
            if row:
                if metric == "core_cpi_yoy":
                    row["value"] -= 100  # source is previous-year-same-month=100
                rows.append(row)
    if not rows:
        raise ValueError(f"Empty NBS history: {path}")
    return clean(rows)


def rates_json(fetch: Fetcher, kind: str, captured: str) -> pd.DataFrame:
    url = "https://cdn.jin10.com/data_center/reports/" + ("il_1.json" if kind == "shibor" else "exchange_rate.json")
    values = fetch.get(url).json().get("values") or {}
    rows = []
    for date, readings in values.items():
        mapping = [("shibor_on", "O/N"), ("shibor_1w", "1W")] if kind == "shibor" else [("usdcny_fix", "美元/人民币")]
        for metric, key in mapping:
            item = readings.get(key)
            if isinstance(item, list) and item:
                row = observation(metric, date, item[0], "Jin10 (CFETS published rates mirror)", url, captured)
                if row:
                    rows.append(row)
    if not rows:
        raise ValueError(f"Empty {kind} history")
    return clean(rows)


def safe_fixing(fetch: Fetcher, captured: str) -> pd.DataFrame:
    """Official fixing is quoted per 100 USD; normalize to CNY per USD."""
    archive = "https://www.safe.gov.cn/safe/2020/1218/17833.html"
    page = BeautifulSoup(fetch.get(archive).content, "html.parser")
    links = [urljoin(archive, a["href"]) for a in page.select("a[href]") if "人民币汇率" in a.get_text() and re.search(r"\.xlsx?$", a["href"], re.I)]
    tables = []
    if links:
        from io import BytesIO
        tables.append(pd.read_excel(BytesIO(fetch.get(links[0]).content)))
    begin = "2020-12-01"
    if tables and "日期" in tables[0]:
        begin = (pd.to_datetime(tables[0]["日期"], errors="coerce").max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    url = "https://www.safe.gov.cn/AppStructured/hlw/RMBQuery.do"
    response = fetch.get(url, form={"startDate": begin, "endDate": captured[:10], "queryYN": "true"})
    response.encoding = "utf-8"
    tables.extend(pd.read_html(StringIO(response.text)))
    rows = []
    for table in tables:
        if "日期" not in table or "美元" not in table:
            continue
        for _, item in table.iterrows():
            row = observation("usdcny_fix", item["日期"], item["美元"], "State Administration of Foreign Exchange / CFETS", url, captured, scale=.01)
            if row:
                rows.append(row)
    if not rows:
        raise ValueError("SAFE central parity history unavailable")
    return clean(rows)


def bond_yields(fetch: Fetcher, captured: str, start: str) -> pd.DataFrame:
    url = "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/historyQuery"
    def year_rows(year):
        end = min(pd.Timestamp(captured).date(), pd.Timestamp(f"{year}-12-31").date())
        begin = max(pd.Timestamp(start).date(), pd.Timestamp(f"{year}-01-01").date())
        response = fetch.get(url, params={"startDate": str(begin), "endDate": str(end), "gjqx": "0", "qxId": "ycqx", "locale": "cn_ZH"})
        tables = pd.read_html(StringIO(response.text), header=0)
        rows = []
        for table in tables:
            if "日期" not in table.columns:
                continue
            for _, item in table.iterrows():
                if "国债" not in str(item.iloc[0]):
                    continue
                for metric, tenor in [("cgb_1y", "1年"), ("cgb_10y", "10年")]:
                    row = observation(metric, item["日期"], item.get(tenor), "ChinaBond / CCDC", url, captured)
                    if row:
                        rows.append(row)
        return rows
    rows = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(year_rows, year) for year in range(pd.Timestamp(start).year, pd.Timestamp(captured).year + 1)]
        for future in as_completed(futures):
            rows.extend(future.result())
    if not rows:
        raise ValueError("No government bond yield rows")
    return clean(rows)
