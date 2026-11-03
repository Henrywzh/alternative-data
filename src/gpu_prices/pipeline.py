"""Fetch source-specific GPU price snapshots for the AI data dashboard.

Each source is validated and written separately to
data/normalized/gpu_price_history/<source>.parquet. Failed fetches leave the
last successful table intact; raw bodies are retained by content hash.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

SOURCES = {
    "getdeploying": "https://getdeploying.com/dataset/gpu-prices/weekly.csv",
    "github_history": "https://raw.githubusercontent.com/rahilmittal1/gpu-price-history/main/data/rent/rent_index_monthly.csv",
    "compute_screener": "https://computescreener.com/data/series.json",
}
KEYS = {
    "getdeploying": ["gpu_slug", "date", "billing_type", "reservation_months"],
    "github_history": ["month", "gpu", "form_factor", "segment"],
    "compute_screener": ["gpu", "date"],
}
MIN_ROWS = {"getdeploying": 1000, "github_history": 100, "compute_screener": 100}
GET_COLUMNS = ["gpu_slug", "date", "billing_type", "reservation_months", "min_price", "max_price", "median_price", "provider_median_price", "provider_count", "offering_count"]
GITHUB_COLUMNS = ["month", "gpu", "form_factor", "segment", "median_usd_per_gpu_hour", "mean_usd_per_gpu_hour", "min_usd_per_gpu_hour", "min_provider", "max_usd_per_gpu_hour", "n_providers", "providers", "chain_log_index", "chain_link", "n_providers_in_link", "chain_index_2023_11_eq_100", "chain_index_first_month_eq_100"]


def _required(frame: pd.DataFrame, fields: list[str], source: str) -> None:
    missing = set(fields) - set(frame.columns)
    if missing:
        raise ValueError(f"{source}: missing columns: {', '.join(sorted(missing))}")
    if frame.empty:
        raise ValueError(f"{source}: empty dataset")


def _valid_key(frame: pd.DataFrame, source: str, optional: set[str] = frozenset()) -> None:
    keys = KEYS[source]
    for key in keys:
        if key not in optional:
            if frame[key].isna().any() or frame[key].astype("string").str.strip().eq("").any():
                raise ValueError(f"{source}: missing key {key}")
    if frame.duplicated(keys).any():
        raise ValueError(f"{source}: duplicate natural keys")


def _numeric(frame: pd.DataFrame, columns: list[str], source: str) -> None:
    for name in columns:
        original = frame[name]
        values = pd.to_numeric(original, errors="coerce")
        if (original.notna() & values.isna()).any() or (values.dropna() < 0).any():
            raise ValueError(f"{source}: invalid or negative {name}")
        if values.dropna().isin([float('inf'), float('-inf')]).any():
            raise ValueError(f"{source}: non-finite {name}")
        frame[name] = values


def _dates(frame: pd.DataFrame, field: str, fmt: str, source: str) -> None:
    parsed = pd.to_datetime(frame[field], format=fmt, errors="coerce")
    if parsed.isna().any():
        raise ValueError(f"{source}: invalid observation date")
    if (parsed > pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()).any():
        raise ValueError(f"{source}: future observation date")


def parse_getdeploying(content: bytes) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(content), dtype={"gpu_slug": "string", "date": "string", "billing_type": "string"})
    _required(frame, GET_COLUMNS, "getdeploying")
    frame = frame[GET_COLUMNS].copy()
    _valid_key(frame, "getdeploying", {"reservation_months"})
    _dates(frame, "date", "%Y-%m-%d", "getdeploying")
    dates = pd.to_datetime(frame["date"])
    if dates.dt.weekday.ne(0).any():
        raise ValueError("getdeploying: week must start on Monday")
    _numeric(frame, ["reservation_months", "min_price", "max_price", "median_price", "provider_median_price", "provider_count", "offering_count"], "getdeploying")
    if frame["provider_median_price"].notna().sum() == 0:
        raise ValueError("getdeploying: no provider-median prices")
    return frame


def parse_github(content: bytes) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(content), dtype={"month": "string", "gpu": "string", "form_factor": "string", "segment": "string"})
    _required(frame, GITHUB_COLUMNS, "github_history")
    frame = frame[GITHUB_COLUMNS].copy()
    _valid_key(frame, "github_history")
    _dates(frame, "month", "%Y-%m", "github_history")
    _numeric(frame, ["median_usd_per_gpu_hour", "mean_usd_per_gpu_hour", "min_usd_per_gpu_hour", "max_usd_per_gpu_hour", "n_providers", "n_providers_in_link", "chain_index_2023_11_eq_100", "chain_index_first_month_eq_100"], "github_history")
    if frame["median_usd_per_gpu_hour"].notna().sum() == 0:
        raise ValueError("github_history: no median prices")
    return frame


def parse_screener(content: bytes) -> pd.DataFrame:
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("compute_screener: expected per-GPU object")
    rows = []
    for gpu, series in payload.items():
        if not isinstance(series, list):
            raise ValueError(f"compute_screener: {gpu} is not a list")
        for item in series:
            if not isinstance(item, dict) or "d" not in item or "v" not in item:
                raise ValueError(f"compute_screener: invalid observation for {gpu}")
            if "w" in item and item["w"] not in (0, 1, True, False):
                raise ValueError(f"compute_screener: invalid weekly flag for {gpu}")
            rows.append({"gpu": gpu, "date": item["d"], "price_usd_per_hour": item["v"],
                         "providers": item.get("p"), "final": item.get("final"),
                         "weekly": bool(item.get("w", False)), "restated": item.get("restated")})
    frame = pd.DataFrame(rows)
    _required(frame, ["gpu", "date", "price_usd_per_hour", "providers", "final", "weekly", "restated"], "compute_screener")
    _valid_key(frame, "compute_screener")
    _dates(frame, "date", "%Y-%m-%d", "compute_screener")
    _numeric(frame, ["price_usd_per_hour", "providers"], "compute_screener")
    if frame["price_usd_per_hour"].notna().sum() == 0:
        raise ValueError("compute_screener: no published prices")
    for field in ("final", "restated"):
        if not frame[field].dropna().map(lambda value: isinstance(value, bool)).all():
            raise ValueError(f"compute_screener: invalid {field} flag")
    return frame


PARSERS = {"getdeploying": parse_getdeploying, "github_history": parse_github, "compute_screener": parse_screener}


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    temp = path.with_suffix(".tmp.parquet")
    frame.to_parquet(temp, index=False)
    os.replace(temp, path)


def refresh(base_dir: Path, timeout: int = 45, session: requests.Session | None = None) -> dict[str, Any]:
    """Update the normalized tables and return source-level success/failure details."""
    root = base_dir / "data" / "normalized" / "gpu_price_history"
    raw_root = base_dir / "data" / "raw" / "gpu_price_history"
    root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    when = datetime.now(timezone.utc).isoformat()
    run: dict[str, Any] = {"started_at_utc": when, "sources": {}}
    client = session or requests.Session()
    for source, url in SOURCES.items():
        try:
            response = client.get(url, timeout=timeout, headers={"User-Agent": "alternative-data-dashboard/1.0"})
            response.raise_for_status()
            body = response.content
            digest = hashlib.sha256(body).hexdigest()
            incoming = PARSERS[source](body)
            if len(incoming) < MIN_ROWS[source]:
                raise ValueError(f"{source}: only {len(incoming)} rows; expected at least {MIN_ROWS[source]}")
            incoming["captured_at_utc"] = when
            incoming["source_sha256"] = digest
            target = root / f"{source}.parquet"
            date_col = "month" if source == "github_history" else "date"
            legacy = root / f"{source}.csv"
            prior = (pd.read_parquet(target) if target.exists() else
                     pd.read_csv(legacy, dtype={"date": "string", "month": "string"}) if legacy.exists() else pd.DataFrame())
            if not prior.empty and incoming[date_col].max() < prior[date_col].max():
                raise ValueError(f"{source}: newest observation regressed from {prior[date_col].max()} to {incoming[date_col].max()}")
            if source != "getdeploying" and len(prior) >= MIN_ROWS[source] and len(incoming) < len(prior) * 0.5:
                raise ValueError(f"{source}: incoming row count fell by over 50%")
            # The weekly download is a rolling year. Retain weeks that fall out
            # of the source window while allowing later captures to revise rows.
            if source == "getdeploying" and not prior.empty:
                incoming = pd.concat([prior, incoming], ignore_index=True).drop_duplicates(KEYS[source], keep="last")
            raw_path = raw_root / f"{source}-{digest}.bin"
            if not raw_path.exists():
                raw_path.write_bytes(body)
            _atomic_parquet(incoming, target)
            run["sources"][source] = {"status": "ok", "rows": len(incoming), "observed_from": str(incoming[date_col].min()),
                                      "observed_through": str(incoming[date_col].max()), "sha256": digest, "url": url}
        except (requests.RequestException, ValueError, KeyError, TypeError, OSError) as exc:
            run["sources"][source] = {"status": "failed", "error": str(exc), "url": url,
                                      "previous_data_available": (root / f"{source}.parquet").exists()}
    temp = root / "latest_run.tmp.json"
    temp.write_text(json.dumps(run, indent=2), encoding="utf-8")
    os.replace(temp, root / "latest_run.json")
    return run
