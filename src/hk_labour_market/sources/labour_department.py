"""Machine-readable Labour Department labour-supply policy sources."""

from __future__ import annotations

from datetime import datetime, timezone
from xml.etree import ElementTree

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS

ESLS_KEY_STATISTICS_URL = "https://www.labour.gov.hk/datagovhk/resource/sls/sls-keystats_en.xml"
ESLS_SOURCE_ID = "labour_department_esls_key_statistics"


class LabourDepartmentFetchError(RuntimeError):
    """Raised for an HTTP-successful but unusable Labour Department payload."""

    def __init__(self, message: str, *, raw_body: str | None = None) -> None:
        super().__init__(message)
        self.raw_body = raw_body


def fetch_esls_key_statistics(timeout: int = 60) -> tuple[str, pd.DataFrame]:
    """Fetch annual SLS/ESLS application counts from Labour Department XML."""
    response = requests.get(ESLS_KEY_STATISTICS_URL, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    raw_xml = response.text
    try:
        root = ElementTree.fromstring(raw_xml)
    except ElementTree.ParseError as exc:
        raise LabourDepartmentFetchError("ESLS XML could not be parsed", raw_body=raw_xml) from exc
    retrieved_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for item in root.findall("item"):
        year = (item.findtext("year") or "").strip()
        value = pd.to_numeric(pd.Series([(item.findtext("no_of_app") or "").strip()]), errors="coerce").iloc[0]
        if not (year.isdigit() and len(year) == 4):
            continue
        rows.append(
            {
                "source_table_id": ESLS_SOURCE_ID,
                "source_title": "Key Statistics of Supplementary Labour Scheme/Enhanced Supplementary Labour Scheme",
                "source_url": ESLS_KEY_STATISTICS_URL,
                "period": year,
                "period_end": f"{year}-12-31",
                "frequency_code": "Y",
                "frequency_label": "annual",
                "metric_code": "applications_received",
                "metric_label": "No. of applications",
                "dimension_key": "{}",
                "source_dimensions_json": "{}",
                "value": None if pd.isna(value) else float(value),
                "status_flag": None,
                "retrieved_at": retrieved_at,
                "data_source": "official_labour_department_open_data",
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("ESLS XML contained no valid annual application records")
    return raw_xml, frame
