from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from uuid import uuid4

from .client import BisMacroClient
from .config import BIS_CREDIT_GAP_BULK_URL
from .storage import BisMacroStorage

logger = logging.getLogger(__name__)


class BisMacroPipeline:
    def __init__(self, base_dir: Path, client: BisMacroClient | None = None) -> None:
        self.base_dir = base_dir
        self.storage = BisMacroStorage(base_dir)
        self.client = client or BisMacroClient()

    def run(self, target_areas: list[str] | None = None) -> dict[str, object]:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        logger.info("Starting BIS Macro Ingestion Run: %s", run_id)
        meta_records = []
        obs_records = []
        errors: dict[str, str] = {}
        try:
            bulk_payload = self.client.fetch_credit_gap_bulk()
            # Retain the payload before parsing it. Writing the snapshot after
            # a successful parse meant the one run whose parse failed was also
            # the one run with nothing to debug.
            self.storage.write_raw_bytes(run_id, "credit_gap_raw.zip", bulk_payload)
            df_cg = self.client.read_credit_gap_bulk(bulk_payload)
            meta_cg, obs_cg = self.client.parse_credit_gap_records(df_cg, target_areas=target_areas)
            meta_records.extend(meta_cg)
            obs_records.extend(obs_cg)
        except Exception as exc:
            logger.error("Error fetching BIS credit gap: %s", exc)
            errors["credit_gap"] = str(exc)
        series_written = len(self.storage.upsert_series_meta(meta_records)) if meta_records else 0
        observations_written = len(self.storage.upsert_observations(obs_records)) if obs_records else 0
        return {
            "run_id": run_id,
            "series_written": series_written,
            "observations_written": observations_written,
            "errors": errors,
        }
