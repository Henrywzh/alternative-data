"""Batch 6/7 genuine consensus revisions via immutable snapshot accumulation.

These tests exercise the collector's pure/injectable functions directly with
injected fake snapshot rows -- no live network. They cover the append-only
store, the genuine (``repository_captured``) revision derivation, the
same-day-rerun dedupe policy, stable natural keys that exclude derived
mapping labels, AkShare per-fiscal-year series identity (the 0700.HK
three-fiscal-year collision regression), honest provider freshness health,
snapshot/revision current-value consistency, zero-denominator handling,
honest empty output, physical schema conformance, and the strict precedence
of genuine revisions over reconstructed cold-start rows.
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


def _ak_snap(**overrides: object) -> dict:
    """A fake akshare-relayed snapshot, shaped like the collector row."""
    row = {
        "snapshot_id": "run-scoped-ak",
        "provider": "akshare",
        "entity_id": "TENCENT",
        "listing_id": "0700_HK",
        "financial_data_security_id": "sec-0700",
        "canonical_ticker": "0700.HK",
        "metric": "eps",
        "fiscal_period": "annual",
        "fiscal_year": 2026,
        "estimate_period_end": date(2026, 12, 31),
        "horizon": "",
        "snapshot_at": pd.Timestamp("2026-07-26T00:00:00Z"),
        "value": 27.188,
        "statistic": "mean",
        "low_value": 23.93,
        "high_value": 31.15,
        "analyst_count": None,
        "provider_contributor_count": None,
        "currency": "HKD",
        "unit": "currency_per_share",
        "accounting_basis": "provider_reported_non_gaap_unverified",
        "provider_asof": pd.Timestamp("2026-07-26T16:17:49Z"),
        "retrieved_at_utc": pd.Timestamp("2026-08-19T00:18:35Z"),
        "source_url": "https://www.akshare.xyz/",
        "raw_hash": "raw-ak",
        "pit_class": "snapshot_from_delayed_source",
        "source_run_id": "consensus-run-1",
        "calculation_origin": "sibling_repository_export",
        "coverage_reason": "",
    }
    row.update(overrides)
    return row

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


def test_reconstructed_covered_chain_suppressed_by_genuine() -> None:
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
    pit_classes = list(combined["pit_class"])
    assert pit_classes.count("repository_captured") == 1
    # Strict precedence: the reconstructed rows for the covered chain are
    # suppressed and the genuine row is emitted first; nothing is blended.
    assert len(combined) == 1
    assert combined.iloc[0]["pit_class"] == "repository_captured"


def test_akshare_three_fiscal_year_rows_map_and_keep_distinct_stable_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the sibling akshare export holds one row per fiscal year
    (0700.HK FY2026/FY2027/FY2028, ``horizon=None``), and all three must
    survive with distinct, deterministic snapshot ids and correct period
    mapping. The historical bug emitted one shared run-scoped snapshot_id
    and the store label-keyed dedupe collapsed the series to a single row."""

    export_dir = tmp_path / "source=akshare" / "snapshot_date=2026-07-26"
    export_dir.mkdir(parents=True)
    export = pd.DataFrame(
        [
            {
                "consensus_id": "c-2026", "security_id": "sec-0700",
                "ticker": "0700.HK", "snapshot_date": "2026-07-26",
                "fiscal_year": 2026, "eps_avg": 27.188, "eps_low": 23.93,
                "eps_high": 31.15, "horizon": None, "eps_currency": None,
                "revenue_currency": None, "revenue_avg": None,
                "fetched_at": pd.Timestamp("2026-07-26T16:17:49Z"),
            },
            {
                "consensus_id": "c-2027", "security_id": "sec-0700",
                "ticker": "0700.HK", "snapshot_date": "2026-07-26",
                "fiscal_year": 2027, "eps_avg": 30.02755, "eps_low": 25.912,
                "eps_high": 34.69, "horizon": None, "eps_currency": None,
                "revenue_currency": None, "revenue_avg": None,
                "fetched_at": pd.Timestamp("2026-07-26T16:17:49Z"),
            },
            {
                "consensus_id": "c-2028", "security_id": "sec-0700",
                "ticker": "0700.HK", "snapshot_date": "2026-07-26",
                "fiscal_year": 2028, "eps_avg": 33.197824, "eps_low": 29.058,
                "eps_high": 38.98, "horizon": None, "eps_currency": None,
                "revenue_currency": None, "revenue_avg": None,
                "fetched_at": pd.Timestamp("2026-07-26T16:17:49Z"),
            },
        ]
    )
    export.to_parquet(export_dir / "consensus-akshare-test.parquet")
    monkeypatch.setattr(collector, "FD_CONSENSUS", tmp_path)

    mapping = pd.DataFrame(
        [
            {
                "ticker": "0700.HK", "metric": "eps", "source_horizon": "0y",
                "mapped_fiscal_year": 2026, "mapped_period_end": pd.Timestamp("2026-12-31"),
                "alignment_quality": "estimated", "confidence": "high",
                "period_kind": "annual",
            },
            {
                "ticker": "0700.HK", "metric": "eps", "source_horizon": "+1y",
                "mapped_fiscal_year": 2027, "mapped_period_end": pd.Timestamp("2027-12-31"),
                "alignment_quality": "estimated", "confidence": "high",
                "period_kind": "annual",
            },
        ]
    )
    listings = pd.DataFrame(
        [
            {
                "entity_id": "TENCENT", "listing_id": "0700_HK",
                "canonical_ticker": "0700.HK",
                "financial_data_security_id": "sec-0700",
                "currency": "HKD", "listing_status": "active",
            }
        ]
    )

    snapshots, notes = collector.collect_financial_data(
        listings, mapping, run_id="consensus-test", now=pd.Timestamp("2026-08-19T00:18:35Z")
    )
    assert not notes
    assert len(snapshots) == 3
    assert len({snap["snapshot_id"] for snap in snapshots}) == 3
    assert sorted(snap["fiscal_year"] for snap in snapshots) == [2026, 2027, 2028]
    ends = sorted(snap["estimate_period_end"] for snap in snapshots)
    assert ends == [date(2026, 12, 31), date(2027, 12, 31), date(2028, 12, 31)]
    assert all(
        "period end derived from issuer annual calendar" in snap["coverage_reason"]
        for snap in snapshots
    )

    # The store must keep all three vintages with deterministic distinct ids.
    store = collector.accumulate_snapshots(_empty_store(), snapshots, run_date=date(2026, 7, 26))
    assert len(store) == 3
    assert store["snapshot_id"].nunique() == 3
    store2 = collector.accumulate_snapshots(store, snapshots, run_date=date(2026, 7, 26))
    assert len(store2) == 3
    assert set(store2["snapshot_id"]) == set(store["snapshot_id"])


