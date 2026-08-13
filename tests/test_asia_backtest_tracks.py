"""Tests for the track-exclusivity guards in src/common/backtest/tracks.py."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.common.backtest.tracks import (
    TRACK_EXCLUSION_GROUPS,
    assert_single_track,
    check_period_type_consistency,
    period_types_for_track,
    validate_track_exclusivity,
)

LONG_FORM_PATH = Path("data/registries/asia_backtest_long_form.csv")


def _frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _row(track_id: str, period_type: str, **extra: object) -> dict[str, object]:
    row = {"track_id": track_id, "target_period_type": period_type}
    row.update(extra)
    return row


# ---------------------------------------------------------------------------
# TRACK_EXCLUSION_GROUPS / period_types_for_track
# ---------------------------------------------------------------------------


def test_exclusion_groups_cover_every_track_id_exactly_once() -> None:
    from src.common.backtest.vocabulary import TRACK_IDS

    seen: set[str] = set()
    for group in TRACK_EXCLUSION_GROUPS:
        assert not (seen & group), "a track_id appears in more than one exclusion group"
        seen |= group
    assert seen == set(TRACK_IDS)


def test_period_types_for_track_known_tracks() -> None:
    assert period_types_for_track("fiscal_year") == ("FY",)
    assert period_types_for_track("half_year_non_overlapping") == ("H1", "H2")
    assert period_types_for_track("monthly_sparse") == ("month",)
    assert period_types_for_track("ytd_current") == ("H1",)


def test_period_types_for_track_unknown_raises() -> None:
    with pytest.raises(ValueError, match="quarterly_bogus"):
        period_types_for_track("quarterly_bogus")


# ---------------------------------------------------------------------------
# validate_track_exclusivity
# ---------------------------------------------------------------------------


def test_fy_and_h1_mixed_raises() -> None:
    frame = _frame([_row("fiscal_year", "FY"), _row("half_year_non_overlapping", "H1")])
    with pytest.raises(ValueError, match="fiscal_year"):
        validate_track_exclusivity(frame)


def test_fy_and_h2_mixed_raises() -> None:
    frame = _frame([_row("fiscal_year", "FY"), _row("half_year_non_overlapping", "H2")])
    with pytest.raises(ValueError, match="half_year_non_overlapping"):
        validate_track_exclusivity(frame)


def test_h1_and_h2_together_passes() -> None:
    frame = _frame(
        [
            _row("half_year_non_overlapping", "H1"),
            _row("half_year_non_overlapping", "H2"),
        ]
    )
    validate_track_exclusivity(frame)  # must not raise


def test_fy_alone_passes() -> None:
    frame = _frame([_row("fiscal_year", "FY"), _row("fiscal_year", "FY")])
    validate_track_exclusivity(frame)  # must not raise


@pytest.mark.parametrize(
    "other_track,other_period",
    [
        ("fiscal_year", "FY"),
        ("half_year_non_overlapping", "H1"),
        ("half_year_non_overlapping", "H2"),
        ("monthly_sparse", "month"),
    ],
)
def test_ytd_current_mixed_with_anything_raises(other_track: str, other_period: str) -> None:
    frame = _frame([_row("ytd_current", "H1"), _row(other_track, other_period)])
    with pytest.raises(ValueError, match="ytd_current"):
        validate_track_exclusivity(frame)


@pytest.mark.parametrize(
    "other_track,other_period",
    [
        ("fiscal_year", "FY"),
        ("half_year_non_overlapping", "H1"),
        ("half_year_non_overlapping", "H2"),
        ("ytd_current", "H1"),
    ],
)
def test_monthly_sparse_mixed_with_anything_raises(other_track: str, other_period: str) -> None:
    frame = _frame([_row("monthly_sparse", "month"), _row(other_track, other_period)])
    with pytest.raises(ValueError, match="monthly_sparse"):
        validate_track_exclusivity(frame)


def test_validate_track_exclusivity_empty_frame_passes() -> None:
    validate_track_exclusivity(pd.DataFrame(columns=["track_id"]))  # must not raise
    validate_track_exclusivity(pd.DataFrame())  # must not raise


def test_validate_track_exclusivity_missing_column_passes() -> None:
    frame = pd.DataFrame({"other_column": [1, 2, 3]})
    validate_track_exclusivity(frame)  # must not raise


def test_validate_track_exclusivity_custom_track_column() -> None:
    frame = pd.DataFrame(
        {"my_track": ["fiscal_year", "half_year_non_overlapping"]}
    )
    with pytest.raises(ValueError):
        validate_track_exclusivity(frame, track_column="my_track")


# ---------------------------------------------------------------------------
# assert_single_track
# ---------------------------------------------------------------------------


def test_assert_single_track_returns_the_track_id() -> None:
    frame = _frame([_row("fiscal_year", "FY"), _row("fiscal_year", "FY")])
    assert assert_single_track(frame) == "fiscal_year"


def test_assert_single_track_raises_on_multiple_tracks_with_context() -> None:
    frame = _frame([_row("fiscal_year", "FY"), _row("half_year_non_overlapping", "H1")])
    with pytest.raises(ValueError, match="headline chart for MTR"):
        assert_single_track(frame, context="headline chart for MTR")


def test_assert_single_track_raises_on_empty_frame_with_context() -> None:
    with pytest.raises(ValueError, match="per-track aggregate"):
        assert_single_track(pd.DataFrame(columns=["track_id"]), context="per-track aggregate")


def test_assert_single_track_raises_on_missing_column() -> None:
    with pytest.raises(ValueError, match="track_id"):
        assert_single_track(pd.DataFrame({"other": [1, 2]}))


# ---------------------------------------------------------------------------
# check_period_type_consistency
# ---------------------------------------------------------------------------


def test_check_period_type_consistency_catches_fy_on_half_year_track() -> None:
    frame = _frame(
        [
            _row("half_year_non_overlapping", "H1"),
            _row("half_year_non_overlapping", "FY"),
        ]
    )
    with pytest.raises(ValueError, match="half_year_non_overlapping"):
        check_period_type_consistency(frame)


def test_check_period_type_consistency_passes_for_legitimate_rows() -> None:
    frame = _frame(
        [
            _row("fiscal_year", "FY"),
            _row("half_year_non_overlapping", "H1"),
            _row("half_year_non_overlapping", "H2"),
            _row("monthly_sparse", "month"),
            _row("ytd_current", "H1"),
        ]
    )
    check_period_type_consistency(frame)  # must not raise


def test_check_period_type_consistency_empty_frame_passes() -> None:
    check_period_type_consistency(pd.DataFrame(columns=["track_id", "target_period_type"]))
    check_period_type_consistency(pd.DataFrame())


def test_check_period_type_consistency_missing_column_passes() -> None:
    frame = pd.DataFrame({"track_id": ["fiscal_year"]})
    check_period_type_consistency(frame)  # target_period_type absent -> no-op


# ---------------------------------------------------------------------------
# Integration: the real long-form registry, if present
# ---------------------------------------------------------------------------


def test_real_long_form_respects_track_exclusivity_and_period_types() -> None:
    if not LONG_FORM_PATH.exists():
        pytest.skip(f"{LONG_FORM_PATH} not present in this checkout")
    frame = pd.read_csv(LONG_FORM_PATH)
    assert "track_id" in frame.columns
    assert "target_period_type" in frame.columns

    for track_id, subset in frame.groupby("track_id"):
        assert assert_single_track(subset, context=f"real long-form subset for {track_id}") == track_id

    check_period_type_consistency(frame)
