from datetime import datetime, timezone
import logging
from pathlib import Path
from uuid import uuid4
from .client import OfrClient
from .storage import OfrStorage

logger = logging.getLogger(__name__)

class OfrPipeline:
    DEFAULT_MNEMONICS = [
        "FICC-SPONSORED_REPO_VOL",
        "FICC-SPONSORED_REVREPO_VOL",
        "FPF-ALLQHF_ALTERNATE_COUNT",
        "FPF-ALLQHF_CDSDOWN250BPS_P5",
        "FPF-ALLQHF_CDSDOWN250BPS_P50"
    ]

    def __init__(self, base_dir: Path, client: OfrClient | None = None) -> None:
        self.base_dir = base_dir
        self.storage = OfrStorage(base_dir)
        self.client = client or OfrClient()

    def run(self, mnemonics: list[str] | None = None) -> dict[str, int]:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        logger.info(f"Starting OFR Ingestion Run: {run_id}")

        # 1. Fetch and store the complete list of mnemonics
        try:
            logger.info("Fetching complete list of OFR mnemonics...")
            all_mnemonics = self.client.get_mnemonics()
            self.storage.write_raw_payload(run_id, "mnemonics_list", all_mnemonics)
            logger.info(f"Retrieved {len(all_mnemonics)} mnemonics.")
        except Exception as e:
            logger.error(f"Failed to fetch mnemonics list: {e}")
            raise

        # 2. Fetch metadata and timeseries for target mnemonics
        target_mnemonics = mnemonics or self.DEFAULT_MNEMONICS

        meta_records = []
        ts_records = []
        errors: dict[str, str] = {}

        for mn in target_mnemonics:
            logger.info(f"Processing mnemonic: {mn}")
            try:
                # Fetch metadata
                meta = self.client.get_metadata(mn)
                meta_records.append(meta)
                self.storage.write_raw_payload(run_id, f"meta_{mn}", meta.to_dict())

                # Fetch timeseries
                ts = self.client.get_timeseries(mn)
                ts_records.extend(ts)
                self.storage.write_raw_payload(run_id, f"ts_{mn}", [t.to_dict() for t in ts])
                logger.info(f"Retrieved {len(ts)} data points for {mn}.")
            except Exception as e:
                logger.error(f"Error fetching data for {mn}: {e}")
                errors[mn] = str(e)

        # 3. Upsert to storage
        mnemonics_written = 0
        ts_written = 0

        if meta_records:
            mn_df = self.storage.upsert_mnemonics(meta_records)
            mnemonics_written = len(mn_df)
            logger.info(f"Upserted mnemonics metadata. Total rows: {mnemonics_written}")

        if ts_records:
            ts_df = self.storage.upsert_timeseries(ts_records)
            ts_written = len(ts_df)
            logger.info(f"Upserted timeseries data points. Total rows: {ts_written}")

        return {
            "mnemonics_written": mnemonics_written,
            "timeseries_written": ts_written,
            "errors": errors,
        }
