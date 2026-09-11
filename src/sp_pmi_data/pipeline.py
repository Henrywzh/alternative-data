from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from uuid import uuid4

from .client import SpPmiClient
from .storage import SpPmiStorage

logger = logging.getLogger(__name__)


class SpPmiPipeline:
    def __init__(self, base_dir: Path, client: SpPmiClient | None = None) -> None:
        self.base_dir = base_dir
        self.storage = SpPmiStorage(base_dir)
        self.client = client or SpPmiClient()

    def run(self) -> dict[str, object]:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        logger.info("Starting S&P PMI Ingestion Run: %s", run_id)
        # Collection for this source lives in the one-shot runner, which owns
        # the cross-source concerns (raw snapshot retention, SHA-256 manifests,
        # coverage accounting). This method used to return zero rows with an
        # empty error map, which reads as a successful run that collected
        # nothing -- the exact "green but empty" outcome the manifests exist to
        # make impossible. Failing loudly is the honest alternative.
        raise NotImplementedError(
            "SpPmiPipeline has no in-package collector. Run:\n"
            "  python3 scripts/backfill_free_institutional_data.py --sources sp_pmi"
        )
