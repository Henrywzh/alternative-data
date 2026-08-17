"""Route-level airline capacity weight enrichment module.

This module provides auditable, source-derived route capacity metrics
(flight frequency, fleet seats per aircraft, stage length, and weekly ASK proxies)
without allocating total company ASK across routes by assumption.
"""

from __future__ import annotations

import math
import re
import pandas as pd

from ..config import NORMALIZED_DIR
from .airline_hsr_enrichment import get_pinyin_for_city

CANDIDATE_PATH = NORMALIZED_DIR / "airline_hsr_route_candidates.csv"
QUEUE_PATH = NORMALIZED_DIR / "airline_hsr_route_query_queue.csv"
CAPACITY_WEIGHTS_PATH = NORMALIZED_DIR / "airline_route_capacity_weights.csv"

# Known city coordinates for stage length (Haversine km) calculation
CITY_COORDINATES: dict[str, tuple[float, float]] = {
    "beijing": (116.4074, 39.9042),
    "shanghai": (121.4737, 31.2304),
    "guangzhou": (113.2644, 23.1291),
    "dali": (100.2297, 25.5916),
    "lanzhou": (103.8343, 36.0611),
    "aletai": (88.1397, 47.8449),
    "dalian": (121.6147, 38.9140),
    "yantai": (121.3913, 37.5393),
    "shenzhen": (114.0579, 22.5431),
    "jakarta": (106.8456, -6.2088),
    "chizhou": (117.4916, 30.6648),
    "shenyang": (123.4315, 41.8057),
    "guiyang": (106.7072, 26.5982),
    "changzhou": (119.9741, 31.8112),
    "wuhan": (114.3055, 30.5928),
    "changchun": (125.3245, 43.8868),
    "hefei": (117.2272, 31.8206),
    "hailaer": (119.7658, 49.2116),
    "jinan": (117.1205, 36.6512),
    "wulumuqi": (87.6168, 43.8256),
    "nanjing": (118.7969, 32.0603),
    "jiaxing": (120.7585, 30.7520),
    "huangshan": (118.1692, 29.7147),
    "xilinhot": (116.0900, 43.9440),
    "wuxi": (120.3119, 31.4912),
    "yangzhou": (119.4127, 32.3942),
    "zhangye": (100.4498, 38.9259),
    "ningbo": (121.5503, 29.8746),
    "yulin": (109.7346, 38.2849),
    "hanzhong": (107.0233, 33.0676),
    "lijiang": (100.2278, 26.8550),
    "tacheng": (82.9853, 46.7464),
    "korla": (86.1605, 41.7303),
    "ganzhou": (114.9350, 25.8311),
}


