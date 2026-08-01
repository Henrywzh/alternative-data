from __future__ import annotations

from unittest.mock import Mock, patch

import pandas as pd

from src.hk_commercial_aerospace.sources.faa_commercial_space import fetch_faa_commercial_space_kpis
from src.hk_commercial_aerospace.sources.global_space_benchmark import fetch_global_objects_launched
from src.hk_commercial_aerospace.sources.launch_library import (
    SCHEMA_COLUMNS as LL2_SCHEMA,
    _append_launch_history,
    _exact_provider_rows,
    _merge_launch_history,
    _parse_launch_results,
    build_monthly_launch_summary,
    build_monthly_launch_total_summary,
)
from src.hk_commercial_aerospace.sources.china_launch_records import (
    EVENT_COLUMNS as CHINA_EVENT_COLUMNS,
    _parse_calt_rows,
    _parse_casc_rows,
    build_china_launch_monthly,
    build_rocket_family_summary,
    enrich_with_ll2,
    parse_payload_count,
)
from src.hk_commercial_aerospace.sources.usaspending import fetch_commercial_space_contracts
from src.hk_commercial_aerospace.sources.celestrak_satellites import fetch_all_constellations


def test_launch_parser_uses_id_and_exact_provider_guard():
    rows = [
        {
            "id": "good",
            "name": "Zhuque-2E",
            "net": "2026-06-09T08:23:00Z",
            "status": {"abbrev": "Success", "name": "Launch Successful"},
            "launch_service_provider": {"id": 259, "name": "LandSpace"},
            "rocket": {"configuration": {"full_name": "Zhuque-2E", "family": "Zhuque"}},
            "mission": {"type": "Communications", "orbit": {"abbrev": "LEO"}},
            "pad": {"name": "Launch Area 96A"},
        },
        {
            "id": "false-match",
            "name": "Other payload mentioning LandSpace",
            "net": "1969-08-27T21:59:00Z",
            "status": {"abbrev": "Failure", "name": "Launch Failure"},
            "launch_service_provider": {"id": 161, "name": "United States Air Force"},
        },
    ]
    exact = _exact_provider_rows(rows, provider_id=259, provider_name="LandSpace")
    parsed = _parse_launch_results(exact, "2026-08-01T00:00:00+00:00")
    assert [row["launch_id"] for row in parsed] == ["good"]
    assert parsed[0]["provider_id"] == 259


def test_monthly_launch_summary_deduplicates_launch_id():
    frame = pd.DataFrame([
        {"launch_id": "a", "net_time": "2026-01-02T00:00:00Z", "provider_name": "LandSpace", "status_abbrev": "Success"},
        {"launch_id": "a", "net_time": "2026-01-02T00:00:00Z", "provider_name": "LandSpace", "status_abbrev": "Success"},
        {"launch_id": "b", "net_time": "2026-01-15T00:00:00Z", "provider_name": "LandSpace", "status_abbrev": "Failure"},
    ])
    summary = build_monthly_launch_summary(frame)
    assert summary["launch_count"].sum() == 2
    assert set(summary["status"]) == {"Success", "Failure"}


def test_monthly_launch_total_is_zero_filled_and_not_provider_status_grain():
    frame = pd.DataFrame([
        {"launch_id": "a", "net_time": "2026-01-02T00:00:00Z", "provider_name": "LandSpace", "status_abbrev": "Success"},
        {"launch_id": "b", "net_time": "2026-03-15T00:00:00Z", "provider_name": "CAS Space", "status_abbrev": "Success"},
        {"launch_id": "b", "net_time": "2026-03-15T00:00:00Z", "provider_name": "CAS Space", "status_abbrev": "Success"},
    ])
    summary = build_monthly_launch_total_summary(frame)
    assert summary.to_dict(orient="records") == [
        {"month": "2026-01", "launch_count": 1},
        {"month": "2026-02", "launch_count": 0},
        {"month": "2026-03", "launch_count": 1},
    ]


