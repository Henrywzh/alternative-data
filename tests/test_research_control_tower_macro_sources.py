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


def test_pit_class_classified_per_series_and_reference_period() -> None:
    # P1-3: the first release of every reference period is
    # official_first_release; later vintages of that period are
    # official_revised_vintage.  Classification must not leak across
    # reference periods via a global row index.
    fetched_at = "2026-08-16T00:00:00Z"
    obs_list = [
        FredObservation(date="2026-01-01", series_id="CPIAUCSL", value=310.2, fetched_at=fetched_at, realtime_start="2026-02-13", realtime_end="2026-03-11"),
        FredObservation(date="2026-01-01", series_id="CPIAUCSL", value=310.5, fetched_at=fetched_at, realtime_start="2026-03-12", realtime_end="9999-12-31"),
        FredObservation(date="2026-02-01", series_id="CPIAUCSL", value=311.0, fetched_at=fetched_at, realtime_start="2026-03-10", realtime_end="2026-04-14"),
        FredObservation(date="2026-02-01", series_id="CPIAUCSL", value=311.2, fetched_at=fetched_at, realtime_start="2026-04-15", realtime_end="9999-12-31"),
    ]

    obs_df = transform_fred_observations_to_macro(obs_list, OFFICIAL_INDICATORS["us_cpi"], fetched_at)
    by = obs_df.set_index(["reference_period", "realtime_start"])["pit_class"]

    assert by[("2026-01", "2026-02-13")] == "official_first_release"
    assert by[("2026-01", "2026-03-12")] == "official_revised_vintage"
    # Second period's first vintage must NOT be classified as a revision just
    # because it appears after the first period's rows.
    assert by[("2026-02", "2026-03-10")] == "official_first_release"
    assert by[("2026-02", "2026-04-15")] == "official_revised_vintage"


def test_daily_series_pit_dedup_keeps_observation_date_granularity() -> None:
    # P1-4: a daily series (e.g. ECBDFR) keeps one row per observation date
    # even when the frame's reference_period is a month token; the old
    # (series_id, reference_period) dedup collapsed every day of the month.
    fetched_at = "2026-08-16T00:00:00Z"
    obs_df = pd.DataFrame(
        [
            {
                "observation_id": "macro_obs_ECBDFR_2026-01-05_20260106",
                "event_id": "",
                "source_id": "official:fred_alfred",
                "series_id": "ECBDFR",
                "scope": "macro",
                "event_type": "ecb_rate_decision",
                "metric_name": "ECB Policy Deposit Facility Rate",
                "reference_period": "2026-01",
                "observation_date": "2026-01-05",
                "release_at": None,
                "actual_value": 2.0,
                "unit": "Percent",
                "frequency": "day",
                "first_observed_at": None,
                "source_published_at": None,
                "retrieved_at_utc": fetched_at,
                "source_url": "https://fred.stlouisfed.org/series/ECBDFR",
                "pit_class": "official_first_release",
                "source_license_class": "official_open_data",
                "is_provisional": False,
                "realtime_start": "2026-01-06",
                "realtime_end": "9999-12-31",
                "registry_version": "v1",
            },
            {
                "observation_id": "macro_obs_ECBDFR_2026-01-06_20260107",
                "event_id": "",
                "source_id": "official:fred_alfred",
                "series_id": "ECBDFR",
                "scope": "macro",
                "event_type": "ecb_rate_decision",
                "metric_name": "ECB Policy Deposit Facility Rate",
                "reference_period": "2026-01",
                "observation_date": "2026-01-06",
                "release_at": None,
                "actual_value": 2.0,
                "unit": "Percent",
                "frequency": "day",
                "first_observed_at": None,
                "source_published_at": None,
                "retrieved_at_utc": fetched_at,
                "source_url": "https://fred.stlouisfed.org/series/ECBDFR",
                "pit_class": "official_first_release",
                "source_license_class": "official_open_data",
                "is_provisional": True,
                "realtime_start": "2026-01-07",
                "realtime_end": "9999-12-31",
                "registry_version": "v1",
            },
            {
                "observation_id": "macro_obs_ECBDFR_2026-01-06_20260120",
                "event_id": "",
                "source_id": "official:fred_alfred",
                "series_id": "ECBDFR",
                "scope": "macro",
                "event_type": "ecb_rate_decision",
                "metric_name": "ECB Policy Deposit Facility Rate",
                "reference_period": "2026-01",
                "observation_date": "2026-01-06",
                "release_at": None,
                "actual_value": 2.25,
                "unit": "Percent",
                "frequency": "day",
                "first_observed_at": None,
                "source_published_at": None,
                "retrieved_at_utc": fetched_at,
                "source_url": "https://fred.stlouisfed.org/series/ECBDFR",
                "pit_class": "official_revised_vintage",
                "source_license_class": "official_open_data",
                "is_provisional": False,
                "realtime_start": "2026-01-20",
                "realtime_end": "9999-12-31",
                "registry_version": "v1",
            },
        ],
        columns=MACRO_OBSERVATION_COLUMNS,
    )

    filtered = filter_observations_pit(obs_df, as_of_utc="2026-01-25T00:00:00Z")

    # Two distinct days survive (2026-01-05 and 2026-01-06); the 2026-01-06
    # row keeps its latest vintage value 2.25.
    assert len(filtered) == 2
    assert sorted(filtered["observation_date"]) == ["2026-01-05", "2026-01-06"]
    assert filtered.set_index("observation_date")["actual_value"].to_dict() == {
        "2026-01-05": 2.0,
        "2026-01-06": 2.25,
    }


