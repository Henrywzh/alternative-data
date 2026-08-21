from __future__ import annotations

import pandas as pd

from openrouter_arr_nowcast import build_arr_nowcast_summary


def _source_with_partial_prior_month() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for date in pd.date_range("2026-07-01", "2026-07-31", freq="D"):
        rows.append({"usage_date": date, "provider_slug": "acme", "estimated_revenue": 10.0})
    # A missing historical day must not be annualized as if August were full.
    for date in pd.date_range("2026-08-01", "2026-08-31", freq="D"):
        if date.day != 15:
            rows.append({"usage_date": date, "provider_slug": "acme", "estimated_revenue": 20.0})
    for date in pd.date_range("2026-09-01", "2026-09-19", freq="D"):
        rows.append({"usage_date": date, "provider_slug": "acme", "estimated_revenue": 30.0})
    return pd.DataFrame(rows)


def test_september_window_excludes_latest_date_and_uses_calendar_end() -> None:
    summary = build_arr_nowcast_summary(
        _source_with_partial_prior_month(),
        provider_column="provider_slug",
        targets={"acme": "Acme"},
    )

    assert summary.latest_period == pd.Period("2026-09", freq="M")
    assert summary.observed_dates[0] == pd.Timestamp("2026-09-01")
    assert summary.observed_dates[-1] == pd.Timestamp("2026-09-18")
    assert summary.remaining_dates[0] == pd.Timestamp("2026-09-19")
    assert summary.remaining_dates[-1] == pd.Timestamp("2026-09-30")
    assert len(summary.remaining_dates) == 12
    assert summary.nowcasts[0].mtd_revenue == 18 * 30.0


def test_partial_provider_month_is_excluded_and_prior_complete_month_is_dynamic() -> None:
    summary = build_arr_nowcast_summary(
        _source_with_partial_prior_month(),
        provider_column="provider_slug",
        targets={"acme": "Acme"},
    )
    history = summary.history.set_index("month")

    assert bool(history.loc[pd.Period("2026-07", freq="M"), "complete"])
    assert not bool(history.loc[pd.Period("2026-08", freq="M"), "complete"])
    assert pd.isna(history.loc[pd.Period("2026-08", freq="M"), "arr"])
    assert summary.prior_period == pd.Period("2026-07", freq="M")
    assert summary.nowcasts[0].prior_period == pd.Period("2026-07", freq="M")
