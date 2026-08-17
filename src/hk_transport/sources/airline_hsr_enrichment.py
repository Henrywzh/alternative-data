"""Build a point-in-time query queue for airline route versus HSR enrichment.

This module provides a reproducible route-observation summarizer, explicit OSRM
access latency enrichment (derived from response data), diagnostic HSR substitution scoring,
and ASK exposure safeguards.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from bs4 import BeautifulSoup
import numpy as np
import pandas as pd
import requests

from ..config import NORMALIZED_DIR


CANDIDATE_PATH = NORMALIZED_DIR / 'airline_hsr_route_candidates.csv'
CAAC_LICENCE_PATH = NORMALIZED_DIR / 'airline_caac_route_licence_events.csv'
QUEUE_PATH = NORMALIZED_DIR / 'airline_hsr_route_query_queue.csv'
STATION_CODES_URL = 'https://kyfw.12306.cn/otn/resources/js/framework/station_name.js'
STATION_CODES_PATH = NORMALIZED_DIR / 'airline_hsr_station_codes.csv'
CTRIP_TRAIN_SNAPSHOT_PATH = NORMALIZED_DIR / 'airline_hsr_train_snapshots.csv'
OBSERVATION_PATH = NORMALIZED_DIR / 'airline_hsr_route_observations.csv'
CTRIP_TRAIN_URL = 'https://trains.ctrip.com/trainbooking/search'
OSRM_BASE_URL = 'http://router.project-osrm.org/route/v1/driving'
ROUTE_SPLIT_RE = re.compile(r'\s*(?:=|—|–|->|→)\s*')

# CAAC new-route licence records are emitted with plain hyphen separators
# (e.g. "南京-广州"), while the HSR candidate/query layer normalizes every
# route to '=' so split_route_legs() works consistently.  The builder below
# rewrites the separator without changing the city strings.
_CAAC_ROUTE_SEP_RE = re.compile(r'\s*(?:-|—|－|->|→|至)\s*')

# Only these issuer families are tracked at company level by the airline
# research layer; licence rows outside the set are not promoted to candidates.
_TRACKED_CAAC_AIRLINES = {
    'Spring Airlines',
    'Juneyao Airlines',
    '9 Air',
    'China Eastern Airlines',
    'China Southern Airlines',
    'Air China',
    'Hainan Airlines Holdings',
}

_OPERATING_ENTITY_BY_AIRLINE = {
    'Spring Airlines': 'Spring Airlines',
    'Juneyao Airlines': 'Juneyao Airlines',
    '9 Air': '9 Air',
    'China Eastern Airlines': 'China Eastern Airlines',
    'China Southern Airlines': 'China Southern Airlines',
    'Air China': 'Air China',
    'Hainan Airlines Holdings': 'Hainan Airlines Holdings',
}

# Company-level parent (the group the route candidate is attributed to in the
# research layer).  9 Air is a Juneyao-group subsidiary: existing candidate
# rows record company=Juneyao Airlines / operating_entity=9 Air and share
# Juneyao's ticker, so CAAC licence rows for 9 Air are mapped the same way.
_COMPANY_BY_CAAC_AIRLINE = {
    'Spring Airlines': 'Spring Airlines',
    'Juneyao Airlines': 'Juneyao Airlines',
    '9 Air': 'Juneyao Airlines',
    'China Eastern Airlines': 'China Eastern Airlines',
    'China Southern Airlines': 'China Southern Airlines',
    'Air China': 'Air China',
    'Hainan Airlines Holdings': 'Hainan Airlines Holdings',
}

_PARENT_GROUP_BY_CAAC_AIRLINE = {
    'Spring Airlines': 'Spring Airlines',
    'Juneyao Airlines': 'Juneyao Airlines',
    '9 Air': 'Juneyao Airlines',
    'China Eastern Airlines': 'China Eastern Airlines',
    'China Southern Airlines': 'China Southern Airlines',
    'Air China': 'Air China',
    'Hainan Airlines Holdings': 'Hainan Airlines Holdings',
}

_TICKER_BY_AIRLINE = {
    'Spring Airlines': '601021.SH',
    'Juneyao Airlines': '603885.SH',
    '9 Air': '603885.SH',
    'China Eastern Airlines': '600115.SH',
    'China Southern Airlines': '600029.SH',
    'Air China': '601111.SH',
    'Hainan Airlines Holdings': '600221.SH',
}

# Explicit verified OSRM coordinates for hub-to-CBD access score calculations
HUB_COORDINATES: dict[str, dict[str, float]] = {
    'SHANGHAI_HONGQIAO_HSR': {'lon': 121.3202, 'lat': 31.1940},
    'SHANGHAI_PUDONG_AIRPORT': {'lon': 121.8052, 'lat': 31.1434},
    'SHANGHAI_CBD_PEOPLES_SQUARE': {'lon': 121.4737, 'lat': 31.2304},
    'GUANGZHOU_SOUTH_HSR': {'lon': 113.2690, 'lat': 22.9889},
    'GUANGZHOU_BAIYUN_AIRPORT': {'lon': 113.3080, 'lat': 23.3924},
    'GUANGZHOU_CBD_ZHUJIANG': {'lon': 113.3220, 'lat': 23.1190},
}

# Cross-sea or island routes with no direct or indirect rail infrastructure
NO_RAIL_GEOGRAPHY_PAIRS: set[tuple[str, str]] = {
    ('dalian', 'yantai'),
    ('yantai', 'dalian'),
}


def _normalize_caac_route_text(route_text: str) -> str | None:
    """Rewrite CAAC licence route separators to the '=' convention.

    CAAC licence rows use plain hyphens (e.g. "南京-广州") or other dash glyphs;
    the HSR route layer uses '=' and the shared route_leg_splitter only handles
    '='/—/–/->/→.  City strings are preserved; only the separator changes.
    Returns None for single-city or empty routes.
    """
    cities = [part.strip() for part in _CAAC_ROUTE_SEP_RE.split(str(route_text)) if part.strip()]
    if len(cities) < 2:
        return None
    return "=".join(cities)


def build_caac_hsr_candidates(
    licence_events: pd.DataFrame | None = None,
    candidates: pd.DataFrame | None = None,
    *,
    retrieved_at: str | None = None,
    output_path: str | os.PathLike | None = None,
) -> pd.DataFrame:
    """Supplement HSR route candidates from CAAC seasonal new-licence events.

    The CAAC seasonal route-licence table names newly approved domestic
    routes (including stated initial weekly frequency and an official release
    date).  Only the issuer families tracked by the airline research layer are
    promoted, and only records whose route text has at least two cities.  The
    function returns the existing candidate panel with new CAAC rows appended;
    it never drops or edits existing rows.
    """
    candidate_path = Path(output_path) if output_path is not None else CANDIDATE_PATH
    if candidates is None and candidate_path.exists():
        candidates = pd.read_csv(candidate_path)
    if candidates is None:
        candidates = pd.DataFrame()

    if licence_events is None and CAAC_LICENCE_PATH.exists():
        licence_events = pd.read_csv(CAAC_LICENCE_PATH)
    if licence_events is None or licence_events.empty:
        return candidates

    now = retrieved_at or pd.Timestamp.now(tz="UTC").isoformat()
    existing = set(str(value) for value in candidates["route_text"].tolist()) if "route_text" in candidates.columns else set()
    added_rows: list[dict[str, object]] = []

    # The CAAC licence table is a domestic route-licence table; it does not
    # expose a route_scope column, so promotion is not scope-filtered here.
    # Rows with a single city (e.g. the "国内（不含港澳台）货运航线" trailer) are
    # dropped by _normalize_caac_route_text, and any blank/ordinate rows by the
    # frequency/source checks below.
    new_events = licence_events[
        licence_events.get("event_type", pd.Series(index=licence_events.index, dtype=object)).astype(str).eq("新增许可")
    ]
    for _, row in new_events.iterrows():
        airline = str(row.get("airline_normalized_name", "") or "")
        if airline not in _TRACKED_CAAC_AIRLINES:
            continue
        route_text = _normalize_caac_route_text(str(row.get("route_text", "") or ""))
        if route_text is None:
            continue
        if route_text in existing:
            continue
        frequency = row.get("initial_frequency_per_week")
        frequency_text = (
            f"每周{int(frequency)}班"
            if frequency is not None and pd.notna(frequency) and int(frequency) > 0
            else None
        )
        source_url = str(row.get("source_url", "") or "")
        source_quality = str(row.get("source_quality", "") or "caac_primary_route_licence_pdf")
        as_of_date = str(row.get("source_release_date", "") or "")[:10] or now[:10]
        added_rows.append(
            {
                "dataset_id": "airline_hsr_route_candidates",
                "as_of_date": as_of_date,
                "company": _COMPANY_BY_CAAC_AIRLINE.get(airline, airline),
                "operating_entity": _OPERATING_ENTITY_BY_AIRLINE.get(airline, airline),
                "parent_group": _PARENT_GROUP_BY_CAAC_AIRLINE.get(airline, airline),
                "ticker": _TICKER_BY_AIRLINE.get(airline),
                "event_month": as_of_date[:7],
                "route_text": route_text,
                "route_scope": "domestic",
                "screening_bucket": "hsr_enrichment_candidate",
                "airline_frequency_text": frequency_text,
                "airline_source_url": source_url,
                "airline_source_quality": source_quality,
                "rail_time_minutes": None,
                "rail_frequency_per_day": None,
                "rail_fare_rmb": None,
                "airport_station_access_score": None,
                "hsr_substitution_score": None,
                "hsr_score_status": "not_scored",
                "next_enrichment": "12306 route query plus centre-to-centre access and fare capture",
                "source_note": (
                    "CAAC seasonal new-route licence names a new domestic route with stated initial "
                    "frequency; planned licence frequency is not realized flight activity or company ASK."
                ),
                "retrieved_at": now,
            }
        )
        existing.add(route_text)

    if not added_rows:
        return candidates
    if candidates.empty:
        result = pd.DataFrame(added_rows)
    else:
        result = pd.concat([candidates, pd.DataFrame(added_rows)], ignore_index=True)
    result.to_csv(candidate_path, index=False)
    return result


def get_pinyin_for_city(city_name: str) -> str:
    """Map city/station names to standard Ctrip search pinyin."""
    mapping = {
        '上海': 'shanghai',
        '上海虹桥': 'shanghai',
        '上海浦东': 'shanghai',
        '广州': 'guangzhou',
        '济南': 'jinan',
        '大理': 'dali',
        '兰州': 'lanzhou',
        '阿勒泰': 'aletai',
        '大连': 'dalian',
        '烟台': 'yantai',
        '池州': 'chizhou',
        '沈阳': 'shenyang',
        '贵阳': 'guiyang',
        '常州': 'changzhou',
        '武汉': 'wuhan',
        '长春': 'changchun',
        '合肥': 'hefei',
        '海拉尔': 'hailaer',
        '乌鲁木齐': 'wulumuqi',
        '深圳': 'shenzhen',
        '雅加达': 'jakarta',
        '南京': 'nanjing',
        '广州南': 'guangzhounan',
        '无锡': 'wuxi',
        '扬州': 'yangzhou',
        '张掖': 'zhangye',
        '北京': 'beijing',
        '北京大兴': 'daxing',
        '宁波': 'ningbo',
        '嘉兴': 'jiaxing',
        '黄山': 'huangshan',
        '锡林浩特': 'xilinhot',
        '榆林': 'yulin',
        '汉中': 'hanzhong',
        '丽江': 'lijiang',
        '塔城': 'tacheng',
        '库尔勒': 'korla',
        '赣州': 'ganzhou',
    }
    clean_name = city_name.strip()
    return mapping.get(clean_name, clean_name.lower())


def split_route_legs(route_text: str) -> list[tuple[str, str]]:
    """Split an airline route string into adjacent origin/destination legs."""
    parts = [part.strip() for part in ROUTE_SPLIT_RE.split(str(route_text)) if part.strip()]
    return list(zip(parts, parts[1:]))


def build_airline_hsr_query_queue(candidates: pd.DataFrame | None = None) -> pd.DataFrame:
    """Expand route candidates to city-pair legs without inventing rail data."""
    if candidates is None:
        candidates = pd.read_csv(CANDIDATE_PATH)

    rows: list[dict[str, object]] = []
    for candidate_index, candidate in candidates.reset_index(drop=True).iterrows():
        route_scope = str(candidate.get('route_scope', ''))
        legs = split_route_legs(str(candidate.get('route_text', '')))
        if not legs:
            legs = [(str(candidate.get('route_text', '')), '')]

        for leg_index, (origin, destination) in enumerate(legs, start=1):
            not_applicable = route_scope == 'international'
            origin_pinyin = get_pinyin_for_city(origin)
            dest_pinyin = get_pinyin_for_city(destination)
            rows.append(
                {
                    'dataset_id': 'airline_hsr_route_query_queue',
                    'candidate_id': f'{candidate_index:03d}_{leg_index:02d}',
                    'as_of_date': candidate.get('as_of_date'),
                    'company': candidate.get('company'),
                    'operating_entity': candidate.get('operating_entity', candidate.get('company')),
                    'parent_group': candidate.get('parent_group', candidate.get('company')),
                    'ticker': candidate.get('ticker'),
                    'event_month': candidate.get('event_month'),
                    'route_text': candidate.get('route_text'),
                    'route_scope': route_scope,
                    'screening_bucket': candidate.get('screening_bucket'),
                    'route_leg_index': leg_index,
                    'route_leg_count': len(legs),
                    'origin_name': origin,
                    'destination_name': destination,
                    'origin_pinyin': origin_pinyin,
                    'destination_pinyin': dest_pinyin,
                    'origin_telecode': None,
                    'destination_telecode': None,
                    'rail_query_status': 'not_applicable' if not_applicable else 'pending_rail_query',
                    'rail_observation_date': None,
                    'rail_time_minutes': None,
                    'rail_frequency_per_day': None,
                    'rail_fare_rmb': None,
                    'airport_station_access_score': None,
                    'access_score_status': 'not_applicable' if not_applicable else 'pending_access_coordinates',
                    'access_source_url': None,
                    'access_coordinate_lineage': None,
                    'hsr_substitution_score': None,
                    'hsr_score_status': 'not_applicable' if not_applicable else 'pending_rail_query',
                    'hsr_ask_weighted_exposure': None,
                    'hsr_ask_exposure_status': 'pending_route_ask_weights',
                    'source_url': candidate.get('airline_source_url'),
                    'source_quality': candidate.get('airline_source_quality'),
                    'source_note': (
                        'International control; HSR fields are not applicable.'
                        if not_applicable
                        else 'Waiting for dated 12306 station-code and rail-service enrichment; no score implied.'
                    ),
                    'retrieved_at': candidate.get('retrieved_at'),
                }
            )

    result = pd.DataFrame(rows)
    result.to_csv(QUEUE_PATH, index=False)
    return result


def fetch_airline_hsr_query_queue() -> pd.DataFrame:
    """Build and persist the deterministic route-leg enrichment queue."""
    return build_airline_hsr_query_queue()


def fetch_12306_station_codes() -> pd.DataFrame:
    """Fetch the live 12306 station dictionary used by rail query endpoints."""
    response = requests.get(
        STATION_CODES_URL,
        headers={'User-Agent': 'Mozilla/5.0'},
        timeout=30,
    )
    response.raise_for_status()
    match = re.search(r"var station_names\s*=\s*'(?P<body>.*)'\s*;?", response.text)
    if not match:
        raise ValueError('12306 station dictionary response did not contain station_names')

    rows = []
    for item in match.group('body').split('@'):
        fields = item.split('|')
        if len(fields) >= 4 and fields[1] and fields[2]:
            rows.append(
                {
                    'station_name': fields[1],
                    'telecode': fields[2],
                    'pinyin': fields[3],
                    'station_alias': fields[0],
                }
            )
    result = pd.DataFrame(rows).drop_duplicates(subset=['station_name', 'telecode'])
    if result.empty:
        raise ValueError('12306 station dictionary parsed zero stations')
    result.insert(0, 'dataset_id', 'airline_hsr_station_codes')
    result['source_url'] = STATION_CODES_URL
    result['source_quality'] = '12306_live_station_dictionary'
    result['retrieved_at'] = pd.Timestamp.now(tz='UTC').isoformat()
    result.to_csv(STATION_CODES_PATH, index=False)
    return result


def fetch_ctrip_train_snapshot(
    origin_pinyin: str,
    destination_pinyin: str,
    observation_date: str | None = None,
) -> pd.DataFrame:
    """Fetch a dated Ctrip SSR train snapshot and retain train-level fields.

    When Ctrip returns 0 direct trains for the searched date, an explicit negative
    observation row (train_number='NO_DIRECT_TRAIN') is persisted to preserve auditability.
    """
    if observation_date is None:
        observation_date = (date.today() + timedelta(days=1)).isoformat()
    url = (
        f'{CTRIP_TRAIN_URL}?from={origin_pinyin}&to={destination_pinyin}'
        f'&day={observation_date}'
    )
    response = requests.get(
        url,
        headers={'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'zh-CN,zh;q=0.9'},
        timeout=30,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    state_node = soup.find('script', id='__NEXT_DATA__')
    if state_node is None or not state_node.string:
        raise ValueError('Ctrip SSR page did not contain __NEXT_DATA__')

    import json

    state = json.loads(state_node.string)['props']['pageProps']['initialState']
    train_info = state.get('trainSearchInfo', {}).get('trainInfoList', [])
    rows: list[dict[str, object]] = []

    if not train_info:
        rows.append(
            {
                'dataset_id': 'airline_hsr_train_snapshots',
                'observation_date': state.get('dDate') or observation_date,
                'origin_pinyin': origin_pinyin,
                'destination_pinyin': destination_pinyin,
                'train_number': 'NO_DIRECT_TRAIN',
                'train_class': 'NONE',
                'run_time_minutes': None,
                'departure_time': '00:00',
                'arrival_time': '00:00',
                'departure_station_name': 'NONE',
                'arrival_station_name': 'NONE',
                'second_class_fare_rmb': None,
                'first_class_fare_rmb': None,
                'business_class_fare_rmb': None,
                'source_url': url,
                'source_quality': 'ctrip_ssr_zero_trains',
                'retrieved_at': pd.Timestamp.now(tz='UTC').isoformat(),
            }
        )
    else:
        for item in train_info:
            train_number = str(item.get('trainNumber') or '')
            seats = item.get('seatItemInfoList') or []
            seat_prices = {
                str(seat.get('seatName')): seat.get('seatPrice')
                for seat in seats
                if seat.get('seatPrice') is not None
            }
            rows.append(
                {
                    'dataset_id': 'airline_hsr_train_snapshots',
                    'observation_date': state.get('dDate') or observation_date,
                    'origin_pinyin': origin_pinyin,
                    'destination_pinyin': destination_pinyin,
                    'train_number': train_number,
                    'train_class': train_number[:1],
                    'run_time_minutes': item.get('runTime'),
                    'departure_time': item.get('departureTime'),
                    'arrival_time': item.get('arrivalTime'),
                    'departure_station_name': item.get('departureStationName'),
                    'arrival_station_name': item.get('arrivalStationName'),
                    'second_class_fare_rmb': seat_prices.get('二等座'),
                    'first_class_fare_rmb': seat_prices.get('一等座'),
                    'business_class_fare_rmb': seat_prices.get('商务座'),
                    'source_url': url,
                    'source_quality': 'ctrip_ssr_train_state',
                    'retrieved_at': pd.Timestamp.now(tz='UTC').isoformat(),
                }
            )

    result = pd.DataFrame(rows)
    if CTRIP_TRAIN_SNAPSHOT_PATH.exists():
        prior = pd.read_csv(CTRIP_TRAIN_SNAPSHOT_PATH)
        result = pd.concat([prior, result], ignore_index=True)
        result = result.drop_duplicates(
            subset=['observation_date', 'origin_pinyin', 'destination_pinyin', 'train_number', 'departure_time']
        )
    result.to_csv(CTRIP_TRAIN_SNAPSHOT_PATH, index=False)
    return result.loc[
        result['observation_date'].eq(state.get('dDate') or observation_date)
        & result['origin_pinyin'].eq(origin_pinyin)
        & result['destination_pinyin'].eq(destination_pinyin)
    ].reset_index(drop=True)


def fetch_osrm_driving_duration(lon1: float, lat1: float, lon2: float, lat2: float) -> tuple[float | None, str]:
    """Perform real HTTP fetch to OSRM API for driving duration in minutes."""
    url = f'{OSRM_BASE_URL}/{lon1},{lat1};{lon2},{lat2}?overview=false'
    response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
    response.raise_for_status()
    data = response.json()
    routes = data.get('routes', [])
    if not routes:
        return None, url
    duration_seconds = float(routes[0]['duration'])
    return round(duration_seconds / 60.0, 1), url


def summarize_ctrip_route_observations(
    snapshots: pd.DataFrame | None = None,
    queue: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Summarize train-level snapshots into route-leg observations with explicit station scope."""
    if snapshots is None and CTRIP_TRAIN_SNAPSHOT_PATH.exists():
        snapshots = pd.read_csv(CTRIP_TRAIN_SNAPSHOT_PATH)
    if queue is None and QUEUE_PATH.exists():
        queue = pd.read_csv(QUEUE_PATH)

    if queue is None or queue.empty:
        queue = build_airline_hsr_query_queue()

    rows: list[dict[str, object]] = []
    for _, leg in queue.iterrows():
        route_scope = str(leg.get('route_scope', ''))
        origin_name = str(leg.get('origin_name', ''))
        dest_name = str(leg.get('destination_name', ''))
        origin_pinyin = leg.get('origin_pinyin') or get_pinyin_for_city(origin_name)
        dest_pinyin = leg.get('destination_pinyin') or get_pinyin_for_city(dest_name)

        if route_scope == 'international':
            rows.append(
                {
                    'dataset_id': 'airline_hsr_route_observations',
                    'as_of_date': leg.get('as_of_date'),
                    'observation_date': leg.get('as_of_date'),
                    'company': leg.get('company'),
                    'operating_entity': leg.get('operating_entity', leg.get('company')),
                    'parent_group': leg.get('parent_group', leg.get('company')),
                    'ticker': leg.get('ticker'),
                    'route_text': leg.get('route_text'),
                    'origin_pinyin': origin_pinyin,
                    'destination_pinyin': dest_pinyin,
                    'station_scope': 'not_applicable',
                    'departure_station_scope': 'not_applicable',
                    'arrival_station_scope': 'not_applicable',
                    'service_filter': 'G_or_D',
                    'train_count': 0,
                    'gd_train_count': 0,
                    'min_run_time_minutes': None,
                    'min_second_class_fare_rmb': None,
                    'fastest_gd_train_number': None,
                    'fastest_gd_fare_rmb': None,
                    'route_observation_status': 'not_applicable_international',
                    'source_url': leg.get('source_url'),
                    'source_quality': leg.get('source_quality'),
                    'source_note': 'International route leg; HSR rail observation not applicable.',
                    'retrieved_at': leg.get('retrieved_at'),
                }
            )
            continue

        leg_snapshots = pd.DataFrame()
        if snapshots is not None and not snapshots.empty:
            leg_snapshots = snapshots[
                snapshots['origin_pinyin'].astype(str).str.lower().eq(origin_pinyin.lower())
                & snapshots['destination_pinyin'].astype(str).str.lower().eq(dest_pinyin.lower())
            ]

        if leg_snapshots.empty:
            rows.append(
                {
                    'dataset_id': 'airline_hsr_route_observations',
                    'as_of_date': leg.get('as_of_date'),
                    'observation_date': leg.get('as_of_date'),
                    'company': leg.get('company'),
                    'operating_entity': leg.get('operating_entity', leg.get('company')),
                    'parent_group': leg.get('parent_group', leg.get('company')),
                    'ticker': leg.get('ticker'),
                    'route_text': leg.get('route_text'),
                    'origin_pinyin': origin_pinyin,
                    'destination_pinyin': dest_pinyin,
                    'station_scope': 'city_level_query',
                    'departure_station_scope': 'pending',
                    'arrival_station_scope': 'pending',
                    'service_filter': 'G_or_D',
                    'train_count': 0,
                    'gd_train_count': 0,
                    'min_run_time_minutes': None,
                    'min_second_class_fare_rmb': None,
                    'fastest_gd_train_number': None,
                    'fastest_gd_fare_rmb': None,
                    'route_observation_status': 'pending_rail_query',
                    'source_url': leg.get('source_url'),
                    'source_quality': leg.get('source_quality'),
                    'source_note': f'Pending Ctrip snapshot fetch for city leg {origin_pinyin}->{dest_pinyin}',
                    'retrieved_at': leg.get('retrieved_at'),
                }
            )
        else:
            latest_date = str(leg_snapshots['observation_date'].max())
            date_snapshots = leg_snapshots[leg_snapshots['observation_date'].astype(str).eq(latest_date)]

            # Filter out negative observation marker rows
            real_trains = date_snapshots[date_snapshots['train_number'].astype(str).ne('NO_DIRECT_TRAIN')]
            gd_trains = real_trains[real_trains['train_class'].astype(str).str.upper().isin(['G', 'D'])]

            train_count = len(real_trains)
            gd_count = len(gd_trains)

            dep_stations = sorted(real_trains['departure_station_name'].dropna().unique())
            arr_stations = sorted(real_trains['arrival_station_name'].dropna().unique())

            dep_scope = '/'.join(dep_stations) if dep_stations else 'not_available'
            arr_scope = '/'.join(arr_stations) if arr_stations else 'not_available'
            station_scope = (
                'main_hub_pair' if len(dep_stations) == 1 and len(arr_stations) == 1 else 'city_level_all_station_pairs'
            )

            if gd_count > 0:
                min_run_time = gd_trains['run_time_minutes'].min()
                valid_fares = gd_trains['second_class_fare_rmb'].dropna()
                min_fare = valid_fares.min() if not valid_fares.empty else None

                fastest_row = gd_trains.sort_values(by=['run_time_minutes', 'second_class_fare_rmb']).iloc[0]
                fastest_train = fastest_row['train_number']
                fastest_fare = fastest_row['second_class_fare_rmb']

                obs_status = 'verified_snapshot'
                note = (
                    f'{gd_count} G/D services observed on {latest_date} for {origin_name}->{dest_name}. '
                    f'Fastest service is {fastest_train} ({min_run_time} mins).'
                )
            else:
                min_run_time = None
                min_fare = None
                fastest_train = None
                fastest_fare = None
                station_scope = 'city_level_query'
                obs_status = 'no_direct_train_result' if train_count == 0 else 'no_g_d_trains'
                note = f'Ctrip search returned 0 direct trains for {origin_pinyin}->{dest_pinyin} on {latest_date}'

            rows.append(
                {
                    'dataset_id': 'airline_hsr_route_observations',
                    'as_of_date': leg.get('as_of_date'),
                    'observation_date': latest_date,
                    'company': leg.get('company'),
                    'operating_entity': leg.get('operating_entity', leg.get('company')),
                    'parent_group': leg.get('parent_group', leg.get('company')),
                    'ticker': leg.get('ticker'),
                    'route_text': leg.get('route_text'),
                    'origin_pinyin': origin_pinyin,
                    'destination_pinyin': dest_pinyin,
                    'station_scope': station_scope,
                    'departure_station_scope': dep_scope,
                    'arrival_station_scope': arr_scope,
                    'service_filter': 'G_or_D',
                    'train_count': train_count,
                    'gd_train_count': gd_count,
                    'min_run_time_minutes': float(min_run_time) if min_run_time is not None else None,
                    'min_second_class_fare_rmb': float(min_fare) if min_fare is not None else None,
                    'fastest_gd_train_number': fastest_train,
                    'fastest_gd_fare_rmb': float(fastest_fare) if fastest_fare is not None else None,
                    'route_observation_status': obs_status,
                    'source_url': date_snapshots['source_url'].iloc[0] if not date_snapshots.empty else leg.get('source_url'),
                    'source_quality': 'ctrip_ssr_train_state',
                    'source_note': note,
                    'retrieved_at': pd.Timestamp.now(tz='UTC').isoformat(),
                }
            )

    result = pd.DataFrame(rows)
    result.to_csv(OBSERVATION_PATH, index=False)
    return result


