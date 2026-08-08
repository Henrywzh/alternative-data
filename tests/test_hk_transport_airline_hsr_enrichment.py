import pandas as pd
import numpy as np

from src.hk_transport.sources.airline_hsr_enrichment import (
    build_airline_hsr_query_queue,
    calculate_ask_weighted_exposure,
    calculate_hsr_substitution_score,
    enrich_osrm_access_times,
    fetch_ctrip_train_snapshot,
    fetch_osrm_driving_duration,
    get_pinyin_for_city,
    run_airline_hsr_enrichment_pipeline,
    split_route_legs,
    summarize_ctrip_route_observations,
)


def test_split_route_legs_handles_multileg_routes():
    assert split_route_legs('上海虹桥=兰州=阿勒泰') == [('上海虹桥', '兰州'), ('兰州', '阿勒泰')]
    assert split_route_legs('广州—池州—沈阳') == [('广州', '池州'), ('池州', '沈阳')]


def test_get_pinyin_for_city_maps_hubs_correctly():
    assert get_pinyin_for_city('上海') == 'shanghai'
    assert get_pinyin_for_city('上海虹桥') == 'shanghai'
    assert get_pinyin_for_city('上海浦东') == 'shanghai'
    assert get_pinyin_for_city('济南') == 'jinan'
    assert get_pinyin_for_city('大连') == 'dalian'
    assert get_pinyin_for_city('烟台') == 'yantai'


def test_query_queue_includes_pinyin_columns_and_keeps_rail_fields_blank():
    candidates = pd.DataFrame(
        [
            {
                'as_of_date': '2026-08-07',
                'company': 'China Eastern Airlines',
                'ticker': '600115.SH',
                'event_month': '2025-09',
                'route_text': '上海浦东—济南',
                'route_scope': 'domestic',
                'screening_bucket': 'hsr_enrichment_candidate',
                'airline_source_url': 'https://example.com/airline.pdf',
                'airline_source_quality': 'issuer_cninfo_operating_release',
                'retrieved_at': '2026-08-07',
            },
        ]
    )
    queue = build_airline_hsr_query_queue(candidates)
    assert len(queue) == 1
    assert queue.iloc[0]['origin_pinyin'] == 'shanghai'
    assert 'operating_entity' in queue.columns
    assert 'parent_group' in queue.columns
    assert queue.iloc[0]['destination_pinyin'] == 'jinan'


def test_station_dictionary_fixture_shape(monkeypatch):
    from src.hk_transport.sources import airline_hsr_enrichment as module

    class FakeResponse:
        text = "var station_names ='@abc|上海虹桥|AOH|shanghaihongqiao|x';"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(module.requests, 'get', lambda *args, **kwargs: FakeResponse())
    result = module.fetch_12306_station_codes()
    assert result.iloc[0]['station_name'] == '上海虹桥'
    assert result.iloc[0]['telecode'] == 'AOH'


