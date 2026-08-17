from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_h1_2026_validation_playbook import (
    build_airline_h1_2026_validation_playbook,
)


def _expectations() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "company": "Spring Airlines",
                "h1_ask_yoy_pct": 15.3,
                "h1_rpk_yoy_pct": 18.0,
                "h1_passengers_yoy_pct": 14.1,
                "h1_passenger_lf_change_pp": 2.0,
                "h1_cargo_tonnes_yoy_pct": 22.5,
            }
        ]
    )


def _calendar() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "company": "Spring Airlines",
                "statement_period": "1H2026",
                "first_scheduled_date": "2026-08-29",
                "actual_disclosure_date": None,
                "calendar_status": "scheduled",
            }
        ]
    )


def _cargo_yield() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "company": "Spring Airlines",
                "h1_2026_cargo_revenue_bridge_native_mn": 194.0,
                "revenue_anchor_period": "FY2025",
            }
        ]
    )


def _v3() -> pd.DataFrame:
    rows = []
    for scenario in ("bear", "base", "bull"):
        rows.append(
            {
                "company": "Spring Airlines",
                "scenario": scenario,
                "v3_revenue_usd_mn": 3_500.0,
                "v3_net_profit_proxy_usd_mn": {
                    "bear": 260.0,
                    "base": 390.0,
                    "bull": 480.0,
                }[scenario],
                "v3_basic_eps_proxy_rmb_per_share": 2.8,
                "consensus_fy2026_profit_usd_mn": 315.0,
                "v3_net_profit_consensus_guarded_usd_mn": 390.0,
                "net_income_leg": "residual_bridge",
                "regime_flip_flag": False,
            }
        )
    return pd.DataFrame(rows)


def test_playbook_consolidates_forecasts_and_marks_awaiting_status(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "src.hk_transport.sources.airline_h1_2026_validation_playbook.OUTPUT_PATH",
        tmp_path / "airline_h1_2026_validation_playbook.csv",
    )
    result = build_airline_h1_2026_validation_playbook(
        expectations=_expectations(),
        calendar=_calendar(),
        cargo_yield=_cargo_yield(),
        v3=_v3(),
        retrieved_at="2026-08-09T00:00:00+00:00",
    )

    row = result.iloc[0]
    assert row["company"] == "Spring Airlines"
    assert row["filing_scheduled_date"] == "2026-08-29"
    assert row["h1_2026_rpk_yoy_pct"] == pytest.approx(18.0)
    assert row["h1_2026_cargo_revenue_bridge_native_mn"] == pytest.approx(194.0)
    assert row["fy2026_v3_base_net_profit_usd_mn"] == pytest.approx(390.0)
    assert row["fy2026_v3_bear_net_profit_usd_mn"] == pytest.approx(260.0)
    assert row["fy2026_v3_bull_net_profit_usd_mn"] == pytest.approx(480.0)
    assert row["consensus_fy2026_profit_usd_mn"] == pytest.approx(315.0)
    assert row["v3_base_vs_consensus_profit_gap_pct"] == pytest.approx(23.8095238)
    assert row["validation_status"] == "awaiting_h1_2026_report"
    assert row["fy2026_v3_base_net_profit_consensus_guarded_usd_mn"] == pytest.approx(390.0)
    assert row["net_income_leg"] == "residual_bridge"
    assert bool(row["regime_flip_flag"]) is False
