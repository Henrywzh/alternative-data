from __future__ import annotations

import pandas as pd

from dashboard.sections.minerals import (
    _build_chinatungsten_long_prices,
    _load_related_stock_links,
    _merge_mineral_selector_prices,
    _merge_mineral_selector_universe,
)


def test_build_chinatungsten_long_prices_adds_tungsten_and_molybdenum_series() -> None:
    tungsten = pd.DataFrame(
        {
            "date": ["2026-06-25", "2026-06-26"],
            "apt": [750000.0, None],
            "ferrotungsten": [730000.0, 735000.0],
        }
    )
    molybdenum = pd.DataFrame(
        {
            "date": ["2026-06-25"],
            "molybdenum_concentrate": [5180.0],
            "ferromolybdenum": [325000.0],
        }
    )

    prices = _build_chinatungsten_long_prices(tungsten, molybdenum)

    assert set(prices["normalized_mineral_id"]) == {"tungsten", "molybdenum"}
    assert set(prices["product_series"]) == {
        "apt",
        "ferrotungsten",
        "molybdenum_concentrate",
        "ferromolybdenum",
    }
    assert prices["price"].notna().all()
    assert prices.loc[prices["product_series"] == "apt", "product_label"].iloc[0] == "APT"


def test_build_chinatungsten_long_prices_adds_rare_earth_series() -> None:
    rare_earth = pd.DataFrame(
        {
            "date": ["2026-06-24", "2026-06-25"],
            "praseodymium_oxide": [820000.0, 820000.0],
            "gadolinium_oxide": [230000.0, 230000.0],
        }
    )

    prices = _build_chinatungsten_long_prices(pd.DataFrame(), pd.DataFrame(), rare_earth)

    assert set(prices["normalized_mineral_id"]) == {"rare_earth"}
    assert set(prices["product_series"]) == {"praseodymium_oxide", "gadolinium_oxide"}
    assert prices.loc[prices["product_series"] == "praseodymium_oxide", "product_label"].iloc[0] == "Praseodymium Oxide"


def test_build_chinatungsten_long_prices_defaults_rare_earth_to_empty() -> None:
    # Backward-compatible call without the rare_earth arg should not raise.
    tungsten = pd.DataFrame({"date": ["2026-06-25"], "apt": [750000.0]})
    prices = _build_chinatungsten_long_prices(tungsten, pd.DataFrame())
    assert set(prices["normalized_mineral_id"]) == {"tungsten"}


def test_merge_mineral_selector_prices_prefers_chinatungsten_for_special_minerals() -> None:
    base_prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-01"]),
            "price": [1.0, 2.0],
            "normalized_mineral_id": ["copper", "tungsten"],
            "mineral_name": ["Copper", "Tungsten"],
            "source_type": ["yfinance", "old"],
        }
    )
    china_prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-25"]),
            "price": [750000.0],
            "normalized_mineral_id": ["tungsten"],
            "mineral_name": ["Tungsten"],
            "source_type": ["chinatungsten_daily"],
            "product_series": ["apt"],
            "product_label": ["APT"],
        }
    )

    merged = _merge_mineral_selector_prices(base_prices, china_prices)

    assert set(merged["normalized_mineral_id"]) == {"copper", "tungsten"}
    assert merged.loc[merged["normalized_mineral_id"] == "tungsten", "source_type"].tolist() == [
        "chinatungsten_daily"
    ]


def test_merge_mineral_selector_universe_adds_synthetic_chinatungsten_metadata() -> None:
    universe = pd.DataFrame(
        {
            "normalized_mineral_id": ["copper"],
            "mineral_name": ["Copper"],
            "trackability_grade": ["direct"],
            "price_source_type": ["yfinance_futures"],
            "price_currency": ["USD"],
        }
    )
    china_prices = pd.DataFrame(
        {
            "normalized_mineral_id": ["tungsten", "molybdenum"],
            "mineral_name": ["Tungsten", "Molybdenum"],
        }
    )

    merged = _merge_mineral_selector_universe(universe, china_prices)

    assert set(merged["normalized_mineral_id"]) == {"copper", "tungsten", "molybdenum"}
    tungsten = merged.loc[merged["normalized_mineral_id"] == "tungsten"].iloc[0]
    assert tungsten["price_source_type"] == "chinatungsten_daily"
    assert tungsten["price_currency"] == "mixed"


def test_load_related_stock_links_falls_back_to_reference_mapping_for_tungsten(tmp_path) -> None:
    reference_dir = tmp_path / "data" / "reference" / "minerals_signal_data"
    reference_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "mineral_name": ["Tungsten"],
            "normalized_mineral_id": ["tungsten"],
            "ticker_raw": ["3993.HK"],
            "ticker_normalized": ["3993.HK"],
            "market": ["HK"],
            "exposure_purity": ["Primary"],
            "mapping_note": ["fixture"],
            "is_primary_exposure": [True],
        }
    ).to_csv(reference_dir / "stock_mapping.csv", index=False)

    links = _load_related_stock_links(pd.DataFrame(), "tungsten", tmp_path)

    assert links["ticker_normalized"].tolist() == ["3993.HK"]
