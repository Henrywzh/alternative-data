from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from typing import Any

import pandas as pd
import requests

from .config import (
    DEFAULT_HEADERS,
    HIBOR_HISTORY_FALLBACK_URL,
    HIBOR_PATH,
    HKMA_BASE_URL,
    INTERBANK_LIQUIDITY_PATH,
)
from .models import AGGREGATOR, OFFICIAL_API, HkmaObservation, HkmaSeriesMeta

logger = logging.getLogger(__name__)

def _as_numeric(value: object) -> float | None:
    """Coerce an HKMA field to float, or None when it is not a number.

    HKMA returns sentinels such as "-", "" and "N/A" in place of a value. A
    bare ``float()`` raises on those, and because the pipeline catches per
    source rather than per field, one bad cell aborted the fetch and lost all
    eight HIBOR series for the run.
    """
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--", "N/A", "n/a", "NA", "null", "None"}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None



class HkmaMacroClient:
    def __init__(
        self,
        base_url: str = HKMA_BASE_URL,
        timeout_seconds: float = 20.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def fetch_endpoint(self, path: str, pagesize: int = 1000, offset: int = 0) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = self.session.get(
            url,
            headers=DEFAULT_HEADERS,
            params={"pagesize": pagesize, "offset": offset},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def fetch_hibor_history_fallback(self, url: str = HIBOR_HISTORY_FALLBACK_URL) -> tuple[bytes, pd.DataFrame]:
        """Fetch the public 2017-present HIBOR history used as a fallback.

        ``il_2.json`` is the underlying public report behind
        ``akshare.macro_china_hk_market_info``.  Returning both the raw bytes
        and a tidy frame lets the caller preserve the exact upstream payload.
        """
        response = self.session.get(
            url,
            params={"_": int(time.time())},
            headers=DEFAULT_HEADERS,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.content
        body = response.json()
        values = body.get("values", {})
        rows: list[dict[str, Any]] = []
        field_map = {
            "ON": "ON",
            "1W": "1W",
            "2W": "2W",
            "1M": "1M",
            "2M": "2M",
            "3M": "3M",
            "6M": "6M",
            "1Y": "1Y",
        }
        for date_text, value_map in values.items():
            row: dict[str, Any] = {"date": str(date_text)}
            for upstream_key, normalized_key in field_map.items():
                cell = value_map.get(upstream_key)
                row[normalized_key] = cell[0] if isinstance(cell, (list, tuple)) and cell else None
            rows.append(row)
        frame = pd.DataFrame(rows, columns=["date", *field_map.values()])
        if not frame.empty:
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            for column in field_map.values():
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            frame = frame.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        return payload, frame

    @staticmethod
    def parse_hibor_history_records(
        frame: pd.DataFrame,
        *,
        fetched_at: str | None = None,
        source_url: str = HIBOR_HISTORY_FALLBACK_URL,
    ) -> list[tuple[HkmaSeriesMeta, list[HkmaObservation]]]:
        fetched = fetched_at or datetime.now(timezone.utc).isoformat()
        series_map = {
            "ON": ("HKMA_HIBOR_ON", "HIBOR Overnight Fixing"),
            "1W": ("HKMA_HIBOR_1W", "HIBOR 1-Week Fixing"),
            "2W": ("HKMA_HIBOR_2W", "HIBOR 2-Week Fixing"),
            "1M": ("HKMA_HIBOR_1M", "HIBOR 1-Month Fixing"),
            "2M": ("HKMA_HIBOR_2M", "HIBOR 2-Month Fixing"),
            "3M": ("HKMA_HIBOR_3M", "HIBOR 3-Month Fixing"),
            "6M": ("HKMA_HIBOR_6M", "HIBOR 6-Month Fixing"),
            "1Y": ("HKMA_HIBOR_12M", "HIBOR 12-Month Fixing"),
        }
        results: list[tuple[HkmaSeriesMeta, list[HkmaObservation]]] = []
        for column, (series_id, title) in series_map.items():
            meta = HkmaSeriesMeta(
                series_id=series_id,
                title=title,
                category="Rates",
                frequency="D",
                units="Percent",
                fetched_at=fetched,
                source_tier=AGGREGATOR,
            )
            observations: list[HkmaObservation] = []
            if column not in frame.columns or "date" not in frame.columns:
                results.append((meta, observations))
                continue
            for _, row in frame.iterrows():
                value = row.get(column)
                observations.append(
                    HkmaObservation(
                        date=str(row["date"]),
                        series_id=series_id,
                        value=_as_numeric(value) if pd.notna(value) else None,
                        fetched_at=fetched,
                        source_url=source_url,
                        source_tier=AGGREGATOR,
                    )
                )
            results.append((meta, observations))
        return results

    def get_interbank_liquidity(self) -> tuple[HkmaSeriesMeta, list[HkmaObservation]]:
        fetched_at = datetime.now(timezone.utc).isoformat()
        data = self.fetch_endpoint(INTERBANK_LIQUIDITY_PATH)
        meta = HkmaSeriesMeta(
            series_id="HKMA_AGGREGATE_BALANCE",
            title="HKMA Aggregate Balance (Interbank Liquidity)",
            category="Liquidity",
            frequency="D",
            units="HKD_Million",
            fetched_at=fetched_at,
            source_tier=OFFICIAL_API,
        )
        records = data.get("result", {}).get("records", [])
        obs: list[HkmaObservation] = []
        for row in records:
            date = row.get("end_of_date")
            # `or` here dropped a legitimate closing_balance of 0 and fell
            # through to a key that is usually absent, storing NULL for a
            # real observation.
            raw = row.get("closing_balance")
            if raw is None:
                raw = row.get("aggregate_balance")
            value = _as_numeric(raw)
            if date:
                obs.append(
                    HkmaObservation(
                        date=str(date),
                        series_id="HKMA_AGGREGATE_BALANCE",
                        value=value,
                        fetched_at=fetched_at,
                        source_url=f"{self.base_url}{INTERBANK_LIQUIDITY_PATH}",
                        source_tier=OFFICIAL_API,
                    )
                )
        return meta, obs

    def get_hibor_fixings(self) -> list[tuple[HkmaSeriesMeta, list[HkmaObservation]]]:
        fetched_at = datetime.now(timezone.utc).isoformat()
        data = self.fetch_endpoint(HIBOR_PATH)
        records = data.get("result", {}).get("records", [])
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
            meta = HkmaSeriesMeta(
                series_id=series_id,
                title=title,
                category="Rates",
                frequency="D",
                units="Percent",
                fetched_at=fetched_at,
                source_tier=OFFICIAL_API,
            )
            obs: list[HkmaObservation] = []
            for row in records:
                date = row.get("end_of_date")
                value = _as_numeric(row.get(field))
                if date:
                    obs.append(
                        HkmaObservation(
                            date=str(date),
                            series_id=series_id,
                            value=value,
                            fetched_at=fetched_at,
                            source_url=f"{self.base_url}{HIBOR_PATH}",
                            source_tier=OFFICIAL_API,
                        )
                    )
            results.append((meta, obs))
        return results
