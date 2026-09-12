"""One-shot backfill for the new free institutional-data source lanes.

This script is deliberately an explicit runner rather than a scheduler.  It
keeps the source packages small and source-specific, while this file owns the
cross-source concerns that should be identical everywhere:

* raw bytes are retained under ``data/raw/<source>/<run_id>/``;
* every artifact gets a SHA-256 payload hash and source URL;
* normalization is written through the package storage contract;
* failures and coverage gaps are recorded instead of being silently filled.

It does not call or rewrite the existing FRED/OFR/VIX/CFTC, Eastmoney
southbound, HKMA mortgage, airline short-selling, or energy benchmark lanes.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import sys
import re
import subprocess
import tempfile
import threading
from typing import Any, Iterable
from urllib.parse import urlencode, urlparse, urlunparse
from uuid import uuid4
import zipfile

import pandas as pd
import requests
from bs4 import BeautifulSoup

# The source packages live under src/, which is not on the path when this file
# is run directly as `python scripts/backfill_free_institutional_data.py`.
# tests/test_scripts_import_cleanly.py enforces that every script imports that
# way; relying on an externally set PYTHONPATH fails it.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from bis_macro_data.client import BisMacroClient
from bis_macro_data.config import BIS_CREDIT_GAP_BULK_URL, DEFAULT_TARGET_AREAS
from bis_macro_data.storage import BisMacroStorage
from cme_voi_data.client import CmeBulletinClient
from cme_voi_data.config import CME_BULLETIN_FILES, DEFAULT_PRODUCT_CODES
from cme_voi_data.storage import CmeVoiStorage
from common.free_data_artifacts import RawSnapshotRun, utc_now
from eia_energy_data.client import EiaEnergyClient
from eia_energy_data.config import DEFAULT_RESPONDENTS, EIA_BULK_EBA_URL, resolve_api_key
from eia_energy_data.models import EiaGridHourlyObservation
from eia_energy_data.storage import EiaEnergyStorage
from factset_earnings_data.client import FactsetEarningsClient
from factset_earnings_data.config import GICS_SECTORS
from factset_earnings_data.storage import FactsetEarningsStorage
from hkex_market_flow_data.client import HkexMarketFlowClient
from hkex_market_flow_data.storage import HkexMarketFlowStorage
from hkma_macro_data.client import HkmaMacroClient
from hkma_macro_data.config import HIBOR_HISTORY_FALLBACK_URL, HIBOR_PATH, HKMA_BASE_URL, INTERBANK_LIQUIDITY_PATH
from hkma_macro_data.models import HkmaObservation, HkmaSeriesMeta
from hkma_macro_data.storage import HkmaMacroStorage
from msci_index_review_data.client import MsciIndexReviewClient
from msci_index_review_data.storage import MsciIndexReviewStorage
from sp_pmi_data.client import SpPmiClient
from sp_pmi_data.storage import SpPmiStorage


LOGGER = logging.getLogger("backfill_free_institutional_data")
RUN_SOURCES = (
    "bis",
    "hkma",
    "eia",
    "cme",
    "factset",
    "sp_pmi",
    "msci",
    "hkex",
)
HKAB_HIBOR_URL = "https://www.hkab.org.hk/en/rates/hibor"
FACTSET_TOPIC_URL = "https://insight.factset.com/topic/earnings"
MSCI_REVIEW_URLS = (
    "https://www.msci.com/eqb/gimi/stdindex/index_review.html",
    "https://www.msci.com/eqb/fm/index_review.html",
)


def _slug(value: str, max_len: int = 100) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return (value or "artifact")[:max_len]


def _url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _relative_to_base(base_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)


def _date_text(value: object) -> str:
    if value is None:
        return ""
    parsed = pd.to_datetime(str(value), errors="coerce")
    return "" if pd.isna(parsed) else parsed.date().isoformat()


def _date_range(start: str, end: str) -> list[str]:
    first = date.fromisoformat(start)
    last = date.fromisoformat(end)
    if first > last:
        raise ValueError(f"start date {start} is after end date {end}")
    values: list[str] = []
    cursor = first
    while cursor <= last:
        if cursor.weekday() < 5:
            values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return values


def _output_map(storage: Any, filenames: Iterable[str]) -> dict[str, str]:
    return {
        name: _relative_to_base(storage.base_dir, storage.normalized_root / name)
        for name in filenames
    }


def _status(row_count: int, errors: dict[str, Any]) -> str:
    if not errors:
        return "ok"
    return "partial" if row_count else "failed"


def _save_source_manifest(
    raw_run: RawSnapshotRun,
    *,
    row_count: int,
    errors: dict[str, Any],
    normalized_outputs: dict[str, str],
    coverage: dict[str, Any],
) -> Path:
    return raw_run.finalize(
        status=_status(row_count, errors),
        errors=errors,
        normalized_outputs=normalized_outputs,
        coverage=coverage,
    )


def _as_numeric(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"nan", "none", "null", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def backfill_bis(base_dir: Path, run_id: str) -> dict[str, Any]:
    storage = BisMacroStorage(base_dir)
    raw_run = RawSnapshotRun(storage.raw_root, run_id, "bis_credit_gap")
    errors: dict[str, Any] = {}
    observations = []
    metadata = []
    try:
        client = BisMacroClient(timeout_seconds=90.0)
        payload = client.fetch_credit_gap_bulk()
        raw_run.write_bytes(
            "credit_gap/WS_CREDIT_GAP_csv_flat.zip",
            payload,
            source_url=BIS_CREDIT_GAP_BULK_URL,
            status_code=200,
            metadata={"artifact": "official BIS full-topic bulk ZIP", "format": "CSV inside ZIP"},
        )
        frame = client.read_credit_gap_bulk(payload)
        metadata, observations = client.parse_credit_gap_records(frame, target_areas=DEFAULT_TARGET_AREAS)
        if not observations:
            errors["normalization"] = "BIS bulk artifact parsed but yielded no target-area credit-gap rows"
    except Exception as exc:
        errors["fetch_or_parse"] = f"{type(exc).__name__}: {exc}"
        LOGGER.warning("BIS failed: %s", errors["fetch_or_parse"])

    series_count = len(storage.upsert_series_meta(metadata)) if metadata else len(storage.load_series_meta())
    observation_count = len(storage.upsert_observations(observations)) if observations else len(storage.load_observations())
    periods = [obs.period for obs in observations if obs.period]
    manifest = _save_source_manifest(
        raw_run,
        row_count=len(observations),
        errors=errors,
        normalized_outputs=_output_map(storage, ["bis_series_meta.parquet", "bis_series_meta.csv", "bis_observations.parquet", "bis_observations.csv"]),
        coverage={
            "target_areas": DEFAULT_TARGET_AREAS,
            "series_count": series_count,
            "rows_fetched": len(observations),
            "min_period": min(periods) if periods else None,
            "max_period": max(periods) if periods else None,
            "frequency": "quarterly",
        },
    )
    return {
        "status": _status(len(observations), errors),
        "rows_fetched": len(observations),
        "rows_normalized_total": observation_count,
        "series_normalized_total": series_count,
        "manifest": _relative_to_base(base_dir, manifest),
        "errors": errors,
    }


def _fetch_hkma_endpoint(
    client: HkmaMacroClient,
    path: str,
    raw_run: RawSnapshotRun,
    name: str,
    *,
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    """Fetch all pages from one HKMA endpoint and snapshot each page."""
    url = f"{client.base_url}{path}"
    records: list[dict[str, Any]] = []
    offset = 0
    for page_number in range(1, 101):
        response = client.session.get(
            url,
            headers=client.session.headers,
            params={"pagesize": page_size, "offset": offset},
            timeout=client.timeout_seconds,
        )
        response.raise_for_status()
        raw_run.write_bytes(
            f"official/{name}_{page_number:04d}.json",
            response.content,
            source_url=response.url,
            status_code=response.status_code,
            metadata={"offset": offset, "pagesize": page_size},
        )
        body = response.json()
        page_records = body.get("result", {}).get("records", [])
        if not isinstance(page_records, list):
            raise ValueError(f"HKMA {name} response has non-list records")
        records.extend(page_records)
        total = body.get("result", {}).get("total") or body.get("result", {}).get("total_count")
        if not page_records or (total is not None and offset + len(page_records) >= int(total)) or len(page_records) < page_size:
            break
        offset += len(page_records)
    else:
        raise RuntimeError(f"HKMA {name} pagination exceeded 100 pages")
    return records


def _parse_hkma_interbank(records: list[dict[str, Any]], fetched_at: str, source_url: str) -> tuple[HkmaSeriesMeta, list[HkmaObservation]]:
    meta = HkmaSeriesMeta(
        series_id="HKMA_AGGREGATE_BALANCE",
        title="HKMA Aggregate Balance (Interbank Liquidity)",
        category="Liquidity",
        frequency="D",
        units="HKD_Million",
        fetched_at=fetched_at,
    )
    observations: list[HkmaObservation] = []
    for row in records:
        raw_date = row.get("end_of_date") or row.get("date")
        raw_value = row.get("closing_balance")
        if raw_value is None:
            raw_value = row.get("aggregate_balance")
        if raw_date:
            observations.append(
                HkmaObservation(
                    date=_date_text(raw_date),
                    series_id=meta.series_id,
                    value=_as_numeric(raw_value),
                    fetched_at=fetched_at,
                    source_url=source_url,
                )
            )
    return meta, observations


def _parse_hkma_hibor(records: list[dict[str, Any]], fetched_at: str, source_url: str) -> list[tuple[HkmaSeriesMeta, list[HkmaObservation]]]:
    series_map = {
        "ir_overnight": ("HKMA_HIBOR_ON", "HIBOR Overnight Fixing"),
        "ir_1w": ("HKMA_HIBOR_1W", "HIBOR 1-Week Fixing"),
        "ir_2w": ("HKMA_HIBOR_2W", "HIBOR 2-Week Fixing"),
        "ir_1m": ("HKMA_HIBOR_1M", "HIBOR 1-Month Fixing"),
        "ir_2m": ("HKMA_HIBOR_2M", "HIBOR 2-Month Fixing"),
        "ir_3m": ("HKMA_HIBOR_3M", "HIBOR 3-Month Fixing"),
        "ir_6m": ("HKMA_HIBOR_6M", "HIBOR 6-Month Fixing"),
        "ir_12m": ("HKMA_HIBOR_12M", "HIBOR 12-Month Fixing"),
    }
    results: list[tuple[HkmaSeriesMeta, list[HkmaObservation]]] = []
    for field, (series_id, title) in series_map.items():
        meta = HkmaSeriesMeta(series_id, title, "Rates", "D", "Percent", fetched_at)
        observations: list[HkmaObservation] = []
        for row in records:
            raw_date = row.get("end_of_date") or row.get("date")
            if raw_date:
                observations.append(
                    HkmaObservation(
                        date=_date_text(raw_date),
                        series_id=series_id,
                        value=_as_numeric(row.get(field)),
                        fetched_at=fetched_at,
                        source_url=source_url,
                    )
                )
        results.append((meta, observations))
    return results


def _parse_hkab_current_page(html: bytes, fetched_at: str, source_url: str) -> list[tuple[HkmaSeriesMeta, list[HkmaObservation]]]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    date_match = re.search(r"Hong Kong Time on\s+(\d{4})-(\d{1,2})-(\d{1,2})", text, re.I)
    if not date_match:
        return []
    current_date = f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
    patterns = {
        "ON": r"Overnight\s+(\d+(?:\.\d+)?)",
        "1W": r"1 Week\s+(\d+(?:\.\d+)?)",
        "2W": r"2 Weeks\s+(\d+(?:\.\d+)?)",
        "1M": r"1 Month\s+(\d+(?:\.\d+)?)",
        "2M": r"2 Months\s+(\d+(?:\.\d+)?)",
        "3M": r"3 Months\s+(\d+(?:\.\d+)?)",
        "6M": r"6 Months\s+(\d+(?:\.\d+)?)",
        "1Y": r"12 Months\s+(\d+(?:\.\d+)?)",
    }
    row: dict[str, Any] = {"date": current_date}
    for column, pattern in patterns.items():
        match = re.search(pattern, text, re.I)
        row[column] = _as_numeric(match.group(1)) if match else None
    rows = [row]
    frame = pd.DataFrame(rows, columns=["date", *patterns])
    return HkmaMacroClient.parse_hibor_history_records(frame, fetched_at=fetched_at, source_url=source_url)


def backfill_hkma(base_dir: Path, run_id: str) -> dict[str, Any]:
    storage = HkmaMacroStorage(base_dir)
    raw_run = RawSnapshotRun(storage.raw_root, run_id, "hkma_macro")
    client = HkmaMacroClient(timeout_seconds=10.0)
    errors: dict[str, Any] = {}
    meta_records: list[HkmaSeriesMeta] = []
    obs_records: list[HkmaObservation] = []
    fetched_at = utc_now()

    try:
        official_records = _fetch_hkma_endpoint(client, INTERBANK_LIQUIDITY_PATH, raw_run, "interbank_liquidity")
        meta, observations = _parse_hkma_interbank(official_records, fetched_at, f"{HKMA_BASE_URL}{INTERBANK_LIQUIDITY_PATH}")
        meta_records.append(meta)
        obs_records.extend(observations)
    except Exception as exc:
        errors["official_interbank_liquidity"] = f"{type(exc).__name__}: {exc}"
        LOGGER.warning("HKMA interbank official endpoint failed: %s", errors["official_interbank_liquidity"])

    official_hibor_ok = False
    try:
        official_records = _fetch_hkma_endpoint(client, HIBOR_PATH, raw_run, "hibor")
        results = _parse_hkma_hibor(official_records, fetched_at, f"{HKMA_BASE_URL}{HIBOR_PATH}")
        for meta, observations in results:
            meta_records.append(meta)
            obs_records.extend(observations)
        official_hibor_ok = bool(official_records)
    except Exception as exc:
        errors["official_hibor"] = f"{type(exc).__name__}: {exc}"
        LOGGER.warning("HKMA HIBOR official endpoint failed: %s", errors["official_hibor"])

    if not official_hibor_ok:
        try:
            fallback_client = HkmaMacroClient(timeout_seconds=30.0)
            payload, frame = fallback_client.fetch_hibor_history_fallback()
            raw_run.write_bytes(
                "fallback/hibor_history_jin10.json",
                payload,
                source_url=HIBOR_HISTORY_FALLBACK_URL,
                status_code=200,
                rows=len(frame),
                coverage={"min_date": frame["date"].min() if not frame.empty else None, "max_date": frame["date"].max() if not frame.empty else None},
                metadata={"provenance": "public aggregator fallback behind AkShare macro_china_hk_market_info", "official_equivalent": False},
                gzip_payload=True,
            )
            for meta, observations in fallback_client.parse_hibor_history_records(frame, fetched_at=fetched_at, source_url=HIBOR_HISTORY_FALLBACK_URL):
                meta_records.append(meta)
                obs_records.extend(observations)
            errors["hibor_provenance"] = "Official HKMA HIBOR endpoint unavailable; normalized history uses the documented public aggregator fallback."
        except Exception as exc:
            errors["hibor_fallback"] = f"{type(exc).__name__}: {exc}"
            LOGGER.warning("HKMA HIBOR fallback failed: %s", errors["hibor_fallback"])

    try:
        hkab_client = HkmaMacroClient(timeout_seconds=20.0)
        response = hkab_client.session.get(HKAB_HIBOR_URL, timeout=hkab_client.timeout_seconds)
        response.raise_for_status()
        raw_run.write_bytes(
            "reference/hkab_hibor_current.html",
            response.content,
            source_url=response.url,
            status_code=response.status_code,
            metadata={"publication_time": "11:15 HKT current fixing page"},
            gzip_payload=True,
        )
        for meta, observations in _parse_hkab_current_page(response.content, fetched_at, response.url):
            meta_records.append(meta)
            obs_records.extend(observations)
    except Exception as exc:
        errors["hkab_current_reference"] = f"{type(exc).__name__}: {exc}"

    # The official current page should win over the fallback for the same
    # date/series; storage's keep-last semantics make that explicit here.
    series_total = len(storage.upsert_series_meta(meta_records)) if meta_records else len(storage.load_series_meta())
    obs_total = len(storage.upsert_observations(obs_records)) if obs_records else len(storage.load_observations())
    dates = [item.date for item in obs_records if item.date]
    manifest = _save_source_manifest(
        raw_run,
        row_count=len(obs_records),
        errors=errors,
        normalized_outputs=_output_map(storage, ["hkma_series_meta.parquet", "hkma_series_meta.csv", "hkma_observations.parquet", "hkma_observations.csv"]),
        coverage={
            "series_count": series_total,
            "rows_fetched": len(obs_records),
            "min_date": min(dates) if dates else None,
            "max_date": max(dates) if dates else None,
            "official_hibor": official_hibor_ok,
            "fallback_used": not official_hibor_ok,
        },
    )
    return {
        "status": _status(len(obs_records), errors),
        "rows_fetched": len(obs_records),
        "rows_normalized_total": obs_total,
        "series_normalized_total": series_total,
        "manifest": _relative_to_base(base_dir, manifest),
        "errors": errors,
    }


def backfill_eia(base_dir: Path, run_id: str, start: str, end: str) -> dict[str, Any]:
    storage = EiaEnergyStorage(base_dir)
    raw_run = RawSnapshotRun(storage.raw_root, run_id, "eia_grid_hourly")
    errors: dict[str, Any] = {}
    bulk_client = EiaEnergyClient(timeout_seconds=90.0)
    respondent_counts: dict[str, int] = {}
    rows_fetched = 0
    min_period_seen: str | None = None
    max_period_seen: str | None = None
    bulk_path = raw_run.path_for("bulk/EBA.zip")
    transport = "official EIA no-key bulk EBA.zip"
    try:
        bulk_client.fetch_bulk_to_path(bulk_path, EIA_BULK_EBA_URL)
        with zipfile.ZipFile(bulk_path) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".txt")]
            if not members:
                raise ValueError("EIA EBA.zip contains no TXT member")
            member = next((name for name in members if name.lower().endswith("eba.txt")), members[0])
            bulk_fetched_at = utc_now()
            start_key = start.replace("-", "")
            end_key = end.replace("-", "")
            observation_buffer = []
            series_counts: dict[str, int] = {}
            with archive.open(member) as compressed_handle:
                import io as _io

                text_handle = _io.TextIOWrapper(compressed_handle, encoding="utf-8")
                for line_number, raw_line in enumerate(text_handle, start=1):
                    if not raw_line.strip():
                        continue
                    # EBA.txt is newline-delimited JSON.  Filter at the byte
                    # line before json.loads because the full member expands
                    # to multiple gigabytes.
                    if not any(f'"series_id":"EBA.{respondent}-' in raw_line for respondent in DEFAULT_RESPONDENTS):
                        continue
                    series = json.loads(raw_line)
                    series_id = str(series.get("series_id", ""))
                    parts = series_id.split(".")
                    if len(parts) < 5 or parts[-1] != "H":
                        continue
                    respondent = parts[1].split("-", 1)[0]
                    if respondent not in DEFAULT_RESPONDENTS:
                        continue
                    fuel_type = parts[-2]
                    data = series.get("data", [])
                    series_counts[respondent] = series_counts.get(respondent, 0) + 1
                    for cell in data:
                        if not isinstance(cell, list) or len(cell) < 2:
                            continue
                        period_raw = str(cell[0])
                        if len(period_raw) != 11 or "T" not in period_raw:
                            continue
                        if period_raw < start_key or period_raw > end_key:
                            continue
                        period = f"{period_raw[:4]}-{period_raw[4:6]}-{period_raw[6:8]}T{period_raw[9:11]}"
                        value = _as_numeric(cell[1])
                        observation_buffer.append(
                            EiaGridHourlyObservation(
                                timestamp_utc=period,
                                respondent=respondent,
                                fuel_type=fuel_type,
                                generation_mwh=value,
                                fetched_at=bulk_fetched_at,
                            )
                        )
                        rows_fetched += 1
                        respondent_counts[respondent] = respondent_counts.get(respondent, 0) + 1
                        min_period_seen = period if min_period_seen is None else min(min_period_seen, period)
                        max_period_seen = period if max_period_seen is None else max(max_period_seen, period)
                        if len(observation_buffer) >= 100_000:
                            storage.upsert_grid_hourly(observation_buffer)
                            observation_buffer = []
                    if line_number % 5000 == 0:
                        LOGGER.info("EIA bulk series scanned %s lines; normalized %s rows", line_number, rows_fetched)
                text_handle.detach()
            if observation_buffer:
                storage.upsert_grid_hourly(observation_buffer)
            raw_run.record_existing_file(
                "bulk/EBA.zip",
                source_url=EIA_BULK_EBA_URL,
                status_code=200,
                rows=rows_fetched,
                coverage={"member": member, "series_counts": series_counts, "min_period": min_period_seen, "max_period": max_period_seen},
                metadata={"transport": transport, "full_topic_raw": True, "normalized_respondents": DEFAULT_RESPONDENTS},
            )
    except Exception as exc:
        errors["bulk_fetch_or_normalize"] = f"{type(exc).__name__}: {exc}"
        LOGGER.warning("EIA bulk failed: %s; attempting API fallback", errors["bulk_fetch_or_normalize"])
        if bulk_path.exists() and not any(entry.get("path") == str(bulk_path.relative_to(storage.raw_root)) for entry in raw_run.entries):
            # Keep a failed/partial bulk file auditable if a connection was
            # interrupted before the ZIP could be opened.
            raw_run.record_existing_file(
                "bulk/EBA.zip",
                source_url=EIA_BULK_EBA_URL,
                status_code=None,
                metadata={"transport": transport, "incomplete_or_unparsed": True},
            )
        api_key = resolve_api_key(base_dir) or os.environ.get("EIA_API_KEY", "").strip() or "DEMO_KEY"
        api_key_source = "configured EIA_API_KEY" if api_key != "DEMO_KEY" else "public DEMO_KEY"
        client = EiaEnergyClient(api_key=api_key, timeout_seconds=35.0)
        observation_buffer = []
        try:
            for respondent, offset, payload, page_observations in client.iter_hourly_grid_generation_pages(
                respondents=DEFAULT_RESPONDENTS,
                start=start,
                end=end,
                page_length=5000,
            ):
                records = payload.get("response", {}).get("data", [])
                periods = [str(item.get("period")) for item in records if item.get("period")]
                raw_run.write_json(
                    f"api/{respondent}/{offset:09d}.json",
                    payload,
                    source_url="https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/",
                    status_code=200,
                    rows=len(records),
                    coverage={"min_period": min(periods) if periods else None, "max_period": max(periods) if periods else None},
                    metadata={"respondent": respondent, "offset": offset, "api_key_source": api_key_source, "total": payload.get("response", {}).get("total")},
                    gzip_payload=True,
                )
                observation_buffer.extend(page_observations)
                rows_fetched += len(page_observations)
                respondent_counts[respondent] = respondent_counts.get(respondent, 0) + len(page_observations)
                if len(observation_buffer) >= 100_000:
                    storage.upsert_grid_hourly(observation_buffer)
                    observation_buffer = []
            if observation_buffer:
                storage.upsert_grid_hourly(observation_buffer)
            transport = "EIA API fallback"
        except Exception as api_exc:
            errors["api_fallback"] = f"{type(api_exc).__name__}: {api_exc}"
            if observation_buffer:
                storage.upsert_grid_hourly(observation_buffer)

    normalized_total = len(storage.load_grid_hourly())
    manifest = _save_source_manifest(
        raw_run,
        row_count=sum(respondent_counts.values()),
        errors=errors,
        # The partition directory, not the single file and CSV twin the
        # store deletes on write: a manifest that names outputs the same run
        # removed is provenance that points at nothing.
        normalized_outputs=_output_map(storage, ["eia_grid_hourly"]),
        coverage={
            "respondents": DEFAULT_RESPONDENTS,
            "respondent_rows": respondent_counts,
            "rows_fetched": sum(respondent_counts.values()),
            "requested_start": start,
            "requested_end": end,
            "normalized_rows_total": normalized_total,
            "period_field_note": "EIA API period is an hourly wall-clock label; retained in the legacy timestamp_utc column without inventing a timezone.",
            "transport": transport,
            "min_period": min_period_seen,
            "max_period": max_period_seen,
            "raw_full_bulk_topic": transport.startswith("official EIA"),
        },
    )
    return {
        "status": _status(sum(respondent_counts.values()), errors),
        "rows_fetched": sum(respondent_counts.values()),
        "rows_normalized_total": normalized_total,
        "manifest": _relative_to_base(base_dir, manifest),
        "errors": errors,
    }


def backfill_cme(base_dir: Path, run_id: str) -> dict[str, Any]:
    storage = CmeVoiStorage(base_dir)
    raw_run = RawSnapshotRun(storage.raw_root, run_id, "cme_volume_open_interest")
    client = CmeBulletinClient(timeout_seconds=25.0)
    errors: dict[str, Any] = {}
    observations = []
    section_results: dict[str, Any] = {}
    for section, filename in CME_BULLETIN_FILES.items():
        url = f"https://www.cmegroup.com/daily_bulletin/current/{filename}"
        try:
            fetched_url, payload = client.fetch_daily_bulletin(section)
            raw_run.write_bytes(
                f"daily/{section}.pdf",
                payload,
                source_url=fetched_url,
                status_code=200,
                metadata={"section": section, "filename": filename, "history_scope": "current public bulletin"},
            )
            text = client.extract_pdf_text(payload)
            section_category = {"equity": "Equity", "rates": "Rates", "metals": "Metals", "energy": "Energy"}[section]
            codes = [code for code, spec in DEFAULT_PRODUCT_CODES.items() if spec["category"] == section_category]
            parsed = client.parse_bulletin_products(text, product_codes=codes)
            observations.extend(parsed)
            section_results[section] = {"status": "ok", "rows": len(parsed), "products": codes}
        except Exception as exc:
            section_results[section] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            errors[f"section_{section}"] = section_results[section]["error"]
            LOGGER.warning("CME %s failed: %s", section, errors[f"section_{section}"])

    normalized_total = len(storage.upsert_observations(observations)) if observations else len(storage.load_observations())
    trade_dates = [obs.trade_date for obs in observations if obs.trade_date]
    manifest = _save_source_manifest(
        raw_run,
        row_count=len(observations),
        errors={"availability": "CME free public history is limited to the current Daily Bulletin; historical detailed daily files require CME DataMine/entitlement.", **errors},
        normalized_outputs=_output_map(storage, ["cme_futures_voi.parquet", "cme_futures_voi.csv"]),
        coverage={
            "sections": section_results,
            "rows_fetched": len(observations),
            "min_trade_date": min(trade_dates) if trade_dates else None,
            "max_trade_date": max(trade_dates) if trade_dates else None,
            "products_requested": list(DEFAULT_PRODUCT_CODES),
            "free_history_limitation": True,
        },
    )
    result_errors = {"availability": "CME free public history is limited to the current Daily Bulletin; historical detailed daily files require CME DataMine/entitlement."}
    result_errors.update(errors)
    return {
        "status": _status(len(observations), result_errors),
        "rows_fetched": len(observations),
        "rows_normalized_total": normalized_total,
        "manifest": _relative_to_base(base_dir, manifest),
        "errors": result_errors,
    }


def _factset_ocr(payload: bytes, suffix: str = ".png") -> str:
    # FactSet infographics can be several thousand pixels wide.  Downscaling
    # before OCR avoids an unbounded tesseract process while retaining enough
    # resolution for the large numeric labels used by the infographic.
    try:
        from PIL import Image

        with Image.open(io.BytesIO(payload)) as image:
            image = image.convert("RGB")
            image.thumbnail((2400, 2400))
            with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
                image.save(image_file, format="PNG", optimize=True)
                image_file.flush()
                input_path = image_file.name
                result = subprocess.run(
                    ["tesseract", input_path, "stdout", "--psm", "6"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=45,
                )
                return result.stdout
    except ImportError:
        input_path = None
    if input_path is None:
        with tempfile.NamedTemporaryFile(suffix=suffix) as image_file:
            image_file.write(payload)
            image_file.flush()
            result = subprocess.run(
                ["tesseract", image_file.name, "stdout", "--psm", "6"],
                check=True,
                capture_output=True,
                text=True,
                timeout=45,
            )
            return result.stdout


def _factset_relevant(title: str, text: str, url: str) -> bool:
    path = urlparse(url).path.strip("/").lower()
    if not path or path.startswith("author/"):
        return False
    blob = f"{title} {text} {url}".lower()
    return (
        ("earnings" in blob and ("insight" in blob or "s&p 500" in blob or "eps" in blob))
        or "forward 12-month p/e" in blob
        or "forward p/e" in blob
    )


def _factset_candidate_url(url: str) -> bool:
    path = urlparse(url).path.strip("/").lower()
    if not path or path.startswith(("author/", "topic/", "search")):
        return False
    return any(token in path for token in ("earnings", "eps", "sp-500", "revenue", "profit", "margin", "estimate"))


def backfill_factset(base_dir: Path, run_id: str) -> dict[str, Any]:
    storage = FactsetEarningsStorage(base_dir)
    raw_run = RawSnapshotRun(storage.raw_root, run_id, "factset_earnings")
    client = FactsetEarningsClient(timeout_seconds=35.0)
    image_client = FactsetEarningsClient(timeout_seconds=10.0, session=client.session)
    errors: dict[str, Any] = {}
    article_urls: list[str] = []
    page_count = 0
    consecutive_empty = 0
    for page_number in range(1, 101):
        url = FACTSET_TOPIC_URL if page_number == 1 else f"{FACTSET_TOPIC_URL}/page/{page_number}"
        try:
            response = client.fetch(url)
            raw_run.write_bytes(
                f"topic/page_{page_number:03d}.html",
                response.content,
                source_url=response.url,
                status_code=response.status_code,
                metadata={"page_number": page_number},
                gzip_payload=True,
            )
            links = client.extract_article_links(response.text, FACTSET_TOPIC_URL)
            new_links = [link for link in links if link not in article_urls]
            article_urls.extend(new_links)
            page_count = page_number
            consecutive_empty = consecutive_empty + 1 if not new_links else 0
            if consecutive_empty >= 2:
                break
        except Exception as exc:
            errors[f"topic_page_{page_number}"] = f"{type(exc).__name__}: {exc}"
            if page_number > 2:
                break

    observations = []
    relevant_articles = 0
    ocr_images = 0
    candidate_urls = [url for url in article_urls if _factset_candidate_url(url)]
    for article_number, url in enumerate(candidate_urls, start=1):
        try:
            response = client.fetch(url)
            name = _slug(urlparse(url).path.rsplit("/", 1)[-1])
            raw_run.write_bytes(
                f"articles/{article_number:04d}_{name}_{_url_hash(url)}.html",
                response.content,
                source_url=response.url,
                status_code=response.status_code,
                metadata={"article_url": url},
                gzip_payload=True,
            )
            metadata = client.extract_article_metadata(response.text)
            if not _factset_relevant(metadata["title"], metadata["text"], url):
                continue
            relevant_articles += 1
            combined_text = f"{metadata['title']}\n{metadata['text']}"
            article_ocr_count = 0
            candidate_image_count = 0
            for image_url in metadata.get("image_urls", []):
                lower_image = image_url.lower()
                if not any(token in lower_image for token in ("earnings", "infographic", "/ei%20", "/ei_", "ei%20infographic")):
                    continue
                if candidate_image_count >= 2:
                    break
                candidate_image_count += 1
                try:
                    image_response = image_client.fetch(image_url)
                    image_name = _slug(urlparse(image_url).path.rsplit("/", 1)[-1].split("?", 1)[0])
                    raw_run.write_bytes(
                        f"images/{article_number:04d}_{image_name}_{_url_hash(image_url)}",
                        image_response.content,
                        source_url=image_response.url,
                        status_code=image_response.status_code,
                        metadata={"article_url": url, "ocr": True},
                    )
                    # Cap expensive OCR to two content panels per article.
                    # The article HTML remains the complete audit artifact.
                    if article_ocr_count >= 2:
                        continue
                    article_ocr_count += 1
                    try:
                        ocr_text = _factset_ocr(image_response.content)
                    except Exception as exc:
                        errors[f"ocr_{article_number}"] = f"{type(exc).__name__}: {exc}"
                        continue
                    if ocr_text.strip():
                        combined_text += "\n" + ocr_text
                        raw_run.write_bytes(
                            f"ocr/{article_number:04d}_{image_name}.txt",
                            ocr_text.encode("utf-8"),
                            source_url=image_response.url,
                            rows=len(ocr_text.splitlines()),
                            metadata={"article_url": url, "derived_from": "tesseract"},
                        )
                    ocr_images += 1
                except Exception as exc:
                    errors[f"image_{article_number}"] = f"{type(exc).__name__}: {exc}"
            ref_q = client.infer_reference_quarter(
                combined_text,
                metadata["title"],
                metadata.get("report_date", ""),
            )
            if not ref_q:
                continue
            observation = client.parse_summary_metrics(
                combined_text,
                metadata.get("report_date", ""),
                ref_q,
                source_url=url,
            )
            metric_values = observation.to_dict()
            if any(metric_values.get(field) is not None for field in (
                "blended_earnings_growth_yoy", "blended_revenue_growth_yoy", "eps_beat_rate", "eps_surprise_pct",
                "revenue_beat_rate", "revenue_surprise_pct", "forward_12m_pe",
            )):
                observations.append(observation)
        except Exception as exc:
            errors[f"article_{article_number}"] = f"{type(exc).__name__}: {exc}"
        if article_number % 25 == 0:
            LOGGER.info("FactSet articles processed %s/%s", article_number, len(candidate_urls))

    normalized_total = len(storage.upsert_observations(observations)) if observations else len(storage.load_observations())
    dates = [obs.report_date for obs in observations if obs.report_date]
    manifest = _save_source_manifest(
        raw_run,
        row_count=len(observations),
        errors=errors,
        normalized_outputs=_output_map(storage, ["factset_sp500_earnings_regime.parquet", "factset_sp500_earnings_regime.csv"]),
        coverage={
            "topic_pages_fetched": page_count,
            "article_links_discovered": len(article_urls),
            "relevant_articles": relevant_articles,
            "ocr_images": ocr_images,
            "rows_fetched": len(observations),
            "min_report_date": min(dates) if dates else None,
            "max_report_date": max(dates) if dates else None,
            "frequency": "irregular/weekly public Insight articles",
            "universe": "S&P 500 aggregate metrics when the article exposes them",
            "coverage_note": "Only public article/infographic metrics are normalized; no paid FactSet API or vendor security-level estimates are fetched.",
        },
    )
    return {
        "status": _status(len(observations), errors),
        "rows_fetched": len(observations),
        "rows_normalized_total": normalized_total,
        "manifest": _relative_to_base(base_dir, manifest),
        "errors": errors,
    }


def _pmi_fetch_with_cache_bust(client: SpPmiClient, url: str) -> tuple[str, bytes]:
    parsed = urlparse(url)
    query = parsed.query
    separator = "&" if query else ""
    cache_bust_url = urlunparse(parsed._replace(query=f"{query}{separator}_={int(datetime.now(timezone.utc).timestamp() * 1000)}"))
    try:
        fetched_url, payload = client.fetch(cache_bust_url)
        if b"AwsWafIntegration" in payload or b"challenge.js" in payload:
            raise RuntimeError("S&P PMI response is an AWS WAF challenge page, not release content")
        return fetched_url, payload
    except Exception:
        fetched_url, payload = client.fetch(url)
        if b"AwsWafIntegration" in payload or b"challenge.js" in payload:
            raise RuntimeError("S&P PMI response is an AWS WAF challenge page, not release content")
        return fetched_url, payload


def backfill_sp_pmi(base_dir: Path, run_id: str) -> dict[str, Any]:
    storage = SpPmiStorage(base_dir)
    raw_run = RawSnapshotRun(storage.raw_root, run_id, "sp_global_pmi")
    client = SpPmiClient(timeout_seconds=30.0)
    errors: dict[str, Any] = {}
    observations = []
    home_url = SpPmiClient.HOME_URL
    try:
        fetched_url, payload = _pmi_fetch_with_cache_bust(client, home_url)
        raw_run.write_bytes("home/index.html", payload, source_url=fetched_url, status_code=200, metadata={"public_scope": "latest headline cards"}, gzip_payload=True)
        home_cards = client.extract_index_cards(payload.decode("utf-8", errors="replace"), fetched_at=utc_now(), source_url=fetched_url)
        observations.extend(home_cards)
        release_links = client.extract_release_links(payload.decode("utf-8", errors="replace"), fetched_url)
    except Exception as exc:
        errors["homepage"] = f"{type(exc).__name__}: {exc}"
        release_links = []
        LOGGER.warning("S&P PMI homepage failed: %s", errors["homepage"])

    try:
        fetched_url, payload = _pmi_fetch_with_cache_bust(client, SpPmiClient.RELEASES_URL)
        raw_run.write_bytes("release_calendar/index.html", payload, source_url=fetched_url, status_code=200, metadata={"public_scope": "release links"}, gzip_payload=True)
        release_links.extend(client.extract_release_links(payload.decode("utf-8", errors="replace"), fetched_url))
    except Exception as exc:
        errors["release_calendar"] = f"{type(exc).__name__}: {exc}"

    unique_release_links: list[str] = []
    for link in release_links:
        if link not in unique_release_links:
            unique_release_links.append(link)
    release_records = 0
    release_failures = 0
    consecutive_release_failures = 0
    for number, url in enumerate(unique_release_links[:250], start=1):
        try:
            fetched_url, payload = _pmi_fetch_with_cache_bust(client, url)
            raw_run.write_bytes(
                f"releases/{number:04d}_{_url_hash(url)}.html",
                payload,
                source_url=fetched_url,
                status_code=200,
                metadata={"release_url": url},
                gzip_payload=True,
            )
            parsed = client.parse_release_html(payload.decode("utf-8", errors="replace"), fetched_url, fetched_at=utc_now())
            if parsed is not None:
                observations.append(parsed)
                release_records += 1
            consecutive_release_failures = 0
        except Exception as exc:
            release_failures += 1
            consecutive_release_failures += 1
            if release_failures <= 5:
                errors[f"release_{number}"] = f"{type(exc).__name__}: {exc}"
            if consecutive_release_failures >= 12:
                errors["release_fetch_stop"] = "Stopped after 12 consecutive public release-page failures; homepage headline cards remain available."
                break

    if release_failures:
        errors["release_fetch_summary"] = {"attempted": min(len(unique_release_links), 250), "failed": release_failures, "sample_errors_recorded": min(release_failures, 5)}
    # If a release page has the same period/region/sector as a card, its
    # sub-index fields and exact release date should replace the headline-only
    # card because it was fetched later in this list.
    normalized_total = len(storage.upsert_observations(observations)) if observations else len(storage.load_observations())
    periods = [obs.period for obs in observations if obs.period]
    manifest = _save_source_manifest(
        raw_run,
        row_count=len(observations),
        errors=errors,
        normalized_outputs=_output_map(storage, ["sp_pmi_subindices.parquet", "sp_pmi_subindices.csv"]),
        coverage={
            "homepage_cards": len([item for item in observations if item.source_url and "/Home/Index" in item.source_url]),
            "release_links": len(unique_release_links),
            "release_records_parsed": release_records,
            "rows_fetched": len(observations),
            "min_period": min(periods) if periods else None,
            "max_period": max(periods) if periods else None,
            "frequency": "monthly public headline/release pages",
            "coverage_note": "Public pages expose headline readings and commentary; S&P Global's underlying full PMI dataset is not treated as free/public here.",
        },
    )
    return {
        "status": _status(len(observations), errors),
        "rows_fetched": len(observations),
        "rows_normalized_total": normalized_total,
        "manifest": _relative_to_base(base_dir, manifest),
        "errors": errors,
    }


def backfill_msci(base_dir: Path, run_id: str, workers: int) -> dict[str, Any]:
    storage = MsciIndexReviewStorage(base_dir)
    raw_run = RawSnapshotRun(storage.raw_root, run_id, "msci_index_reviews")
    errors: dict[str, Any] = {}
    links: list[str] = []
    page_status: dict[str, Any] = {}
    page_client = MsciIndexReviewClient(timeout_seconds=45.0)
    for number, url in enumerate(MSCI_REVIEW_URLS, start=1):
        try:
            fetched_url, payload = page_client.fetch_review_page(url)
            raw_run.write_bytes(
                f"review_pages/page_{number:02d}.html",
                payload,
                source_url=fetched_url,
                status_code=200,
                metadata={"page_url": url},
                gzip_payload=True,
            )
            extracted = page_client.extract_public_list_links(payload.decode("utf-8", errors="replace"), fetched_url)
            links.extend(link for link in extracted if link not in links)
            page_status[url] = {"status": "ok", "public_list_links": len(extracted)}
        except Exception as exc:
            page_status[url] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            errors[f"review_page_{number}"] = page_status[url]["error"]

    observations = []
    fetched_count = 0
    failed_count = 0
    def fetch_one(url: str) -> tuple[str, bytes | None, str | None]:
        try:
            client = MsciIndexReviewClient(timeout_seconds=60.0)
            fetched_url, payload = client.fetch_public_list(url)
            return fetched_url, payload, None
        except Exception as exc:
            return url, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as executor:
        future_map = {executor.submit(fetch_one, url): url for url in links}
        for number, future in enumerate(as_completed(future_map), start=1):
            requested_url = future_map[future]
            fetched_url, payload, error = future.result()
            if error or payload is None:
                failed_count += 1
                if failed_count <= 10:
                    errors[f"public_list_{failed_count}"] = {"url": requested_url, "error": error}
                continue
            fetched_count += 1
            filename = _slug(urlparse(fetched_url).path.rsplit("/", 1)[-1])
            raw_run.write_bytes(
                f"public_lists/{filename}_{_url_hash(fetched_url)}.pdf",
                payload,
                source_url=fetched_url,
                status_code=200,
                metadata={"content_type": "application/pdf"},
            )
            try:
                parsed = MsciIndexReviewClient.parse_public_list_pdf(payload, fetched_url, fetched_at=utc_now())
                observations.extend(parsed)
            except Exception as exc:
                errors[f"parse_{fetched_count}"] = {"url": fetched_url, "error": f"{type(exc).__name__}: {exc}"}
            if number % 25 == 0:
                LOGGER.info("MSCI public lists processed %s/%s", number, len(links))

    if failed_count:
        errors["public_list_fetch_summary"] = {"attempted": len(links), "fetched": fetched_count, "failed": failed_count}
    normalized_total = len(storage.upsert_events(observations)) if observations else len(storage.load_events())
    effective_dates = [item.effective_date for item in observations if item.effective_date]
    manifest = _save_source_manifest(
        raw_run,
        row_count=len(observations),
        errors=errors,
        normalized_outputs=_output_map(storage, ["msci_rebalance_events.parquet", "msci_rebalance_events.csv"]),
        coverage={
            "review_pages": page_status,
            "public_list_links": len(links),
            "public_list_pdfs_fetched": fetched_count,
            "public_list_pdfs_failed": failed_count,
            "rows_fetched": len(observations),
            "min_effective_date": min(effective_dates) if effective_dates else None,
            "max_effective_date": max(effective_dates) if effective_dates else None,
            "identifier_note": "MSCI public review PDFs generally expose security names, not exchange tickers; ticker remains blank and is not guessed.",
            "license_note": "MSCI public PDFs include redistribution/derivative-use restrictions; raw artifacts remain local and ignored.",
        },
    )
    return {
        "status": _status(len(observations), errors),
        "rows_fetched": len(observations),
        "rows_normalized_total": normalized_total,
        "manifest": _relative_to_base(base_dir, manifest),
        "errors": errors,
    }


_HKEX_THREAD_LOCAL = threading.local()


def _hkex_fetch_day(trade_date: str) -> dict[str, Any]:
    client = getattr(_HKEX_THREAD_LOCAL, "client", None)
    if client is None:
        client = HkexMarketFlowClient(timeout_seconds=25.0)
        _HKEX_THREAD_LOCAL.client = client
    result: dict[str, Any] = {"trade_date": trade_date, "daily": None, "short": None, "errors": {}}
    for kind in ("daily", "short"):
        try:
            url, payload = client.fetch_dated_file(kind, trade_date)
            result[kind] = {"url": url, "payload": payload, "status_code": 200}
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            result["errors"][kind] = {"status_code": status_code, "error": f"{type(exc).__name__}: {exc}"}
        except Exception as exc:
            result["errors"][kind] = {"status_code": None, "error": f"{type(exc).__name__}: {exc}"}
    return result


def backfill_hkex(base_dir: Path, run_id: str, start: str, end: str, workers: int) -> dict[str, Any]:
    storage = HkexMarketFlowStorage(base_dir)
    raw_run = RawSnapshotRun(storage.raw_root, run_id, "hkex_market_flow")
    errors: dict[str, Any] = {}
    trade_dates = _date_range(start, end)
    observations = []
    daily_success = short_success = 0
    expected_missing = {"daily": 0, "short": 0}
    unexpected_errors: list[dict[str, Any]] = []
    parsed_short_nonzero = 0
    client_parser = HkexMarketFlowClient
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as executor:
        futures = {executor.submit(_hkex_fetch_day, trade_date): trade_date for trade_date in trade_dates}
        for number, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            trade_date = result["trade_date"]
            daily = result.get("daily")
            short = result.get("short")
            if daily:
                daily_success += 1
                raw_run.write_bytes(
                    f"daily/{trade_date.replace('-', '')}.js",
                    daily["payload"],
                    source_url=daily["url"],
                    status_code=200,
                    metadata={"trade_date": trade_date, "kind": "official Stock Connect historical daily"},
                    gzip_payload=True,
                )
            if short:
                short_success += 1
                raw_run.write_bytes(
                    f"short_selling/{trade_date.replace('-', '')}.js",
                    short["payload"],
                    source_url=short["url"],
                    status_code=200,
                    metadata={"trade_date": trade_date, "kind": "official A-share short-selling detail"},
                    gzip_payload=True,
                )
            for kind, issue in result.get("errors", {}).items():
                if issue.get("status_code") == 404:
                    expected_missing[kind] += 1
                else:
                    if len(unexpected_errors) < 20:
                        unexpected_errors.append({"trade_date": trade_date, "kind": kind, **issue})

            daily_metrics = client_parser.parse_daily_statistics(daily["payload"]) if daily else {}
            short_metrics = client_parser.parse_short_selling_metrics(short["payload"]) if short else {}
            has_data = bool(daily_metrics or short_metrics)
            if has_data:
                short_turnover = short_metrics.get("short_selling_turnover_rmb_mln")
                if short_turnover not in (None, 0.0):
                    parsed_short_nonzero += 1
                observations.append(
                    client_parser.derive_flow_metrics(
                        trade_date=trade_date,
                        sb_buy_hkd=daily_metrics.get("southbound_buy_hkd_mln"),
                        sb_sell_hkd=daily_metrics.get("southbound_sell_hkd_mln"),
                        nb_buy_rmb=None,
                        nb_sell_rmb=None,
                        total_mkt_hkd=None,
                        short_turnover_hkd=None,
                        short_turnover_rmb=short_turnover,
                        short_selling_security_count=short_metrics.get("short_selling_security_count"),
                        short_turnover_shares=short_metrics.get("short_selling_turnover_shares"),
                        northbound_total_rmb=daily_metrics.get("northbound_total_turnover_rmb_mln"),
                    )
                )
            if number % 250 == 0:
                LOGGER.info("HKEX dates processed %s/%s", number, len(trade_dates))

    if unexpected_errors:
        errors["unexpected_fetch_errors"] = unexpected_errors
    if daily_success == 0:
        errors["daily_availability"] = "No official HKEX daily Stock Connect files were fetched."
    if short_success == 0:
        errors["short_availability"] = "No official HKEX short-selling files were fetched."
    if short_success and parsed_short_nonzero == 0:
        errors["short_quality_note"] = "All fetched short-selling value aggregates are zero; shares/security counts are retained, but this needs source-level validation before signal use."

    normalized_total = len(storage.upsert_observations(observations)) if observations else len(storage.load_observations())
    observed_dates = [item.trade_date for item in observations if item.trade_date]
    manifest = _save_source_manifest(
        raw_run,
        row_count=len(observations),
        errors=errors,
        normalized_outputs=_output_map(storage, ["hkex_market_flow_daily.parquet", "hkex_market_flow_daily.csv"]),
        coverage={
            "requested_start": start,
            "requested_end": end,
            "weekdays_requested": len(trade_dates),
            "daily_files_fetched": daily_success,
            "short_files_fetched": short_success,
            "expected_404_non_trading_or_holiday": expected_missing,
            "rows_fetched": len(observations),
            "min_trade_date": min(observed_dates) if observed_dates else None,
            "max_trade_date": max(observed_dates) if observed_dates else None,
            "deduplication_boundary": "official HKEX aggregate cross-check; existing Eastmoney southbound pipeline is not touched",
            "units_note": "Southbound turnover is HKD million; northbound and short-selling fields are RMB million where populated.",
        },
    )
    return {
        "status": _status(len(observations), errors),
        "rows_fetched": len(observations),
        "rows_normalized_total": normalized_total,
        "manifest": _relative_to_base(base_dir, manifest),
        "errors": errors,
    }


def _write_master_manifest(base_dir: Path, run_id: str, started_at: str, results: dict[str, Any], args: argparse.Namespace) -> Path:
    root = base_dir / "data" / "raw" / "free_institutional_backfill" / run_id
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "manifest_version": "free_public_data_backfill.v1",
        "run_id": run_id,
        "started_at_utc": started_at,
        "finished_at_utc": utc_now(),
        "status": "ok" if all(item.get("status") == "ok" for item in results.values()) else ("partial" if any(item.get("rows_fetched", 0) for item in results.values()) else "failed"),
        "scope": {
            "sources": list(results),
            "eia_start": args.eia_start,
            "eia_end": args.eia_end,
            "hkex_start": args.hkex_start,
            "hkex_end": args.end_date,
            "workers": args.workers,
        },
        "source_manifests": {source: result.get("manifest") for source, result in results.items()},
        "results": results,
        "non_duplication_boundary": [
            "quantamental-lab FRED/OFR/VIX/CFTC lanes excluded",
            "market_monitor Eastmoney southbound lane excluded",
            "hk_real_estate HKMA mortgage RMS lane excluded",
            "hk_transport airline Stock Connect short lane excluded",
            "hk_transport EIA benchmark price lane excluded",
        ],
    }
    path = root / "manifest.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill the new free institutional-data lanes with raw manifests.")
    parser.add_argument("--base-dir", type=Path, default=Path("."))
    parser.add_argument("--source", action="append", choices=RUN_SOURCES, help="Run only this source; repeat for multiple sources. Default: all.")
    parser.add_argument("--eia-start", default="2019-01-01T00")
    parser.add_argument("--eia-end", default=f"{date.today().isoformat()}T23")
    parser.add_argument("--hkex-start", default="2019-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    base_dir = args.base_dir.resolve()
    sources = args.source or list(RUN_SOURCES)
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    started_at = utc_now()
    results: dict[str, Any] = {}
    LOGGER.info("Starting free institutional-data backfill %s for %s", run_id, ",".join(sources))
    for source in sources:
        LOGGER.info("Starting source %s", source)
        try:
            if source == "bis":
                result = backfill_bis(base_dir, run_id)
            elif source == "hkma":
                result = backfill_hkma(base_dir, run_id)
            elif source == "eia":
                result = backfill_eia(base_dir, run_id, args.eia_start, args.eia_end)
            elif source == "cme":
                result = backfill_cme(base_dir, run_id)
            elif source == "factset":
                result = backfill_factset(base_dir, run_id)
            elif source == "sp_pmi":
                result = backfill_sp_pmi(base_dir, run_id)
            elif source == "msci":
                result = backfill_msci(base_dir, run_id, args.workers)
            elif source == "hkex":
                result = backfill_hkex(base_dir, run_id, args.hkex_start, args.end_date, args.workers)
            else:  # pragma: no cover
                raise ValueError(f"unknown source {source}")
        except Exception as exc:
            LOGGER.exception("Source %s crashed", source)
            result = {"status": "failed", "rows_fetched": 0, "errors": {"runner": f"{type(exc).__name__}: {exc}"}}
        results[source] = result
        LOGGER.info("Finished source %s: %s rows, status=%s", source, result.get("rows_fetched", 0), result.get("status"))
    manifest = _write_master_manifest(base_dir, run_id, started_at, results, args)
    print(json.dumps({"run_id": run_id, "manifest": _relative_to_base(base_dir, manifest), "results": results}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    main()
