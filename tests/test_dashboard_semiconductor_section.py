from __future__ import annotations

import pandas as pd
import pytest

from dashboard.sections import semiconductor


def _capture_yoy_pivot(monkeypatch, frame: pd.DataFrame) -> pd.DataFrame:
    captured: dict[str, pd.DataFrame] = {}
    monkeypatch.setattr(semiconductor.st, "plotly_chart", lambda fig, **kwargs: None)
    monkeypatch.setattr(
        semiconductor,
        "make_line_chart",
        lambda pivot, colors, **kwargs: captured.setdefault("pivot", pivot),
    )
    semiconductor._render_trade_yoy_chart(frame, "IC-only", "Official")
    return captured.get("pivot", pd.DataFrame())


def _monthly_frame(country: str, start: str, months: int, step: float) -> pd.DataFrame:
    periods = pd.period_range(start, periods=months, freq="M")
    return pd.DataFrame(
        {
            "period": periods.strftime("%Y-%m"),
            "country_name": country,
            "display_value": [100.0 + step * i for i in range(months)],
        }
    )


def test_a_country_that_has_not_reported_this_month_gets_no_yoy_point(monkeypatch) -> None:
    """pandas padded the previous month forward and called it a YoY reading.

    Hong Kong had not published 2026-07, yet the chart drew it at -1206.93%:
    its June value divided by July a year earlier. The point is an artefact,
    not an observation, and being wildly out of range it also rescaled the
    whole panel.
    """
    reported = _monthly_frame("South Korea", "2025-01", 19, 1.0)
    lagging = _monthly_frame("Hong Kong", "2025-01", 18, 2.0)
    pivot = _capture_yoy_pivot(monkeypatch, pd.concat([reported, lagging], ignore_index=True))

    assert "2026-07" in pivot.index
    assert pd.isna(pivot.loc["2026-07", "Hong Kong"])
    assert pd.notna(pivot.loc["2026-07", "South Korea"])


def test_the_yoy_lag_is_twelve_months_not_twelve_rows(monkeypatch) -> None:
    """With a month absent from the panel the row offset stops being a year."""
    frame = _monthly_frame("Japan", "2025-01", 14, 0.0)
    frame = frame[frame["period"] != "2025-06"]
    frame.loc[frame["period"] == "2026-01", "display_value"] = 200.0
    pivot = _capture_yoy_pivot(monkeypatch, frame)

    # 2026-01 (200.0) against 2025-01 (100.0) is +100%. Counting twelve rows
    # back from 2026-01 in a panel missing 2025-06 lands on 2025-02 instead.
    assert pivot.loc["2026-01", "Japan"] == pytest.approx(100.0)
    # The absent month stays absent rather than being padded into existence.
    assert "2025-06" not in pivot.index
