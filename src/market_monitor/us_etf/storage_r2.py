"""R2-First / Git-Never storage client with graceful local cache fallback.

Environment variables / .config keys:
- R2_BUCKET (e.g. 'quant-market-data')
- R2_ACCOUNT_ID
- R2_ACCESS_KEY_ID
- R2_SECRET_ACCESS_KEY
- R2_PUBLIC_URL (e.g. 'https://data.mydomain.com')
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import REPO_ROOT

logger = logging.getLogger(__name__)

# Local cache directory ignored by Git (.gitignore has data/*)
LOCAL_CACHE_DIR = REPO_ROOT / "data" / "cache" / "us_etf"


# .config holds credentials for several unrelated services (FRED, Groq, Gmail).
# Only these keys ever leave this function: a config reader that returns the
# whole file hands every caller -- including the Streamlit process -- secrets
# it has no business holding.
R2_CONFIG_KEYS = (
    "R2_BUCKET",
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_ENDPOINT_URL",
    "R2_PUBLIC_URL",
)


def get_r2_config() -> dict[str, str]:
    """Read the Cloudflare R2 settings, and only those, from .config or env."""
    values: dict[str, str] = {}
    config_path = REPO_ROOT / ".config"
    if config_path.exists():
        for line in config_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if key not in R2_CONFIG_KEYS:
                continue
            values[key] = value.strip().strip('"').strip("'")

    for env_key in R2_CONFIG_KEYS:
        if os.environ.get(env_key):
            values[env_key] = os.environ[env_key]

    return values


def upload_json_to_r2(key: str, data: dict[str, Any] | list[Any]) -> str:
    """Upload a JSON artifact to R2. Returns the outcome, not just success.

    In an R2-first design the upload silently never happening is the failure
    that matters, and a bare False cannot tell "no credentials" apart from
    "the bucket rejected it". Returns one of ``uploaded``, ``not_configured``
    or ``failed``; the local cache is written either way.
    """
    cfg = get_r2_config()
    bucket = cfg.get("R2_BUCKET")
    account_id = cfg.get("R2_ACCOUNT_ID")
    access_key = cfg.get("R2_ACCESS_KEY_ID")
    secret_key = cfg.get("R2_SECRET_ACCESS_KEY")
    
    if not all([bucket, account_id, access_key, secret_key]):
        missing = [
            name for name, value in (
                ("R2_BUCKET", bucket), ("R2_ACCOUNT_ID", account_id),
                ("R2_ACCESS_KEY_ID", access_key), ("R2_SECRET_ACCESS_KEY", secret_key),
            ) if not value
        ]
        logger.warning(
            "R2 not configured (missing %s); wrote local cache only, nothing published.",
            ", ".join(missing),
        )
        save_local_cache_json(key, data)
        return "not_configured"
        
    try:
        import boto3
        endpoint_url = cfg.get("R2_ENDPOINT_URL") or f"https://{account_id}.r2.cloudflarestorage.com"
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
        )
        json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=json_bytes,
            ContentType="application/json",
            CacheControl="public, max-age=900",
        )
        logger.info("Successfully uploaded %s to R2 bucket %s", key, bucket)
        save_local_cache_json(key, data)
        return "uploaded"
    except Exception as exc:
        logger.error("Failed uploading %s to R2: %s", key, exc)
        save_local_cache_json(key, data)
        return "failed"


def save_local_cache_json(key: str, data: dict[str, Any] | list[Any]) -> Path:
    """Save JSON artifact to local cache directory (git-ignored)."""
    target = LOCAL_CACHE_DIR / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def local_cache_age_hours(key: str) -> float | None:
    """Age of the cached artifact in hours, or None when there is none."""
    target = LOCAL_CACHE_DIR / key
    if not target.exists():
        return None
    modified = datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - modified).total_seconds() / 3600.0


def load_local_cache_json(key: str) -> dict[str, Any] | None:
    """Read JSON artifact from local cache directory."""
    target = LOCAL_CACHE_DIR / key
    if target.exists():
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None
