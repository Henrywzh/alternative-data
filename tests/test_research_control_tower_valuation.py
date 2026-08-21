"""Tests for valuation snapshots and internal estimates data contracts and transforms.

Validates Gate T2 requirements:
- valuation_snapshots schema, primary keys, and calculations
- forward_pe, ev_ebitda, fcf_yield, shareholder_cash_return_yield
- Full auditability of numerator/denominator vintages, currency conversions, and FX logging
- Percentile history unavailable without historical denominator vintages
- Full isolation between provider consensus and internal estimates / management guidance
- Deterministic error handling and fail-closed validation
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.research_control_tower.valuation import (
    INTERNAL_ESTIMATES_COLUMNS,
    SUPPORTED_METRIC_BASES,
    SUPPORTED_OBSERVATION_TYPES,
    SUPPORTED_VALUATION_METRICS,
    SUPPORTED_VALUATION_PIT_CLASSES,
    VALUATION_SNAPSHOTS_COLUMNS,
    ValuationInput,
    build_valuation_snapshot_row,
    compute_valuation_id,
    load_internal_estimates_csv,
    validate_internal_estimates_df,
    validate_valuation_snapshots_df,
)


def test_constants_and_vocabularies():
    """Verify supported enums and columns conform strictly to design spec."""
    assert "forward_pe" in SUPPORTED_VALUATION_METRICS
    assert "ev_ebitda" in SUPPORTED_VALUATION_METRICS
    assert "fcf_yield" in SUPPORTED_VALUATION_METRICS
    assert "shareholder_cash_return_yield" in SUPPORTED_VALUATION_METRICS

    assert "GAAP_REPORTED" in SUPPORTED_METRIC_BASES
    assert "NON_IFRS_MANAGEMENT" in SUPPORTED_METRIC_BASES
    assert "PROVIDER_UNVERIFIED" in SUPPORTED_METRIC_BASES

    assert "management_guidance" in SUPPORTED_OBSERVATION_TYPES
    assert "internal_estimate" in SUPPORTED_OBSERVATION_TYPES

    assert "snapshot_from_delayed_source" in SUPPORTED_VALUATION_PIT_CLASSES
    assert "true_pit" in SUPPORTED_VALUATION_PIT_CLASSES

    assert "valuation_id" in VALUATION_SNAPSHOTS_COLUMNS
    assert "percentile_history_status" in VALUATION_SNAPSHOTS_COLUMNS
    assert "estimate_id" in INTERNAL_ESTIMATES_COLUMNS


def test_build_forward_pe_same_currency():
    """Test Forward P/E calculation when price and EPS share the same currency."""
    now = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
    inp = ValuationInput(
        listing_id="0700_HK",
        valuation_at=now,
        metric_name="forward_pe",
        metric_basis="NON_IFRS_MANAGEMENT",
        numerator_value=380.0,
        numerator_currency="HKD",
        numerator_ref="quote:0700_HK_20260821",
        denominator_value=25.0,
        denominator_currency="HKD",
        denominator_ref="consensus:0700_HK_fy26e_eps",
        source_id="valuation_engine",
        percentile_history_status="unavailable",
    )
    row = build_valuation_snapshot_row(inp)
    assert row["ratio_value"] == pytest.approx(380.0 / 25.0)  # 15.2
    assert row["numerator_value"] == 380.0
    assert row["denominator_value"] == 25.0
    assert row["fx_rate_applied"] is None
    assert row["percentile_history_status"] == "unavailable"

    df = pd.DataFrame([row])
    issues = validate_valuation_snapshots_df(df)
    assert not issues


def test_build_forward_pe_with_fx_conversion():
    """Test Forward P/E calculation with explicit FX conversion and audit log."""
    now = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
    fx_time = datetime(2026, 8, 21, 10, 0, 0, tzinfo=timezone.utc)
    # Price is 375.0 HKD, EPS is 28.0 CNY. FX rate: 1 CNY = 1.08 HKD.
    # Converted EPS = 28.0 * 1.08 = 30.24 HKD.
    # P/E = 375.0 / 30.24 = 12.40079
    inp = ValuationInput(
        listing_id="0700_HK",
        valuation_at=now,
        metric_name="forward_pe",
        metric_basis="NON_IFRS_MANAGEMENT",
        numerator_value=375.0,
        numerator_currency="HKD",
        numerator_ref="quote:0700_HK_20260821",
        denominator_value=28.0,
        denominator_currency="CNY",
        denominator_ref="consensus:0700_HK_fy26e_eps",
        fx_rate_applied=1.08,
        fx_source="ecb_fx:CNY_HKD_20260821",
        fx_snapshot_at_utc=fx_time,
        source_id="valuation_engine",
        percentile_history_status="unavailable",
    )
    row = build_valuation_snapshot_row(inp)
    assert row["ratio_value"] == pytest.approx(375.0 / (28.0 * 1.08))
    assert row["fx_rate_applied"] == 1.08
    assert row["fx_source"] == "ecb_fx:CNY_HKD_20260821"
    assert row["fx_snapshot_at_utc"] == fx_time

    df = pd.DataFrame([row])
    issues = validate_valuation_snapshots_df(df)
    assert not issues


def test_fcf_yield_and_shareholder_cash_return_yield():
    """Test yield metrics calculations where ratio = denominator / numerator."""
    now = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
    # Market Cap / EV = 3,500,000M HKD, FCF = 175,000M HKD -> Yield = 5%
    inp_fcf = ValuationInput(
        listing_id="0700_HK",
        valuation_at=now,
        metric_name="fcf_yield",
        metric_basis="NON_IFRS_MANAGEMENT",
        numerator_value=3500000.0,
        numerator_currency="HKD",
        numerator_ref="mcap:0700_HK_20260821",
        denominator_value=175000.0,
        denominator_currency="HKD",
        denominator_ref="actual:0700_HK_ttm_fcf",
        source_id="valuation_engine",
        percentile_history_status="unavailable",
    )
    row_fcf = build_valuation_snapshot_row(inp_fcf)
    assert row_fcf["ratio_value"] == pytest.approx(0.05)

    # Shareholder cash return yield (Dividends + Buybacks / Market Cap)
    inp_sh = ValuationInput(
        listing_id="0700_HK",
        valuation_at=now,
        metric_name="shareholder_cash_return_yield",
        metric_basis="GAAP_REPORTED",
        numerator_value=3500000.0,
        numerator_currency="HKD",
        numerator_ref="mcap:0700_HK_20260821",
        denominator_value=140000.0,
        denominator_currency="HKD",
        denominator_ref="corp_actions:0700_HK_ttm_cash_return",
        source_id="valuation_engine",
        percentile_history_status="unavailable",
    )
    row_sh = build_valuation_snapshot_row(inp_sh)
    assert row_sh["ratio_value"] == pytest.approx(0.04)


def test_fail_closed_on_missing_fx_or_currency_mismatch():
    """Validation must fail if currencies differ without valid FX parameters."""
    now = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="Currencies differ"):
        build_valuation_snapshot_row(
            ValuationInput(
                listing_id="0700_HK",
                valuation_at=now,
                metric_name="forward_pe",
                metric_basis="NON_IFRS_MANAGEMENT",
                numerator_value=380.0,
                numerator_currency="HKD",
                numerator_ref="quote:0700_HK",
                denominator_value=25.0,
                denominator_currency="CNY",  # mismatch without fx_rate_applied
                denominator_ref="consensus:0700_HK_eps",
            )
        )


def test_fail_closed_on_invalid_percentile_or_unsupported_metrics():
    """Validator must reject invalid metric names or non-unavailable percentile status."""
    now = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="Unsupported metric_name"):
        build_valuation_snapshot_row(
            ValuationInput(
                listing_id="0700_HK",
                valuation_at=now,
                metric_name="ps_ratio",  # not supported in core contract
                metric_basis="GAAP_REPORTED",
                numerator_value=380.0,
                numerator_currency="HKD",
                numerator_ref="q1",
                denominator_value=25.0,
                denominator_currency="HKD",
                denominator_ref="d1",
            )
        )

    # Test validator flagging percentile status
    valid_row = build_valuation_snapshot_row(
        ValuationInput(
            listing_id="0700_HK",
            valuation_at=now,
            metric_name="forward_pe",
            metric_basis="GAAP_REPORTED",
            numerator_value=380.0,
            numerator_currency="HKD",
            numerator_ref="q1",
            denominator_value=25.0,
            denominator_currency="HKD",
            denominator_ref="d1",
        )
    )
    df_invalid_percentile = pd.DataFrame([valid_row])
    df_invalid_percentile["percentile_history_status"] = "available"  # illegal without vintage history
    issues = validate_valuation_snapshots_df(df_invalid_percentile)
    assert any("percentile_history_status must be 'unavailable'" in msg for msg in issues)


def test_internal_estimates_loading_and_validation(tmp_path: Path):
    """Test internal estimates CSV loading, schema validation, and isolation from consensus."""
    csv_file = tmp_path / "internal_estimates.csv"
    csv_content = """estimate_id,version,supersedes_estimate_id,entity_id,listing_id,observation_type,author,metric,accounting_basis,metric_basis,fiscal_period,fiscal_year,value_low,value_high,value_mid,currency,unit,effective_asof,recorded_at_utc,rationale_notes,source_ref,source_url,pit_class,reviewed_at_utc,reviewed_by
