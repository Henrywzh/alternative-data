"""Tests for source-PDF recovery, kept separate from interpolation tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
NORMALIZED = ROOT / "data" / "normalized" / "hk_transport"
RAW = ROOT / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"


def test_source_recovery_layer_has_audited_recovered_and_undisclosed_rows() -> None:
    recovered_path = NORMALIZED / "airline_operating_kpi_source_recovered.parquet"
    audit_path = NORMALIZED / "airline_operating_kpi_source_recovery_audit.csv"
    if not recovered_path.exists() or not audit_path.exists():
        return

    raw = pd.read_parquet(RAW)
    recovered = pd.read_parquet(recovered_path)
    audit = pd.read_csv(audit_path)
    keys = ["month", "airline_code", "region", "metric"]

    assert recovered.groupby(keys, dropna=False).size().max() == 1
    assert set(audit["status"]) == {
        "recovered_from_cached_official_pdf",
        "not_disclosed_in_source_pdf",
    }
    assert int(
        (audit["status"] == "recovered_from_cached_official_pdf").sum()
    ) == 178
    assert int(
        (audit["status"] == "not_disclosed_in_source_pdf").sum()
    ) == 22

    source_rows = recovered[recovered["recovery_method"].notna()]
    assert len(source_rows) == 178
    assert source_rows["source_quality"].eq(
        "issuer_cninfo_operating_release_recovered"
    ).all()
    assert source_rows["source_pdf_url"].notna().all()

    undisclosed = audit[audit["status"].eq("not_disclosed_in_source_pdf")]
    assert len(undisclosed) == 22
    assert undisclosed["disclosure_check"].eq(
        "not_disclosed_in_source_pdf"
    ).all()
    assert not undisclosed["source_text_metric_present"].fillna(False).any()
    assert not undisclosed["parser_metric_present"].fillna(False).any()
    assert undisclosed["companion_parser_metrics"].str.contains(
        "atk", na=False
    ).all()
    assert undisclosed["companion_parser_metrics"].str.contains(
        "rftk", na=False
    ).all()
    recovered_audit = audit[audit["status"].eq("recovered_from_cached_official_pdf")]
    assert recovered_audit["disclosure_check"].eq("parser_gap_recovered").all()
    assert recovered_audit["parser_metric_present"].fillna(False).all()


def test_source_recovery_layer_remains_explicitly_labelled() -> None:
    """Recovery output carries a distinct lineage label from issuer rows."""
    recovered_path = NORMALIZED / "airline_operating_kpi_source_recovered.parquet"
    if not recovered_path.exists():
        return
    recovered = pd.read_parquet(recovered_path)
    source_rows = recovered[recovered["recovery_method"].notna()]
    assert len(source_rows) == 178
    assert source_rows["source_quality"].eq(
        "issuer_cninfo_operating_release_recovered"
    ).all()
    assert source_rows["recovery_note"].notna().all()
