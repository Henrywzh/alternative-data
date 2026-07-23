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
        "src.hk_real_estate.pipeline",
    ):
        assert importlib.import_module(module)


def test_parse_midland_mhpi():
    df = parse_midland_mhpi({"mrIndexWeekly": [{"date": "2026-03-14T00:00:00.000Z", "mr_index": 124.7, "mr_index_hk": 140.5, "mr_index_kln": 121.2, "mr_index_nt": 116.5, "weekly_perc": -0.5}]})
    assert len(df) == 1
    assert df.iloc[0]["date"] == "2026-03-14"
    assert df.iloc[0]["mhpi_overall"] == 124.7


def test_parse_midland_confidence():
    df = parse_midland_confidence({"confidenceIndex": [{"date": "2026-03-14T00:00:00.000Z", "confidence_index": 76.3, "confidence_avg_index": 61.2, "weekly_perc": 3.0}]})
    assert len(df) == 1
    assert df.iloc[0]["confidence_index"] == 76.3


def test_parse_midland_estate_counts_uses_nested_market_stat():
    df = parse_midland_estate_counts({"estatesTransactionCount": {"result": [{"id": "E00385", "name": "宏福苑", "region": {"name": "新界"}, "district": {"name": "大埔墟"}, "market_stat": {"tx_count": 15}}]}})
    assert len(df) == 1
    assert df.iloc[0]["transaction_count"] == 15


def test_parse_centaline_payload_uses_explicit_json_arrays_without_code_execution():
    payload = {"ccl": {"chartData": {"date": ["1997-07-06", "1997-07-13"], "index": [100.0, 100.5]}}}
    df = parse_centaline_ccl_payload(payload)
    assert df.to_dict("records") == [
        {"date": "1997-07-06", "ccl_index": 100.0, "source_agency": "Centaline Property Agency"},
        {"date": "1997-07-13", "ccl_index": 100.5, "source_agency": "Centaline Property Agency"},
    ]
    assert parse_centaline_ccl_payload({"ccl": {"chartData": {"date": ["1997-07-06"], "index": []}}}).empty


@patch("src.hk_real_estate.sources.centaline.requests.get")
def test_fetch_centaline_ccl_requests_json_endpoint(mock_get):
    response = MagicMock()
    response.text = '{"ccl": {"chartData": {"date": ["1997-07-06"], "index": [100.0]}}}'
    response.json.return_value = {"ccl": {"chartData": {"date": ["1997-07-06"], "index": [100.0]}}}
    mock_get.return_value = response
    df = fetch_centaline_ccl()
    assert df.iloc[0]["ccl_index"] == 100.0
    assert mock_get.call_args.args[0].endswith("/CCI/api/Index/CCL")


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


@patch("src.hk_real_estate.sources.landreg.requests.get")
def test_fetch_landreg_monthly_sp_catalog(mock_get):
    response = MagicMock()
    response.text = '<html><body><a href="/en/monthly/202605.htm">Statistics May 2026</a></body></html>'
    mock_get.return_value = response
    df = fetch_landreg_monthly_sp()
    assert df.iloc[0]["date"] == "2026-05-01"


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


def test_empty_catalog_is_recorded_and_group_exits_as_failure(monkeypatch, tmp_path):
    import src.hk_real_estate.pipeline as pipeline

    latest = "2026-07-12"
    mhpi = pd.DataFrame([{ "date": latest, "mhpi_overall": 100.0 }])
    confidence = pd.DataFrame([{ "date": latest, "confidence_index": 60.0 }])
    estates = pd.DataFrame([{ "estate_id": "E1", "estate_name": "Estate", "transaction_count": 1 }])
    ccl = pd.DataFrame([{ "date": latest, "ccl_index": 150.0 }])
    monkeypatch.setattr(pipeline, "run_midland_ingestion", lambda: (mhpi, confidence, estates))
    monkeypatch.setattr(pipeline, "fetch_centaline_ccl", lambda: ccl)
    monkeypatch.setattr(pipeline, "fetch_28hse_new_projects", lambda: pd.DataFrame(columns=["project_name"]))

    with pytest.raises(pipeline.PipelineRunError) as exc:
        pipeline.run_group_a_pipeline(run_id="run-empty")
    manifest = json.loads(Path(exc.value.manifest_path).read_text())
    assert manifest["groups"]["group_a"]["hse28_new_projects_catalog"]["status"] == "empty"


def test_cli_returns_nonzero_when_pipeline_reports_failure(monkeypatch):
    import src.hk_real_estate.cli as cli
    import src.hk_real_estate.pipeline as pipeline

    failure = pipeline.PipelineRunError("bad data", {}, "/tmp/manifest.json")
    monkeypatch.setattr(cli, "run_group_a_pipeline", lambda: (_ for _ in ()).throw(failure))
    monkeypatch.setattr(sys, "argv", ["hk-real-estate", "run-group-a"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
