from __future__ import annotations

import pandas as pd

from dashboard.sections.opencode import (
    _latest_leaderboard,
    _latest_market_share_snapshot,
    _latest_published_timeframe,
)


def test_latest_leaderboard_uses_newer_weekly_snapshot_when_daily_history_is_stale():
    leaderboard = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-08-05",
                "user_tier": "All Users",
                "timeframe": "1D",
                "rank": 1,
                "model_slug": "old-model",
                "tokens": 100,
                "scraped_at": "2026-08-05T06:40:00Z",
            },
            {
                "snapshot_date": "2026-09-06",
                "user_tier": "All Users",
                "timeframe": "1W",
                "rank": 1,
                "model_slug": "current-model",
                "tokens": 200,
                "scraped_at": "2026-09-06T04:51:00Z",
            },
        ]
    )

    latest = _latest_leaderboard(leaderboard)

    assert latest["timeframe"].tolist() == ["1W"]
    assert latest["model_slug"].tolist() == ["current-model"]


def test_latest_published_timeframe_prefers_the_freshest_supported_source():
    frame = pd.DataFrame(
        [
            {"timeframe": "1D", "scraped_at": "2026-08-05T06:40:00Z"},
            {"timeframe": "1W", "scraped_at": "2026-09-06T04:51:00Z"},
            {"timeframe": "3M", "scraped_at": "2026-08-05T06:40:00Z"},
        ]
    )

    assert _latest_published_timeframe(frame, ("1D", "1W")) == "1W"


def test_latest_market_share_snapshot_does_not_mix_periods():
    frame = pd.DataFrame(
        [
            {"timeframe": "1W", "usage_date": "SEP 5", "author": "A", "share_pct": 70, "scraped_at": "2026-09-06T04:00:00Z"},
            {"timeframe": "1W", "usage_date": "SEP 5", "author": "B", "share_pct": 30, "scraped_at": "2026-09-06T04:00:00Z"},
            {"timeframe": "1W", "usage_date": "SEP 6", "author": "A", "share_pct": 40, "scraped_at": "2026-09-06T04:00:00Z"},
            {"timeframe": "1W", "usage_date": "SEP 6", "author": "B", "share_pct": 60, "scraped_at": "2026-09-06T04:00:00Z"},
        ]
    )

    latest = _latest_market_share_snapshot(frame)

    assert latest["usage_date"].unique().tolist() == ["SEP 6"]
    assert latest["share_pct"].sum() == 100
