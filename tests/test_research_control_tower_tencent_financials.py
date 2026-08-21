"""Contract and leakage tests for Tencent official historical financials."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.research_control_tower_tencent_financials import (
    REQUIRED_CORE_METRICS,
    SUPPORTED_METRIC_BASES,
    TENCENT_EARNINGS_ACTUALS_COLUMNS,
    TENCENT_ENTITY_ID,
    TENCENT_LISTING_ID,
    assess_core_quarter_coverage,
    load_tencent_disclosure_records,
    parse_and_collect_tencent_actuals,
    transform_tencent_disclosures_to_actuals,
    validate_tencent_actuals,
)
from src.research_control_tower.build import SOURCE_STATE_COLUMNS


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tencent_ir"
FIXTURE_PATH = FIXTURE_DIR / "tencent_disclosures_2021_2026.json"
EXPECTED_HKEX_METADATA = {
    "1Q2021": ("2021-05-20T08:30:00Z", "hkexnews:9771605", "2021052000308"),
    "2Q2021": ("2021-08-18T08:36:00Z", "hkexnews:9898606", "2021081800391"),
    "3Q2021": ("2021-11-10T08:36:00Z", "hkexnews:10007323", "2021111000481"),
    "4Q2021": ("2022-03-23T08:31:00Z", "hkexnews:10168304", "2022032300430"),
    "1Q2022": ("2022-05-18T08:30:00Z", "hkexnews:10264906", "2022051800271"),
    "2Q2022": ("2022-08-17T08:30:00Z", "hkexnews:10389095", "2022081700319"),
    "3Q2022": ("2022-11-16T08:40:00Z", "hkexnews:10508846", "2022111600375"),
    "4Q2022": ("2023-03-22T08:33:00Z", "hkexnews:10640498", "2023032200281"),
    "1Q2023": ("2023-05-17T08:30:00Z", "hkexnews:10739945", "2023051700239"),
    "2Q2023": ("2023-08-16T08:38:00Z", "hkexnews:10854099", "2023081600440"),
    "3Q2023": ("2023-11-15T08:30:00Z", "hkexnews:10969152", "2023111500283"),
    "4Q2023": ("2024-03-20T08:39:00Z", "hkexnews:11106351", "2024032000508"),
    "1Q2024": ("2024-05-14T08:30:00Z", "hkexnews:11210132", "2024051400293"),
    "2Q2024": ("2024-08-14T08:30:00Z", "hkexnews:11321791", "2024081400282"),
    "3Q2024": ("2024-11-13T08:30:00Z", "hkexnews:11439424", "2024111300327"),
    "4Q2024": ("2025-03-19T08:30:00Z", "hkexnews:11576382", "2025031900336"),
    "1Q2025": ("2025-05-14T08:31:00Z", "hkexnews:11673735", "2025051400273"),
    "2Q2025": ("2025-08-13T08:30:00Z", "hkexnews:11793093", "2025081300261"),
    "3Q2025": ("2025-11-13T08:30:00Z", "hkexnews:11914783", "2025111300286"),
    "4Q2025": ("2026-03-18T08:30:00Z", "hkexnews:12056832", "2026031800388"),
    "1Q2026": ("2026-05-13T08:31:00Z", "hkexnews:12157226", "2026051300334"),
    "2Q2026": ("2026-08-12T08:31:00Z", "hkexnews:12280990", "2026081200296"),
}


def _record(period_label: str) -> dict[str, object]:
    return next(
        item
        for item in load_tencent_disclosure_records(FIXTURE_PATH)
        if item["period_label"] == period_label
    )


def test_fixture_uses_audited_hkex_metadata_and_real_document_ids():
    records = load_tencent_disclosure_records(FIXTURE_PATH)

    assert len(records) == 22
    assert records[0]["period_label"] == "1Q2021"
    assert records[-1]["period_label"] == "2Q2026"

    older = _record("1Q2021")
    assert older["accepted_at"] == "2021-05-20T08:30:00Z"
    assert older["accession_no"] == "hkexnews:9771605"
    assert older["source_document_id"] == "2021052000308"
    assert older["source_url"].endswith("/2021/0520/2021052000308.pdf")

    for label, (published_at, accession_no, document_id) in EXPECTED_HKEX_METADATA.items():
        item = _record(label)
        assert item["filing_at"] == published_at
        assert item["published_at"] == published_at
        assert item["accepted_at"] == published_at
        assert item["accession_no"] == accession_no
        assert item["source_document_id"] == document_id
        assert item["source_url"].startswith("https://www1.hkexnews.hk/")
        assert item["source_url"].endswith(f"/{document_id}.pdf")
        assert item["timestamp_precision"] == "minute"
        assert item["source_timezone"] == "Asia/Hong_Kong"


@pytest.mark.parametrize(
    ("document_id", "expected_sha256"),
    [
        (
            "2021052000308",
            "4d2fe2bf9e9ebf3de9e1a9f498f6b079fcbbdd2f128d5b392a926528a93806c7",
        ),
        (
            "2026081200296",
            "6ae9083e568a17ea49c796c5f6d15741a5ab720b0d98e8e97291292a29385119",
        ),
    ],
)
def test_archived_official_pdf_hashes_are_real(document_id, expected_sha256):
    document = FIXTURE_DIR / "source_documents" / f"{document_id}.pdf"
    assert document.read_bytes().startswith(b"%PDF")
    assert hashlib.sha256(document.read_bytes()).hexdigest() == expected_sha256
    fixture_row = next(
        item
        for item in load_tencent_disclosure_records(FIXTURE_PATH)
        if item["source_document_id"] == document_id
    )
    assert fixture_row["source_document_sha256"] == expected_sha256


def test_values_and_page_references_are_backed_by_archived_official_pdfs():
    PdfReader = pytest.importorskip("pypdf").PdfReader
    older_pdf = PdfReader(
        FIXTURE_DIR / "source_documents" / "2021052000308.pdf"
    )
    older_page_one = older_pdf.pages[0].extract_text()
    older_reconciliation = older_pdf.pages[13].extract_text()
    assert "Revenues 135,303" in older_page_one
    assert "Operating profit 56,273" in older_page_one
    assert "– diluted 4.917" in older_page_one
    assert "42,758" in older_reconciliation
    assert (
        _record("1Q2021")["source_page_refs"]["operating_profit_non_ifrs"]
        == "PDF p. 14, Non-IFRS reconciliation, current three-month period column"
    )

    recent_pdf = PdfReader(
        FIXTURE_DIR / "source_documents" / "2026081200296.pdf"
    )
    recent_page_one = recent_pdf.pages[0].extract_text()
    recent_capex_page = recent_pdf.pages[11].extract_text()
    recent_fcf_page = recent_pdf.pages[16].extract_text()
    assert "Revenues 204,785" in recent_page_one
    assert "Operating profit 67,276" in recent_page_one
    assert "Non-IFRS operating profit 75,636" in recent_page_one
    assert "52,784" in recent_capex_page
    assert "free cash flow" in recent_fcf_page.lower()
    assert "RMB13.8 billion" in recent_fcf_page


def test_transform_has_enriched_exact_contract_and_unblended_tracks():
    rows = transform_tencent_disclosures_to_actuals(
        [_record("2Q2026")],
        as_of_utc=pd.Timestamp("2026-08-21T12:00:00Z"),
    )
    frame = pd.DataFrame(rows)

    assert list(frame.columns) == TENCENT_EARNINGS_ACTUALS_COLUMNS
    assert len(frame) == 9  # seven core track rows plus capex and FCF
    assert set(frame["metric_basis"]) == {"GAAP_REPORTED", "NON_IFRS_MANAGEMENT"}
    assert set(frame["accounting_basis"]) == {"IFRS", "Non-IFRS management measure"}
    assert frame["source_document_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert frame["source_page_ref"].str.startswith("PDF p.").all()
    assert set(frame["value_origin"]) == {"direct_quarterly_disclosure"}
    assert set(frame["timestamp_precision"]) == {"minute"}
    assert set(frame["accession_no"]) == {"hkexnews:12280990"}
    assert set(frame["source_document_id"]) == {"2026081200296"}

    q2 = frame.set_index(["metric", "metric_basis"])
    assert q2.loc[("revenue_total", "GAAP_REPORTED"), "reported_value"] == 204785e6
    assert q2.loc[("operating_profit", "GAAP_REPORTED"), "reported_value"] == 67276e6
    assert q2.loc[("operating_profit", "NON_IFRS_MANAGEMENT"), "reported_value"] == 75636e6
    assert q2.loc[("net_profit_attributable", "GAAP_REPORTED"), "reported_value"] == 56022e6
    assert q2.loc[("net_profit_attributable", "NON_IFRS_MANAGEMENT"), "reported_value"] == 68415e6
    assert q2.loc[("diluted_eps", "GAAP_REPORTED"), "reported_value"] == 6.104
    assert q2.loc[("diluted_eps", "NON_IFRS_MANAGEMENT"), "reported_value"] == 7.433
    assert q2.loc[("capex", "GAAP_REPORTED"), "reported_value"] == 52784e6
    assert q2.loc[("free_cash_flow", "NON_IFRS_MANAGEMENT"), "reported_value"] == -13800e6

    for actual_id in frame["actual_id"]:
        assert "12280990" in actual_id
        assert "2Q2026" in actual_id
        assert actual_id.endswith("_v1")


def test_q4_values_are_direct_columns_not_fy_minus_nine_months():
    rows = transform_tencent_disclosures_to_actuals(
        [_record("4Q2025")],
        as_of_utc=pd.Timestamp("2026-03-18T09:00:00Z"),
    )
    frame = pd.DataFrame(rows)

    assert set(frame["value_origin"]) == {"direct_quarterly_disclosure"}
    assert set(frame["derivation_method"]) == {"direct_q4_column_in_annual_results"}
    assert set(frame["source_page_ref"]) == {
        "PDF p. 1, Financial Performance Highlights, three months ended 31 December 2025"
    }


def test_as_of_excludes_future_disclosures_without_timestamp_leakage():
    frame, state = parse_and_collect_tencent_actuals(
        fixture_path=FIXTURE_PATH,
        as_of_utc=pd.Timestamp("2022-06-01T00:00:00Z"),
    )

    assert set(frame["period_label"]) == {
        "1Q2021",
        "2Q2021",
        "3Q2021",
        "4Q2021",
        "1Q2022",
    }
    assert "2Q2022" not in set(frame["period_label"])
    cutoff = pd.Timestamp("2022-06-01T00:00:00Z")
    for column in ("filing_at", "published_at", "accepted_at", "retrieved_at_utc"):
        assert (frame[column] <= cutoff).all()
    assert (frame["filing_at"] <= frame["retrieved_at_utc"]).all()
    assert (frame["published_at"] <= frame["retrieved_at_utc"]).all()
    assert (frame["accepted_at"] <= frame["retrieved_at_utc"]).all()
    assert state.iloc[0]["status"] == "partial"
    assert "5 complete core quarters" in state.iloc[0]["detail"]


def test_2024_cutoff_does_not_emit_2025_or_2026_records():
    frame, state = parse_and_collect_tencent_actuals(
        fixture_path=FIXTURE_PATH,
        as_of_utc=pd.Timestamp("2024-06-01T00:00:00Z"),
    )

    assert frame["period_end"].max() == pd.Timestamp("2024-03-31T00:00:00Z")
    assert not frame["period_label"].str.contains("2025|2026").any()
    assert state.iloc[0]["status"] == "available"
    assert "13 complete core quarters" in state.iloc[0]["detail"]


def test_core_coverage_requires_four_required_metrics_in_each_distinct_quarter():
    full, _ = parse_and_collect_tencent_actuals(
        fixture_path=FIXTURE_PATH,
        as_of_utc=pd.Timestamp("2026-08-21T00:00:00Z"),
    )
    assert assess_core_quarter_coverage(full) == 22

    removed_periods = {f"{q}Q{year}" for year in range(2021, 2024) for q in range(1, 5)}
    incomplete = full[
        ~(
            full["metric"].eq("diluted_eps")
            & full["metric_basis"].eq("GAAP_REPORTED")
            & full["period_label"].isin(removed_periods)
        )
    ].copy()
    assert len(incomplete) > 12
    assert assess_core_quarter_coverage(incomplete) == 10
    assert REQUIRED_CORE_METRICS == {
        ("revenue_total", "GAAP_REPORTED"),
        ("operating_profit", "GAAP_REPORTED"),
        ("net_profit_attributable", "GAAP_REPORTED"),
        ("diluted_eps", "GAAP_REPORTED"),
    }


def test_parser_coverage_gate_is_not_metric_row_count(tmp_path):
    records = load_tencent_disclosure_records(FIXTURE_PATH)
    for item in records[:12]:
        item.pop("diluted_eps_gaap")
    broken_fixture = tmp_path / "broken.json"
    broken_fixture.write_text(json.dumps(records), encoding="utf-8")

    frame, state = parse_and_collect_tencent_actuals(
        fixture_path=broken_fixture,
        as_of_utc=pd.Timestamp("2026-08-21T00:00:00Z"),
    )
    assert len(frame) > 12
    assert state.iloc[0]["status"] == "partial"
    assert "10 complete core quarters" in state.iloc[0]["detail"]


def test_validation_rejects_wrong_schema_duplicate_and_nonfinite_values():
    frame, _ = parse_and_collect_tencent_actuals(
        fixture_path=FIXTURE_PATH,
        as_of_utc=pd.Timestamp("2026-08-21T00:00:00Z"),
    )

    with pytest.raises(ValueError, match="exact schema"):
        validate_tencent_actuals(frame.drop(columns=["metric_basis"]))

    duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate actual_id"):
        validate_tencent_actuals(duplicate)

    duplicate_natural_key = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    duplicate_natural_key.loc[len(duplicate_natural_key) - 1, "actual_id"] += "-other"
    with pytest.raises(ValueError, match="duplicate natural keys"):
        validate_tencent_actuals(duplicate_natural_key)

    nonfinite = frame.copy()
    nonfinite.loc[0, "reported_value"] = float("inf")
    with pytest.raises(ValueError, match="finite"):
        validate_tencent_actuals(nonfinite)

    bad_basis = frame.copy()
    bad_basis.loc[0, "metric_basis"] = "BLENDED"
    with pytest.raises(ValueError, match="metric_basis"):
        validate_tencent_actuals(bad_basis)


def test_full_pipeline_writes_atomic_loadable_outputs(tmp_path):
    output = tmp_path / "actuals"
    frame, state = parse_and_collect_tencent_actuals(
        fixture_path=FIXTURE_PATH,
        as_of_utc=pd.Timestamp("2026-08-21T12:00:00Z"),
        output_dir=output,
    )

    assert list(frame.columns) == TENCENT_EARNINGS_ACTUALS_COLUMNS
    assert list(state.columns) == SOURCE_STATE_COLUMNS
    assert len(frame) == (22 * 7) + 4
    assert state.iloc[0]["status"] == "available"
    assert state.iloc[0]["row_count"] == len(frame)
    assert not list(output.glob("*.tmp"))

    actuals_path = output / "tencent_earnings_actuals_v1.parquet"
    state_path = output / "tencent_earnings_actuals_state.parquet"
    assert actuals_path.is_file()
    assert state_path.is_file()
    loaded = pd.read_parquet(actuals_path)
    assert list(loaded.columns) == TENCENT_EARNINGS_ACTUALS_COLUMNS
    assert set(loaded["entity_id"]) == {TENCENT_ENTITY_ID}
    assert set(loaded["listing_id"]) == {TENCENT_LISTING_ID}
    assert set(loaded["metric_basis"]).issubset(SUPPORTED_METRIC_BASES)
