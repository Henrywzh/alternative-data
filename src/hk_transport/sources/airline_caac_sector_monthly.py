"""CAAC monthly sector production statistics from official PDF releases.

The Civil Aviation Administration of China publishes a public monthly
statistics index with one linked PDF per month.  The PDF table contains
monthly and year-to-date values for industry transport turnover, passenger and
cargo volume/turnover, aircraft utilization, load factors and airport
throughput.  This module keeps the regulator's release date separate from the
observation month and emits a long table suitable for sector-trend joins.

The PDF is a fast-report aggregation and the document itself says final
values are subject to the annual statistical report.  That caveat is retained
in ``status`` and ``source_note``; values are not used as company-specific
realized yield or revenue.
"""

from __future__ import annotations

import io
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Any
from urllib.parse import urljoin

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup
from urllib3.exceptions import InsecureRequestWarning

from ..config import (
    CAAC_ENGLISH_MONTHLY_KPI_INDEX_URL_TEMPLATE,
    CAAC_CHINESE_MONTHLY_KPI_LIST_URL,
    CAAC_MONTHLY_KPI_INDEX_URL,
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    NORMALIZED_DIR,
)
from ..storage import save_raw_snapshot


OUTPUT_PATH = NORMALIZED_DIR / "airline_caac_sector_monthly.csv"
DATASET_ID = "airline_caac_sector_monthly"

OUTPUT_COLUMNS = [
    "dataset_id",
    "source_organization",
    "source_document_date",
    "source_document_type",
    "source_url",
    "observation_month",
    "period_type",
    "scope",
    "metric",
    "value",
    "yoy_pct",
    "unit",
    "status",
    "source_release_date",
    "source_release_date_status",
    "point_in_time_status",
    "source_quality",
    "source_note",
    "raw_snapshot_path",
    "retrieved_at",
]


ROOT_METRICS: tuple[tuple[str, str], ...] = (
    ("运输总周转量", "total_transport_turnover"),
    ("旅客运输量", "passenger_volume"),
    ("货邮运输量", "cargo_mail_volume"),
    ("旅客周转量", "passenger_traffic_turnover"),
    ("货邮周转量", "cargo_mail_turnover"),
    ("飞机日利用率", "aircraft_daily_utilization"),
    ("正班客座率", "scheduled_passenger_load_factor"),
    ("正班载运率", "scheduled_cargo_load_factor"),
    ("旅客吞吐量", "airport_passenger_throughput"),
    ("货邮吞吐量", "airport_cargo_throughput"),
    ("起降架次", "airport_aircraft_movements"),
)

SCOPE_LABELS: tuple[tuple[str, str], ...] = (
    ("港澳台航线", "hk_macao_taiwan"),
    ("国内航线", "domestic"),
    ("国际航线", "international"),
    ("东部地区", "east"),
    ("中部地区", "central"),
    ("西部地区", "west"),
    ("东北地区", "northeast"),
)

ENGLISH_ROOT_METRICS: tuple[tuple[str, str], ...] = (
    ("Total Transport Turnover", "total_transport_turnover"),
    ("Passenger Volume", "passenger_volume"),
    ("Cargo and Mail Volume", "cargo_mail_volume"),
    ("Passenger Turnover", "passenger_traffic_turnover"),
    ("Cargo and Mail Turnover", "cargo_mail_turnover"),
    ("Daily Aircraft Use", "aircraft_daily_utilization"),
    ("Passenger Load Factor", "scheduled_passenger_load_factor"),
    ("Weight Load Factor", "scheduled_cargo_load_factor"),
    ("Passenger Throughput", "airport_passenger_throughput"),
    ("Cargo and Mail Throughput", "airport_cargo_throughput"),
    ("Aircraft Movements", "airport_aircraft_movements"),
)

ENGLISH_SCOPE_LABELS: tuple[tuple[str, str], ...] = (
    ("Macao and Taiwan Routes", "hk_macao_taiwan"),
    ("Domestic Routes", "domestic"),
    ("International Routes", "international"),
    ("Northeastern Region", "northeast"),
    ("Eastern Region", "east"),
    ("Central Region", "central"),
    ("Western Region", "west"),
)


def _number_tokens(line: str) -> list[float]:
    values: list[float] = []
    for token in re.findall(r"-?\d+(?:\.\d+)?", line):
        try:
            values.append(float(token))
        except ValueError:
            continue
    return values


def _matched_root(line: str) -> tuple[str, str] | None:
    for label, metric in ROOT_METRICS:
        if label in line:
            return label, metric
    return None


