from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from src.fred_macro_data.models import FredObservation
from src.research_control_tower.macro import (
    MACRO_EVENT_COLUMNS,
    materialize_macro_calendar,
    materialize_macro_observations,
)
from src.research_control_tower.macro_sources import (
    MACRO_OBSERVATION_COLUMNS,
    OFFICIAL_INDICATORS,
    MacroDataCollector,
    SourceHealth,
    filter_observations_pit,
    transform_fred_observations_to_macro,
)
from scripts.research_control_tower_macro_collector import write_atomic_artifact


def test_official_indicators_contain_required_events() -> None:
    required = {
        "us_cpi",
        "us_ppi",
        "us_payrolls",
        "us_unemployment",
        "us_gdp",
        "us_fed_decision",
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


def test_transform_fred_observations_to_macro() -> None:
    fetched_at = "2026-08-16T00:00:00Z"
    obs_list = [
        FredObservation(
            date="2026-01-01",
            series_id="CPIAUCSL",
            value=310.2,
            fetched_at=fetched_at,
            realtime_start="2026-02-13",
            realtime_end="9999-12-31",
        ),
        FredObservation(
            date="2026-02-01",
            series_id="CPIAUCSL",
            value=311.0,
            fetched_at=fetched_at,
            realtime_start="2026-03-12",
            realtime_end="9999-12-31",
        ),
    ]

    indicator_meta = OFFICIAL_INDICATORS["us_cpi"]
    events_df, obs_df = transform_fred_observations_to_macro(obs_list, indicator_meta, fetched_at)

    assert len(events_df) == 2
    assert len(obs_df) == 2
    assert list(events_df.columns) == MACRO_EVENT_COLUMNS
    assert list(obs_df.columns) == MACRO_OBSERVATION_COLUMNS

    first_obs = obs_df.iloc[0]
    assert first_obs["series_id"] == "CPIAUCSL"
    assert first_obs["reference_period"] == "2026-01"
    assert first_obs["actual_value"] == 310.2
    assert first_obs["unit"] == "Index 1982-1984=100"


def test_alfred_vintage_pit_filtering_prevents_future_lookahead() -> None:
    # Reference period 2026-Q1 has two vintages:
    # 1. First advance estimate published on 2026-04-28 with value 2.0
    # 2. Revised estimate published on 2026-05-28 with value 2.3
    rows = [
        {
            "observation_id": "obs_1",
            "event_id": "MACRO_US_GDP_2026-Q1",
            "source_id": "official:bea_fred",
            "series_id": "GDP",
            "scope": "macro",
            "event_type": "us_gdp",
            "metric_name": "Gross Domestic Product (GDP)",
            "reference_period": "2026-Q1",
            "observation_date": "2026-03-31",
            "release_at": "2026-04-28",
            "actual_value": 2.0,
            "unit": "Percent",
            "frequency": "quarter",
            "first_observed_at": "2026-04-28T12:30:00Z",
            "source_published_at": "2026-04-28",
            "retrieved_at_utc": "2026-08-16T00:00:00Z",
            "source_url": "https://www.bea.gov/",
            "pit_class": "official_first_release",
            "source_license_class": "public_domain",
            "is_provisional": True,
            "realtime_start": "2026-04-28",
            "realtime_end": "2026-05-27",
            "registry_version": "v1",
        },
        {
            "observation_id": "obs_2",
            "event_id": "MACRO_US_GDP_2026-Q1",
            "source_id": "official:bea_fred",
            "series_id": "GDP",
            "scope": "macro",
            "event_type": "us_gdp",
            "metric_name": "Gross Domestic Product (GDP)",
            "reference_period": "2026-Q1",
            "observation_date": "2026-03-31",
            "release_at": "2026-05-28",
            "actual_value": 2.3,
            "unit": "Percent",
            "frequency": "quarter",
            "first_observed_at": "2026-05-28T12:30:00Z",
            "source_published_at": "2026-05-28",
            "retrieved_at_utc": "2026-08-16T00:00:00Z",
            "source_url": "https://www.bea.gov/",
            "pit_class": "official_revised_vintage",
            "source_license_class": "public_domain",
            "is_provisional": False,
            "realtime_start": "2026-05-28",
            "realtime_end": "9999-12-31",
            "registry_version": "v1",
        },
    ]
    df = pd.DataFrame(rows)

    # As of 2026-05-01 (before revision): should return only the advance estimate (2.0)
    as_of_may1 = filter_observations_pit(df, as_of_utc="2026-05-01T00:00:00Z")
    assert len(as_of_may1) == 1
    assert as_of_may1.iloc[0]["actual_value"] == 2.0
    assert as_of_may1.iloc[0]["realtime_start"] == "2026-04-28"

    # As of 2026-06-01 (after revision): should return the revised estimate (2.3)
    as_of_june1 = filter_observations_pit(df, as_of_utc="2026-06-01T00:00:00Z")
    assert len(as_of_june1) == 1
    assert as_of_june1.iloc[0]["actual_value"] == 2.3
    assert as_of_june1.iloc[0]["realtime_start"] == "2026-05-28"

    # As of 2026-04-01 (before advance release): should return zero rows
    as_of_april1 = filter_observations_pit(df, as_of_utc="2026-04-01T00:00:00Z")
    assert len(as_of_april1) == 0


def test_collector_health_reporting_with_fixtures(tmp_path: Path) -> None:
    fetched_at = "2026-08-16T00:00:00Z"
    obs_list = [
        FredObservation(
            date="2026-01-01",
            series_id="CPIAUCSL",
            value=310.2,
            fetched_at=fetched_at,
        )
    ]

    fixtures = {
        "fred_alfred": {
            "observations": obs_list,
        },
        "bls": {
            "status": "available",
            "events": pd.DataFrame(columns=MACRO_EVENT_COLUMNS),
            "observations": pd.DataFrame(columns=MACRO_OBSERVATION_COLUMNS),
        },
        "bea": {
            "status": "unconfigured",
            "error_detail": "BEA API key not configured",
        },
    }

    collector = MacroDataCollector(base_dir=tmp_path, offline_fixtures=fixtures)
    events_df, obs_df, health_map = collector.collect_all()

    assert "official:fred_alfred" in health_map
    assert health_map["official:fred_alfred"]["status"] == "available"
    assert health_map["official:fred_alfred"]["observation_count"] == 1

    assert "official:bea" in health_map
    assert health_map["official:bea"]["status"] == "unconfigured"
    assert health_map["official:bea"]["error_detail"] == "BEA API key not configured"


def test_collector_unconfigured_fred_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    collector = MacroDataCollector(base_dir=tmp_path)
    events_df, obs_df, health = collector.collect_fred_alfred()

    assert health.status == "unconfigured"
    assert "missing or unconfigured" in health.error_detail.lower()
    assert events_df.empty
    assert obs_df.empty


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


def test_macro_collector_cli_run(tmp_path: Path) -> None:
    out_dir = tmp_path / "collector_output"
    cmd = [
        sys.executable,
        "scripts/research_control_tower_macro_collector.py",
        "--output-dir",
        str(out_dir),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert (out_dir / "macro_events.parquet").exists()
    assert (out_dir / "macro_observations.parquet").exists()
    assert (out_dir / "macro_source_health.json").exists()


def test_materialize_macro_observations_pure_function() -> None:
    raw_obs = [
        {
            "observation_id": "obs_100",
            "event_id": "MACRO_TEST_01",
            "source_id": "official:test",
            "series_id": "TEST_SERIES",
            "scope": "macro",
            "event_type": "test_event",
            "metric_name": "Test Metric",
            "reference_period": "2026-06",
            "observation_date": "2026-06-01",
            "release_at": "2026-06-15",
            "actual_value": 4.5,
            "unit": "Percent",
            "frequency": "month",
        }
    ]
    df = materialize_macro_observations(raw_obs)
    assert len(df) == 1
    assert list(df.columns) == MACRO_OBSERVATION_COLUMNS
    assert df.iloc[0]["actual_value"] == 4.5
    assert df.iloc[0]["metric_name"] == "Test Metric"
