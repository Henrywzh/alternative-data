"""Runtime fetch of committed datasets from GitHub.

On Streamlit Community Cloud the app runs against a git checkout that is frozen
at the last deploy/reboot, so daily data pushed by GitHub Actions never reaches
the running container's disk until a manual reboot. To avoid that, the dashboard
reads dataset bytes directly from ``raw.githubusercontent.com`` keyed by the
latest data commit SHA, and falls back to the local checkout on any failure
(local dev / offline / private-network).

All network access is cached via ``st.cache_data`` so steady-state reads are
served from memory; bytes are keyed by the immutable commit SHA so a given SHA
always maps to correct content.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import requests
import streamlit as st

# Repo coordinates. Overridable via st.secrets / env for forks or branch testing.
DEFAULT_REPO_SLUG = "Henrywzh/alternative-data"
DEFAULT_DATA_BRANCH = "main"
DATA_PATH_PREFIX = "data/normalized"

_API_BASE = "https://api.github.com"
_RAW_BASE = "https://raw.githubusercontent.com"
_TIMEOUT = 30

# Shared session for HTTP keep-alive across the several files fetched per section.
_SESSION = requests.Session()


def _secret(name: str, default: str | None = None) -> str | None:
    """Read a value from st.secrets, falling back to the environment."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        # st.secrets raises if no secrets.toml exists; env is the fallback.
        pass
    return os.environ.get(name, default)


def repo_slug() -> str:
    return _secret("DATA_REPO_SLUG", DEFAULT_REPO_SLUG) or DEFAULT_REPO_SLUG


def data_branch() -> str:
    return _secret("DATA_BRANCH", DEFAULT_DATA_BRANCH) or DEFAULT_DATA_BRANCH


def remote_enabled() -> bool:
    """Remote fetch is on unless explicitly disabled via DATA_SOURCE=local."""
    return (_secret("DATA_SOURCE", "remote") or "remote").strip().lower() != "local"


def _auth_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    token = _secret("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


@st.cache_data(ttl=300, show_spinner=False, max_entries=24)
def _latest_data_sha_cached(path_prefix: str) -> str | None:
    """Latest commit SHA touching one data domain, or None on failure.

    A domain-specific path prevents an unrelated workflow push from duplicating
    heavy cached DataFrames. Returns None on any error, which makes callers fall
    back to the local checkout.
    """
    url = f"{_API_BASE}/repos/{repo_slug()}/commits"
    params = {"sha": data_branch(), "path": path_prefix, "per_page": 1}
    try:
        resp = _SESSION.get(url, params=params, headers=_auth_headers(), timeout=_TIMEOUT)
        resp.raise_for_status()
        commits = resp.json()
        if commits:
            return str(commits[0]["sha"])
    except Exception:
        return None
    return None


def latest_data_sha(path_prefix: str = DATA_PATH_PREFIX) -> str | None:
    """Return the latest data SHA without letting cache failures stop the app.

    Streamlit's cache wrapper executes outside the network error handling in
    ``_latest_data_sha_cached``.  If the cache layer itself raises (for example
    while hashing or materializing a value), treat it like any other remote
    lookup failure and let callers use the committed local checkout.
    """
    try:
        return _latest_data_sha_cached(path_prefix)
    except Exception:
        return None


@st.cache_data(ttl=1800, show_spinner=False, max_entries=24)
def _fetch_bytes_cached(rel_path: str, sha: str) -> bytes | None:
    """Fetch a repo file at a pinned commit SHA, or None if not found/unreachable.

    Keyed by the immutable SHA, so cached content is always correct for that SHA.
    A 404 (e.g. a not-yet-committed dataset) returns None rather than raising,
    letting the caller fall back to local / CSV.
    """
    url = f"{_RAW_BASE}/{repo_slug()}/{sha}/{rel_path}"
    try:
        resp = _SESSION.get(url, headers=_auth_headers(), timeout=_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content
    except Exception:
        return None


def fetch_bytes(rel_path: str, sha: str) -> bytes | None:
    """Fetch remote bytes, falling back cleanly if Streamlit caching fails."""
    try:
        return _fetch_bytes_cached(rel_path, sha)
    except Exception:
        return None


# GitHub's contents API returns at most 1000 entries for a directory and gives
# no truncation flag, so a larger directory would come back looking complete
# while silently missing files.  Refuse to assemble a dataset from a listing
# that could be truncated and fall back to the local checkout instead.
_MAX_DIRECTORY_ENTRIES = 1000


@st.cache_data(ttl=1800, show_spinner=False, max_entries=8)
def _fetch_directory_cached(rel_dir: str, sha: str, suffix: str) -> tuple[bytes, ...] | None:
    """Fetch every ``suffix`` file in one repo directory at a pinned commit SHA.

    Partitioned datasets are stored as a directory of per-date files rather than
    a single blob, so reading one means listing the directory and fetching each
    part.  Returns the payloads in sorted-name order, or None if the directory
    is missing, unreachable, or only partially retrievable.

    Cached as one entry per directory rather than one per file: a dataset with a
    hundred-odd partitions would otherwise evict every other dataset out of the
    per-file byte cache on each load.
    """
    listing_url = f"{_API_BASE}/repos/{repo_slug()}/contents/{rel_dir}"
    try:
        resp = _SESSION.get(
            listing_url, params={"ref": sha}, headers=_auth_headers(), timeout=_TIMEOUT
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        entries = resp.json()
    except Exception:
        return None
    if not isinstance(entries, list) or len(entries) >= _MAX_DIRECTORY_ENTRIES:
        return None

    names = sorted(
        str(entry["name"])
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("type") == "file"
        and str(entry.get("name", "")).endswith(suffix)
    )
    if not names:
        return None

    def _fetch_one(name: str) -> bytes | None:
        url = f"{_RAW_BASE}/{repo_slug()}/{sha}/{rel_dir}/{name}"
        try:
            resp = _SESSION.get(url, headers=_auth_headers(), timeout=_TIMEOUT)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.content
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=min(8, len(names))) as executor:
        payloads = list(executor.map(_fetch_one, names))

    # A partially fetched directory is a wrong dataset, not a smaller one: one
    # missing partition silently drops a day of history with no error anywhere.
    # Treat it as a miss so the caller uses the local checkout instead.
    if any(payload is None for payload in payloads):
        return None
    return tuple(payloads)


def fetch_directory(rel_dir: str, sha: str, suffix: str = ".parquet") -> tuple[bytes, ...] | None:
    """Fetch a remote directory's files, falling back cleanly if caching fails."""
    try:
        return _fetch_directory_cached(rel_dir, sha, suffix)
    except Exception:
        return None
