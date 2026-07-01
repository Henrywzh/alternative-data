from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from signal_layer.models import (
    ASSET_SIGNAL_COLUMNS,
    METRIC_SIGNAL_COLUMNS,
    THEME_SIGNAL_COLUMNS,
    PipelineResult,
)
from signal_layer.registry import load_registries
from signal_layer.storage import SignalLayerStorage


class SignalLayerPipeline:
    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.storage = SignalLayerStorage(self.base_dir)

    def validate_registry(self) -> dict[str, int]:
        metrics, mappings = load_registries(self.base_dir)
        return {"metrics": int(len(metrics)), "asset_mappings": int(len(mappings))}

    def build(self, *, sources: list[str] | None = None) -> PipelineResult:
        load_registries(self.base_dir)
        run_id = _run_id()
        run_dir = self.storage.run_dir(run_id)
        selected_sources = sources or []
        datasets_written = {
            "metric_signals": 0,
            "asset_signals": 0,
            "theme_signals": 0,
        }
        self.storage.write_dataset(
            "metric_signals",
            pd.DataFrame(columns=METRIC_SIGNAL_COLUMNS),
            target_dir=run_dir,
        )
        self.storage.write_dataset(
            "asset_signals",
            pd.DataFrame(columns=ASSET_SIGNAL_COLUMNS),
            target_dir=run_dir,
        )
        self.storage.write_dataset(
            "theme_signals",
            pd.DataFrame(columns=THEME_SIGNAL_COLUMNS),
            target_dir=run_dir,
        )
        manifest = {
            "run_id": run_id,
            "sources": selected_sources,
            "datasets_written": datasets_written,
        }
        self.storage.write_run_manifest(manifest, target_dir=run_dir)
        self.storage.update_latest(run_dir)
        return PipelineResult(
            run_id=run_id,
            datasets_written=datasets_written,
            output_dir=str(run_dir),
        )


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
