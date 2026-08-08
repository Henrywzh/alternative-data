"""Primary-issuer financial and operating drivers from Cninfo reports.

The monthly operating-data collector already uses Cninfo PDFs.  This module
adds a smaller, explicitly curated report registry for the six mainland
listed airlines and extracts the comparable fields needed for a long/short
model.  It intentionally keeps the report date and page number on every row:
the resulting layer is a primary-source evidence layer, not a provider
history without announcement dates.

The parser is conservative.  It writes a blank when a report uses a wording
or table layout that is not safely recognized.  Derived RASK/CASK/fuel-per-ASK
rows are marked ``calculation_method=derived`` and never presented as issuer-
reported figures.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pdfplumber
import requests

from ..config import AIRLINE_REPORTS_DIR, DEFAULT_HEADERS, DEFAULT_TIMEOUT, NORMALIZED_DIR


@dataclass(frozen=True)
class ReportSpec:
    report_id: str
    symbol: str
    ticker: str
    company: str
    report_type: str
    statement_period: str
    period_start: str
    period_end: str
    announcement_date: str
    source_url: str
    financial_scale_to_rmb_million: float
    cost_scale_to_rmb_million: float


REPORTS: tuple[ReportSpec, ...] = (
    ReportSpec(
        "601111_2025_fy", "601111", "0753.HK / 601111.SH", "Air China",
        "annual", "FY2025", "2025-01-01", "2025-12-31", "2026-03-27",
        "https://static.cninfo.com.cn/finalpage/2026-03-27/1225039287.PDF", 1 / 1000, 1 / 1000,
    ),
    ReportSpec(
        "601111_2025_h1", "601111", "0753.HK / 601111.SH", "Air China",
        "interim", "1H2025", "2025-01-01", "2025-06-30", "2025-08-29",
        "https://static.cninfo.com.cn/finalpage/2025-08-29/1224611848.PDF", 1 / 1000, 1 / 1000,
    ),
    ReportSpec(
        "600029_2025_fy", "600029", "01055.HK / 600029.SH", "China Southern Airlines",
        "annual", "FY2025", "2025-01-01", "2025-12-31", "2026-03-31",
        "https://static.cninfo.com.cn/finalpage/2026-03-31/1225063223.PDF", 1, 1,
    ),
    ReportSpec(
        "600029_2025_h1", "600029", "01055.HK / 600029.SH", "China Southern Airlines",
        "interim", "1H2025", "2025-01-01", "2025-06-30", "2025-08-29",
        "https://static.cninfo.com.cn/finalpage/2025-08-29/1224612089.PDF", 1, 1,
    ),
    ReportSpec(
        "600115_2025_fy", "600115", "0670.HK / 600115.SH", "China Eastern Airlines",
        "annual", "FY2025", "2025-01-01", "2025-12-31", "2026-03-31",
        "https://static.cninfo.com.cn/finalpage/2026-03-31/1225064857.PDF", 1, 1,
    ),
    ReportSpec(
        "600115_2025_h1", "600115", "0670.HK / 600115.SH", "China Eastern Airlines",
        "interim", "1H2025", "2025-01-01", "2025-06-30", "2025-08-30",
        "https://static.cninfo.com.cn/finalpage/2025-08-30/1224626126.PDF", 1, 1,
    ),
    ReportSpec(
        "601021_2025_fy", "601021", "601021.SH", "Spring Airlines",
        "annual", "FY2025", "2025-01-01", "2025-12-31", "2026-04-11",
        "https://static.cninfo.com.cn/finalpage/2026-04-11/1225093115.PDF", 1 / 1_000_000, 1 / 1_000_000,
    ),
    ReportSpec(
        "601021_2025_h1", "601021", "601021.SH", "Spring Airlines",
        "interim", "1H2025", "2025-01-01", "2025-06-30", "2025-08-29",
        "https://static.cninfo.com.cn/finalpage/2025-08-29/1224612122.PDF", 1 / 1_000_000, 1 / 1_000_000,
    ),
    ReportSpec(
        "600221_2025_fy", "600221", "600221.SH", "Hainan Airlines Holdings",
        "annual", "FY2025", "2025-01-01", "2025-12-31", "2026-04-18",
        "https://static.cninfo.com.cn/finalpage/2026-04-18/1225119605.PDF", 1 / 1000, 1 / 1000,
    ),
    ReportSpec(
        "600221_2025_h1", "600221", "600221.SH", "Hainan Airlines Holdings",
        "interim", "1H2025", "2025-01-01", "2025-06-30", "2025-08-30",
        "https://static.cninfo.com.cn/finalpage/2025-08-30/1224624045.PDF", 1 / 1000, 1 / 1000,
    ),
    ReportSpec(
        "603885_2025_fy", "603885", "603885.SH", "Juneyao Airlines",
        "annual", "FY2025", "2025-01-01", "2025-12-31", "2026-04-23",
        "https://static.cninfo.com.cn/finalpage/2026-04-23/1225151299.PDF", 1 / 1_000_000, 1 / 100,
    ),
    ReportSpec(
        "603885_2025_h1", "603885", "603885.SH", "Juneyao Airlines",
        "interim", "1H2025", "2025-01-01", "2025-06-30", "2025-08-23",
        "https://static.cninfo.com.cn/finalpage/2025-08-23/1224558764.PDF", 1 / 1_000_000, 1 / 100,
    ),
)

REPORT_COLUMNS = [
    "dataset_id", "report_id", "ticker", "company", "report_type", "statement_period",
    "period_start", "period_end", "announcement_date", "source_quality", "source_url",
    "raw_snapshot_path", "retrieved_at", "parse_status", "parse_note",
]

DRIVER_COLUMNS = [
    "dataset_id", "report_id", "ticker", "company", "report_type", "statement_period",
    "period_end", "announced_at", "metric", "value_native", "native_unit", "native_currency",
    "value_usd", "usd_unit", "fx_pair", "fx_observation_date", "fx_value", "metric_scope",
    "calculation_method", "source_quality", "source_url", "source_page", "source_note",
    "retrieved_at",
]


# A small set of report-specific table anchors supplements the generic PDF
# parser.  These are not estimates: each value is copied from the issuer's
# operating/cost table at the cited PDF page.  The anchors are deliberately
# limited to the six 1H2025 reports where the layouts put explanatory prose
# next to the operating tables and a first-number parser can silently select
# the wrong value.  Keeping the table anchors here makes the exception
# auditable and prevents a disclosure gap from being filled by a model output.
OPERATING_OVERRIDES: dict[str, tuple[tuple[str, float, str, int, str], ...]] = {
    "601111_2025_fy": (
        ("passenger_revenue", 154_855.779, "RMB million", 16, "Air China product-revenue table: aviation passenger revenue."),
        ("cargo_revenue", 7_778.380, "RMB million", 16, "Air China product-revenue table: aviation cargo and mail revenue."),
        ("cash_and_cash_equivalents", 14_295.268, "RMB million", 85, "Air China consolidated cash-flow statement: year-end cash and cash equivalents; source narrative also states RMB14.295bn."),
        ("total_liabilities", 303_815.731, "RMB million", 78, "Air China consolidated balance sheet: total liabilities."),
        ("interest_bearing_debt", 228_320.0, "RMB million", 20, "Air China management discussion: current and non-current interest-bearing debt of RMB662.60bn and RMB1,620.60bn, summed to RMB228.320bn."),
        ("capex_cash_paid", 17_561.276, "RMB million", 84, "Air China consolidated cash-flow statement: cash paid for property, plant and equipment and other long-term assets."),
    ),
    "601111_2025_h1": (
        ("passenger_load_factor_pct", 80.72, "%", 12, "Air China operating table: group passenger load factor."),
        ("fuel_cost", 24_327.485, "RMB million", 15, "Air China cost-analysis table: aviation fuel cost."),
        ("passenger_revenue", 73_196.376, "RMB million", 15, "Air China product-revenue table: aviation passenger revenue."),
        ("cargo_revenue", 3_577.468, "RMB million", 15, "Air China product-revenue table: aviation cargo and mail revenue."),
        ("cash_and_cash_equivalents", 25_331.0, "RMB million", 16, "Air China management discussion: group cash and cash equivalents at 2025-06-30, reported as RMB253.31亿元 (RMB25.331bn)."),
        ("total_liabilities", 309_309.0, "RMB million", 16, "Air China management discussion: group total liabilities at 2025-06-30, reported as RMB3,093.09亿元 (RMB309.309bn)."),
        ("interest_bearing_debt", 236_179.0, "RMB million", 16, "Air China management discussion: current and non-current interest-bearing debt of RMB766.96bn and RMB1,594.83bn, summed to RMB236.179bn."),
    ),
    "600029_2025_h1": (
        ("rpk", 157_986.19, "million passenger-km", 14, "China Southern operating table: group RPK total."),
        ("ask", 184_837.28, "million seat-km", 15, "China Southern operating table: group ASK total."),
        ("passengers", 83.27982, "million passengers", 14, "China Southern operating table: group passengers, converted from thousand."),
        ("passenger_load_factor_pct", 85.47, "%", 15, "China Southern operating table: average passenger load factor."),
        ("passenger_yield", 0.46, "RMB/RPK", 16, "China Southern operating table: average passenger yield."),
        ("cargo_yield", 1.87, "RMB/RTK", 16, "China Southern operating table: average cargo yield."),
        ("fuel_cost", 25_334.0, "RMB million", 145, "China Southern cost note: fuel cost."),
        ("fleet_total", 943.0, "aircraft", 16, "China Southern fleet table: group fleet total."),
        ("passenger_revenue", 74_570.0, "RMB million", 20, "China Southern product-revenue table: passenger and related services revenue."),
        ("cash_and_cash_equivalents", 12_692.0, "RMB million", 66, "China Southern consolidated cash-flow statement: period-end cash and cash equivalents."),
        ("total_liabilities", 284_770.0, "RMB million", 57, "China Southern consolidated balance sheet: total liabilities."),
        ("capex_cash_paid", 5_876.0, "RMB million", 65, "China Southern consolidated cash-flow statement: cash paid for property, plant and equipment and other long-term assets."),
    ),
    "600029_2025_fy": (
        ("cash_and_cash_equivalents", 9_402.0, "RMB million", 191, "China Southern consolidated cash-flow note: year-end cash and cash equivalents."),
        ("total_liabilities", 294_803.0, "RMB million", 93, "China Southern consolidated balance sheet: total liabilities."),
        ("capex_cash_paid", 17_767.0, "RMB million", 101, "China Southern consolidated cash-flow statement: cash paid for property, plant and equipment and other long-term assets."),
    ),
    "600115_2025_h1": (
        ("ask", 155_022.29, "million seat-km", 14, "China Eastern operating table: group ASK."),
        ("rpk", 131_477.90, "million passenger-km", 14, "China Eastern operating table: group RPK."),
        ("passengers", 73.16963, "million passengers", 14, "China Eastern operating table: passengers, converted from thousand."),
        ("passenger_load_factor_pct", 84.81, "%", 14, "China Eastern operating table: group passenger load factor."),
        ("cargo_load_factor_pct", 36.99, "%", 15, "China Eastern operating table: group cargo load factor."),
        ("passenger_yield", 0.488, "RMB/RPK", 14, "China Eastern operating table: group passenger yield."),
        ("cargo_yield", 1.334, "RMB/RTK", 15, "China Eastern operating table: group cargo yield."),
        ("passenger_revenue", 61_813.0, "RMB million", 141, "China Eastern consolidated-report note: passenger-service revenue."),
        ("cargo_revenue", 2_577.0, "RMB million", 141, "China Eastern consolidated-report note: cargo-service revenue."),
        ("fuel_cost", 21_411.0, "RMB million", 29, "China Eastern cost-analysis table: aviation fuel cost."),
        ("fleet_total", 816.0, "aircraft", 16, "China Eastern fleet table: passenger-aircraft total."),
        ("cash_and_cash_equivalents", 3_599.0, "RMB million", 152, "China Eastern consolidated cash-flow note: period-end cash and cash equivalents."),
        ("total_liabilities", 242_709.0, "RMB million", 32, "China Eastern management discussion: group total liabilities at 2025-06-30, reported as RMB2,427.09亿元 (RMB242.709bn)."),
        ("interest_bearing_debt", 181_439.0, "RMB million", 38, "China Eastern management discussion: group interest-bearing debt, reported as RMB1,814.39亿元 (RMB181.439bn)."),
    ),
    "600115_2025_fy": (
        ("total_liabilities", 252_916.0, "RMB million", 30, "China Eastern management discussion: group total liabilities at 2025-12-31, reported as RMB2,529.16亿元 (RMB252.916bn)."),
        ("interest_bearing_debt", 181_928.0, "RMB million", 40, "China Eastern management discussion: group interest-bearing debt, reported as RMB1,819.28亿元 (RMB181.928bn)."),
    ),
    "601021_2025_fy": (
        ("rpk", 56_519.0999, "million passenger-km", 31, "Spring Airlines operating table: RPK, converted from ten-thousand passenger-km."),
        ("cash_and_cash_equivalents", 6_648.791807, "RMB million", 180, "Spring Airlines consolidated cash-flow note: year-end cash and cash equivalents."),
    ),
    "601021_2025_h1": (
        ("ask", 29_307.9501, "million seat-km", 13, "Spring Airlines operating table: ASK, converted from ten-thousand seat-km."),
        ("rpk", 26_528.9104, "million passenger-km", 13, "Spring Airlines operating table: RPK, converted from ten-thousand passenger-km."),
        ("passengers", 15.2189, "million passengers", 13, "Spring Airlines operating table: passengers, converted from ten-thousand passengers."),
        ("passenger_load_factor_pct", 90.52, "%", 14, "Spring Airlines operating table: average passenger load factor."),
        ("passenger_yield", 0.377, "RMB/RPK", 14, "Spring Airlines operating table: passenger yield."),
        ("daily_utilization", 9.74, "hours/day", 13, "Spring Airlines operating table: aircraft daily utilization."),
        ("cask", 0.303, "RMB/ASK", 21, "Spring Airlines operating discussion: reported unit cost."),
        ("fuel_cost", 2_980.0, "RMB million", 32, "Spring Airlines risk disclosure: fuel cost, RMB hundred-million converted to RMB million."),
        ("fleet_total", 133.0, "aircraft", 16, "Spring Airlines fleet disclosure: A320 fleet total."),
        ("cash_and_cash_equivalents", 7_323.963631, "RMB million", 68, "Spring Airlines consolidated cash-flow statement: period-end cash and cash equivalents."),
        ("total_liabilities", 28_706.670898, "RMB million", 63, "Spring Airlines consolidated balance sheet: total liabilities."),
        ("capex_cash_paid", 2_740.08249, "RMB million", 67, "Spring Airlines consolidated cash-flow statement: cash paid for property, plant and equipment and other long-term assets."),
    ),
    "600221_2025_h1": (
        ("ask", 77_921.27, "million seat-km", 12, "Hainan Airlines operating table: ASK, converted from ten-thousand seat-km."),
        ("rpk", 64_480.17, "million passenger-km", 12, "Hainan Airlines operating table: RPK, converted from ten-thousand passenger-km."),
        ("passengers", 34.089, "million passengers", 12, "Hainan Airlines operating table: passengers, converted from thousand."),
        ("passenger_load_factor_pct", 82.75, "%", 12, "Hainan Airlines operating table: passenger load factor."),
        ("daily_utilization", 9.6, "hours/day", 12, "Hainan Airlines operating table: aircraft daily utilization."),
        ("fleet_total", 348.0, "aircraft", 11, "Hainan Airlines fleet table: group fleet total."),
        ("passenger_revenue", 28_953.261, "RMB million", 119, "Hainan Airlines product-revenue table: passenger and other revenue; scope is not pure ticket revenue."),
        ("fuel_cost_share_pct_reported", 31.65, "%", 19, "Hainan Airlines risk disclosure: fuel cost as a share of operating cost."),
        ("fuel_cost_sensitivity_5pct_cost_abs", 488.261, "RMB million", 19, "Hainan Airlines risk disclosure: operating-cost change for a 5% fuel-price move."),
        ("cargo_revenue", 1_443.056, "RMB million", 119, "Hainan Airlines product-revenue table: aviation cargo and excess-baggage revenue."),
        ("cash_and_cash_equivalents", 2_105.700, "RMB million", 53, "Hainan Airlines consolidated cash-flow statement: period-end cash and cash equivalents."),
        ("total_liabilities", 140_655.005, "RMB million", 46, "Hainan Airlines consolidated balance sheet: total liabilities."),
        ("capex_cash_paid", 709.392, "RMB million", 53, "Hainan Airlines consolidated cash-flow statement: cash paid for property, plant and equipment and other long-term assets."),
    ),
    "600221_2025_fy": (
        ("passenger_revenue", 60_219.702, "RMB million", 167, "Hainan Airlines product-revenue table: passenger and other revenue; scope is not pure ticket revenue."),
        ("cargo_revenue", 3_231.747, "RMB million", 167, "Hainan Airlines product-revenue table: aviation cargo and excess-baggage revenue."),
        ("cash_and_cash_equivalents", 2_552.353, "RMB million", 174, "Hainan Airlines consolidated cash-flow note: period-end cash and cash equivalents."),
        ("total_liabilities", 146_911.165, "RMB million", 86, "Hainan Airlines consolidated balance sheet: total liabilities."),
        ("capex_cash_paid", 2_188.703, "RMB million", 93, "Hainan Airlines consolidated cash-flow statement: cash paid for property, plant and equipment and other long-term assets."),
    ),
    "603885_2025_fy": (
        ("rpk", 48_961.2604, "million passenger-km", 26, "Juneyao Airlines operating table: RPK, converted from ten-thousand passenger-km."),
        ("attributable_net_income", 1_039.63838235, "RMB million", 7, "Juneyao Airlines annual main financial-data table: attributable net income."),
        ("cash_and_cash_equivalents", 2_963.2715285, "RMB million", 168, "Juneyao Airlines consolidated cash-flow note: period-end cash and cash equivalents."),
        ("total_liabilities", 40_119.0, "RMB million", 39, "Juneyao Airlines management discussion: group total liabilities at 2025-12-31, reported as RMB401.19亿元 (RMB40.119bn)."),
        ("interest_bearing_debt", 35_606.0, "RMB million", 174, "Juneyao Airlines management discussion: group interest-bearing debt, reported as RMB356.06亿元 (RMB35.606bn)."),
    ),
    "603885_2025_h1": (
        ("cash_and_cash_equivalents", 2_689.08841001, "RMB million", 60, "Juneyao Airlines consolidated cash-flow statement: period-end cash and cash equivalents."),
        ("total_liabilities", 40_861.90831457, "RMB million", 53, "Juneyao Airlines consolidated balance sheet: total liabilities."),
        ("interest_bearing_debt", 36_097.0, "RMB million", 162, "Juneyao Airlines management discussion: group interest-bearing debt, reported as RMB360.97亿元 (RMB36.097bn)."),
        ("capex_cash_paid", 433.39876325, "RMB million", 59, "Juneyao Airlines consolidated cash-flow statement: cash paid for property, plant and equipment and other long-term assets."),
    ),
}


def _compact(value: str) -> str:
    return (
        re.sub(r"\s+", "", value)
        .replace("（", "(")
        .replace("）", ")")
        .replace("：", ":")
        .replace("，", ",")
        .replace("－", "-")
        .replace("—", "-")
        .replace("／", "/")
    )


def _parse_number(value: str) -> float | None:
    text = value.strip().replace(",", "").replace("，", "")
    if not text or text in {"-", "--", "—", "不适用"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    try:
        parsed = float(text)
    except ValueError:
        return None
    return -parsed if negative else parsed


_NUMBER_RE = re.compile(
    # Do not treat aircraft model names such as A350 or B787 as numeric
    # columns, while still allowing a number immediately after Chinese text.
    r"(?<![A-Za-z0-9.])(?:\(-?[\d,]+(?:\.\d+)?\)|-?[\d,]+(?:\.\d+)?)(?![A-Za-z0-9.])"
)


def _numbers_after(text: str, label: str) -> list[float]:
    # Do not remove separators between table cells: ``182,256 174,224`` must
    # remain two numbers.  Match the label while allowing PDF line-wrap
    # whitespace between its characters, then parse the untouched tail.
    label_chars = [char for char in label if not char.isspace()]
    if not label_chars:
        return []
    label_pattern = r"\s*".join(re.escape(char) for char in label_chars)
    match = re.search(label_pattern, text, flags=re.DOTALL)
    if not match:
        return []
    values: list[float] = []
    # Rows in the financial tables contain current-year, prior-year and often
    # an extra percentage/third-year column.  Keep all numeric tokens so the
    # current-year extraction remains auditable.
    for number_match in _NUMBER_RE.finditer(text[match.end():]):
        parsed = _parse_number(number_match.group(0))
        if parsed is not None:
            values.append(parsed)
    return values


def _first_after(text: str, labels: Iterable[str]) -> float | None:
    for label in labels:
        values = _numbers_after(text, label)
        if values:
            return values[0]
    return None


def _find_page(pages: list[str], predicates: Iterable[str]) -> int | None:
    required = tuple(predicates)
    for index, text in enumerate(pages, start=1):
        compact = _compact(text)
        if all(_compact(predicate) in compact for predicate in required):
            return index
    return None


def _find_operations_pages(pages: list[str]) -> list[int]:
    """Find the operating-information pages rather than the definitions page."""
    candidates: list[int] = []
    for index, text in enumerate(pages, start=1):
        compact = _compact(text)
        if any(term in compact for term in ("释义", "本报告书中", "常用词语释义", "下列词语具有如下含义")):
            continue
        has_capacity = "可用座位公里" in compact or "ASK" in compact
        has_operating_context = any(
            term in compact
            for term in (
                "运营数据摘要", "运营数据表", "行业经营性信息", "运力投入",
                "主要经营状况", "经营数据摘要", "机队经营状况",
            )
        )
        if has_capacity and has_operating_context:
            candidates.append(index)

    if not candidates:
        for index, text in enumerate(pages, start=1):
            compact = _compact(text)
            if not any(term in compact for term in ("释义", "本报告书中", "常用词语释义")) and "可用座位公里" in compact and "客座率" in compact:
                candidates.append(index)

    if not candidates:
        return []

    selected: set[int] = set()
    for index in candidates:
        selected.add(index)
        # The table commonly splits across one or two pages: ASK on the first
        # page, load factor/yield on the next, and the fleet table after that.
        for neighbour in (index + 1, index + 2):
            if neighbour <= len(pages):
                neighbour_text = _compact(pages[neighbour - 1])
                if any(
                    term in neighbour_text
                    for term in (
                        "客座率", "收益", "机队情况", "机队结构", "机队数据摘要",
                        "飞机日利用率", "飞行量", "总飞行小时", "起飞架次",
                    )
                ):
                    selected.add(neighbour)

    # Include a later standalone fleet/operating summary when the report puts
    # the group fleet table in a separate section (Air China is an example).
    fleet_page = _find_page(pages, ("机队情况",)) or _find_page(pages, ("机队结构",))
    if fleet_page is not None:
        selected.add(fleet_page)
        if fleet_page < len(pages):
            fleet_neighbour = _compact(pages[fleet_page])
            if any(term in fleet_neighbour for term in ("飞机型号", "机型", "客机合计", "机队情况")):
                selected.add(fleet_page + 1)
    return sorted(selected)


def _find_operations_page(pages: list[str]) -> int | None:
    pages_found = _find_operations_pages(pages)
    return pages_found[0] if pages_found else None


def _find_segment_page(pages: list[str]) -> int | None:
    for index, text in enumerate(pages, start=1):
        compact = _compact(text)
        if "主营业务分产品" not in compact:
            continue
        if any(term in compact for term in ("航空客运", "客运及客运", "客运相关服务", "客运收入")) and any(
            term in compact for term in ("航空货运", "货运及邮运", "货邮运输")
        ):
            return index
    return None


def _page_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _line_numbers(line: str) -> list[float]:
    values: list[float] = []
    for match in _NUMBER_RE.finditer(line.replace("，", ",")):
        parsed = _parse_number(match.group(0))
        if parsed is not None:
            values.append(parsed)
    return values


def _line_value(
    text: str,
    labels: Iterable[str],
    *,
    position: int = 0,
    prefer_total: bool = False,
) -> tuple[float | None, int | None]:
    lines = _page_lines(text)
    candidates = [line for line in lines if any(label in _compact(line) for label in labels)]
    if prefer_total:
        total = [line for line in candidates if any(x in line for x in ("合计", "总计"))]
        if total:
            candidates = total + [line for line in candidates if line not in total]
    for line in candidates:
        values = _line_numbers(line)
        if len(values) > position:
            return values[position], None
    return None, None


def _extract_fleet_total(text: str) -> float | None:
    compact = _compact(text)
    # Search the full selected operating-text block.  The report can place
    # the prose fleet total before a later table heading (or put the table on
    # a separate page), so anchoring at the first heading can hide the answer.
    patterns = (
        r"(?:机队共有飞机|共运营(?:飞机)?|公司共运营|运营飞机|共拥有飞机)(?:数)?[^\d]{0,50}(\d{2,4})",
    )
    for pattern in patterns:
        match = re.search(pattern, compact)
        if match:
            return _parse_number(match.group(1))
    # A table total is safer than a generic ``合计`` elsewhere in the report.
    # ``客机合计`` uses the second column as the fleet total; the Southern
    # table has a standalone ``合计`` row whose final column is the total.
    for line in _page_lines(text):
        values = _line_numbers(line)
        if not values or "合计" not in line:
            continue
        if "客机合计" in line and len(values) > 1:
            return values[1]
        if _compact(line).startswith("合计") and len(values) >= 5:
            # Southern's fleet table has six columns and ends with the
            # report-period-end total; Hainan's compact table has five
            # columns and ends with average age.
            if len(values) >= 6:
                return values[-1]
            if len(values) == 5 and values[0] >= 100 and values[-1] < 30:
                return values[0]

    # Spring and Juneyao disclose ownership-form rows without a group-total
    # row.  Summing only the explicit ownership rows avoids mistaking the
    # passenger ``总计`` row for a fleet count.
    ownership_labels = ("自行保有", "自购飞机", "融资租赁", "经营租赁")
    fleet_start = next(
        (index for index, line in enumerate(_page_lines(text)) if any(term in _compact(line) for term in ("机队情况", "机队结构"))),
        None,
    )
    fleet_lines = _page_lines(text)[fleet_start:] if fleet_start is not None else []
    ownership_total = 0.0
    ownership_rows = 0
    for line in fleet_lines:
        if any(marker in _compact(line) for marker in ("投资状况", "报告期内飞机", "资本开支计划", "(五)")):
            break
        if not any(_compact(line).startswith(label) for label in ownership_labels):
            continue
        values = _line_numbers(line)
        if values:
            ownership_total += values[0]
            ownership_rows += 1
    if ownership_rows:
        return ownership_total
    return None


def _operations_line_metric(text: str, metric: str) -> float | None:
    """Extract a total/average operating value from a carrier table."""
    lines = _page_lines(text)
    has_aircraft_age = "平均机龄" in _compact(text)
    age_index = next((i for i, line in enumerate(lines) if "平均机龄" in _compact(line)), None)
    heading_seen = False
    heading_index: int | None = None
    for index, line in enumerate(lines):
        compact = _compact(line)
        values = _line_numbers(line)
        if metric == "passenger_load_factor_pct" and "客座率" in compact:
            heading_seen = True
            heading_index = index
            if values and len(values) > 1 and not ("本集团" in compact and "运力投入" in compact):
                return values[0]
        if metric == "daily_utilization" and "日利用率" in compact:
            heading_seen = True
            heading_index = index
            if values and len(values) > 1:
                return values[0]
        if metric == "passengers" and any(label in compact for label in ("旅客运输量", "载客人数", "旅客人次", "承运旅客人数")):
            heading_seen = True
            heading_index = index

        if metric not in {"passenger_load_factor_pct", "daily_utilization", "passengers"}:
            continue
        if not heading_seen:
            continue
        if heading_index is not None and index - heading_index > 25:
            continue
        if not any(marker in compact for marker in ("合计", "总计", "平均")):
            continue
        if not values:
            continue
        if metric == "passengers":
            return values[0]
        in_fleet_table = has_aircraft_age and (age_index is None or index >= age_index)
        if in_fleet_table:
            # Fleet-type table: average age, utilization, passenger LF,
            # overall LF.  The average row is the group total.
            position = 2 if metric == "passenger_load_factor_pct" else 1
            if len(values) > position:
                return values[position]
            continue
        # Passenger operating table: passengers, passenger LF, overall LF,
        # utilization.  Juneyao/Spring use this layout.
        position = 1 if metric == "passenger_load_factor_pct" else 3
        if len(values) > position:
            return values[position]

    if metric == "passengers":
        # A single-type low-cost carrier may have no total marker.  Take the
        # first data row after the passenger-table header.
        for index, line in enumerate(lines):
            if "旅客运输量" not in _compact(line) and "承运旅客人数" not in _compact(line):
                continue
            for candidate in lines[index + 1:index + 12]:
                values = _line_numbers(candidate)
                if len(values) >= 4:
                    return values[0]
    return None


def _table_value_after_heading(text: str, headings: Iterable[str], *, kind: str) -> float | None:
    """Read a total/average row following a table heading.

    Airline reports usually print regional rows followed by ``合计`` or
    ``平均``.  Reading the first number after the heading would silently pick
    the domestic row, so this helper prefers the total row and only falls back
    to a direct value on the heading line.
    """
    lines = _page_lines(text)
    for index, line in enumerate(lines):
        if not any(_compact(heading) in _compact(line) for heading in headings):
            continue
        direct_values = _line_numbers(line)
        if direct_values:
            # Narrative discussion often contains the same label as the
            # table (for example, Air China explains revenue changes caused by
            # a higher load factor).  Never treat those explanatory amounts
            # as the KPI itself; wait for the following formal table row.
            compact_line = _compact(line)
            if any(marker in compact_line for marker in ("因客座率", "增加收入", "减少收入", "影响收入")):
                continue
            if kind in {"passenger_load_factor_pct", "passengers"} and len(direct_values) < 2:
                continue
            return direct_values[0]
        first_data_row: list[float] | None = None
        for candidate in lines[index + 1:index + 18]:
            values = _line_numbers(candidate)
            if not values:
                continue
            if len(values) >= 2 and first_data_row is None:
                first_data_row = values
            compact = _compact(candidate)
            if "平均" in compact:
                if kind == "daily_utilization" and "平均机龄" in _compact(text):
                    return values[1] if len(values) > 1 else None
                return values[0]
            if any(marker in compact for marker in ("合计", "总计")):
                if kind in {"ask", "rpk"}:
                    return values[0]
                if kind == "passengers":
                    return values[0]
                if kind == "passenger_load_factor_pct":
                    return values[1] if len(values) > 1 else None
                if kind == "daily_utilization":
                    return values[-1]
        # Stop before walking into a different table/section.
        if index + 1 < len(lines) and any(
            marker in _compact(lines[index + 1]) for marker in ("机队情况", "机队结构", "投资状况", "风险")
        ):
            break
        if first_data_row is not None:
            if kind == "daily_utilization":
                return first_data_row[-1]
            if kind in {"ask", "rpk"}:
                return first_data_row[0]
            if kind == "passengers":
                return first_data_row[0]
    return None


def _reported_yield(text: str, headings: Iterable[str]) -> float | None:
    """Prefer an issuer table's ``平均`` yield over the first region row."""
    lines = _page_lines(text)
    for index, line in enumerate(lines):
        if not any(_compact(heading) in _compact(line) for heading in headings):
            continue
        direct_values = _line_numbers(line)
        if direct_values:
            return direct_values[0]
        first_value: float | None = None
        for candidate in lines[index + 1:index + 18]:
            values = _line_numbers(candidate)
            if not values:
                continue
            if first_value is None:
                first_value = values[0]
            compact = _compact(candidate)
            if "平均" in compact or any(marker in compact for marker in ("合计", "总计")):
                return values[0]
        if first_value is not None:
            return first_value
    return None


