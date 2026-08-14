from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from src.research_control_tower.events import (
    EventBundle,
    compute_t_minus,
    is_catalyst_eligible,
    load_event_bundle,
    validate_event_bundle,
)
from src.research_control_tower.macro import materialize_macro_calendar
from src.research_control_tower.registries import load_registry_bundle


@pytest.fixture()
def registry_root() -> Path:
    return Path(__file__).parents[1] / "config" / "research_control_tower"


@pytest.fixture()
def registry_bundle(registry_root):
    return load_registry_bundle(registry_root)


@pytest.fixture()
def event_bundle(registry_root):
    return load_event_bundle(registry_root)


def test_hard_event_requires_source_and_exact_observation(event_bundle, registry_bundle):
    issues = validate_event_bundle(
        event_bundle,
        registry_bundle,
        pd.Timestamp("2026-08-13T00:00:00Z"),
    )

    assert not [issue for issue in issues if issue.code == "hard_event_missing_source"]
    assert not [
        issue for issue in issues if issue.code == "hard_event_requires_exact_date"
    ]


def test_thesis_checkpoint_preserves_window(event_bundle):
    row = event_bundle.events.set_index("event_id").loc[
        "AI_HBM4_QUALIFICATION_WINDOW"
    ]

    assert row["certainty_class"] == "thesis_checkpoint"
    assert row["date_precision"] in {"month", "quarter", "half", "year"}
    assert pd.notna(row["starts_at"]) and pd.notna(row["ends_at"])
    assert row["starts_at"] <= row["ends_at"]


def test_event_links_resolve_to_registry(event_bundle, registry_bundle):
    issues = validate_event_bundle(
        event_bundle,
        registry_bundle,
        pd.Timestamp("2026-08-13T00:00:00Z"),
    )

    assert not [
        issue for issue in issues if issue.code.startswith("orphan_event_link")
    ]


def test_representative_ledger_spans_scopes_and_required_links(event_bundle):
    assert {"company", "basket", "macro", "policy", "index"} <= set(
        event_bundle.events["scope"]
    )
    assert {"hard", "thesis_checkpoint", "observed"} <= set(
        event_bundle.events["certainty_class"]
    )
    assert "provisional" not in set(event_bundle.events["certainty_class"])

    sk_links = event_bundle.event_links[
        event_bundle.event_links["target_id"].isin({"SK_HYNIX", "AI_BOTTLENECKS_GLOBAL"})
    ]
    assert {"SK_HYNIX", "AI_BOTTLENECKS_GLOBAL"} <= set(sk_links["target_id"])
    assert {
        "AI_ADVANCED_PACKAGING_WINDOW",
        "AI_CPO_RAMP_WINDOW",
        "AI_POWER_GRID_WINDOW",
    } <= set(event_bundle.events["event_id"])


def test_event_observation_key_and_supersession_direction(event_bundle, registry_bundle):
    observations = event_bundle.events[
        ["event_key", "first_observed_at", "observation_version"]
    ].copy()
    observations["first_observed_at"] = pd.to_datetime(
        observations["first_observed_at"], utc=True
    )
    assert not observations.duplicated().any()

    revisions = event_bundle.events[
        event_bundle.events["supersedes_event_id"].astype("string").str.strip().ne("")
    ]
    assert not revisions.empty
    by_id = event_bundle.events.set_index("event_id")
    for _, row in revisions.iterrows():
        prior = by_id.loc[row["supersedes_event_id"]]
        assert prior["event_key"] == row["event_key"]
        assert prior["first_observed_at"] < row["first_observed_at"]
        assert prior["observation_version"] < row["observation_version"]

    issues = validate_event_bundle(
        event_bundle,
        registry_bundle,
        pd.Timestamp("2026-08-13T00:00:00Z"),
    )
    assert not [
        issue
        for issue in issues
        if issue.code in {"duplicate_event_observation_key", "invalid_supersession_direction"}
    ]


def test_supersession_rejects_branching_history(event_bundle, registry_bundle):
    events = event_bundle.events.astype(object)
    revision = events.loc[
        events["event_id"] == "AI_HBM4_QUALIFICATION_WINDOW_V2"
    ].iloc[0].copy()
    revision["event_id"] = "AI_HBM4_QUALIFICATION_WINDOW_V2_BRANCH"
    revision["first_observed_at"] = pd.Timestamp("2026-08-14T00:00:00Z")
    invalid = pd.concat([events, pd.DataFrame([revision])], ignore_index=True)

    issues = validate_event_bundle(
        replace(event_bundle, events=invalid),
        registry_bundle,
        pd.Timestamp("2026-08-14T00:00:00Z"),
    )

    assert any(issue.code == "branched_supersession_chain" for issue in issues)


