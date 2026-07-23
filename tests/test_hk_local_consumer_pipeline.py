import importlib
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
from src.hk_local_consumer.pipeline import run_stage_1_pipeline, QUALITY_SPECS
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


def test_parse_consumer_council_payload():
    payload = [
        {"code": "P101", "name": "Shampoo A", "category": "Personal Care", "brand": "BrandA", "supermarket": "Watsons", "price": 50.0, "original_price": 60.0},
        {"code": "P102", "name": "Lotion B", "category": "Skincare", "brand": "BrandB", "supermarket": "Mannings", "price": 80.0, "original_price": 80.0},
    ]
    df = parse_consumer_council_payload(payload)
    assert len(df) == 2
    assert bool(df.iloc[0]["is_on_sale"]) is True
    assert bool(df.iloc[1]["is_on_sale"]) is False


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
    df = fetch_cnsd_retail_sales()
    assert not df.empty
    assert "sales_value_index" in df.columns
    assert "Supermarkets" in set(df["category"])


def test_censtatd_restaurant_survey():
    df = fetch_censtatd_restaurant_survey()
    assert not df.empty
    assert "total_receipts_hkd_m" in df.columns
    assert "Fast food shops" in set(df["sub_sector"])
    assert "All restaurants" in set(df["sub_sector"])


def test_stage_1_pipeline_execution(tmp_path):
    results = run_stage_1_pipeline()
    assert results is not None
    assert "afcd_wholesale_food_prices_daily" in results
    assert "consumer_council_price_watch_daily" in results
    assert "sge_gold_benchmark_daily" in results
    assert "hk_consumer_ticker_valuations_daily" in results
    assert "cnsd_retail_sales_monthly" in results
    assert "censtatd_fast_food_survey_quarterly" in results

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
