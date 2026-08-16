"""Batch 3 collector tests: SEC XBRL actuals extraction and honest states."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from src.research_control_tower.build import EARNINGS_ACTUALS_COLUMNS, SOURCE_STATE_COLUMNS
from src.research_control_tower.earnings_actuals import (
    _fact_rows,
    _lineage,
    collect_earnings_actuals,
)


def _fact(metric_rows, **kwargs):
    """Build a companyfacts payload with one us-gaap tag per metric."""

    facts = {}
    for tag, rows in metric_rows.items():
        facts[tag] = {"units": {"CNY": rows}}
    return {
        "cik": 1577552,
        "entityName": "Alibaba Group Holding Ltd",
        "facts": {"us-gaap": facts, "dei": {}},
    }


REVENUE_ROWS = [
    {
        "start": "2025-04-01", "end": "2026-03-31", "val": 52504000000,
        "accn": "0001047469-16-013400", "fy": 2016, "fp": "FY",
        "form": "20-F", "filed": "2026-06-25", "frame": "CY2025",
    },
    {
        "start": "2025-04-01", "end": "2026-03-31", "val": 53120000000,
        "accn": "0001047469-16-020001", "fy": 2016, "fp": "FY",
        "form": "20-F/A", "filed": "2026-07-30", "frame": "CY2025",
    },
]
NET_INCOME_ROWS = [
    {
        "start": "2025-04-01", "end": "2026-03-31", "val": 8532000000,
        "accn": "0001047469-16-013400", "fy": 2016, "fp": "FY",
        "form": "20-F", "filed": "2026-06-25", "frame": "CY2025",
    },
]


def test_companyfacts_extraction_preserves_reported_values_and_restatement_lineage():
    payload = _fact(
        {
            "Revenues": REVENUE_ROWS,
            "NetIncomeLoss": NET_INCOME_ROWS,
        }
    )
    extracted = _fact_rows(
        payload,
        cik=1577552,
        entity_id="ALIBABA",
        listing_id="BABA_US",
        canonical_ticker="BABA.US",
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        filed_cutoff=pd.Timestamp("2025-08-16T00:00:00Z"),
        fetched_at=pd.Timestamp("2026-08-16T12:00:00Z"),
        max_rows=1000,
    )
    rows = _lineage(extracted)
    assert len(rows) == 3
    revenue = [row for row in rows if row["metric"] == "revenue"]
    assert len(revenue) == 2
    first, second = revenue
    assert first["version"] == 1
    assert first["supersedes_actual_id"] == ""
    assert first["reported_value"] == 52504000000.0
    assert first["normalized_value"] == first["reported_value"]
    assert first["normalization_note"] == "as_reported; no normalization applied"
    assert first["currency"] == "CNY"
    assert first["accounting_basis"] == "us-gaap as reported"
    assert second["version"] == 2
    assert second["supersedes_actual_id"] == first["actual_id"]
    assert second["is_restatement"] is True
    assert second["revision_reason"] == "restatement_or_amended_filing"
    assert second["reported_value"] == 53120000000.0
    assert first["period_label"] == "FY2026"
    assert first["period_end"] == date(2026, 3, 31)
    assert first["form"] == "20-F"
    assert first["xbrl_frame"] == "CY2025"
    assert first["source_id"] == "earnings:sec_companyfacts"
    assert first["source_url"].startswith("https://www.sec.gov/Archives/edgar/data/1577552/")


def test_hkex_only_issuers_report_not_applicable_and_bytedance_is_not_applicable(tmp_path):
    identity = pd.DataFrame(
        [
            {
                "entity_id": "TENCENT",
                "listing_id": "0700_HK",
                "canonical_ticker": "0700.HK",
                "source_kind": "hkex_code",
                "source_native_id": "700",
                "source_url": "https://www1.hkexnews.hk/",
                "note": "",
            },
            {
                "entity_id": "KUAISHOU",
                "listing_id": "1024_HK",
                "canonical_ticker": "1024.HK",
                "source_kind": "hkex_code",
                "source_native_id": "1024",
                "source_url": "https://www1.hkexnews.hk/",
                "note": "",
            },
        ]
    )
    output = tmp_path / "out"
    frame, state = collect_earnings_actuals(
        identity,
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        lookback_days=730,
        output_dir=output,
        raw_root=tmp_path,
        user_agent="test/0.1 research@example.com",
        timeout=5,
    )
    assert frame.empty
    assert list(frame.columns) == EARNINGS_ACTUALS_COLUMNS
    by_source = state.set_index("source_id")["status"].to_dict()
    # Issuer-IR HTML scraping is a deliberate non-goal (SEC XBRL
    # companyfacts is the intended source for this concept; HKEX issuers
    # without a CIK simply have no XBRL to consume), not an unfilled query
    # -- "not_applicable" is the honest label, matching the
    # already-established "earnings:bytedance" convention below.
    # "no_records" previously aged this row into a permanent
    # ``review_required`` and wrongly capped every entity's
    # earnings_actuals cell at "partial"/"unavailable" forever, regardless
    # of real SEC XBRL coverage (see test_stage1_matrix regression tests
    # in test_research_control_tower_coverage_states.py).
    assert by_source["earnings:hkex_issuer_ir"] == "not_applicable"
    assert "TENCENT" in state.loc[state["source_id"].eq("earnings:hkex_issuer_ir"), "detail"].iloc[0]
    assert by_source["earnings:bytedance"] == "not_applicable"
    assert (output / "earnings_actuals_v1.parquet").is_file()
    assert (output / "earnings_actuals_state.parquet").is_file()


def test_sec_companyfacts_rows_flow_through_collector(tmp_path):
    identity = pd.DataFrame(
        [
            {
                "entity_id": "ALIBABA",
                "listing_id": "BABA_US",
                "canonical_ticker": "BABA.US",
                "source_kind": "sec_cik",
                "source_native_id": "1577552",
                "source_url": "https://www.sec.gov/",
                "note": "",
            }
        ]
    )

    class _StubClient:
        def fetch_company_facts(self, cik):
            assert cik == 1577552
            return _fact({"Revenues": REVENUE_ROWS, "NetIncomeLoss": NET_INCOME_ROWS})

    frame, state = collect_earnings_actuals(
        identity,
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        lookback_days=730,
        raw_root=tmp_path,
        user_agent="test/0.1 research@example.com",
        companyfacts_client=_StubClient(),
        timeout=5,
    )
    assert len(frame) == 3
    assert set(frame["source_id"]) == {"earnings:sec_companyfacts"}
    assert state.loc[state["source_id"].eq("earnings:sec_companyfacts"), "status"].iloc[0] == "available"
    assert state.loc[state["source_id"].eq("earnings:bytedance"), "status"].iloc[0] == "not_applicable"


def test_fact_rows_combines_legacy_and_modern_taxonomy_tags_for_non_overlapping_periods():
    legacy_rows = [
        {
            "start": "2016-01-01", "end": "2016-12-31", "val": 100000000,
            "accn": "0000000000-17-000001", "fy": 2016, "fp": "FY",
            "form": "10-K", "filed": "2017-02-15",
        },
        {
            "start": "2017-01-01", "end": "2017-12-31", "val": 120000000,
            "accn": "0000000000-18-000001", "fy": 2017, "fp": "FY",
            "form": "10-K", "filed": "2018-02-15",
        },
    ]
    modern_rows = [
        {
            "start": "2018-01-01", "end": "2018-12-31", "val": 150000000,
            "accn": "0000000000-19-000001", "fy": 2018, "fp": "FY",
            "form": "10-K", "filed": "2019-02-15",
        },
    ]
    payload = {
        "cik": 100000,
        "entityName": "Legacy Filer Inc",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": modern_rows}},
                "SalesRevenueNet": {"units": {"USD": legacy_rows}},
            }
        },
    }
    rows = _fact_rows(
        payload,
        cik=100000,
        entity_id="LEGACY",
        listing_id="LEG_US",
        canonical_ticker="LEG.US",
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        filed_cutoff=pd.Timestamp("2015-01-01T00:00:00Z"),
        fetched_at=pd.Timestamp("2026-08-16T12:00:00Z"),
        max_rows=100,
    )
    assert len(rows) == 3
    period_ends = {r["period_end"] for r in rows}
    assert period_ends == {date(2016, 12, 31), date(2017, 12, 31), date(2018, 12, 31)}
    by_tag = {r["period_end"]: r["tag"] for r in rows}
    assert by_tag[date(2016, 12, 31)] == "SalesRevenueNet"
    assert by_tag[date(2017, 12, 31)] == "SalesRevenueNet"
    assert by_tag[date(2018, 12, 31)] == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_fact_rows_supports_ifrs_full_taxonomy_tags():
    ifrs_revenue_rows = [
        {
            "start": "2025-01-01", "end": "2025-12-31", "val": 250000000,
            "accn": "0000000000-26-000001", "fy": 2025, "fp": "FY",
            "form": "20-F", "filed": "2026-03-30",
        }
    ]
    ifrs_profit_rows = [
        {
            "start": "2025-01-01", "end": "2025-12-31", "val": 45000000,
            "accn": "0000000000-26-000001", "fy": 2025, "fp": "FY",
            "form": "20-F", "filed": "2026-03-30",
        }
    ]
    payload = {
        "cik": 200000,
        "entityName": "IFRS Filer Corp",
        "facts": {
            "ifrs-full": {
                "Revenue": {"units": {"EUR": ifrs_revenue_rows}},
                "ProfitLoss": {"units": {"EUR": ifrs_profit_rows}},
            }
        },
    }
    extracted = _fact_rows(
        payload,
        cik=200000,
        entity_id="IFRS_CO",
        listing_id="IFRS_US",
        canonical_ticker="IFRS.US",
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        filed_cutoff=pd.Timestamp("2025-01-01T00:00:00Z"),
        fetched_at=pd.Timestamp("2026-08-16T12:00:00Z"),
        max_rows=100,
    )
    rows = _lineage(extracted)
    assert len(rows) == 2
    metrics = {r["metric"]: r for r in rows}
    assert "revenue" in metrics
    assert "net_income" in metrics
    assert metrics["revenue"]["accounting_basis"] == "ifrs-full as reported"
    assert metrics["net_income"]["accounting_basis"] == "ifrs-full as reported"
