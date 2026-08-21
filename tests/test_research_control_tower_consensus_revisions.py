"""Batch 6/7 genuine consensus revisions via immutable snapshot accumulation.

These tests exercise the collector's pure/injectable functions directly with
injected fake snapshot rows -- no live network. They cover the append-only
store, the genuine (``repository_captured``) revision derivation, the
same-day-rerun dedupe policy, zero-denominator handling, honest empty output,
physical schema conformance, and the coexistence/ordering of genuine vs
reconstructed revisions in the export.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import pandas as pd
import pyarrow.parquet as pq
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "scripts", REPO_ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import research_control_tower_consensus_collector as collector  # noqa: E402
from research_control_tower.build import (  # noqa: E402
    TASK3_REVISION_ARROW_SCHEMA,
    TASK3_SNAPSHOT_ARROW_SCHEMA,
)


DAY1 = date(2026, 8, 1)
DAY2 = date(2026, 8, 2)


def _snap(**overrides: object) -> dict:
    """A fake captured snapshot shaped like the collector's row dicts."""

    row = {
        "snapshot_id": "run-scoped-id",
        "provider": "yfinance",
        "entity_id": "ALIBABA",
        "listing_id": "9988_HK",
        "financial_data_security_id": "sec-9988",
        "canonical_ticker": "9988.HK",
        "metric": "eps",
        "fiscal_period": "quarterly",
        "fiscal_year": 2027,
        "estimate_period_end": pd.Timestamp("2027-03-31").date(),
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
        "source_url": "https://finance.yahoo.com/quote/9988.HK/analysis",
        "raw_hash": "raw-hash",
        "pit_class": "snapshot_from_live_source",
        "source_run_id": "consensus-run-1",
        "calculation_origin": "provider_published_consensus",
        "coverage_reason": "",
    }
    row.update(overrides)
    return row


def _empty_store() -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in collector.STORE_COLUMNS})


def _reconstructed(**overrides: object) -> dict:
    """A fake eps_trend reconstructed revision, exactly as collected."""

    row = {
        "revision_id": "recon-1",
        "snapshot_id": "snap-1",
        "provider": "yfinance",
        "prior_provider": "yfinance",
        "entity_id": "ALIBABA",
        "listing_id": "9988_HK",
        "financial_data_security_id": "sec-9988",
        "canonical_ticker": "9988.HK",
        "metric": "eps",
        "fiscal_period": "quarterly",
        "fiscal_year": 2027,
        "estimate_period_end": pd.Timestamp("2027-03-31").date(),
        "horizon": "0q",
        "statistic": "mean",
        "current_snapshot_at": pd.Timestamp("2026-08-02T10:00:00Z"),
        "current_value": 3.15,
        "current_analyst_count": 32,
        "current_dispersion": None,
        "lookback_days": 7,
        "cutoff_at": pd.Timestamp("2026-07-26T10:00:00Z"),
        "prior_snapshot_id": "",
        "prior_snapshot_at": pd.Timestamp("2026-07-26T10:00:00Z"),
        "prior_value": 3.00,
        "prior_provider_asof": pd.Timestamp("2026-07-26T10:00:00Z"),
        "provider_asof": pd.Timestamp("2026-08-02T10:00:00Z"),
        "retrieved_at_utc": pd.Timestamp("2026-08-02T10:00:00Z"),
        "source_url": "https://finance.yahoo.com/quote/9988.HK/analysis",
        "pit_class": "reconstructed_sparse",
        "source_run_id": "consensus-run-1",
        "prior_analyst_count": None,
        "revision_value": 0.15,
        "revision_pct": 5.0,
        "analyst_count_change": None,
        "dispersion": None,
        "alignment_status": "high_confidence_high",
    }
    row.update(overrides)
    return row


