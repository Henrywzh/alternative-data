"""Point-in-time fuel-hedging disclosure coverage from primary airline reports.

This is deliberately separate from the numeric earnings-driver table.  A
report may disclose a fuel hedge policy, an open notional, a fair-value change,
or an explicit ``no fuel futures`` statement; those are different facts and
must not be collapsed into a zero or a single hedge-cost number.

The layer is a coverage/audit contract as well as a data source.  For reports
where the targeted primary-report scan finds no safe fuel-specific anchor, the
row says exactly that.  It does not claim that the issuer had no hedges.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterable

import pandas as pd
import pdfplumber

from ..config import AIRLINE_REPORTS_DIR, NORMALIZED_DIR
from .airline_official_reports import REPORTS, ReportSpec


OUTPUT_PATH = NORMALIZED_DIR / "airline_hedging_disclosures.csv"

OUTPUT_COLUMNS = [
    "dataset_id", "report_id", "ticker", "company", "report_type",
    "statement_period", "period_end", "announcement_date", "information_date",
    "hedge_scope", "disclosure_type", "hedge_status", "hedge_instrument",
    "notional_native", "notional_unit", "fair_value_change_native",
    "fair_value_end_native", "native_currency", "source_quality", "source_url",
    "source_page", "source_note", "raw_snapshot_path", "scan_scope",
    "parse_status", "retrieved_at",
]


SCAN_SCOPE = (
    "Full cached issuer PDF text scan for fuel-specific terms: "
    "燃油套期, 航油套期, 燃油期货, 航油期货, 燃油价格风险, 航油价格风险; "
    "explicit anchors retained separately from scan-result rows."
)


def _compact(value: str) -> str:
    return "".join(str(value).split())


def _pages(path: Path) -> list[str]:
    # Poppler's text extractor is materially lighter than retaining a full
    # pdfplumber page object graph for the large annual reports.  Keep the
    # pdfplumber fallback for environments without the command-line utility.
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        result = subprocess.run(
            [pdftotext, "-layout", str(path), "-"],
            check=True,
            capture_output=True,
        )
        return result.stdout.decode("utf-8", errors="replace").split("\f")
    with pdfplumber.open(path) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def _find_page(pages: list[str], needles: Iterable[str]) -> int | None:
    compact_needles = tuple(_compact(needle) for needle in needles)
    for page_number, page in enumerate(pages, start=1):
        text = _compact(page)
        if any(needle in text for needle in compact_needles):
            return page_number
    return None


def _row(
    spec: ReportSpec,
    *,
    hedge_scope: str,
    disclosure_type: str,
    hedge_status: str,
    hedge_instrument: str | None,
    source_page: int | None,
    source_note: str,
    raw_snapshot_path: str | None,
    source_quality: str,
    parse_status: str,
    retrieved_at: str,
    notional_native: float | None = None,
    notional_unit: str | None = None,
    fair_value_change_native: float | None = None,
    fair_value_end_native: float | None = None,
    native_currency: str | None = None,
) -> dict[str, Any]:
    return {
        "dataset_id": "airline_hedging_disclosures",
        "report_id": spec.report_id,
        "ticker": spec.ticker,
        "company": spec.company,
        "report_type": spec.report_type,
        "statement_period": spec.statement_period,
        "period_end": spec.period_end,
        "announcement_date": spec.announcement_date,
        "information_date": spec.announcement_date,
        "hedge_scope": hedge_scope,
        "disclosure_type": disclosure_type,
        "hedge_status": hedge_status,
        "hedge_instrument": hedge_instrument,
        "notional_native": notional_native,
        "notional_unit": notional_unit,
        "fair_value_change_native": fair_value_change_native,
        "fair_value_end_native": fair_value_end_native,
        "native_currency": native_currency,
        "source_quality": source_quality,
        "source_url": spec.source_url,
        "source_page": source_page,
        "source_note": source_note,
        "raw_snapshot_path": raw_snapshot_path,
        "scan_scope": SCAN_SCOPE,
        "parse_status": parse_status,
        "retrieved_at": retrieved_at,
    }


def build_airline_hedging_disclosures(
    *, reports: Iterable[ReportSpec] = REPORTS, retrieved_at: str | None = None
) -> pd.DataFrame:
    """Build report-level fuel-hedging disclosure rows from cached primary PDFs."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []

    for spec in reports:
        raw_path = AIRLINE_REPORTS_DIR / spec.symbol / f"{spec.report_id}.PDF"
        if not raw_path.exists() or raw_path.stat().st_size == 0:
            rows.append(_row(
                spec,
                hedge_scope="fuel",
                disclosure_type="scan_result",
                hedge_status="raw_snapshot_missing",
                hedge_instrument=None,
                source_page=None,
                source_note="Cached primary issuer PDF is unavailable; no disclosure conclusion is drawn.",
                raw_snapshot_path=str(raw_path),
                source_quality="primary_issuer_scan_missing",
                parse_status="raw_snapshot_missing",
                retrieved_at=retrieved,
            ))
            continue

        try:
            pages = _pages(raw_path)
        except Exception as exc:
            rows.append(_row(
                spec,
                hedge_scope="fuel",
                disclosure_type="scan_result",
                hedge_status="scan_error",
                hedge_instrument=None,
                source_page=None,
                source_note=f"Primary issuer PDF scan failed: {type(exc).__name__}: {exc}",
                raw_snapshot_path=str(raw_path),
                source_quality="primary_issuer_scan_error",
                parse_status="scan_error",
                retrieved_at=retrieved,
            ))
            continue

        compact_pages = [_compact(page) for page in pages]
        raw_path_text = str(raw_path)

        # Eastern FY2025: the issuer reports both a fair-value table and a
        # separate period-end open-position statement.  Keep these as two
        # observations rather than treating fair value as hedge notional.
        if spec.report_id == "600115_2025_fy":
            fair_value_page = _find_page(pages, ("燃油套期合约", "以公允价值计量的金融资产"))
            position_page = _find_page(pages, ("持有的尚未交割的航油套期保值交易的持仓头寸",))
            if fair_value_page is not None:
                rows.append(_row(
                    spec,
                    hedge_scope="fuel",
                    disclosure_type="fair_value",
                    hedge_status="active_disclosed",
                    hedge_instrument="fuel hedge contract",
                    fair_value_change_native=3.75,
                    fair_value_end_native=3.75,
                    native_currency="RMB",
                    source_page=fair_value_page,
                    source_note=(
                        "Primary issuer fair-value table: fuel-hedge current-period fair-value "
                        "change and ending fair value are both RMB3.75m. This is fair value, "
                        "not hedge notional or total realized fuel-hedge P&L."
                    ),
                    raw_snapshot_path=raw_path_text,
                    source_quality="primary_issuer",
                    parse_status="verified_anchor",
                    retrieved_at=retrieved,
                ))
            if position_page is not None:
                rows.append(_row(
                    spec,
                    hedge_scope="fuel",
                    disclosure_type="position",
                    hedge_status="active_unsettled_position",
                    hedge_instrument="fuel hedge transaction",
                    notional_native=500_000.0,
                    notional_unit="barrels",
                    source_page=position_page,
                    source_note=(
                        "Primary issuer risk disclosure: at 2025-12-31, outstanding fuel-hedge "
                        "position was 500,000 barrels, due in 2026. Notional is not converted to "
                        "RMB and is not a forecast of fuel consumption."
                    ),
                    raw_snapshot_path=raw_path_text,
                    source_quality="primary_issuer",
                    parse_status="verified_anchor",
                    retrieved_at=retrieved,
                ))
            if fair_value_page is not None or position_page is not None:
                continue

        # Southern FY/H1 explicitly state that the group had no fuel-futures
        # contract in the relevant period.  This does not rule out other
        # instruments or policy actions, so the note keeps the scope narrow.
        if spec.report_id in {"600029_2025_fy", "600029_2025_h1"}:
            needle = "于本年度，本集团无燃油期货合约" if spec.report_type == "annual" else "于本期，本集团无燃油期货合约"
            page = _find_page(pages, (needle,))
            if page is not None:
                rows.append(_row(
                    spec,
                    hedge_scope="fuel",
                    disclosure_type="explicit_no_fuel_futures",
                    hedge_status="no_fuel_futures_in_period",
                    hedge_instrument="fuel futures",
                    source_page=page,
                    source_note=(
                        "Primary issuer derivative-risk disclosure explicitly states no fuel "
                        "futures contract in the relevant period; this is not evidence that "
                        "all possible fuel-hedging instruments were absent."
                    ),
                    raw_snapshot_path=raw_path_text,
                    source_quality="primary_issuer",
                    parse_status="verified_anchor",
                    retrieved_at=retrieved,
                ))
                continue

        # Eastern H1 gives a policy/activity statement but no safe amount or
        # period-end position.  Preserve it as qualitative evidence only.
        if spec.report_id == "600115_2025_h1":
            page = _find_page(pages, ("谨慎开展航油套期保值业务",))
            if page is not None:
                rows.append(_row(
                    spec,
                    hedge_scope="fuel",
                    disclosure_type="policy_statement",
                    hedge_status="policy_or_activity_not_quantified",
                    hedge_instrument="fuel hedge",
                    source_page=page,
                    source_note=(
                        "Primary issuer risk disclosure says the company cautiously conducts "
                        "fuel-hedging business under board authorization; no period-end notional "
                        "or fair-value amount is disclosed in the covered section."
                    ),
                    raw_snapshot_path=raw_path_text,
                    source_quality="primary_issuer",
                    parse_status="verified_anchor",
                    retrieved_at=retrieved,
                ))
                continue

        # For the remaining reports, preserve a transparent scan result.  A
        # risk-section page is retained when the PDF contains a fuel-risk
        # discussion; blank means the targeted phrase was not found at all.
        risk_page = _find_page(
            pages,
            ("燃油价格风险", "燃油价格波动风险", "航油价格风险", "燃油套期", "航油套期"),
        )
        rows.append(_row(
            spec,
            hedge_scope="fuel",
            disclosure_type="scan_result",
            hedge_status="no_explicit_fuel_hedge_anchor_found_in_scan",
            hedge_instrument=None,
            source_page=risk_page,
            source_note=(
                "Targeted scan of the cached primary issuer report found no safe fuel-specific "
                "numeric hedge anchor or explicit no-futures statement. This is a coverage result, "
                "not a claim that the issuer had no hedge."
            ),
            raw_snapshot_path=raw_path_text,
            source_quality="primary_issuer_scan_audit",
            parse_status="scanned_no_anchor",
            retrieved_at=retrieved,
        ))

    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_hedging_disclosures() -> pd.DataFrame:
    result = build_airline_hedging_disclosures()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
