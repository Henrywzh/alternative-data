from __future__ import annotations

import os
from pathlib import Path


CENSUS_IMPORTS_HS_URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
CENSUS_IMPORTS_PORTHS_URL = "https://api.census.gov/data/timeseries/intltrade/imports/porths"
CENSUS_SOURCE_URL = "https://www.census.gov/data/developers/data-sets/international-trade.html"
DEFAULT_HS_CODE = "854232"
DEFAULT_SOUTH_KOREA_CODE = "5800"
DEFAULT_START_MONTH = "2010-01"
DEFAULT_COMPARISON_COUNTRY_CODES = ("5800", "5830", "5880", "5700")


class MissingCredentialError(ValueError):
    """Raised when the Census API key is not configured."""


class SourceResponseError(RuntimeError):
    """Raised when the Census API returns a structured error."""


def resolve_optional_credential(base_dir: Path, env_names: tuple[str, ...]) -> str | None:
    """Resolve a credential without exposing its value in logs or source URLs."""
    for env_name in env_names:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value

    config_path = base_dir / ".config"
    if not config_path.exists():
        return None

    for line in config_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        if key.strip() not in env_names:
            continue
        value = raw_value.strip().strip('"').strip("'")
        if value:
            return value
    return None


def require_credential(api_key: str | None) -> str:
    value = (api_key or "").strip()
    if value:
        return value
    raise MissingCredentialError(
        "Census International Trade API requires a key. "
        "Set CENSUS_DATA_API_KEY, CENSUS_API_KEY, or US_CENSUS_API_KEY "
        "in the environment or .config."
    )
