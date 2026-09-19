"""Hover helpers must not rewrite dummy legend traces."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import plotly.graph_objects as go


APP_DIR = Path(__file__).resolve().parents[1] / "apps" / "asia-markets-streamlit"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from am.core import apply_line_hover  # noqa: E402


def test_apply_line_hover_can_skip_empty_legend_traces() -> None:
    fig = go.Figure()
    fig.add_scatter(
        x=pd.to_datetime(["2026-09-01", "2026-09-02"]),
        y=[20.0, 40.0],
        name="CNN Fear & Greed",
    )
    fig.add_scatter(x=[None], y=[None], name="0-24 Extreme Fear", hoverinfo="skip")
    frame = pd.DataFrame(
        {"_date": pd.to_datetime(["2026-09-01", "2026-09-02"]), "_value": [20.0, 40.0]}
    )
    apply_line_hover(fig, frame, "number", skip_empty=True)

    assert "CNN Fear & Greed" in fig.data[0].hovertemplate
    assert fig.data[1].hovertemplate is None or fig.data[1].hoverinfo == "skip"
    assert "0-24 Extreme Fear" not in str(fig.data[1].hovertemplate or "")
