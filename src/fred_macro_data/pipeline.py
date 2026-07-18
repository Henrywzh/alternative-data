from datetime import datetime, timezone
import logging
from pathlib import Path
from uuid import uuid4
from .client import FredMacroClient
from .config import resolve_api_key
from .storage import FredMacroStorage

logger = logging.getLogger(__name__)

class FredMacroPipeline:
    # Systemic-risk / financial-conditions macro series, distinct from the
    # AI-demand PPI series already tracked in semiconductor_memory_data.
    DEFAULT_SERIES = [
        "SOFR",         # Secured Overnight Financing Rate
        "RRPONTSYD",    # Overnight Reverse Repurchase Agreements
        "NFCI",         # Chicago Fed National Financial Conditions Index
        "BAMLC0A0CM",   # ICE BofA US Corporate Index Option-Adjusted Spread
        "WALCL",        # Federal Reserve total assets (balance sheet)
    ]

    def __init__(self, base_dir: Path, client: FredMacroClient | None = None) -> None:
        self.base_dir = base_dir
        self.storage = FredMacroStorage(base_dir)
        self.client = client or FredMacroClient(api_key=resolve_api_key(base_dir))

    def run(self, series_ids: list[str] | None = None) -> dict:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        logger.info(f"Starting FRED Macro Ingestion Run: {run_id}")

        target_series = series_ids or self.DEFAULT_SERIES

        meta_records = []
        obs_records = []
        errors: dict[str, str] = {}

        for sid in target_series:
            logger.info(f"Processing series: {sid}")
            try:
                meta = self.client.get_series_meta(sid)
                meta_records.append(meta)
                self.storage.write_raw_payload(run_id, f"meta_{sid}", meta.to_dict())

                obs = self.client.get_observations(sid)
                obs_records.extend(obs)
                self.storage.write_raw_payload(run_id, f"obs_{sid}", [o.to_dict() for o in obs])
                logger.info(f"Retrieved {len(obs)} observations for {sid}.")
            except Exception as e:
                logger.error(f"Error fetching data for {sid}: {e}")
                errors[sid] = str(e)

        series_written = 0
        observations_written = 0

        if meta_records:
            meta_df = self.storage.upsert_series_meta(meta_records)
            series_written = len(meta_df)
            logger.info(f"Upserted series metadata. Total rows: {series_written}")

        if obs_records:
            obs_df = self.storage.upsert_observations(obs_records)
            observations_written = len(obs_df)
            logger.info(f"Upserted observations. Total rows: {observations_written}")

        return {
            "series_written": series_written,
            "observations_written": observations_written,
            "errors": errors,
        }