def test_ctrip_snapshot_parses_ssr_state(monkeypatch, tmp_path):
    import json
    from src.hk_transport.sources import airline_hsr_enrichment as module

    payload = {
        'props': {
            'pageProps': {
                'initialState': {
                    'dDate': '2026-08-15',
                    'trainSearchInfo': {
                        'trainInfoList': [
                            {
                                'trainNumber': 'G1305',
                                'runTime': 448,
                                'departureTime': '06:51',
                                'arrivalTime': '14:19',
                                'departureStationName': '上海南',
                                'arrivalStationName': '广州新塘',
                                'seatItemInfoList': [
                                    {'seatName': '二等座', 'seatPrice': 843},
                                    {'seatName': '一等座', 'seatPrice': 1345},
                                ],
                            }
                        ]
                    },
                }
            }
        }
    }

    class FakeResponse:
        text = f'<script id=" __NEXT_DATA__" type="application/json">{json.dumps(payload, ensure_ascii=False)}</script>'.replace(' __NEXT_DATA__', '__NEXT_DATA__')

        def raise_for_status(self):
            return None

    monkeypatch.setattr(module.requests, 'get', lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(module, 'CTRIP_TRAIN_SNAPSHOT_PATH', tmp_path / 'snapshot.csv')
    result = fetch_ctrip_train_snapshot('shanghai', 'guangzhou', '2026-08-15')
    assert result.iloc[0]['train_number'] == 'G1305'
    assert result.iloc[0]['run_time_minutes'] == 448
    assert result.iloc[0]['second_class_fare_rmb'] == 843


def test_ctrip_snapshot_persists_zero_trains_negative_observation(monkeypatch, tmp_path):
    import json
    from src.hk_transport.sources import airline_hsr_enrichment as module

    payload = {
        'props': {
            'pageProps': {
                'initialState': {
                    'dDate': '2026-08-15',
                    'trainSearchInfo': {
                        'trainInfoList': []  # 0 trains returned
                    },
                }
            }
        }
    }

    class FakeResponse:
        text = f'<script id=" __NEXT_DATA__" type="application/json">{json.dumps(payload, ensure_ascii=False)}</script>'.replace(' __NEXT_DATA__', '__NEXT_DATA__')

        def raise_for_status(self):
            return None

    monkeypatch.setattr(module.requests, 'get', lambda *args, **kwargs: FakeResponse())
    snapshot_path = tmp_path / 'snapshot_zero.csv'
    monkeypatch.setattr(module, 'CTRIP_TRAIN_SNAPSHOT_PATH', snapshot_path)

    result = fetch_ctrip_train_snapshot('dalian', 'yantai', '2026-08-15')
    assert len(result) == 1
    assert result.iloc[0]['train_number'] == 'NO_DIRECT_TRAIN'
    assert result.iloc[0]['source_quality'] == 'ctrip_ssr_zero_trains'

    # Summarizer check
    queue = pd.DataFrame([
        {
            'as_of_date': '2026-08-07',
            'company': 'Spring Airlines',
            'ticker': '601021.SH',
            'route_text': '大连=烟台',
            'route_scope': 'domestic',
            'origin_name': '大连',
            'destination_name': '烟台',
            'source_url': 'https://example.com',
            'source_quality': 'cninfo',
            'retrieved_at': '2026-08-07',
        }
    ])
    summary = summarize_ctrip_route_observations(snapshots=result, queue=queue)
    assert len(summary) == 1
    row = summary.iloc[0]
    assert row['route_observation_status'] == 'no_direct_train_result'
    assert row['train_count'] == 0
    assert row['gd_train_count'] == 0


def test_summarize_ctrip_route_observations_preserves_station_scope():
    snapshots = pd.DataFrame([
        {
            'observation_date': '2026-08-15',
            'origin_pinyin': 'shanghai',
            'destination_pinyin': 'guangzhou',
            'train_number': 'G1305',
            'train_class': 'G',
            'run_time_minutes': 448,
            'departure_station_name': '上海虹桥',
            'arrival_station_name': '广州南',
            'second_class_fare_rmb': 843,
            'source_url': 'https://trains.ctrip.com/search',
        },
        {
            'observation_date': '2026-08-15',
            'origin_pinyin': 'shanghai',
            'destination_pinyin': 'guangzhou',
            'train_number': 'G3073',
            'train_class': 'G',
            'run_time_minutes': 492,
            'departure_station_name': '上海虹桥',
            'arrival_station_name': '广州南',
            'second_class_fare_rmb': 864,
            'source_url': 'https://trains.ctrip.com/search',
        }
    ])
    queue = pd.DataFrame([
        {
            'as_of_date': '2026-08-07',
            'company': 'China Eastern Airlines',
            'ticker': '600115.SH',
            'route_text': '上海虹桥—广州',
            'route_scope': 'domestic',
            'origin_name': '上海虹桥',
            'destination_name': '广州',
            'source_url': 'https://example.com',
            'source_quality': 'cninfo',
            'retrieved_at': '2026-08-07',
        }
    ])

    summary = summarize_ctrip_route_observations(snapshots=snapshots, queue=queue)
    assert len(summary) == 1
    row = summary.iloc[0]
    assert row['station_scope'] == 'main_hub_pair'
    assert row['departure_station_scope'] == '上海虹桥'
    assert row['arrival_station_scope'] == '广州南'
    assert row['gd_train_count'] == 2
    assert row['min_run_time_minutes'] == 448.0
    assert row['min_second_class_fare_rmb'] == 843.0
    assert row['fastest_gd_train_number'] == 'G1305'
    assert row['route_observation_status'] == 'verified_snapshot'


def test_osrm_access_time_enrichment_matches_shanghai_guangzhou(monkeypatch):
    df = pd.DataFrame([
        {'origin_name': '上海虹桥', 'destination_name': '广州', 'origin_pinyin': 'shanghai', 'destination_pinyin': 'guangzhou', 'route_scope': 'domestic'},
        {'origin_name': '贵阳', 'destination_name': '常州', 'origin_pinyin': 'guiyang', 'destination_pinyin': 'changzhou', 'route_scope': 'domestic'},
    ])

    def fake_osrm(lon1, lat1, lon2, lat2):
        if lon1 == 121.8052:  # Pudong Airport
            return 50.1, 'http://osrm/pudong'
        else:  # Hongqiao HSR
            return 14.2, 'http://osrm/hongqiao'

    from src.hk_transport.sources import airline_hsr_enrichment as module
    monkeypatch.setattr(module, 'fetch_osrm_driving_duration', fake_osrm)

    live_enriched = enrich_osrm_access_times(df, fetch_live=True)
    row0 = live_enriched.iloc[0]
    assert row0['access_score_status'] == 'osrm_response_derived'
    assert row0['airport_station_access_score'] == round(50.1 - 14.2, 1)


def test_pipeline_matches_dalian_yantai_defensible_geography_score():
    merged = run_airline_hsr_enrichment_pipeline(fetch_live_osrm=False)
    assert not merged.empty

    # Find Dalian to Yantai leg
    dalian_yantai = merged[
        merged['origin_pinyin'].eq('dalian') & merged['destination_pinyin'].eq('yantai')
    ]
    assert len(dalian_yantai) == 1
    row = dalian_yantai.iloc[0]
    assert row['hsr_score_status'] == 'defensible_no_rail_geography'
    assert row['hsr_substitution_score'] == 0.0
    assert row['rail_query_status'] == 'no_direct_train_result'