def test_official_launch_parsers_keep_long_march_and_jielong_fields():
    casc_html = """
    <table><tr><th>发射序号</th><th>运载火箭</th><th>发射日期</th><th>卫星/航天器</th><th>发射地点</th></tr>
    <tr><td>660</td><td>长征六号改运载火箭</td><td>2026.07.30</td><td>通信技术试验卫星二十七号A/B星</td><td>太原卫星发射中心</td></tr>
    </table>
    """
    calt_html = """
    <table><tr><th>发射日期</th><th>运载火箭</th><th>发射卫星</th><th>发射基地</th><th>发射次数</th><th>结果</th></tr>
    <tr><td>2026年2月12日</td><td>捷龙三号</td><td>基斯坦PRSC-EO2卫星、港中大一号卫星</td><td>广东阳江附近海域</td><td>捷龙系列第10次</td><td>成功</td></tr>
    <tr><td>2026年7月29日</td><td>长征七号A</td><td>天链三号01星</td><td>文昌</td><td>第387次</td><td>成功</td></tr>
    </table>
    """
    casc = _parse_casc_rows(casc_html, "casc-url", "casc.raw", "2026-08-01T00:00:00Z")
    calt = _parse_calt_rows(calt_html, "calt-url", "calt.raw", "2026-08-01T00:00:00Z")
    assert len(casc) == 1
    assert casc[0]["program_class"] == "national_program"
    assert casc[0]["official_sequence"] == "long-march-660"
    assert len(calt) == 2
    jielong = next(row for row in calt if row["program_class"] == "state_owned_commercial")
    assert jielong["payload_summary"].startswith("基斯坦")


def test_payload_count_only_uses_explicit_source_language():
    assert parse_payload_count("一箭十四星") == 14
    assert parse_payload_count("烟台二号卫星等9颗卫星") == 9
    assert parse_payload_count("天仪41星、星时代-15卫星等8颗商业卫星") == 8
    assert parse_payload_count("通信技术试验卫星二十七号A/B星") is None


def test_official_events_are_enriched_by_date_rocket_and_site_without_ll2_only_rows():
    official = pd.DataFrame([
        {
            "event_id": "casc-long-march-660",
            "official_source_id": "casc:long-march-660",
            "official_sequence": "long-march-660",
            "launch_date": "2026-07-30",
            "launch_time": None,
            "launch_time_precision": "date",
            "rocket_name": "长征六号改运载火箭",
            "rocket_family": "长征",
            "rocket_variant": "长征六号改运载火箭",
            "mission_name": "通信技术试验卫星二十七号A/B星",
            "launch_site": "太原卫星发射中心",
            "launch_pad": None,
            "target_orbit": None,
            "mission_type": None,
            "outcome": "成功",
            "outcome_normalized": "Success",
            "program_class": "national_program",
            "classification_status": "verified",
            "payload_summary": "通信技术试验卫星二十七号A/B星",
            "payload_count": None,
            "official_source_url": "casc-url",
            "official_source_kind": "casc-long-march",
            "ll2_launch_id": None,
            "ll2_match_status": "not_checked",
            "ll2_match_confidence": None,
            "ll2_provider_name": None,
            "source_snapshot": "casc.raw",
            "fetched_at": "2026-08-01T00:00:00Z",
            "parser_version": "test",
        }
    ], columns=CHINA_EVENT_COLUMNS)
    ll2 = pd.DataFrame([
        {
            "launch_id": "ll2-660",
            "net_time": "2026-07-30T02:00:00Z",
            "rocket_name": "Long March 6A",
            "pad_name": "Taiyuan Satellite Launch Center",
            "orbit_abbrev": "SSO",
            "mission_type": "Communications",
            "provider_name": "China Aerospace Science and Technology Corporation",
        },
        {
            "launch_id": "ll2-unmatched",
            "net_time": "2026-07-31T02:00:00Z",
            "rocket_name": "Long March 7A",
            "pad_name": "Wenchang",
            "orbit_abbrev": "GTO",
            "mission_type": "Communications",
            "provider_name": "China Aerospace Science and Technology Corporation",
        },
    ])
    enriched = enrich_with_ll2(official, ll2)
    assert enriched.loc[0, "ll2_launch_id"] == "ll2-660"
    assert enriched.loc[0, "ll2_match_status"] == "matched"
    assert enriched.loc[0, "launch_time_precision"] == "timestamp"
    assert len(enriched) == 1


def test_china_monthly_comparison_is_zero_filled_and_reconciles_classes():
    events = pd.DataFrame([
        {"event_id": "national-1", "launch_date": "2024-01-10", "program_class": "national_program", "classification_status": "verified", "outcome_normalized": "Success", "rocket_family": "长征"},
        {"event_id": "jielong-1", "launch_date": "2024-03-10", "program_class": "state_owned_commercial", "classification_status": "verified", "outcome_normalized": "Success", "rocket_family": "捷龙"},
        {"event_id": "commercial-1", "launch_date": "2024-03-10", "program_class": "commercial_provider", "classification_status": "verified", "outcome_normalized": "Failure", "rocket_family": "Zhuque"},
    ])
    monthly = build_china_launch_monthly(events)
    assert monthly["launch_count"].sum() == 3
    assert monthly[(monthly["month"] == "2024-02")]["launch_count"].sum() == 0
    assert monthly[(monthly["month"] == "2024-03") & (monthly["program_class"] == "commercial_provider")]["failed_launch_count"].iloc[0] == 1
    family = build_rocket_family_summary(events)
    assert family["launch_count"].sum() == 3


