"""Recover airline KPI gaps caused by known PDF extraction failures.

This is deliberately separate from interpolation.  It re-parses the cached
official CNINFO PDFs after the parser repair, overlays only the affected
company/month/metric/region keys, and writes a source-recovered layer while
leaving the original processed archive untouched.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.scrape_cn_airline_traffic import _pdf_text, parse_airline_pdf  # noqa: E402

RAW_MONTHLY_PATH = ROOT / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"
REGISTRY_PATH = ROOT / "data" / "normalized" / "hk_transport" / "airline_operating_release_registry.csv"
PDF_ROOT = ROOT / "data" / "raw" / "airline_pdfs"
RECOVERED_PATH = ROOT / "data" / "normalized" / "hk_transport" / "airline_operating_kpi_source_recovered.parquet"
AUDIT_PATH = ROOT / "data" / "normalized" / "hk_transport" / "airline_operating_kpi_source_recovery_audit.csv"

RECOVERY_TARGETS = (
    {
        "airline_code": "600029",
        "month": "2019-06",
        "metrics": {
            "aftk",
            "ask",
            "atk",
            "cargo_tonnes",
            "overall_load_factor_pct",
            "passenger_load_factor_pct",
            "passengers",
            "rftk",
            "rpk",
            "rtk",
        },
        "reason": "PDF page-break shifted the first value of each block into the header row; official table arithmetic and labels validate the repair.",
    },
    {
        "airline_code": "603885",
        "month": "2019-12",
        "metrics": {"ask"},
        "reason": "ASK unit continuation row starts on the next PDF page; preserving the active header recovers the regional values.",
    },
    {
        "airline_code": "603885",
        "month": "2020-02",
        "metrics": {"rpk"},
        "reason": "RPK unit/code continuation row starts on the next PDF page; preserving the active header and applying the stated unit recovers the regional values.",
    },
)

# Parser repairs can be correct without automatically changing the historical
# processed archive.  These cached-PDF keys are therefore overlaid into the
# source-recovered layer as well, so the backtest does not replace a visible
# official value with a future interpolation merely because the raw materializer
# predates the parser repair.
PARSER_GAP_RECOVERY_TARGETS = (
    *(
        {
            "airline_code": "603885",
            "month": month,
            "metrics": {"ask"},
            "reason": "The repaired parser now extracts the ASK regional rows from the official PDF; the retained raw archive predates that parser repair.",
        }
        for month in ("2017-06", "2018-01", "2018-07", "2018-11", "2018-12", "2019-02", "2019-03", "2019-08", "2019-09", "2023-10")
    ),
    *(
        {
            "airline_code": "603885",
            "month": month,
            "metrics": {"rpk"},
            "reason": "The repaired parser now extracts the RPK regional rows from the official PDF; the retained raw archive predates that parser repair.",
        }
        for month in ("2018-04", "2019-04", "2020-10", "2021-10")
    ),
    {
        "airline_code": "600115",
        "month": "2023-06",
        "metrics": {"rpk"},
        "reason": "The repaired parser now extracts the RPK row from the official PDF; the retained raw archive predates that parser repair.",
    },
    {
        "airline_code": "601021",
        "month": "2016-03",
        "metrics": {"ask", "rpk"},
        "reason": "The repaired parser now extracts the ASK/RPK rows from the official PDF; the retained raw archive predates that parser repair.",
    },
    {
        "airline_code": "601111",
        "month": "2021-08",
        "metrics": {"ask"},
        "reason": "The repaired parser now extracts the ASK rows from the official PDF; the retained raw archive predates that parser repair.",
    },
    {
        "airline_code": "601111",
        "month": "2023-12",
        "metrics": {"rpk"},
        "reason": "The repaired parser now extracts the RPK rows from the official PDF; the retained raw archive predates that parser repair.",
    },
    *(
        {
            "airline_code": "600029",
            "month": month,
            "metrics": {"aftk"},
            "reason": "The official PDF contains the AFTK regional rows; the raw parser archive omitted the recoverable table values.",
        }
        for month in ("2020-01", "2020-10")
    ),
    *(
        {
            "airline_code": "600029",
            "month": month,
            "metrics": {"freight_load_factor_pct"},
            "reason": "The official PDF contains the freight-load-factor regional rows; the raw parser archive omitted the recoverable table values.",
        }
        for month in ("2017-10", "2020-02", "2020-09")
    ),
    *(
        {
            "airline_code": "600029",
            "month": month,
            "metrics": {"rftk"},
            "reason": "The official PDF contains the RFTK regional rows; the raw parser archive omitted the recoverable table values.",
        }
        for month in ("2020-12", "2021-05", "2021-07")
    ),
    *(
        {
            "airline_code": "603885",
            "month": month,
            "metrics": {"aftk"},
            "reason": "The repaired parser now extracts the AFTK table from the official PDF; the retained raw archive had been filling this source value by interpolation.",
        }
        for month in ("2020-12", "2023-12", "2024-01")
    ),
    *(
        {
            "airline_code": "600115",
            "month": month,
            "metrics": {"aftk"},
            "reason": "The repaired parser now recognizes the abbreviated AFTK header in the official PDF; the retained raw archive had been filling this source value by interpolation.",
        }
        for month in ("2025-05", "2025-07")
    ),
    {
        "airline_code": "601111",
        "month": "2023-10",
        "metrics": {"rftk"},
        "reason": "The repaired parser now recovers the RFTK header/Total and page-three regional rows from the official PDF text layer.",
    },
    *(
        {
            "airline_code": "601021",
            "month": month,
            "metrics": {"freight_load_factor_pct"},
            "reason": "The repaired parser now reads the current-period freight load factor from the PDF's third value column instead of recording a zero from a blank cell.",
        }
        for month in ("2016-04", "2017-04", "2018-02")
    ),
)

# Keep the known PDF recoveries and parser-gap recoveries in one execution
# path, while retaining separate reasons in the audit.
RECOVERY_TARGETS = (*RECOVERY_TARGETS, *PARSER_GAP_RECOVERY_TARGETS)

UNDISCLOSED_TARGETS = tuple(
    {
        "airline_code": "603885",
        "month": f"2016-{month:02d}",
        "metric": metric,
        "reason": "The official monthly PDF discloses ATK/RTK/RFTK and cargo tonnage but does not disclose AFTK; freight load factor cannot be derived without AFTK.",
    }
    for month in range(1, 12)
    for metric in ("aftk", "freight_load_factor_pct")
)

# These are deliberately kept in the recovery audit rather than inferred from
# the normalized parquet.  The point of the audit is to compare the visible
# source PDF with parser output and make a parser-vs-disclosure decision.
_SOURCE_DISCLOSURE_KEYWORDS = {
    "ask": (
        "可用座位公里", "可利用座位公里", "可用座公里", "可利用座公里",
        "可用客公里", "座位公里",
    ),
    "rpk": (
        "收入客公里", "收入乘客公里", "客运收入客公里", "客运人公里",
        "旅客周转量",
    ),
    "passengers": (
        "旅客运输量", "旅客人数", "运输旅客", "客运量", "载运旅客人次",
    ),
    "passenger_load_factor_pct": ("客座率", "客座利用率"),
    "overall_load_factor_pct": ("综合载运率", "综合载客率", "总体载运率"),
    "aftk": (
        "可用货运吨公里", "可用货邮吨公里", "可用货邮吨公里数",
        "可利用货邮吨公里", "可利用吨公里——货邮运", "可利用吨公里—货邮运",
        "可利用吨公里-货邮运",
    ),
    "freight_load_factor_pct": ("货物及邮件载运率", "货邮载运率"),
    "atk": ("可利用吨公里数", "可利用吨公里", "可用吨公里数", "可用吨公里"),
    "rtk": ("运输周转量", "收入吨公里"),
    "rftk": ("货邮周转量", "收入货运吨公里", "收入货邮吨公里", "货邮载运吨公里"),
    "cargo_tonnes": ("货邮载重量", "货邮载运量", "货物及邮件数量", "货物及邮件"),
}


def _source_metric_evidence(
    pdf_bytes: bytes,
    parsed_rows: list[dict],
    metric: str,
) -> dict[str, object]:
    """Compare visible PDF wording with parser output for one metric.

    A missing normalized row is not enough to call a parser bug: an issuer can
    omit a KPI entirely.  This small evidence record preserves both sides of
    that decision and is also useful when a future parser change alters the
    result.  Whitespace is removed only for keyword matching; the original PDF
    path remains in the audit for human review.
    """
    text = re.sub(r"\s+", "", _pdf_text(pdf_bytes))
    keywords = _SOURCE_DISCLOSURE_KEYWORDS.get(metric, ())
    matched = [keyword for keyword in keywords if keyword.replace(" ", "") in text]
    parser_rows = [row for row in parsed_rows if row.get("metric") == metric]
    source_present = bool(matched)
    parser_present = bool(parser_rows)
    if source_present and not parser_present:
        decision = "parser_gap"
    elif source_present and parser_present:
        decision = "parsed_from_source"
    elif not source_present and not parser_present:
        decision = "not_disclosed_in_source_pdf"
    else:
        # The parser can recognize an issuer synonym that is not yet in the
        # audit keyword dictionary.  That is a source-keyword coverage note,
        # not evidence that the source failed to disclose the metric.
        decision = "parsed_without_keyword_match"
    return {
        "source_text_metric_present": source_present,
        "source_text_keyword_matches": ";".join(matched) if matched else None,
        "parser_metric_present": parser_present,
        "parser_metric_row_count": len(parser_rows),
        "parser_metric_regions": ";".join(
            sorted({str(row.get("region")) for row in parser_rows})
        ) if parser_rows else None,
        "disclosure_check": decision,
    }


def _companion_evidence(parsed_rows: list[dict]) -> str:
    """Return the metrics actually emitted from the same source PDF."""
    return ";".join(sorted({str(row.get("metric")) for row in parsed_rows if row.get("metric")}))


def _key_frame(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["month"].astype(str)
        + "|"
        + frame["airline_code"].astype(str).str.zfill(6)
        + "|"
        + frame["region"].astype(str)
        + "|"
        + frame["metric"].astype(str)
    )


def _registry_lookup() -> pd.DataFrame:
    registry = pd.read_csv(REGISTRY_PATH, dtype={"airline_code": str})
    registry["airline_code"] = registry["airline_code"].astype(str).str.zfill(6)
    return registry.set_index(["airline_code", "month"])


def recover_cached_source_gaps(
    frame: pd.DataFrame | None = None,
    *,
    retrieved_at: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the source-recovered monthly panel and an auditable recovery log."""
    raw = pd.read_parquet(RAW_MONTHLY_PATH) if frame is None else frame.copy()
    registry = _registry_lookup()
    recovered_rows: list[dict] = []
    audit_rows: list[dict] = []
    retrieved = retrieved_at or dt.datetime.now(dt.timezone.utc).isoformat()

    for target in RECOVERY_TARGETS:
        code = target["airline_code"]
        month = target["month"]
        try:
            release = registry.loc[(code, month)]
        except KeyError as exc:
            raise RuntimeError(f"No release registry row for {code} {month}") from exc
        pdf_path = PDF_ROOT / code / f"{int(release['announcement_id'])}.PDF"
        if not pdf_path.exists():
            raise FileNotFoundError(f"Cached official PDF not found: {pdf_path}")

        pdf_bytes = pdf_path.read_bytes()
        parsed = parse_airline_pdf(pdf_bytes, code, month)
        rows = [row for row in parsed if row["metric"] in target["metrics"]]
        if not rows:
            raise RuntimeError(
                f"Recovery parser returned no target rows for {code} {month}: {sorted(target['metrics'])}"
            )

        source_metadata = {
            "announcement_date": release.get("announcement_date"),
            "announcement_time": release.get("announcement_time"),
            "announcement_id": release.get("announcement_id"),
            "announcement_title": release.get("announcement_title"),
            "source_pdf_url": release.get("source_pdf_url"),
            "source_quality": "issuer_cninfo_operating_release_recovered",
            "retrieved_at": retrieved,
        }
        for row in rows:
            row = {**row, **source_metadata}
            row.setdefault("recovery_method", "source_pdf_recovery")
            row.setdefault("recovery_note", target["reason"])
            recovered_rows.append(row)
            evidence = _source_metric_evidence(pdf_bytes, parsed, str(row["metric"]))
            # Every row in RECOVERY_TARGETS is a known within-PDF extraction
            # failure, regardless of whether the repaired parser now returns
            # the row and regardless of the keyword dictionary's coverage.
            # Keep this historical classification explicit instead of letting
            # the post-repair parser result erase the original parser gap.
            evidence["disclosure_check"] = "parser_gap_recovered"
            audit_rows.append(
                {
                    "status": "recovered_from_cached_official_pdf",
                    "airline_code": code,
                    "month": month,
                    "metric": row["metric"],
                    "region": row["region"],
                    "value": row["value"],
                    "recovery_method": row.get("recovery_method"),
                    "reason": target["reason"],
                    "announcement_date": release.get("announcement_date"),
                    "announcement_id": release.get("announcement_id"),
                    "source_pdf_url": release.get("source_pdf_url"),
                    "source_pdf_path": str(pdf_path),
                    "companion_parser_metrics": _companion_evidence(parsed),
                    **evidence,
                    "retrieved_at": retrieved,
                }
            )

    for target in UNDISCLOSED_TARGETS:
        code = target["airline_code"]
        month = target["month"]
        release = registry.loc[(code, month)]
        pdf_path = PDF_ROOT / code / f"{int(release['announcement_id'])}.PDF"
        pdf_bytes = pdf_path.read_bytes()
        parsed = parse_airline_pdf(pdf_bytes, code, month)
        evidence = _source_metric_evidence(pdf_bytes, parsed, str(target["metric"]))
        audit_rows.append(
            {
                "status": "not_disclosed_in_source_pdf",
                "airline_code": code,
                "month": month,
                "metric": target["metric"],
                "region": "Total",
                "value": None,
                "recovery_method": "not_applicable",
                "reason": target["reason"],
                "announcement_date": release.get("announcement_date"),
                "announcement_id": release.get("announcement_id"),
                "source_pdf_url": release.get("source_pdf_url"),
                "source_pdf_path": str(pdf_path),
                "companion_parser_metrics": _companion_evidence(parsed),
                **evidence,
                "retrieved_at": retrieved,
            }
        )

    recovered = pd.DataFrame(recovered_rows)
    recovery_keys = set(_key_frame(recovered).tolist())
    raw_without_targets = raw.loc[~_key_frame(raw).isin(recovery_keys)].copy()
    combined = pd.concat([raw_without_targets, recovered], ignore_index=True, sort=False)
    combined["airline_code"] = combined["airline_code"].astype(str).str.zfill(6)
    combined = combined.drop_duplicates(
        subset=["month", "airline_code", "region", "metric"],
        keep="last",
    ).sort_values(["month", "airline_code", "metric", "region"]).reset_index(drop=True)
    for column in (
        "announcement_date",
        "announcement_time",
        "announcement_id",
        "announcement_title",
        "source_pdf_url",
        "source_quality",
        "retrieved_at",
        "recovery_method",
        "recovery_note",
    ):
        if column in combined.columns:
            combined[column] = combined[column].where(
                combined[column].notna(), None
            ).astype(object)
            combined[column] = combined[column].map(
                lambda value: str(value) if value is not None else None
            )
    audit = pd.DataFrame(audit_rows).sort_values(
        ["status", "airline_code", "month", "metric", "region"]
    ).reset_index(drop=True)
    return combined, audit


def fetch_airline_operating_kpi_source_recovered() -> pd.DataFrame:
    recovered, audit = recover_cached_source_gaps()
    RECOVERED_PATH.parent.mkdir(parents=True, exist_ok=True)
    recovered.to_parquet(RECOVERED_PATH, index=False)
    audit.to_csv(AUDIT_PATH, index=False)
    print(
        f"Built source-recovered airline KPI layer: rows={len(recovered)}, "
        f"recovered_rows={int((audit.status == 'recovered_from_cached_official_pdf').sum())}, "
        f"not_disclosed={int((audit.status == 'not_disclosed_in_source_pdf').sum())}"
    )
    return recovered


if __name__ == "__main__":
    fetch_airline_operating_kpi_source_recovered()
