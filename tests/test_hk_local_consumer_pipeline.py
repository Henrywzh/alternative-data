import importlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.hk_local_consumer.sources.afcd_food import fetch_afcd_food_prices, parse_afcd_csv
from src.hk_local_consumer.sources.consumer_council import fetch_consumer_council_prices, parse_consumer_council_payload
from src.hk_local_consumer.sources.sge_gold import fetch_sge_gold_benchmark
from src.hk_local_consumer.sources.hk_valuation import fetch_hk_consumer_valuations
from src.hk_local_consumer.sources.cnsd_retail import fetch_cnsd_retail_sales
from src.hk_local_consumer.sources.censtatd_restaurant import fetch_censtatd_restaurant_survey
from src.hk_local_consumer.pipeline import _quality_errors, run_stage_1_pipeline, QUALITY_SPECS
from src.hk_local_consumer.storage import save_normalized_dataset, save_raw_snapshot


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    """Ensure tests do not write into production data directories."""
    raw_dir = tmp_path / "raw"
    norm_dir = tmp_path / "normalized"
    raw_dir.mkdir()
    norm_dir.mkdir()
    import src.hk_local_consumer.storage as storage_mod
    import src.hk_local_consumer.pipeline as pipeline_mod

    monkeypatch.setattr(storage_mod, "RAW_DIR", raw_dir)
    monkeypatch.setattr(storage_mod, "NORMALIZED_DIR", norm_dir)
    monkeypatch.setattr(pipeline_mod, "NORMALIZED_DIR", norm_dir)
    return tmp_path


def test_import_smoke():
    for module in (
        "src.hk_local_consumer.config",
        "src.hk_local_consumer.storage",
        "src.hk_local_consumer.sources.afcd_food",
        "src.hk_local_consumer.sources.consumer_council",
        "src.hk_local_consumer.sources.sge_gold",
        "src.hk_local_consumer.sources.hk_valuation",
        "src.hk_local_consumer.sources.cnsd_retail",
        "src.hk_local_consumer.sources.censtatd_restaurant",
        "src.hk_local_consumer.pipeline",
        "src.hk_local_consumer.cli",
    ):
        assert importlib.import_module(module)


def test_parse_afcd_csv():
    # Mirrors AFCD's real export shape: every column appears twice (an
    # ASCII English header, then a mojibake Chinese-label duplicate of the
    # same values) and price is in HKD/catty, not HKD/kg.
    sample_csv = (
        "ENGLISH CATEGORY,X,FRESH FOOD CATEGORY,X,FOOD TYPE,X,"
        "PRICE (THIS MORNING),X,UNIT,X\n"
        "Average Wholesale Prices,X,Poultry,X,Fresh Chicken,X,42.34,X,($ / Catty),X\n"
        "Average Wholesale Prices,X,Pork,X,Fresh Pork,X,-,X,($ / Catty),X\n"
    )
    df = parse_afcd_csv(sample_csv)
    assert len(df) == 1
    assert "date" in df.columns
    assert df.iloc[0]["commodity_name"] == "Fresh Chicken"
    assert df.iloc[0]["price_hkd_per_kg"] == round(42.34 / 0.6047989, 2)


def test_parse_afcd_csv_missing_columns_returns_empty():
    df = parse_afcd_csv("Some,Other,Header\n1,2,3\n")
    assert df.empty
    assert list(df.columns) == ["date", "category", "commodity_name", "price_hkd_per_kg", "unit", "remarks"]


def test_afcd_quality_contract_rejects_placeholder_rows():
    placeholder = pd.DataFrame(
        [
            {
                "date": "2026-07-29",
                "category": "Fresh Food",
                "commodity_name": f"Item_{index}",
                "price_hkd_per_kg": 0.0,
            }
            for index in range(20)
        ]
    )
    errors = _quality_errors("afcd_wholesale_food_prices_daily", placeholder)
    assert errors == ["category has only 1 unique values; expected at least 3"]


