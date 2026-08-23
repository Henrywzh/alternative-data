from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

for path in (ROOT, SRC):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def require_local_normalized(*dataset_names: str) -> None:
    """Skip when a gitignored normalized dataset this test needs is absent.

    ``data/normalized/hk_real_estate/`` holds ~215 pipeline-output datasets
    (~400 MB) that the repository deliberately does not track.  Tests that read
    them therefore pass only on a machine that has generated them.  Rather than
    let CI report a data-availability gap as a code failure -- or silently pass
    -- these tests skip with the specific dataset named, so the reason is
    visible in the run output instead of inferred.
    """

    import pytest

    root = ROOT / "data" / "normalized" / "hk_real_estate"
    missing = [name for name in dataset_names if not (root / name).is_dir()]
    if missing:
        pytest.skip(
            "requires locally generated datasets not tracked by git: "
            + ", ".join(missing)
            + f" (expected under {root.relative_to(ROOT)}/)"
        )


def require_local_capture(*relative_paths: str) -> None:
    """Skip when a gitignored raw capture this test needs is absent.

    Same contract as :func:`require_local_normalized`, for captured raw inputs
    under ``data/raw/`` rather than normalized pipeline output.  Production code
    is expected to degrade gracefully when these are missing (the market-reaction
    fields simply stay blank); it is only the assertions about the *filled* case
    that need the capture on disk.
    """

    import pytest

    # A pattern containing "*" is matched as a glob: the captures are named
    # with a capture timestamp, so the test depends on one existing, not on a
    # particular one.
    missing = []
    for path in relative_paths:
        if "*" in path:
            if not list(ROOT.glob(path)):
                missing.append(path)
        elif not (ROOT / path).exists():
            missing.append(path)
    if missing:
        pytest.skip(
            "requires locally captured raw inputs not tracked by git: " + ", ".join(missing)
        )


# --- Outbound network policy ---------------------------------------------
#
# The suite used to reach live endpoints during an ordinary `pytest` run, and
# the fetches wrote fresh captures into `data/raw/**`, which is gitignored.
# Loaders pick the newest valid local capture, so the suite rewrote its own
# inputs as it ran: on 2026-08-19 a clean checkout produced three failures in
# tests that make no network calls at all, including one named
# `test_default_immigration_input_uses_local_snapshot_without_fetch`, which
# failed because a *different* test had fetched. Which tests broke depended on
# how pytest-xdist happened to distribute the run, so the same commit passed
# and failed on the same machine.
#
# Outbound connections are therefore blocked by default. Tests that genuinely
# verify a live endpoint carry `@pytest.mark.network` and are skipped unless
# `--run-network` is passed; the daily data workflows exercise those same
# endpoints for real every day, which is a better place to find out a provider
# changed than a pull request that did not touch it.

import socket


class NetworkAccessBlocked(RuntimeError):
    """Raised when a test opens a connection without @pytest.mark.network."""


_ALLOW_NETWORK = {"enabled": False}
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


def _host_of(address: object) -> str:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return str(address)


def _install_socket_guard() -> None:
    original_connect = socket.socket.connect
    if getattr(original_connect, "_guarded_by_conftest", False):
        return

    def guarded_connect(self, address):
        host = _host_of(address)
        if not _ALLOW_NETWORK["enabled"] and host not in _LOOPBACK and not host.startswith("127."):
            raise NetworkAccessBlocked(
                f"blocked outbound connection to {host}. Tests run offline: a live fetch "
                "rewrites the gitignored captures under data/raw/ that other tests read, "
                "which made the suite nondeterministic. Stub the fetch, or mark the test "
                "@pytest.mark.network and run with --run-network."
            )
        return original_connect(self, address)

    guarded_connect._guarded_by_conftest = True  # type: ignore[attr-defined]
    socket.socket.connect = guarded_connect


# --- tracked-data write guard ----------------------------------------
# Several builders write their output as a side effect of building it --
# ``build_airline_catalyst_calendar()`` ends in ``result.to_csv(OUTPUT_PATH)``
# with no way to ask for the frame alone -- so a test that only wants the
# returned DataFrame still rewrites the repository's copy. Those files carry a
# ``retrieved_at`` stamp, so the rewrite always shows as a diff even when
# nothing about the data changed, and a full run leaves ~40 tracked files
# modified. `git status` then reports work nobody did, which is actively
# dangerous when more than one session is on the same branch.
#
# tests/test_hk_transport_airline_earnings_model_v3.py already shows the fix:
#
#     monkeypatch.setattr(module, "OUTPUT_PATH", tmp_path / "output.csv")
#
# This hook does not stop the writes -- doing that centrally would break the
# tests that deliberately read their output back. It records which tracked
# files a run modified and reports them at the end, so an existing offender
# is easy to find and a new one cannot slip in unnoticed.

