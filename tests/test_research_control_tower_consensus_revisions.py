"""Batch 6/7 genuine consensus revisions: store accumulation + derivation tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import research_control_tower_consensus_collector as collector  # noqa: E402
from research_control_tower.build import (  # noqa: E402
    TASK3_REVISION_ARROW_SCHEMA,
    TASK3_SNAPSHOT_ARROW_SCHEMA,
)


def _snap(**overrides: object) -> dict:
    row = {
        "snapshot_id": "run-scoped-id",
        "provider": "yfinance",
        "entity_id": "TENCENT",
        "listing_id": "0700_HK",
        "financial_data_security_id": "sec-0700",
        "canonical_ticker": "0700.HK",
        "metric": "eps",
        "fiscal_period": "quarterly",
        "fiscal_year": 2027,
        "estimate_period_end": pd.Timestamp("2026-06-30").date(),
        "horizon": "0q",
        "snapshot_at": pd.Timestamp("2026-08-01T10:00:00Z"),
        "value": 3.00,
        "statistic": "mean",
        "low_value": 2.80,
        "high_value": 3.20,
        "analyst_count": 30,
        "provider_contributor_count": 30,
        "currency": "HKD",
        "unit": "currency_per_share",
        "accounting_basis": "provider_reported_non_gaap_unverified",
        "provider_asof": pd.Timestamp("2026-08-01T10:00:00Z"),
        "retrieved_at_utc": pd.Timestamp("2026-08-01T10:00:00Z"),
        "source_url": "https://finance.yahoo.com/quote/0700.HK/analysis",
        "raw_hash": "abc",
        "pit_class": "snapshot_from_live_source",
        "source_run_id": "run-1",
        "calculation_origin": "provider_published_consensus",
        "coverage_reason": "",
    }
    row.update(overrides)
    return row


def test_two_day_accumulation_derives_genuine_revision() -> None:
    day1 = _snap(snapshot_at=pd.Timestamp("2026-08-01T10:00:00Z"), value=3.00, analyst_count=30)
    day2 = _snap(snapshot_at=pd.Timestamp("2026-08-02T10:00:00Z"), value=3.15, analyst_count=32)

    store, remap = collector.accumulate_snapshots(collector._empty_store_frame(), [day1])
    store, _ = collector.accumulate_snapshots(store, [day2])

    assert len(store) == 2
    revisions = collector.derive_genuine_revisions(store)
    assert len(revisions) == 1
    rev = revisions[0]
    assert rev["pit_class"] == "repository_captured"
    assert rev["prior_value"] == 3.00
    assert rev["current_value"] == 3.15
    assert rev["revision_value"] == pytest.approx(0.15)
    assert rev["revision_pct"] == pytest.approx(5.0)
    assert rev["analyst_count_change"] == 2
    assert rev["lookback_days"] == 1
    assert rev["prior_snapshot_id"] != ""
    assert rev["snapshot_id"] != rev["prior_snapshot_id"]
    assert "run-scoped-id" in remap


def test_same_day_rerun_is_idempotent() -> None:
    first = _snap(snapshot_at=pd.Timestamp("2026-08-01T08:00:00Z"), value=3.00)
    rerun = _snap(snapshot_at=pd.Timestamp("2026-08-01T22:00:00Z"), value=3.10)

    store, _ = collector.accumulate_snapshots(collector._empty_store_frame(), [first])
    assert len(store) == 1
    store, _ = collector.accumulate_snapshots(store, [rerun])
    assert len(store) == 1
    assert float(store.iloc[0]["value"]) == 3.10
    assert collector.derive_genuine_revisions(store) == []


def test_fiscal_mapping_change_does_not_break_chain() -> None:
    day1 = _snap(
        snapshot_at=pd.Timestamp("2026-08-01T10:00:00Z"),
        value=3.00,
        fiscal_year=None,
        estimate_period_end=None,
    )
    day2 = _snap(
        snapshot_at=pd.Timestamp("2026-08-02T10:00:00Z"),
        value=3.20,
        fiscal_year=2027,
        estimate_period_end=pd.Timestamp("2026-06-30").date(),
    )
    store, _ = collector.accumulate_snapshots(collector._empty_store_frame(), [day1, day2])
    assert len(store) == 2
    revisions = collector.derive_genuine_revisions(store)
    assert len(revisions) == 1
    assert revisions[0]["prior_value"] == 3.00
    assert revisions[0]["current_value"] == 3.20
    assert revisions[0]["pit_class"] == "repository_captured"


def test_revision_pct_zero_denominator_is_none() -> None:
    day1 = _snap(snapshot_at=pd.Timestamp("2026-08-01T10:00:00Z"), value=0.0)
    day2 = _snap(snapshot_at=pd.Timestamp("2026-08-02T10:00:00Z"), value=1.0)
    store, _ = collector.accumulate_snapshots(collector._empty_store_frame(), [day1, day2])
    revisions = collector.derive_genuine_revisions(store)
    assert len(revisions) == 1
    assert revisions[0]["revision_pct"] is None
    assert revisions[0]["revision_value"] == 1.0


def test_empty_inputs_produce_no_fabricated_rows() -> None:
    store, remap = collector.accumulate_snapshots(collector._empty_store_frame(), [])
    assert store.empty
    assert remap == {}
    assert collector.derive_genuine_revisions(store) == []


def test_export_schema_validation(tmp_path: Path) -> None:
    day1 = _snap(snapshot_at=pd.Timestamp("2026-08-01T10:00:00Z"), value=3.00)
    day2 = _snap(snapshot_at=pd.Timestamp("2026-08-02T10:00:00Z"), value=3.10)
    store, _ = collector.accumulate_snapshots(collector._empty_store_frame(), [day1, day2])
    revisions = collector.derive_genuine_revisions(store)

    snap_path = tmp_path / "snapshots.parquet"
    rev_path = tmp_path / "revisions.parquet"
    collector._write(store.to_dict("records"), TASK3_SNAPSHOT_ARROW_SCHEMA, snap_path)
    collector._write(revisions, TASK3_REVISION_ARROW_SCHEMA, rev_path)

    snap_schema = pq.read_schema(snap_path)
    assert [field.name for field in snap_schema] == [field.name for field in TASK3_SNAPSHOT_ARROW_SCHEMA]
    rev_schema = pq.read_schema(rev_path)
    assert [field.name for field in rev_schema] == [field.name for field in TASK3_REVISION_ARROW_SCHEMA]


def test_genuine_sorted_most_recent_first() -> None:
    rows = [
        _snap(snapshot_at=pd.Timestamp("2026-08-01T10:00:00Z"), value=3.00),
        _snap(snapshot_at=pd.Timestamp("2026-08-02T10:00:00Z"), value=3.10),
        _snap(snapshot_at=pd.Timestamp("2026-08-03T10:00:00Z"), value=3.20),
    ]
    store, _ = collector.accumulate_snapshots(collector._empty_store_frame(), rows)
    revisions = collector.derive_genuine_revisions(store)
    assert len(revisions) == 2
    timestamps = [pd.Timestamp(rev["current_snapshot_at"]) for rev in revisions]
    assert timestamps == sorted(timestamps, reverse=True)
