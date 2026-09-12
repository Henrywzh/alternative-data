from __future__ import annotations

import os
from pathlib import Path

EIA_BASE_URL = "https://api.eia.gov/v2"
EIA_BULK_EBA_URL = "https://www.eia.gov/opendata/bulk/EBA.zip"
# EIA's EBA bulk/API respondent code for ERCOT is ``ERCO``.  Keep the source
# code here rather than inventing a display alias; downstream labels can map
# ERCO -> ERCOT when needed.
DEFAULT_RESPONDENTS = ["PJM", "ERCO", "CISO", "NYIS", "MISO"]
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


def resolve_api_key(base_dir: Path | None = None) -> str | None:
    env_value = os.environ.get("EIA_API_KEY", "").strip()
    if env_value:
        return env_value
    if base_dir:
        env_path = base_dir / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("EIA_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return None
