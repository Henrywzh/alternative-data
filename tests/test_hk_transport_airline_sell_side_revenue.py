from __future__ import annotations

import pandas as pd
import pytest

from hk_transport.sources.airline_sell_side_revenue import (
    build_sell_side_revenue_revisions,
    extract_revenue_forecast_from_text,
)


def test_extract_revenue_forecast_from_standard_sell_side_table() -> None:
    text = """
    盈利预测和财务指标 2024 2025 2026E 2027E 2028E
    营业收入(百万元) 20,000 21,460 26,152 28,998 32,362
    营业收入增长率 11.5% 7.3% 21.9% 10.9% 11.6%
    """
    result = extract_revenue_forecast_from_text(text)
    assert result == [
        {"fiscal_year": 2026, "revenue_forecast_native_mn": 26152.0},
        {"fiscal_year": 2027, "revenue_forecast_native_mn": 28998.0},
        {"fiscal_year": 2028, "revenue_forecast_native_mn": 32362.0},
    ]


def test_sell_side_revenue_revision_compares_same_institution_and_year() -> None:
    forecasts = pd.DataFrame(
        {
            "ticker": ["601021.SH", "601021.SH"],
            "company": ["Spring Airlines"] * 2,
            "institution": ["Test Securities"] * 2,
            "fiscal_year": [2026, 2026],
            "report_date": ["2026-01-01", "2026-04-01"],
            "revenue_forecast_native_mn": [25000.0, 26152.0],
            "report_title": ["old", "new"],
            "report_url": ["https://example.com/old", "https://example.com/new"],
        }
    )
    result = build_sell_side_revenue_revisions(forecasts, retrieved_at="2026-08-06")
    latest = result.iloc[-1]
    assert latest["prior_report_date"] == "2026-01-01"
    assert latest["revenue_change_native_mn"] == pytest.approx(1152.0)
    assert latest["revenue_change_pct"] == pytest.approx(4.608)