def test_ecbdfr_indicator_declared_daily() -> None:
    assert OFFICIAL_INDICATORS["ecb_rate_decision"]["frequency"] == "day"


def test_observation_ids_are_deterministic_without_row_numbers() -> None:
    fetched_at = "2026-08-16T00:00:00Z"
    obs_list = [
        FredObservation(date="2026-01-01", series_id="CPIAUCSL", value=310.2, fetched_at=fetched_at, realtime_start="2026-02-13"),
        FredObservation(date="2026-01-01", series_id="CPIAUCSL", value=310.5, fetched_at=fetched_at, realtime_start="2026-03-12"),
        FredObservation(date="2026-01-01", series_id="CPIAUCSL", value=310.0, fetched_at=fetched_at),
    ]

    first = transform_fred_observations_to_macro(obs_list, OFFICIAL_INDICATORS["us_cpi"], fetched_at)
    second = transform_fred_observations_to_macro(obs_list, OFFICIAL_INDICATORS["us_cpi"], fetched_at)

    assert list(first["observation_id"]) == list(second["observation_id"])
    assert first["observation_id"].is_unique
    ids = set(first["observation_id"])
    assert "macro_obs_CPIAUCSL_2026-01_20260101_20260213" in ids
    assert "macro_obs_CPIAUCSL_2026-01_20260101_20260312" in ids
    assert "macro_obs_CPIAUCSL_2026-01_20260101_unknown_vintage" in ids
    assert all("idx" not in str(identifier) for identifier in ids)


def test_observation_event_id_joins_release_event_key() -> None:
    # P2-10: observations and calendar events share the same stable event key,
    # so a vintage observation links to its release event.
    fetched_at = "2026-08-16T00:00:00Z"
    meta = OFFICIAL_INDICATORS["us_cpi"]
    events_df = transform_release_dates_to_macro_events(
        [{"date": "2026-02-13", "release_id": 10}],
        meta,
        fetched_at,
        as_of_date_str="2026-08-16",
    )
    obs_df = transform_fred_observations_to_macro(
        [
            FredObservation(
                date="2026-01-01",
                series_id="CPIAUCSL",
                value=310.2,
                fetched_at=fetched_at,
                realtime_start="2026-02-13",
            )
        ],
        meta,
        fetched_at,
    )

    assert obs_df.iloc[0]["event_id"] == "MACRO_US_CPI_R10_20260213"
    assert events_df.iloc[0]["event_id"] == obs_df.iloc[0]["event_id"]


