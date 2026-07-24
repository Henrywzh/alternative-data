import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.hk_real_estate.sources.midland import parse_midland_mhpi, parse_midland_confidence, parse_midland_estate_counts
from src.hk_real_estate.sources.centaline import fetch_centaline_ccl, parse_centaline_ccl_payload
from src.hk_real_estate.sources.hse28 import fetch_28hse_new_projects
from src.hk_real_estate.sources.rvd import _parse_rvd_monthly_csv
from src.hk_real_estate.sources.landreg import fetch_landreg_monthly_sp
from src.hk_real_estate.storage import save_normalized_dataset, save_raw_snapshot
from src.hk_real_estate.mapping.developer_registry import DeveloperRegistry
from src.hk_real_estate.sources.hkma import fetch_hkma_residential_mortgage_survey
from src.hk_real_estate.sources.bd_projects import parse_bd_xls_projects, fetch_bd_supply_leading_indicators
from src.hk_real_estate.dedup.transaction_dedup import deduplicate_agency_transactions
from src.hk_real_estate.sources.srpe import fetch_srpe_firsthand_sales_digest


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    """No test may write into the user's data/raw or data/normalized directories."""
    raw_dir = tmp_path / "raw"
    norm_dir = tmp_path / "normalized"
    raw_dir.mkdir()
    norm_dir.mkdir()
    import src.hk_real_estate.storage as storage_mod
    import src.hk_real_estate.pipeline as pipeline_mod

    monkeypatch.setattr(storage_mod, "RAW_DIR", raw_dir)
    monkeypatch.setattr(storage_mod, "NORMALIZED_DIR", norm_dir)
    monkeypatch.setattr(pipeline_mod, "NORMALIZED_DIR", norm_dir)
    return tmp_path


def test_import_smoke():
    for module in (
        "src.hk_real_estate.config",
        "src.hk_real_estate.sources.centaline",
        "src.hk_real_estate.sources.hse28",
        "src.hk_real_estate.sources.hkma",
        "src.hk_real_estate.sources.bd_projects",
        "src.hk_real_estate.mapping.developer_registry",
        "src.hk_real_estate.dedup.transaction_dedup",
        "src.hk_real_estate.pipeline",
    ):
        assert importlib.import_module(module)


def test_transaction_deduplication():
    df1 = pd.DataFrame([
        {
            "estate_name": "Taikoo Shing",
            "floor_level": "15F",
            "unit_flat": "A",
            "transaction_date": "2026-07-20",
            "price_hkd": 12500000.0,
            "saleable_area_sqft": 680,
            "source_platform": "28Hse",
            "source_record_id": "hse-101"
        }
    ])
    df2 = pd.DataFrame([
        {
            "estate_name": "Taikoo Shing",
            "floor_level": "15F",
            "unit_flat": "A",
            "transaction_date": "2026-07-20",
            "price_hkd": 12500000.0,
            "saleable_area_sqft": 680,
            "source_platform": "Midland",
            "source_record_id": "midland-909"
        }
    ])
    
    deduped = deduplicate_agency_transactions([df1, df2])
    assert len(deduped) == 1
    assert deduped.iloc[0]["estate_name"] == "Taikoo Shing"
    assert deduped.iloc[0]["matched_agency_count"] == 2
    assert "28Hse" in deduped.iloc[0]["source_agencies"]
    assert "Midland" in deduped.iloc[0]["source_agencies"]


def test_developer_registry_confidence_tiers():
    registry = DeveloperRegistry()
    match_exact, tier1 = registry.match_project("YOHO WEST")
    assert tier1 == "EXACT"
    assert match_exact["stock_code"] == "0016"

    match_alias, tier2 = registry.match_project("天水圍YOHO")
    assert tier2 == "ALIAS"
    assert match_alias["stock_code"] == "0016"

    match_fuzzy, tier3 = registry.match_project("YOHO WEST Development Block C")
    assert tier3 == "FUZZY"
    assert match_fuzzy["stock_code"] == "0016"

    match_none, tier4 = registry.match_project("Random Unlisted Site Address")
    assert tier4 == "UNMATCHED"
    assert match_none is None

    df = pd.DataFrame([
        {"site_address": "YOHO WEST Development Block C"},
        {"site_address": "Unmatched Site"}
    ])
    attr_df = registry.attribute_dataframe(df, project_col="site_address")
    assert attr_df.iloc[0]["matched_stock_code"] == "0016"
    assert attr_df.iloc[0]["match_confidence_tier"] == "FUZZY"
    assert attr_df.iloc[1]["match_confidence_tier"] == "UNMATCHED"
    assert attr_df.attrs["unmatched_rate_pct"] == 50.0


