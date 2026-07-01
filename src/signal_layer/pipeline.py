from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from signal_layer.aggregation import build_asset_signals, build_theme_signals
from signal_layer.builders.provider_adoption import build_provider_adoption_signals
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
        metric_registry, asset_mapping = load_registries(self.base_dir)
        run_id, run_dir = self._create_run()
        selected_sources = sources or _implemented_sources(metric_registry)
        metric_frames: list[pd.DataFrame] = []
        if "provider_adoption" in selected_sources:
            metric_frames.append(build_provider_adoption_signals(self.base_dir, metric_registry))
        metric_signals = (
            pd.concat(metric_frames, ignore_index=True)
            if metric_frames
            else pd.DataFrame(columns=METRIC_SIGNAL_COLUMNS)
        )
        asset_signals = build_asset_signals(metric_signals, asset_mapping, metric_registry)
        theme_signals = build_theme_signals(asset_signals)
        datasets_written = {
            "metric_signals": int(len(metric_signals)),
            "asset_signals": int(len(asset_signals)),
            "theme_signals": int(len(theme_signals)),
        }
        self.storage.write_dataset(
            "metric_signals",
            metric_signals,
            target_dir=run_dir,
        )
        self.storage.write_dataset(
            "asset_signals",
            asset_signals if not asset_signals.empty else pd.DataFrame(columns=ASSET_SIGNAL_COLUMNS),
            target_dir=run_dir,
        )
        self.storage.write_dataset(
            "theme_signals",
            theme_signals if not theme_signals.empty else pd.DataFrame(columns=THEME_SIGNAL_COLUMNS),
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

    def _create_run(self) -> tuple[str, Path]:
        for _ in range(10):
            run_id = _run_id()
            try:
                return run_id, self.storage.create_run_dir(run_id)
            except FileExistsError:
                continue
        raise RuntimeError("Unable to allocate a unique signal pipeline run directory")


def _run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{uuid4().hex[:8]}"


def _implemented_sources(metric_registry: pd.DataFrame) -> list[str]:
    implemented = {"provider_adoption"}
    available = metric_registry["source"].dropna().astype(str)
    return [source for source in available.unique().tolist() if source in implemented]