EST_001,1,,TENCENT,0700_HK,management_guidance,company_management,shareholder_cash_return,IFRS,NON_IFRS_MANAGEMENT,FY2026,2026,100000000000,,100000000000,HKD,count,2026-03-20,2026-03-20T10:00:00Z,Management FY26 buyback commitment >=100B HKD,tencent_fy25_results_call,,snapshot_from_live_source,2026-03-21T00:00:00Z,analyst_1
EST_002,1,,TENCENT,0700_HK,internal_estimate,research_analyst,operating_profit,IFRS,NON_IFRS_MANAGEMENT,FY2026,2026,260000000000,280000000000,270000000000,CNY,count,2026-08-20,2026-08-20T15:00:00Z,Internal model base case,model_v2_6,,not_pit,2026-08-20T16:00:00Z,lead_pm
"""
    csv_file.write_text(csv_content, encoding="utf-8")

    df = load_internal_estimates_csv(csv_file)
    assert len(df) == 2
    assert list(df.columns) == INTERNAL_ESTIMATES_COLUMNS
    assert df.iloc[0]["observation_type"] == "management_guidance"
    assert df.iloc[1]["observation_type"] == "internal_estimate"
    assert df.iloc[0]["pit_class"] == "snapshot_from_live_source"
    assert df.iloc[1]["pit_class"] == "not_pit"

    issues = validate_internal_estimates_df(df)
    assert not issues


def test_internal_estimates_fail_closed_on_invalid_data():
    """Test that invalid observation_type or missing values trigger validation errors."""
    bad_df = pd.DataFrame([
        {
            "estimate_id": "EST_BAD",
            "version": "1",
            "supersedes_estimate_id": None,
            "entity_id": "TENCENT",
            "listing_id": "0700_HK",
            "observation_type": "third_party_consensus",  # ILLEGAL: must stay separate from consensus!
            "author": "analyst",
            "metric": "revenue",
            "accounting_basis": "IFRS",
            "metric_basis": "GAAP_REPORTED",
            "fiscal_period": "FY26",
            "fiscal_year": 2026,
            "value_low": None,
            "value_high": None,
            "value_mid": None,  # All values null is illegal
            "currency": "CNY",
            "unit": "count",
            "effective_asof": "2026-08-21",
            "recorded_at_utc": "2026-08-21T00:00:00Z",
            "rationale_notes": "test",
            "source_ref": "",  # Empty source ref is illegal
            "source_url": None,
            "pit_class": "not_pit",
            "reviewed_at_utc": None,
            "reviewed_by": None,
        }
    ])
    issues = validate_internal_estimates_df(bad_df)
    assert any("invalid observation_type" in msg for msg in issues)
    assert any("at least one of value_low, value_high, value_mid must be provided" in msg for msg in issues)
    assert any("source_ref must not be empty" in msg for msg in issues)

