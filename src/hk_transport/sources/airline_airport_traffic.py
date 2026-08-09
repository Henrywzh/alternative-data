"""Issuer monthly airport production statistics from CNINFO PDFs.

Shanghai International Airport (600009), Shenzhen Airport (000089) and
Guangzhou Baiyun Airport (600004) publish free monthly production bulletins
with aircraft movements, passenger throughput and cargo throughput by route
scope.  The PDFs expose an official announcement date, which makes the rows
point-in-time safe for airline demand context.

The layer is sector/hub demand context, not airline revenue: airport
throughput includes many carriers.  It is intentionally kept separate from
company ASK/RPK and never converted into revenue.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pdfplumber
import requests

from ..config import (
    BCIA_TRAFFIC_RELEASE_DATES,
    BCIA_TRAFFIC_URLS,
    CAN_2026_05_TRAFFIC_URL,
    CAN_2026_06_TRAFFIC_URL,
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    NORMALIZED_DIR,
    SHA_2026_06_TRAFFIC_URL,
    SZX_2026_05_TRAFFIC_URL,
    SZX_2026_06_TRAFFIC_URL,
)
from ..storage import save_raw_snapshot


OUTPUT_PATH = NORMALIZED_DIR / "airline_airport_traffic.csv"
DATASET_ID = "airline_airport_traffic"

OUTPUT_COLUMNS = [
    "dataset_id",
    "source_organization",
    "source_document_type",
    "source_url",
    "observation_month",
    "period_type",
    "airport",
    "airport_parent_company",
    "metric",
    "scope",
    "value",
    "unit",
    "yoy_pct",
    "ytd_value",
    "ytd_unit",
    "ytd_yoy_pct",
    "source_release_date",
    "source_release_date_status",
    "point_in_time_status",
    "source_quality",
    "source_note",
    "raw_snapshot_path",
    "retrieved_at",
]

METRIC_KEYS = {
    "飞机起降量": "aircraft_movements",
    "旅客吞吐量": "passenger_throughput",
    "货邮吞吐量": "cargo_throughput",
    "航班起降架次": "aircraft_movements",
    "起降架次": "aircraft_movements",
}

METRIC_UNITS = {
    "aircraft_movements": "movements",
    "passenger_throughput": "10k persons",
    "cargo_throughput": "10k tonnes",
}

# CNINFO bulletins use per-issuer unit wording.  The parsed header exposes the
# actual unit; values are normalized to the shared unit scheme below.
UNIT_SCALE_TO_10K = {
    "万人次": 1.0,
    "人次": 1 / 10_000.0,
    "万吨": 1.0,
    "吨": 1 / 10_000.0,
    "架次": 1.0,
}

SCOPE_MAP = {
    "总计": "total",
    "境内航线": "domestic",
    "境外航线": "international",
    "-国际航线": "international",
    "-港澳台航线": "hk_macao_taiwan",
    "国内航线": "domestic",
    "地区航线": "regional",
    "国际航线": "international",
}

BCIA_METRIC_KEYS = {
    "飞机起降架次": "aircraft_movements",
    "旅客吞吐量": "passenger_throughput",
    "货邮吞吐量": "cargo_throughput",
}

# BCIA reports raw unit wording on the metric header ((单位：架次)).  The
# display layer uses the shared hub unit scheme; passenger/cargo values are
# scaled from raw 人次/吨 to 10k so they line up with the other hubs.
BCIA_UNIT_HEADER_MAP = {
    "aircraft_movements": ("movements", 1.0),
    "passenger_throughput": ("10k persons", 1 / 10_000.0),
    "cargo_throughput": ("10k tonnes", 1 / 10_000.0),
}

SOURCE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "event_id": "sha_2026_01",
        "airport": "SHA-PVG",
        "airport_2": "SHA-SHA",
        "parent_company": "Shanghai International Airport",
        "observation_month": "2026-01",
        "release_date": "2026-02-14",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-02-14/1224980751.PDF",
        "layout": "shanghai_dual_airport",
    },
    {
        "event_id": "sha_2026_02",
        "airport": "SHA-PVG",
        "airport_2": "SHA-SHA",
        "parent_company": "Shanghai International Airport",
        "observation_month": "2026-02",
        "release_date": "2026-03-14",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-03-14/1225007733.PDF",
        "layout": "shanghai_dual_airport",
    },
    {
        "event_id": "sha_2026_03",
        "airport": "SHA-PVG",
        "airport_2": "SHA-SHA",
        "parent_company": "Shanghai International Airport",
        "observation_month": "2026-03",
        "release_date": "2026-04-15",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-04-15/1225100297.PDF",
        "layout": "shanghai_dual_airport",
    },
    {
        "event_id": "sha_2026_04",
        "airport": "SHA-PVG",
        "airport_2": "SHA-SHA",
        "parent_company": "Shanghai International Airport",
        "observation_month": "2026-04",
        "release_date": "2026-05-15",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-05-15/1225305693.PDF",
        "layout": "shanghai_dual_airport",
    },
    {
        "event_id": "sha_2026_05",
        "airport": "SHA-PVG",
        "airport_2": "SHA-SHA",
        "parent_company": "Shanghai International Airport",
        "observation_month": "2026-05",
        "release_date": "2026-06-15",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-06-15/1225370109.PDF",
        "layout": "shanghai_dual_airport",
    },
    {
        "event_id": "sha_2026_06",
        "airport": "SHA-PVG",
        "airport_2": "SHA-SHA",
        "parent_company": "Shanghai International Airport",
        "observation_month": "2026-06",
        "release_date": "2026-07-15",
        "source_url": SHA_2026_06_TRAFFIC_URL,
        "layout": "shanghai_dual_airport",
    },
    {
        "event_id": "szx_2026_01",
        "airport": "SZX",
        "parent_company": "Shenzhen Airport",
        "observation_month": "2026-01",
        "release_date": "2026-02-11",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-02-11/1224974610.PDF",
        "layout": "szx_can",
    },
    {
        "event_id": "szx_2026_02",
        "airport": "SZX",
        "parent_company": "Shenzhen Airport",
        "observation_month": "2026-02",
        "release_date": "2026-03-13",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-03-13/1225006050.PDF",
        "layout": "szx_can",
    },
    {
        "event_id": "szx_2026_03",
        "airport": "SZX",
        "parent_company": "Shenzhen Airport",
        "observation_month": "2026-03",
        "release_date": "2026-04-16",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-04-16/1225105059.PDF",
        "layout": "szx_can",
    },
    {
        "event_id": "szx_2026_04",
        "airport": "SZX",
        "parent_company": "Shenzhen Airport",
        "observation_month": "2026-04",
        "release_date": "2026-05-12",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-05-12/1225289194.PDF",
        "layout": "szx_can",
    },
    {
        "event_id": "szx_2026_05",
        "airport": "SZX",
        "parent_company": "Shenzhen Airport",
        "observation_month": "2026-05",
        "release_date": "2026-06-13",
        "source_url": SZX_2026_05_TRAFFIC_URL,
        "layout": "szx_can",
    },
    {
        "event_id": "can_2026_01",
        "airport": "CAN",
        "parent_company": "Guangzhou Baiyun Airport",
        "observation_month": "2026-01",
        "release_date": "2026-02-07",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-02-07/1224970136.PDF",
        "layout": "szx_can",
    },
    {
        "event_id": "can_2026_02",
        "airport": "CAN",
        "parent_company": "Guangzhou Baiyun Airport",
        "observation_month": "2026-02",
        "release_date": "2026-03-11",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-03-11/1225003003.PDF",
        "layout": "szx_can",
    },
    {
        "event_id": "can_2026_03",
        "airport": "CAN",
        "parent_company": "Guangzhou Baiyun Airport",
        "observation_month": "2026-03",
        "release_date": "2026-04-11",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-04-11/1225091803.PDF",
        "layout": "szx_can",
    },
    {
        "event_id": "can_2026_04",
        "airport": "CAN",
        "parent_company": "Guangzhou Baiyun Airport",
        "observation_month": "2026-04",
        "release_date": "2026-05-16",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-05-16/1225308187.PDF",
        "layout": "szx_can",
    },
    {
        "event_id": "szx_2026_06",
        "airport": "SZX",
        "parent_company": "Shenzhen Airport",
        "observation_month": "2026-06",
        "release_date": "2026-07-10",
        "source_url": SZX_2026_06_TRAFFIC_URL,
        "layout": "szx_can",
    },
    {
        "event_id": "can_2026_05",
        "airport": "CAN",
        "parent_company": "Guangzhou Baiyun Airport",
        "observation_month": "2026-05",
        "release_date": "2026-06-16",
        "source_url": CAN_2026_05_TRAFFIC_URL,
        "layout": "szx_can",
    },
    {
        "event_id": "can_2026_06",
        "airport": "CAN",
        "parent_company": "Guangzhou Baiyun Airport",
        "observation_month": "2026-06",
        "release_date": "2026-07-15",
        "source_url": CAN_2026_06_TRAFFIC_URL,
        "layout": "szx_can",
    },
    *(  # Beijing Capital International Airport monthly fast reports.
        {
            "event_id": f"bcia_{month.replace('-', '')}",
            "airport": "PEK",
            "airport_2": None,
            "parent_company": "Beijing Capital International Airport",
            "observation_month": month,
            "release_date": BCIA_TRAFFIC_RELEASE_DATES[month],
            "source_url": BCIA_TRAFFIC_URLS[month],
            "layout": "bcia",
        }
        for month in sorted(BCIA_TRAFFIC_URLS)
    ),
)


def _number(value: str | float | None) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(str(value).replace(",", "").rstrip("%"), errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _row(
    spec: dict[str, Any],
    *,
    airport: str,
    metric_key: str,
    scope: str,
    value: float,
    unit: str,
    yoy: float | None,
    ytd_value: float | None = None,
    ytd_unit: str | None = None,
    ytd_yoy: float | None = None,
    raw_snapshot_path: str | None = None,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    return {
        "dataset_id": DATASET_ID,
        "source_organization": spec["parent_company"],
        "source_document_type": "monthly_production_statistics",
        "source_url": spec["source_url"],
        "observation_month": spec["observation_month"],
        "period_type": "monthly",
        "airport": airport,
        "airport_parent_company": spec["parent_company"],
        "metric": metric_key,
        "scope": scope,
        "value": value,
        "unit": unit,
        "yoy_pct": yoy,
        "ytd_value": ytd_value,
        "ytd_unit": ytd_unit,
        "ytd_yoy_pct": ytd_yoy,
        "source_release_date": spec["release_date"],
        "source_release_date_status": "official_announcement_date",
        "point_in_time_status": "release_date_safe_observation",
        "source_quality": "issuer_primary_official_pdf",
        "source_note": (
            "Issuer monthly fast-report production statistics; airport throughput includes many carriers "
            "and is not company revenue.  Values are provisional until the official periodic report."
        ),
        "raw_snapshot_path": raw_snapshot_path,
        "retrieved_at": retrieved_at or datetime.now(timezone.utc).isoformat(),
    }


def parse_shanghai_dual_airport(
    payload: bytes,
    *,
    spec: dict[str, Any],
    text: str | None = None,
    raw_snapshot_path: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse the Shanghai two-airport bulletin (6-column rows)."""
    if text is None:
        with pdfplumber.open(io.BytesIO(payload)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    rows: list[dict[str, Any]] = []
    airport: str | None = None
    metric_columns: list[str] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        matched = [label for label in METRIC_KEYS if label in line]
        if matched and "本月" not in line and "同比" not in line and "总计" not in line:
            metric_columns = matched
            continue
        if "浦东国际机场" in line:
            airport = spec["airport"]
            continue
        if "虹桥国际机场" in line:
            airport = spec["airport_2"]
            continue
        if airport is None:
            continue
        if "本月" in line or "同比" in line or "重要说明" in line:
            continue
        parts = line.split()
        if len(parts) != 7 or parts[0] not in SCOPE_MAP:
            continue
        numbers = [_number(token) for token in parts[1:]]
        if any(value is None for value in numbers):
            continue
        scope = SCOPE_MAP[parts[0]]
        for index, metric_label in enumerate(metric_columns):
            metric_key = METRIC_KEYS[metric_label]
            rows.append(
                _row(
                    spec,
                    airport=airport,
                    metric_key=metric_key,
                    scope=scope,
                    value=numbers[index * 2],
                    unit=METRIC_UNITS[metric_key],
                    yoy=numbers[index * 2 + 1],
                    raw_snapshot_path=raw_snapshot_path,
                    retrieved_at=retrieved_at,
                )
            )
    if not rows:
        raise ValueError(f"Shanghai airport PDF produced no rows: {spec['event_id']}")
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


METRIC_HEADER_PATTERN = re.compile(
    r"^(?:[一二三四五六七八九十]、)?(其中：)?(旅客吞吐量|货邮吞吐量|航班起降架次|起降架次)（[^）]+）\s*(.+)$"
)
METRIC_COLUMN_HEADER_PATTERN = re.compile(
    r"^(起降架次|飞机起降量|旅客吞吐量|货邮吞吐量)（[^）]+）"
    r"(?:\s+(起降架次|飞机起降量|旅客吞吐量|货邮吞吐量)（[^）]+）)*"
)
SCOPE_LINE_PATTERN = re.compile(
    r"^(?:其中：)?(总计|国内航线|地区航线|国际航线)\s*(.+)$"
)


def parse_szx_can_layout(
    payload: bytes,
    *,
    spec: dict[str, Any],
    text: str | None = None,
    raw_snapshot_path: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse the Shenzhen/Guangzhou layout with month and cumulative columns."""
    if text is None:
        with pdfplumber.open(io.BytesIO(payload)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    rows: list[dict[str, Any]] = []
    current_metric: str | None = None
    column_metrics: list[tuple[str, str]] = []
    column_mode = False
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if not line or "项目" in line or "本月" in line or "累计" in line or "重要说明" in line:
            continue
        column_header = (
            METRIC_COLUMN_HEADER_PATTERN.match(line)
            and not re.search(r"\d", line)
        )
        if column_header and "总计" not in line and "航线" not in line:
            column_metrics = [
                (label, unit)
                for label, unit in re.findall(
                    r"(起降架次|飞机起降量|旅客吞吐量|货邮吞吐量)（([^）]+)）",
                    line,
                )
            ]
            column_mode = len(column_metrics) >= 3
            continue
        if column_mode:
            scope_match = SCOPE_LINE_PATTERN.match(line)
            if scope_match:
                scope_label = scope_match.group(1)
                scope = (
                    "total"
                    if scope_label == "总计"
                    else (
                        "domestic"
                        if "国内" in scope_label
                        else "international"
                        if "国际" in scope_label
                        else "regional"
                    )
                )
                parts = scope_match.group(2).split()
                if len(parts) != 6:
                    continue
                numbers = [_number(token) for token in parts]
                if any(value is None for value in numbers):
                    continue
                for index, (metric_label, raw_unit) in enumerate(column_metrics):
                    metric_key = METRIC_KEYS[metric_label]
                    unit_scale = UNIT_SCALE_TO_10K.get(raw_unit, 1.0)
                    unit = METRIC_UNITS[metric_key]
                    rows.append(
                        _row(
                            spec,
                            airport=spec["airport"],
                            metric_key=metric_key,
                            scope=scope,
                            value=round(numbers[index * 2] * unit_scale, 4),
                            unit=unit,
                            yoy=numbers[index * 2 + 1],
                            raw_snapshot_path=raw_snapshot_path,
                            retrieved_at=retrieved_at,
                        )
                    )
                continue
        header = METRIC_HEADER_PATTERN.match(line)
        if header:
            current_metric = header.group(2)
            unit_match = re.search(r"（([^）]+)）", line)
            current_metric_unit = unit_match.group(1) if unit_match else None
            tail = header.group(3)
            total_line = True
        else:
            scope_match = SCOPE_LINE_PATTERN.match(line)
            if scope_match:
                tail = scope_match.group(2)
                total_line = False
            else:
                continue
        if current_metric is None:
            continue
        parts = tail.split()
        if len(parts) != 4:
            continue
        numbers = [_number(token) for token in parts]
        if any(value is None for value in numbers):
            continue
        scope = (
            "total"
            if total_line
            else (
                "domestic"
                if "国内" in line
                else "international"
                if "国际" in line
                else "regional"
            )
        )
        metric_key = METRIC_KEYS[current_metric]
        header_unit = (
            dict(column_metrics).get(current_metric)
            if column_mode and column_metrics
            else current_metric_unit
        )
        unit_scale = UNIT_SCALE_TO_10K.get(header_unit, 1.0) if header_unit else 1.0
        unit = METRIC_UNITS[metric_key]
        ytd_unit = unit
        value = round(numbers[0] * unit_scale, 4)
        ytd_value = round(numbers[2] * unit_scale, 4)
        rows.append(
            _row(
                spec,
                airport=spec["airport"],
                metric_key=metric_key,
                scope=scope,
                value=value,
                unit=unit,
                yoy=numbers[1],
                ytd_value=ytd_value,
                ytd_unit=ytd_unit,
                ytd_yoy=numbers[3],
                raw_snapshot_path=raw_snapshot_path,
                retrieved_at=retrieved_at,
            )
        )
    if not rows:
        raise ValueError(f"Airport PDF produced no rows: {spec['event_id']}")
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


BCIA_METRIC_HEADER_RE = re.compile(
    r"^[一二三四五六七八九十]、"
    r"?(飞机起降架次|旅客吞吐量|货邮吞吐量)（单位：([^）]+)）\s+(.+)$"
)
BCIA_SCOPE_RE = re.compile(
    r"^(国内航线|其中，港澳台地区|国际航线)\s+(.+)$"
)
BCIA_RELEASE_DATE_RE = re.compile(
    r"实时发布\s*(\d{4})年(\d{1,2})月(\d{1,2})日"
)


def parse_bcia_layout(
    payload: bytes,
    *,
    spec: dict[str, Any],
    text: str | None = None,
    raw_snapshot_path: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse a Beijing Capital monthly operating-data fast report.

    The BCIA PDF carries each metric's total plus domestic / HK-Macao-Taiwan /
    international scope rows on the first page, and an explicit release date in
    the opening line ("实时发布 YYYY年M月D日").  Values for movements are raw
    counts, while passengers/cargo are scaled from raw 人次/吨 to the shared
    10k hub unit scheme so the panel stays comparable with SHA/SZX/CAN.
    """
    if text is None:
        with pdfplumber.open(io.BytesIO(payload)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    rows: list[dict[str, Any]] = []
    current_metric: str | None = None
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if not line or "累计" in line or "重要说明" in line or "本月实际" in line:
            continue
        metric_header = BCIA_METRIC_HEADER_RE.match(line)
        if metric_header:
            current_metric = BCIA_METRIC_KEYS[metric_header.group(1)]
            unit, unit_scale = BCIA_UNIT_HEADER_MAP[current_metric]
            parts = metric_header.group(3).split()
            if len(parts) == 2 and current_metric is not None:
                value = _number(parts[0])
                yoy = _number(parts[1])
                if value is not None:
                    rows.append(
                        _row(
                            spec,
                            airport=spec["airport"],
                            metric_key=current_metric,
                            scope="total",
                            value=round(value * unit_scale, 4),
                            unit=unit,
                            yoy=yoy,
                            raw_snapshot_path=raw_snapshot_path,
                            retrieved_at=retrieved_at,
                        )
                    )
            continue
        if current_metric is None:
            continue
        scope_match = BCIA_SCOPE_RE.match(line)
        if not scope_match:
            continue
        scope = (
            "domestic"
            if "国内" in scope_match.group(1)
            else "international"
            if "国际" in scope_match.group(1)
            else "hk_macao_taiwan"
        )
        parts = scope_match.group(2).split()
        if len(parts) != 2:
            continue
        _, unit_scale = BCIA_UNIT_HEADER_MAP[current_metric]
        unit, _ = BCIA_UNIT_HEADER_MAP[current_metric]
        value = _number(parts[0])
        yoy = _number(parts[1])
        if value is None:
            continue
        rows.append(
            _row(
                spec,
                airport=spec["airport"],
                metric_key=current_metric,
                scope=scope,
                value=round(value * unit_scale, 4),
                unit=unit,
                yoy=yoy,
                raw_snapshot_path=raw_snapshot_path,
                retrieved_at=retrieved_at,
            )
        )
    if not rows:
        raise ValueError(f"BCIA airport PDF produced no rows: {spec['event_id']}")
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def parse_airport_traffic_pdf(
    payload: bytes,
    *,
    spec: dict[str, Any],
    raw_snapshot_path: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    if spec["layout"] == "shanghai_dual_airport":
        return parse_shanghai_dual_airport(
            payload,
            spec=spec,
            raw_snapshot_path=raw_snapshot_path,
            retrieved_at=retrieved_at,
        )
    if spec["layout"] == "szx_can":
        return parse_szx_can_layout(
            payload,
            spec=spec,
            raw_snapshot_path=raw_snapshot_path,
            retrieved_at=retrieved_at,
        )
    if spec["layout"] == "bcia":
        return parse_bcia_layout(
            payload,
            spec=spec,
            raw_snapshot_path=raw_snapshot_path,
            retrieved_at=retrieved_at,
        )
    raise ValueError(f"Unknown airport traffic layout: {spec['layout']}")


def fetch_airline_airport_traffic() -> pd.DataFrame:
    """Fetch the curated issuer airport bulletins and persist the panel."""
    retrieved = datetime.now(timezone.utc).isoformat()
    frames: list[pd.DataFrame] = []
    for spec in SOURCE_SPECS:
        response = requests.get(
            spec["source_url"],
            headers=DEFAULT_HEADERS,
            timeout=max(DEFAULT_TIMEOUT, 30),
        )
        response.raise_for_status()
        raw_path = save_raw_snapshot(
            f"airline_airport_traffic_{spec['event_id']}",
            response.content,
            file_ext="pdf",
            source_url=spec["source_url"],
        )
        frames.append(
            parse_airport_traffic_pdf(
                response.content,
                spec=spec,
                raw_snapshot_path=str(raw_path),
                retrieved_at=retrieved,
            )
        )
    result = pd.DataFrame(
        [record for frame in frames for record in frame.to_dict("records")],
        columns=OUTPUT_COLUMNS,
    )
    if OUTPUT_PATH.exists():
        prior = pd.read_csv(OUTPUT_PATH)
        result = pd.DataFrame(
            [*prior.to_dict("records"), *result.to_dict("records")],
            columns=OUTPUT_COLUMNS,
        )
    result = result.drop_duplicates(
        subset=["observation_month", "airport", "metric", "scope", "source_url"],
        keep="last",
    ).reindex(columns=OUTPUT_COLUMNS)
    result.to_csv(OUTPUT_PATH, index=False)
    return result.sort_values(
        ["observation_month", "airport", "metric", "scope"]
    ).reset_index(drop=True)


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "SOURCE_SPECS",
    "fetch_airline_airport_traffic",
    "parse_airport_traffic_pdf",
    "parse_shanghai_dual_airport",
    "parse_szx_can_layout",
    "parse_bcia_layout",
    "source_path",
]