def haversine_distance_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Compute great-circle distance in km between two lon/lat points."""
    r = 6371.0  # Earth radius in km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(r * c, 1)


def parse_disclosed_weekly_frequency(frequency_text: str | None) -> tuple[float | None, str]:
    """Parse disclosed frequency text into weekly flights count and quality label."""
    if not frequency_text or pd.isna(frequency_text):
        return None, "pending_frequency_disclosure"

    text = str(frequency_text).strip()
    if text == "天天班":
        return 7.0, "disclosed_daily_schedule"

    # Match '周246' (3 days/week) or '周36' (2 days/week) or '周257' (3 days/week)
    m_days = re.match(r"^周([1-7]+)$", text)
    if m_days:
        num_days = len(m_days.group(1))
        return float(num_days), "disclosed_weekly_schedule_days"

    # Match '每周3班' or '每周4班'
    m_weekly = re.search(r"每周\s*(\d+)\s*班", text)
    if m_weekly:
        return float(m_weekly.group(1)), "disclosed_weekly_frequency"

    if "frequency increase" in text.lower():
        return None, "qualitative_frequency_increase"

    if "weekly frequency" in text.lower():
        return None, "qualitative_weekly_detail"

    return None, "unparsed_frequency_text"


def get_fleet_seats_per_flight(operating_entity: str) -> dict[str, object]:
    """Return disclosed seats per flight, source dates, URLs, and conflict notes for operating entity.

    Returns dict containing:
      seats_operational_proxy, seats_scenario_189, seats_source_quality,
      seats_operational_source_url, seats_operational_source_date,
      seats_scenario_source_url, seats_scenario_source_date, conflict_note.
    """
    op = str(operating_entity).strip().lower()
    if op == "spring airlines":
        return {
            "seats_operational_proxy": 186.0,
            "seats_scenario_189": 186.0,
            "seats_source_quality": "spring_annual_report_2025_a320_single_class_186_seats",
            "seats_operational_source_url": "https://static.cninfo.com.cn/finalpage/2026-04-11/1225093115.PDF",
            "seats_operational_source_date": "2026-04-11",
            "seats_scenario_source_url": "https://static.cninfo.com.cn/finalpage/2026-04-11/1225093115.PDF",
            "seats_scenario_source_date": "2026-04-11",
            "conflict_note": None,
        }
    elif op == "9 air":
        conflict_note = (
            "Primary source conflict detected: Live official 9air.com fleet page (2026-05-26) states 188 seats "
            "for 9 Air B737 operational layout, while Juneyao FY2025 Annual Report Page 15 (2026-04-23) states 189 seats. "
            "Analytical inference: 188.0 represents current operational seat-selection layout, while 189.0 represents generic "
            "B737 series limit description. Both values and source dates are retained in scenario metadata."
        )
        return {
            "seats_operational_proxy": 188.0,
            "seats_scenario_189": 189.0,
            "seats_source_quality": "9air_official_website_188_seats_with_annual_report_189_conflict",
            "seats_operational_source_url": "https://www.9air.com/cmsProvider/info/1011/1431.htm",
            "seats_operational_source_date": "2026-05-26",
            "seats_scenario_source_url": "https://static.cninfo.com.cn/finalpage/2026-04-23/1225151299.PDF",
            "seats_scenario_source_date": "2026-04-23",
            "conflict_note": conflict_note,
        }
    elif op == "juneyao airlines mainline":
        return {
            "seats_operational_proxy": 180.0,
            "seats_scenario_189": 180.0,
            "seats_source_quality": "juneyao_annual_report_2025_narrowbody_fleet_180_seats",
            "seats_operational_source_url": "https://static.cninfo.com.cn/finalpage/2026-04-23/1225151299.PDF",
            "seats_operational_source_date": "2026-04-23",
            "seats_scenario_source_url": "https://static.cninfo.com.cn/finalpage/2026-04-23/1225151299.PDF",
            "seats_scenario_source_date": "2026-04-23",
            "conflict_note": None,
        }
    elif op == "juneyao airlines":
        # Juneyao mainline (not the 9 Air subsidiary): the same FY2025 annual
        # report discloses the mainline narrowbody fleet at 180 seats; CAAC
        # licence candidates for the mainline entity carry this anchor.
        return {
            "seats_operational_proxy": 180.0,
            "seats_scenario_189": 180.0,
            "seats_source_quality": "juneyao_annual_report_2025_narrowbody_fleet_180_seats",
            "seats_operational_source_url": "https://static.cninfo.com.cn/finalpage/2026-04-23/1225151299.PDF",
            "seats_operational_source_date": "2026-04-23",
            "seats_scenario_source_url": "https://static.cninfo.com.cn/finalpage/2026-04-23/1225151299.PDF",
            "seats_scenario_source_date": "2026-04-23",
            "conflict_note": None,
        }
    elif op == "china eastern airlines":
        return {
            "seats_operational_proxy": None,
            "seats_scenario_189": None,
            "seats_source_quality": "pending_route_aircraft_configuration",
            "seats_operational_source_url": "https://static.cninfo.com.cn/finalpage/2025-10-16/1224713276.PDF",
            "seats_operational_source_date": "2025-10-16",
            "seats_scenario_source_url": None,
            "seats_scenario_source_date": None,
            "conflict_note": None,
        }
    elif op == "china southern airlines":
        return {
            "seats_operational_proxy": None,
            "seats_scenario_189": None,
            "seats_source_quality": "pending_route_aircraft_configuration",
            "seats_operational_source_url": "https://static.cninfo.com.cn/finalpage/2026-07-16/1225425964.PDF",
            "seats_operational_source_date": "2026-07-16",
            "seats_scenario_source_url": None,
            "seats_scenario_source_date": None,
            "conflict_note": None,
        }
    else:
        return {
            "seats_operational_proxy": None,
            "seats_scenario_189": None,
            "seats_source_quality": "pending_operator_seat_configuration",
            "seats_operational_source_url": None,
            "seats_operational_source_date": None,
            "seats_scenario_source_url": None,
            "seats_scenario_source_date": None,
            "conflict_note": None,
        }


def build_airline_route_capacity_weights(
    candidates: pd.DataFrame | None = None,
    queue: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build auditable route capacity weights dataset with operator and parent_group scope."""
    if candidates is None and CANDIDATE_PATH.exists():
        candidates = pd.read_csv(CANDIDATE_PATH)

    if candidates is None:
        raise ValueError("Missing airline_hsr_route_candidates.csv")

    rows: list[dict[str, object]] = []
    for _, row in candidates.iterrows():
        company = str(row.get("company", ""))
        operating_entity = str(row.get("operating_entity", company))
        parent_group = str(row.get("parent_group", company))
        ticker = str(row.get("ticker", ""))
        route_text = str(row.get("route_text", ""))
        route_scope = str(row.get("route_scope", ""))
        freq_text = row.get("airline_frequency_text")
        source_url = str(row.get("airline_source_url", ""))
        source_quality = str(row.get("airline_source_quality", ""))
        as_of_date = str(row.get("as_of_date", ""))
        retrieved_at = str(row.get("retrieved_at", ""))

        weekly_freq, freq_status = parse_disclosed_weekly_frequency(freq_text)
        seats_meta = get_fleet_seats_per_flight(operating_entity)

        seats_per_flight = seats_meta["seats_operational_proxy"]
        seats_scen_189 = seats_meta["seats_scenario_189"]
        seats_quality = seats_meta["seats_source_quality"]
        op_seats_url = seats_meta["seats_operational_source_url"]
        op_seats_date = seats_meta["seats_operational_source_date"]
        scen_seats_url = seats_meta["seats_scenario_source_url"]
        scen_seats_date = seats_meta["seats_scenario_source_date"]
        conflict_note = seats_meta["conflict_note"]

        # Split into legs if multi-leg
        from .airline_hsr_enrichment import split_route_legs
        legs = split_route_legs(route_text)
        if not legs:
            legs = [(route_text, "")]

        for leg_idx, (orig, dest) in enumerate(legs, start=1):
            orig_pinyin = get_pinyin_for_city(orig)
            dest_pinyin = get_pinyin_for_city(dest)

            # Distance
            dist_km = None
            if orig_pinyin in CITY_COORDINATES and dest_pinyin in CITY_COORDINATES:
                lon1, lat1 = CITY_COORDINATES[orig_pinyin]
                lon2, lat2 = CITY_COORDINATES[dest_pinyin]
                dist_km = haversine_distance_km(lon1, lat1, lon2, lat2)

            if weekly_freq is not None and seats_per_flight is not None:
                seat_cap_proxy = round(weekly_freq * float(seats_per_flight), 1)
                ask_proxy_k = (
                    round(seat_cap_proxy * dist_km / 1000.0, 2)
                    if dist_km is not None
                    else None
                )

                # Secondary scenario ASK proxy using 189 seats
                ask_scen_189_k = None
                if seats_scen_189 is not None and dist_km is not None:
                    ask_scen_189_k = round(weekly_freq * float(seats_scen_189) * dist_km / 1000.0, 2)

                if conflict_note:
                    cap_status = "frequency_disclosed_proxy_conflicted_seats"
                    note = f"Operator {operating_entity}: {conflict_note}"
                else:
                    cap_status = "frequency_disclosed_proxy"
                    note = (
                        f"Operator {operating_entity}: Disclosed frequency {weekly_freq} flights/week x "
                        f"{seats_per_flight} seats/flight = {seat_cap_proxy} seats/week ({dist_km} km stage length)"
                    )
            elif "qualitative" in freq_status:
                seat_cap_proxy = None
                ask_proxy_k = None
                ask_scen_189_k = None
                cap_status = "qualitative_frequency_only"
                note = f"Operator {operating_entity}: Disclosed qualitative addition ({freq_text}); exact weekly frequency pending schedule parse"
            else:
                seat_cap_proxy = None
                ask_proxy_k = None
                ask_scen_189_k = None
                cap_status = "pending_route_ask_weights"
                note = f"Operator {operating_entity}: Route capacity weight pending schedule disclosure"

            rows.append(
                {
                    "dataset_id": "airline_route_capacity_weights",
                    "as_of_date": as_of_date,
                    "company": company,
                    "operating_entity": operating_entity,
                    "parent_group": parent_group,
                    "ticker": ticker,
                    "route_text": route_text,
                    "route_scope": route_scope,
                    "leg_index": leg_idx,
                    "origin_name": orig,
                    "destination_name": dest,
                    "origin_pinyin": orig_pinyin,
                    "destination_pinyin": dest_pinyin,
                    "disclosed_frequency_text": freq_text,
                    "weekly_flight_frequency": weekly_freq,
                    "frequency_status": freq_status,
                    "seats_per_flight": seats_per_flight,
                    "seats_per_flight_scenario_189": seats_scen_189,
                    "seats_source_quality": seats_quality,
                    "seats_operational_source_url": op_seats_url,
                    "seats_operational_source_date": op_seats_date,
                    "seats_scenario_source_url": scen_seats_url,
                    "seats_scenario_source_date": scen_seats_date,
                    "seats_conflict_note": conflict_note,
                    "stage_length_km": dist_km,
                    "weekly_seat_capacity_proxy": seat_cap_proxy,
                    "weekly_ask_proxy_thousand": ask_proxy_k,
                    "weekly_ask_proxy_scenario_189_thousand": ask_scen_189_k,
                    "route_capacity_status": cap_status,
                    "source_url": source_url,
                    "source_quality": source_quality,
                    "source_note": note,
                    "retrieved_at": retrieved_at,
                }
            )

    result = pd.DataFrame(rows)
    result.to_csv(CAPACITY_WEIGHTS_PATH, index=False)
    return result
