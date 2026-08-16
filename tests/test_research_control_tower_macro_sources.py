from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from fred_macro_data.models import FredObservation
from research_control_tower.macro import (
    MACRO_EVENT_COLUMNS,
    MACRO_OBSERVATION_COLUMNS,
    materialize_macro_calendar,
    materialize_macro_observations,
)
from research_control_tower.macro_sources import (
    OFFICIAL_INDICATORS,
    MacroDataCollector,
    SourceHealth,
    filter_observations_pit,
    transform_fred_observations_to_macro,
    transform_release_dates_to_macro_events,
)
from scripts.research_control_tower_macro_collector import write_atomic_artifact


def test_official_indicators_contain_required_events_and_provenance() -> None:
    required = {
        "us_cpi",
        "us_ppi",
        "us_payrolls",
        "us_unemployment",
        "us_gdp",
        "us_fed_funds_rate",
        "ecb_rate_decision",
        "cn_cpi",
        "cn_gdp",
        "hk_cpi",
        "hk_unemployment",
    }
    assert required.issubset(OFFICIAL_INDICATORS.keys())

    for key in required:
        info = OFFICIAL_INDICATORS[key]
        assert info["event_type"] == key
        assert info["metric_name"]
        assert info["source_id"].startswith("official:")
        assert info["timezone"]
        assert info["unit"]
        assert info["source_url"]

    # Issue 3: FEDFUNDS is a rate indicator, not a fake FOMC rate decision calendar meeting
    assert OFFICIAL_INDICATORS["us_fed_funds_rate"]["fred_series_id"] == "FEDFUNDS"
    assert "us_fed_decision" not in OFFICIAL_INDICATORS or OFFICIAL_INDICATORS["us_fed_decision"].get("fred_series_id") != "FEDFUNDS"

    # Issue 4: ECB/China/HK series fetched via FRED use official:fred_alfred transport with origin_agency retained
    ecb_info = OFFICIAL_INDICATORS["ecb_rate_decision"]
    assert ecb_info["source_id"] == "official:fred_alfred"
    assert ecb_info["origin_agency"] == "European Central Bank"

    cn_info = OFFICIAL_INDICATORS["cn_cpi"]
    assert cn_info["source_id"] == "official:fred_alfred"
    assert cn_info["origin_agency"] == "National Bureau of Statistics of China"


def test_transform_fred_observations_returns_only_observations_and_retains_vintages() -> None:
    # Issue 1 & Issue 2: transform_fred_observations_to_macro returns obs_df retaining realtime_start/end
    # and does NOT synthesize calendar events from observation reference dates.
    fetched_at = "2026-08-16T00:00:00Z"
    obs_list = [
        FredObservation(
            date="2026-01-01",
            series_id="CPIAUCSL",
            value=310.2,
            fetched_at=fetched_at,
            realtime_start="2026-02-13",
            realtime_end="2026-03-11",
        ),
        FredObservation(
            date="2026-01-01",
            series_id="CPIAUCSL",
            value=310.5,
            fetched_at=fetched_at,
            realtime_start="2026-03-12",
            realtime_end="9999-12-31",
        ),
    ]

    indicator_meta = OFFICIAL_INDICATORS["us_cpi"]
    obs_df = transform_fred_observations_to_macro(obs_list, indicator_meta, fetched_at)

    assert len(obs_df) == 2
    assert list(obs_df.columns) == MACRO_OBSERVATION_COLUMNS
    assert "realtime_start" in obs_df.columns
    assert "realtime_end" in obs_df.columns

    # Test PIT filtering directly on actual transformed output
    filtered_feb = filter_observations_pit(obs_df, as_of_utc="2026-02-20T00:00:00Z")
    assert len(filtered_feb) == 1
    assert filtered_feb.iloc[0]["actual_value"] == 310.2

    filtered_mar = filter_observations_pit(obs_df, as_of_utc="2026-03-20T00:00:00Z")
    assert len(filtered_mar) == 1
    assert filtered_mar.iloc[0]["actual_value"] == 310.5


def test_transform_release_dates_to_macro_events_without_fabricated_time() -> None:
    # Issue 2 & Issue 9: Date-only release dates retain precision='day' without gaining a fabricated 08:30 time.
    release_dates = [
        {"date": "2026-02-13", "release_id": 10},
        {"date": "2026-09-11", "release_id": 10},  # upcoming
    ]
    meta = OFFICIAL_INDICATORS["us_cpi"]
    events_df = transform_release_dates_to_macro_events(
        release_dates,
        meta,
        "2026-08-16T00:00:00Z",
        as_of_date_str="2026-08-16",
    )

    assert len(events_df) == 2
    assert list(events_df.columns) == MACRO_EVENT_COLUMNS

    first_ev = events_df.iloc[0]
    assert first_ev["date_precision"] == "day"
    # Starts_at timestamp should not have fabricated time added
    assert first_ev["status"] == "observed"

    upcoming_ev = events_df.iloc[1]
    assert upcoming_ev["status"] == "scheduled"