def test_supersession_rejects_skipped_version(event_bundle, registry_bundle):
    events = event_bundle.events.astype(object)
    revision = events.loc[
        events["event_id"] == "AI_HBM4_QUALIFICATION_WINDOW_V2"
    ].iloc[0].copy()
    revision["event_id"] = "AI_HBM4_QUALIFICATION_WINDOW_V4"
    revision["observation_version"] = 4
    revision["first_observed_at"] = pd.Timestamp("2026-08-14T00:00:00Z")
    invalid = pd.concat([events, pd.DataFrame([revision])], ignore_index=True)

    issues = validate_event_bundle(
        replace(event_bundle, events=invalid),
        registry_bundle,
        pd.Timestamp("2026-08-14T00:00:00Z"),
    )

    assert any(
        issue.code == "noncontiguous_observation_versions" for issue in issues
    )


def test_watch_only_listing_is_not_eligible_for_automated_links(
    event_bundle, registry_bundle
):
    watch_only_listing = registry_bundle.listings.loc[
        ~registry_bundle.listings["collection_eligible"].fillna(False).astype(bool),
        "listing_id",
    ].iloc[0]
    row = event_bundle.event_links.iloc[0].copy()
    row["target_type"] = "listing"
    row["target_id"] = watch_only_listing
    row["link_role"] = "automated"
    invalid_links = pd.concat(
        [event_bundle.event_links, pd.DataFrame([row])], ignore_index=True
    )

    issues = validate_event_bundle(
        replace(event_bundle, event_links=invalid_links),
        registry_bundle,
        pd.Timestamp("2026-08-13T00:00:00Z"),
    )

    assert any(issue.code == "ineligible_automated_listing_link" for issue in issues)


def test_thesis_checkpoint_requires_watch_question(event_bundle, registry_bundle):
    questions = event_bundle.event_watch_questions[
        event_bundle.event_watch_questions["event_id"] != "AI_HBM4_QUALIFICATION_WINDOW"
    ]
    invalid = replace(event_bundle, event_watch_questions=questions)

    issues = validate_event_bundle(
        invalid,
        registry_bundle,
        pd.Timestamp("2026-08-13T00:00:00Z"),
    )

    assert any(issue.code == "thesis_checkpoint_missing_watch_question" for issue in issues)


def test_source_timestamps_must_be_timezone_aware(event_bundle, registry_bundle):
    events = event_bundle.events.astype(object)
    events.loc[events.index[0], "first_observed_at"] = "2026-08-13T00:00:00"

    issues = validate_event_bundle(
        replace(event_bundle, events=events),
        registry_bundle,
        pd.Timestamp("2026-08-13T00:00:00Z"),
    )

    assert any(issue.code == "source_timestamp_not_timezone_aware" for issue in issues)


def test_event_shape_validation_rejects_invalid_scope_and_inverted_thesis_window(
    event_bundle, registry_bundle
):
    events = event_bundle.events.astype(object)
    events.loc[events.index[0], "scope"] = "headline"
    thesis_index = events.index[events["certainty_class"] == "thesis_checkpoint"][0]
    events.loc[thesis_index, "ends_at"] = events.loc[thesis_index, "starts_at"] - pd.Timedelta(
        days=1
    )

    issues = validate_event_bundle(
        replace(event_bundle, events=events),
        registry_bundle,
        pd.Timestamp("2026-08-13T00:00:00Z"),
    )
    codes = {issue.code for issue in issues}
    assert "invalid_event_scope" in codes
    assert "event_window_inverted" in codes


def test_validation_issue_order_is_deterministic(event_bundle, registry_bundle):
    events = event_bundle.events.astype(object)
    events.loc[events.index[0], ["event_id", "title", "source_timezone"]] = [
        "",
        "",
        "Mars/Olympus",
    ]
    invalid = replace(event_bundle, events=events)

    left = validate_event_bundle(
        invalid, registry_bundle, pd.Timestamp("2026-08-13T00:00:00Z")
    )
    right = validate_event_bundle(
        invalid, registry_bundle, pd.Timestamp("2026-08-13T00:00:00Z")
    )

    assert left == right


