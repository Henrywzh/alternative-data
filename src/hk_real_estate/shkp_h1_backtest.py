"""Official SHKP interim-report panel and H1-to-FY backtest.

The financial-model input builder previously depended on source-selected rows
from the sibling ``financial-data`` repository.  Those rows are useful as a
fallback, but their original announcement dates are not retained.  This
module creates a separate, auditable lane from SHKP's own interim-report PDFs.

The parser is intentionally conservative.  It extracts only figures that are
next to an interpretable label in the English financial highlights or financial
review section.  Missing figures remain missing; no H1 number is inferred from
an annual number or from a comparative percentage.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd
import requests
from pypdf import PdfReader

from .config import DEFAULT_HEADERS
from .storage import load_latest_normalized, save_normalized_dataset, save_raw_snapshot


H1_REPORT_REGISTRY_DATA: tuple[dict[str, Any], ...] = (
    {
        "report_id": "shkp_fy2016_17_h1",
        "fiscal_label": "FY2016/17",
        "fiscal_year_end": 2017,
        "period_start": "2016-07-01",
        "period_end": "2016-12-31",
        "release_date": "2017-02-28",
        "source_url": "https://www.shkp.com/sites/assets/files/2019-01/E_IR_2016_17.pdf",
    },
    {
        "report_id": "shkp_fy2017_18_h1",
        "fiscal_label": "FY2017/18",
        "fiscal_year_end": 2018,
        "period_start": "2017-07-01",
        "period_end": "2017-12-31",
        "release_date": "2018-02-27",
        "source_url": "https://www.shkp.com/sites/assets/files/2019-01/E_IR_2017_18.pdf",
    },
    {
        "report_id": "shkp_fy2018_19_h1",
        "fiscal_label": "FY2018/19",
        "fiscal_year_end": 2019,
        "period_start": "2018-07-01",
        "period_end": "2018-12-31",
        "release_date": "2019-02-27",
        "source_url": "https://www.shkp.com/sites/assets/files/2019-03/E_IR_2018_19.pdf",
    },
    {
        "report_id": "shkp_fy2019_20_h1",
        "fiscal_label": "FY2019/20",
        "fiscal_year_end": 2020,
        "period_start": "2019-07-01",
        "period_end": "2019-12-31",
        "release_date": "2020-02-27",
        "source_url": "https://www.shkp.com/Content/Uploads/FinReports/E_IR_2019_20.pdf",
    },
    {
        "report_id": "shkp_fy2020_21_h1",
        "fiscal_label": "FY2020/21",
        "fiscal_year_end": 2021,
        "period_start": "2020-07-01",
        "period_end": "2020-12-31",
        "release_date": "2021-02-25",
        "source_url": "https://www.shkp.com/Content/Uploads/FinReports/E_IR_2020_21.pdf",
    },
    {
        "report_id": "shkp_fy2021_22_h1",
        "fiscal_label": "FY2021/22",
        "fiscal_year_end": 2022,
        "period_start": "2021-07-01",
        "period_end": "2021-12-31",
        "release_date": "2022-02-24",
        "source_url": "https://www.shkp.com/Content/Uploads/FinReports/E_IR_2021_22.pdf",
    },
    {
        "report_id": "shkp_fy2022_23_h1",
        "fiscal_label": "FY2022/23",
        "fiscal_year_end": 2023,
        "period_start": "2022-07-01",
        "period_end": "2022-12-31",
        "release_date": "2023-02-23",
        "source_url": "https://www.shkp.com/sites/assets/files/2023-03/ew_00016IR-23022023.pdf",
    },
    {
        "report_id": "shkp_fy2023_24_h1",
        "fiscal_label": "FY2023/24",
        "fiscal_year_end": 2024,
        "period_start": "2023-07-01",
        "period_end": "2023-12-31",
        "release_date": "2024-02-28",
        "source_url": "https://www.shkp.com/Content/Uploads/FinReports/E_IR_2023_24.pdf",
    },
    {
        "report_id": "shkp_fy2024_25_h1",
        "fiscal_label": "FY2024/25",
        "fiscal_year_end": 2025,
        "period_start": "2024-07-01",
        "period_end": "2024-12-31",
        "release_date": "2025-02-27",
        "source_url": "https://www.shkp.com/Content/Uploads/FinReports/E_IR_2024_25.pdf",
    },
    {
        "report_id": "shkp_fy2025_26_h1",
        "fiscal_label": "FY2025/26",
        "fiscal_year_end": 2026,
        "period_start": "2025-07-01",
        "period_end": "2025-12-31",
        "release_date": "2026-02-26",
        "source_url": "https://www.shkp.com/Content/Uploads/FinReports/E_IR_2025_26.pdf",
    },
)

REPORT_REGISTRY_DATASET = "shkp_h1_report_registry"
H1_ACTUAL_DATASET = "shkp_h1_actual_panel"
H1_BACKTEST_DATASET = "shkp_h1_actual_vs_nowcast"
H1_BRIDGE_DATASET = "shkp_h1_to_fy_bridge"
H1_COMPONENT_ANNUAL_DATASET = "shkp_h1_component_annual_history"
H1_COMPONENT_BACKTEST_DATASET = "shkp_h1_component_actual_vs_nowcast"

REPORT_REGISTRY_COLUMNS = [
    "report_id", "ticker", "fiscal_label", "fiscal_year_end", "period_start",
    "period_end", "period_type", "release_date", "source_url", "document_type",
    "source_role", "pit_quality", "parser_status", "retrieved_at", "raw_snapshot",
    "caveat",
]

H1_ACTUAL_COLUMNS = [
    "fact_id", "ticker", "report_id", "fiscal_label", "fiscal_year_end",
    "period_start", "period_end", "period_type", "scope", "segment", "metric",
    "value", "unit", "currency", "value_operator", "source_page", "source_url",
    "release_date", "availability_date", "pit_quality", "source_method",
    "evidence_excerpt", "caveat",
]

H1_BACKTEST_COLUMNS = [
    "target_fiscal_year", "fiscal_label", "period_end", "metric", "unit", "currency",
    "h1_actual", "full_year_actual", "training_years", "training_observations",
    "h1_share_median", "h1_annualized_forecast", "prior_share_forecast",
    "h1_annualized_error_pct", "prior_share_error_pct", "h1_annualized_ape_pct",
    "prior_share_ape_pct", "model_status", "pit_quality", "actual_source",
    "h1_source", "caveat",
]

H1_BRIDGE_COLUMNS = [
    "fiscal_year_end", "fiscal_label", "metric", "unit", "currency", "h1_actual",
    "h2_actual", "full_year_actual", "h1_share_pct", "h2_share_pct", "scope",
    "h1_source", "full_year_source", "pit_quality", "status", "caveat",
]

H1_COMPONENT_ANNUAL_COLUMNS = [
    "fiscal_year_end", "fiscal_label", "group_revenue_hkd_m",
    "hk_development_revenue_hkd_m", "hk_rental_revenue_hkd_m",
    "hotel_revenue_hkd_m", "residual_revenue_hkd_m", "source_status",
    "caveat",
]

H1_COMPONENT_BACKTEST_COLUMNS = [
    "target_fiscal_year", "fiscal_label", "period_end", "target_metric",
    "h1_group_revenue_hkd_m", "full_year_group_revenue_hkd_m",
    "h2_group_revenue_actual_hkd_m", "h1_hk_development_hkd_m",
    "h1_hk_rental_hkd_m", "h1_hotel_hkd_m", "h1_residual_hkd_m",
    "h2_hk_development_forecast_hkd_m", "h2_hk_rental_forecast_hkd_m",
    "h2_hotel_forecast_hkd_m", "h2_residual_forecast_hkd_m",
    "h2_component_forecast_hkd_m", "fy_component_forecast_hkd_m",
    "component_error_pct", "component_ape_pct",
    "development_h2_h1_ratio", "rental_h2_h1_ratio", "hotel_h2_h1_ratio",
    "residual_h2_h1_ratio", "training_years", "training_observations",
    "component_coverage_status", "model_status", "pit_quality",
    "h1_source", "annual_source", "caveat",
]


def h1_report_registry() -> pd.DataFrame:
    """Return the immutable official-report catalogue as a DataFrame."""
    rows = []
    for item in H1_REPORT_REGISTRY_DATA:
        rows.append({
            **item,
            "ticker": "0016.HK",
            "period_type": "interim",
            "document_type": "official_interim_report_pdf",
            "source_role": "primary_issuer_filing",
            "pit_quality": "strict_release_date_observed",
            "parser_status": "catalogued",
            "retrieved_at": None,
            "raw_snapshot": None,
            "caveat": "Six months ended 31 December; official PDF release date is used as the earliest availability date.",
        })
    return pd.DataFrame(rows, columns=REPORT_REGISTRY_COLUMNS)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(value).replace(",", ""))
    if not cleaned or cleaned in {".", "-", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _page_number(text: str, position: int) -> int | None:
    if position < 0:
        return None
    return str(text[:position]).count("\f") + 1


def _match_number(text: str, patterns: Iterable[str], *, flags: int = re.IGNORECASE | re.DOTALL) -> tuple[float | None, str | None, int | None]:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            value = _number(match.group(1))
            if value is not None:
                return value, match.group(0).strip(), match.start()
    return None, None, None


def _table_row_combined_number(text: str, label_pattern: str, *, window: int = 180) -> tuple[float | None, str | None, int | None]:
    """Read the combined revenue value from a six-number segment row.

    SHKP's interim segment tables are extracted by ``pypdf`` as rows shaped
    like ``consolidated revenue, consolidated result, JV revenue, JV result,
    combined revenue, combined result, label``.  The row is deliberately
    parsed only when six adjacent numeric/placeholder tokens are present;
    narrative mentions of a segment do not satisfy this shape.  This keeps
    the component layer from silently turning a comparative or prose number
    into a current-period fact.
    """
    token_pattern = re.compile(r"\([0-9][0-9,]*(?:\.\d+)?\)|[0-9][0-9,]*(?:\.\d+)?|[–—-]")
    for match in re.finditer(label_pattern, text, flags=re.IGNORECASE):
        tail = text[match.end(): match.end() + window]
        tokens = list(token_pattern.finditer(tail))
        if len(tokens) < 6:
            continue
        # Require the first six tokens to be close enough to form one table
        # row.  This rejects prose where unrelated numbers occur later.
        if tokens[5].start() > 120:
            continue
        values: list[float | None] = []
        for token in tokens[:6]:
            raw = token.group(0)
            values.append(None if raw in {"-", "–", "—"} else _number(raw))
        combined = values[4]
        if combined is not None:
            end = match.end() + tokens[5].end()
            return combined, text[match.start():end].replace("\n", " ").strip(), match.start()
    return None, None, None


def _highlight_section(text: str) -> str:
    candidates = list(re.finditer(r"FINANCIAL\s+HIGHLIGHTS", text, flags=re.IGNORECASE))
    valid = [
        candidate
        for candidate in candidates
        if re.search(
            r"For\s+the\s+six\s+months\s+ended",
            text[candidate.start(): candidate.start() + 2_500],
            flags=re.IGNORECASE,
        )
    ]
    # The PDF's table of contents repeats the heading.  The last valid
    # heading before the actual financial-highlights table is the useful one.
    start = max(valid, key=lambda candidate: candidate.start()) if valid else None
    if not start:
        return text[:20_000]
    tail_offset = 200
    end = re.search(r"CORPORATE\s+INFORMATION", text[start.start() + tail_offset:], flags=re.IGNORECASE)
    return text[start.start(): start.start() + tail_offset + end.start()] if end else text[start.start(): start.start() + 20_000]


def _line_number(section: str, pattern: str) -> tuple[float | None, str | None, int | None]:
    match = re.search(pattern, section, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return None, None, None
    value = _number(match.group(1))
    return value, match.group(0).strip(), match.start() if value is not None else None


def _labeled_number(section: str, label_pattern: str, *, window: int = 180) -> tuple[float | None, str | None, int | None]:
    """Read the first current-period number after a label.

    ``pypdf`` extraction is not layout-preserving for several older reports:
    footnotes can be placed on their own line, and the bullet glyph may become
    ``{``.  This helper skips a standalone 1/2/3 footnote token and accepts a
    value on the next line while keeping the evidence excerpt bounded.
    """
    match = re.search(label_pattern, section, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return None, None, None
    tail = section[match.end(): match.end() + window]
    tail = re.sub(r"\(\s*\d+\s*\)", " ", tail)
    for number_match in re.finditer(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?", tail):
        token = number_match.group(0)
        if token in {"1", "2", "3"} and number_match.start() < 60:
            continue
        value = _number(token)
        if value is not None:
            start = match.start()
            end = match.end() + number_match.end()
            return value, section[start:end].replace("\n", " ").strip(), start
    return None, None, None


def _append_fact(
    rows: list[dict[str, Any]],
    report: Mapping[str, Any],
    *,
    metric: str,
    value: float | None,
    unit: str,
    scope: str,
    segment: str,
    source_text: str | None,
    source_pos: int | None,
    source_page_base: int = 1,
    caveat: str,
) -> None:
    if value is None:
        return
    # The source position is relative to either the complete PDF text or a
    # section.  For a section offset, callers pass a synthetic page below; the
    # parser still retains the exact evidence excerpt for audit.
    page = _page_number(source_text or "", source_pos or -1)
    rows.append({
        "fact_id": _stable_id(report["report_id"], scope, segment, metric),
        "ticker": "0016.HK",
        "report_id": report["report_id"],
        "fiscal_label": report["fiscal_label"],
        "fiscal_year_end": report["fiscal_year_end"],
        "period_start": report["period_start"],
        "period_end": report["period_end"],
        "period_type": "interim",
        "scope": scope,
        "segment": segment,
        "metric": metric,
        "value": float(value),
        "unit": unit,
        "currency": "HKD" if unit.startswith("HKD") else None,
        "value_operator": "=",
        "source_page": page,
        "source_url": report["source_url"],
        "release_date": report["release_date"],
        "availability_date": report["release_date"],
        "pit_quality": "strict_release_date_observed",
        "source_method": "official_interim_pdf_text_extract",
        "evidence_excerpt": source_text[source_pos:source_pos + 220].replace("\n", " ").strip() if source_text and source_pos is not None else None,
        "caveat": caveat,
    })


def parse_shkp_h1_report_text(report: Mapping[str, Any], text: str) -> pd.DataFrame:
    """Parse one official interim PDF's extracted English text.

    The parser returns only observed figures.  In particular, it does not
    convert year-on-year percentages into a level and does not treat a missing
    Hong Kong split as zero.
    """
    if not text or not str(text).strip():
        return pd.DataFrame(columns=H1_ACTUAL_COLUMNS)
    full_text = str(text)
    section = _highlight_section(full_text)
    rows: list[dict[str, Any]] = []

    # Financial highlights.  Anchoring to the beginning of the line avoids
    # accidentally picking a comparative number from the narrative below.
    highlight_specs = [
        ("group_revenue", [r"^\s*(?:Group\s+)?Revenue(?:\([^\n)]*\))?\s+([0-9][0-9,]*(?:\.\d+)?)"], "HKD_m", "group", "consolidated"),
        ("reported_profit_attributable", [r"^\s*[—-]\s*Reported(?:\s*\d+)?(?:\([^\n)]*\))?\s+([0-9][0-9,]*(?:\.\d+)?)"], "HKD_m", "group", "consolidated"),
        ("underlying_profit_attributable", [r"^\s*[—-]\s*Underlying(?:\s*\(?\d+\)?)*(?:\([^\n)]*\))?(?:,\s*\([^\n)]*\))?\s+([0-9][0-9,]*(?:\.\d+)?)"], "HKD_m", "group", "consolidated"),
        ("gross_rental_income", [r"^\s*Gross\s+rental\s+income\s*(?:\d+)?\s*(?:\([^\n)]*\))?\s+([0-9][0-9,]*(?:\.\d+)?)"], "HKD_m", "group", "property_rental"),
        ("net_rental_income", [r"^\s*Net\s+rental\s+income\s*(?:\d+)?\s*(?:\([^\n)]*\))?\s+([0-9][0-9,]*(?:\.\d+)?)"], "HKD_m", "group", "property_rental"),
    ]
    label_patterns = {
        "group_revenue": r"(?:Group\s+)?Revenue",
        "reported_profit_attributable": r"Reported",
        "underlying_profit_attributable": r"Underlying",
        "gross_rental_income": r"Gross\s+rental\s+income",
        "net_rental_income": r"Net\s+rental\s+income",
    }
    profit_section = section[: re.search(r"Financial\s+Information\s+per\s+Share", section, flags=re.IGNORECASE).start()] if re.search(r"Financial\s+Information\s+per\s+Share", section, flags=re.IGNORECASE) else section
    for metric, patterns, unit, scope, segment in highlight_specs:
        value, excerpt, pos = _labeled_number(profit_section if metric in {"reported_profit_attributable", "underlying_profit_attributable"} else section, label_patterns[metric])
        _append_fact(
            rows, report, metric=metric, value=value, unit=unit, scope=scope,
            segment=segment, source_text=full_text,
            source_pos=(full_text.find(excerpt) if excerpt else None),
            caveat="Reported in the official six-month financial highlights; rental metrics include joint ventures and associates where the report footnote says so.",
        )

    share_start = re.search(r"Financial\s+Information\s+per\s+Share", section, flags=re.IGNORECASE)
    share_section = section[share_start.start():] if share_start else ""
    for metric, pattern in (
        ("reported_eps", r"^\s*[—-]\s*Reported(?:\s*\d+)?(?:\([^\n)]*\))?\s+([0-9]+(?:\.\d+)?)"),
        ("underlying_eps", r"^\s*[—-]\s*Underlying(?:\s*\(?\d+\)?)*(?:\([^\n)]*\))?(?:,\s*\([^\n)]*\))?\s+([0-9]+(?:\.\d+)?)"),
    ):
        value, excerpt, _ = _labeled_number(share_section, r"Reported" if metric == "reported_eps" else r"Underlying")
        _append_fact(
            rows, report, metric=metric, value=value, unit="HKD_per_share", scope="group",
            segment="consolidated", source_text=full_text,
            source_pos=(full_text.find(excerpt) if excerpt else None),
            caveat="Per-share figure reported in the official six-month financial highlights.",
        )
    value, excerpt, _ = _labeled_number(share_section, r"Interim\s+dividend(?:s)?")
    _append_fact(
        rows, report, metric="interim_dividend", value=value, unit="HKD_per_share", scope="group",
        segment="consolidated", source_text=full_text,
        source_pos=(full_text.find(excerpt) if excerpt else None),
        caveat="Per-share dividend announced for the interim period; payment date is not a recognition date.",
    )

    detail_specs: list[tuple[str, list[str], str, str, str, str]] = [
        (
            "property_sales_revenue", [
                r"Revenue\s+from\s+property\s+sales\s+for\s+the\s+period(?:\s+under\s+review)?[^.]{0,350}?was\s+HK\$\s*([0-9,]+)\s+million",
                r"Revenue\s+from\s+property\s+sales\s+\(including\s+share\s+of\s+joint\s+ventures\)\s+for\s+the\s+six\s+months\s+ended\s+31\s+December\s+20\d{2}\s+was\s+HK\$\s*([0-9,]+)\s+million",
            ], "HKD_m", "group", "property_sales", "Financial-review property-sales revenue includes the Group's share of joint ventures where stated."),
        (
            "property_sales_profit", [
                r"profit\s+generated\s+from\s+property\s+sales\s+(?:reached|totalled|was)\s+HK\$\s*([0-9,]+)\s+million",
                r"profit\s+generated\s+from\s+property\s+sales\s+.*?reached\s+HK\$\s*([0-9,]+)\s+million",
                r"Profit\s+from\s+property\s+sales,\s+inclusive\s+of\s+share\s+of\s+joint\s+ventures,\s+was\s+HK\$\s*([0-9,]+)\s+million",
            ], "HKD_m", "group", "property_sales", "Financial-review property-sales profit; scope follows the wording of the official report."),
        (
            "contracted_sales_attributable", [
                r"Contracted\s+sales\s+during\s+the\s+period[^.]{0,180}?(?:amounted\s+to|reached|totalled)\s+(?:an\s+approximate|approximately|about|over)?\s*HK\$\s*([0-9,]+)\s+million",
            ], "HKD_m", "group", "property_sales", "Attributable contracted-sales flow, not revenue; retained as a separate metric."),
        (
            "hk_rental_revenue", [
                r"gross\s+rental\s+income\s+from\s+(?:its\s+well-diversified,\s+premium\s+assets\s+in\s+)?Hong\s+Kong.{0,220}?(?:to|at)\s+HK\$\s*([0-9,]+)\s+million",
                r"rental\s+revenue\s+of\s+(?:the\s+Group[’']s\s+)?Hong\s+Kong\s+portfolio.{0,220}?(?:to|at)\s+HK\$\s*([0-9,]+)\s+million",
                r"Hong\s+Kong\s+portfolio\s+posted.{0,180}?revenue.{0,100}?to\s+HK\$\s*([0-9,]+)\s+million",
                r"rental\s+revenue\s+and\s+net\s+rental\s+income\s+of\s+property\s+investment\s+in\s+Hong\s+Kong.{0,180}?to\s+HK\$\s*([0-9,]+)\s+million",
                r"rental\s+revenue\s+of\s+property\s+investment\s+in\s+Hong\s+Kong.{0,180}?(?:to|at)\s+HK\$\s*([0-9,]+)\s+million",
            ], "HKD_m", "hong_kong", "property_rental", "HK rental revenue; includes joint ventures and associates where stated."),
        (
            "hk_net_rental_income", [
                r"net\s+rental\s+income\s+from\s+the\s+Group[’']s\s+rental\s+portfolios\s+in\s+Hong\s+Kong.{0,150}?to\s+HK\$\s*([0-9,]+)\s+million",
                r"rental\s+revenue\s+of\s+(?:(?:the\s+)?Group[’']s\s+)?Hong\s+Kong\s+portfolio.{0,220}?net\s+rental\s+income.{0,120}?HK\$\s*([0-9,]+)\s+million",
                r"Hong\s+Kong\s+portfolio\s+posted.{0,180}?net\s+rental\s+income.{0,100}?HK\$\s*([0-9,]+)\s+million",
                r"rental\s+revenue\s+and\s+net\s+rental\s+income\s+of\s+property\s+investment\s+in\s+Hong\s+Kong.{0,180}?to\s+HK\$\s*[0-9,]+\s+million\s+and\s+HK\$\s*([0-9,]+)\s+million",
                r"rental\s+revenue\s+of\s+property\s+investment\s+in\s+Hong\s+Kong.{0,220}?net\s+rental\s+income.{0,120}?(?:to|at)\s+HK\$\s*([0-9,]+)\s+million",
            ], "HKD_m", "hong_kong", "property_rental", "HK net rental income; includes joint ventures and associates where stated."),
        (
            "hk_office_revenue", [
                r"office\s+portfolio\s+(?:recorded\s+a\s+)?revenue.*?(?:to|of)\s+HK\$\s*([0-9,]+)\s+million",
                r"office\s+portfolio\s+generated\s+steady\s+revenue\s+of\s+HK\$\s*([0-9,]+)\s+million",
            ], "HKD_m", "hong_kong", "office", "Office portfolio revenue; not a whole-company office profit measure."),
        (
            "hk_retail_revenue", [
                r"retail\s+portfolio\s+(?:saw\s+a\s+)?revenue.*?(?:to|of)\s+HK\$\s*([0-9,]+)\s+million",
                r"Revenue\s+of\s+the\s+retail\s+portfolio\s+(?:decreased|increased).*?(?:to|of)\s+HK\$\s*([0-9,]+)\s+million",
            ], "HKD_m", "hong_kong", "retail", "Retail portfolio revenue; turnover-rent and concession effects remain embedded."),
        (
            "hk_property_sales_revenue", [
                r"Revenue\s+from\s+property\s+sales\s+\(including\s+share\s+of\s+joint\s+ventures\)\s+in\s+Hong\s+Kong.{0,220}?(?:to|was)\s+HK\$\s*([0-9,]+)\s+million",
                r"comprising\s+revenue\s+of\s+HK\$\s*([0-9,]+)\s+million\s+from\s+Hong\s+Kong",
                r"property\s+sales\s+in\s+Hong\s+Kong\s+for\s+the\s+period\s+reached\s+HK\$\s*([0-9,]+)\s+million",
            ], "HKD_m", "hong_kong", "property_sales", "Hong Kong property-sales revenue including the Group's share of joint ventures where stated."),
        (
            "hk_property_sales_backlog", [
                r"contracted\s+property\s+sales.*?not\s+yet\s+recognized.*?comprising\s+HK\$\s*([0-9,.]+)\s+billion\s+in\s+Hong\s+Kong",
            ], "HKD_m", "hong_kong", "property_sales", "Point-in-time Hong Kong contracted-sales backlog; converted from HKD billion to HKD million."),
    ]
    for metric, patterns, unit, scope, segment, caveat in detail_specs:
        value, excerpt, pos = _match_number(full_text, patterns)
        if value is not None and metric == "hk_property_sales_backlog":
            value *= 1000.0
        _append_fact(
            rows, report, metric=metric, value=value, unit=unit, scope=scope,
            segment=segment, source_text=full_text, source_pos=pos, caveat=caveat,
        )

    # Older reports expose the Hong Kong property rows only in the segment
    # table.  Prefer the table's combined revenue value when the narrative
    # did not provide a precise current-period level; this also prevents a
    # nearby profit sentence from being mistaken for revenue.
    if not any(row["metric"] == "hk_property_sales_revenue" for row in rows):
        value, excerpt, pos = _table_row_combined_number(
            full_text, r"(?:Property\s+sales|Property\s+development)\s+Hong\s+Kong"
        )
        _append_fact(
            rows,
            report,
            metric="hk_property_sales_revenue",
            value=value,
            unit="HKD_m",
            scope="hong_kong",
            segment="property_sales",
            source_text=full_text,
            source_pos=(full_text.find(excerpt) if excerpt else pos),
            caveat="Hong Kong combined property-development revenue from the interim segment-information table; includes the Group's share of joint ventures and associates.",
        )

    if not any(row["metric"] == "hk_rental_revenue" for row in rows):
        value, excerpt, pos = _table_row_combined_number(
            full_text, r"Property\s+rental\s+Hong\s+Kong"
        )
        _append_fact(
            rows,
            report,
            metric="hk_rental_revenue",
            value=value,
            unit="HKD_m",
            scope="hong_kong",
            segment="property_rental",
            source_text=full_text,
            source_pos=(full_text.find(excerpt) if excerpt else pos),
            caveat="Hong Kong combined rental revenue from the interim segment-information table; includes the Group's share of joint ventures and associates.",
        )

    # Hotel revenue is carried in the interim segment-information table even
    # when the financial-review narrative does not print a standalone hotel
    # figure. The fifth revenue value in the six-number row is the combined
    # company + JV/associate amount, matching the annual hotel segment series.
    hotel_value, hotel_excerpt, hotel_pos = _table_row_combined_number(
        full_text, r"Hotel\s+operat(?:ion|ions)"
    )
    _append_fact(
        rows,
        report,
        metric="hotel_revenue",
        value=hotel_value,
        unit="HKD_m",
        scope="group",
        segment="hotel_operations",
        source_text=full_text,
        source_pos=(full_text.find(hotel_excerpt) if hotel_excerpt else hotel_pos),
        caveat="Combined hotel-segment revenue from the interim segment-information table; includes the Group's share of joint ventures and associates.",
    )

    result = pd.DataFrame(rows, columns=H1_ACTUAL_COLUMNS)
    if result.empty:
        return result
    # A malformed PDF extraction should not create duplicate facts.  Keep the
    # first occurrence because the source position is the primary financial
    # review/highlights evidence, and preserve a deterministic order.
    return result.drop_duplicates(subset=["report_id", "scope", "segment", "metric"], keep="first").reset_index(drop=True)


def _pdf_text(payload: bytes) -> str:
    reader = PdfReader(BytesIO(payload))
    text = "\f".join(page.extract_text() or "" for page in reader.pages)
    # A few legacy SHKP PDFs split words at a line-box boundary (``Gr oss``,
    # ``r ental``, ``Shar e``).  These are extraction artefacts, not source
    # spelling, and otherwise make the official highlights disappear from the
    # panel.  Keep the replacements narrow rather than deleting all spaces
    # between letters.
    replacements = {
        "Gr oss": "Gross", "r ental": "rental", "Pr ofit": "Profit",
        "shar eholders": "shareholders", "Shar e": "Share", "ear nings": "earnings",
        "Underly ing": "Underlying", "Compan y": "Company", "Rev enue": "Revenue",
        "Fin ancial": "Financial", "Inf ormation": "Information",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def fetch_shkp_h1_reports(*, timeout: float = 45.0, request_delay: float = 0.15) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Fetch and parse the official interim PDF catalogue.

    Returns ``(registry, panel, raw_snapshot_paths)``.  A failed report is
    retained in the registry with ``parser_status=fetch_failed``; the builder
    never fills its facts from a different source silently.
    """
    registry = h1_report_registry().copy()
    rows: list[pd.DataFrame] = []
    raw_paths: list[str] = []
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    for idx, item in enumerate(H1_REPORT_REGISTRY_DATA):
        try:
            response = session.get(item["source_url"], timeout=timeout)
            response.raise_for_status()
            payload = response.content
            raw_path = save_raw_snapshot(
                "shkp_h1_interim_report_pdf", payload, file_ext="pdf",
                source_url=item["source_url"], run_id=f"shkp-h1-{item['report_id']}",
            )
            raw_paths.append(str(raw_path))
            registry.loc[idx, "raw_snapshot"] = str(raw_path)
            registry.loc[idx, "retrieved_at"] = datetime.now(timezone.utc).isoformat()
            text = _pdf_text(payload)
            parsed = parse_shkp_h1_report_text(item, text)
            if parsed.empty:
                registry.loc[idx, "parser_status"] = "parsed_zero_facts"
            else:
                registry.loc[idx, "parser_status"] = "parsed"
                rows.append(parsed)
        except Exception as exc:  # preserve failure in the audit registry
            registry.loc[idx, "parser_status"] = "fetch_failed"
            registry.loc[idx, "caveat"] = f"Official fetch/parser failed: {type(exc).__name__}: {exc}"
        if request_delay and idx < len(H1_REPORT_REGISTRY_DATA) - 1:
            import time
            time.sleep(request_delay)
    panel = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=H1_ACTUAL_COLUMNS)
    return registry, panel.reindex(columns=H1_ACTUAL_COLUMNS), raw_paths


