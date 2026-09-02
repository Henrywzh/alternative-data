"""Historical official Sino Land interim-report facts.

The current financial-facts layer contains the latest H1 report and annual
history.  This module fills the missing H1 observations from official HKEX or
issuer-hosted PDFs, keeping the raw document, release date and parser audit.
It is intentionally a parser/ingestion layer; it does not fit a forecast.
"""

from __future__ import annotations

from io import BytesIO
import json
import re
from typing import Any, Mapping
import uuid

import pandas as pd
import requests
from pypdf import PdfReader

from .config import DEFAULT_HEADERS
from .sino_land_financial_model import SINO_LAND_TICKER
from .storage import save_normalized_dataset, save_raw_snapshot


H1_HISTORY_DATASET = "sino_land_h1_history"
H1_HISTORY_AUDIT_DATASET = "sino_land_h1_history_audit"

INTERIM_REPORT_REGISTRY: tuple[dict[str, str], ...] = (
    {
        "report_id": "sino_ir_2020_21",
        "fiscal_label": "FY2020/21",
        "period_end": "2020-12-31",
        "fiscal_year_end": "2021-06-30",
        "release_date": "2021-03-15",
        "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2021/0315/2021031500181.pdf",
    },
    {
        "report_id": "sino_ir_2021_22",
        "fiscal_label": "FY2021/22",
        "period_end": "2021-12-31",
        "fiscal_year_end": "2022-06-30",
        "release_date": "2022-03-07",
        "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0307/2022030700723.pdf",
    },
    {
        "report_id": "sino_ir_2022_23",
        "fiscal_label": "FY2022/23",
        "period_end": "2022-12-31",
        "fiscal_year_end": "2023-06-30",
        "release_date": "2023-03-09",
        "source_url": "https://www.hkexnews.hk/listedco/listconews/sehk/2023/0309/2023030900217.pdf",
    },
    {
        "report_id": "sino_ir_2023_24",
        "fiscal_label": "FY2023/24",
        "period_end": "2023-12-31",
        "fiscal_year_end": "2024-06-30",
        "release_date": "2024-03-11",
        "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0311/2024031100217.pdf",
    },
    {
        "report_id": "sino_ir_2024_25",
        "fiscal_label": "FY2024/25",
        "period_end": "2024-12-31",
        "fiscal_year_end": "2025-06-30",
        "release_date": "2025-03-14",
        "source_url": "https://www.hkexnews.hk/listedco/listconews/sehk/2025/0314/2025031400265.pdf",
    },
    {
        "report_id": "sino_ir_2025_26",
        "fiscal_label": "FY2025/26",
        "period_end": "2025-12-31",
        "fiscal_year_end": "2026-06-30",
        "release_date": "2026-03-17",
        "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0317/2026031700201.pdf",
    },
)

H1_HISTORY_COLUMNS = [
    "fact_id",
    "ticker",
    "report_id",
    "fiscal_label",
    "fact_group",
    "segment",
    "metric",
    "value",
    "unit",
    "currency",
    "period_start",
    "period_end",
    "fiscal_year_end",
    "period_type",
    "geography_scope",
    "attribution_scope",
    "accounting_basis",
    "source_url",
    "source_page",
    "release_date",
    "availability_quality",
    "evidence_status",
    "model_use",
    "caveat",
]

H1_HISTORY_AUDIT_COLUMNS = [
    "audit_id",
    "ticker",
    "report_id",
    "fiscal_label",
    "period_end",
    "release_date",
    "source_url",
    "fetch_status",
    "parse_status",
    "fact_rows",
    "missing_metrics",
    "statement_page",
    "revenue_note_page",
    "segment_page",
    "unit_scale",
    "raw_snapshot",
    "error",
    "caveat",
]

GROUP_METRICS = (
    "consolidated_revenue",
    "sales_of_properties",
    "rental_income_operating_leases",
    "hotel_operations_revenue",
    "underlying_profit_attributable",
    "profit_attributable",
)
SEGMENT_COMPONENTS = (
    "property_sales",
    "property_rental",
    "property_management_other_services",
    "hotel_operations",
    "investments_securities",
    "financing",
)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _number(value: str) -> float | None:
    cleaned = value.strip().replace(",", "")
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()")
    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    return -parsed if negative else parsed


_NUM_TOKEN = re.compile(r"\([0-9][0-9,]*(?:\.\d+)?\)|[0-9][0-9,]*(?:\.\d+)?|[-–—]")


