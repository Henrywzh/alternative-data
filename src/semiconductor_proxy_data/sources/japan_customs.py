from __future__ import annotations

import re
from collections.abc import Iterable

import requests
from bs4 import BeautifulSoup

from semiconductor_proxy_data.models import OfficialMonthlyPoint, Snapshot, SourceCatalogPoint

USER_AGENT = "alternative-data-semiconductor-proxy/0.2"


class JapanCustomsSource:
    SEARCH_URL = "https://www.customs.go.jp/toukei/srch/indexe.htm?M=79&P=0"
    RESULT_URL = "https://www.customs.go.jp/JCWSV20/servlet/JCWSV20"
    CATEGORY_CONFIG = {
        "ic_only": {
            "principal_code": "7032305",
            "principal_name": "INTEGRATED CIRCUITS",
            "category_label": "IC-only",
        },
    }

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = 45,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.timeout = timeout

    def fetch_snapshots(self, months: list[str], regions: list[str], categories: list[str]) -> list[Snapshot]:
        if "japan" not in {region.lower() for region in regions}:
            return []

        target_categories = [category for category in categories if category in self.CATEGORY_CONFIG]
        if not target_categories:
            return []

        snapshots: list[Snapshot] = []
        for category in target_categories:
            config = self.CATEGORY_CONFIG[category]
            for start_month, end_month in _chunk_months(months, max_year_span=2):
                start_year = int(start_month[:4])
                end_year = int(end_month[:4])
                payload = _build_payload(
                    start_year=start_year,
                    end_year=end_year,
                    principal_code=config["principal_code"],
                    principal_name=config["principal_name"],
                )
                response = self.session.post(
                    self.RESULT_URL,
                    data=payload,
                    timeout=self.timeout,
                    verify=False,
                )
                response.raise_for_status()
                snapshots.append(
                    Snapshot(
                        name=f"official_japan_{category}_{start_month}_{end_month}",
                        source_url=self.RESULT_URL,
                        body=response.text,
                    )
                )
        return snapshots

    def extract(
        self,
        snapshots: list[Snapshot],
        run_id: str,
        scraped_at: str,
    ) -> list[OfficialMonthlyPoint]:
        points: list[OfficialMonthlyPoint] = []
        for snapshot in snapshots:
            if not snapshot.name.startswith("official_japan_"):
                continue
            parts = snapshot.name.split("_")
            if len(parts) < 6:
                continue
            category_id = "_".join(parts[2:-2])
            start_month = parts[-2]
            end_month = parts[-1]
            config = self.CATEGORY_CONFIG.get(category_id)
            if not config:
                continue

            soup = BeautifulSoup(snapshot.body, "html.parser")
            latest_public_text = soup.get_text(" ", strip=True)
            release_date = _parse_latest_release_month(latest_public_text)

            table = soup.find("table", class_="value")
            if table is None:
                continue

            for row in table.find_all("tr"):
                cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
                if len(cells) != 6:
                    continue
                raw_period, unit_label, current_quantity, current_value, ytd_quantity, ytd_value = cells
                period = raw_period.replace("/", "-")
                if period < start_month or period > end_month:
                    continue

                points.append(
                    OfficialMonthlyPoint(
                        dataset_id="semiconductor_official_monthly",
                        source_region="japan",
                        country_name="Japan",
                        metric_type="exports",
                        flow_code="X",
                        partner_scope="world",
                        period=period,
                        release_date=release_date,
                        expected_release_window_days=20,
                        lag_days=None,
                        category_id=category_id,
                        category_label=config["category_label"],
                        classification_system="Japan Principal Commodity",
                        classification_code=config["principal_code"],
                        unit="jpy_thousand",
                        currency="JPY",
                        value=_to_float(current_value),
                        yoy_pct=None,
                        mom_pct=None,
                        is_preliminary=False,
                        is_revised=False,
                        is_official_primary=True,
                        comparison_gap_pct=None,
                        source_name="Japan Customs Principal Commodity Series",
                        source_url=snapshot.source_url,
                        source_run_id=run_id,
                        scraped_at=scraped_at,
                        parser_version="semi-official-japan-v1",
                    )
                )
        return points

    def catalog_points(self, run_id: str, scraped_at: str) -> list[SourceCatalogPoint]:
        return [
            SourceCatalogPoint(
                dataset_id="semiconductor_source_catalog",
                source_region="japan",
                country_name="Japan",
                source_name="Japan Customs Principal Commodity Series",
                source_tier="official",
                metric_type="exports",
                category_id="ic_only",
                category_label="IC-only",
                coverage_start="1988-01",
                latest_period=None,
                cadence="monthly",
                expected_release_window_days=20,
                default_unit="jpy_thousand",
                default_currency="JPY",
                is_official_primary=True,
                notes="Official monthly principal commodity series for integrated circuits (7032305).",
                source_url=self.SEARCH_URL,
                source_run_id=run_id,
                scraped_at=scraped_at,
            )
        ]


