import pandas as pd
import numpy as np

from src.hk_transport.sources.airline_route_capacity import (
    build_airline_route_capacity_weights,
    get_fleet_seats_per_flight,
    haversine_distance_km,
    parse_disclosed_weekly_frequency,
)
from src.hk_transport.sources.airline_hsr_enrichment import (
    calculate_ask_weighted_exposure,
)


def test_parse_disclosed_weekly_frequency():
    freq1, status1 = parse_disclosed_weekly_frequency('周246')
    assert freq1 == 3.0
    assert status1 == 'disclosed_weekly_schedule_days'

    freq2, status2 = parse_disclosed_weekly_frequency('天天班')
    assert freq2 == 7.0
    assert status2 == 'disclosed_daily_schedule'

    freq3, status3 = parse_disclosed_weekly_frequency('每周4班')
    assert freq3 == 4.0
    assert status3 == 'disclosed_weekly_frequency'

    freq4, status4 = parse_disclosed_weekly_frequency('frequency increase')
    assert freq4 is None
    assert status4 == 'qualitative_frequency_increase'


def test_get_fleet_seats_per_flight_strict_operator_attribution_and_conflict_handling():
    # Spring Airlines has explicit disclosed 186-seat single-class A320 layout
    spring_meta = get_fleet_seats_per_flight('Spring Airlines')
    assert spring_meta['seats_operational_proxy'] == 186.0
    assert spring_meta['seats_scenario_189'] == 186.0
    assert 'spring_annual_report' in spring_meta['seats_source_quality']
    assert 'cninfo' in spring_meta['seats_operational_source_url']
    assert spring_meta['seats_operational_source_date'] == '2026-04-11'
    assert spring_meta['conflict_note'] is None

    # 9 Air has conflict: 188 operational seats (live 9air.com 2026-05-26) vs 189 series limit (Juneyao FY2025 Annual Report Page 15 2026-04-23)
    nineair_meta = get_fleet_seats_per_flight('9 Air')
    assert nineair_meta['seats_operational_proxy'] == 188.0
    assert nineair_meta['seats_scenario_189'] == 189.0
    assert nineair_meta['seats_source_quality'] == '9air_official_website_188_seats_with_annual_report_189_conflict'
    assert nineair_meta['seats_operational_source_url'] == 'https://www.9air.com/cmsProvider/info/1011/1431.htm'
    assert nineair_meta['seats_operational_source_date'] == '2026-05-26'
    assert nineair_meta['seats_scenario_source_url'] == 'https://static.cninfo.com.cn/finalpage/2026-04-23/1225151299.PDF'
    assert nineair_meta['seats_scenario_source_date'] == '2026-04-23'
    assert nineair_meta['conflict_note'] is not None
    assert 'Primary source conflict detected' in nineair_meta['conflict_note']

    # Juneyao Airlines Mainline has 180-seat layout
    jy_meta = get_fleet_seats_per_flight('Juneyao Airlines Mainline')
    assert jy_meta['seats_operational_proxy'] == 180.0
    assert jy_meta['seats_scenario_189'] == 180.0
    assert 'juneyao_annual_report' in jy_meta['seats_source_quality']

    # Eastern and Southern MUST NOT use unverified benchmark seats
    ce_meta = get_fleet_seats_per_flight('China Eastern Airlines')
    assert ce_meta['seats_operational_proxy'] is None
    assert ce_meta['seats_scenario_189'] is None
    assert ce_meta['seats_source_quality'] == 'pending_route_aircraft_configuration'


def test_haversine_distance_km():
    dist = haversine_distance_km(121.4737, 31.2304, 113.2644, 23.1291)
    assert 1200.0 < dist < 1220.0


def test_build_airline_route_capacity_weights_9air_attribution_and_scenarios():
    df = build_airline_route_capacity_weights()
    assert not df.empty
    assert 'operating_entity' in df.columns
    assert 'parent_group' in df.columns
    assert 'seats_operational_source_date' in df.columns
    assert 'seats_scenario_source_date' in df.columns

    # 9 Air route check (Guiyang - Changzhou)
    nine_air = df[df['operating_entity'].eq('9 Air')]
    assert not nine_air.empty
    for _, row in nine_air.iterrows():
        assert row['parent_group'] == 'Juneyao Airlines'
        assert row['seats_per_flight'] == 188.0
        assert row['seats_per_flight_scenario_189'] == 189.0
        assert row['seats_operational_source_url'] == 'https://www.9air.com/cmsProvider/info/1011/1431.htm'
        assert row['seats_operational_source_date'] == '2026-05-26'
        assert row['seats_scenario_source_url'] == 'https://static.cninfo.com.cn/finalpage/2026-04-23/1225151299.PDF'
        assert row['seats_scenario_source_date'] == '2026-04-23'
        assert row['weekly_ask_proxy_thousand'] > 0
        assert row['weekly_ask_proxy_scenario_189_thousand'] > row['weekly_ask_proxy_thousand']
        assert row['route_capacity_status'] == 'frequency_disclosed_proxy_conflicted_seats'
        assert 'Primary source conflict detected' in row['seats_conflict_note']


def test_calculate_ask_weighted_exposure_prevents_multi_operator_route_collision():
    df_queue = pd.DataFrame([
        {
            'operating_entity': 'Spring Airlines',
            'company': 'Spring Airlines',
            'origin_pinyin': 'shanghai',
            'destination_pinyin': 'guangzhou',
            'hsr_substitution_score': 0.50,
        },
        {
            'operating_entity': 'China Eastern Airlines',
            'company': 'China Eastern Airlines',
            'origin_pinyin': 'shanghai',
            'destination_pinyin': 'guangzhou',
            'hsr_substitution_score': 0.50,
        },
        {
            'operating_entity': 'Unknown Air',
            'company': 'Unknown Group',
            'origin_pinyin': 'shanghai',
            'destination_pinyin': 'guangzhou',
            'hsr_substitution_score': 0.50,
        }
    ])

    df_capacity = pd.DataFrame([
        {
            'operating_entity': 'Spring Airlines',
            'company': 'Spring Airlines',
            'origin_pinyin': 'shanghai',
            'destination_pinyin': 'guangzhou',
            'weekly_ask_proxy_thousand': 2000.0,
            'route_capacity_status': 'frequency_disclosed_proxy',
        },
        {
            'operating_entity': 'China Eastern Airlines',
            'company': 'China Eastern Airlines',
            'origin_pinyin': 'shanghai',
            'destination_pinyin': 'guangzhou',
            'weekly_ask_proxy_thousand': None,
            'route_capacity_status': 'qualitative_frequency_only',
        }
    ])

    result = calculate_ask_weighted_exposure(df_queue, capacity_weights=df_capacity)

    row_spring = result.iloc[0]
    assert row_spring['operating_entity'] == 'Spring Airlines'
    assert row_spring['hsr_ask_exposure_status'] == 'modelled_route_ask_proxy'
    assert row_spring['hsr_ask_weighted_exposure'] == 1000.0

    row_ce = result.iloc[1]
    assert row_ce['operating_entity'] == 'China Eastern Airlines'
    assert row_ce['hsr_ask_exposure_status'] == 'pending_route_ask_weights'
    assert pd.isna(row_ce['hsr_ask_weighted_exposure'])

    row_unk = result.iloc[2]
    assert row_unk['operating_entity'] == 'Unknown Air'
    assert row_unk['hsr_ask_exposure_status'] == 'pending_route_ask_weights'
    assert pd.isna(row_unk['hsr_ask_weighted_exposure'])