def test_parse_consumer_council_payload():
    payload = [
        {"code": "P101", "name": "Shampoo A", "category": "Personal Care", "brand": "BrandA", "supermarket": "Watsons", "price": 50.0, "original_price": 60.0},
        {"code": "P102", "name": "Lotion B", "category": "Skincare", "brand": "BrandB", "supermarket": "Mannings", "price": 80.0, "original_price": 80.0},
    ]
    df = parse_consumer_council_payload(payload)
    assert len(df) == 2
    assert bool(df.iloc[0]["is_on_sale"]) is True
    assert bool(df.iloc[1]["is_on_sale"]) is False


@pytest.mark.network
def test_sge_gold_benchmark_fallback():
    df = fetch_sge_gold_benchmark()
    assert not df.empty
    assert "gold_benchmark_pm_rmb_gram" in df.columns
    assert "currency" in df.columns


def test_hk_consumer_valuations():
    df = fetch_hk_consumer_valuations()
    assert not df.empty
    assert "ticker" in df.columns
    assert "pe_ttm" in df.columns
    # Check that key tickers exist
    tickers = set(df["ticker"].tolist())
    assert "01929.HK" in tickers or "00590.HK" in tickers


def test_cnsd_retail_sales():
    # fetch_cnsd_retail_sales hits the live censtatd.gov.hk API with no
    # offline fixture path and honestly returns an empty frame on network
    # failure rather than fabricating data. A transient failure of that
    # external site is not a code regression.
    df = fetch_cnsd_retail_sales()
    if df.empty:
        pytest.skip("C&SD retail sales live API unavailable (network fetch failed, not a code regression)")
    assert "sales_value_index" in df.columns
    assert "Supermarkets" in set(df["category"])


def test_censtatd_restaurant_survey():
    df = fetch_censtatd_restaurant_survey()
    if df.empty:
        pytest.skip("CenStatD restaurant survey live API unavailable (network fetch failed, not a code regression)")
    assert "total_receipts_hkd_m" in df.columns
    assert "Fast food shops" in set(df["sub_sector"])
    assert "All restaurants" in set(df["sub_sector"])


@pytest.mark.network
def test_fetch_immigration_flow():
    from src.hk_local_consumer.sources.immigration_flow import fetch_immigration_flow
    df = fetch_immigration_flow()
    assert not df.empty
    assert "hk_resident_departures" in df.columns
    assert "mainland_visitor_arrivals" in df.columns
    assert "hk_resident_departures_7d_ma" in df.columns
    assert "land_hk_resident_departures_7d_ma" in df.columns
    assert len(df) > 100
    # land-only ("northbound") departures must never exceed the all-control-point
    # total -- the land figure is a strict subset (9 of 17 control points).
    # This is the exact invariant whose absence let the "northbound" KPI/chart
    # get wired to the wrong (all-points) column instead of the land-only one.
    land = df["land_hk_resident_departures_7d_ma"].dropna()
    total = df.loc[land.index, "hk_resident_departures_7d_ma"]
    assert (land <= total).all()


def test_fetch_weather_demand_drivers():
    from src.hk_local_consumer.sources.weather_demand_drivers import fetch_weather_demand_drivers
    df = fetch_weather_demand_drivers()
    assert not df.empty
    assert "signal_8_plus_hours" in df.columns
    assert "red_black_rain_hours" in df.columns
    assert "rmb_per_100_hkd" in df.columns
    assert len(df) >= 30


def test_stage_1_pipeline_execution(tmp_path):
    results = run_stage_1_pipeline()
    assert results is not None
    assert "afcd_wholesale_food_prices_daily" in results
    assert "consumer_council_price_watch_daily" in results
    assert "sge_gold_benchmark_daily" in results
    assert "hk_consumer_ticker_valuations_daily" in results
    assert "cnsd_retail_sales_monthly" in results
    assert "censtatd_fast_food_survey_quarterly" in results
    assert "immigration_passenger_traffic_daily" in results
    assert "weather_demand_drivers_monthly" in results

    manifest_file = tmp_path / "normalized" / "runs"
    assert manifest_file.exists()


def test_raw_snapshots_uniqueness():
    first = save_raw_snapshot("test_src", {"a": 1}, file_ext="json", source_url="https://test.com")
    second = save_raw_snapshot("test_src", {"a": 1}, file_ext="json", source_url="https://test.com")
    assert first != second
    metadata = json.loads(first.with_suffix(".meta.json").read_text())
    assert metadata["source_name"] == "test_src"


