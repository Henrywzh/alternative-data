from __future__ import annotations

import json
from pathlib import Path

import pytest


NOTEBOOKS = [
    "00_data_catalog.ipynb",
    "01_weekly_openrouter_usage.ipynb",
    "02_provider_daily_economics.ipynb",
    "03_frontier_intelligence_dynamics.ipynb",
]


@pytest.mark.parametrize("notebook_name", NOTEBOOKS)
def test_notebook_smoke_executes_top_to_bottom(notebook_name: str) -> None:
    notebook_path = Path(__file__).resolve().parents[1] / "notebooks" / notebook_name
    payload = json.loads(notebook_path.read_text(encoding="utf-8"))
    namespace: dict[str, object] = {"__name__": "__main__"}

    for cell in payload["cells"]:
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        if not source.strip():
            continue
        exec(compile(source, str(notebook_path), "exec"), namespace)