def _session_copy(relative: str, env_var: str) -> None:
    """Point ``env_var`` at a throwaway copy of ``relative``.

    It is a copy rather than an empty directory because these files are also
    inputs -- the builders read each other's output -- so copying keeps the
    within-session ordering behaviour identical to before; only the
    repository's copy is spared. On APFS/btrfs the clone is nearly free
    (~50 MB in ~50 ms).
    """
    if os.environ.get(env_var):
        return
    source = Path(__file__).resolve().parents[1] / relative
    if not source.is_dir():
        return
    target = Path(tempfile.mkdtemp(prefix="repo-data-")) / source.name
    try:
        subprocess.run(
            ["cp", "-c", "-R", str(source), str(target)],
            capture_output=True,
            timeout=300,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        try:
            shutil.copytree(source, target, dirs_exist_ok=True)
        except OSError:
            shutil.rmtree(target.parent, ignore_errors=True)
            return
    os.environ[env_var] = str(target)
    atexit.register(shutil.rmtree, str(target.parent), True)


def _redirect_repo_data_writes() -> None:
    """Keep builder side-effect writes out of the working tree.

    Builders under src/hk_transport/sources/ and scripts/build_asia_backtest_*
    write their output as a side effect of building it -- for example
    build_airline_catalyst_calendar() ends in result.to_csv(OUTPUT_PATH) with
    no way to ask for the frame alone -- and those path constants are frozen
    from a directory constant at import time. So a test that only wanted the
    returned DataFrame rewrote the tracked file, and since each carries a
    retrieved_at or build timestamp, a full run left ~75 tracked files
    modified. `git status` then reported work nobody did, which is actively
    dangerous when more than one session is on the same branch.

    Redirecting the directories is the only lever that reaches all of them:
    the builders chain, so patching one OUTPUT_PATH moves the problem down the
    chain. This runs in pytest_configure, before any test module is imported
    and therefore before those constants are computed.
    """
    _session_copy("data/normalized/hk_transport", "HK_TRANSPORT_NORMALIZED_DIR")
    _session_copy("data/registries", "ASIA_BACKTEST_REGISTRY_DIR")


_TRACKED_DATA_SNAPSHOT: dict[str, tuple[int, int]] = {}


def _tracked_data_files() -> list[str]:
    """Tracked paths under data/ -- git is the only authority on 'tracked'."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "data"],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [name for name in result.stdout.decode("utf-8", "replace").split("\0") if name]


def _snapshot_tracked_data() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in _tracked_data_files():
        path = root / name
        try:
            stat = path.stat()
        except OSError:
            continue
        _TRACKED_DATA_SNAPSHOT[name] = (stat.st_size, stat.st_mtime_ns)


def _modified_tracked_data() -> list[str]:
    root = Path(__file__).resolve().parents[1]
    changed = []
    for name, before in _TRACKED_DATA_SNAPSHOT.items():
        path = root / name
        try:
            stat = path.stat()
        except OSError:
            changed.append(name)
            continue
        if (stat.st_size, stat.st_mtime_ns) != before:
            changed.append(name)
    return sorted(changed)


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="run tests marked @pytest.mark.network against live endpoints (they write to data/raw/)",
    )


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        "network: reaches live external endpoints; skipped unless --run-network is passed",
    )
    _install_socket_guard()
    _redirect_repo_data_writes()
    _snapshot_tracked_data()


def pytest_collection_modifyitems(config, items) -> None:
    if config.getoption("--run-network"):
        return
    import pytest

    skip_network = pytest.mark.skip(reason="reaches live endpoints; run with --run-network")
    for item in items:
        if item.get_closest_marker("network"):
            item.add_marker(skip_network)


def pytest_runtest_setup(item) -> None:
    _ALLOW_NETWORK["enabled"] = bool(
        item.get_closest_marker("network") and item.config.getoption("--run-network")
    )


def pytest_runtest_teardown(item) -> None:
    _ALLOW_NETWORK["enabled"] = False


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    del exitstatus, config
    changed = _modified_tracked_data()
    if not changed:
        return
    terminalreporter.section("tracked data files modified by this run", red=True)
    terminalreporter.write_line(
        f"{len(changed)} tracked file(s) under data/ were rewritten by tests. "
        "This is test output, not work you did -- restore it before reading "
        "`git status`, and point the builder at tmp_path instead:"
    )
    for name in changed[:40]:
        terminalreporter.write_line(f"  {name}")
    if len(changed) > 40:
        terminalreporter.write_line(f"  ... and {len(changed) - 40} more")
    terminalreporter.write_line("  git checkout -- " + " ".join(sorted({name.split("/")[0] + "/" + name.split("/")[1] for name in changed})))