def test_thesis_events_have_internal_research_evidence(event_bundle, registry_bundle):
    thesis = event_bundle.events[
        event_bundle.events["certainty_class"] == "thesis_checkpoint"
    ]
    assert set(thesis["evidence_class"]) == {"internal_research"}
    assert thesis["evidence_ref"].str.contains(
        "docs/superpowers/specs/2026-08-13-research-control-tower-design.md"
        "#5.2-event-classes",
        regex=False,
    ).all()
    assert thesis["source_url"].astype("string").str.strip().eq("").all()

    events = event_bundle.events.astype(object)
    thesis_index = events.index[events["certainty_class"] == "thesis_checkpoint"][0]
    events.loc[thesis_index, "evidence_ref"] = ""
    issues = validate_event_bundle(
        replace(event_bundle, events=events),
        registry_bundle,
        pd.Timestamp("2026-08-13T00:00:00Z"),
    )
    assert any(issue.code == "missing_evidence_ref" for issue in issues)


def test_internal_research_cannot_masquerade_as_external_source(
    event_bundle, registry_bundle
):
    events = event_bundle.events.astype(object)
    thesis_index = events.index[events["certainty_class"] == "thesis_checkpoint"][0]
    events.loc[thesis_index, "source_url"] = "https://example.test/not-external-evidence"

    issues = validate_event_bundle(
        replace(event_bundle, events=events),
        registry_bundle,
        pd.Timestamp("2026-08-13T00:00:00Z"),
    )

    assert any(
        issue.code == "internal_research_must_not_use_source_url"
        for issue in issues
    )


def test_coverage_gaps_are_unavailable_and_not_catalysts(event_bundle):
    gaps = event_bundle.events[event_bundle.events["event_type"] == "coverage_gap"]
    assert {
        "TAIWAN_COMPANY_EARNINGS_COVERAGE_GAP",
        "CSI500_REVIEW_COVERAGE_GAP",
        "STOXX_EUROPE_600_REVIEW_COVERAGE_GAP",
    } <= set(gaps["event_id"])
    assert set(gaps["status"]) == {"unavailable"}
    assert not is_catalyst_eligible(gaps).any()
    assert is_catalyst_eligible(
        event_bundle.events[
            event_bundle.events["event_id"] == "MTR_H1_2025_INTERIM_RESULTS"
        ]
    ).all()
    assert "HKMA_STABLECOIN_ROLLOUT_WINDOW" not in set(
        event_bundle.events["event_id"]
    )


def test_source_timezone_must_be_valid_iana(event_bundle, registry_bundle):
    events = event_bundle.events.astype(object)
    events.loc[events.index[0], "source_timezone"] = "Mars/Olympus"

    issues = validate_event_bundle(
        replace(event_bundle, events=events),
        registry_bundle,
        pd.Timestamp("2026-08-13T00:00:00Z"),
    )

    assert any(issue.code == "invalid_source_timezone" for issue in issues)


def test_link_intervals_must_be_ordered_and_temporally_valid(
    event_bundle, registry_bundle
):
    links = event_bundle.event_links.copy()
    links.loc[links.index[0], "active_to"] = links.loc[links.index[0], "active_from"]
    links.loc[links.index[3], "active_from"] = pd.Timestamp("2024-01-01")
    links.loc[links.index[3], "active_to"] = pd.Timestamp("2025-01-01")

    issues = validate_event_bundle(
        replace(event_bundle, event_links=links),
        registry_bundle,
        pd.Timestamp("2026-08-13T00:00:00Z"),
    )
    codes = {issue.code for issue in issues}

    assert "event_link_active_to_not_after_active_from" in codes
    assert "event_link_outside_event_window" in codes
    assert "event_link_outside_target_interval" in codes


def test_actual_values_use_actual_unit_and_remain_scalar(event_bundle):
    populated = event_bundle.events[
        event_bundle.events["actual_value"].astype("string").str.strip().ne("")
    ]
    assert populated["actual_unit"].astype("string").str.strip().ne("").all()
    assert not populated["actual_value"].astype("string").str.contains(
        ";", regex=False
    ).any()
    no_surprise = event_bundle.events[
        event_bundle.events["surprise_value"].astype("string").str.strip().eq("")
    ]
    assert no_surprise["surprise_unit"].astype("string").str.strip().eq("").all()


def test_compute_t_minus_uses_viewer_timezone_calendar_dates():
    events = pd.DataFrame(
        {
            "event_id": ["CROSS_DATE", "PAST_RANGE"],
            "starts_at": [
                pd.Timestamp("2026-08-14T00:30:00Z"),
                pd.Timestamp("2026-08-10T14:30:00Z"),
            ],
            "ends_at": [pd.NaT, pd.Timestamp("2026-08-12T23:30:00Z")],
        }
    ).set_index("event_id")

    result = compute_t_minus(
        events,
        pd.Timestamp("2026-08-13T14:30:00Z"),
        viewer_timezone="Asia/Tokyo",
    )

    assert result.loc["CROSS_DATE"] == 1
    assert result.loc["PAST_RANGE"] == -3


