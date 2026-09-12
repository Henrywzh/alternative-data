from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from uuid import uuid4

from .client import HkmaMacroClient
from .config import INTERBANK_LIQUIDITY_PATH
from .storage import HkmaMacroStorage

logger = logging.getLogger(__name__)


class HkmaMacroPipeline:
    def __init__(self, base_dir: Path, client: HkmaMacroClient | None = None) -> None:
        self.base_dir = base_dir
        self.storage = HkmaMacroStorage(base_dir)
        self.client = client or HkmaMacroClient()

    def run(self) -> dict[str, object]:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        logger.info("Starting HKMA Macro Ingestion Run: %s", run_id)
        meta_records = []
        obs_records = []
        errors: dict[str, str] = {}

        try:
            # Fetch and retain first, parse second: a snapshot written only on
            # the success path is missing exactly when it is needed.
            raw_liq = self.client.fetch_endpoint(INTERBANK_LIQUIDITY_PATH)
            self.storage.write_raw_payload(run_id, "interbank_liquidity_raw", raw_liq)
            meta_liq, obs_liq = self.client.parse_interbank_liquidity(raw_liq)
            meta_records.append(meta_liq)
            obs_records.extend(obs_liq)
        except Exception as exc:
            logger.error("Error fetching HKMA interbank liquidity: %s", exc)
            errors["interbank_liquidity"] = str(exc)

        try:
            hibor_results = self.client.get_hibor_fixings()
            for meta_h, obs_h in hibor_results:
                meta_records.append(meta_h)
                obs_records.extend(obs_h)
            self.storage.write_raw_payload(
                run_id,
                "hibor_fixings",
                [o.to_dict() for o in obs_records if "HIBOR" in o.series_id],
            )
        except Exception as exc:
            logger.error("Error fetching HKMA HIBOR: %s", exc)
            errors["hibor_fixings"] = str(exc)

        series_written = 0
        observations_written = 0
        if meta_records:
            series_written = len(self.storage.upsert_series_meta(meta_records))
        if obs_records:
            observations_written = len(self.storage.upsert_observations(obs_records))
        return {
            "run_id": run_id,
            "series_written": series_written,
            "observations_written": observations_written,
            "errors": errors,
        }
