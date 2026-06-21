from __future__ import annotations

import json
import re
from typing import Any

import requests
from bs4 import BeautifulSoup
import pandas as pd

from taiwan_semiconductor_revenue_data.models import CompanyConfig, MonthlyRevenuePoint, Snapshot


DEFAULT_COMPANIES: tuple[CompanyConfig, ...] = (
    CompanyConfig(company_code="2330", company_name="TSMC", market="TWSE", industry="Foundry"),
    CompanyConfig(company_code="2303", company_name="UMC", market="TWSE", industry="Foundry"),
    CompanyConfig(company_code="5347", company_name="VIS", market="TPEx", industry="Foundry"),
)

MARKET_PATHS = {
    "TWSE": "sii",
    "TPEx": "otc",
}

CANONICAL_COLUMN_MAP = {
    "公司代號": "company_code",
    "代號": "company_code",
    "公司名稱": "company_name",
    "名稱": "company_name",
    "當月營收": "monthly_revenue_ntd",
    "營業收入-當月營收": "monthly_revenue_ntd",
    "本月營收": "monthly_revenue_ntd",
    "上月比較增減(%)": "mom_pct",
    "上月比較增減(％)": "mom_pct",
    "營業收入-上月比較增減(%)": "mom_pct",
    "營業收入-上月比較增減(％)": "mom_pct",
    "去年同月增減(%)": "yoy_pct",
    "去年同月增減(％)": "yoy_pct",
    "營業收入-去年同月增減(%)": "yoy_pct",
    "營業收入-去年同月增減(％)": "yoy_pct",
    "當月累計營收": "ytd_revenue_ntd",
    "營業收入-當月累計營收": "ytd_revenue_ntd",
    "累計營收": "ytd_revenue_ntd",
    "前期比較增減(%)": "ytd_yoy_pct",
    "前期比較增減(％)": "ytd_yoy_pct",
    "營業收入-前期比較增減(%)": "ytd_yoy_pct",
    "營業收入-前期比較增減(％)": "ytd_yoy_pct",
}

RAW_FIELD_MAP = {
    "company_name": "raw_company_name_text",
    "monthly_revenue_ntd": "raw_monthly_revenue_text",
    "mom_pct": "raw_mom_pct_text",
    "yoy_pct": "raw_yoy_pct_text",
    "ytd_revenue_ntd": "raw_ytd_revenue_text",
    "ytd_yoy_pct": "raw_ytd_yoy_pct_text",
}


