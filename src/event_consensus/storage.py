"""Append-only local ledgers and compact artifact storage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .config import (
    COMPONENT_LEDGER_PATH,
    EVENT_LEDGER_PATH,
    LATEST_ARTIFACT_PATH,
    QUOTE_LEDGER_PATH,
)
from .domain import (
    component_observation_signature,
    component_snapshot_id,
    enrich_quote_row,
)


def _concat_frames(left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
    """Concatenate while avoiding pandas' all-NA dtype deprecation warning."""
    columns = list(dict.fromkeys([*left.columns.tolist(), *right.columns.tolist()]))
    left_columns = [column for column in left.columns if left[column].notna().any()]
    right_columns = [column for column in right.columns if right[column].notna().any()]
    combined = pd.concat(
        [left[left_columns], right[right_columns]],
        ignore_index=True,
        sort=False,
    )
    for column in columns:
        if column not in combined.columns:
            combined[column] = None
    return combined[columns]


def _quote_identity(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame.copy()
    return pd.DataFrame(
        [enrich_quote_row(row) for row in frame.to_dict(orient="records")]
    )


def _component_identity(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame.copy()
    records = frame.to_dict(orient="records")
    for row in records:
        signature = row.get("observation_signature")
        if signature is None or pd.isna(signature):
            row["observation_signature"] = component_observation_signature(row)
        snapshot = row.get("snapshot_id")
        if snapshot is None or pd.isna(snapshot):
            row["snapshot_id"] = component_snapshot_id(row)
    return pd.DataFrame(records)


def _read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except (OSError, ValueError):
        return pd.DataFrame()


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def append_event_snapshots(
    incoming: pd.DataFrame,
    *,
    path: Path = EVENT_LEDGER_PATH,
) -> pd.DataFrame:
    """Append observations without collapsing changed PIT values.

    Scheduled refreshes deduplicate identical event/checkpoint/value payloads.
    Explicit manual observations remain separate because the user's action is
    itself part of the observation lineage.
    """
    existing = _read_parquet(path)
    if incoming is None or incoming.empty:
        return existing
    combined = (
        incoming.copy()
        if existing.empty
        else _concat_frames(existing, incoming)
    )
    if "snapshot_id" in combined.columns:
        combined = combined.drop_duplicates("snapshot_id", keep="first")

    required = {"trigger_type", "event_id", "observation_signature"}
    if required.issubset(combined.columns):
        manual = combined[combined["trigger_type"].astype(str).eq("manual")]
        automatic = combined[~combined["trigger_type"].astype(str).eq("manual")]
        automatic = automatic.drop_duplicates(
            ["event_id", "observation_signature"],
            keep="first",
        )
        combined = _concat_frames(automatic, manual)

    sort_columns = [
        column
        for column in ("scheduled_at_utc", "event_id", "retrieved_at_utc")
        if column in combined.columns
    ]
    if sort_columns:
        combined = combined.sort_values(sort_columns).reset_index(drop=True)
    _atomic_parquet(combined, path)
    return combined


def append_quote_snapshots(
    incoming: pd.DataFrame,
    *,
    path: Path = QUOTE_LEDGER_PATH,
) -> pd.DataFrame:
    existing = _quote_identity(_read_parquet(path))
    if incoming is None or incoming.empty:
        return existing
    incoming = _quote_identity(incoming)
    combined = (
        incoming.copy()
        if existing.empty
        else _concat_frames(existing, incoming)
    )
    if "snapshot_id" in combined.columns:
        combined = combined.drop_duplicates("snapshot_id", keep="first")
    if {"trigger_type", "symbol", "observation_signature"}.issubset(combined.columns):
        automatic = combined[~combined["trigger_type"].astype(str).eq("manual")]
        manual = combined[combined["trigger_type"].astype(str).eq("manual")]
        automatic = automatic.drop_duplicates(
            ["symbol", "observation_signature"],
            keep="first",
        )
        combined = _concat_frames(automatic, manual)
    if "retrieved_at_utc" in combined.columns:
        combined = combined.sort_values("retrieved_at_utc").reset_index(drop=True)
    _atomic_parquet(combined, path)
    return combined


def append_component_snapshots(
    incoming: pd.DataFrame,
    *,
    path: Path = COMPONENT_LEDGER_PATH,
) -> pd.DataFrame:
    existing = _component_identity(_read_parquet(path))
    if incoming is None or incoming.empty:
        return existing
    incoming = _component_identity(incoming)
    combined = (
        incoming.copy()
        if existing.empty
        else _concat_frames(existing, incoming)
    )
    if "snapshot_id" in combined.columns:
        combined = combined.drop_duplicates("snapshot_id", keep="first")
    if {"trigger_type", "series_id", "observation_signature"}.issubset(combined.columns):
        automatic = combined[~combined["trigger_type"].astype(str).eq("manual")]
        manual = combined[combined["trigger_type"].astype(str).eq("manual")]
        automatic = automatic.drop_duplicates(
            ["source_id", "series_id", "observation_signature"],
            keep="first",
        )
        combined = _concat_frames(automatic, manual)
    if "retrieved_at_utc" in combined.columns:
        combined = combined.sort_values("retrieved_at_utc").reset_index(drop=True)
    _atomic_parquet(combined, path)
    return combined


def load_event_ledger(path: Path = EVENT_LEDGER_PATH) -> pd.DataFrame:
    return _read_parquet(path)


def load_quote_ledger(path: Path = QUOTE_LEDGER_PATH) -> pd.DataFrame:
    return _read_parquet(path)


def load_component_ledger(path: Path = COMPONENT_LEDGER_PATH) -> pd.DataFrame:
    return _read_parquet(path)


def semantic_hash(artifact: dict[str, Any]) -> str:
    """Hash decision-relevant values while excluding transport timestamps."""
    compact = {
        "events": [
            {
                key: row.get(key)
                for key in (
                    "event_id",
                    "scheduled_at_utc",
                    "forecast",
                    "previous",
                    "actual",
                    "unit",
                    "risk_score",
                    "verification_status",
                )
            }
            for row in artifact.get("events", [])
        ],
        "quotes": [
            {
                key: row.get(key)
                for key in ("symbol", "current", "percent_change", "market_timestamp_utc")
            }
            for row in artifact.get("quotes", [])
        ],
        "health": [
            {
                key: row.get(key)
                for key in ("source_id", "status", "records")
            }
            for row in artifact.get("source_health", [])
        ],
        "component_contracts": artifact.get("component_contracts", []),
        "scenario_templates": artifact.get("scenario_templates", {}),
        "official_components": [
            {
                key: row.get(key)
                for key in (
                    "series_id",
                    "reference_period",
                    "latest_value",
                    "mom_change",
                    "mom_pct",
                    "yoy_pct",
                )
            }
            for row in artifact.get("official_components", [])
        ],
    }
    return hashlib.sha256(
        json.dumps(compact, sort_keys=True, default=str).encode()
    ).hexdigest()


def save_artifact(
    artifact: dict[str, Any],
    *,
    path: Path = LATEST_ARTIFACT_PATH,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(artifact)
    payload["content_hash"] = semantic_hash(payload)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def load_artifact(path: Path = LATEST_ARTIFACT_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("events", []), list):
        return None
    if not isinstance(payload.get("quotes", []), list):
        return None
    return payload
