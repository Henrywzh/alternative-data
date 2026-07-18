import logging
from datetime import datetime, timezone
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .models import FredSeriesMeta, FredObservation

logger = logging.getLogger(__name__)

def _build_retrying_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        connect=3,
        read=3,
        status=4,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session

class FredMacroClient:
    BASE_URL = "https://api.stlouisfed.org/fred"

    def __init__(self, api_key: str, timeout: int = 15):
        self.api_key = api_key
        self.timeout = timeout
        self.session = _build_retrying_session()

    def get_series_meta(self, series_id: str) -> FredSeriesMeta:
        url = f"{self.BASE_URL}/series"
        params = {"series_id": series_id, "api_key": self.api_key, "file_type": "json"}
        r = self.session.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()

        seriess = data.get("seriess", [])
        if not seriess:
            raise ValueError(f"FRED returned no series metadata for {series_id}")
        info = seriess[0]

        return FredSeriesMeta(
            series_id=series_id,
            title=info.get("title", ""),
            frequency=info.get("frequency_short", ""),
            units=info.get("units", ""),
            seasonal_adjustment=info.get("seasonal_adjustment_short", ""),
            observation_start=str(info.get("observation_start", "")),
            last_updated=str(info.get("last_updated", "")),
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    def get_observations(self, series_id: str, observation_start: str = "2015-01-01") -> list[FredObservation]:
        url = f"{self.BASE_URL}/series/observations"
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "observation_start": observation_start,
        }
        r = self.session.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()

        fetched_at = datetime.now(timezone.utc).isoformat()
        points = []
        skipped = 0
        for obs in data.get("observations", []):
            raw_value = obs.get("value", ".")
            if raw_value == "." or raw_value is None:
                skipped += 1
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                skipped += 1
                continue
            points.append(FredObservation(
                date=str(obs.get("date", "")),
                series_id=series_id,
                value=value,
                fetched_at=fetched_at,
            ))
        if skipped:
            logger.warning(f"Skipped {skipped} missing/malformed observations for {series_id}.")
        return points
