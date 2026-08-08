from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.fuel_surcharge import (
    FUEL_SURCHARGE_COLUMNS,
    parse_cathay_fuel_surcharge_html,
    parse_china_domestic_fuel_surcharge_html,
)


def test_parse_cathay_surcharge_rows() -> None:
    html = """
    <html><body>
    Cathay adjusts fuel surcharge effective 1 August 2026. Review every two weeks.
    Flights from Hong Kong to Chinese Mainland:
    Until 31Jul2026 HKD 165 From 01Aug2026 HKD 198
    Flights from Chinese Mainland to Hong Kong:
    Until 31Jul2026 CNY 135 From 01Aug2026 CNY 162
    </body></html>
    """
    result = parse_cathay_fuel_surcharge_html(html, retrieved_at="2026-08-06T00:00:00+00:00")

    assert list(result.columns) == FUEL_SURCHARGE_COLUMNS
    assert len(result) == 2
    hk_row = result[result["currency"].eq("HKD")].iloc[0]
    assert hk_row["previous_value"] == 165
    assert hk_row["current_value"] == 198
    assert hk_row["effective_from"] == "2026-08-01"
    assert hk_row["review_frequency"] == "biweekly"


def test_parse_mainland_surcharge_announcement() -> None:
    html = """
    <html><body>
    Chinese airlines will lower fuel surcharges for mainland routes on tickets sold from July 5.
    Passengers will pay a fuel surcharge of 50 yuan on routes up to 800 km,
    and 100 yuan for longer routes. Compared with current rates, reduced by 30 yuan
    and by 50 yuan.
    </body></html>
    """
    result = parse_china_domestic_fuel_surcharge_html(html)

    assert result["effective_from"].tolist() == ["2026-07-05", "2026-07-05"]
    assert result["current_value"].tolist() == [50.0, 100.0]
    assert result["previous_value"].tolist() == [80.0, 150.0]
    assert result["previous_value_inferred"].all()
