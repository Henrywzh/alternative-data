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

    Hong Kong had not published 2026-07, yet the chart drew it at +57.75%:
    its June value divided by July a year earlier. The value sits inside the
    range the real series occupies, so the fabricated point reads as data.
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


def test_a_thousand_usd_series_is_not_plotted_as_dollars() -> None:
    """Korea Customs answers in thousands; the label said plain USD.

    Keying the USD-normalized scale off currency alone put Korea's exports
    on the chart a thousandfold too small. Comtrade reports the same month
    at exactly 1000x the official figure, which is what a thousands series
    read as dollars looks like.
    """
    frame = pd.DataFrame(
        [
            {"period": "2026-06", "country_name": "South Korea", "currency": "USD",
             "unit": "usd_thousand", "value": 33_564_194.0},
            {"period": "2026-06", "country_name": "United States", "currency": "USD",
             "unit": "usd", "value": 33_564_194_000.0},
        ]
    )
    display, y_title, complete = semiconductor._prepare_official_trade_display(
        frame, "USD Normalized (PT FX)"
    )

    assert y_title == "USD Billion"
    assert complete
    by_country = display.set_index("country_name")["display_value"]
    # The same economic quantity, one reported in thousands: both are 33.56bn.
    assert by_country["South Korea"] == pytest.approx(33.564194)
    assert by_country["United States"] == pytest.approx(33.564194)


def test_the_native_scale_labels_thousand_usd_in_billions() -> None:
    scale, y_title = semiconductor._official_trade_unit_config("usd_thousand")

    assert y_title == "USD Billion"
    assert 33_564_194.0 / scale == pytest.approx(33.564194)


class _StubDataset:
    """Minimal stand-in for DatasetLoadResult as render_dataset_guard reads it."""

    def __init__(self, dataset_id: str, frame: pd.DataFrame) -> None:
        self.dataset_id = dataset_id
        self.label = dataset_id
        self.frame = frame
        self.source_path = "stub.parquet"


def _census_frame() -> pd.DataFrame:
    periods = pd.period_range("2025-01", periods=18, freq="M").strftime("%Y-%m")
    rows = []
    for partner, base in (("KOREA, SOUTH", 100.0), ("TAIWAN", 50.0)):
        for i, period in enumerate(periods):
            rows.append(
                {
                    "period": period,
                    "partner_country_name": partner,
                    "hs_code": "854232",
                    "item_name": "MEMORIES, ELECTRONIC INTEGRATED CIRCUITS",
                    "general_import_value_usd": (base + i) * 1e6,
                    "air_import_value_usd": (base + i) * 1e6 * 0.99,
                    "vessel_import_value_usd": (base + i) * 1e6 * 0.01,
                }
            )
    return pd.DataFrame(rows)


def test_the_import_panel_does_not_call_its_own_flow_exports(monkeypatch) -> None:
    """The YoY chart is shared with the export tracker, which hardcoded the word.

    Reused as-is on the Census panel it titled a chart of US imports
    "US Imports of Memory Exports YoY" -- the one thing a reader must not get
    wrong here, since the two panels describe opposite directions of trade.
    """
    titles: list[str] = []
    monkeypatch.setattr(semiconductor.st, "plotly_chart", lambda fig, **kwargs: None)
    monkeypatch.setattr(semiconductor.st, "dataframe", lambda *a, **k: None)
    monkeypatch.setattr(
        semiconductor,
        "make_line_chart",
        lambda pivot, colors, **kwargs: titles.append(kwargs.get("title", "")),
    )
    monkeypatch.setattr(semiconductor, "make_stacked_area_chart", lambda *a, **k: None)

    semiconductor._render_us_import_demand(
        {"us_census_memory_imports_monthly": _StubDataset("us_census_memory_imports_monthly", _census_frame())},
        None,
    )

    assert titles, "the YoY chart should have been drawn"
    assert "Imports" in titles[0]
    assert "Exports" not in titles[0]


def test_census_partner_names_are_normalised_for_display() -> None:
    assert semiconductor._display_partner_name("KOREA, SOUTH") == "South Korea"
    assert semiconductor._display_partner_name("TAIWAN") == "Taiwan"
    assert semiconductor._display_partner_name("") == "Unknown"
    assert semiconductor._display_partner_name(None) == "Unknown"


def test_the_export_tracker_still_says_exports(monkeypatch) -> None:
    """The shared helper's default must not have moved when it gained a flag."""
    titles: list[str] = []
    monkeypatch.setattr(semiconductor.st, "plotly_chart", lambda fig, **kwargs: None)
    monkeypatch.setattr(
        semiconductor,
        "make_line_chart",
        lambda pivot, colors, **kwargs: titles.append(kwargs.get("title", "")),
    )
    semiconductor._render_trade_yoy_chart(_monthly_frame("Japan", "2025-01", 14, 1.0), "IC-only", "Official")

    assert titles == ["Official IC-only Exports YoY"]


def test_the_census_datasets_are_reachable_through_the_registry() -> None:
    """Wiring, not rendering: without these the tab loads nothing at all."""
    from dashboard.data import DATASET_REGISTRY, dataset_source_for_domain, domain_dataset_ids

    ids = domain_dataset_ids("us_census_trade")
    assert ids == [
        "us_census_memory_imports_monthly",
        "us_census_memory_imports_port_monthly",
    ]
    assert dataset_source_for_domain("us_census_trade") == "us_census_trade"
    for dataset_id in ids:
        assert DATASET_REGISTRY[dataset_id]["domain"] == "us_census_trade"


def test_the_semiconductor_page_requests_the_census_domain() -> None:
    """The section reads domain_states["us_census_trade"] and would KeyError."""
    import dashboard.app as app

    assert "us_census_trade" in app.SECTION_DOMAIN_MAP["Semiconductor Analysis"]
