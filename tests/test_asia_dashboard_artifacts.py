"""Tests for the non-Streamlit Asia Markets dashboard artifact builders."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "apps" / "asia-markets-dashboard" / "scripts"


def _load_builder(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_china_airline_traffic_normalizes_clean_parquet(tmp_path):
    builder = _load_builder("build_hk_transport_artifact.py", "transport_builder_loader_test")
    path = tmp_path / "china_airlines_monthly.parquet"
    pd.DataFrame(
        [
            {
                "month": "2026-01",
                "date": "2026-01-01",
                "airline_code": "600029",
                "region": "Domestic",
                "metric": "passengers",
                "value": 123.4,
            }
        ]
    ).to_parquet(path, index=False)

    result = builder.load_china_airline_traffic(path)

    assert list(result.columns) == [
        "month",
        "date",
        "airline_code",
        "airline",
        "region",
        "metric",
        "value",
    ]
    assert result.iloc[0]["airline"] == "China Southern"
    assert result.iloc[0]["value"] == 123.4


def test_china_airline_views_are_wired_into_transport_artifact():
    builder = _load_builder("build_hk_transport_artifact.py", "transport_builder_views_test")
    source = pd.DataFrame(
        [
            {"month": "2026-01", "date": "2026-01-01", "airline_code": "600029", "region": "Total", "metric": "passengers", "value": 100.0},
            {"month": "2026-01", "date": "2026-01-01", "airline_code": "600029", "region": "Total", "metric": "ask", "value": 200.0},
            {"month": "2026-01", "date": "2026-01-01", "airline_code": "600029", "region": "Total", "metric": "rpk", "value": 150.0},
            {"month": "2026-01", "date": "2026-01-01", "airline_code": "600029", "region": "Total", "metric": "passenger_load_factor_pct", "value": 75.0},
            {"month": "2026-01", "date": "2026-01-01", "airline_code": "600029", "region": "Domestic", "metric": "passengers", "value": 80.0},
        ]
    )

    views = builder.build_china_airline_views(source)

    assert set(views) == {
        "china_airline_passengers_history",
        "china_airline_ask_history",
        "china_airline_rpk_history",
        "china_airline_load_factor_history",
        "china_airline_region_split_history",
        "china_airline_latest_snapshot",
    }
    assert views["china_airline_passengers_history"][0]["airline"] == "China Southern"
    assert views["china_airline_ask_history"][0]["value"] == 200.0
    assert views["china_airline_rpk_history"][0]["value"] == 150.0
    assert {row["series"] for row in views["china_airline_ask_history"]} == {"CS"}
    assert views["china_airline_load_factor_history"][0]["value"] == 75.0
    assert views["china_airline_region_split_history"][0]["region"] == "Domestic"
    assert views["china_airline_latest_snapshot"][0]["airline_code"] == "600029"


def _regional_rows(metric: str, regions: dict[str, float]) -> list[dict]:
    return [
        {
            "month": "2026-01",
            "date": "2026-01-01",
            "airline_code": "601021",
            "region": region,
            "metric": metric,
            "value": value,
        }
        for region, value in regions.items()
    ]


def test_partial_region_coverage_leaves_a_gap_instead_of_a_derived_total():
    """A carrier with no reported Total must not get one from 2 of 3 regions.

    Spring Airlines publishes only a regional breakdown, so its totals are
    derived. When a page-break artifact dropped one region's ASK, summing the
    remaining two understated ASK and pushed the derived RPK/ASK load factor
    above 100%. The builder now requires all three regions before deriving.
    """
    builder = _load_builder("build_hk_transport_artifact.py", "transport_builder_gate_test")

    complete = pd.DataFrame(
        _regional_rows("ask", {"Domestic": 100.0, "International": 50.0, "Regional": 10.0})
        + _regional_rows("rpk", {"Domestic": 80.0, "International": 40.0, "Regional": 8.0})
    )
    full = builder.build_china_airline_views(complete)
    assert [row["value"] for row in full["china_airline_ask_history"]] == [160.0]
    assert full["china_airline_load_factor_history"][0]["value"] == pytest.approx(80.0)

    # Same data with one ASK region dropped: RPK is still complete, so an
    # ungated sum would divide complete RPK by an understated ASK.
    partial = pd.DataFrame(
        _regional_rows("ask", {"Domestic": 100.0, "Regional": 10.0})
        + _regional_rows("rpk", {"Domestic": 80.0, "International": 40.0, "Regional": 8.0})
    )
    gapped = builder.build_china_airline_views(partial)
    assert gapped["china_airline_ask_history"] == [], "2 of 3 regions must not yield a total"
    assert gapped["china_airline_load_factor_history"] == [], (
        "load factor must be dropped rather than derived from an incomplete ASK"
    )
    # The complete metric is unaffected.
    assert [row["value"] for row in gapped["china_airline_rpk_history"]] == [128.0]