def _values_after(pattern: str, text: str, count: int = 2) -> list[float]:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return []
    values: list[float] = []
    for token in _NUM_TOKEN.findall(text[match.end() : match.end() + 500]):
        if token in {"-", "–", "—"}:
            continue
        parsed = _number(token)
        if parsed is not None:
            values.append(parsed)
        if len(values) >= count:
            break
    return values


def _find_page(pages: list[str], predicate: Any) -> tuple[int | None, str]:
    for index, text in enumerate(pages):
        if predicate(text):
            return index + 1, text
    return None, ""


def _period_start(period_end: str) -> str:
    end = pd.Timestamp(period_end)
    return (end - pd.DateOffset(months=6) + pd.DateOffset(days=1)).strftime(
        "%Y-%m-%d"
    )


def _fact(
    item: Mapping[str, str],
    *,
    fact_group: str,
    segment: str | None,
    metric: str,
    value: float,
    unit: str,
    source_page: int,
    accounting_basis: str,
    attribution_scope: str,
    caveat: str,
) -> dict[str, Any]:
    return {
        "fact_id": f"sino_land:{item['report_id']}:{metric}:{segment or 'group'}",
        "ticker": SINO_LAND_TICKER,
        "report_id": item["report_id"],
        "fiscal_label": item["fiscal_label"],
        "fact_group": fact_group,
        "segment": segment,
        "metric": metric,
        "value": value,
        "unit": unit,
        "currency": "HKD",
        "period_start": _period_start(item["period_end"]),
        "period_end": item["period_end"],
        "fiscal_year_end": item["fiscal_year_end"],
        "period_type": "interim",
        "geography_scope": "group_all_geographies",
        "attribution_scope": attribution_scope,
        "accounting_basis": accounting_basis,
        "source_url": item["source_url"],
        "source_page": str(source_page),
        "release_date": item["release_date"],
        "availability_quality": "hkex_release_date_verified_time_unverified",
        "evidence_status": "parsed_official_pdf",
        "model_use": "historical_h1_actual",
        "caveat": caveat,
    }