def _build_payload(*, start_year: int, end_year: int, principal_code: str, principal_name: str) -> list[tuple[str, str]]:
    payload: list[tuple[str, str]] = [
        ("CW_SEARCHID", "JCCHT79S"),
        ("CW_JAPANKBN", "2"),
        ("CW_IMPKBN", "1"),
        ("CW_CARGOKBN", ""),
        ("CW_SUMKBN", ""),
        ("CW_SPCODE", ""),
        ("CW_SPNAME", ""),
        ("CW_YMSORTKBN", "3"),
        ("CW_SISUKBN", ""),
        ("CW_SENKIKBN", ""),
        ("CW_HKKBN", ""),
        ("CW_YMKBN", "2"),
        ("CW_KI", ""),
        ("CW_SYY", str(start_year)),
        ("CW_EYY", str(end_year)),
        ("CW_SMM", ""),
        ("CW_EMM", ""),
        ("CW_HSKBN", "6"),
        ("CW_HSCODE", principal_code),
        ("CW_HSNAME", principal_name),
    ]
    for _ in range(9):
        payload.extend([("CW_HSCODE", ""), ("CW_HSNAME", "")])
    payload.extend([
        ("CW_KUNIKBN", "1"),
    ])
    for _ in range(10):
        payload.extend([("CW_KUNICODE", ""), ("CW_KUNINAME", "")])
    payload.extend([
        ("CW_ZMKBN", "5"),
    ])
    for index in range(10):
        if index == 9:
            payload.extend([("CW_ZMCODE", ""), ("CW_ZMNAME", "74bfe79a173e16e1372ced2094f2aa9f02193927c419b63f2a99c5332fe6d50b")])
        else:
            payload.extend([("CW_ZMCODE", ""), ("CW_ZMNAME", "")])
    payload.append(("CW_MEISAICNT", "36"))
    return payload


def _chunk_months(months: Iterable[str], *, max_year_span: int) -> list[tuple[str, str]]:
    ordered = sorted({month for month in months})
    if not ordered:
        return []
    ranges: list[tuple[str, str]] = []
    start = ordered[0]
    end = ordered[0]
    start_year = int(start[:4])
    for month in ordered[1:]:
        year = int(month[:4])
        if year - start_year >= max_year_span:
            ranges.append((start, end))
            start = month
            end = month
            start_year = year
            continue
        end = month
    ranges.append((start, end))
    return ranges


def _parse_latest_release_month(text: str) -> str | None:
    match = re.search(r"made public so far is ([A-Za-z]+),\s*(\d{4})", text)
    if not match:
        return None
    month_name, year = match.groups()
    month_map = {
        "January": "01",
        "February": "02",
        "March": "03",
        "April": "04",
        "May": "05",
        "June": "06",
        "July": "07",
        "August": "08",
        "September": "09",
        "October": "10",
        "November": "11",
        "December": "12",
    }
    month_num = month_map.get(month_name)
    return f"{year}-{month_num}" if month_num else None


def _to_float(value: str) -> float | None:
    cleaned = value.replace(",", "").strip()
    if not cleaned:
        return None
    return float(cleaned)