def _annual_actuals() -> pd.DataFrame:
    """Load annual values for the recognition bridge.

    Official segment history is preferred for HK property sales.  Consolidated
    revenue/profit falls back to the source-selected sibling actuals, with the
    caveat preserved because historical announcement timestamps are absent.
    """
    frames: list[pd.DataFrame] = []
    disclosed = load_latest_normalized("shkp_financial_model_disclosed_facts")
    if not disclosed.empty:
        annual = disclosed.loc[disclosed.get("period_type", pd.Series(dtype=str)).eq("annual")].copy()
        for metric in ("group_revenue", "underlying_profit_attributable", "profit_attributable_to_company_shareholders"):
            subset = annual.loc[annual["metric"].eq(metric), ["period_end", "value", "unit", "currency", "available_at", "source_url"]].copy()
            subset["model_metric"] = metric
            subset["annual_source"] = "official_financial_summary_curated"
            frames.append(subset)
    actuals = load_latest_normalized("shkp_financial_model_financial_data_actuals")
    if not actuals.empty:
        annual = actuals.loc[actuals.get("period_type", pd.Series(dtype=str)).eq("annual")].copy()
        mappings = {
            "akshare_revenue": "group_revenue",
            "net_income_attributable": "profit_attributable_to_company_shareholders",
        }
        for raw_metric, model_metric in mappings.items():
            subset = annual.loc[annual["metric"].eq(raw_metric), ["period_end", "value", "unit", "currency", "available_at", "source", "source_priority"]].copy()
            if subset.empty:
                continue
            # Sibling financial-data income-statement amounts are absolute HKD
            # when ``unit=currency``.  Normalize them to HKD millions before
            # the H1/FY ratio is calculated; otherwise ratios become 1e-6 and
            # the bridge silently produces a false 100% H2 share.
            absolute_currency = (
                subset["unit"].astype(str).str.lower().eq("currency")
                & subset["currency"].astype(str).str.upper().eq("HKD")
            )
            subset.loc[absolute_currency, "value"] = pd.to_numeric(
                subset.loc[absolute_currency, "value"], errors="coerce"
            ) / 1_000_000.0
            subset.loc[absolute_currency, "unit"] = "HKD_m"
            # Keep one source-selected row per year; this is a recognition
            # bridge fallback, not a claim that AkShare's fetch time is PIT.
            subset["period_end"] = pd.to_datetime(subset["period_end"], errors="coerce").dt.strftime("%Y-%m-%d")
            subset = subset.sort_values(["period_end", "source_priority"], na_position="last").drop_duplicates("period_end", keep="first")
            subset["model_metric"] = model_metric
            subset["annual_source"] = "sibling_financial_data_source_selected_non_pit"
            frames.append(subset)
    if not frames:
        return pd.DataFrame(columns=["period_end", "value", "unit", "currency", "model_metric", "annual_source", "available_at", "source_url"])
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined["period_end"] = pd.to_datetime(combined["period_end"], errors="coerce").dt.strftime("%Y-%m-%d")
    # Prefer official curated facts over fallback rows for duplicated year/metric.
    combined["source_rank"] = combined["annual_source"].eq("official_financial_summary_curated").astype(int)
    return combined.sort_values(["period_end", "model_metric", "source_rank"], ascending=[True, True, False]).drop_duplicates(["period_end", "model_metric"], keep="first").drop(columns=["source_rank"], errors="ignore")