def test_fiscal_mapping_label_change_does_not_break_revision_chain() -> None:
    """Spec rule: fiscal-period mapping labels never enter the chaining key.
    A corrected mapping (day two relabels the same horizon to a later fiscal
    year) must not split one series into two chains."""

    day1 = _snap(
        snapshot_at=pd.Timestamp("2026-08-01T10:00:00Z"),
        value=7.20, fiscal_year=2026,
        estimate_period_end=date(2026, 9, 30),
    )
    day2 = _snap(
        snapshot_at=pd.Timestamp("2026-08-02T10:00:00Z"),
        value=7.35, fiscal_year=2027,  # mapping correction, same source series
        estimate_period_end=date(2027, 9, 30),
        source_run_id="consensus-run-2",
    )

    store = collector.accumulate_snapshots(_empty_store(), [day1], run_date=DAY1)
    store = collector.accumulate_snapshots(store, [day2], run_date=DAY2)
    assert len(store) == 2

    revisions = collector.derive_genuine_revisions(store)
    assert len(revisions) == 1  # relabeling must not break the pair
    rev = revisions.iloc[0]
    assert rev["prior_value"] == pytest.approx(7.20)
    assert rev["current_value"] == pytest.approx(7.35)
    assert rev["fiscal_year"] == 2027  # descriptive label follows the newer vintage


def test_reconstructed_revision_matches_snapshot_identity_and_value() -> None:
    """The reconstructed eps_trend revision must reference the snapshot's
    stable id and expose the snapshot's own mean value as ``current_value``,
    so the revisions mart and the snapshots mart cannot diverge."""

    snap = _snap(
        snapshot_at=pd.Timestamp("2026-08-02T10:00:00Z"),
        value=3.15, analyst_count=32,
    )
    snap["snapshot_id"] = collector.stable_snapshot_id(snap, date(2026, 8, 2))

    revision = collector._reconstructed_revision_row(
        snap,
        prior_value=3.00,
        lookback_days=7,
        now=pd.Timestamp("2026-08-02T10:00:00Z"),
        alignment_status="estimated_confidence_high",
    )
    assert revision["snapshot_id"] == snap["snapshot_id"]
    assert revision["provider"] == "yfinance"
    assert revision["current_value"] == pytest.approx(3.15)
    assert revision["prior_value"] == pytest.approx(3.00)
    assert revision["revision_value"] == pytest.approx(0.15)
    assert revision["lookback_days"] == 7
    assert revision["current_analyst_count"] == 32
    assert revision["pit_class"] == "reconstructed_sparse"
    assert revision["prior_snapshot_id"] == ""
    assert revision["alignment_status"] == "estimated_confidence_high"
    assert revision["current_snapshot_at"] == snap["snapshot_at"]


