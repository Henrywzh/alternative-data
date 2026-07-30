"""Immigration Department annual employment-policy open-data CSVs.

The source files are intentionally normalized to a long format.  Most files
have two count columns (received/approved); QMAS also publishes a quota count
and optional breakdown columns.  Keeping the source column as a dimension
prevents those distinct concepts from being silently merged.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
import json
import re

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS

EMPLOYMENT_POLICY_SOURCES = (
    {
        "dataset_id": "immd_gep_applications_annual",
        "source_table_id": "immd_gep_applications",
        "scheme": "General Employment Policy",
        "source_title": "Annual applications received and approved under General Employment Policy",
        "url": "https://www.immd.gov.hk/opendata/eng/law-and-security/visas/Statistics_Applications_Received_Approved_GEP_EN.csv",
    },
    {
        "dataset_id": "immd_asmtp_applications_annual",
        "source_table_id": "immd_asmtp_applications",
        "scheme": "Admission Scheme for Mainland Talents and Professionals",
        "source_title": "Annual applications received and approved under Admission Scheme for Mainland Talents and Professionals",
        "url": "https://www.immd.gov.hk/opendata/eng/law-and-security/visas/Statistics_Applications_Received_Approved_ASMTP_EN.csv",
    },
    {
        "dataset_id": "immd_techtas_applications_annual",
        "source_table_id": "immd_techtas_applications",
        "scheme": "Technology Talent Admission Scheme",
        "source_title": "Annual applications received and approved under Technology Talent Admission Scheme",
        "url": "https://www.immd.gov.hk/opendata/eng/law-and-security/visas/Statistics_Applications_Received_Approved_TechTAS_EN.csv",
    },
    {
        "dataset_id": "immd_ttps_applications_annual",
        "source_table_id": "immd_ttps_applications",
        "scheme": "Top Talent Pass Scheme",
        "source_title": "Annual applications received and approved under Top Talent Pass Scheme",
        "url": "https://www.immd.gov.hk/opendata/eng/law-and-security/visas/statistics_applications_received_approved_TTPS.csv",
    },
    {
        "dataset_id": "immd_iang_applications_annual",
        "source_table_id": "immd_iang_applications",
        "scheme": "Immigration Arrangements for Non-local Graduates",
        "source_title": "Annual applications received and approved under Immigration Arrangements for Non-local Graduates",
        "url": "https://www.immd.gov.hk/opendata/eng/law-and-security/visas/Statistics_Applications_Received_Approved_IANG_EN.csv",
    },
    {
        "dataset_id": "immd_assg_applications_annual",
        "source_table_id": "immd_assg_applications",
        "scheme": "Admission Scheme for the Second Generation of Chinese Hong Kong Permanent Residents",
        "source_title": "Annual applications received and approved under Admission Scheme for the Second Generation of Chinese Hong Kong Permanent Residents",
        "url": "https://www.immd.gov.hk/opendata/eng/law-and-security/visas/Statistics_Applications_Received_Approved_ASSG_EN.csv",
    },
    {
        "dataset_id": "immd_qmas_applications_annual",
        "source_table_id": "immd_qmas_applications",
        "scheme": "Quality Migrant Admission Scheme",
        "source_title": "Annual applications received and quota allotted under Quality Migrant Admission Scheme",
        "url": "https://www.immd.gov.hk/opendata/eng/law-and-security/visas/Statistics_Received_Quota_Allotted_QMAS_EN.csv",
    },
    {
        "dataset_id": "immd_qmas_industry_annual",
        "source_table_id": "immd_qmas_industry",
        "scheme": "Quality Migrant Admission Scheme",
        "breakdown_type": "industry_sector",
        "source_title": "Annual quota allotted under Quality Migrant Admission Scheme by industry/sector",
        "url": "https://www.immd.gov.hk/opendata/eng/law-and-security/visas/Statistics_Quota_Allotted_QMAS_Industry_Sector_EN.csv",
    },
    {
        "dataset_id": "immd_qmas_region_annual",
        "source_table_id": "immd_qmas_region",
        "scheme": "Quality Migrant Admission Scheme",
        "breakdown_type": "applicant_region",
        "source_title": "Annual quota allotted under Quality Migrant Admission Scheme by applicant region",
        # The DATA.GOV.HK English resource currently returns 404 while the
        # official simplified-Chinese file is live and has the same numbers.
        "url": "https://www.immd.gov.hk/opendata/hks/law-and-security/visas/Statistics_Quota_Allotted_QMAS_region_SC.csv",
    },
    {
        "dataset_id": "immd_qmas_academic_annual",
        "source_table_id": "immd_qmas_academic_qualification",
        "scheme": "Quality Migrant Admission Scheme",
        "breakdown_type": "academic_qualification",
        "source_title": "Annual quota allotted under Quality Migrant Admission Scheme by academic qualification",
        "url": "https://www.immd.gov.hk/opendata/eng/law-and-security/visas/Statistics_Quota_Allotted_QMAS_academic_qualification_EN.csv",
    },
)


class ImmigrationEmploymentFetchError(RuntimeError):
    """Raised for an HTTP-successful but unusable Immigration Department CSV."""

    def __init__(self, message: str, *, raw_body: str | None = None) -> None:
        super().__init__(message)
        self.raw_body = raw_body


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return text or "unknown"


def _metric_code(column: str, *, breakdown_type: str | None) -> str:
    """Assign a stable metric code without throwing away the source label."""
    lowered = column.lower()
    if "received" in lowered:
        return "applications_received"
    if "approved" in lowered:
        return "applications_approved"
    if "quota" in lowered or breakdown_type:
        return "quota_allotted"
    return _slug(column)


def _dimension_label(column: str, *, breakdown_type: str | None) -> str:
    if not breakdown_type:
        return "All applicants"
    if column.strip().lower() == "total":
        return "Total"
    return column.strip()


def _metric_label(column: str, *, scheme: str, breakdown_type: str | None) -> str:
    if breakdown_type:
        return f"Quota allotted under {scheme}"
    return column.strip()


def _decode_csv(content: bytes) -> str:
    encodings = ("utf-8-sig", "utf-16", "cp950")
    for encoding in encodings:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("csv", content, 0, len(content), "unsupported CSV encoding")


def _year_text(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text if text.isdigit() and len(text) == 4 else None


def _number(value: object) -> float | None:
    if pd.isna(value):
        return None
    parsed = pd.to_numeric(str(value).replace(",", "").strip(), errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def fetch_employment_policy_source(source: dict[str, str], timeout: int = 60) -> tuple[str, pd.DataFrame]:
    response = requests.get(source["url"], headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    try:
        raw_csv = _decode_csv(response.content)
    except UnicodeDecodeError as exc:
        raise ImmigrationEmploymentFetchError("Immigration Department CSV encoding is unsupported", raw_body=response.content.decode("utf-8", errors="replace")) from exc
    try:
        source_frame = pd.read_csv(StringIO(raw_csv), on_bad_lines="error")
    except (pd.errors.ParserError, ValueError) as exc:
        raise ImmigrationEmploymentFetchError("Immigration Department CSV could not be parsed", raw_body=raw_csv) from exc
    if source_frame.shape[1] < 2:
        raise ImmigrationEmploymentFetchError(f"{source['dataset_id']} has fewer than two CSV columns", raw_body=raw_csv)
    year_col = source_frame.columns[0]
    breakdown_type = source.get("breakdown_type")
    metric_columns = [
        column
        for column in source_frame.columns[1:]
        if "remark" not in column.lower() and "备注" not in column
    ]
    if not metric_columns:
        raise ImmigrationEmploymentFetchError(f"{source['dataset_id']} contained no metric columns", raw_body=raw_csv)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for _, record in source_frame.iterrows():
        year = _year_text(record[year_col])
        if year is None:
            continue
        for column in metric_columns:
            value = _number(record[column])
            if value is None:
                continue
            metric_code = _metric_code(column, breakdown_type=breakdown_type)
            dimension_label = _dimension_label(column, breakdown_type=breakdown_type)
            dimensions = {
                "scheme": source["scheme"],
                "breakdown_type": breakdown_type,
                "dimension": dimension_label,
            }
            dimensions = {key: value for key, value in dimensions.items() if value is not None}
            rows.append(
                {
                    "source_table_id": source["source_table_id"],
                    "source_title": source.get(
                        "source_title",
                        f"Annual applications received and approved under {source['scheme']}",
                    ),
                    "source_url": source["url"],
                    "period": year,
                    "period_end": f"{year}-12-31",
                    "frequency_code": "Y",
                    "frequency_label": "annual",
                    "metric_code": metric_code,
                    "metric_label": _metric_label(column, scheme=source["scheme"], breakdown_type=breakdown_type),
                    "dimension_type": breakdown_type or "scheme",
                    "dimension_label": dimension_label,
                    "dimension_key": json.dumps(dimensions, ensure_ascii=False, sort_keys=True),
                    "source_dimensions_json": json.dumps(dimensions, ensure_ascii=False, sort_keys=True),
                    "value": value,
                    "status_flag": None,
                    "retrieved_at": retrieved_at,
                    "data_source": "official_immd_open_data",
                }
            )
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ImmigrationEmploymentFetchError(f"{source['dataset_id']} contained no annual observations", raw_body=raw_csv)
    return raw_csv, frame