def _fy_label(year: int) -> str:
    return f"FY{year - 1}/{str(year)[-2:]}"


def build_shkp_h1_to_fy_bridge(panel: pd.DataFrame, annual: pd.DataFrame | None = None) -> pd.DataFrame:
    """Build observed H1/H2/FY recognition rows without annualising H1."""
    if panel is None or panel.empty:
        return pd.DataFrame(columns=H1_BRIDGE_COLUMNS)
    annual = annual if annual is not None else _annual_actuals()
    h1_map = {
        "group_revenue": "group_revenue",
        "reported_profit_attributable": "profit_attributable_to_company_shareholders",
        "hk_property_sales_revenue": "hk_property_sales_revenue",
    }
    annual_hk = load_latest_normalized("shkp_financial_model_hk_property_sales_segment_history")
    annual_rows: list[dict[str, Any]] = []
    if annual is not None and not annual.empty:
        for _, row in annual.iterrows():
            annual_rows.append({
                "fiscal_year_end": pd.to_datetime(row.get("period_end"), errors="coerce").year if pd.notna(pd.to_datetime(row.get("period_end"), errors="coerce")) else None,
                "metric": row.get("model_metric"), "value": row.get("value"), "unit": row.get("unit"), "currency": row.get("currency"),
                "annual_source": row.get("annual_source"), "annual_source_url": row.get("source_url"),
            })
    if annual_hk is not None and not annual_hk.empty:
        for _, row in annual_hk.iterrows():
            annual_rows.append({
                "fiscal_year_end": int(row["fiscal_year_end"]), "metric": "hk_property_sales_revenue", "value": row["revenue_hkd_m"], "unit": "HKD_m", "currency": "HKD",
                "annual_source": "official_annual_report_segment_history", "annual_source_url": None,
            })
    annual_frame = pd.DataFrame(annual_rows)
    rows: list[dict[str, Any]] = []
    for metric, annual_metric in h1_map.items():
        source = panel.loc[panel["metric"].eq(metric)].copy()
        if source.empty:
            continue
        source["fiscal_year_end"] = source["fiscal_year_end"].astype(int)
        for year, h1_group in source.groupby("fiscal_year_end"):
            h1_row = h1_group.iloc[0]
            fy = annual_frame.loc[(annual_frame["fiscal_year_end"].eq(int(year))) & (annual_frame["metric"].eq(annual_metric))]
            if fy.empty:
                rows.append({
                    "fiscal_year_end": year, "fiscal_label": h1_row["fiscal_label"], "metric": metric,
                    "unit": h1_row["unit"], "currency": h1_row["currency"], "h1_actual": h1_row["value"],
                    "h2_actual": None, "full_year_actual": None, "h1_share_pct": None, "h2_share_pct": None,
                    "scope": h1_row["scope"], "h1_source": h1_row["source_url"], "full_year_source": None,
                    "pit_quality": "h1_strict_filing_full_year_missing", "status": "h1_only", "caveat": "No aligned annual actual in current repository.",
                })
                continue
            annual_row = fy.iloc[0]
            full_year = float(annual_row["value"]) if pd.notna(annual_row["value"]) else None
            h1_value = float(h1_row["value"]) if pd.notna(h1_row["value"]) else None
            h2_value = full_year - h1_value if full_year is not None and h1_value is not None else None
            h1_share = h1_value / full_year * 100 if full_year not in (None, 0) and h1_value is not None else None
            h2_share = h2_value / full_year * 100 if full_year not in (None, 0) and h2_value is not None else None
            annual_pit = "official_annual_source" if annual_row.get("annual_source") == "official_annual_report_segment_history" or annual_row.get("annual_source") == "official_financial_summary_curated" else "non_pit_fallback_annual_source"
            rows.append({
                "fiscal_year_end": year, "fiscal_label": h1_row["fiscal_label"], "metric": metric,
                "unit": h1_row["unit"], "currency": h1_row["currency"], "h1_actual": h1_value,
                "h2_actual": h2_value, "full_year_actual": full_year, "h1_share_pct": h1_share, "h2_share_pct": h2_share,
                "scope": h1_row["scope"], "h1_source": h1_row["source_url"], "full_year_source": annual_row.get("annual_source_url"),
                "pit_quality": "h1_strict_filing_annual_source_" + annual_pit, "status": "complete", "caveat": "H2 is arithmetic FY minus H1; it is not a separately filed half-year observation.",
            })
    return pd.DataFrame(rows, columns=H1_BRIDGE_COLUMNS).sort_values(["metric", "fiscal_year_end"], ignore_index=True) if rows else pd.DataFrame(columns=H1_BRIDGE_COLUMNS)


