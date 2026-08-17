"""Shared contracts for Asia Markets forecast/backtest artifacts.

The package is intentionally additive.  Existing sector models, wide CSV
outputs, and dashboard consumers remain unchanged; the modules here provide a
stable long-form contract and evaluator for new consumers.
"""

from .metrics import (
    METRIC_POLICY_VERSION,
    build_metrics_manifest,
    compute_error_intervals,
    compute_metric_table,
)
from .storage import BacktestRunSpec, RunArtifactStore, dataframe_fingerprint, file_fingerprint, runtime_metadata
from .vocabulary import (
    EVALUABLE_STATUSES,
    PIT_GRADES,
    TRACK_IDS,
    EvaluationStatus,
    PitGrade,
)

__all__ = [
    "BacktestRunSpec",
    "EVALUABLE_STATUSES",
    "EvaluationStatus",
    "METRIC_POLICY_VERSION",
    "PIT_GRADES",
    "PitGrade",
    "RunArtifactStore",
    "TRACK_IDS",
    "dataframe_fingerprint",
    "file_fingerprint",
    "runtime_metadata",
    "compute_metric_table",
    "compute_error_intervals",
    "build_metrics_manifest",
]
