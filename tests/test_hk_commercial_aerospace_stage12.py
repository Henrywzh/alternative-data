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