def build_shkp_h1_actual_vs_nowcast(panel: pd.DataFrame, annual: pd.DataFrame | None = None, *, lookback: int = 3) -> pd.DataFrame:
    """Run a descriptive expanding H1-to-FY holdout backtest.

    Two baselines are reported: simple H1 annualisation and a prior-share
    forecast based only on earlier fiscal years.  The latter is PIT-safe with
    respect to the panel's release dates; annual fallback values are explicitly
    marked non-PIT when their original publication date is unavailable.
    """
    if panel is None or panel.empty:
        return pd.DataFrame(columns=H1_BACKTEST_COLUMNS)
    annual = annual if annual is not None else _annual_actuals()
    bridge = build_shkp_h1_to_fy_bridge(panel, annual)
    if bridge.empty:
        return pd.DataFrame(columns=H1_BACKTEST_COLUMNS)
    rows: list[dict[str, Any]] = []
    for metric, group in bridge.groupby("metric"):
        group = group.sort_values("fiscal_year_end")
        for _, target in group.iterrows():
            if target["status"] != "complete":
                continue
            year = int(target["fiscal_year_end"])
            earlier = group.loc[(group["fiscal_year_end"] < year) & group["h1_share_pct"].notna()].tail(lookback)
            shares = earlier["h1_share_pct"].astype(float)
            median_share = float(shares.median()) if not shares.empty else None
            h1 = float(target["h1_actual"])
            fy = float(target["full_year_actual"])
            annualized = h1 * 2.0
            prior_forecast = h1 / (median_share / 100.0) if median_share and median_share > 0 else None
            rows.append({
                "target_fiscal_year": year, "fiscal_label": target["fiscal_label"],
                "period_end": target["fiscal_year_end"], "metric": metric,
                "unit": target["unit"], "currency": target["currency"],
                "h1_actual": h1, "full_year_actual": fy,
                "training_years": ",".join(str(int(v)) for v in earlier["fiscal_year_end"].tolist()),
                "training_observations": int(len(earlier)), "h1_share_median": median_share,
                "h1_annualized_forecast": annualized, "prior_share_forecast": prior_forecast,
                "h1_annualized_error_pct": (annualized / fy - 1.0) * 100.0 if fy else None,
                "prior_share_error_pct": (prior_forecast / fy - 1.0) * 100.0 if prior_forecast is not None and fy else None,
                "h1_annualized_ape_pct": abs(annualized / fy - 1.0) * 100.0 if fy else None,
                "prior_share_ape_pct": abs(prior_forecast / fy - 1.0) * 100.0 if prior_forecast is not None and fy else None,
                "model_status": "valid_prior_share_holdout" if median_share is not None else "annualization_only_insufficient_training",
                "pit_quality": target["pit_quality"], "actual_source": target["full_year_source"],
                "h1_source": target["h1_source"],
                "caveat": "This is a small descriptive recognition backtest, not a full earnings forecast; annual fallback sources may not preserve original release vintages.",
            })
    return pd.DataFrame(rows, columns=H1_BACKTEST_COLUMNS).sort_values(["metric", "target_fiscal_year"], ignore_index=True)