def _operation_unit_divisor(text: str, phrase: str) -> float:
    compact = _compact(text)
    index = compact.find(_compact(phrase))
    nearby = compact[index:index + 100] if index >= 0 else compact
    if "万座公里" in nearby or "万人公里" in nearby:
        return 100.0
    if "万" in nearby and "百万" not in nearby:
        return 100.0
    return 1.0


def _report_pages(payload: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def _fx_asof(fx_rates: pd.DataFrame | None, as_of: str) -> tuple[str | None, float | None]:
    if fx_rates is None or fx_rates.empty:
        return None, None
    frame = fx_rates.loc[fx_rates["pair"].eq("USD_CNY")].copy()
    if frame.empty:
        return None, None
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    target = pd.Timestamp(as_of)
    frame = frame.loc[frame["observation_date"].le(target)].dropna(subset=["observation_date", "value"])
    if frame.empty:
        return None, None
    row = frame.sort_values("observation_date").iloc[-1]
    return row["observation_date"].strftime("%Y-%m-%d"), float(row["value"])


def _add_driver(
    rows: list[dict[str, Any]],
    spec: ReportSpec,
    *,
    metric: str,
    value_native: float | None,
    native_unit: str,
    source_page: int | None,
    source_note: str,
    source_quality: str = "primary_issuer",
    metric_scope: str = "group_reported",
    calculation_method: str = "issuer_reported",
    fx_rates: pd.DataFrame | None = None,
    retrieved_at: str,
) -> None:
    if value_native is None:
        return
    value_usd = None
    usd_unit = None
    fx_date = None
    fx_value = None
    fx_pair = None
    if native_unit == "RMB million":
        fx_pair = "USD_CNY"
        fx_date, fx_value = _fx_asof(fx_rates, spec.period_end)
        if fx_value is not None:
            value_usd = value_native / fx_value
            usd_unit = "USD million"
    rows.append(
        {
            "dataset_id": "airline_official_report_drivers",
            "report_id": spec.report_id,
            "ticker": spec.ticker,
            "company": spec.company,
            "report_type": spec.report_type,
            "statement_period": spec.statement_period,
            "period_end": spec.period_end,
            "announced_at": spec.announcement_date,
            "metric": metric,
            "value_native": value_native,
            "native_unit": native_unit,
            "native_currency": "RMB" if native_unit.startswith("RMB") else None,
            "value_usd": value_usd,
            "usd_unit": usd_unit,
            "fx_pair": fx_pair,
            "fx_observation_date": fx_date,
            "fx_value": fx_value,
            "metric_scope": metric_scope,
            "calculation_method": calculation_method,
            "source_quality": source_quality,
            "source_url": spec.source_url,
            "source_page": source_page,
            "source_note": source_note,
            "retrieved_at": retrieved_at,
        }
    )


def _validate_driver_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop numerically impossible parser outputs rather than publish false facts.

    Cninfo PDFs frequently place a year/unit number beside the operating table.
    A permissive first-number parser can therefore emit values such as 2025 for
    ASK or 175,000% for load factor.  The report remains in the registry, but
    an unsafe driver becomes an explicit disclosure/parser gap in the normalized
    layer.  Bounds are broad domain guards, not investment assumptions.
    """
    bounds: dict[str, tuple[float, float]] = {
        "total_revenue": (100.0, 1_000_000.0),
        "operating_cost": (100.0, 1_000_000.0),
        "fuel_cost": (0.0, 100_000.0),
        "ask": (10_000.0, 1_000_000.0),
        "rpk": (10_000.0, 1_500_000.0),
        "passengers": (1.0, 500.0),
        "passenger_load_factor_pct": (0.0, 100.0),
        "cargo_load_factor_pct": (0.0, 100.0),
        "passenger_yield": (0.01, 5.0),
        "cargo_yield": (0.01, 10.0),
        "cask": (0.05, 2.0),
        "cask_derived": (0.05, 2.0),
        "fuel_cost_per_ask_derived": (0.01, 1.0),
        "fuel_cost_share_pct_derived": (0.0, 100.0),
        "fuel_cost_share_pct_reported": (0.0, 100.0),
        "fuel_cost_implied_from_reported_share": (0.0, 100_000.0),
        "passenger_revenue": (100.0, 1_000_000.0),
        "cargo_revenue": (100.0, 1_000_000.0),
        "rask_derived": (0.05, 2.0),
        "rask_from_reported_yield_derived": (0.05, 2.0),
        "passenger_yield_derived": (0.01, 5.0),
        "daily_utilization": (0.0, 24.0),
        "fleet_total": (20.0, 2_000.0),
        "weighted_average_roe": (-100.0, 100.0),
        "cash_and_cash_equivalents": (0.0, 1_000_000.0),
        "total_liabilities": (0.0, 1_000_000.0),
        "liabilities_to_assets_pct_derived": (0.0, 200.0),
        "interest_bearing_debt": (0.0, 1_000_000.0),
        "capex_cash_paid": (0.0, 1_000_000.0),
    }
    valid: list[dict[str, Any]] = []
    for row in rows:
        metric = row.get("metric")
        value = row.get("value_native")
        if metric not in bounds or value is None:
            valid.append(row)
            continue
        low, high = bounds[metric]
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if low <= numeric <= high:
            valid.append(row)
    return valid


def _apply_operating_overrides(
    rows: list[dict[str, Any]],
    spec: ReportSpec,
    *,
    pages: list[str],
    fx_rates: pd.DataFrame | None,
    retrieved_at: str,
) -> None:
    """Apply verified issuer-table anchors to a parsed report in place."""
    overrides = OPERATING_OVERRIDES.get(spec.report_id, ())
    if not overrides:
        return

    override_metrics = {metric for metric, *_ in overrides}
    rows[:] = [row for row in rows if row.get("metric") not in override_metrics]
    for metric, value, native_unit, source_page, source_note in overrides:
        if not 1 <= source_page <= len(pages):
            # A source-page mismatch should create a gap rather than a row
            # with unverifiable lineage.
            continue
        _add_driver(
            rows,
            spec,
            metric=metric,
            value_native=value,
            native_unit=native_unit,
            source_page=source_page,
            source_note=f"Primary issuer table anchor; {source_note}",
            fx_rates=fx_rates,
            retrieved_at=retrieved_at,
        )


def parse_official_report(
    payload: bytes,
    spec: ReportSpec,
    *,
    fx_rates: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse comparable financial and operating drivers from one issuer PDF."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    pages = _report_pages(payload)
    financial_page = _find_page(pages, ("主要会计数据", "归属于上市公司股东"))
    income_page = _find_page(pages, ("营业成本", "经营活动产生的现金流量净额"))
    if income_page is None:
        # Some annual reports split the income statement and cash-flow table
        # across pages.  The income-statement page still provides the primary
        # operating-cost row and is safe to use as a fallback.
        income_page = _find_page(pages, ("营业成本", "营业收入"))
    cost_page = _find_page(pages, ("成本分析表",))
    ops_page_indices = _find_operations_pages(pages)
    ops_page = ops_page_indices[0] if ops_page_indices else None
    segment_page = _find_segment_page(pages)
    rows: list[dict[str, Any]] = []

    if financial_page:
        text = pages[financial_page - 1]
        main_specs = (
            ("total_revenue", ("营业收入",), "RMB million"),
            ("profit_total", ("利润总额",), "RMB million"),
            ("attributable_net_income", ("归属于上市公司股东的净利润",), "RMB million"),
            (
                "adjusted_attributable_net_income",
                ("归属于上市公司股东的扣除非经常性损益的净利润",),
                "RMB million",
            ),
            ("operating_cash_flow", ("经营活动产生的现金流量净额",), "RMB million"),
            ("equity_attributable", ("归属于上市公司股东的净资产",), "RMB million"),
            ("total_assets", ("总资产",), "RMB million"),
            ("basic_eps", ("基本每股收益",), "RMB/share"),
            ("weighted_average_roe", ("加权平均净资产收益率",), "%"),
        )
        for metric, labels, unit in main_specs:
            raw = _first_after(text, labels)
            if raw is not None:
                value = raw * spec.financial_scale_to_rmb_million if unit == "RMB million" else raw
                _add_driver(
                    rows, spec, metric=metric, value_native=value, native_unit=unit,
                    source_page=financial_page,
                    source_note="Primary issuer annual/interim report main financial-data table.",
                    fx_rates=fx_rates, retrieved_at=retrieved,
                )

    if income_page:
        text = pages[income_page - 1]
        raw = _first_after(text, ("营业成本",))
        if raw is not None:
            _add_driver(
                rows, spec, metric="operating_cost", value_native=raw * spec.financial_scale_to_rmb_million,
                native_unit="RMB million", source_page=income_page,
                source_note="Primary issuer income-statement / financial-indicator table.",
                fx_rates=fx_rates, retrieved_at=retrieved,
            )

    if cost_page:
        text = pages[cost_page - 1]
        cost_specs = (
            ("fuel_cost", ("航空油料成本", "航空油料消耗", "航空燃油消耗", "飞机燃油成本", "航油费", "航油成本")),
            ("staff_cost", ("职工薪酬费用", "职工薪酬", "员工薪酬成本", "工资及福利费用", "工资福利费用")),
            ("depreciation_amortization", ("折旧与摊销费用", "折旧与摊销", "飞发及高周件折旧", "折旧费用和摊销费用", "租赁折旧费用")),
            ("airport_landing_cost", ("起降服务费", "机场起降费", "起降成本", "起降费用")),
            ("maintenance_cost", ("飞机维护及修理费用", "飞机维护及修理", "飞发维修及航材消耗费", "飞发修理", "维修成本", "修理费用")),
            ("lease_cost", ("租赁费",)),
        )
        for metric, labels in cost_specs:
            raw = _first_after(text, labels)
            if raw is None:
                continue
            _add_driver(
                rows, spec, metric=metric, value_native=raw * spec.cost_scale_to_rmb_million,
                native_unit="RMB million", source_page=cost_page,
                source_note="Primary issuer cost-analysis table; reported cost category.",
                fx_rates=fx_rates, retrieved_at=retrieved,
            )

    # Spring and Juneyao also disclose fuel cost in the risk/operating
    # discussion as RMB hundred-million, while their formal cost-analysis
    # table may not repeat the fuel line.  Use that explicit issuer number as
    # a fallback only when the cost table did not yield fuel cost.
    if not any(row.get("metric") == "fuel_cost" for row in rows):
        for source_page, page_text in enumerate(pages, start=1):
            for line in _page_lines(page_text):
                compact_line = _compact(line)
                if "航油成本" not in compact_line or "亿元" not in compact_line:
                    continue
                values = _line_numbers(line)
                if not values:
                    continue
                _add_driver(
                    rows, spec, metric="fuel_cost", value_native=values[0] * 100.0,
                    native_unit="RMB million", source_page=source_page,
                    source_note="Primary issuer risk/operating disclosure; fuel cost reported in RMB hundred-million.",
                    fx_rates=fx_rates, retrieved_at=retrieved,
                )
                break
            if any(row.get("metric") == "fuel_cost" for row in rows):
                break

    if ops_page:
        text = "\n".join(pages[index - 1] for index in ops_page_indices)
        ask_raw = _table_value_after_heading(text, ("可用座位公里", "可用座公里"), kind="ask")
        if ask_raw is None:
            ask_raw = _first_after(text, ("可用座位公里", "可用座公里"))
        if ask_raw is not None:
            ask = ask_raw / _operation_unit_divisor(text, "可用座位公里")
            _add_driver(
                rows, spec, metric="ask", value_native=ask, native_unit="million seat-km",
                source_page=ops_page, source_note="Primary issuer operating-information table; ASK normalized to million seat-km.",
                fx_rates=fx_rates, retrieved_at=retrieved,
            )

        rpk_headings = ("收费客公里", "收入客公里", "旅客周转量", "客运人公里")
        rpk_label = next(
            (label for label in rpk_headings if _compact(label) in _compact(text)),
            "收费客公里",
        )
        rpk_raw = _table_value_after_heading(text, rpk_headings, kind="rpk")
        if rpk_raw is None:
            rpk_raw = _first_after(text, rpk_headings)
        if rpk_raw is not None:
            rpk = rpk_raw / _operation_unit_divisor(text, rpk_label)
            _add_driver(
                rows, spec, metric="rpk", value_native=rpk,
                native_unit="million passenger-km", source_page=ops_page,
                source_note="Primary issuer operating-information table; RPK normalized to million passenger-km.",
                fx_rates=fx_rates, retrieved_at=retrieved,
            )

        # In the aircraft summary table, total/combined rows are preferred;
        # for a single-type low-cost carrier the only row is the carrier row.
        passenger_raw = _table_value_after_heading(
            text, ("旅客运输量", "载客人数", "旅客人次", "承运旅客人数"), kind="passengers"
        )
        if passenger_raw is None:
            passenger_raw = _operations_line_metric(text, "passengers")
        passenger_unit = "million passengers"
        compact = _compact(text)
        if any(unit in compact for unit in ("旅客运输量(万人", "旅客运输量(万", "承运旅客人数(万人", "载客人数(万人", "单位:万人", "单位：万人")):
            passenger_raw = passenger_raw / 100 if passenger_raw is not None else None
        elif any(unit in compact for unit in ("旅客运输量(千", "承运旅客人数(千", "载客人数(千", "旅客人次(千")):
            passenger_raw = passenger_raw / 1000 if passenger_raw is not None else None
        elif any(unit in compact for unit in ("旅客运输量(人", "承运旅客人数(人", "载客人数(人", "单位:人", "单位：人")):
            passenger_raw = passenger_raw / 1_000_000 if passenger_raw is not None else None
        if passenger_raw is not None:
            _add_driver(
                rows, spec, metric="passengers", value_native=passenger_raw,
                native_unit=passenger_unit, source_page=ops_page,
                source_note="Primary issuer operating-information table; passenger count normalized to millions.",
                fx_rates=fx_rates, retrieved_at=retrieved,
            )

        load_raw = _table_value_after_heading(text, ("客座率", "客座利用率"), kind="passenger_load_factor_pct")
        if load_raw is None:
            load_raw = _operations_line_metric(text, "passenger_load_factor_pct")
        if load_raw is None:
            load_raw = _first_after(text, ("客座率",))
        _add_driver(
            rows, spec, metric="passenger_load_factor_pct", value_native=load_raw,
            native_unit="%", source_page=ops_page,
            source_note="Primary issuer operating-information table.",
            fx_rates=fx_rates, retrieved_at=retrieved,
        )

        cargo_load_raw = _first_after(text, ("货物及邮件载运率", "货邮载运率"))
        _add_driver(
            rows, spec, metric="cargo_load_factor_pct", value_native=cargo_load_raw,
            native_unit="%", source_page=ops_page,
            source_note="Primary issuer operating-information table.",
            fx_rates=fx_rates, retrieved_at=retrieved,
        )

        passenger_yield = _reported_yield(
            text,
            ("每收入客公里收益", "每收费客公里收益", "每客公里收益", "客运人公里收益", "客公里收益"),
        )
        _add_driver(
            rows, spec, metric="passenger_yield", value_native=passenger_yield,
            native_unit="RMB/RPK", source_page=ops_page,
            source_note="Primary issuer disclosed passenger-yield line; scope follows the issuer table.",
            metric_scope="issuer_disclosed_line", fx_rates=fx_rates, retrieved_at=retrieved,
        )
        cargo_yield = _reported_yield(
            text, ("每收入货运吨公里收益", "每收费货运吨公里收益", "每货运吨公里收益", "货运吨公里收益")
        )
        _add_driver(
            rows, spec, metric="cargo_yield", value_native=cargo_yield,
            native_unit="RMB/RTK", source_page=ops_page,
            source_note="Primary issuer disclosed cargo-yield line; scope follows the issuer table.",
            metric_scope="issuer_disclosed_line", fx_rates=fx_rates, retrieved_at=retrieved,
        )
        cask = _first_after(text, ("每可用座位公里的营业成本", "单位营业成本", "单位成本"))
        _add_driver(
            rows, spec, metric="cask", value_native=cask,
            native_unit="RMB/ASK", source_page=ops_page,
            source_note="Primary issuer disclosed unit-cost line; scope follows the issuer table.",
            metric_scope="issuer_disclosed_line", fx_rates=fx_rates, retrieved_at=retrieved,
        )
        if "平均机龄" in compact:
            utilization = _operations_line_metric(text, "daily_utilization")
        else:
            utilization = _table_value_after_heading(text, ("日利用率", "飞机日利用率"), kind="daily_utilization")
        if utilization is None:
            utilization = _table_value_after_heading(text, ("日利用率", "飞机日利用率"), kind="daily_utilization")
        if utilization is None:
            utilization = _operations_line_metric(text, "daily_utilization")
        if utilization is None:
            utilization = _first_after(text, ("飞机日利用率", "日利用率"))
        _add_driver(
            rows, spec, metric="daily_utilization", value_native=utilization,
            native_unit="hours/day", source_page=ops_page,
            source_note="Primary issuer operating-information table.",
            fx_rates=fx_rates, retrieved_at=retrieved,
        )
        fleet = _extract_fleet_total(text)
        _add_driver(
            rows, spec, metric="fleet_total", value_native=fleet,
            native_unit="aircraft", source_page=ops_page,
            source_note="Primary issuer fleet table / group fleet total.",
            fx_rates=fx_rates, retrieved_at=retrieved,
        )

    # Some issuers quantify fuel-hedge fair-value changes and fuel-price
    # sensitivity outside the operating/cost tables.  Keep these rows sparse
    # and issuer-reported; a missing row means the report did not disclose a
    # safely parseable number, not that the company had no hedge.
    hedge_rows = [
        (index, page)
        for index, page in enumerate(pages, start=1)
        if "燃油套期合约" in _compact(page)
        and ("以公允价值计量的金融资产" in _compact(page) or "衍生品投资情况" in _compact(page))
    ]
    if hedge_rows:
        # The same hedge can appear in both the fair-value note and the
        # derivative-investment section.  Prefer the former and write one
        # observation per report/metric.
        preferred = [row for row in hedge_rows if "以公允价值计量的金融资产" in _compact(row[1])]
        hedge_rows = (preferred or hedge_rows)[:1]
    for source_page, text in hedge_rows:
        for line in _page_lines(text):
            if "燃油套期合约" not in _compact(line):
                continue
            values = _line_numbers(line)
            if not values:
                continue
            _add_driver(
                rows, spec, metric="fuel_hedge_fair_value_change", value_native=values[0],
                native_unit="RMB million", source_page=source_page,
                source_note="Primary issuer derivative table; current-period fair-value change for fuel hedge.",
                metric_scope="group_reported", fx_rates=fx_rates, retrieved_at=retrieved,
            )
            if len(values) > 1:
                _add_driver(
                    rows, spec, metric="fuel_hedge_ending_fair_value", value_native=values[-1],
                    native_unit="RMB million", source_page=source_page,
                    source_note="Primary issuer derivative table; ending fair value for fuel hedge.",
                    metric_scope="group_reported", fx_rates=fx_rates, retrieved_at=retrieved,
                )

    sensitivity_rows = [
        (index, page)
        for index, page in enumerate(pages, start=1)
        if "平均航油价格" in _compact(page)
        and ("上升或下降5%" in _compact(page) or "上升或下降" in _compact(page))
    ]
    for source_page, text in sensitivity_rows:
        lines = _page_lines(text)
        for index, line in enumerate(lines):
            if "平均航油价格" not in _compact(line):
                continue
            candidates = lines[index:index + 5]
            cost_line = next((candidate for candidate in candidates if "亿元" in _compact(candidate)), None)
            if cost_line is not None and _line_numbers(cost_line):
                # Air China describes the exposure as an absolute fuel-cost
                # change in RMB hundred-million, rather than a profit table.
                value = _line_numbers(cost_line)[-1]
                if "亿元" in _compact(cost_line):
                    value *= 100.0
                _add_driver(
                    rows, spec, metric="fuel_cost_sensitivity_5pct_abs", value_native=value,
                    native_unit="RMB million", source_page=source_page,
                    source_note="Primary issuer risk disclosure; absolute fuel-cost change for a 5% average jet-fuel-price move.",
                    metric_scope="sensitivity_reported", fx_rates=fx_rates, retrieved_at=retrieved,
                )
                break

            values: list[float] = []
            for candidate in lines[index + 1:index + 5]:
                values.extend(_line_numbers(candidate))
                if len(values) >= 2:
                    break
            if len(values) >= 2:
                for metric, value, direction in (
                    ("fuel_price_sensitivity_5pct_profit_if_price_up", values[0], "up"),
                    ("fuel_price_sensitivity_5pct_profit_if_price_down", values[1], "down"),
                ):
                    _add_driver(
                        rows, spec, metric=metric, value_native=value,
                        native_unit="RMB million", source_page=source_page,
                        source_note=f"Primary issuer sensitivity table; 5% average jet-fuel-price scenario ({direction}).",
                        metric_scope="sensitivity_reported", fx_rates=fx_rates, retrieved_at=retrieved,
                    )
            break

    if segment_page:
        text = pages[segment_page - 1]
        for metric, labels in (
            ("passenger_revenue", ("航空客运", "客运收入", "客运")),
            ("cargo_revenue", ("航空货运", "货运及邮运", "货邮运输")),
        ):
            raw = _first_after(text, labels)
            if raw is None:
                continue
            _add_driver(
                rows, spec, metric=metric, value_native=raw * spec.financial_scale_to_rmb_million,
                native_unit="RMB million", source_page=segment_page,
                source_note="Primary issuer revenue-disaggregation table; wording and scope follow the report.",
                metric_scope="issuer_disclosed_line", fx_rates=fx_rates, retrieved_at=retrieved,
            )

    # Apply only the explicitly verified report-specific anchors after all
    # generic source fields have been parsed.  This ordering is important for
    # report layouts where a nearby narrative number can otherwise append a
    # second row for the same metric.  Derived unit economics below therefore
    # use one corrected primary input per metric.
    _apply_operating_overrides(
        rows,
        spec,
        pages=pages,
        fx_rates=fx_rates,
        retrieved_at=retrieved,
    )

    # Hainan's 1H2025 report discloses fuel cost as a percentage of operating
    # cost and gives a separate 5% sensitivity, but does not print a direct
    # RMB fuel-cost line. Preserve a model-useful implied amount under a
    # distinct metric name and calculation method rather than promoting it to
    # the issuer-reported ``fuel_cost`` field.
    if spec.report_id == "600221_2025_h1":
        operating_cost = next(
            (float(row["value_native"]) for row in rows if row.get("metric") == "operating_cost"),
            None,
        )
        fuel_share = next(
            (float(row["value_native"]) for row in rows if row.get("metric") == "fuel_cost_share_pct_reported"),
            None,
        )
        if operating_cost is not None and fuel_share is not None:
            _add_driver(
                rows,
                spec,
                metric="fuel_cost_implied_from_reported_share",
                value_native=operating_cost * fuel_share / 100.0,
                native_unit="RMB million",
                source_page=19,
                source_note=(
                    "Derived from issuer-reported operating cost and 31.65% fuel-cost share; "
                    "the report's relevant cost/risk disclosures provide no direct RMB fuel-cost "
                    "line, so this is not an issuer-reported fuel expense. The separate 5% "
                    "sensitivity implies approximately RMB9,765m after report rounding."
                ),
                metric_scope="derived_group",
                calculation_method="derived_from_reported_share",
                fx_rates=fx_rates,
                retrieved_at=retrieved,
            )

    # Derive model-friendly unit economics from the same report only when the
    # required inputs are available.  These rows are intentionally separate
    # from issuer-reported values.
    indexed = {row["metric"]: row["value_native"] for row in rows}
    passenger_revenue_page = next(
        (
            row.get("source_page")
            for row in rows
            if row.get("metric") == "passenger_revenue" and row.get("source_page") is not None
        ),
        None,
    )
    rpk_page = next(
        (
            row.get("source_page")
            for row in rows
            if row.get("metric") == "rpk" and row.get("source_page") is not None
        ),
        None,
    )
    if indexed.get("passenger_revenue") is not None and indexed.get("rpk") is not None:
        _add_driver(
            rows, spec, metric="passenger_yield_derived", value_native=indexed["passenger_revenue"] / indexed["rpk"],
            native_unit="RMB/RPK", source_page=passenger_revenue_page or rpk_page or segment_page or ops_page,
            source_note=(
                "Derived as passenger revenue / RPK; use only when revenue and RPK have matching scope. "
                f"Input source pages: passenger revenue={passenger_revenue_page}, RPK={rpk_page}."
            ),
            metric_scope="derived_group", calculation_method="derived", fx_rates=fx_rates, retrieved_at=retrieved,
        )
    if indexed.get("passenger_revenue") is not None and indexed.get("ask") is not None:
        _add_driver(
            rows, spec, metric="rask_derived", value_native=indexed["passenger_revenue"] / indexed["ask"],
            native_unit="RMB/ASK", source_page=passenger_revenue_page or segment_page or ops_page,
            source_note=(
                "Derived as passenger revenue / ASK; not issuer-reported RASK. "
                f"Input source pages: passenger revenue={passenger_revenue_page}, ASK={ops_page}."
            ),
            metric_scope="derived_group", calculation_method="derived", fx_rates=fx_rates, retrieved_at=retrieved,
        )
    if (
        indexed.get("passenger_revenue") is None
        and indexed.get("passenger_yield") is not None
        and indexed.get("rpk") is not None
        and indexed.get("ask") is not None
    ):
        yield_page = next(
            (
                row.get("source_page")
                for row in rows
                if row.get("metric") == "passenger_yield" and row.get("source_page") is not None
            ),
            None,
        )
        _add_driver(
            rows,
            spec,
            metric="rask_from_reported_yield_derived",
            value_native=indexed["passenger_yield"] * indexed["rpk"] / indexed["ask"],
            native_unit="RMB/ASK",
            source_page=yield_page or rpk_page or ops_page,
            source_note=(
                "Derived as reported passenger yield × RPK / ASK; preserves the issuer yield scope "
                "and is not issuer-reported RASK."
            ),
            metric_scope="derived_group",
            calculation_method="derived_from_reported_yield_load_factor",
            fx_rates=fx_rates,
            retrieved_at=retrieved,
        )
    if indexed.get("operating_cost") is not None and indexed.get("ask") is not None:
        _add_driver(
            rows, spec, metric="cask_derived", value_native=indexed["operating_cost"] / indexed["ask"],
            native_unit="RMB/ASK", source_page=income_page or ops_page,
            source_note="Derived as consolidated operating cost / ASK; not issuer-reported CASK.",
            metric_scope="derived_group", calculation_method="derived", fx_rates=fx_rates, retrieved_at=retrieved,
        )
    if indexed.get("fuel_cost") is not None and indexed.get("ask") is not None:
        _add_driver(
            rows, spec, metric="fuel_cost_per_ask_derived", value_native=indexed["fuel_cost"] / indexed["ask"],
            native_unit="RMB/ASK", source_page=cost_page or ops_page,
            source_note="Derived as reported fuel cost / ASK; fuel-price, mix and hedging effects remain embedded.",
            metric_scope="derived_group", calculation_method="derived", fx_rates=fx_rates, retrieved_at=retrieved,
        )
    if indexed.get("fuel_cost") is not None and indexed.get("operating_cost") not in (None, 0):
        _add_driver(
            rows, spec, metric="fuel_cost_share_pct_derived", value_native=100 * indexed["fuel_cost"] / indexed["operating_cost"],
            native_unit="%", source_page=cost_page or income_page,
            source_note="Derived as reported fuel cost / reported operating cost.",
            metric_scope="derived_group", calculation_method="derived", fx_rates=fx_rates, retrieved_at=retrieved,
        )
    if indexed.get("total_liabilities") is not None and indexed.get("total_assets") not in (None, 0):
        liabilities_page = next(
            (row.get("source_page") for row in rows if row.get("metric") == "total_liabilities" and row.get("source_page") is not None),
            None,
        )
        assets_page = next(
            (row.get("source_page") for row in rows if row.get("metric") == "total_assets" and row.get("source_page") is not None),
            None,
        )
        _add_driver(
            rows,
            spec,
            metric="liabilities_to_assets_pct_derived",
            value_native=100 * indexed["total_liabilities"] / indexed["total_assets"],
            native_unit="%",
            source_page=liabilities_page or assets_page,
            source_note=(
                "Derived as consolidated total liabilities / total assets; not an issuer-reported ratio. "
                f"Input source pages: liabilities={liabilities_page}, assets={assets_page}."
            ),
            metric_scope="derived_group",
            calculation_method="derived_from_total_liabilities_divided_by_total_assets",
            fx_rates=fx_rates,
            retrieved_at=retrieved,
        )

    rows = _validate_driver_rows(rows)
    return pd.DataFrame(rows, columns=DRIVER_COLUMNS)


def _download_report(spec: ReportSpec, *, session: requests.Session, retrieved_at: str) -> tuple[bytes, Path]:
    target = AIRLINE_REPORTS_DIR / spec.symbol / f"{spec.report_id}.PDF"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        return target.read_bytes(), target
    response = session.get(spec.source_url, headers=DEFAULT_HEADERS, timeout=max(DEFAULT_TIMEOUT, 60))
    response.raise_for_status()
    target.write_bytes(response.content)
    return response.content, target


def fetch_official_airline_report_drivers(
    *,
    reports: Iterable[ReportSpec] = REPORTS,
    fx_rates: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Download curated Cninfo reports and persist registry/driver CSVs.

    When ``reports`` is a subset, the refresh is incremental: only successfully
    parsed report IDs replace their existing rows.  This keeps a large or
    temporarily malformed PDF from overwriting an otherwise valid snapshot.
    """
    report_specs = tuple(reports)
    if fx_rates is None:
        fx_path = NORMALIZED_DIR / "airline_fx_rates.parquet"
        if fx_path.exists():
            fx_rates = pd.read_parquet(fx_path)
    retrieved = datetime.now(timezone.utc).isoformat()
    session = requests.Session()
    registry_rows: list[dict[str, Any]] = []
    driver_frames: list[pd.DataFrame] = []
    for spec in report_specs:
        raw_path: Path | None = None
        try:
            payload, raw_path = _download_report(spec, session=session, retrieved_at=retrieved)
            drivers = parse_official_report(payload, spec, fx_rates=fx_rates, retrieved_at=retrieved)
            driver_frames.append(drivers)
            registry_rows.append(
                {
                    "dataset_id": "airline_official_report_registry",
                    "report_id": spec.report_id,
                    "ticker": spec.ticker,
                    "company": spec.company,
                    "report_type": spec.report_type,
                    "statement_period": spec.statement_period,
                    "period_start": spec.period_start,
                    "period_end": spec.period_end,
                    "announcement_date": spec.announcement_date,
                    "source_quality": "primary_issuer",
                    "source_url": spec.source_url,
                    "raw_snapshot_path": str(raw_path),
                    "retrieved_at": retrieved,
                    "parse_status": "parsed" if not drivers.empty else "parsed_no_rows",
                    "parse_note": f"financial_page/cost_page/ops_page extracted; {len(drivers)} driver rows",
                }
            )
        except Exception as exc:
            registry_rows.append(
                {
                    "dataset_id": "airline_official_report_registry",
                    "report_id": spec.report_id,
                    "ticker": spec.ticker,
                    "company": spec.company,
                    "report_type": spec.report_type,
                    "statement_period": spec.statement_period,
                    "period_start": spec.period_start,
                    "period_end": spec.period_end,
                    "announcement_date": spec.announcement_date,
                    "source_quality": "primary_issuer",
                    "source_url": spec.source_url,
                    "raw_snapshot_path": str(raw_path) if raw_path else None,
                    "retrieved_at": retrieved,
                    "parse_status": "error",
                    "parse_note": f"{type(exc).__name__}: {exc}",
                }
            )

    registry = pd.DataFrame(registry_rows, columns=REPORT_COLUMNS)
    drivers = pd.concat([frame for frame in driver_frames if not frame.empty], ignore_index=True) if driver_frames else pd.DataFrame(columns=DRIVER_COLUMNS)
    registry_path = NORMALIZED_DIR / "airline_official_report_registry.csv"
    drivers_path = NORMALIZED_DIR / "airline_official_report_drivers.csv"
    successful_ids = set(registry.loc[registry["parse_status"].eq("parsed"), "report_id"])
    if len(report_specs) < len(REPORTS) and successful_ids and registry_path.exists() and drivers_path.exists():
        prior_registry = pd.read_csv(registry_path)
        prior_drivers = pd.read_csv(drivers_path)
        registry = pd.concat(
            [
                prior_registry.loc[~prior_registry["report_id"].isin(successful_ids)],
                registry,
            ],
            ignore_index=True,
        ).drop_duplicates("report_id", keep="last")
        drivers = pd.concat(
            [
                prior_drivers.loc[~prior_drivers["report_id"].isin(successful_ids)],
                drivers,
            ],
            ignore_index=True,
        )
    registry.to_csv(registry_path, index=False)
    drivers.to_csv(drivers_path, index=False)
    return {"registry": registry, "drivers": drivers}


def source_paths() -> dict[str, Path]:
    return {
        "registry": NORMALIZED_DIR / "airline_official_report_registry.csv",
        "drivers": NORMALIZED_DIR / "airline_official_report_drivers.csv",
        "raw_dir": AIRLINE_REPORTS_DIR,
    }