def test_combine_revision_export_precedence_suppresses_covered_reconstructed_chains() -> None:
    """Strict precedence: reconstructed cold-start rows for a chain that
    already has genuine repository_captured history are suppressed; rows for
    uncovered chains survive to give the panel a cold start. The two classes
    are never blended or deduped against each other."""

    day1 = _snap(snapshot_at=pd.Timestamp("2026-08-01T10:00:00Z"), value=3.00)
    day2 = _snap(snapshot_at=pd.Timestamp("2026-08-02T10:00:00Z"), value=3.10)
    store = collector.accumulate_snapshots(
        collector.accumulate_snapshots(_empty_store(), [day1], run_date=DAY1),
        [day2],
        run_date=DAY2,
    )
    genuine = collector.derive_genuine_revisions(store)
    covered = _reconstructed(revision_id="recon-covered")
    uncovered = _reconstructed(
        revision_id="recon-uncovered",
        horizon="+1q",
        fiscal_period="quarterly",
        estimate_period_end=date(2027, 6, 30),
    )
    reconstructed = pd.DataFrame([covered, uncovered], columns=collector.REVISION_COLUMNS)

    combined = collector.combine_revision_export(genuine, reconstructed)
    assert len(combined) == 2
    pit_classes = list(combined["pit_class"])
    assert pit_classes.count("repository_captured") == 1
    assert pit_classes.count("reconstructed_sparse") == 1
    assert pit_classes.index("repository_captured") < pit_classes.index("reconstructed_sparse")
    recon_rows = combined.loc[combined["pit_class"].eq("reconstructed_sparse")]
    assert list(recon_rows["revision_id"]) == ["recon-uncovered"]
    assert list(recon_rows["horizon"]) == ["+1q"]  # untouched, labeled sparse


def test_provider_health_flags_stale_provider_asof() -> None:
    """Health semantics: a populated provider whose latest provider_asof is
    outside its freshness window is reported ``stale``, never ``available``
    (regression: the akshare relay was 24d old yet flagged available)."""

    store = collector.accumulate_snapshots(
        _empty_store(),
        [_ak_snap(
            snapshot_at=pd.Timestamp("2026-07-26T00:00:00Z"),
            provider_asof=pd.Timestamp("2026-07-26T16:17:49Z"),
        )],
        run_date=date(2026, 7, 26),
    )
    now = pd.Timestamp("2026-08-19T00:00:00Z")
    sla_days = collector.PROVIDER_FRESHNESS_SLA_DAYS["akshare"]
    status, detail = collector._provider_freshness_status(store, sla_days, now)
    assert status == "stale"
    assert "provider_asof" in detail
    assert f"{sla_days}d" in detail

    fresh = collector.accumulate_snapshots(
        _empty_store(),
        [_ak_snap(
            snapshot_at=pd.Timestamp("2026-08-19T00:00:00Z"),
            provider_asof=pd.Timestamp("2026-08-19T00:00:00Z"),
        )],
        run_date=date(2026, 8, 19),
    )
    status, detail = collector._provider_freshness_status(fresh, sla_days, now)
    assert status == "available"


def test_build_provider_health_rows_reports_stale_akshare_and_fresh_yfinance() -> None:
    """The health sidecar must distinguish a stale relayed provider from a
    fresh live provider and keep empty providers honest."""

    stale_ak = _ak_snap(
        snapshot_at=pd.Timestamp("2026-07-26T00:00:00Z"),
        provider_asof=pd.Timestamp("2026-07-26T16:17:49Z"),
    )
    fresh_yf = _snap(
        provider="yfinance",
        entity_id="TENCENT",
        listing_id="0700_HK",
        canonical_ticker="0700.HK",
        financial_data_security_id="sec-0700",
        snapshot_at=pd.Timestamp("2026-08-19T00:18:35Z"),
        provider_asof=pd.Timestamp("2026-08-19T00:18:35Z"),
        retrieved_at_utc=pd.Timestamp("2026-08-19T00:18:35Z"),
        value=29.11,
    )
    store = collector.accumulate_snapshots(
        _empty_store(), [stale_ak, fresh_yf], run_date=date(2026, 8, 19)
    )
    revisions = pd.DataFrame({column: pd.Series(dtype="object") for column in collector.REVISION_COLUMNS})
    now = pd.Timestamp("2026-08-19T00:30:00Z")

    health = collector.build_provider_health_rows(
        store, revisions, now=now, yf_notes=[], fd_notes=[], calls=3
    )
    by_provider = {row["provider"]: row for row in health}
    assert set(by_provider) == {"yfinance", "akshare"}
    assert by_provider["yfinance"]["status"] == "available"
    assert by_provider["akshare"]["status"] == "stale"
    assert "older than as_of (freshness window 14d)" in by_provider["akshare"]["reason"]
    assert "store_vintages=1" in by_provider["akshare"]["reason"]

    # Empty store -> both providers honestly unavailable.
    empty_health = collector.build_provider_health_rows(
        _empty_store(), revisions, now=now, yf_notes=[], fd_notes=[], calls=0
    )
    assert {row["status"] for row in empty_health} == {"unavailable"}