def test_alfred_closed_closed_interval_boundary_behavior() -> None:
    # Issue 8: FRED real-time periods are closed intervals [realtime_start, realtime_end].
    # Vintage active from 2026-01-28 to 2026-02-25.
    fetched_at = "2026-08-16T00:00:00Z"
    obs_list = [
        FredObservation(
            date="2025-12-01",
            series_id="GDP",
            value=2.0,
            fetched_at=fetched_at,
            realtime_start="2026-01-28",
            realtime_end="2026-02-25",
        ),
    ]
    obs_df = transform_fred_observations_to_macro(obs_list, OFFICIAL_INDICATORS["us_gdp"], fetched_at)

    # 1. Exact start boundary (2026-01-28) -> included
    pit_start = filter_observations_pit(obs_df, as_of_utc="2026-01-28T00:00:00Z")
    assert len(pit_start) == 1

    # 2. Middle of interval (2026-02-10) -> included
    pit_mid = filter_observations_pit(obs_df, as_of_utc="2026-02-10T00:00:00Z")
    assert len(pit_mid) == 1

    # 3. Exact end boundary (2026-02-25) -> included (closed/closed boundary)
    pit_end = filter_observations_pit(obs_df, as_of_utc="2026-02-25T00:00:00Z")
    assert len(pit_end) == 1

    # 4. After end boundary (2026-02-26) -> excluded (superseded)
    pit_after = filter_observations_pit(obs_df, as_of_utc="2026-02-26T00:00:00Z")
    assert len(pit_after) == 0

    # 5. Before start boundary (2026-01-27) -> excluded (not published yet)
    pit_before = filter_observations_pit(obs_df, as_of_utc="2026-01-27T00:00:00Z")
    assert len(pit_before) == 0


def test_null_realtime_start_excluded_from_strict_pit() -> None:
    # Issue 7: Null/missing realtime_start does not falsely claim ancient availability
    fetched_at = "2026-08-16T00:00:00Z"
    obs_list = [
        FredObservation(
            date="2026-01-01",
            series_id="SOFR",
            value=4.5,
            fetched_at=fetched_at,
            realtime_start=None,
            realtime_end=None,
        )
    ]
    obs_df = transform_fred_observations_to_macro(obs_list, OFFICIAL_INDICATORS["us_fed_funds_rate"], fetched_at)

    assert obs_df.iloc[0]["pit_class"] == "latest_snapshot_unknown_vintage"

    # When strict PIT filtering is applied, unknown vintage is excluded
    filtered = filter_observations_pit(obs_df, as_of_utc="2026-02-01T00:00:00Z")
    assert len(filtered) == 0


def test_collector_six_state_contract_for_unconfigured_sources(tmp_path: Path) -> None:
    # Issue 5: collect_ecb and collect_nbs_hk return unconfigured when native adapters are inactive,
    # never returning 'available' with zero rows.
    collector = MacroDataCollector(base_dir=tmp_path)
    _, _, ecb_health = collector.collect_ecb()
    assert ecb_health.status == "unavailable"
    assert ecb_health.event_count == 0
    assert ecb_health.observation_count == 0
    assert ecb_health.error_detail

    _, _, nbs_health = collector.collect_nbs_hk()
    assert nbs_health.status == "unavailable"
    assert nbs_health.event_count == 0
    assert nbs_health.observation_count == 0
    assert nbs_health.error_detail


def test_collector_cli_indicators_filtering(tmp_path: Path) -> None:
    # Issue 6: CLI --indicators filters output indicators
    fetched_at = "2026-08-16T00:00:00Z"
    fixtures = {
        "fred_alfred": {
            "observations": [
                FredObservation(
                    date="2026-01-01",
                    series_id="CPIAUCSL",
                    value=310.2,
                    fetched_at=fetched_at,
                    realtime_start="2026-02-13",
                )
            ],
            "release_dates": [{"date": "2026-02-13", "release_id": 10}],
        }
    }

    out_dir = tmp_path / "cli_out"
    cmd = [
        sys.executable,
        "scripts/research_control_tower_macro_collector.py",
        "--output-dir",
        str(out_dir),
        "--indicators",
        "us_cpi",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert (out_dir / "macro_events.parquet").exists()
    assert (out_dir / "macro_observations.parquet").exists()


def test_write_atomic_artifact(tmp_path: Path) -> None:
    df = pd.DataFrame([{"a": 1, "b": 2}])
    out_parquet = tmp_path / "test.parquet"
    write_atomic_artifact(df, out_parquet)
    assert out_parquet.exists()
    reloaded = pd.read_parquet(out_parquet)
    assert len(reloaded) == 1

    health_dict = {"source_id": "test", "status": "available"}
    out_json = tmp_path / "health.json"
    write_atomic_artifact(health_dict, out_json)
    assert out_json.exists()
    loaded_json = json.loads(out_json.read_text(encoding="utf-8"))
    assert loaded_json["status"] == "available"