def test_faa_parser_extracts_official_metrics():
    html = """
    <div class="field--name-field-value numbers__value text-center"><a>670</a></div>
    <div class="field--name-field-label numbers__detail text-center">Licensed Launches</div>
    <div class="field--name-field-value numbers__value text-center"><a>24</a></div>
    <div class="field--name-field-label numbers__detail text-center">Active Launch Licenses</div>
    """
    response = Mock(status_code=200, text=html, url="https://www.faa.gov/node/52196")
    response.raise_for_status.return_value = None
    with patch("src.hk_commercial_aerospace.sources.faa_commercial_space.requests.get", return_value=response):
        frame = fetch_faa_commercial_space_kpis()
    assert frame.set_index("metric").loc["Licensed Launches", "value"] == 670
    assert frame.set_index("metric").loc["Active Launch Licenses", "value"] == 24


def test_global_benchmark_keeps_world_china_us_only():
    csv = "Entity,Code,Year,Annual number of objects launched into outer space\nWorld,OWID_WRL,2024,2849\nChina,CHN,2024,270\nFrance,FRA,2024,2\nUnited States,USA,2024,2500\n"
    response = Mock(status_code=200, text=csv, url="https://ourworldindata.org/grapher/x.csv")
    response.raise_for_status.return_value = None
    with patch("src.hk_commercial_aerospace.sources.global_space_benchmark.requests.get", return_value=response):
        frame = fetch_global_objects_launched()
    assert set(frame["entity"]) == {"World", "China", "United States"}
    assert int(frame.loc[frame["entity"] == "World", "objects_launched"].iloc[0]) == 2849


def test_usaspending_drops_non_space_keyword_matches():
    payload = {
        "results": [
            {
                "Award ID": "GOOD",
                "Recipient Name": "Space Company",
                "Award Amount": 100,
                "Awarding Agency": "NASA",
                "Description": "Commercial launch services for a satellite mission",
                "Start Date": "2026-01-01",
                "End Date": "2027-01-01",
            },
            {
                "Award ID": "BAD",
                "Recipient Name": "Housing Company",
                "Award Amount": 200,
                "Awarding Agency": "DHS",
                "Description": "Commercial space rental for manufactured housing units",
                "Start Date": "2026-01-01",
                "End Date": "2027-01-01",
            },
        ]
    }
    response = Mock(status_code=200, url="https://api.usaspending.gov/api/v2/search/spending_by_award/")
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    with patch("src.hk_commercial_aerospace.sources.usaspending.requests.post", return_value=response):
        frame = fetch_commercial_space_contracts(keywords=["commercial space"], limit_per_keyword=10)
    assert list(frame["award_id"]) == ["GOOD"]


def test_celestrak_failed_fetch_is_not_reported_as_live():
    with patch(
        "src.hk_commercial_aerospace.sources.celestrak_satellites.requests.get",
        side_effect=RuntimeError("offline"),
    ):
        frame = fetch_all_constellations()
    assert frame.attrs["source"] == "unavailable"
    assert frame.attrs["partial"] is False


def test_ll2_history_is_append_only_and_used_when_current_fetch_is_unavailable(tmp_path):
    import src.hk_commercial_aerospace.sources.launch_library as launch_library

    history_path = tmp_path / "launch_events_history.jsonl"
    frame = pd.DataFrame([
        {
            "launch_id": "landspace-1",
            "name": "Zhuque-2E",
            "net_time": "2026-06-09T08:23:00Z",
            "status_abbrev": "Success",
            "status_name": "Launch Successful",
            "provider_id": 259,
            "provider_name": "LandSpace",
            "rocket_name": "Zhuque-2E",
            "rocket_family": "Zhuque",
            "pad_name": "Launch Area 96A",
            "orbit_abbrev": "LEO",
            "mission_type": "Communications",
            "launch_designator": None,
            "country_code": "CHN",
            "last_updated": "2026-06-09T09:00:00Z",
            "fetched_at": "2026-08-01T00:00:00Z",
        }
    ], columns=LL2_SCHEMA)
    frame.attrs["source"] = "live"

    with patch.object(launch_library, "HISTORY_PATH", history_path):
        _append_launch_history({"LandSpace": frame})
        _append_launch_history({"LandSpace": frame})
        merged = _merge_launch_history({
            "LandSpace": pd.DataFrame(columns=LL2_SCHEMA),
        })

    assert len(history_path.read_text(encoding="utf-8").splitlines()) == 1
    assert list(merged["LandSpace"]["launch_id"]) == ["landspace-1"]
    assert merged["LandSpace"].attrs["source"] == "history"
