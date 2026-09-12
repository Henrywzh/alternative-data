from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import logging
from pathlib import Path
from uuid import uuid4

from .client import EiaEnergyClient
from .config import DEFAULT_RESPONDENTS, resolve_api_key
from .storage import EiaEnergyStorage

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 7


class EiaEnergyPipeline:
    def __init__(self, base_dir: Path, client: EiaEnergyClient | None = None) -> None:
        self.base_dir = base_dir
        self.storage = EiaEnergyStorage(base_dir)
        self.api_key = resolve_api_key(base_dir)
        self.client = client or EiaEnergyClient(api_key=self.api_key)

    def run(
        self,
        respondents: list[str] | None = None,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, object]:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        logger.info("Starting EIA Energy Ingestion Run: %s", run_id)
        errors: dict[str, str] = {}

        # A missing key is a configuration error, not an empty day. Without
        # this the request goes out unauthenticated and fails at the HTTP
        # layer with an opaque 403.
        if not self.api_key:
            errors["api_key"] = (
                "EIA_API_KEY is not set. Export it, or add it to the repository's "
                ".config file alongside the other provider keys."
            )
            return {"run_id": run_id, "grid_observations_written": 0, "errors": errors}

        last = date.fromisoformat(end) if end else datetime.now(timezone.utc).date()
        first = date.fromisoformat(start) if start else last - timedelta(days=DEFAULT_LOOKBACK_DAYS)

        written = 0
        try:
            # iter_hourly_grid_generation_pages, not get_hourly_grid_generation:
            # the latter takes a `length` that caps ROWS, not hours. With five
            # respondents and eight fuel types a "168" meant about five hours of
            # data, not the week the number implies, and it could not page past
            # the API's 5,000-row response cap at all.
            batch = []
            for respondent, offset, _payload, observations in self.client.iter_hourly_grid_generation_pages(
                respondents=respondents or DEFAULT_RESPONDENTS,
                start=first.isoformat(),
                end=last.isoformat(),
            ):
                batch.extend(observations)
                logger.debug("EIA %s offset %s: %s rows", respondent, offset, len(observations))
            if batch:
                written = len(self.storage.upsert_grid_hourly(batch))
        except Exception as exc:
            logger.error("Error fetching EIA grid hourly data: %s", exc)
            errors["grid_hourly"] = f"{type(exc).__name__}: {exc}"

        return {
            "run_id": run_id,
            "requested_start": first.isoformat(),
            "requested_end": last.isoformat(),
            "grid_observations_written": written,
            "errors": errors,
        }