def test_two_day_accumulation_derives_genuine_revision() -> None:
    day1 = _snap(snapshot_at=pd.Timestamp("2026-08-01T10:00:00Z"), value=3.00, analyst_count=30)
    day2 = _snap(
        snapshot_at=pd.Timestamp("2026-08-02T10:00:00Z"),
        value=3.15,
        analyst_count=32,
        source_run_id="consensus-run-2",
    )

    store = collector.accumulate_snapshots(_empty_store(), [day1], run_date=DAY1)
    store = collector.accumulate_snapshots(store, [day2], run_date=DAY2)

    assert len(store) == 2  # two vintages for the same natural key, one per UTC day
    assert len(set(store["snapshot_id"])) == 2  # deterministic distinct vintage ids

    revisions = collector.derive_genuine_revisions(store)
    assert len(revisions) == 1
    rev = revisions.iloc[0]

    prior_row = store.iloc[0]
    current_row = store.iloc[1]
    assert rev["prior_snapshot_id"] == prior_row["snapshot_id"]
    assert rev["snapshot_id"] == current_row["snapshot_id"]
    assert rev["provider"] == "yfinance"
    assert rev["prior_provider"] == "yfinance"
    assert rev["pit_class"] == "repository_captured"

    assert rev["prior_value"] == pytest.approx(3.00)
    assert rev["current_value"] == pytest.approx(3.15)
    assert rev["revision_value"] == pytest.approx(0.15)
    # Spec: revision_pct = (current - prior) / abs(prior) -- a fraction, not x100.
    assert rev["revision_pct"] == pytest.approx(0.15 / 3.00)
    assert rev["analyst_count_change"] == 2
    assert rev["lookback_days"] == 1
    assert rev["prior_analyst_count"] == 30
    assert rev["current_analyst_count"] == 32

    assert rev["current_snapshot_at"] == pd.Timestamp("2026-08-02T10:00:00Z")
    assert rev["prior_snapshot_at"] == pd.Timestamp("2026-08-01T10:00:00Z")
    assert rev["cutoff_at"] == rev["prior_snapshot_at"]
    assert rev["retrieved_at_utc"] == day2["retrieved_at_utc"]
    assert rev["source_url"] == day2["source_url"]
    assert rev["source_run_id"] == "consensus-run-2"
    # Fiscal fields copied from the newer vintage.
    assert rev["fiscal_year"] == 2027
    assert rev["estimate_period_end"] == pd.Timestamp("2027-03-31").date()
    assert rev["entity_id"] == "ALIBABA"
    assert rev["listing_id"] == "9988_HK"


def test_same_day_rerun_is_idempotent_and_id_stable() -> None:
    first = _snap(snapshot_at=pd.Timestamp("2026-08-01T08:00:00Z"), value=3.00)
    rerun = _snap(snapshot_at=pd.Timestamp("2026-08-01T22:00:00Z"), value=3.10)

    store = collector.accumulate_snapshots(_empty_store(), [first], run_date=DAY1)
    assert len(store) == 1
    first_id = str(store.iloc[0]["snapshot_id"])

    store = collector.accumulate_snapshots(store, [rerun], run_date=DAY1)
    assert len(store) == 1  # same natural key + same UTC day -> still one vintage
    assert float(store.iloc[0]["value"]) == 3.10  # last-write-wins within the day
    assert str(store.iloc[0]["snapshot_id"]) == first_id  # stable id across rerun

    # The id is the deterministic hash of the natural key + snapshot UTC date.
    assert collector.stable_snapshot_id(rerun, DAY1) == first_id
    assert collector.derive_genuine_revisions(store).empty  # one vintage -> no revision


def test_revision_pct_zero_denominator_is_none() -> None:
    day1 = _snap(snapshot_at=pd.Timestamp("2026-08-01T10:00:00Z"), value=0.0)
    day2 = _snap(snapshot_at=pd.Timestamp("2026-08-02T10:00:00Z"), value=1.0)

    store = collector.accumulate_snapshots(_empty_store(), [day1], run_date=DAY1)
    store = collector.accumulate_snapshots(store, [day2], run_date=DAY2)
    revisions = collector.derive_genuine_revisions(store)

    assert len(revisions) == 1
    assert revisions.iloc[0]["revision_value"] == pytest.approx(1.0)
    assert revisions.iloc[0]["revision_pct"] is None  # denominator zero -> None, no crash


def test_empty_inputs_produce_no_fabricated_rows() -> None:
    store = collector.accumulate_snapshots(_empty_store(), [], run_date=DAY1)
    assert store.empty
    assert list(store.columns) == collector.STORE_COLUMNS
    revisions = collector.derive_genuine_revisions(store)
    assert revisions.empty
    assert list(revisions.columns) == collector.REVISION_COLUMNS