def _component_annual_history(annual: pd.DataFrame | None = None) -> pd.DataFrame:
    """Assemble annual component anchors for the H2 recognition model.

    The component model deliberately uses the Hong Kong development and
    rental series plus the combined hotel series.  Everything left after
    those three components is an explicit residual (Mainland, telecom,
    infrastructure, other businesses and scope differences), rather than an
    unlabelled balancing number hidden inside the forecast.
    """
    rows: dict[int, dict[str, Any]] = {}
    if annual is not None and not annual.empty:
        frame = annual.copy()
        frame["fiscal_year_end"] = pd.to_datetime(frame.get("period_end"), errors="coerce").dt.year
        group = frame.loc[frame.get("model_metric", pd.Series(dtype=str)).eq("group_revenue")]
        for _, row in group.iterrows():
            year = int(row["fiscal_year_end"])
            rows.setdefault(year, {})["group_revenue_hkd_m"] = float(row["value"])
            rows[year]["group_source"] = row.get("annual_source") or row.get("source_url")

    # The HK development segment history is already audited against annual
    # reports and is the same combined (company + JV/associate) scope used by
    # the H1 Hong Kong property-sales fact.
    hk_development = load_latest_normalized("shkp_financial_model_hk_property_sales_segment_history")
    if not hk_development.empty:
        for _, row in hk_development.iterrows():
            year = int(row["fiscal_year_end"])
            rows.setdefault(year, {})["hk_development_revenue_hkd_m"] = float(row["revenue_hkd_m"])
            rows[year]["hk_development_source"] = "official_annual_report_hk_segment_history"

    # Reuse the commercial module's reviewed annual HK rental series rather
    # than treating a consolidated group rental line as Hong Kong rental.
    from .shkp_commercial_model import SHKP_HK_RENTAL_REVENUE_HKD_M

    for year, value in SHKP_HK_RENTAL_REVENUE_HKD_M.items():
        rows.setdefault(int(year), {})["hk_rental_revenue_hkd_m"] = float(value)
        rows[int(year)]["hk_rental_source"] = "official_annual_report_hk_rental_series"

    hotel = load_latest_normalized("shkp_hotel_segment_series")
    if not hotel.empty:
        for _, row in hotel.iterrows():
            year = int(row["fiscal_year_end"])
            rows.setdefault(year, {})["hotel_revenue_hkd_m"] = float(row["revenue_combined_hkd_m"])
            rows[year]["hotel_source"] = "official_annual_report_hotel_segment_series"

    output: list[dict[str, Any]] = []
    for year in sorted(rows):
        row = rows[year]
        group_value = row.get("group_revenue_hkd_m")
        dev_value = row.get("hk_development_revenue_hkd_m")
        rental_value = row.get("hk_rental_revenue_hkd_m")
        hotel_value = row.get("hotel_revenue_hkd_m")
        components = [group_value, dev_value, rental_value, hotel_value]
        residual = (
            float(group_value) - float(dev_value) - float(rental_value) - float(hotel_value)
            if all(value is not None for value in components)
            else None
        )
        status = "complete" if residual is not None else "partial_component_history"
        output.append({
            "fiscal_year_end": year,
            "fiscal_label": _fy_label(year),
            "group_revenue_hkd_m": group_value,
            "hk_development_revenue_hkd_m": dev_value,
            "hk_rental_revenue_hkd_m": rental_value,
            "hotel_revenue_hkd_m": hotel_value,
            "residual_revenue_hkd_m": residual,
            "source_status": status,
            "caveat": (
                "Residual = consolidated group revenue minus Hong Kong development, Hong Kong rental and hotel segment revenue. "
                "The named components include JV/associate shares; the residual therefore carries Mainland, other businesses and scope differences."
            ),
        })
    return pd.DataFrame(output, columns=H1_COMPONENT_ANNUAL_COLUMNS)


