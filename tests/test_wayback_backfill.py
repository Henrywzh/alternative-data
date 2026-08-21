from __future__ import annotations

from datetime import date

import pytest

from wayback_backfill import Capture, plan_rolling_window_captures


def _capture(day: str) -> Capture:
    return Capture(timestamp=day.replace("-", "") + "120000", original="https://openrouter.ai/provider/test")


def test_capture_plan_uses_minimal_overlapping_rolling_windows() -> None:
    captures = [
        _capture("2026-01-08"),
        _capture("2026-02-01"),
        _capture("2026-04-08"),
        _capture("2026-07-07"),
        _capture("2026-08-20"),
    ]

    plan = plan_rolling_window_captures(
        captures,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 8, 20),
        window_days=91,
    )

    assert [capture.capture_date for capture in plan.selected] == [
        "2026-02-01",
        "2026-04-08",
        "2026-07-07",
        "2026-08-20",
    ]
    assert plan.uncovered_ranges == ()


def test_capture_plan_reports_gaps_instead_of_claiming_complete_history() -> None:
    plan = plan_rolling_window_captures(
        [_capture("2026-01-08"), _capture("2026-07-07")],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 8, 20),
        window_days=91,
    )

    assert [capture.capture_date for capture in plan.selected] == [
        "2026-01-08",
        "2026-07-07",
    ]
    assert plan.uncovered_ranges == (
        ("2026-01-09", "2026-04-07"),
        ("2026-07-08", "2026-08-20"),
    )


@pytest.mark.parametrize(
    ("start", "end", "window_days"),
    [
        (date(2026, 2, 1), date(2026, 1, 1), 91),
        (date(2026, 1, 1), date(2026, 2, 1), 0),
    ],
)
def test_capture_plan_rejects_invalid_ranges(
    start: date, end: date, window_days: int
) -> None:
    with pytest.raises(ValueError):
        plan_rolling_window_captures(
            [],
            start_date=start,
            end_date=end,
            window_days=window_days,
        )