class MopsMonthlyRevenueSource:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: int = 30,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout

    def resolve_companies(self, company_codes: list[str] | None = None) -> list[CompanyConfig]:
        if not company_codes:
            return list(DEFAULT_COMPANIES)

        available = {company.company_code: company for company in DEFAULT_COMPANIES}
        unknown = [code for code in company_codes if code not in available]
        if unknown:
            raise ValueError(f"Unsupported company codes: {', '.join(sorted(unknown))}")
        return [available[code] for code in company_codes]

    def fetch_snapshots(self, months: list[str], companies: list[CompanyConfig]) -> list[Snapshot]:
        snapshots: list[Snapshot] = []
        for month in months:
            year, month_number = month.split("-")
            roc_year = int(year) - 1911
            for company in companies:
                url = "https://mops.twse.com.tw/mops/api/t05st10_ifrs"
                payload = self._build_payload(company.company_code, roc_year, int(month_number))
                response = self.session.post(
                    url,
                    headers=self._api_headers(),
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                body = response.text
                snapshots.append(
                    Snapshot(
                        name=f"{company.company_code}_{year}_{month_number}",
                        source_url=url,
                        body=body,
                    )
                )
        return snapshots

    def extract(
        self,
        snapshot: Snapshot,
        *,
        companies: list[CompanyConfig],
        run_id: str,
        scraped_at: str,
        parser_version: str,
    ) -> tuple[list[MonthlyRevenuePoint], list[str]]:
        if snapshot.body.lstrip().startswith("{"):
            return self._extract_from_json_snapshot(
                snapshot,
                companies=companies,
                run_id=run_id,
                scraped_at=scraped_at,
                parser_version=parser_version,
            )

        revenue_month, filing_date = _extract_report_metadata(snapshot.body)
        frames = _extract_tables(snapshot.body)

        candidate_frames = [_normalize_dataframe(frame) for frame in frames]
        matching_frame = next((frame for frame in candidate_frames if _looks_like_revenue_table(frame)), None)
        if matching_frame is None:
            raise ValueError(f"No revenue table found in snapshot {snapshot.name}")

        records = _normalize_records(matching_frame)
        by_code = {
            _clean_code(record.get("company_code")): record
            for record in records
            if _clean_code(record.get("company_code"))
        }

        points: list[MonthlyRevenuePoint] = []
        failures: list[str] = []
        for company in companies:
            row = by_code.get(company.company_code)
            if row is None:
                failures.append(f"{snapshot.name}:{company.company_code}:missing-row")
                continue
            try:
                raw_values = {field: _stringify(row.get(field)) for field in RAW_FIELD_MAP}
                points.append(
                    MonthlyRevenuePoint(
                        dataset_id="tw_monthly_revenue",
                        company_code=company.company_code,
                        company_name=_stringify(row.get("company_name")) or company.company_name,
                        market=company.market,
                        industry=company.industry,
                        filing_date=filing_date,
                        revenue_month=revenue_month,
                        monthly_revenue_ntd=_parse_number(row.get("monthly_revenue_ntd")),
                        mom_pct=_parse_number(row.get("mom_pct")),
                        yoy_pct=_parse_number(row.get("yoy_pct")),
                        ytd_revenue_ntd=_parse_number(row.get("ytd_revenue_ntd")),
                        ytd_yoy_pct=_parse_number(row.get("ytd_yoy_pct")),
                        source_url=snapshot.source_url,
                        source_run_id=run_id,
                        scraped_at=scraped_at,
                        parser_version=parser_version,
                        **{target: raw_values[source] for source, target in RAW_FIELD_MAP.items()},
                    )
                )
            except ValueError as exc:
                failures.append(f"{snapshot.name}:{company.company_code}:{exc}")
        return points, failures

    @staticmethod
    def _build_month_url(market: str, roc_year: int, month: int) -> str:
        market_path = MARKET_PATHS[market]
        suffix = "_0" if roc_year > 98 else ""
        return f"https://mops.twse.com.tw/nas/t21/{market_path}/t21sc03_{roc_year}_{month}{suffix}.html"

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://mops.twse.com.tw/mops/web/t05st10_ifrs",
        }

    @staticmethod
    def _api_headers() -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
            "Origin": "https://mops.twse.com.tw",
            "Referer": "https://mops.twse.com.tw/mops/#/web/t05st10_ifrs",
        }

    @staticmethod
    def _build_payload(company_code: str, roc_year: int, month: int) -> dict[str, str]:
        return {
            "companyId": company_code,
            "dataType": "2",
            "month": str(month),
            "year": str(roc_year),
            "subsidiaryCompanyId": "",
        }

    def _extract_from_json_snapshot(
        self,
        snapshot: Snapshot,
        *,
        companies: list[CompanyConfig],
        run_id: str,
        scraped_at: str,
        parser_version: str,
    ) -> tuple[list[MonthlyRevenuePoint], list[str]]:
        payload = json.loads(snapshot.body)
        if payload.get("code") != 200:
            raise ValueError(f"MOPS API error: {payload.get('message')}")

        result = payload.get("result") or {}
        company_code = snapshot.name.split("_", 1)[0]
        company = next((item for item in companies if item.company_code == company_code), None)
        if company is None:
            company = next((item for item in companies if item.company_code == _extract_company_code_from_result(result)), None)
        if company is None:
            return [], [f"{snapshot.name}:missing-company-config"]

        revenue_month = _roc_yymm_to_gregorian(result.get("yymm"))
        filing_date = _extract_json_filing_date(payload.get("datetime"))
        values = _json_metric_map(result.get("data") or [])
        market_name = _stringify(result.get("marketKindName")) or ""

        point = MonthlyRevenuePoint(
            dataset_id="tw_monthly_revenue",
            company_code=company.company_code,
            company_name=_stringify(result.get("companyAbbreviation")) or company.company_name,
            market=_market_name_to_code(market_name) or company.market,
            industry=company.industry,
            filing_date=filing_date,
            revenue_month=revenue_month,
            monthly_revenue_ntd=_parse_number(values.get("本月")),
            mom_pct=None,
            yoy_pct=_parse_number(values.get("增減百分比_本月")),
            ytd_revenue_ntd=_parse_number(values.get("本年累計")),
            ytd_yoy_pct=_parse_number(values.get("增減百分比_累計")),
            source_url=snapshot.source_url,
            source_run_id=run_id,
            scraped_at=scraped_at,
            parser_version=parser_version,
            raw_company_name_text=_stringify(result.get("companyAbbreviation")),
            raw_monthly_revenue_text=_stringify(values.get("本月")),
            raw_mom_pct_text=None,
            raw_yoy_pct_text=_stringify(values.get("增減百分比_本月")),
            raw_ytd_revenue_text=_stringify(values.get("本年累計")),
            raw_ytd_yoy_pct_text=_stringify(values.get("增減百分比_累計")),
        )
        return [point], []


def _extract_report_metadata(html: str) -> tuple[str, str | None]:
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)

    month_match = re.search(r"資料年月[:：]?\s*(\d{2,3})/(\d{1,2})", text)
    if month_match is None:
        raise ValueError("Could not determine revenue month from page")
    revenue_month = _roc_year_month_to_gregorian(month_match.group(1), month_match.group(2))

    filing_match = re.search(r"(?:報表日期|出表日期)[:：]?\s*(\d{2,3})/(\d{1,2})/(\d{1,2})", text)
    filing_date = None
    if filing_match is not None:
        filing_date = _roc_date_to_gregorian(
            filing_match.group(1),
            filing_match.group(2),
            filing_match.group(3),
        )
    return revenue_month, filing_date