def enrich_osrm_access_times(df: pd.DataFrame, fetch_live: bool = False) -> pd.DataFrame:
    """Enrich route legs with OSRM driving access latency scores derived from response queries.

    If fetch_live is False, access score is marked as pending_access_coordinates and left as NaN.
    No benchmark values are hardcoded as verified data.
    """
    df = df.copy()
    access_scores: list[float | None] = []
    access_statuses: list[str] = []
    source_urls: list[str | None] = []
    lineages: list[str | None] = []

    for _, row in df.iterrows():
        origin_name = str(row.get('origin_name', ''))
        dest_name = str(row.get('destination_name', ''))
        origin_pinyin = str(row.get('origin_pinyin') or get_pinyin_for_city(origin_name))
        dest_pinyin = str(row.get('destination_pinyin') or get_pinyin_for_city(dest_name))
        route_scope = str(row.get('route_scope', ''))

        if route_scope == 'international':
            access_scores.append(None)
            access_statuses.append('not_applicable')
            source_urls.append(None)
            lineages.append(None)
            continue

        # Check if route connects verified hubs (Shanghai to Guangzhou)
        is_sh_gz = (origin_pinyin == 'shanghai' and dest_pinyin == 'guangzhou') or (
            origin_pinyin == 'guangzhou' and dest_pinyin == 'shanghai'
        )

        if is_sh_gz and fetch_live:
            try:
                # Fetch Pudong Airport -> Shanghai CBD
                dur_pd, url_pd = fetch_osrm_driving_duration(
                    HUB_COORDINATES['SHANGHAI_PUDONG_AIRPORT']['lon'],
                    HUB_COORDINATES['SHANGHAI_PUDONG_AIRPORT']['lat'],
                    HUB_COORDINATES['SHANGHAI_CBD_PEOPLES_SQUARE']['lon'],
                    HUB_COORDINATES['SHANGHAI_CBD_PEOPLES_SQUARE']['lat'],
                )
                # Fetch Hongqiao HSR -> Shanghai CBD
                dur_hq, url_hq = fetch_osrm_driving_duration(
                    HUB_COORDINATES['SHANGHAI_HONGQIAO_HSR']['lon'],
                    HUB_COORDINATES['SHANGHAI_HONGQIAO_HSR']['lat'],
                    HUB_COORDINATES['SHANGHAI_CBD_PEOPLES_SQUARE']['lon'],
                    HUB_COORDINATES['SHANGHAI_CBD_PEOPLES_SQUARE']['lat'],
                )
                if dur_pd is not None and dur_hq is not None:
                    delta = round(dur_pd - dur_hq, 1)
                    access_scores.append(delta)
                    access_statuses.append('osrm_response_derived')
                    source_urls.append(f'{url_pd} ; {url_hq}')
                    lineages.append(
                        f'Pudong_Airport({dur_pd}m) - Hongqiao_HSR({dur_hq}m) to Shanghai_CBD = {delta}m'
                    )
                else:
                    access_scores.append(None)
                    access_statuses.append('pending_access_coordinates')
                    source_urls.append(None)
                    lineages.append(None)
            except Exception:
                access_scores.append(None)
                access_statuses.append('pending_access_coordinates')
                source_urls.append(None)
                lineages.append(None)
        else:
            access_scores.append(None)
            access_statuses.append('pending_access_coordinates')
            source_urls.append(None)
            lineages.append(None)

    df['airport_station_access_score'] = access_scores
    df['access_score_status'] = access_statuses
    df['access_source_url'] = source_urls
    df['access_coordinate_lineage'] = lineages
    return df