@patch("src.hk_real_estate.sources.hkma.requests.get")
def test_hkma_percentage_scaling_and_date_semantics(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": {
            "records": [
                {
                    "end_of_month": "2026-05",
                    "new_loans_app_received": 10767,
                    "new_loans_approved_amt": 40231,
                    "ir_new_loans_approved_hibor": 0.738,
                    "ir_new_loans_approved_blr": 0.012,
                    "ir_new_loans_approved_fixed": 0.207,
                    "delinquency_ratio": 0.11
                }
            ]
        }
    }
    mock_get.return_value = mock_resp
    
    df = fetch_hkma_residential_mortgage_survey()
    assert not df.empty
    assert len(df) == 1
    assert df.iloc[0]["observation_date"] == "2026-05-01"
    assert df.iloc[0]["hibor_pricing_pct_share"] == 73.8
    assert df.iloc[0]["blr_pricing_pct_share"] == 1.2
    assert df.iloc[0]["fixed_pricing_pct_share"] == 20.7
    assert df.iloc[0]["delinquency_ratio_pct"] == 0.11
    assert df.iloc[0]["publication_date"] is None


def test_parse_midland_mhpi():
    df = parse_midland_mhpi({"mrIndexWeekly": [{"date": "2026-03-14T00:00:00.000Z", "mr_index": 124.7, "mr_index_hk": 140.5, "mr_index_kln": 121.2, "mr_index_nt": 116.5, "weekly_perc": -0.5}]})
    assert len(df) == 1
    assert df.iloc[0]["date"] == "2026-03-14"
    assert df.iloc[0]["mhpi_overall"] == 124.7


def test_parse_rvd_monthly_csv_reads_all_classes_and_remarks():
    sample_csv = """PRIVATE DOMESTIC - PRICE INDICES,,,,,,,,,,,,,,,,
Month,Class A,Class A - Remarks,Class B,Class B - Remarks,Class C,Class C - Remarks,Class D,Class D - Remarks,Class E,Class E - Remarks,"Classes A, B & C","Classes A, B & C - Remarks",Classes D & E,Classes D & E - Remarks,All Classes,All Classes - Remarks
01-2026,288.1,,278.4,,268.2,,255.0,,248.1,,300.0,,290.0,,321.9,
05-2026,286.6,,276.9,,266.8,,253.5,,246.8,,298.0,,288.0,,320.5,P
"""
    df = _parse_rvd_monthly_csv(sample_csv)
    assert len(df) == 2
    assert df.iloc[0]["overall"] == 321.9
    assert df.iloc[1]["overall"] == 320.5
    assert bool(df.iloc[1]["is_provisional"]) is True


def test_raw_snapshots_are_unique_and_preserve_actual_extension(tmp_path):
    first = save_raw_snapshot("example", "<html/>", file_ext="html", source_url="https://example.test")
    second = save_raw_snapshot("example", "<html/>", file_ext="html", source_url="https://example.test")
    assert first != second
    assert first.suffix == ".html"
    metadata = json.loads(first.with_suffix(".meta.json").read_text())
    assert metadata["source_url"] == "https://example.test"
    assert metadata["sha256"]


def test_save_normalized_dataset_is_run_scoped_and_has_lineage():
    result = save_normalized_dataset("test_dataset", pd.DataFrame([{"date": "2026-07-22", "val": 100.0}]), run_id="run-123", raw_snapshot="/tmp/raw.csv")
    assert "/test_dataset/run-123/" in result["csv"]
    lineage = json.loads(Path(result["lineage"]).read_text())
    assert lineage["raw_snapshot"] == "/tmp/raw.csv"