def _extract_tables(html: str) -> list[pd.DataFrame]:
    soup = BeautifulSoup(html, "html.parser")
    frames: list[pd.DataFrame] = []
    for table in soup.find_all("table"):
        rows: list[list[str | None]] = []
        max_width = 0
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if not cells:
                continue
            values = [cell.get_text(" ", strip=True) or None for cell in cells]
            max_width = max(max_width, len(values))
            rows.append(values)
        if not rows:
            continue
        normalized_rows = [row + [None] * (max_width - len(row)) for row in rows]
        frames.append(pd.DataFrame(normalized_rows))
    return frames


def _normalize_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    dataframe = frame.copy()
    if isinstance(dataframe.columns, pd.MultiIndex):
        dataframe.columns = [_flatten_header(column) for column in dataframe.columns]
    else:
        dataframe.columns = [_stringify(column) or "" for column in dataframe.columns]

    if all(re.fullmatch(r"\d+", str(column)) or str(column) == "" for column in dataframe.columns):
        header_row_index = _find_header_row(dataframe)
        if header_row_index is not None:
            header_values = [_stringify(value) or "" for value in dataframe.iloc[header_row_index].tolist()]
            dataframe = dataframe.iloc[header_row_index + 1 :].reset_index(drop=True)
            dataframe.columns = header_values

    dataframe = dataframe.dropna(axis=0, how="all").dropna(axis=1, how="all")
    dataframe.columns = [_normalize_label(column) for column in dataframe.columns]
    return dataframe.reset_index(drop=True)


def _find_header_row(frame: pd.DataFrame) -> int | None:
    for index, row in frame.iterrows():
        values = {_normalize_label(value) for value in row.tolist()}
        if {"公司代號", "公司名稱"}.issubset(values) or {"代號", "名稱"}.issubset(values):
            return int(index)
    return None


def _looks_like_revenue_table(frame: pd.DataFrame) -> bool:
    normalized_columns = {CANONICAL_COLUMN_MAP.get(_normalize_label(column)) for column in frame.columns}
    return "company_code" in normalized_columns and "monthly_revenue_ntd" in normalized_columns


def _normalize_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rename_map = {
        column: CANONICAL_COLUMN_MAP[_normalize_label(column)]
        for column in frame.columns
        if _normalize_label(column) in CANONICAL_COLUMN_MAP
    }
    normalized = frame.rename(columns=rename_map)
    keep_columns = list(dict.fromkeys(rename_map.values()))
    normalized = normalized[keep_columns]
    return normalized.to_dict(orient="records")


def _flatten_header(parts: Any) -> str:
    items = [_stringify(part) for part in parts if _stringify(part) and "unnamed" not in _stringify(part).lower()]
    return "-".join(items)


def _normalize_label(value: Any) -> str:
    text = _stringify(value) or ""
    text = text.replace("\n", "").replace(" ", "").replace("　", "")
    text = text.replace("（", "(").replace("）", ")").replace("％", "%")
    return text


def _stringify(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(value).strip()


def _clean_code(value: Any) -> str | None:
    text = _stringify(value)
    if text is None:
        return None
    digits = re.sub(r"\D", "", text)
    return digits or text


def _parse_number(value: Any) -> float | None:
    text = _stringify(value)
    if text is None or text in {"--", "-", "N/A", "nan"}:
        return None
    normalized = text.replace(",", "")
    return float(normalized)


def _roc_year_month_to_gregorian(roc_year: str, month: str) -> str:
    year = int(roc_year) + 1911
    return f"{year:04d}-{int(month):02d}"


def _roc_date_to_gregorian(roc_year: str, month: str, day: str) -> str:
    year = int(roc_year) + 1911
    return f"{year:04d}-{int(month):02d}-{int(day):02d}"


def _roc_yymm_to_gregorian(value: Any) -> str:
    text = _stringify(value)
    if text is None or not re.fullmatch(r"\d{4,5}", text):
        raise ValueError(f"Could not parse MOPS yymm value: {value}")
    roc_year = text[:-2]
    month = text[-2:]
    return _roc_year_month_to_gregorian(roc_year, month)


def _extract_json_filing_date(value: Any) -> str | None:
    text = _stringify(value)
    if text is None:
        return None
    match = re.search(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", text)
    if match is None:
        return None
    return _roc_date_to_gregorian(match.group(1), match.group(2), match.group(3))


def _json_metric_map(rows: list[list[Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    increase_count = 0
    for label, value, *_ in rows:
        normalized_label = _stringify(label) or ""
        if normalized_label == "增減百分比":
            key = "增減百分比_本月" if increase_count == 0 else "增減百分比_累計"
            metrics[key] = value
            increase_count += 1
            continue
        metrics[normalized_label] = value
    return metrics


def _extract_company_code_from_result(result: dict[str, Any]) -> str | None:
    code = result.get("companyId") or result.get("company_id")
    return _clean_code(code)


def _market_name_to_code(value: str) -> str | None:
    if "上市" in value:
        return "TWSE"
    if "上櫃" in value:
        return "TPEx"
    return None