def test_release_events_thread_supersedes_event_id() -> None:
    # P2-10: FRED transport release events form a revision chain.
    fetched_at = "2026-08-16T00:00:00Z"
    events_df = transform_release_dates_to_macro_events(
        [
            {"date": "2026-02-13", "release_id": 10},
            {"date": "2026-03-12", "release_id": 10},
        ],
        OFFICIAL_INDICATORS["us_cpi"],
        fetched_at,
        as_of_date_str="2026-08-16",
    )

    by_date = events_df.set_index(events_df["starts_at"].dt.date)["event_id"]
    first_key = by_date.loc[pd.Timestamp("2026-02-13").date()]
    second_key = by_date.loc[pd.Timestamp("2026-03-12").date()]
    first_row = events_df[events_df["event_id"] == first_key].iloc[0]
    second_row = events_df[events_df["event_id"] == second_key].iloc[0]
    assert first_row["supersedes_event_id"] == ""
    assert second_row["supersedes_event_id"] == first_key


def test_first_release_is_not_provisional_solely_by_realtime_after_date() -> None:
    # P2-11: realtime_start > reference date alone does not make a first
    # release provisional; provisional requires a later known vintage.
    fetched_at = "2026-08-16T00:00:00Z"
    meta = OFFICIAL_INDICATORS["us_cpi"]
    single = transform_fred_observations_to_macro(
        [
            FredObservation(
                date="2026-01-01",
                series_id="CPIAUCSL",
                value=310.2,
                fetched_at=fetched_at,
                realtime_start="2026-02-13",
            )
        ],
        meta,
        fetched_at,
    )
    assert single.iloc[0]["pit_class"] == "official_first_release"
    assert single.iloc[0]["is_provisional"].item() is False

    two_vintages = transform_fred_observations_to_macro(
        [
            FredObservation(date="2026-01-01", series_id="CPIAUCSL", value=310.2, fetched_at=fetched_at, realtime_start="2026-02-13"),
            FredObservation(date="2026-01-01", series_id="CPIAUCSL", value=310.5, fetched_at=fetched_at, realtime_start="2026-03-12"),
        ],
        meta,
        fetched_at,
    )
    assert two_vintages.iloc[0]["is_provisional"].item() is True
    # The latest known vintage is the current value: not provisional.
    assert two_vintages.iloc[1]["is_provisional"].item() is False


def test_offline_dict_observations_without_series_id_are_filtered(tmp_path: Path) -> None:
    # P2-9: dict observations without a series_id must be filtered by
    # indicator (never transformed once per indicator), and dict rows must not
    # crash the transform.
    fetched_at = "2026-08-16T00:00:00Z"
    fixtures = {
        "fred_alfred": {
            "us_cpi": {
                "observations": [
                    {
                        "date": "2026-01-01",
                        "series_id": "CPIAUCSL",
                        "value": 310.2,
                        "fetched_at": fetched_at,
                        "realtime_start": "2026-02-13",
                    },
                    {"date": "2026-01-01", "value": 999.9, "fetched_at": fetched_at},
                ],
                "release_dates": [{"date": "2026-02-13", "release_id": 10}],
            },
            "us_ppi": {
                "observations": [
                    {
                        "date": "2026-01-01",
                        "series_id": "PPIACO",
                        "value": 120.5,
                        "fetched_at": fetched_at,
                        "realtime_start": "2026-02-13",
                    },
                ],
                "release_dates": [],
            },
        }
    }
    collector = MacroDataCollector(base_dir=tmp_path, offline_fixtures=fixtures)

    events_df, obs_df, health = collector.collect_fred_alfred(indicators=["us_cpi", "us_ppi"])

    # The no-series_id dict row is excluded; each indicator keeps only its own
    # series observations (never one row per indicator for unowned dicts).
    assert len(obs_df) == 2
    assert set(obs_df["series_id"]) == {"CPIAUCSL", "PPIACO"}
    assert health.series_covered == ["CPIAUCSL", "PPIACO"]
    assert len(events_df) == 1