def test_save_normalized_dataset():
    df = pd.DataFrame([{"date": "2026-07-23", "commodity_name": "Pork", "price_hkd_per_kg": 40.0}])
    res = save_normalized_dataset("test_dataset", df, run_id="run-999")
    assert "run-999" in res["parquet"]
    lineage = json.loads(Path(res["lineage"]).read_text())
    assert lineage["records"] == 1


def _load_comparison_row():
    """Import _comparison_row from the artifact builder script, which lives
    outside the src/ package tree (apps/asia-markets-dashboard/scripts)."""
    scripts_dir = Path(__file__).resolve().parents[1] / "apps" / "asia-markets-dashboard" / "scripts"
    spec = importlib.util.spec_from_file_location(
        "build_hk_local_consumer_artifact", scripts_dir / "build_hk_local_consumer_artifact.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._comparison_row


def _load_local_consumer_artifact_builder():
    scripts_dir = Path(__file__).resolve().parents[1] / "apps" / "asia-markets-dashboard" / "scripts"
    spec = importlib.util.spec_from_file_location(
        "build_hk_local_consumer_artifact", scripts_dir / "build_hk_local_consumer_artifact.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pricewatch_archive_coverage_requires_valid_loaded_history():
    builder = _load_local_consumer_artifact_builder()
    valid = pd.DataFrame(
        [
            {
                "year_month": "2024-01",
                "category_1": "Food",
                "supermarket_code": "A",
                "avg_price": 10.0,
                "item_count": 4,
            },
            {
                "year_month": "2024-02",
                "category_1": "Food",
                "supermarket_code": "B",
                "avg_price": 12.0,
                "item_count": 5,
            },
        ]
    )
    valid.attrs["archive_validation"] = {"complete": True}

    assert builder._pricewatch_archive_coverage(pd.DataFrame()) == []
    invalid_counts = valid.assign(item_count=0)
    invalid_counts.attrs["archive_validation"] = {"complete": True}
    assert builder._pricewatch_archive_coverage(invalid_counts) == []

    coverage = builder._pricewatch_archive_coverage(valid)
    assert coverage == [
        {
            "first_observation": "2024-01",
            "latest_observation": "2024-02",
            "months": 2,
            "category_supermarket_aggregates": 2,
            "categories": 1,
            "supermarkets": 2,
            "notes": coverage[0]["notes"],
        }
    ]
    assert "not a price index" in coverage[0]["notes"]


def test_comparison_row_zero_prior_value_does_not_raise():
    """Regression test: total_disruption_hours is genuinely 0.0 in most quiet
    months (HK's dry season). _comparison_row must not raise ZeroDivisionError
    when the prior-period or year-ago value is 0 -- previously this crashed the
    entire dashboard build, not just the weather card."""
    comparison_row = _load_comparison_row()
    import datetime as dt

    now = dt.datetime(2026, 7, 23, tzinfo=dt.timezone.utc)
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp("2025-07-01"), "total_disruption_hours": 0.0},
            {"date": pd.Timestamp("2026-06-01"), "total_disruption_hours": 0.0},
            {"date": pd.Timestamp("2026-07-01"), "total_disruption_hours": 12.5},
        ]
    )
    result = comparison_row(frame, "total_disruption_hours", now)
    assert result["latest"] == 12.5
    assert result["period_change"] is None
    assert result["year_change"] is None


def test_comparison_row_nonzero_still_computes_percent():
    comparison_row = _load_comparison_row()
    import datetime as dt

    now = dt.datetime(2026, 7, 23, tzinfo=dt.timezone.utc)
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp("2025-07-01"), "total_disruption_hours": 10.0},
            {"date": pd.Timestamp("2026-06-01"), "total_disruption_hours": 20.0},
            {"date": pd.Timestamp("2026-07-01"), "total_disruption_hours": 25.0},
        ]
    )
    result = comparison_row(frame, "total_disruption_hours", now)
    assert result["period_change"] == pytest.approx(0.25)
    assert result["year_change"] == pytest.approx(1.5)
