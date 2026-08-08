from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_consensus_dispersion import (
    build_airline_consensus_dispersion,
)


def test_consensus_dispersion_flags_sign_disagreement_and_keeps_freshness() -> None:
    market = pd.DataFrame(
        {
            "ticker": ["0753.HK", "601111.SH"],
            "company": ["Air China", "Air China"],
            "snapshot_date": ["2026-08-06", "2026-08-06"],
            "market_cap_usd_mn": [11000.0, 18000.0],
            "fy2026_net_profit_avg_usd_mn": [-332.0, 40.0],
            "fy2026_revenue_avg_usd_mn": [28820.0, 28820.0],
            "consensus_source_quality": ["hk_discovery", "ashare_discovery"],
        }
    )
    bridge = pd.DataFrame(
        {
            "market_ticker": ["0753.HK", "601111.SH"],
            "hk_broker_latest_report_date": ["2026-07-06", None],
            "hk_broker_consensus_as_of_date": ["2026-07-06", None],
            "profit_consensus_latest_observation_date": [None, "2026-07-21"],
            "hk_broker_consensus_age_days": [32, None],
            "profit_consensus_age_days": [None, 16],
            "hk_broker_consensus_freshness_band": ["recent", None],
            "profit_consensus_freshness_band": [None, "recent"],
            "revenue_consensus_age_days": [0, 0],
            "revenue_consensus_freshness_band": ["fresh", "fresh"],
        }
    )
    eps_revisions = pd.DataFrame(
        {
            "company": ["Air China", "Air China"],
            "fiscal_year": [2026, 2026],
            "report_date": ["2026-05-01", "2026-05-05"],
            "prior_report_date": ["2026-04-01", "2026-05-01"],
            "eps_change_pct": [-10.0, 5.0],
        }
    )
    revenue_revisions = pd.DataFrame(
        {
            "company": ["Air China"],
            "fiscal_year": [2026],
            "report_date": ["2026-05-05"],
            "prior_report_date": ["2026-04-01"],
            "revenue_change_pct": [2.0],
        }
    )
    events = pd.DataFrame(
        {
            "company": ["Air China"],
            "event_type": ["earnings_warning"],
            "event_date": ["2026-07-14"],
        }
    )

    result = build_airline_consensus_dispersion(
        market_expectations=market,
        bridge=bridge,
        events=events,
        eps_revisions=eps_revisions,
        revenue_revisions=revenue_revisions,
        retrieved_at="2026-08-07T00:00:00+00:00",
    )
    row = result.iloc[0]
    assert len(result) == 1
    assert row["profit_gap_a_minus_hk_usd_mn"] == 372.0
    assert row["profit_sign_disagreement"] == True
    assert row["hk_profit_freshness_band"] == "recent"
    assert row["a_profit_freshness_band"] == "recent"
    assert row["latest_h1_warning_date"] == "2026-07-14"
    assert row["hk_profit_forecast_pre_warning"] == True
    assert row["a_profit_forecast_pre_warning"] == False
    assert row["forecast_warning_alignment"] == "hk_pre_warning_a_post_warning"
    assert row["eps_revision_count"] == 2
    assert row["eps_positive_revision_count"] == 1
    assert row["eps_negative_revision_count"] == 1
    assert row["revenue_revision_count"] == 1
    assert "profit_sign_disagreement" in row["vintage_status"]
    assert "asynchronous_profit_observation_dates" in row["vintage_status"]