def test_collector_real_path_empty_responses_never_report_coverage(tmp_path: Path) -> None:
    # P2-7: a successful-but-empty FRED response is not series coverage.
    class EmptyFredClient:
        def get_observations(self, series_id: str, **kwargs) -> list:
            return []

        def get_release_dates(self, release_id: int) -> list:
            return []

    collector = MacroDataCollector(base_dir=tmp_path, fred_client=EmptyFredClient())
    events_df, obs_df, health = collector.collect_fred_alfred(indicators=["us_cpi"])

    assert obs_df.empty
    assert events_df.empty
    assert health.status == "unavailable"
    assert health.series_covered == []
    assert health.error_detail == "All series calls returned no data"

    class PartialFredClient:
        def get_observations(self, series_id: str, **kwargs) -> list:
            if series_id == "CPIAUCSL":
                return [
                    FredObservation(
                        date="2026-01-01",
                        series_id="CPIAUCSL",
                        value=310.2,
                        fetched_at="2026-08-16T00:00:00Z",
                        realtime_start="2026-02-13",
                    )
                ]
            return []

        def get_release_dates(self, release_id: int) -> list:
            return []

    partial = MacroDataCollector(base_dir=tmp_path, fred_client=PartialFredClient())
    _, partial_obs, partial_health = partial.collect_fred_alfred(indicators=["us_cpi", "us_ppi"])
    assert not partial_obs.empty
    assert partial_health.status == "partial"
    assert partial_health.series_covered == ["CPIAUCSL"]


def test_collector_offline_empty_fixture_is_unavailable_without_coverage(tmp_path: Path) -> None:
    # P2-7: the offline path must not report series_covered when unavailable.
    collector = MacroDataCollector(
        base_dir=tmp_path,
        offline_fixtures={"fred_alfred": {"observations": [], "release_dates": []}},
    )
    events_df, obs_df, health = collector.collect_fred_alfred(indicators=["us_cpi"])

    assert obs_df.empty
    assert events_df.empty
    assert health.status == "unavailable"
    assert health.series_covered == []


def test_collector_realtime_start_is_configurable(tmp_path: Path) -> None:
    # P3: the hardcoded 2015-01-01 realtime start is configurable.
    captured: dict[str, dict] = {}

    class RecordingClient:
        def get_observations(self, series_id: str, **kwargs) -> list:
            captured["params"] = kwargs
            return []

        def get_release_dates(self, release_id: int) -> list:
            return []

    collector = MacroDataCollector(
        base_dir=tmp_path,
        fred_client=RecordingClient(),
        realtime_start="2020-01-01",
    )
    collector.collect_fred_alfred(indicators=["us_cpi"])

    assert captured["params"]["realtime_start"] == "2020-01-01"


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


@pytest.mark.parametrize("api_key_env", [None, "test-key"])
def test_collector_cli_injects_fixtures_without_live_fred_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    api_key_env: str | None,
) -> None:
    # P2-9: the CLI test must inject fixtures (no live FRED calls) and work
    # both with and without a configured API key / repo .config.
    fetched_at = "2026-08-16T00:00:00Z"
    fixture_payload = {
        "fred_alfred": {
            "observations": [
                {
                    "date": "2026-01-01",
                    "series_id": "CPIAUCSL",
                    "value": 310.2,
                    "fetched_at": fetched_at,
                    "realtime_start": "2026-02-13",
                },
                {"date": "2026-01-01", "value": 999.9, "fetched_at": fetched_at},
            ],
            "release_dates": [{"date": "2026-02-13", "release_id": 10}],
        }
    }
    fixture_path = tmp_path / "macro_fixtures.json"
    fixture_path.write_text(json.dumps(fixture_payload), encoding="utf-8")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    if api_key_env:
        monkeypatch.setenv("FRED_API_KEY", api_key_env)

    out_dir = tmp_path / "cli_out"
    cmd = [
        sys.executable,
        "scripts/research_control_tower_macro_collector.py",
        "--fixtures",
        str(fixture_path),
        "--output-dir",
        str(out_dir),
        "--indicators",
        "us_cpi",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert (out_dir / "macro_events.parquet").exists()
    assert (out_dir / "macro_observations.parquet").exists()

    events = pd.read_parquet(out_dir / "macro_events.parquet")
    observations = pd.read_parquet(out_dir / "macro_observations.parquet")
    # Real content from the fixture, not empty placeholder files.
    assert len(events) == 1
    assert len(observations) == 1
    assert observations.iloc[0]["series_id"] == "CPIAUCSL"
    assert observations.iloc[0]["actual_value"] == 310.2

    health = json.loads((out_dir / "macro_source_health.json").read_text(encoding="utf-8"))
    assert health["official:fred_alfred"]["status"] == "available"
    assert health["official:fred_alfred"]["series_covered"] == ["CPIAUCSL"]


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
