"""Water Supplies Department temporary water-suspension event feed.

The WSD feed is a current event snapshot refreshed every five minutes. It is
not a continuous water-consumption series: rows contain planned/emergency
notices, affected districts/addresses, start and resumption times, causes and
current status.

The upstream CSV is pipe-delimited and is occasionally published with a
missing separator between either the Traditional-Chinese district and English
nature fields or the Traditional-Chinese address and English cause fields.
The parser repairs those specific, recognizable defects and drops any other
malformed row rather than shifting status/address columns silently.
"""

from __future__ import annotations

import csv
import io
import logging
import shutil
import subprocess
from typing import Iterable

import pandas as pd
import requests

from ..config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    WSD_WATER_SUSPENSION_URL,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

RAW_COLUMNS = [
    "SUSPENSION_ID",
    "WATER_TYPE_DESCRIPTION",
    "WATER_TYPE_DESCRIPTION_ZHT",
    "DISTRICT_ENG",
    "DISTRICT_ZHT",
    "NATURE_DESCRIPTION",
    "NATURE_DESCRIPTION_ZHT",
    "SUSPENSION_DATE_TIME",
    "ACTUAL_RESUMPTION_DATE_TIME",
    "LONG_ADDRESS",
    "LONG_ADDRESS_ZHT",
    "CAUSE",
    "CAUSE_ZHT",
    "STATUS",
    "STATUS_ZHT",
]

SCHEMA_COLUMNS = [
    "suspension_id",
    "water_type",
    "district",
    "nature",
    "suspension_start",
    "suspension_date",
    "actual_resumption",
    "address",
    "cause",
    "status",
    "is_active",
]

_NATURE_VALUES = ("Planned", "Emergency")
_CAUSE_VALUES = (
    "Emergency repairing of water main/installation",
    "Improvement work of water main/installation",
    "Replacement and rehabilitation of water mains",
    "Tee connection works for new customer",
    "Valve exercise",
)


def _repair_missing_nature_separator(row: list[str]) -> list[str] | None:
    """Repair WSD's known 14-field district/nature separator defect."""
    if len(row) != len(RAW_COLUMNS) - 1:
        return None

    combined = row[4]
    for nature in _NATURE_VALUES:
        if combined.endswith(nature):
            district_zh = combined[: -len(nature)]
            return row[:4] + [district_zh, nature] + row[5:]

    # A second observed upstream defect omits the separator between the
    # Traditional-Chinese address and English cause field.
    combined = row[10]
    for cause in _CAUSE_VALUES:
        if combined.endswith(cause):
            address_zh = combined[: -len(cause)]
            return row[:10] + [address_zh, cause] + row[11:]
    return None


def _iter_normalized_rows(lines: Iterable[str]) -> Iterable[list[str]]:
    reader = csv.reader(lines, delimiter="|")
    try:
        header = next(reader)
    except StopIteration:
        return

    normalized_header = [str(value).lstrip("\ufeff").strip() for value in header]
    if normalized_header != RAW_COLUMNS:
        raise ValueError(
            "WSD water-suspension CSV header changed: "
            f"expected {RAW_COLUMNS}, got {normalized_header}"
        )

    for line_number, row in enumerate(reader, start=2):
        if not row or not any(value.strip() for value in row):
            continue
        if len(row) == len(RAW_COLUMNS) - 1:
            repaired = _repair_missing_nature_separator(row)
            if repaired is None:
                logger.warning("Skipping unrepairable WSD row %d with %d fields", line_number, len(row))
                continue
            row = repaired
            logger.info("Repaired WSD row %d with missing district/nature separator", line_number)
        if len(row) != len(RAW_COLUMNS):
            logger.warning("Skipping WSD row %d with %d fields", line_number, len(row))
            continue
        yield row


def parse_wsd_water_suspension_csv(payload: bytes) -> pd.DataFrame:
    """Parse and normalize the current WSD pipe-delimited event feed."""
    # The feed contains Traditional-Chinese fields and has a small number of
    # bytes that are not valid under strict Big5/CP950. English fields remain
    # intact with replacement decoding, which is preferable to misaligning
    # columns or failing the entire event snapshot.
    text = payload.decode("big5", errors="replace")
    rows = list(_iter_normalized_rows(io.StringIO(text).read().splitlines()))
    frame = pd.DataFrame(rows, columns=RAW_COLUMNS)
    if frame.empty:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    renamed = frame.rename(
        columns={
            "SUSPENSION_ID": "suspension_id",
            "WATER_TYPE_DESCRIPTION": "water_type",
            "DISTRICT_ENG": "district",
            "NATURE_DESCRIPTION": "nature",
            "SUSPENSION_DATE_TIME": "suspension_start",
            "ACTUAL_RESUMPTION_DATE_TIME": "actual_resumption",
            "LONG_ADDRESS": "address",
            "CAUSE": "cause",
            "STATUS": "status",
        }
    )
    for column in ("suspension_id", "water_type", "district", "nature", "address", "cause", "status"):
        renamed[column] = renamed[column].astype("string").str.strip()

    renamed["suspension_id"] = renamed["suspension_id"].astype("string")
    renamed["suspension_start"] = pd.to_datetime(
        renamed["suspension_start"].astype("string").str.strip(),
        format="%d-%m-%Y %H:%M",
        errors="coerce",
    )
    renamed["actual_resumption"] = pd.to_datetime(
        renamed["actual_resumption"].astype("string").str.strip(),
        format="%d-%m-%Y %H:%M",
        errors="coerce",
    )
    renamed["suspension_date"] = renamed["suspension_start"].dt.normalize()
    renamed["is_active"] = renamed["status"].str.casefold().ne("supply resumed")

    result = (
        renamed[SCHEMA_COLUMNS]
        .sort_values("suspension_start", ascending=False, na_position="last")
        .reset_index(drop=True)
    )
    duplicate_ids = result["suspension_id"].duplicated().sum()
    if duplicate_ids:
        logger.warning("WSD water-suspension feed contains %d duplicate IDs", duplicate_ids)
    return result


def _fetch_with_curl_fallback(url: str) -> tuple[bytes, str | None]:
    """Fetch a fixed official URL with requests, then curl if TLS rejects it."""
    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=max(DEFAULT_TIMEOUT, 30))
        response.raise_for_status()
        return response.content, response.headers.get("Last-Modified")
    except requests.RequestException as request_error:
        curl_path = shutil.which("curl")
        if not curl_path:
            raise request_error
        command = [
            curl_path,
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--max-time",
            str(max(DEFAULT_TIMEOUT, 30)),
            "--user-agent",
            DEFAULT_HEADERS["User-Agent"],
            url,
        ]
        try:
            completed = subprocess.run(command, check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError) as curl_error:
            detail = getattr(curl_error, "stderr", b"")
            detail_text = detail.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"WSD feed failed with requests ({request_error}) and curl ({detail_text})"
            ) from curl_error
        return completed.stdout, None


def fetch_wsd_water_suspension() -> pd.DataFrame:
    """Fetch and normalize WSD's current temporary water-suspension notices."""
    payload, last_modified = _fetch_with_curl_fallback(WSD_WATER_SUSPENSION_URL)
    result = parse_wsd_water_suspension_csv(payload)
    raw_path = save_raw_snapshot(
        "wsd_water_suspension",
        payload,
        file_ext="csv",
        source_url=WSD_WATER_SUSPENSION_URL,
    )
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = WSD_WATER_SUSPENSION_URL
    result.attrs["source_last_modified"] = last_modified
    return result
