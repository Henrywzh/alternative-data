"""Control Tower V1's local read, filter, and formatting API."""

from pathlib import Path
import sys

# Ensure repository root is on sys.path deterministically before importing modules that depend on src
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from .config import artifact_fingerprint
from .coverage import (
    COVERAGE_STATUS_DESCRIPTIONS,
    COVERAGE_STATUS_LABELS,
    COVERAGE_STATUS_ORDER,
    CoverageCell,
    CoverageRow,
    CoverageStatusCode,
    DataCoverageSummary,
    STAGE1_BASKET_ID,
    Stage1CoverageMatrix,
    Stage1EntityCoverage,
    Stage1ListingCoverage,
    build_data_coverage_summary,
    build_stage1_coverage_matrix,
)
from .filters import apply_event_filters
from .formatting import format_t_minus
from .models import ControlTowerSnapshot, EventFilters
from .repository import ControlTowerRepository, ControlTowerStartupError

__all__ = [
    "ControlTowerRepository",
    "ControlTowerSnapshot",
    "ControlTowerStartupError",
    "COVERAGE_STATUS_DESCRIPTIONS",
    "COVERAGE_STATUS_LABELS",
    "COVERAGE_STATUS_ORDER",
    "CoverageCell",
    "CoverageRow",
    "CoverageStatusCode",
    "DataCoverageSummary",
    "EventFilters",
    "STAGE1_BASKET_ID",
    "Stage1CoverageMatrix",
    "Stage1EntityCoverage",
    "Stage1ListingCoverage",
    "apply_event_filters",
    "artifact_fingerprint",
    "build_data_coverage_summary",
    "build_stage1_coverage_matrix",
    "format_t_minus",
]
