from __future__ import annotations

import sys
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
