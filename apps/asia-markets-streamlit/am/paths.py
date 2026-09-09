"""Filesystem paths and sys.path bootstrap for the Asia Markets terminal.

Importing this package inserts the repo root and src/ layout root into
sys.path so the domain packages (market_monitor, global_market_regime)
resolve the same way they did when app.py was a single top-level script.
"""

from __future__ import annotations

import sys
from pathlib import Path

# apps/asia-markets-streamlit/am/paths.py -> repo root is three parents up.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# The domain packages live under src/ and pyproject maps them to the top level
# (package-dir = {"" = "src"}), so market_monitor is the real module name.
# Importing them as src.market_monitor only ever worked by accident: src has no
# __init__.py, so it resolves as a PEP 420 namespace package, and any installed
# distribution shipping a top-level src wins over the repo directory.
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

ARTIFACT_ROOT = REPO_ROOT / "apps" / "asia-markets-dashboard" / ".generated"