def calculate_hsr_substitution_score(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate explicit diagnostic HSR substitution score.

    The output is explicitly declared as a modelled diagnostic, not observed truth.
    Absence of a direct train result is marked as pending_no_direct_rail_observation (NaN),
    retaining 0.0 ONLY for defensible no-rail geography cases (e.g. cross-sea routes).
    """
    df = df.copy()
    scores: list[float | None] = []
    statuses: list[str] = []

    for _, row in df.iterrows():
        route_scope = str(row.get('route_scope', ''))
        origin_name = str(row.get('origin_name', ''))
        dest_name = str(row.get('destination_name', ''))
        origin_pinyin = str(row.get('origin_pinyin') or get_pinyin_for_city(origin_name))
        dest_pinyin = str(row.get('destination_pinyin') or get_pinyin_for_city(dest_name))
        obs_status = str(row.get('route_observation_status', row.get('rail_query_status', '')))
        run_time = row.get('min_run_time_minutes', row.get('rail_time_minutes'))
        gd_count = row.get('gd_train_count', row.get('rail_frequency_per_day'))
        access_score = row.get('airport_station_access_score')

        if route_scope == 'international':
            scores.append(None)
            statuses.append('not_applicable_international')
            continue

        # Defensible geographical no-rail case (e.g. Dalian-Yantai cross-sea)
        if (origin_pinyin, dest_pinyin) in NO_RAIL_GEOGRAPHY_PAIRS:
            scores.append(0.0)
            statuses.append('defensible_no_rail_geography')
            continue

        # Absence of direct train result is NOT proof of 0.0 rail substitution (connecting rail may exist)
        if obs_status == 'no_direct_train_result' or (gd_count is not None and pd.notna(gd_count) and float(gd_count) == 0):
            scores.append(None)
            statuses.append('pending_no_direct_rail_observation')
            continue

        if run_time is None or pd.isna(run_time):
            scores.append(None)
            statuses.append('pending_rail_data')
            continue

        t = float(run_time)
        # Base Rail Time Score
        if t <= 240:
            s_time = 1.0 - 0.2 * (t / 240.0)
        elif t <= 360:
            s_time = 0.8 - 0.3 * ((t - 240.0) / 120.0)
        elif t <= 480:
            s_time = 0.5 - 0.3 * ((t - 360.0) / 120.0)
        else:
            s_time = max(0.05, 0.2 - 0.15 * ((t - 480.0) / 240.0))

        # Frequency modifier
        m_freq = 0.0
        if gd_count is not None and pd.notna(gd_count):
            c = float(gd_count)
            if c >= 15:
                m_freq = 0.05
            elif c < 5:
                m_freq = -0.05

        # Access modifier
        m_access = 0.0
        if access_score is not None and pd.notna(access_score) and float(access_score) > 30:
            m_access = 0.05

        total_score = round(float(np.clip(s_time + m_freq + m_access, 0.0, 1.0)), 3)
        scores.append(total_score)
        statuses.append('modelled_diagnostic')

    df['hsr_substitution_score'] = scores
    df['hsr_score_status'] = statuses
    return df


def calculate_ask_weighted_exposure(df: pd.DataFrame, capacity_weights: pd.DataFrame | None = None) -> pd.DataFrame:
    """Calculate ASK-weighted exposure using explicit operator-scoped route capacity proxies.

    Detects whether queue (df) and capacity inputs have operator scope columns (operating_entity/company).
    If both inputs have operator scope, matching is strictly restricted to (operator, origin_pinyin, destination_pinyin);
    unmatched operators remain pending/NaN without falling back to another operator's city-pair capacity.
    Unscoped city-pair fallback is permitted ONLY when input queue or capacity table genuinely lacks operator scope columns.
    """
    df = df.copy()
    if capacity_weights is None and (NORMALIZED_DIR / "airline_route_capacity_weights.csv").exists():
        capacity_weights = pd.read_csv(NORMALIZED_DIR / "airline_route_capacity_weights.csv")

    exposures: list[float | None] = []
    statuses: list[str] = []

    has_df_operator = any(col in df.columns for col in ["operating_entity", "company"])
    has_cap_operator = (
        capacity_weights is not None
        and not capacity_weights.empty
        and any(col in capacity_weights.columns for col in ["operating_entity", "company"])
    )
    both_have_operator_scope = has_df_operator and has_cap_operator

    cap_map_scoped: dict[tuple[str, str, str], pd.Series] = {}
    cap_map_unscoped: dict[tuple[str, str], pd.Series] = {}

    if capacity_weights is not None and not capacity_weights.empty:
        for _, c_row in capacity_weights.iterrows():
            op = str(c_row.get("operating_entity") or c_row.get("company") or "").strip()
            orig = str(c_row.get("origin_pinyin", "")).strip()
            dest = str(c_row.get("destination_pinyin", "")).strip()

            if op:
                cap_map_scoped[(op, orig, dest)] = c_row
            cap_map_unscoped[(orig, dest)] = c_row

    for _, row in df.iterrows():
        op = str(row.get("operating_entity") or row.get("company") or "").strip()
        orig_pinyin = str(row.get("origin_pinyin", "")).strip()
        dest_pinyin = str(row.get("destination_pinyin", "")).strip()
        score = row.get("hsr_substitution_score")

        cap_info = None
        if both_have_operator_scope:
            # STRICT OPERATOR MATCH: When both datasets carry operator scope, require exact (operator, origin, dest) match.
            # Never fall back to another operator's capacity on the same route.
            if op and (op, orig_pinyin, dest_pinyin) in cap_map_scoped:
                cap_info = cap_map_scoped[(op, orig_pinyin, dest_pinyin)]
        else:
            # UNSCOPED FALLBACK: Permitted only when queue or capacity table genuinely lacks operator scope columns.
            if op and (op, orig_pinyin, dest_pinyin) in cap_map_scoped:
                cap_info = cap_map_scoped[(op, orig_pinyin, dest_pinyin)]
            elif (orig_pinyin, dest_pinyin) in cap_map_unscoped:
                cap_info = cap_map_unscoped[(orig_pinyin, dest_pinyin)]

        ask_proxy = cap_info.get("weekly_ask_proxy_thousand") if cap_info is not None else None

        if ask_proxy is not None and pd.notna(ask_proxy):
            if score is not None and pd.notna(score):
                exposures.append(round(float(ask_proxy) * float(score), 2))
                statuses.append("modelled_route_ask_proxy")
            else:
                exposures.append(None)
                statuses.append("pending_hsr_score")
        else:
            exposures.append(None)
            statuses.append("pending_route_ask_weights")

    df["hsr_ask_weighted_exposure"] = exposures
    df["hsr_ask_exposure_status"] = statuses
    return df


def run_airline_hsr_enrichment_pipeline(fetch_live_osrm: bool = False) -> pd.DataFrame:
    """Run complete reproducible pipeline: candidates -> queue -> observations -> access score -> diagnostic score -> ASK exposure."""
    queue = fetch_airline_hsr_query_queue()
    observations = summarize_ctrip_route_observations(queue=queue)

    # Merge observation metrics into queue
    merged = queue.copy()
    if 'origin_pinyin' not in merged.columns:
        merged['origin_pinyin'] = merged['origin_name'].apply(lambda x: get_pinyin_for_city(str(x)))
    if 'destination_pinyin' not in merged.columns:
        merged['destination_pinyin'] = merged['destination_name'].apply(lambda x: get_pinyin_for_city(str(x)))

    if not observations.empty:
        obs_map = observations.set_index(['origin_pinyin', 'destination_pinyin'])
        for idx, row in merged.iterrows():
            op = str(row['origin_pinyin'])
            dp = str(row['destination_pinyin'])
            if (op, dp) in obs_map.index:
                obs = obs_map.loc[(op, dp)]
                if isinstance(obs, pd.DataFrame):
                    obs = obs.iloc[0]
                merged.at[idx, 'rail_time_minutes'] = obs.get('min_run_time_minutes')
                merged.at[idx, 'rail_frequency_per_day'] = obs.get('gd_train_count')
                merged.at[idx, 'rail_fare_rmb'] = obs.get('min_second_class_fare_rmb')
                merged.at[idx, 'rail_observation_date'] = obs.get('observation_date')
                merged.at[idx, 'rail_query_status'] = obs.get('route_observation_status')

    # Apply OSRM access latency (response-derived or pending), diagnostic score, and ASK exposure safeguards
    merged = enrich_osrm_access_times(merged, fetch_live=fetch_live_osrm)
    merged = calculate_hsr_substitution_score(merged)

    # Build or fetch capacity weights
    from .airline_route_capacity import build_airline_route_capacity_weights
    capacity_weights = build_airline_route_capacity_weights()
    merged = calculate_ask_weighted_exposure(merged, capacity_weights=capacity_weights)

    merged.to_csv(QUEUE_PATH, index=False)
    return merged
