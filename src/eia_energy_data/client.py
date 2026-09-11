from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import requests

from .config import DEFAULT_HEADERS, DEFAULT_RESPONDENTS, EIA_BASE_URL, EIA_BULK_EBA_URL
from .models import EiaGridHourlyObservation


class EiaEnergyClient:
    def __init__(self, api_key: str | None = None, base_url: str = EIA_BASE_URL, timeout_seconds: float = 25.0) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def fetch_route(self, route: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/{route.lstrip('/')}"
        payload = dict(params or {})
        if self.api_key:
            payload["api_key"] = self.api_key
        response = requests.get(url, headers=DEFAULT_HEADERS, params=payload, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.json()

    def fetch_bulk_to_path(self, path: Path, url: str = EIA_BULK_EBA_URL) -> Path:
        """Stream EIA's no-key EBA bulk ZIP to disk.

        The decompressed file is several gigabytes, so the backfill runner
        must not materialize either the ZIP or ``EBA.txt`` as one Python bytes
        object.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        bulk_headers = dict(DEFAULT_HEADERS)
        bulk_headers["Accept"] = "application/zip,application/x-zip-compressed,application/octet-stream,*/*"
        with requests.get(url, headers=bulk_headers, timeout=self.timeout_seconds, stream=True) as response:
            response.raise_for_status()
            with path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        return path

    def get_hourly_grid_generation(self, respondents: list[str] | None = None, length: int = 168) -> list[EiaGridHourlyObservation]:
        fetched_at = datetime.now(timezone.utc).isoformat()
        params: dict[str, Any] = {
            "frequency": "hourly",
            "data[0]": "value",
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": length,
        }
        for idx, respondent in enumerate(respondents or DEFAULT_RESPONDENTS):
            params[f"facets[respondent][{idx}]"] = respondent
        data = self.fetch_route("electricity/rto/fuel-type-data/data", params=params)
        records = data.get("response", {}).get("data", [])
        obs: list[EiaGridHourlyObservation] = []
        for row in records:
            timestamp = row.get("period")
            respondent = row.get("respondent")
            fuel = row.get("fueltype")
            raw = row.get("value")
            if timestamp and respondent and fuel:
                obs.append(
                    EiaGridHourlyObservation(
                        timestamp_utc=str(timestamp),
                        respondent=str(respondent),
                        fuel_type=str(fuel),
                        generation_mwh=float(raw) if raw is not None else None,
                        fetched_at=fetched_at,
                    )
                )
        return obs

    @staticmethod
    def parse_grid_rows(records: list[dict[str, Any]], fetched_at: str) -> list[EiaGridHourlyObservation]:
        observations: list[EiaGridHourlyObservation] = []
        for row in records:
            timestamp = row.get("period")
            respondent = row.get("respondent")
            fuel = row.get("fueltype")
            raw = row.get("value")
            if timestamp and respondent and fuel:
                observations.append(
                    EiaGridHourlyObservation(
                        timestamp_utc=str(timestamp),
                        respondent=str(respondent),
                        fuel_type=str(fuel),
                        generation_mwh=float(raw) if raw is not None else None,
                        fetched_at=fetched_at,
                    )
                )
        return observations

    def iter_hourly_grid_generation_pages(
        self,
        *,
        respondents: list[str],
        start: str,
        end: str,
        page_length: int = 5000,
    ) -> Iterator[tuple[str, int, dict[str, Any], list[EiaGridHourlyObservation]]]:
        """Yield raw API pages and parsed observations for a full time range.

        EIA's JSON response is capped at 5,000 rows.  A separate facet per
        balancing authority makes the pagination deterministic and avoids
        accidentally mixing duplicate rows when a caller resumes a run.
        """
        if page_length <= 0 or page_length > 5000:
            raise ValueError("EIA page_length must be between 1 and 5000")
        for respondent in respondents:
            offset = 0
            while True:
                params: dict[str, Any] = {
                    "frequency": "hourly",
                    "data[0]": "value",
                    "facets[respondent][0]": respondent,
                    "start": start,
                    "end": end,
                    "sort[0][column]": "period",
                    "sort[0][direction]": "asc",
                    "length": page_length,
                    "offset": offset,
                }
                payload = self.fetch_route("electricity/rto/fuel-type-data/data", params=params)
                response = payload.get("response", {})
                records = response.get("data", [])
                fetched_at = datetime.now(timezone.utc).isoformat()
                observations = self.parse_grid_rows(records, fetched_at)
                yield respondent, offset, payload, observations
                total = int(response.get("total", 0) or 0)
                if not records or offset + len(records) >= total:
                    break
                offset += len(records)
