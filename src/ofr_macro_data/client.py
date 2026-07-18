import logging
from datetime import datetime, timezone
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .models import OfrMnemonic, OfrDataPoint

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

class OfrClient:
    BASE_URL = "https://data.financialresearch.gov/hf/v1"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = _build_retrying_session()

    def get_mnemonics(self) -> list[str]:
        url = f"{self.BASE_URL}/metadata/mnemonics"
        r = self.session.get(url, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_metadata(self, mnemonic: str) -> OfrMnemonic:
        url = f"{self.BASE_URL}/metadata/query"
        r = self.session.get(url, params={"mnemonic": mnemonic}, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()

        description = data.get("description", {})
        schedule = data.get("schedule", {})

        return OfrMnemonic(
            mnemonic=mnemonic,
            name=description.get("name", ""),
            notes=description.get("notes", ""),
            frequency=schedule.get("observation_frequency", ""),
            start_date=str(schedule.get("start_date", "")),
            last_update=str(schedule.get("last_update", "")),
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    def get_timeseries(self, mnemonic: str) -> list[OfrDataPoint]:
        url = f"{self.BASE_URL}/series/timeseries"
        r = self.session.get(url, params={"mnemonic": mnemonic}, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()

        fetched_at = datetime.now(timezone.utc).isoformat()
        points = []
        skipped = 0
        if isinstance(data, list):
            for item in data:
                if len(item) == 2 and item[1] is not None:
                    date, val = item
                    points.append(OfrDataPoint(
                        date=date,
                        mnemonic=mnemonic,
                        value=float(val),
                        fetched_at=fetched_at
                    ))
                else:
                    skipped += 1
        else:
            logger.warning(f"Unexpected timeseries payload shape for {mnemonic}: {type(data).__name__}")
        if skipped:
            logger.warning(f"Skipped {skipped} malformed/null data points for {mnemonic}.")
        return points