def parse_sino_land_interim_report(
    content: bytes,
    item: Mapping[str, str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse one official interim PDF without using comparative columns."""
    reader = PdfReader(BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages]
    target_year = pd.Timestamp(item["period_end"]).year
    target_pattern = rf"six months ended\s+(?:31st\s+December,?\s*)?{target_year}"
    statement_page, statement = _find_page(
        pages,
        lambda text: re.search(target_pattern, text, re.IGNORECASE)
        and "Profit for the period" in text
        and re.search(r"\bRevenue\s+3,?\s*4", text, re.IGNORECASE) is not None,
    )
    revenue_note_page, revenue_note = _find_page(
        pages,
        lambda text: re.search(target_pattern, text, re.IGNORECASE)
        and re.search(r"3\.\s*Revenue", text, re.IGNORECASE)
        and "Sales of properties" in text,
    )
    segment_page, segment_text = _find_page(
        pages,
        lambda text: re.search(target_pattern, text, re.IGNORECASE)
        and "Property sales" in text
        and re.search(r"Segment\s+revenue", text, re.IGNORECASE) is not None,
    )
    scale = 1.0 if re.search(r"HK\$\s*Million", statement, re.IGNORECASE) else 1e-6
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    if statement_page is None:
        missing.extend(["consolidated_revenue", "profit_attributable"])
    else:
        revenue_values = _values_after(r"\bRevenue\s+3,?\s*4", statement)
        # The issuer's PDF text extraction varies between straight and curly
        # apostrophes, and older reports insert a space before the apostrophe.
        # Match the label rather than relying on one exact glyph sequence.
        profit_values = _values_after(
            r"The\s+Company.{0,12}shareholders", statement, count=1
        )
        if revenue_values:
            rows.append(
                _fact(
                    item,
                    fact_group="interim_actuals",
                    segment=None,
                    metric="consolidated_revenue",
                    value=revenue_values[0] * scale,
                    unit="HKD_m",
                    source_page=statement_page,
                    accounting_basis="interim_consolidated_statement",
                    attribution_scope="consolidated_group",
                    caveat="Parsed from the current-period Revenue row; comparative column was ignored.",
                )
            )
        else:
            missing.append("consolidated_revenue")
        if profit_values:
            rows.append(
                _fact(
                    item,
                    fact_group="interim_actuals",
                    segment=None,
                    metric="profit_attributable",
                    value=profit_values[0] * scale,
                    unit="HKD_m",
                    source_page=statement_page,
                    accounting_basis="interim_consolidated_statement",
                    attribution_scope="company_shareholders",
                    caveat="Parsed from the current-period company-shareholders profit row; comparative column was ignored.",
                )
            )
        else:
            missing.append("profit_attributable")

    if revenue_note_page is None:
        missing.extend(
            ["sales_of_properties", "rental_income_operating_leases", "hotel_operations_revenue"]
        )
    else:
        note_patterns = {
            "sales_of_properties": r"^[ \t]*Sales\s+of\s+properties",
            "hotel_operations_revenue": r"^[ \t]*Hotel\s+operations",
            "rental_income_operating_leases": r"^[ \t]*Rental\s+income\s+from\s+operating\s+leases",
        }
        for metric, pattern in note_patterns.items():
            values = _values_after(pattern, revenue_note)
            if not values:
                missing.append(metric)
                continue
            rows.append(
                _fact(
                    item,
                    fact_group="interim_actuals",
                    segment={
                        "sales_of_properties": "property_sales",
                        "rental_income_operating_leases": "property_rental",
                        "hotel_operations_revenue": "hotel_operations",
                    }[metric],
                    metric=metric,
                    value=values[0] * scale,
                    unit="HKD_m",
                    source_page=revenue_note_page,
                    accounting_basis="interim_revenue_note",
                    attribution_scope="consolidated_group",
                    caveat="Parsed from Note 3 current-period revenue row; comparative column was ignored.",
                )
            )

    if segment_page is None:
        missing.extend([f"segment:{component}" for component in SEGMENT_COMPONENTS])
    else:
        labels = {
            "property_sales": r"^[ \t]*Property\s+sales",
            "property_rental": r"^[ \t]*Property\s+rental",
            "property_management_other_services": r"^[ \t]*Property\s+management\s+and\s+other\s+services",
            "hotel_operations": r"^[ \t]*Hotel\s+operations",
            "investments_securities": r"^[ \t]*Investments\s+in\s+securities",
            "financing": r"^[ \t]*Financing",
        }
        for component, pattern in labels.items():
            values = _values_after(pattern, segment_text, count=6)
            if len(values) < 6:
                missing.append(f"segment:{component}")
                continue
            for metric, value in (
                ("segment_revenue", values[4]),
                ("segment_result", values[5]),
            ):
                rows.append(
                    _fact(
                        item,
                        fact_group="operating_segments",
                        segment=component,
                        metric=metric,
                        value=value * scale,
                        unit="HKD_m",
                        source_page=segment_page,
                        accounting_basis="interim_operating_segment_note",
                        attribution_scope="company_and_subsidiaries_plus_share_of_associates_and_joint_ventures",
                        caveat="Parsed from the current-period combined Segment revenue/result columns; this includes associates/JVs and is not consolidated turnover.",
                    )
                )

    # Underlying profit is a narrative KPI, not part of the accounting table.
    full_text = "\n".join(pages)
    underlying_match = re.search(
        r"underlying\s+profit\s+attributable.*?was\s+HK\$?\s*([0-9][0-9,]*(?:\.\d+)?)\s*million",
        full_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if underlying_match:
        rows.append(
            _fact(
                item,
                fact_group="interim_actuals",
                segment=None,
                metric="underlying_profit_attributable",
                value=float(underlying_match.group(1).replace(",", "")),
                unit="HKD_m",
                source_page=_page_for_position(pages, underlying_match.start()),
                accounting_basis="interim_chairman_statement",
                attribution_scope="company_shareholders",
                caveat="Parsed from the interim-report narrative KPI; it excludes investment-property fair-value changes per the issuer's definition.",
            )
        )
    else:
        missing.append("underlying_profit_attributable")

    facts = pd.DataFrame(rows, columns=H1_HISTORY_COLUMNS)
    facts = facts.drop_duplicates(subset=["fact_id"], keep="first")
    audit = {
        "audit_id": f"sino_land_h1_history:{item['report_id']}",
        "ticker": SINO_LAND_TICKER,
        "report_id": item["report_id"],
        "fiscal_label": item["fiscal_label"],
        "period_end": item["period_end"],
        "release_date": item["release_date"],
        "source_url": item["source_url"],
        "fetch_status": "fetched",
        "parse_status": "pass" if not missing else "warn",
        "fact_rows": len(facts),
        "missing_metrics": json.dumps(sorted(set(missing)), ensure_ascii=False),
        "statement_page": statement_page,
        "revenue_note_page": revenue_note_page,
        "segment_page": segment_page,
        "unit_scale": scale,
        "raw_snapshot": None,
        "error": None,
        "caveat": "Parser uses current-period columns only; comparative figures remain in the PDF but are not ingested as separate facts.",
    }
    return facts, audit


def _page_for_position(pages: list[str], position: int) -> int:
    remaining = position
    for index, page in enumerate(pages, start=1):
        if remaining <= len(page):
            return index
        remaining -= len(page) + 1
    return len(pages)


def run_sino_land_h1_history(
    *,
    persist: bool = True,
    timeout: float = 60.0,
    report_items: tuple[Mapping[str, str], ...] = INTERIM_REPORT_REGISTRY,
) -> dict[str, Any]:
    """Fetch, parse and optionally persist the official H1 history."""
    run_id = f"sino-land-h1-history-{uuid.uuid4()}"
    fact_parts: list[pd.DataFrame] = []
    audits: list[dict[str, Any]] = []
    raw_snapshots: list[str] = []
    for raw_item in report_items:
        item = dict(raw_item)
        audit_base = {
            "audit_id": f"sino_land_h1_history:{item['report_id']}",
            "ticker": SINO_LAND_TICKER,
            "report_id": item["report_id"],
            "fiscal_label": item["fiscal_label"],
            "period_end": item["period_end"],
            "release_date": item["release_date"],
            "source_url": item["source_url"],
            "fetch_status": "not_fetched",
            "parse_status": "not_run",
            "fact_rows": 0,
            "missing_metrics": "[]",
            "statement_page": None,
            "revenue_note_page": None,
            "segment_page": None,
            "unit_scale": None,
            "raw_snapshot": None,
            "error": None,
            "caveat": "Parser uses current-period columns only; comparative figures remain in the PDF but are not ingested as separate facts.",
        }
        try:
            response = requests.get(
                item["source_url"], headers=DEFAULT_HEADERS, timeout=timeout
            )
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise ValueError("response did not start with a PDF signature")
            audit_base["fetch_status"] = "fetched"
            raw_snapshot = None
            if persist:
                raw_snapshot = save_raw_snapshot(
                    "sino_land_h1_reports",
                    response.content,
                    file_ext="pdf",
                    source_url=item["source_url"],
                    run_id=run_id,
                )
                audit_base["raw_snapshot"] = str(raw_snapshot)
                raw_snapshots.append(str(raw_snapshot))
            facts, audit = parse_sino_land_interim_report(response.content, item)
            fact_parts.append(facts)
            audit_base.update(audit)
            audit_base["raw_snapshot"] = str(raw_snapshot) if raw_snapshot else None
        except Exception as exc:  # pragma: no cover - exercised by live source failures
            audit_base["fetch_status"] = (
                "fetch_failed" if audit_base["fetch_status"] == "not_fetched" else "parse_failed"
            )
            audit_base["parse_status"] = "fail"
            audit_base["error"] = f"{type(exc).__name__}: {exc}"
        audits.append(audit_base)

    facts = (
        pd.concat(fact_parts, ignore_index=True)
        if fact_parts
        else pd.DataFrame(columns=H1_HISTORY_COLUMNS)
    )
    if not facts.empty:
        facts = facts.drop_duplicates(subset=["fact_id"], keep="last").sort_values(
            ["period_end", "fact_group", "segment", "metric"], na_position="last"
        )
    audit_frame = pd.DataFrame(audits, columns=H1_HISTORY_AUDIT_COLUMNS)
    normalized: dict[str, Any] = {}
    if persist:
        source_urls = [item["source_url"] for item in report_items]
        lineage = {
            "lineage_type": "sino_land_official_h1_history",
            "run_id": run_id,
            "ticker": SINO_LAND_TICKER,
            "source_urls": source_urls,
            "research_only": False,
            "model_fit_performed": False,
        }
        normalized[H1_HISTORY_DATASET] = save_normalized_dataset(
            H1_HISTORY_DATASET,
            facts,
            run_id=run_id,
            raw_snapshots=raw_snapshots,
            source_urls=source_urls,
            lineage_metadata=lineage,
        )
        normalized[H1_HISTORY_AUDIT_DATASET] = save_normalized_dataset(
            H1_HISTORY_AUDIT_DATASET,
            audit_frame,
            run_id=run_id,
            raw_snapshots=raw_snapshots,
            source_urls=source_urls,
            lineage_metadata=lineage,
        )
    return {
        "run_id": run_id,
        "ticker": SINO_LAND_TICKER,
        "report_count": len(report_items),
        "fact_rows": int(len(facts)),
        "audit_rows": int(len(audit_frame)),
        "failed_reports": int(audit_frame["parse_status"].eq("fail").sum())
        if not audit_frame.empty
        else 0,
        "non_pass_reports": int(
            audit_frame["parse_status"].ne("pass").sum()
        )
        if not audit_frame.empty
        else 0,
        "normalized": normalized,
    }
