from __future__ import annotations

import os
from pathlib import Path


KCS_TEN_DAY_URL = "https://apis.data.go.kr/1220000/prlstMmUtPrviExpAcrs/getPrlstMmUtPrviExpAcrs"
KCS_ITEM_COUNTRY_URL = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"
KRX_JSON_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KOSIS_PARAMETER_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"

KCS_SOURCE_URL = "https://www.data.go.kr/data/15157908/openapi.do"
KCS_ITEM_COUNTRY_SOURCE_URL = "https://www.data.go.kr/data/15100475/openapi.do"
KRX_SOURCE_URL = "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd?locale=en"
KOSIS_SOURCE_URL = "https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1F01501"

DEFAULT_KCS_HS_CODE = "854232"
DEFAULT_KCS_WORLD_COUNTRY_CODE = "00"
DEFAULT_KCS_TAIWAN_COUNTRY_CODE = "TW"
DEFAULT_KOSIS_ORG_ID = "101"
DEFAULT_KOSIS_TABLE_ID = "DT_1F01501"


class MissingCredentialError(ValueError):
    """Raised when a live source needs a key that is not configured."""


class SourceResponseError(RuntimeError):
    """Raised when an official endpoint returns a structured error."""


def resolve_credential(base_dir: Path, env_names: tuple[str, ...]) -> str:
    value = resolve_optional_credential(base_dir, env_names)
    if value:
        return value

    names = ", ".join(env_names)
    raise MissingCredentialError(f"Missing credential. Set one of {names} in the environment or {base_dir / '.config'}")


def resolve_optional_credential(base_dir: Path, env_names: tuple[str, ...]) -> str | None:
    for env_name in env_names:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value

    config_path = base_dir / ".config"
    if config_path.exists():
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