def _matched_scope(line: str) -> str | None:
    for label, scope in SCOPE_LABELS:
        if label in line:
            return scope
    return None


def _unit_after_label(line: str, label: str, first_number_start: int) -> str:
    tail = line[line.find(label) + len(label):first_number_start].strip()
    tail = re.sub(r"^[：:、\s]+", "", tail)
    return tail or "unknown"


def parse_caac_sector_kpi_text(
    text: str,
    *,
    observation_month: str,
    source_release_date: str,
    source_url: str,
    raw_snapshot_path: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse the one-page CAAC KPI table text into monthly/YTD rows."""
    if not re.fullmatch(r"\d{4}-\d{2}", str(observation_month)):
        raise ValueError(f"Invalid CAAC observation_month: {observation_month!r}")
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    section = "unknown"
    parent_metric: tuple[str, str] | None = None
    rows: list[dict[str, Any]] = []
    for raw_line in str(text).splitlines():
        line = " ".join(str(raw_line).split())
        if not line:
            continue
        if "运输完成情况" in line:
            section = "transport"
            parent_metric = None
            continue
        if "航班效率" in line:
            section = "efficiency"
            parent_metric = None
            continue
        if "机场完成情况" in line:
            section = "airport"
            parent_metric = None
            continue
        if "统计指标" in line or "月" in line and "当年累计" in line or line.startswith("注"):
            continue
        numbers = _number_tokens(line)
        if len(numbers) < 4:
            continue
        first_number = re.search(r"-?\d+(?:\.\d+)?", line)
        if first_number is None:
            continue
        root = _matched_root(line)
        if root is not None:
            label, metric = root
            # In the route and airport sections, a line containing a root label
            # is the total row for that metric.  The next route/region rows use
            # the same parent metric with a narrower scope.
            parent_metric = root
            scope = "total"
            if section == "airport":
                scope = "total"
            unit = _unit_after_label(line, label, first_number.start())
        elif parent_metric is not None and _matched_scope(line) is not None:
            label, metric = parent_metric
            scope = _matched_scope(line) or "unknown"
            scope_label = next(
                (scope_name for scope_name, scope_value in SCOPE_LABELS if scope_value == scope),
                scope,
            )
            unit = _unit_after_label(line, scope_label, first_number.start())
        else:
            continue
        values = numbers[-4:]
        for period_type, value, yoy in (
            ("monthly", values[0], values[1]),
            ("ytd", values[2], values[3]),
        ):
            rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "source_organization": "Civil Aviation Administration of China",
                    "source_document_date": source_release_date,
                    "source_document_type": "monthly_sector_production_statistics",
                    "source_url": source_url,
                    "observation_month": observation_month,
                    "period_type": period_type,
                    "scope": scope,
                    "metric": metric,
                    "value": value,
                    "yoy_pct": yoy,
                    "unit": unit,
                    "status": "official_fast_report",
                    "source_release_date": source_release_date,
                    "source_release_date_status": "official_page_announcement_date",
                    "point_in_time_status": "release_date_safe_observation",
                    "source_quality": "caac_primary_official_pdf",
                    "source_note": "CAAC monthly fast-report aggregation; final values are subject to the annual statistical report.",
                    "raw_snapshot_path": raw_snapshot_path,
                    "retrieved_at": retrieved,
                }
            )
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if result.empty:
        raise ValueError("CAAC KPI PDF text produced no recognized metric rows")
    result = result.drop_duplicates(
        subset=["observation_month", "period_type", "scope", "metric"], keep="last"
    ).sort_values(["period_type", "metric", "scope"]).reset_index(drop=True)
    return result


def parse_caac_sector_kpi_pdf(
    payload: bytes,
    *,
    observation_month: str,
    source_release_date: str,
    source_url: str,
    raw_snapshot_path: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Extract text from a CAAC PDF and parse its KPI table."""
    pages: list[str] = []
    tables: list[list[list[Any]]] = []
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
        is_english_table = any("Indicator" in text or "Traffic Handled" in text for text in pages)
        if is_english_table:
            for page in pdf.pages:
                tables.extend(page.extract_tables())
    if tables:
        return parse_caac_sector_kpi_tables(
            tables,
            observation_month=observation_month,
            source_release_date=source_release_date,
            source_url=source_url,
            raw_snapshot_path=raw_snapshot_path,
            retrieved_at=retrieved_at,
        )
    return parse_caac_sector_kpi_text(
        "\n".join(pages),
        observation_month=observation_month,
        source_release_date=source_release_date,
        source_url=source_url,
        raw_snapshot_path=raw_snapshot_path,
        retrieved_at=retrieved_at,
    )


def _clean_cell(value: object) -> str:
    return " ".join(str(value or "").replace("\n", " ").split())


def _english_root(label: str) -> tuple[str, str] | None:
    compact = re.sub(r"\s+", "", label).lower()
    for root_label, metric in ENGLISH_ROOT_METRICS:
        if re.sub(r"\s+", "", root_label).lower() in compact:
            return root_label, metric
    return None


def _english_scope(label: str) -> str | None:
    compact = re.sub(r"\s+", "", label).lower()
    for scope_label, scope in ENGLISH_SCOPE_LABELS:
        if re.sub(r"\s+", "", scope_label).lower() in compact:
            return scope
    return None


def parse_caac_sector_kpi_tables(
    tables: Iterable[list[list[Any]]],
    *,
    observation_month: str,
    source_release_date: str,
    source_url: str,
    raw_snapshot_path: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse the multi-page English CAAC PDF table representation."""
    if not re.fullmatch(r"\d{4}-\d{2}", str(observation_month)):
        raise ValueError(f"Invalid CAAC observation_month: {observation_month!r}")
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    logical: list[dict[str, Any]] = []
    section = "unknown"
    for table in tables:
        for raw_row in table:
            cells = [_clean_cell(cell) for cell in (raw_row or [])]
            cells += [""] * max(0, 6 - len(cells))
            joined = " ".join(cell for cell in cells[:2] if cell)
            if not joined and not any(cells[2:6]):
                continue
            if "Traffic Handled by Airports" in joined:
                section = "airport"
                continue
            if "Traffic Handled" in joined and "Airports" not in joined:
                section = "transport"
                continue
            if "Flight Efficiency" in joined:
                section = "efficiency"
                continue
            if joined in {"Indicator", "Unit", "Monthly Total", "Year-to-date Total", "Value YoY % Increase"}:
                continue
            numeric = [_number for _number in (_number_tokens(cell) for cell in cells) for _number in _number]
            if len(numeric) >= 4:
                logical.append(
                    {
                        "label": cells[0],
                        "unit": cells[1],
                        "values": numeric[-4:],
                        "section": section,
                    }
                )
                continue
            # English PDFs split long labels and units over continuation rows;
            # carry those fragments forward, including across a page break.
            if logical:
                if cells[0] and cells[0] not in {"Indicator", "Unit"}:
                    logical[-1]["label"] = f"{logical[-1]['label']} {cells[0]}".strip()
                if cells[1] and cells[1] not in {"Unit"}:
                    logical[-1]["unit"] = f"{logical[-1]['unit']} {cells[1]}".strip()

    parent_metric: tuple[str, str] | None = None
    rows: list[dict[str, Any]] = []
    for item in logical:
        label = _clean_cell(item["label"])
        root = _english_root(label)
        scope = "total"
        if root is not None:
            parent_metric = root
            metric = root[1]
        else:
            narrow_scope = _english_scope(label)
            if parent_metric is None or narrow_scope is None:
                continue
            metric = parent_metric[1]
            scope = narrow_scope
        values = item["values"]
        for period_type, value, yoy in (
            ("monthly", values[0], values[1]),
            ("ytd", values[2], values[3]),
        ):
            rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "source_organization": "Civil Aviation Administration of China",
                    "source_document_date": source_release_date,
                    "source_document_type": "monthly_sector_production_statistics",
                    "source_url": source_url,
                    "observation_month": observation_month,
                    "period_type": period_type,
                    "scope": scope,
                    "metric": metric,
                    "value": value,
                    "yoy_pct": yoy,
                    "unit": _clean_cell(item["unit"]) or "unknown",
                    "status": "official_fast_report",
                    "source_release_date": source_release_date,
                    "source_release_date_status": "official_page_announcement_date",
                    "point_in_time_status": "release_date_safe_observation",
                    "source_quality": "caac_primary_official_pdf",
                    "source_note": "CAAC monthly fast-report aggregation; final values are subject to the annual statistical report.",
                    "raw_snapshot_path": raw_snapshot_path,
                    "retrieved_at": retrieved,
                }
            )
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if result.empty:
        raise ValueError("CAAC English KPI tables produced no recognized metric rows")
    return result.drop_duplicates(
        subset=["observation_month", "period_type", "scope", "metric"], keep="last"
    ).sort_values(["period_type", "metric", "scope"]).reset_index(drop=True)


def _get(url: str) -> requests.Response:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", InsecureRequestWarning)
        response = requests.get(
            url,
            headers=DEFAULT_HEADERS,
            timeout=max(DEFAULT_TIMEOUT, 45),
            verify=False,
        )
    response.raise_for_status()
    return response


def discover_caac_monthly_kpi_pages(
    *,
    index_url: str = CAAC_MONTHLY_KPI_INDEX_URL,
    years: Iterable[int | str] | None = None,
) -> list[dict[str, str]]:
    """Discover monthly report pages and their PDF attachments from the index."""
    if years is not None:
        discovered: dict[str, dict[str, str]] = {}
        month_names = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12,
        }
        requested_years = {int(year_value) for year_value in years}
        for year in sorted(requested_years):
            page_number = 0
            while True:
                candidate = CAAC_ENGLISH_MONTHLY_KPI_INDEX_URL_TEMPLATE.format(year=year)
                if page_number:
                    candidate = candidate.rstrip("/") + f"/index_{page_number}.html"
                try:
                    response = _get(candidate)
                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 404:
                        break
                    raise
                soup = BeautifulSoup(response.content, "html.parser")
                found_on_page = False
                for anchor in soup.find_all("a", href=True):
                    text = " ".join(anchor.get_text(" ", strip=True).split())
                    match = re.search(
                        r"Statistics of Key Performance Indicators.*? in (January|February|March|April|May|June|July|August|September|October|November|December) (20\d{2})",
                        text,
                        flags=re.IGNORECASE,
                    )
                    if not match:
                        continue
                    month = f"{match.group(2)}-{month_names[match.group(1).lower()]:02d}"
                    page_url = urljoin(candidate, str(anchor["href"]))
                    report_page = _get(page_url)
                    page_soup = BeautifulSoup(report_page.content, "html.parser")
                    pdf_url = next(
                        (
                            urljoin(page_url, str(link["href"]))
                            for link in page_soup.find_all("a", href=True)
                            if str(link["href"]).lower().split("?")[0].endswith(".pdf")
                        ),
                        None,
                    )
                    if not pdf_url:
                        continue
                    found_on_page = True
                    page_text = " ".join(page_soup.get_text(" ", strip=True).split())
                    release_match = re.search(r"(\d{2})/(\d{2})/(20\d{2})", page_text)
                    if release_match:
                        release_date = f"{release_match.group(3)}-{release_match.group(2)}-{release_match.group(1)}"
                    else:
                        path_match = re.search(r"t(20\d{6})_", page_url)
                        release_date = (
                            f"{path_match.group(1)[:4]}-{path_match.group(1)[4:6]}-{path_match.group(1)[6:]}"
                            if path_match
                            else f"{month}-28"
                        )
                    discovered[month] = {
                        "observation_month": month,
                        "source_release_date": release_date,
                        "page_url": page_url,
                        "pdf_url": pdf_url,
                    }
                if not found_on_page or page_number >= 4:
                    break
                page_number += 1
        missing_years = requested_years - {
            int(key[:4]) for key in discovered
        }
        if missing_years:
            for page_number in range(13):
                candidate = (
                    CAAC_CHINESE_MONTHLY_KPI_LIST_URL
                    if page_number == 0
                    else CAAC_CHINESE_MONTHLY_KPI_LIST_URL.replace(
                        "index_1215.html", f"index_1215_{page_number}.html"
                    )
                )
                try:
                    response = _get(candidate)
                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 404:
                        break
                    raise
                soup = BeautifulSoup(response.content, "html.parser")
                for anchor in soup.find_all("a", href=True):
                    text = " ".join(anchor.get_text(" ", strip=True).split())
                    match = re.search(
                        r"中国民航(20\d{2})年(\d{1,2})月份主要生产指标统计", text
                    )
                    if not match or int(match.group(1)) not in missing_years:
                        continue
                    month = f"{match.group(1)}-{int(match.group(2)):02d}"
                    page_url = urljoin(candidate, str(anchor["href"]))
                    report_page = _get(page_url)
                    page_soup = BeautifulSoup(report_page.content, "html.parser")
                    pdf_url = next(
                        (
                            urljoin(page_url, str(link["href"]))
                            for link in page_soup.find_all("a", href=True)
                            if str(link["href"]).lower().split("?")[0].endswith(".pdf")
                        ),
                        None,
                    )
                    if not pdf_url:
                        continue
                    page_text = " ".join(page_soup.get_text(" ", strip=True).split())
                    release_match = re.search(
                        r"发文日期[：:]\s*(20\d{2}-\d{2}-\d{2})", page_text
                    )
                    path_match = re.search(r"t(20\d{6})_", page_url)
                    release_date = (
                        release_match.group(1)
                        if release_match
                        else (
                            f"{path_match.group(1)[:4]}-{path_match.group(1)[4:6]}-{path_match.group(1)[6:]}"
                            if path_match
                            else f"{month}-28"
                        )
                    )
                    discovered[month] = {
                        "observation_month": month,
                        "source_release_date": release_date,
                        "page_url": page_url,
                        "pdf_url": pdf_url,
                    }
        return [discovered[key] for key in sorted(discovered)]
    response = _get(index_url)
    soup = BeautifulSoup(response.content, "html.parser")
    discovered: dict[str, dict[str, str]] = {}
    for anchor in soup.find_all("a", href=True):
        text = " ".join(anchor.get_text(" ", strip=True).split())
        match = re.search(r"(20\d{2})年(\d{1,2})月份主要生产指标统计", text)
        if not match:
            continue
        month = f"{match.group(1)}-{int(match.group(2)):02d}"
        page_url = urljoin(index_url, str(anchor["href"]))
        page = _get(page_url)
        page_soup = BeautifulSoup(page.content, "html.parser")
        pdf_url = next(
            (
                urljoin(page_url, str(link["href"]))
                for link in page_soup.find_all("a", href=True)
                if str(link["href"]).lower().split("?")[0].endswith(".pdf")
            ),
            None,
        )
        if not pdf_url:
            continue
        page_text = " ".join(page_soup.get_text(" ", strip=True).split())
        release_match = re.search(r"发文日期[：:]\s*(20\d{2}-\d{2}-\d{2})", page_text)
        release_date = release_match.group(1) if release_match else month + "-28"
        discovered[month] = {
            "observation_month": month,
            "source_release_date": release_date,
            "page_url": page_url,
            "pdf_url": pdf_url,
        }
    return [discovered[key] for key in sorted(discovered)]


def _merge_vintages(result: pd.DataFrame, output_path: Path = OUTPUT_PATH) -> pd.DataFrame:
    if output_path.exists():
        prior = pd.read_csv(output_path)
        combined = pd.concat([prior, result], ignore_index=True)
    else:
        combined = result.copy()
    key = ["observation_month", "period_type", "scope", "metric", "source_release_date"]
    combined = combined.drop_duplicates(subset=key, keep="last")
    return combined.reindex(columns=OUTPUT_COLUMNS).sort_values(
        ["observation_month", "period_type", "metric", "scope"]
    ).reset_index(drop=True)


def fetch_caac_sector_monthly_kpis(
    *,
    months: Iterable[str] | None = None,
    years: Iterable[int | str] | None = None,
) -> pd.DataFrame:
    """Fetch all currently listed CAAC monthly KPI PDFs (or selected months)."""
    wanted = {str(month) for month in months} if months is not None else None
    reports = discover_caac_monthly_kpi_pages(years=years)
    if wanted is not None:
        reports = [report for report in reports if report["observation_month"] in wanted]
    if not reports:
        raise ValueError("No CAAC monthly KPI reports matched the requested months")
    retrieved = datetime.now(timezone.utc).isoformat()
    frames: list[pd.DataFrame] = []
    for report in reports:
        response = _get(report["pdf_url"])
        raw_path = save_raw_snapshot(
            f"caac_sector_kpi_{report['observation_month']}",
            response.content,
            file_ext="pdf",
            source_url=report["pdf_url"],
        )
        frame = parse_caac_sector_kpi_pdf(
            response.content,
            observation_month=report["observation_month"],
            source_release_date=report["source_release_date"],
            source_url=report["pdf_url"],
            raw_snapshot_path=str(raw_path),
            retrieved_at=retrieved,
        )
        frames.append(frame)
    result = _merge_vintages(pd.concat(frames, ignore_index=True))
    result.to_csv(OUTPUT_PATH, index=False)
    result.attrs["source_index_url"] = CAAC_MONTHLY_KPI_INDEX_URL
    return result


__all__ = [
    "OUTPUT_COLUMNS",
    "OUTPUT_PATH",
    "discover_caac_monthly_kpi_pages",
    "fetch_caac_sector_monthly_kpis",
    "parse_caac_sector_kpi_pdf",
    "parse_caac_sector_kpi_tables",
    "parse_caac_sector_kpi_text",
]
