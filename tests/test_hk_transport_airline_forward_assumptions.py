from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_forward_assumptions import (
    CURATED_FY2025_TAX_ANCHORS,
    build_airline_forward_assumptions,
)


def _official() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "company": "China Southern Airlines",
                "statement_period": "FY2025",
                "metric": "profit_total",
                "value_native": 4_811.0,
            },
            {
                "company": "China Southern Airlines",
                "statement_period": "FY2025",
                "metric": "income_tax_expense",
                "value_native": 2_126.0,
            },
            {
                "company": "Air China",
                "statement_period": "FY2025",
                "metric": "profit_total",
                "value_native": -1_596.707,
            },
            {
                "company": "Air China",
                "statement_period": "FY2025",
                "metric": "income_tax_expense",
                "value_native": 1_928.119,
            },
            {
                "company": "Spring Airlines",
                "statement_period": "FY2025",
                "metric": "profit_total",
                "value_native": 3_030.254828,
            },
        ]
    )


def _fx() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "pair": "USD_CNY",
                "observation_date": "2026-08-07",
                "value": 6.747638,
            }
        ]
    )


def test_forward_assumptions_use_curated_anchors_and_flag_reversal_cases(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "src.hk_transport.sources.airline_forward_assumptions.OUTPUT_PATH",
        tmp_path / "airline_forward_assumptions.csv",
    )
    result = build_airline_forward_assumptions(
        official=_official(),
        fx=_fx(),
        retrieved_at="2026-08-09T00:00:00+00:00",
    )

    southern = result[result["company"].eq("China Southern Airlines")].iloc[0]
    assert southern["fy2025_effective_tax_rate_pct"] == pytest.approx(44.190397)
    assert southern["tax_assumption_status"] == "fy2025_effective_tax_rate_carry"
    assert southern["forward_fx_usd_cny"] == pytest.approx(6.747638)

    air_china = result[result["company"].eq("Air China")].iloc[0]
    assert air_china["tax_assumption_status"] == "loss_with_reversal_tax_absolute_carry_required"
    assert pd.isna(air_china["fy2025_effective_tax_rate_pct"])

    spring = result[result["company"].eq("Spring Airlines")].iloc[0]
    assert spring["fy2025_income_tax_expense_native_mn"] == pytest.approx(712.853155)
    assert spring["income_tax_source_page"] == 25
    assert spring["fy2025_effective_tax_rate_pct"] == pytest.approx(23.524528)
    assert "Spring Airlines" in CURATED_FY2025_TAX_ANCHORS


def test_forward_assumptions_flag_extreme_rates_from_deferred_tax() -> None:
    official = pd.DataFrame(
        [
            {
                "company": "China Eastern Airlines",
                "statement_period": "FY2025",
                "metric": "profit_total",
                "value_native": 274.0,
            },
            {
                "company": "China Eastern Airlines",
                "statement_period": "FY2025",
                "metric": "income_tax_expense",
                "value_native": 1_907.0,
            },
        ]
    )
    result = build_airline_forward_assumptions(
        official=official,
        fx=_fx(),
        retrieved_at="2026-08-09T00:00:00+00:00",
    )
    eastern = result[result["company"].eq("China Eastern Airlines")].iloc[0]
    assert (
        eastern["tax_assumption_status"]
        == "extreme_rate_deferred_tax_effects_absolute_carry_required"
    )
    assert eastern["fy2025_effective_tax_rate_pct"] is None