def test_future_dated_provider_asof_fails_closed() -> None:
    """Check (1) & (2): Future-dated provider_asof must fail closed in freshness status
    and be excluded in collect_financial_data."""
    now = pd.Timestamp("2026-08-01T00:00:00Z")
    future_snap = _ak_snap(
        snapshot_at=pd.Timestamp("2026-08-10T00:00:00Z"),
        provider_asof=pd.Timestamp("2026-08-10T12:00:00Z"),
    )
    store = collector.accumulate_snapshots(_empty_store(), [future_snap], run_date=date(2026, 8, 10))
    status, detail = collector._provider_freshness_status(store, 14, now)
    assert status == "fail_closed_future_dated"
    assert "in the future relative to as_of" in detail


def test_collect_financial_data_excludes_future_dated_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sibling relay rows with snapshot_date or fetched_at later than now are excluded with notes."""
    export_dir = tmp_path / "source=akshare" / "snapshot_date=2026-08-10"
    export_dir.mkdir(parents=True)
    export = pd.DataFrame(
        [
            {
                "consensus_id": "c-future", "security_id": "sec-0700",
                "ticker": "0700.HK", "snapshot_date": "2026-08-10",
                "fiscal_year": 2026, "eps_avg": 28.0, "eps_low": 25.0,
                "eps_high": 32.0, "horizon": None, "eps_currency": None,
                "revenue_currency": None, "revenue_avg": None,
                "fetched_at": pd.Timestamp("2026-08-10T12:00:00Z"),
            }
        ]
    )
    export.to_parquet(export_dir / "consensus-future.parquet")
    monkeypatch.setattr(collector, "FD_CONSENSUS", tmp_path)
    listings = pd.DataFrame(
        [
            {
                "entity_id": "TENCENT", "listing_id": "0700_HK",
                "canonical_ticker": "0700.HK",
                "financial_data_security_id": "sec-0700",
                "currency": "HKD", "listing_status": "active",
            }
        ]
    )
    mapping = pd.DataFrame()
    now = pd.Timestamp("2026-08-01T00:00:00Z")
    snapshots, notes = collector.collect_financial_data(listings, mapping, run_id="r1", now=now)
    assert len(snapshots) == 0
    assert any("excluded future-dated sibling row for 0700.HK" in n for n in notes)


def test_same_day_multiple_rows_selects_newest_provider_asof() -> None:
    """Check (3): Same-day multiple rows for one natural key must choose deterministic newest vintage
    using provider_asof/retrieved_at_utc, not parquet/list ingestion order."""
    row_earlier = _snap(
        snapshot_at=pd.Timestamp("2026-08-01T10:00:00Z"),
        provider_asof=pd.Timestamp("2026-08-01T08:00:00Z"),
        retrieved_at_utc=pd.Timestamp("2026-08-01T08:00:00Z"),
        value=10.0,
    )
    row_later = _snap(
        snapshot_at=pd.Timestamp("2026-08-01T10:00:00Z"),
        provider_asof=pd.Timestamp("2026-08-01T14:00:00Z"),
        retrieved_at_utc=pd.Timestamp("2026-08-01T14:00:00Z"),
        value=12.5,
    )

    # Ingestion order 1: [earlier, later]
    store1 = collector.accumulate_snapshots(_empty_store(), [row_earlier, row_later], run_date=DAY1)
    assert len(store1) == 1
    assert store1.iloc[0]["value"] == pytest.approx(12.5)

    # Ingestion order 2: [later, earlier] -> must still pick later!
    store2 = collector.accumulate_snapshots(_empty_store(), [row_later, row_earlier], run_date=DAY1)
    assert len(store2) == 1
    assert store2.iloc[0]["value"] == pytest.approx(12.5)
