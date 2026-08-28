"""Control Tower V1's local read, filter, and formatting API."""

from pathlib import Path
import sys

# Put the repository root and src/ on sys.path before importing anything that
# reaches into the domain packages.
#
# The root alone is not enough. src has no __init__.py, so `src.foo` resolves
# as a PEP 420 namespace package and loses to any installed distribution that
# ships a top-level `src`. That is how the sibling Streamlit app went down
# with an ImportError on Streamlit Cloud. pyproject maps these packages to the
# top level already (package-dir = {"" = "src"}), so research_control_tower is
# the name that does not depend on path luck.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _REPO_ROOT / "src"
for _path in (_REPO_ROOT, _SRC_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

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
