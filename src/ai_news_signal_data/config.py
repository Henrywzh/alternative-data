from __future__ import annotations

import os
from pathlib import Path

_KEYS = (
    "GROQ_API_KEY",
    "CLOUDFLARE_API_KEY",
    "CLOUDFLARE_ACCOUNT_ID",
    "GMAIL_SENDER",
    "GMAIL_APP_PASSWORD",
    "GMAIL_RECIPIENT",
)


def _read_config_file(base_dir: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    config_path = base_dir / ".config"
    if config_path.exists():
        for raw in config_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return values


def load_config(base_dir: Path) -> dict[str, str]:
    file_values = _read_config_file(base_dir)
    return {key: os.environ.get(key) or file_values.get(key, "") for key in _KEYS}


def groq_api_keys(config: dict[str, str]) -> list[str]:
    # GROQ_API_KEY holds a comma-separated pool of free-tier keys so the guard
    # can rotate past a single key's rate limit rather than failing the run.
    raw = config.get("GROQ_API_KEY", "")
    return [key.strip() for key in raw.split(",") if key.strip()]