def _component_h1_snapshot(panel: pd.DataFrame, year: int) -> dict[str, Any]:
    """Return the current H1 component values for one fiscal year."""
    frame = panel.loc[panel["fiscal_year_end"].astype(int).eq(int(year))].copy()

    def value(metric: str) -> float | None:
        subset = frame.loc[frame["metric"].eq(metric)]
        if subset.empty or pd.isna(subset.iloc[0]["value"]):
            return None
        return float(subset.iloc[0]["value"])

    group_value = value("group_revenue")
    development = value("hk_property_sales_revenue")
    rental = value("hk_rental_revenue")
    hotel = value("hotel_revenue")
    known = [v for v in (development, rental, hotel) if v is not None]
    residual = float(group_value - sum(known)) if group_value is not None and len(known) == 3 else None
    return {
        "group": group_value,
        "development": development,
        "rental": rental,
        "hotel": hotel,
        "residual": residual,
        "development_observed": development is not None,
        "rental_observed": rental is not None,
        "hotel_observed": hotel is not None,
    }


def build_shkp_h1_component_actual_vs_nowcast(
    panel: pd.DataFrame,
    annual: pd.DataFrame | None = None,
    *,
    component_annual: pd.DataFrame | None = None,
    lookback: int = 3,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Backtest a component-based H1-to-FY revenue recognition bridge.

    This is intentionally a small, transparent model rather than a claim of
    project-level precision:

    ``FY = H1 actual + H2 development + H2 HK rental + H2 hotel + H2 residual``

    Each H2 component is the current H1 component multiplied by the median
    H2/H1 ratio from up to ``lookback`` strictly earlier fiscal years.  The
    residual is explicit and absorbs Mainland, telecom/infrastructure, other
    businesses and unavoidable JV/scope differences.  A row is scored only
    when all three named H1 components and enough historical ratios exist.
    """
    empty_backtest = pd.DataFrame(columns=H1_COMPONENT_BACKTEST_COLUMNS)
    empty_annual = pd.DataFrame(columns=H1_COMPONENT_ANNUAL_COLUMNS)
    if panel is None or panel.empty:
        return empty_backtest, empty_annual
    annual = annual if annual is not None else _annual_actuals()
    component_annual = component_annual if component_annual is not None else _component_annual_history(annual)
    if component_annual is None or component_annual.empty:
        return empty_backtest, component_annual if component_annual is not None else empty_annual

    annual_index = component_annual.set_index("fiscal_year_end")
    group_bridge = build_shkp_h1_to_fy_bridge(panel, annual)
    group_bridge = group_bridge.loc[group_bridge["metric"].eq("group_revenue")].copy()
    if group_bridge.empty:
        return empty_backtest, component_annual

    component_names = ("development", "rental", "hotel", "residual")
    annual_columns = {
        "development": "hk_development_revenue_hkd_m",
        "rental": "hk_rental_revenue_hkd_m",
        "hotel": "hotel_revenue_hkd_m",
        "residual": "residual_revenue_hkd_m",
    }
    rows: list[dict[str, Any]] = []
    for _, target in group_bridge.sort_values("fiscal_year_end").iterrows():
        year = int(target["fiscal_year_end"])
        h1 = _component_h1_snapshot(panel, year)
        if h1["group"] is None:
            continue
        ratios: dict[str, float | None] = {}
        ratio_years: dict[str, list[int]] = {}
        for component in component_names:
            observations: list[tuple[int, float]] = []
            annual_column = annual_columns[component]
            for prior_year in sorted(int(v) for v in annual_index.index if int(v) < year):
                prior_h1 = _component_h1_snapshot(panel, prior_year).get(component)
                annual_value = annual_index.loc[prior_year].get(annual_column)
                if prior_h1 is None or pd.isna(annual_value) or float(prior_h1) <= 0:
                    continue
                ratio = (float(annual_value) - float(prior_h1)) / float(prior_h1)
                if pd.notna(ratio) and abs(float(ratio)) < 20:
                    observations.append((prior_year, float(ratio)))
            observations = observations[-lookback:]
            ratio_years[component] = [item[0] for item in observations]
            ratios[component] = float(pd.Series([item[1] for item in observations]).median()) if observations else None

        component_forecasts: dict[str, float | None] = {}
        for component in component_names:
            h1_value = h1.get(component)
            ratio = ratios[component]
            component_forecasts[component] = float(h1_value) * ratio if h1_value is not None and ratio is not None else None

        required = ("development", "rental", "hotel", "residual")
        complete = all(component_forecasts[name] is not None for name in required)
        training_union = sorted({year_value for values in ratio_years.values() for year_value in values})
        h2_forecast = sum(float(component_forecasts[name]) for name in required) if complete else None
        fy_forecast = float(h1["group"] + h2_forecast) if h2_forecast is not None else None
        fy_actual = float(target["full_year_actual"]) if target["status"] == "complete" and pd.notna(target["full_year_actual"]) else None
        error_pct = (fy_forecast / fy_actual - 1.0) * 100.0 if fy_forecast is not None and fy_actual else None
        rows.append({
            "target_fiscal_year": year,
            "fiscal_label": target["fiscal_label"],
            "period_end": target["fiscal_year_end"],
            "target_metric": "group_revenue",
            "h1_group_revenue_hkd_m": h1["group"],
            "full_year_group_revenue_hkd_m": fy_actual,
            "h2_group_revenue_actual_hkd_m": float(target["h2_actual"]) if target["status"] == "complete" else None,
            "h1_hk_development_hkd_m": h1["development"],
            "h1_hk_rental_hkd_m": h1["rental"],
            "h1_hotel_hkd_m": h1["hotel"],
            "h1_residual_hkd_m": h1["residual"],
            "h2_hk_development_forecast_hkd_m": component_forecasts["development"],
            "h2_hk_rental_forecast_hkd_m": component_forecasts["rental"],
            "h2_hotel_forecast_hkd_m": component_forecasts["hotel"],
            "h2_residual_forecast_hkd_m": component_forecasts["residual"],
            "h2_component_forecast_hkd_m": h2_forecast,
            "fy_component_forecast_hkd_m": fy_forecast,
            "component_error_pct": error_pct,
            "component_ape_pct": abs(error_pct) if error_pct is not None else None,
            "development_h2_h1_ratio": ratios["development"],
            "rental_h2_h1_ratio": ratios["rental"],
            "hotel_h2_h1_ratio": ratios["hotel"],
            "residual_h2_h1_ratio": ratios["residual"],
            "training_years": ",".join(str(value) for value in training_union),
            "training_observations": len(training_union),
            "component_coverage_status": "all_components_observed" if all(h1.get(f"{name}_observed", False) for name in ("development", "rental", "hotel")) else "missing_named_component",
            "model_status": "valid_holdout" if complete and fy_actual is not None else "valid_current_h1_only" if complete else "insufficient_component_coverage",
            "pit_quality": target["pit_quality"],
            "h1_source": target["h1_source"],
            "annual_source": target["full_year_source"],
            "caveat": (
                "Component H2 is a prior-ratio recognition bridge, not a project-level handover forecast. "
                "Residual explicitly absorbs Mainland, telecom/infrastructure, other businesses and JV/scope differences. "
                "Training years are strictly earlier than the target fiscal year."
            ),
        })
    return pd.DataFrame(rows, columns=H1_COMPONENT_BACKTEST_COLUMNS), component_annual


def run_shkp_h1_backtest(*, timeout: float = 45.0, request_delay: float = 0.15, use_cached_text: bool = False) -> dict[str, Any]:
    """Fetch official reports and persist registry, panel, bridge and backtest."""
    registry, panel, raw_paths = fetch_shkp_h1_reports(timeout=timeout, request_delay=request_delay)
    annual = _annual_actuals()
    bridge = build_shkp_h1_to_fy_bridge(panel, annual)
    backtest = build_shkp_h1_actual_vs_nowcast(panel, annual)
    component_backtest, component_annual = build_shkp_h1_component_actual_vs_nowcast(panel, annual)
    run_id = f"shkp-h1-{uuid.uuid4()}"
    lineage = {
        "lineage_type": "shkp_official_h1_backtest",
        "source_urls": [str(v) for v in registry["source_url"].tolist()],
        "raw_snapshots": raw_paths,
        "h1_report_count": int(len(registry)),
        "h1_fact_count": int(len(panel)),
        "annual_source_note": "Consolidated annual fallback may originate from sibling financial-data without original announcement timestamps; official HK property-sales segment history is preferred where available.",
        "pit_contract": "H1 availability equals issuer interim-report release date; no facts are shifted to the period end for PIT use.",
    }
    outputs = {
        REPORT_REGISTRY_DATASET: save_normalized_dataset(REPORT_REGISTRY_DATASET, registry, run_id=run_id, raw_snapshots=raw_paths, source_urls=registry["source_url"].tolist(), lineage_metadata=lineage),
        H1_ACTUAL_DATASET: save_normalized_dataset(H1_ACTUAL_DATASET, panel, run_id=run_id, raw_snapshots=raw_paths, source_urls=registry["source_url"].tolist(), lineage_metadata=lineage),
        H1_BRIDGE_DATASET: save_normalized_dataset(H1_BRIDGE_DATASET, bridge, run_id=run_id, raw_snapshots=raw_paths, source_urls=registry["source_url"].tolist(), lineage_metadata=lineage),
        H1_BACKTEST_DATASET: save_normalized_dataset(H1_BACKTEST_DATASET, backtest, run_id=run_id, raw_snapshots=raw_paths, source_urls=registry["source_url"].tolist(), lineage_metadata=lineage),
        H1_COMPONENT_ANNUAL_DATASET: save_normalized_dataset(H1_COMPONENT_ANNUAL_DATASET, component_annual, run_id=run_id, raw_snapshots=raw_paths, source_urls=registry["source_url"].tolist(), lineage_metadata={**lineage, "contract_dataset": H1_COMPONENT_ANNUAL_DATASET}),
        H1_COMPONENT_BACKTEST_DATASET: save_normalized_dataset(H1_COMPONENT_BACKTEST_DATASET, component_backtest, run_id=run_id, raw_snapshots=raw_paths, source_urls=registry["source_url"].tolist(), lineage_metadata={**lineage, "contract_dataset": H1_COMPONENT_BACKTEST_DATASET}),
    }
    return {
        "run_id": run_id, "registry_rows": int(len(registry)), "parsed_reports": int(registry["parser_status"].eq("parsed").sum()),
        "panel_rows": int(len(panel)), "bridge_rows": int(len(bridge)), "backtest_rows": int(len(backtest)),
        "component_annual_rows": int(len(component_annual)), "component_backtest_rows": int(len(component_backtest)),
        "outputs": outputs,
    }