def test_compute_t_minus_requires_timezone_aware_now():
    events = pd.DataFrame(
        {"starts_at": [pd.Timestamp("2026-08-14T00:00:00Z")], "ends_at": [pd.NaT]}
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        compute_t_minus(events, pd.Timestamp("2026-08-13"))


def test_macro_calendar_is_deterministic_and_normalized():
    source = pd.DataFrame(
        {
            "release_date": ["2026-08-12"],
            "release_time": ["08:30"],
            "timezone": ["America/New_York"],
            "title": ["US CPI"],
            "source_url": ["https://example.test/us-cpi"],
            "country": ["US"],
        }
    )

    left = materialize_macro_calendar({"us_cpi": source})
    right = materialize_macro_calendar({"us_cpi": source.copy()})

    pd.testing.assert_frame_equal(left, right)
    assert left.loc[0, "scope"] == "macro"
    assert left.loc[0, "event_type"] == "us_cpi"
    assert left.loc[0, "starts_at"] == pd.Timestamp("2026-08-12T12:30:00Z")
    assert left.loc[0, "source_url"] == "https://example.test/us-cpi"


def test_macro_metadata_uses_declared_source_timezone():
    source = pd.DataFrame(
        {
            "release_date": ["2026-08-12"],
            "release_time": ["08:30"],
            "source_published_at": ["2026-08-12 08:30"],
            "first_observed_at": ["2026-08-12 09:15"],
            "source_timezone": ["America/New_York"],
            "source_url": ["https://example.test/us-cpi"],
        }
    )

    result = materialize_macro_calendar({"us_cpi": source})

    assert result.loc[0, "source_published_at"] == pd.Timestamp(
        "2026-08-12T12:30:00Z"
    )
    assert result.loc[0, "first_observed_at"] == pd.Timestamp(
        "2026-08-12T13:15:00Z"
    )


def test_macro_period_is_not_used_as_release_time():
    result = materialize_macro_calendar(
        {"china_gdp": pd.DataFrame({"period": ["2026-Q2"], "timezone": ["Asia/Shanghai"]})}
    )

    assert pd.isna(result.loc[0, "starts_at"])
    assert result.loc[0, "reference_period"] == "2026-Q2"
    assert result.loc[0, "status"] == "unavailable"


def test_macro_missing_observed_or_release_timing_fails_closed():
    source = pd.DataFrame(
        {
            "release_date": ["2026-08-12", ""],
            "release_time": ["08:30", ""],
            "first_observed_at": ["", "2026-08-12 09:15"],
            "source_timezone": ["America/New_York", "America/New_York"],
        }
    )

    result = materialize_macro_calendar({"macro_source": source})

    assert pd.isna(result.loc[0, "first_observed_at"])
    assert result.loc[0, "status"] == "unavailable"
    assert pd.isna(result.loc[1, "starts_at"])
    assert result.loc[1, "status"] == "unavailable"


def test_macro_unavailable_rows_validate_without_invented_timestamps(
    registry_bundle,
):
    frame = materialize_macro_calendar(
        {
            "period_only": pd.DataFrame(
                {
                    "period": ["2026-Q2"],
                    "source_timezone": ["Asia/Shanghai"],
                    "source_id": ["period_only_fixture"],
                }
            )
        }
    )
    empty_links = pd.DataFrame(columns=load_event_bundle(
        Path(__file__).parents[1] / "config" / "research_control_tower"
    ).event_links.columns)
    empty_questions = pd.DataFrame(columns=load_event_bundle(
        Path(__file__).parents[1] / "config" / "research_control_tower"
    ).event_watch_questions.columns)
    bundle = EventBundle(frame, empty_links, empty_questions)

    issues = validate_event_bundle(
        bundle,
        registry_bundle,
        pd.Timestamp("2026-08-13T00:00:00Z"),
    )

    assert not [
        issue
        for issue in issues
        if issue.code in {"missing_starts_at", "missing_first_observed_at"}
    ]


def test_macro_invalid_source_timezone_is_rejected():
    source = pd.DataFrame(
        {
            "release_date": ["2026-08-12"],
            "source_timezone": ["Mars/Olympus"],
        }
    )

    with pytest.raises(ValueError, match="unknown source timezone"):
        materialize_macro_calendar({"invalid_timezone": source})


def test_loaded_event_bundle_has_no_validation_errors(event_bundle, registry_bundle):
    issues = validate_event_bundle(
        event_bundle,
        registry_bundle,
        pd.Timestamp("2026-08-13T00:00:00Z"),
    )
    assert not [issue for issue in issues if issue.severity == "error"]
