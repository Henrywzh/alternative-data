"""Free monthly China trade proxy for airline cargo-demand research.

The Ministry of Commerce (MOFCOM) data centre exposes a small JSON endpoint
behind its public ``货物进出口月度统计`` page.  It reports monthly total trade,
exports, imports and year-on-year changes in USD 100 million.  This is not an
airline cargo revenue series: it is a broad external demand/shipping-cycle
proxy which should be combined with issuer cargo tonnes/CTK and cargo-revenue
disclosures when those are available.

The endpoint currently returns the latest available snapshot and does not
include the original release timestamp.  The normalized layer therefore
preserves retrieval date, leaves ``source_release_date`` null, and marks the
point-in-time status as a retrieved-vintage-only observation.  Historical
rows are not silently overwritten; a new retrieval date creates a new vintage
in the local history.
"""

from __future__ import annotations

import re
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from urllib3.exceptions import InsecureRequestWarning

from ..config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    MOFCOM_MONTHLY_TRADE_PAGE_URL,
    MOFCOM_MONTHLY_TRADE_QUERY_URL,
    NORMALIZED_DIR,
)
from ..storage import save_raw_snapshot


OUTPUT_PATH = NORMALIZED_DIR / "airline_cargo_demand_proxies.csv"
DATASET_ID = "airline_cargo_demand_proxies"
REQUIRED_INPUT_FIELDS = ("trade_date", "total_value", "export_value", "import_value")

OUTPUT_COLUMNS = [
    "dataset_id",
    "source_organization",
    "source_document_type",
    "source_url",
    "observation_month",
    "period_end",
    "trade_date_raw",
    "total_trade_value_usd_100m",
    "export_value_usd_100m",
    "import_value_usd_100m",
    "trade_balance_usd_100m",
    "total_trade_yoy_pct",
    "export_yoy_pct",
    "import_yoy_pct",
    "total_trade_cumulative_usd_100m",
    "export_cumulative_usd_100m",
    "import_cumulative_usd_100m",
    "trade_balance_cumulative_usd_100m",
    "source_release_date",
    "source_release_date_status",
    "point_in_time_status",
    "revision_semantics",
    "source_quality",
    "source_snapshot_date",
    "retrieved_at",
]


