"""Wiring tests for the Asia Markets sector roster.

These do not test data correctness -- they test that the pieces are *connected*:
that a sector added under src/ reaches a dashboard page, that the roster in
apps/asia-markets-dashboard/sectors.json matches what is actually on disk, and
that the build scripts have not re-grown their own private copies of the
sector list.

They exist because the historical failure mode in this repo is silence: a new
data module lands, the dashboard is never updated, and nothing fails. Every
allowlist below is deliberately noisy -- it must carry a reason and an expiry
so "not wired yet" stays a decision instead of decaying into an oversight.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "asia-markets-dashboard"
SCRIPTS = APP / "scripts"
ROSTER = json.loads((APP / "sectors.json").read_text(encoding="utf-8"))
LIVE = ROSTER["live"]
PLANNED = ROSTER["planned"]

# Build scripts that must stay free of per-sector wiring literals; the roster is
# the only place allowed to know which sectors exist.
BUILD_SCRIPTS = (
    "run-artifact-builders.mjs",
    "build-static-hub.mjs",
    "package-dashboard.mjs",
)

# src/hk_* packages that intentionally do not back a published sector yet.
# Format: package -> (reason, expiry). The test fails once the expiry passes,
# so a snoozed entry resurfaces instead of becoming permanent.
UNPUBLISHED_PACKAGES: dict[str, tuple[str, str]] = {
}

# Builder scripts that exist on disk but are not yet rostered in sectors.json.
# Format: script_filename -> (reason, expiry). Same contract as UNPUBLISHED_PACKAGES.
UNROSTERED_BUILDERS: dict[str, tuple[str, str]] = {}

# Source modules that exist but are deliberately not wired into their sector's
# pipeline yet. Format: "package/module" -> (reason, expiry).
UNWIRED_SOURCE_MODULES: dict[str, tuple[str, str]] = {}


def _strip_js_line_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))


def _check_not_expired(allowlist: dict[str, tuple[str, str]], label: str) -> None:
    today = dt.date.today()
    expired = {
        key: reason
        for key, (reason, expiry) in allowlist.items()
        if dt.date.fromisoformat(expiry) < today
    }
    assert not expired, (
        f"{label} allowlist entries are past their expiry and must be wired up or "
        f"consciously re-dated: {expired}"
    )


@pytest.mark.parametrize("sector", LIVE, ids=[s["id"] for s in LIVE])
def test_live_sector_files_exist(sector: dict) -> None:
    """Every rostered sector points at a builder, a status file and an artifact."""
    assert (APP / sector["builder"]).is_file(), f"missing builder for {sector['id']}"
    assert (APP / "src" / "data" / sector["statusFile"]).is_file(), (
        f"missing status file for {sector['id']}"
    )
    assert (APP / ".generated" / f"{sector['id']}-artifact.json").is_file(), (
        f"missing artifact for {sector['id']}"
    )
    assert (ROOT / "src" / sector["package"]).is_dir(), (
        f"missing src package for {sector['id']}"
    )


def test_every_builder_script_is_rostered() -> None:
    """A builder on disk that no sector claims would never run."""
    _check_not_expired(UNROSTERED_BUILDERS, "UNROSTERED_BUILDERS")
    on_disk = {p.name for p in SCRIPTS.glob("build_hk_*_artifact.py")}
    rostered = {Path(s["builder"]).name for s in LIVE}
    # Exclude intentionally unrostered builders (pending real-data verification).
    truly_unrostered = (on_disk - rostered) - set(UNROSTERED_BUILDERS)
    assert not truly_unrostered, (
        "builder scripts and sectors.json disagree; "
        f"unrostered={sorted(truly_unrostered)} missing={sorted(rostered - on_disk)}"
    )


def test_every_hk_package_reaches_a_sector() -> None:
    """An src/hk_* package that no sector consumes is invisible to every surface.

    This is the check for "added new data, forgot to add it to the dashboard".
    """
    _check_not_expired(UNPUBLISHED_PACKAGES, "UNPUBLISHED_PACKAGES")
    on_disk = {p.name for p in (ROOT / "src").glob("hk_*") if p.is_dir()}
    rostered = {s["package"] for s in LIVE}
    unreached = on_disk - rostered - set(UNPUBLISHED_PACKAGES)
    assert not unreached, (
        f"src packages produce data that no dashboard sector consumes: {sorted(unreached)}. "
        "Add them to sectors.json, or to UNPUBLISHED_PACKAGES with a reason and expiry."
    )


@pytest.mark.parametrize("sector", LIVE, ids=[s["id"] for s in LIVE])
def test_source_modules_are_wired_into_their_sector(sector: dict) -> None:
    """Every src/hk_*/sources/*.py is referenced by its package or its builder.

    Sectors do not share an input layer -- hk_telecom fetches live inside the
    builder, hk_transport reads data/processed/, others read data/normalized/ --
    so this checks reachability by reference rather than by output file.
    """
    _check_not_expired(UNWIRED_SOURCE_MODULES, "UNWIRED_SOURCE_MODULES")
    package = ROOT / "src" / sector["package"]
    sources_dir = package / "sources"
    if not sources_dir.is_dir():
        pytest.skip(f"{sector['package']} has no sources/ directory")

    consumers = [p for p in package.rglob("*.py") if "__pycache__" not in p.parts]
    consumers.append(APP / sector["builder"])
    blob = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in consumers)

    orphans = []
    for module in sorted(sources_dir.glob("*.py")):
        stem = module.stem
        if stem.startswith("_"):
            continue  # shared helpers, referenced by relative import spelling
        if f"{sector['package']}/{stem}" in UNWIRED_SOURCE_MODULES:
            continue
        # Ignore the module's own file path when searching for references.
        haystack = blob.replace(f"sources/{stem}.py", "")
        if not re.search(rf"\b{re.escape(stem)}\b", haystack):
            orphans.append(stem)

    assert not orphans, (
        f"{sector['package']} source modules are never referenced by the pipeline or "
        f"the artifact builder: {orphans}. Wire them in, or add "
        f"'{sector['package']}/<module>' to UNWIRED_SOURCE_MODULES with a reason and expiry."
    )


@pytest.mark.parametrize("sector", PLANNED, ids=[s["code"] for s in PLANNED])
def test_planned_sector_evidence_exists(sector: dict) -> None:
    """The hub claims research is done; the doc backing that claim must exist."""
    evidence = ROOT / sector["evidence"]
    assert evidence.is_file(), (
        f"planned sector {sector['code']} ({sector['nameEn']}) cites {sector['evidence']}, "
        "which is not in the repo -- the hub is advertising research that was moved or deleted."
    )


def test_every_live_sector_has_a_zh_dictionary() -> None:
    """A rostered sector with no ZH dictionary would ship an English-only ZH page."""
    text = (SCRIPTS / "package-dashboard.mjs").read_text(encoding="utf-8")
    block = re.search(r"const ZH_DICTIONARIES = \{(.*?)\n\};", text, re.S)
    assert block, "ZH_DICTIONARIES table not found in package-dashboard.mjs"
    mapped = set(re.findall(r'"([^"]+)":', block.group(1)))
    missing = {s["id"] for s in LIVE} - mapped
    assert not missing, f"sectors with no ZH dictionary: {sorted(missing)}"


@pytest.mark.parametrize("script", BUILD_SCRIPTS)
def test_build_scripts_carry_no_sector_wiring_literals(script: str) -> None:
    """Guard against a build script re-growing its own copy of the sector list.

    The five duplicated lists this consolidated were each individually
    reasonable; the drift came from there being five of them.
    """
    text = _strip_js_line_comments((SCRIPTS / script).read_text(encoding="utf-8"))
    offenders = {
        pattern
        for pattern in ("dashboard-status", "build_hk_", ".generated/hk-", "attachment_filename")
        if pattern in text
    }
    assert not offenders, (
        f"{script} hardcodes sector wiring {sorted(offenders)}; derive it from sectors.mjs instead."
    )


@pytest.mark.parametrize("sector", LIVE, ids=[s["id"] for s in LIVE])
def test_status_live_source_count_is_consistent(sector: dict) -> None:
    """live_sources feeds the hub's headline total, so it must be sane.

    Only bounds are asserted: the six builders each compute live_sources by
    their own rule (hk-real-estate reports 5 of 9 Measure rows, hk-telecom
    counts a Context row), so a stricter invariant would encode a convention
    that does not actually exist yet.
    """
    status = json.loads((APP / "src" / "data" / sector["statusFile"]).read_text(encoding="utf-8"))
    rows = status["sources"]
    assert rows, f"{sector['id']} status lists no sources at all"
    assert 1 <= status["live_sources"] <= len(rows), (
        f"{sector['id']} live_sources={status['live_sources']} is outside 1..{len(rows)}"
    )
    assert status["attachment_filename"].startswith(sector["id"]), (
        f"{sector['id']} attachment_filename {status['attachment_filename']!r} does not "
        "start with the sector id, which the export-link derivation assumes."
    )
