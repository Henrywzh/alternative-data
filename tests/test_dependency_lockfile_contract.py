"""The lockfile that governs deployment must honour the declared constraints.

Streamlit Community Cloud installs from ``uv.lock`` (its build log says so, and
warns that several dependency files are present and it picked uv-sync).  CI, by
contrast, installs ``pip install -e .[dev]``, which resolves from
``pyproject.toml``.  When the lockfile drifts from the declared constraints the
two environments diverge silently: CI stays green on the version the code is
verified against while production runs a different one.

That is not hypothetical.  ``uv.lock`` recorded ``pandas >=2.2`` without the
``<3`` cap that pyproject.toml and requirements.txt both carry -- with seven
lines explaining why -- and resolved pandas 3.0.5 into the deployed container.
It also omitted scikit-learn, scipy and pypdf entirely.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
UV_LOCK = REPO_ROOT / "uv.lock"


def _declared_requirements() -> list[Requirement]:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    return [Requirement(entry) for entry in project["dependencies"]]


def _locked_versions() -> dict[str, list[Version]]:
    lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    versions: dict[str, list[Version]] = {}
    for package in lock.get("package", []):
        name = str(package["name"]).lower().replace("_", "-")
        versions.setdefault(name, []).append(Version(str(package["version"])))
    return versions


def test_uv_lock_is_present_for_the_deployment_installer() -> None:
    assert UV_LOCK.is_file(), "Streamlit Cloud installs from uv.lock; it must be committed"


@pytest.mark.parametrize("requirement", _declared_requirements(), ids=lambda r: r.name)
def test_uv_lock_satisfies_each_declared_constraint(requirement: Requirement) -> None:
    """Every dependency pyproject declares must be locked, at a allowed version."""
    locked = _locked_versions()
    name = requirement.name.lower().replace("_", "-")

    assert name in locked, (
        f"{requirement.name} is declared in pyproject.toml but absent from uv.lock, "
        "so the deployed environment does not have it. Run `uv lock`."
    )
    for version in locked[name]:
        assert requirement.specifier.contains(version, prereleases=True), (
            f"uv.lock pins {requirement.name} {version}, which violates the declared "
            f"constraint {requirement.specifier}. The deployed container installs from "
            "uv.lock while CI resolves pyproject.toml, so this drift is invisible until "
            "production behaves differently. Run `uv lock`."
        )
