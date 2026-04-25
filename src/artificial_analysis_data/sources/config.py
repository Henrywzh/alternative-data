from __future__ import annotations

import os
from pathlib import Path


API_KEY_ENV_VAR = "ARTIFICIAL_ANALYSIS_API_KEY"


def resolve_api_key(base_dir: Path) -> str:
    env_value = os.environ.get(API_KEY_ENV_VAR, "").strip()
    if env_value:
        return env_value

    config_path = base_dir / ".config"
    if config_path.exists():
        for line in config_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() != API_KEY_ENV_VAR:
                continue
            return value.strip().strip("'").strip('"')

    raise ValueError("Missing ARTIFICIAL_ANALYSIS_API_KEY in environment or repository .config")
