"""Orchestration for the HK REIT data pipeline.

No fallback/mock data path exists anywhere in this pipeline. If a source
returns nothing, the dataset's status is honestly recorded as "empty" or
"error" in the run manifest — never silently substituted with placeholder
numbers (see the hk_local_consumer pipeline review for why that matters).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from .config import NORMALIZED_DIR
from .sources.reit_price import fetch_reit_price_history, fetch_reit_spot_quotes
from .storage import save_normalized_dataset

logger = logging.getLogger(__name__)


class PipelineRunError(RuntimeError):
    """Raised by run_all_reit_pipelines when every dataset in a run failed or was empty."""


def _quality_status(df: pd.DataFrame, required_columns: list[str]) -> str:
    if df is None or df.empty:
        return "empty"
    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        return "invalid_missing_columns"
    if df[required_columns].isna().all(axis=None):
        return "invalid_all_null"
    return "success"


DATASETS: dict[str, dict[str, Any]] = {
    "hk_reit_spot_quotes_daily": {
        "fetch": fetch_reit_spot_quotes,
        "required_columns": ["ticker", "latest_price_hkd"],
    },
    "hk_reit_price_history_daily": {
        "fetch": fetch_reit_price_history,
        "required_columns": ["ticker", "close_hkd"],
    },
}


def run_reit_pipeline(run_id: str | None = None) -> Dict[str, Any]:
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}

    for dataset_name, spec in DATASETS.items():
        try:
            df = spec["fetch"](run_id=run_id)
        except Exception:
            logger.exception("Fetch failed for %s.", dataset_name)
            results[dataset_name] = {"status": "error", "records": 0}
            continue

        status = _quality_status(df, spec["required_columns"])
        if status != "success":
            logger.warning("%s produced no usable data (status=%s).", dataset_name, status)
            results[dataset_name] = {"status": status, "records": 0 if df is None else len(df)}
            continue

        write_result = save_normalized_dataset(dataset_name, df, run_id=run_id)
        results[dataset_name] = {
            "status": "success",
            "records": len(df),
            "run_id": write_result["run_id"],
        }

    _write_run_manifest(run_id, results)
    return results


def _write_run_manifest(run_id: str, results: Dict[str, Any]) -> Path:
    manifest_dir = NORMALIZED_DIR / "runs" / run_id
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    manifest = {
        "run_id": run_id,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "datasets": results,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def run_all_reit_pipelines(run_id: str | None = None) -> Dict[str, Any]:
    results = run_reit_pipeline(run_id=run_id)
    if all(r["status"] != "success" for r in results.values()):
        raise PipelineRunError(f"All REIT datasets failed or were empty in run {run_id}: {results}")
    return results
