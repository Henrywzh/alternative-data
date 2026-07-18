from __future__ import annotations

import os
from pathlib import Path

USER_AGENT_ENV_VAR = "SEC_EDGAR_USER_AGENT"

# SEC EDGAR requires a User-Agent identifying the requester and a contact
# point (https://www.sec.gov/os/webmaster-faq#developers). This default is
# used when no override is configured; set SEC_EDGAR_USER_AGENT in .config
# or the environment to a "<app name>/<version> <your-email>" string for
# compliance. Note: SEC's bot-detection rejects any User-Agent containing a
# URL (e.g. a github.com link) even alongside a valid email — keep it to a
# plain "name email" shape.
DEFAULT_USER_AGENT = "alternative-data-dashboard/0.1 research@example.com"


def resolve_user_agent(base_dir: Path) -> str:
    env_value = os.environ.get(USER_AGENT_ENV_VAR, "").strip()
    if env_value:
        return env_value

    config_path = base_dir / ".config"
    if config_path.exists():
        for line in config_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() != USER_AGENT_ENV_VAR:
                continue
            return value.strip().strip("'").strip('"')

    return DEFAULT_USER_AGENT
