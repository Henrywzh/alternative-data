from __future__ import annotations

import json
import os
import sys
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


@pytest.mark.parametrize("notebook_name", NOTEBOOKS)
def test_notebook_bootstraps_src_path_without_test_conftest(notebook_name: str) -> None:
    notebook_path = Path(__file__).resolve().parents[1] / "notebooks" / notebook_name
    payload = json.loads(notebook_path.read_text(encoding="utf-8"))
    namespace: dict[str, object] = {"__name__": "__main__"}
    repo_root = notebook_path.parents[1]
    src_dir = repo_root / "src"
    original_sys_path = list(sys.path)
    original_cwd = Path.cwd()
    removed_modules = {
        name: module
        for name, module in list(sys.modules.items())
        if name in {"research_data", "dashboard"} or name.startswith("research_data.") or name.startswith("dashboard.")
    }

    try:
        sys.path[:] = [path for path in sys.path if Path(path).resolve() not in {repo_root, src_dir}]
        os.chdir(notebook_path.parent)
        for name in removed_modules:
            sys.modules.pop(name, None)

        for cell in payload["cells"]:
            if cell.get("cell_type") != "code":
                continue
            source = "".join(cell.get("source", []))
            if not source.strip():
                continue
            exec(compile(source, str(notebook_path), "exec"), namespace)
    finally:
        os.chdir(original_cwd)
        sys.path[:] = original_sys_path
        sys.modules.update(removed_modules)