def test_main_empty_listings_writes_honest_empty_exports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    listings = tmp_path / "listings.csv"
    listings.write_text(
        "entity_id,listing_id,canonical_ticker,financial_data_security_id,currency,listing_status,active_from,active_to,registry_version\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    monkeypatch.setattr(collector, "collect_yfinance", lambda *args, **kwargs: ([], [], 0, []))
    monkeypatch.setattr(collector, "collect_financial_data", lambda *args, **kwargs: ([], []))

    code = collector.main([
        "--listings", str(listings),
        "--output-dir", str(out),
    ])
    assert code == 0

    snap_path = out / "control_tower_consensus_snapshots.parquet"
    rev_path = out / "control_tower_consensus_revisions.parquet"
    health_path = out / "control_tower_consensus_source_health.parquet"
    assert snap_path.is_file()
    assert rev_path.is_file()
    assert health_path.is_file()

    snapshots = pd.read_parquet(snap_path)
    revisions = pd.read_parquet(rev_path)
    assert snapshots.empty
    assert revisions.empty
    health = pd.read_parquet(health_path)
    assert len(health) == 2
    yf = health.loc[health["provider"].eq("yfinance")].iloc[0]
    assert yf["status"] == "unavailable"
    assert "genuine_revisions=0" in yf["reason"]
    assert "reconstructed=0" in yf["reason"]
    assert "store_vintages=0" in yf["reason"]


def test_export_physical_schemas_match_task3_arrow_schemas(tmp_path: Path) -> None:
    day1 = _snap(snapshot_at=pd.Timestamp("2026-08-01T10:00:00Z"), value=3.00)
    day2 = _snap(snapshot_at=pd.Timestamp("2026-08-02T10:00:00Z"), value=3.10)
    store = collector.accumulate_snapshots(
        collector.accumulate_snapshots(_empty_store(), [day1], run_date=DAY1),
        [day2],
        run_date=DAY2,
    )
    revisions = collector.derive_genuine_revisions(store)

    snap_path = tmp_path / "control_tower_consensus_snapshots.parquet"
    rev_path = tmp_path / "control_tower_consensus_revisions.parquet"
    collector._write(
        collector.snapshot_export_frame(store),
        TASK3_SNAPSHOT_ARROW_SCHEMA,
        snap_path,
    )
    collector._write(revisions, TASK3_REVISION_ARROW_SCHEMA, rev_path)

    # Same physical arrow schema check _task3_physical_schema performs.
    assert pq.read_schema(snap_path).equals(TASK3_SNAPSHOT_ARROW_SCHEMA)
    assert pq.read_schema(rev_path).equals(TASK3_REVISION_ARROW_SCHEMA)


def test_appended_store_preserves_schema_and_reverts_deterministically(tmp_path: Path) -> None:
    day1 = _snap(snapshot_at=pd.Timestamp("2026-08-01T10:00:00Z"), value=3.00)
    day2 = _snap(snapshot_at=pd.Timestamp("2026-08-02T10:00:00Z"), value=3.10)
    store = collector.accumulate_snapshots(
        collector.accumulate_snapshots(_empty_store(), [day1], run_date=DAY1),
        [day2],
        run_date=DAY2,
    )
    store_path = tmp_path / "store" / "snapshots_store.parquet"
    collector._write_atomic(store, TASK3_SNAPSHOT_ARROW_SCHEMA, store_path)
    assert pq.read_schema(store_path).equals(TASK3_SNAPSHOT_ARROW_SCHEMA)

    reloaded = collector._read_store(store_path)
    assert len(reloaded) == 2
    first = collector.derive_genuine_revisions(reloaded)
    second = collector.derive_genuine_revisions(collector._read_store(store_path))
    assert not first.empty
    assert list(first["revision_id"]) == list(second["revision_id"])
    assert list(first["current_snapshot_at"]) == list(second["current_snapshot_at"])


def test_genuine_sorted_first_and_reconstructed_preserved() -> None:
    day1 = _snap(snapshot_at=pd.Timestamp("2026-08-01T10:00:00Z"), value=3.00)
    day2 = _snap(snapshot_at=pd.Timestamp("2026-08-02T10:00:00Z"), value=3.10)
    store = collector.accumulate_snapshots(
        collector.accumulate_snapshots(_empty_store(), [day1], run_date=DAY1),
        [day2],
        run_date=DAY2,
    )
    genuine = collector.derive_genuine_revisions(store)
    reconstructed = pd.DataFrame(
        [_reconstructed(revision_id="recon-a"), _reconstructed(revision_id="recon-b")],
        columns=collector.REVISION_COLUMNS,
    )

    combined = collector.combine_revision_export(genuine, reconstructed)
    assert len(combined) == 3
    pit_classes = list(combined["pit_class"])
    assert pit_classes.count("repository_captured") == 1
    assert pit_classes.count("reconstructed_sparse") == 2
    # Genuine rows are all before reconstructed rows; reconstructed stay as-is.
    assert pit_classes.index("repository_captured") < pit_classes.index("reconstructed_sparse")
    recon_rows = combined.loc[combined["pit_class"].eq("reconstructed_sparse")]
    assert list(recon_rows["revision_id"]) == ["recon-a", "recon-b"]
    assert recon_rows["revision_pct"].tolist() == [5.0, 5.0]  # unchanged, labeled sparse
