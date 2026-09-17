"""Narrow credential lookup without exposing unrelated repository secrets."""

from __future__ import annotations

import os
from pathlib import Path


def _read_one(path: Path, name: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""

def resolve_credential(name: str, repo_root: Path) -> str:
    """Resolve one named value from env, local config, or canonical checkout."""
    value = os.environ.get(name, "").strip()
    if value:
        return value

    explicit = os.environ.get("EVENT_CONSENSUS_CONFIG_PATH", "").strip()
    candidates = [
        Path(explicit).expanduser() if explicit else None,
        Path(repo_root) / ".config",
        Path.home() / "Quant" / "alternative-data" / ".config",
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        value = _read_one(candidate, name)
        if value:
            return value
    return ""