def _number(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    parsed = pd.to_numeric(str(value).replace(",", ""), errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    """Extract the row list from the current endpoint shape.

    The current response is ``[rows, chart_config]``.  Supporting a mapping
    with a nested ``data`` key makes the parser robust to a small front-end
    API change without weakening validation of the row schema.
    """
    rows: Any = payload
    if isinstance(payload, list):
        if payload and isinstance(payload[0], list):
            rows = payload[0]
        elif payload and isinstance(payload[0], dict):
            rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("data", payload.get("rows", payload.get("list")))
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("MOFCOM monthly trade payload does not contain a row list")
    return rows


def _period_end(trade_date: str) -> tuple[str, str]:
    value = str(trade_date).strip()
    if not re.fullmatch(r"\d{6}", value):
        raise ValueError(f"Invalid MOFCOM trade_date: {trade_date!r}")
    period = pd.to_datetime(f"{value[:4]}-{value[4:]}-01", errors="coerce")
    if pd.isna(period):
        raise ValueError(f"Invalid MOFCOM YYYYMM trade_date: {trade_date!r}")
    return period.strftime("%Y-%m"), period.to_period("M").end_time.strftime("%Y-%m-%d")


def parse_mofcom_totalmonth_payload(
    payload: Any,
    *,
    retrieved_at: str | None = None,
    source_url: str = MOFCOM_MONTHLY_TRADE_QUERY_URL,
) -> pd.DataFrame:
    """Parse the public MOFCOM total-month response into one row per month."""
    rows = _rows_from_payload(payload)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    snapshot_date = pd.Timestamp(retrieved).strftime("%Y-%m-%d")
    normalized: list[dict[str, Any]] = []
    for raw in rows:
        missing = [field for field in REQUIRED_INPUT_FIELDS if field not in raw]
        if missing:
            raise ValueError(f"MOFCOM monthly trade row is missing fields: {missing}")
        observation_month, period_end = _period_end(raw["trade_date"])
        export_value = _number(raw.get("export_value"))
        import_value = _number(raw.get("import_value"))
        balance = (
            export_value - import_value
            if export_value is not None and import_value is not None
            else _number(raw.get("imexgap_value"))
        )
        normalized.append(
            {
                "dataset_id": DATASET_ID,
                "source_organization": "MOFCOM Data Center",
                "source_document_type": "monthly_goods_trade_statistics",
                "source_url": source_url,
                "observation_month": observation_month,
                "period_end": period_end,
                "trade_date_raw": str(raw["trade_date"]).strip(),
                "total_trade_value_usd_100m": _number(raw.get("total_value")),
                "export_value_usd_100m": export_value,
                "import_value_usd_100m": import_value,
                "trade_balance_usd_100m": balance,
                "total_trade_yoy_pct": _number(raw.get("total_per")),
                "export_yoy_pct": _number(raw.get("export_per")),
                "import_yoy_pct": _number(raw.get("import_per")),
                "total_trade_cumulative_usd_100m": _number(raw.get("total_lj_value")),
                "export_cumulative_usd_100m": _number(raw.get("export_lj_value")),
                "import_cumulative_usd_100m": _number(raw.get("import_lj_value")),
                "trade_balance_cumulative_usd_100m": _number(raw.get("imexgap_lj_value")),
                "source_release_date": None,
                "source_release_date_status": "not_exposed_by_endpoint",
                "point_in_time_status": "retrieved_vintage_only_latest_snapshot",
                "revision_semantics": "latest_mofcom_snapshot_historical_rows_may_be_revised",
                "source_quality": "mofcom_primary_open_data_trade_aggregation",
                "source_snapshot_date": snapshot_date,
                "retrieved_at": retrieved,
            }
        )
    result = pd.DataFrame(normalized, columns=OUTPUT_COLUMNS)
    if result.empty:
        raise ValueError("MOFCOM monthly trade payload contains no rows")
    if result["observation_month"].duplicated().any():
        # Duplicate months would make the downstream cargo proxy ambiguous.
        raise ValueError("MOFCOM monthly trade payload contains duplicate observation months")
    result = result.sort_values("observation_month").reset_index(drop=True)
    return result


def _merge_vintages(result: pd.DataFrame, output_path: Path = OUTPUT_PATH) -> pd.DataFrame:
    """Append a retrieval vintage while replacing only same-day duplicates."""
    if output_path.exists():
        prior = pd.read_csv(output_path)
        combined = pd.concat([prior, result], ignore_index=True)
    else:
        combined = result.copy()
    key = ["observation_month", "source_snapshot_date"]
    combined = combined.drop_duplicates(subset=key, keep="last")
    return combined.reindex(columns=OUTPUT_COLUMNS).sort_values(
        ["observation_month", "source_snapshot_date"]
    ).reset_index(drop=True)


def fetch_airline_cargo_demand_proxies() -> pd.DataFrame:
    """Fetch and persist the free MOFCOM monthly trade proxy."""
    headers = {
        **DEFAULT_HEADERS,
        "Referer": MOFCOM_MONTHLY_TRADE_PAGE_URL,
        "X-Requested-With": "XMLHttpRequest",
    }
    # The local execution environment currently cannot validate the Chinese
    # government site's certificate chain.  This matches the repository's
    # existing customs-source convention; source URL and raw snapshot are
    # preserved for audit.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", InsecureRequestWarning)
        response = requests.post(
            MOFCOM_MONTHLY_TRADE_QUERY_URL,
            headers=headers,
            timeout=max(DEFAULT_TIMEOUT, 30),
            verify=False,
        )
    response.raise_for_status()
    payload = response.json()
    retrieved = datetime.now(timezone.utc).isoformat()
    result = parse_mofcom_totalmonth_payload(
        payload,
        retrieved_at=retrieved,
        source_url=MOFCOM_MONTHLY_TRADE_QUERY_URL,
    )
    raw_path = save_raw_snapshot(
        "mofcom_totalmonth_trade",
        payload,
        file_ext="json",
        source_url=MOFCOM_MONTHLY_TRADE_QUERY_URL,
    )
    merged = _merge_vintages(result)
    merged.to_csv(OUTPUT_PATH, index=False)
    merged.attrs["raw_snapshot"] = str(raw_path)
    merged.attrs["source_page"] = MOFCOM_MONTHLY_TRADE_PAGE_URL
    merged.attrs["source_url"] = MOFCOM_MONTHLY_TRADE_QUERY_URL
    return merged


__all__ = [
    "OUTPUT_COLUMNS",
    "OUTPUT_PATH",
    "fetch_airline_cargo_demand_proxies",
    "parse_mofcom_totalmonth_payload",
]
