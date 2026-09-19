from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from event_consensus.storage import save_artifact


NOW = datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc)


def _event(
    event_id: str,
    *,
    country: str,
    title: str,
    scheduled_at_utc: str,
    importance: int,
    risk_score: float,
    event_family: str = "cpi",
    actual: float | None = None,
) -> dict:
    return {
        "event_id": event_id,
        "provider": "tradingview",
        "provider_event_id": event_id.split(":", 1)[-1],
        "source_name": "TradingView economic calendar",
        "source_url": "https://example.test/calendar",
        "country": country,
        "currency": "USD" if country == "US" else "CNY",
        "title": title,
        "indicator": title,
        "event_family": event_family,
        "scheduled_at_utc": scheduled_at_utc,
        "provider_published_at": None,
        "first_observed_at_utc": "2026-09-16T00:00:00Z",
        "retrieved_at_utc": "2026-09-16T00:00:00Z",
        "trigger_type": "scheduled",
        "snapshot_stage": "t_minus_1d",
        "importance": importance,
        "risk_score": risk_score,
        "risk_importance": 15.0 if importance == 1 else 30.0,
        "risk_proximity": 20.0,
        "risk_consensus": 10.0,
        "risk_forecast_gap": 0.0,
        "risk_actual_surprise": 0.0,
        "risk_watchlist": 0.0,
        "forecast": 3.0,
        "forecast_raw": "3.0",
        "previous": 2.8,
        "previous_raw": "2.8",
        "revised_previous": None,
        "actual": actual,
        "actual_raw": None if actual is None else str(actual),
        "surprise": None if actual is None else actual - 3.0,
        "unit": None,
        "verification_status": "third_party_consensus" if actual is None else "official_cross_check",
        "payload_checksum": f"checksum-{event_id}",
    }


def write_artifact(tmp_path: Path) -> Path:
    path = tmp_path / "events_consensus_latest.json"
    save_artifact(
        {
            "schema_version": "1.0",
            "status": "ready",
            "generated_at_utc": "2026-09-16T00:00:00Z",
            "events": [
                _event(
                    "tradingview:importance-one",
                    country="US",
                    title="US CPI",
                    scheduled_at_utc="2026-09-17T12:30:00Z",
                    importance=1,
                    risk_score=20.0,
                ),
                _event(
                    "tradingview:normal",
                    country="CN",
                    title="China Retail Sales",
                    scheduled_at_utc="2026-09-18T02:00:00Z",
                    importance=0,
                    risk_score=80.0,
                ),
                _event(
                    "tradingview:released",
                    country="US",
                    title="Released US CPI",
                    scheduled_at_utc="2026-09-16T12:30:00Z",
                    importance=1,
                    risk_score=70.0,
                    actual=3.2,
                ),
            ],
            "consensus_history": [
                {
                    "event_id": "tradingview:importance-one",
                    "forecast": 2.9,
                    "previous": 2.7,
                    "actual": None,
                    "retrieved_at_utc": "2026-09-15T00:00:00Z",
                    "snapshot_stage": "t_minus_5d",
                    "trigger_type": "scheduled",
                    "verification_status": "third_party_consensus",
                },
                {
                    "event_id": "tradingview:importance-one",
                    "forecast": 3.0,
                    "previous": 2.8,
                    "actual": None,
                    "retrieved_at_utc": "2026-09-16T00:00:00Z",
                    "snapshot_stage": "t_minus_1d",
                    "trigger_type": "scheduled",
                    "verification_status": "third_party_consensus",
                },
            ],
            "quotes": [
                {
                    "provider": "finnhub",
                    "symbol": "SPY",
                    "label": "S&P 500",
                    "asset_class": "US equity",
                    "current": 500.0,
                    "percent_change": 0.5,
                    "market_timestamp_utc": "2026-09-16T23:59:00Z",
                }
            ],
            "official_components": [
                {
                    "source_id": "official_bls",
                    "series_id": "CUSR0000SA0",
                    "event_family": "cpi",
                    "component_id": "headline",
                    "reference_period": "2026-08",
                    "latest_value": 100.0,
                    "verification_status": "official",
                }
            ],
            "component_contracts": [
                {
                    "event_family": "cpi",
                    "component_id": "headline",
                    "label_en": "Headline CPI",
                    "label_zh": "整体 CPI",
                }
            ],
            "scenario_templates": {
                "cpi": [
                    {
                        "scenario": "hot",
                        "label_en": "Broad upside surprise",
                        "label_zh": "广泛上行意外",
                        "invalidation_en": "Energy-only move",
                        "invalidation_zh": "仅能源上升",
                    }
                ]
            },
            "source_health": [
                {
                    "source_id": "tradingview_calendar",
                    "status": "Healthy",
                    "records": 3,
                },
                {
                    "source_id": "official_bls",
                    "status": "Ready",
                    "records": 1,
                },
            ],
        },
        path=path,
    )
    return path


def write_event_ledger(tmp_path: Path) -> Path:
    path = tmp_path / "event_snapshots.parquet"
    pd.DataFrame(
        [
            {
                "event_id": "tradingview:importance-one",
                "snapshot_id": "old",
                "observation_signature": "old-signature",
                "trigger_type": "scheduled",
                "snapshot_stage": "t_minus_5d",
                "scheduled_at_utc": "2026-09-17T12:30:00Z",
                "retrieved_at_utc": "2026-09-12T00:00:00Z",
                "forecast": 2.8,
                "previous": 2.7,
                "actual": None,
            },
            {
                "event_id": "tradingview:importance-one",
                "snapshot_id": "new",
                "observation_signature": "new-signature",
                "trigger_type": "manual",
                "snapshot_stage": "t_minus_1d",
                "scheduled_at_utc": "2026-09-17T12:30:00Z",
                "retrieved_at_utc": "2026-09-16T00:00:00Z",
                "forecast": 3.0,
                "previous": 2.8,
                "actual": None,
            },
        ]
    ).to_parquet(path, index=False)
    return path


def fake_pipeline_result(**_kwargs) -> dict:
    return {
        "artifact": {
            "status": "ready",
            "generated_at_utc": "2026-09-16T00:00:00Z",
            "events": [{"event_id": "fake:event"}],
            "quotes": [],
            "source_health": [],
        },
        "artifact_path": "fake/latest.json",
        "used_previous_artifact": False,
    }


@pytest.fixture
def artifact_path(tmp_path: Path) -> Path:
    return write_artifact(tmp_path)


@pytest.fixture
def event_ledger_path(tmp_path: Path) -> Path:
    return write_event_ledger(tmp_path)
