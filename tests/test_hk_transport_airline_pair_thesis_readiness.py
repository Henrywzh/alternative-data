import pandas as pd
import numpy as np

from src.hk_transport.sources.airline_pair_thesis_readiness import (
    build_airline_pair_thesis_readiness,
)


def test_injected_dataframe_changes_output():
    custom_bridge = pd.DataFrame([
        {
            'company': 'Spring Airlines',
            'market_ticker': '601021.SH',
            'market': 'CN_A',
            'snapshot_date': '2026-08-10',
            'market_cap_usd_mn': 8000.0,
            'fy2026_revenue_avg_usd_mn': 5000.0,
            'fy2026_net_profit_avg_usd_mn': 500.0,
            'consensus_valuation_quality': 'profit_based_multiple_usable',
        }
    ])

    result = build_airline_pair_thesis_readiness(bridge=custom_bridge)
    spring_row = result[result['operating_entity'].eq('Spring Airlines')].iloc[0]

    assert spring_row['market_cap_usd_mn'] == 8000.0
    assert spring_row['consensus_revenue_fy2026_usd_mn'] == 5000.0
    assert spring_row['consensus_net_margin_fy2026_pct'] == 10.0  # (500 / 5000) * 100
    assert spring_row['consensus_status'] == 'consensus_data_available'


def test_missing_bridge_and_risk_sets_nan_and_pending_status():
    empty_bridge = pd.DataFrame()
    empty_risk = pd.DataFrame()

    result = build_airline_pair_thesis_readiness(bridge=empty_bridge, risk=empty_risk)
    spring_row = result[result['operating_entity'].eq('Spring Airlines')].iloc[0]

    assert pd.isna(spring_row['consensus_revenue_fy2026_usd_mn'])
    assert pd.isna(spring_row['consensus_net_margin_fy2026_pct'])
    assert spring_row['consensus_status'] == 'pending_consensus_data'

    assert pd.isna(spring_row['beta_to_benchmark'])
    assert pd.isna(spring_row['annualized_volatility_pct'])
    assert spring_row['risk_status'] == 'pending_risk_metrics'


def test_dynamic_as_of_date_derivation():
    custom_fundamentals = pd.DataFrame([
        {
            'as_of_date': '2026-09-20',
            'company': 'Spring Airlines',
            'ticker': '601021.SH',
            'parent_group': 'Spring Airlines',
            'carrier_type': 'low_cost',
            'lcc_or_fsc': 'low_cost',
            'primary_hubs': 'Shanghai Hongqiao',
        }
    ])

    result = build_airline_pair_thesis_readiness(fundamentals=custom_fundamentals)
    assert result['as_of_date'].iloc[0] == '2026-09-20'


def test_airline_pair_thesis_readiness_non_directional_and_scope():
    result = build_airline_pair_thesis_readiness()
    assert len(result) == 3

    # Operating entities
    entities = set(result['operating_entity'].unique())
    assert 'Spring Airlines' in entities
    assert 'Juneyao Airlines Mainline' in entities
    assert '9 Air' in entities

    # Non-directional readiness check
    for _, row in result.iterrows():
        assert 'non_directional' in row['readiness_status'] or 'pending' in row['readiness_status']
        assert 'Non-directional' in row['source_note']

    # 9 Air row check: unlisted subsidiary consensus should be NaN
    row_9air = result[result['operating_entity'].eq('9 Air')].iloc[0]
    assert pd.isna(row_9air['consensus_revenue_fy2026_usd_mn'])
    assert row_9air['consensus_status'] == 'not_applicable_unlisted_subsidiary'
    assert 'Primary source conflict detected' in row_9air['seat_conflict_details']
    assert row_9air['risk_scope'] == 'parent_listed_security_proxy'
    assert row_9air['variant_perception_evidence_status'] == 'modelled_hypothesis_pending_market_test'
    assert 'complete_official_actuals_and_consensus' not in set(result['source_as_of_completeness'])
    assert 'source_url' in result.columns or 'fundamentals_source_url' in result.columns


def test_expectation_bridge_freshness_and_dispersion_are_preserved():
    result = build_airline_pair_thesis_readiness()
    spring = result[result['operating_entity'].eq('Spring Airlines')].iloc[0]
    juneyao = result[result['operating_entity'].eq('Juneyao Airlines Mainline')].iloc[0]

    assert spring['fy2026_revenue_analyst_count'] == 12.0
    assert spring['revenue_consensus_freshness'] == 'fresh'
    assert juneyao['fy2026_revenue_analyst_count'] == 1.0
    assert juneyao['profit_consensus_freshness'] == 'stale'
    assert juneyao['formal_report_scheduled_date'] == '2026-08-31'
