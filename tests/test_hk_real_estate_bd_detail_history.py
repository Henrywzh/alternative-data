from unittest.mock import patch

import pandas as pd
import pytest

from src.hk_real_estate.sources.bd_history import (
    build_bd_project_lifecycle_history_audit,
    discover_bd_digest_monthly_pdf_urls,
    _detail_detect_columns,
    _detail_numeric,
    _detail_normalize_permit,
    parse_bd_detail_pdf,
    reparse_bd_project_lifecycle_history_from_local_snapshots,
)


class _FakePage:
    def __init__(self, text, words):
        self._text = text
        self._words = words

    def extract_text(self, layout=True):
        return self._text

    def extract_words(self, use_text_flow=True, keep_blank_chars=False):
        return self._words


class _FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _word(top, x0, text):
    return {"top": float(top), "x0": float(x0), "text": text}


def test_detail_parser_keeps_digest_month_and_explicitly_withholds_event_day():
    text = """
DETAILED INFORMATION
TABLE 5.6 COMPLETED NEW BUILDINGS FOR WHICH OCCUPATION PERMITS HAVE BEEN ISSUED
Address of Site Occupation Permit No. Blocks Storeys Building Type Domestic Units
"""
    words = [
        _word(100, 0, "Address of Site"),
        _word(100, 100, "Occupation Permit No."),
        _word(100, 180, "Blocks"),
        _word(120, 0, "1 Test Road,"),
        _word(120, 110, "HK1/2024/OP"),
        _word(120, 180, "1"),
        _word(120, 230, "10"),
        _word(120, 250, "Apartment"),
        _word(120, 337, "2"),
        _word(120, 372, "12.0"),
    ]
    fake_pdf = _FakePdf([_FakePage(text, words)])
    with patch("src.hk_real_estate.sources.bd_history.pdfplumber.open", return_value=fake_pdf):
        result = parse_bd_detail_pdf(b"pdf", "2024-01-01", "https://bd.example/Md202401e.pdf", 2024)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["digest_month"] == "2024-01-01"
    assert row["observation_month"] == "2024-01-01"
    assert pd.isna(row["event_date"])
    assert row["event_date_status"] == "not_published_in_monthly_digest"
    assert row["permit_number"] == "HK1/2024/OP"
    assert row["domestic_units_count"] == 2


def test_detail_parser_merges_unit_tiers_after_planning_reference():
    text = """
DETAILED INFORMATION
TABLE 5.6 COMPLETED NEW BUILDINGS FOR WHICH OCCUPATION PERMITS HAVE BEEN ISSUED
Address of Site Occupation Permit No. Blocks Storeys Building Type Domestic Units
"""
    words = [
        _word(100, 0, "Address of Site"),
        _word(100, 100, "Occupation Permit No."),
        _word(120, 0, "1 Test Road,"),
        _word(120, 110, "HK2/2024/OP"),
        _word(120, 180, "1"),
        _word(120, 230, "20"),
        _word(120, 250, "Apartment"),
        _word(120, 337, "2"),
        _word(120, 372, "12.0"),
        _word(127, 0, "2.1.1/(1)"),
        _word(127, 337, "3"),
        _word(127, 372, "14.0"),
    ]
    fake_pdf = _FakePdf([_FakePage(text, words)])
    with patch("src.hk_real_estate.sources.bd_history.pdfplumber.open", return_value=fake_pdf):
        result = parse_bd_detail_pdf(b"pdf", "2024-01-01", "https://bd.example/Md202401e.pdf", 2024)

    assert len(result) == 1
    assert result.iloc[0]["domestic_units_count"] == 5


def test_discover_monthly_pdf_urls_preserves_year_month_keys():
    html = """
    <a href="../../../doc/en/whats-new/monthly-digests/Md202601e.pdf">Jan</a>
    <a href="../../../doc/en/whats-new/monthly-digests/Md202602e.pdf">Feb</a>
    <a href="../../../doc/en/whats-new/monthly-digests/Md202603e_revised.pdf">Mar</a>
    """
    result = discover_bd_digest_monthly_pdf_urls(html)
    assert sorted(result) == [(2026, 1), (2026, 2), (2026, 3)]
    assert result[(2026, 3)].endswith("Md202603e_revised.pdf")


def test_local_reparse_reuses_raw_snapshot_and_records_v6_lineage(tmp_path):
    raw_path = tmp_path / "Md202401e.pdf"
    raw_path.write_bytes(b"cached pdf")
    source = pd.DataFrame(
        [
            {
                "raw_snapshot": str(raw_path),
                "digest_month": "2024-01-01",
                "observation_month": "2024-01-01",
                "source_url": "https://bd.example/Md202401e.pdf",
                "archive_year": 2024,
            }
        ]
    )
    parsed = pd.DataFrame(
        [
            {
                "digest_month": "2024-01-01",
                "observation_month": "2024-01-01",
                "permit_stage": "Occupation Permits (OP) Issued",
                "site_address": "1 Test Road",
                "applicant": "Pacific Good Investment Ltd",
                "parser_version": "bd-detail-history-v6",
            }
        ]
    )
    with patch("src.hk_real_estate.sources.bd_history.parse_bd_detail_pdf", return_value=parsed):
        result = reparse_bd_project_lifecycle_history_from_local_snapshots(source)

    assert len(result) == 1
    assert result.iloc[0]["raw_snapshot"] == str(raw_path)
    assert result.iloc[0]["applicant"] == "Pacific Good Investment Ltd"
    assert result.attrs["lineage_metadata"]["parser_version"] == "bd-detail-history-v6"
    assert result.attrs["lineage_metadata"]["raw_pdf_count"] == 1
    assert result.attrs["reparse_errors"] == []


def test_local_reparse_is_strict_on_missing_raw_snapshot(tmp_path):
    source = pd.DataFrame(
        [
            {
                "raw_snapshot": str(tmp_path / "missing.pdf"),
                "digest_month": "2024-01-01",
                "source_url": "https://bd.example/Md202401e.pdf",
                "archive_year": 2024,
            }
        ]
    )
    with pytest.raises(RuntimeError, match="local BD detail reparse failed"):
        reparse_bd_project_lifecycle_history_from_local_snapshots(source)


def test_detail_permit_normalizer_accepts_legacy_parenthesis_format():
    assert _detail_normalize_permit("HK 47/2015(OP)") == "HK47/2015/OP"


def test_detail_numeric_does_not_truncate_four_digit_unit_counts():
    assert _detail_numeric("1580", integer=True) == 1580
    assert _detail_numeric("1 275.0", integer=True) == 1


def test_detail_column_detector_tracks_shifted_occupation_permit_header():
    words = [
        _word(90, 17, "Occupation"), _word(90, 105, "No."), _word(90, 160, "of"),
        _word(90, 215, "No."), _word(90, 270, "of"), _word(90, 310, "Domestic"),
        _word(90, 335, "Units"), _word(90, 372, "Gross"), _word(90, 410, "Floor"),
        _word(90, 445, "Area"), _word(90, 500, "Usable"), _word(90, 540, "Floor"),
        _word(90, 570, "Area"), _word(90, 620, "Registered"), _word(90, 700, "Structural"),
        _word(100, 17, "Address"), _word(100, 105, "Permit"), _word(100, 130, "No."),
        _word(100, 160, "Blocks"), _word(100, 215, "Storeys"), _word(100, 232, "Building"),
        _word(100, 270, "Type"), _word(100, 307, "No."), _word(100, 335, "Unit"),
        _word(100, 372, "Domestic"), _word(100, 410, "Non-domestic"),
        _word(100, 450, "Domestic"), _word(100, 500, "Non-domestic"),
        _word(100, 520, "Authorized"), _word(100, 580, "Engineer"), _word(100, 645, "Applicant"),
        _word(100, 80, "of"), _word(100, 95, "Site"),
    ]
    columns = _detail_detect_columns(words, "Occupation Permits (OP) Issued")
    assert columns is not None
    bands = {name: (left, right) for name, left, right in columns}
    assert bands["units"][0] <= 307 < bands["units"][1]
    assert bands["unit_size"][0] <= 340 < bands["unit_size"][1]


def test_detail_column_detector_accepts_multiline_legacy_header_and_split_permit_prefix():
    words = [
        _word(90, 17, "Occupation"), _word(90, 105, "No."),
        _word(90, 215, "No."), _word(90, 331, "Domestic"),
        _word(90, 400, "Gross"), _word(90, 480, "Usable"),
        _word(100, 63, "Address"), _word(100, 83, "of"), _word(100, 89, "Site"),
        _word(100, 127, "Permit"),
        _word(100, 170, "Blocks"), _word(100, 215, "Storeys"),
        _word(100, 268, "Building"), _word(100, 356, "Unit"),
        _word(100, 552, "Authorized"), _word(100, 610, "Registered"),
        _word(100, 709, "Applicant"),
        _word(109, 388, "Domestic"), _word(109, 424, "Non-domestic"),
        _word(109, 470, "Domestic"), _word(109, 507, "Non-domestic"),
        _word(109, 623, "Engineer"), _word(115, 326, "No."),
        _word(115, 355, "Size"), _word(115, 365, "*"),
    ]
    columns = _detail_detect_columns(words, "Occupation Permits (OP) Issued")
    assert columns is not None
    bands = {name: (left, right) for name, left, right in columns}
    # The prefix may be extracted as a separate word before 55/2017(OP).
    assert bands["permit_number"][0] <= 119 < bands["permit_number"][1]
    assert bands["units"][0] <= 329 < bands["units"][1]
    assert bands["unit_size"][0] <= 359 < bands["unit_size"][1]


def test_detail_parser_keeps_distinct_same_address_plan_rows():
    text = """
DETAILED INFORMATION
TABLE 5.3 NEW BUILDINGS FOR WHICH PLANS HAVE BEEN APPROVED
Address of site Blocks Storeys Building type Domestic Non-domestic Authorized Person Engineer Applicant
"""
    words = [
        _word(100, 0, "Address of site"),
        _word(120, 0, "Oil Street"), _word(120, 180, "1"),
        _word(120, 245, "-"), _word(120, 270, "Public open space"),
        _word(120, 470, "LIANG"), _word(120, 660, "Ocean Century Investment Ltd"),
        _word(140, 0, "Oil Street"), _word(140, 180, "1"),
        _word(140, 245, "-"), _word(140, 270, "Public open space"),
        _word(140, 470, "YUNG"), _word(140, 660, "Ocean Century Investment Ltd"),
    ]
    fake_pdf = _FakePdf([_FakePage(text, words)])
    with patch("src.hk_real_estate.sources.bd_history.pdfplumber.open", return_value=fake_pdf):
        result = parse_bd_detail_pdf(b"pdf", "2012-12-01", "https://bd.example/Md201212e.pdf", 2012)

    assert len(result[result.permit_stage.eq("Plans Approved")]) == 2


def test_bd_history_audit_marks_match_gap_and_non_comparable_stage():
    detail = pd.DataFrame(
        [
            {
                "digest_month": "2020-12-01",
                "permit_stage": "Occupation Permits (OP) Issued",
                "site_address": "1 Test Road",
                "domestic_units_count": 10,
                "parser_quality_flag": "ok",
                "parser_confidence": "HIGH",
                "source_url": "https://bd.example/detail.pdf",
                "parser_version": "bd-detail-history-v3",
            },
            {
                "digest_month": "2020-12-01",
                "permit_stage": "Demolition Consents",
                "site_address": "2 Test Road",
                "domestic_units_count": None,
                "parser_quality_flag": "ok",
                "parser_confidence": "HIGH",
                "source_url": "https://bd.example/detail.pdf",
                "parser_version": "bd-detail-history-v3",
            },
        ]
    )
    summary = pd.DataFrame(
        [
            {
                "observation_month": "2020-12-01",
                "permit_stage": "Occupation Permits (OP) Issued",
                "total_domestic_units": 10,
                "total_projects_count": 1,
                "source_url": "https://bd.example/summary.pdf",
                "parser_version": "bd-summary-history-v1",
            }
        ]
    )
    result = build_bd_project_lifecycle_history_audit(detail, summary)
    statuses = dict(zip(result["permit_stage"], result["reconciliation_status"]))
    assert statuses["Occupation Permits (OP) Issued"] == "matched"
    assert statuses["Demolition Consents"] == "not_comparable"


def test_bd_history_audit_excludes_explicit_amendments_from_section_one_comparison():
    detail = pd.DataFrame(
        [
            {
                "digest_month": "2025-12-01",
                "permit_stage": "Notice of Commencement Received",
                "site_address": "1 Published Road",
                "domestic_units_count": 3,
                "revision_status": "as_published",
                "parser_quality_flag": "ok",
                "parser_confidence": "HIGH",
            },
            {
                "digest_month": "2025-12-01",
                "permit_stage": "Notice of Commencement Received",
                "site_address": "2 Amended Road",
                "domestic_units_count": 570,
                "revision_status": "amendment",
                "parser_quality_flag": "ok",
                "parser_confidence": "HIGH",
            },
        ]
    )
    summary = pd.DataFrame(
        [
            {
                "observation_month": "2025-12-01",
                "permit_stage": "Notice of Commencement Received",
                "total_domestic_units": 3,
                "total_projects_count": 1,
            }
        ]
    )
    result = build_bd_project_lifecycle_history_audit(detail, summary)
    row = result.iloc[0]
    assert row["reconciliation_status"] == "matched"
    assert row["comparison_detail_value"] == 3
    assert row["detail_row_count"] == 2
    assert row["detail_compared_row_count"] == 1
    assert row["detail_amendment_row_count"] == 1
    assert row["detail_amendment_domestic_units"] == 570


def test_bd_history_audit_labels_explicit_zero_domestic_units():
    detail = pd.DataFrame(
        [
            {
                "digest_month": "2024-12-01",
                "permit_stage": "Notice of Commencement Received",
                "site_address": "A non-domestic work",
                "domestic_units_count": None,
                "revision_status": "as_published",
            }
        ]
    )
    summary = pd.DataFrame(
        [
            {
                "observation_month": "2024-12-01",
                "permit_stage": "Notice of Commencement Received",
                "total_domestic_units": 0,
                "total_projects_count": 0,
            }
        ]
    )
    result = build_bd_project_lifecycle_history_audit(detail, summary)
    assert result.iloc[0]["reconciliation_status"] == "matched_zero"


def test_detail_parser_keeps_wrapped_2010_unit_tier_at_left_shifted_x_position():
    text = """
DETAILED INFORMATION
TABLE 5.6 COMPLETED NEW BUILDINGS FOR WHICH OCCUPATION PERMITS HAVE BEEN ISSUED
Address of Site Occupation Permit No. Blocks Storeys Building Type Domestic Units
"""
    words = [
        _word(100, 0, "Address of Site"),
        _word(100, 130, "Occupation Permit No."),
        _word(120, 0, "8 Test Road"),
        _word(120, 142, "HK35/2010(OP)"),
        _word(120, 205, "1"),
        _word(120, 244, "Apartment"),
        # Archived 2010 PDFs place some continuation counts at x=327.7.
        _word(120, 327.7, "103"),
        _word(120, 358.6, "42.4"),
    ]
    fake_pdf = _FakePdf([_FakePage(text, words)])
    with patch("src.hk_real_estate.sources.bd_history.pdfplumber.open", return_value=fake_pdf):
        result = parse_bd_detail_pdf(b"pdf", "2010-12-01", "https://bd.example/Md201012e.pdf", 2010)

    assert result.iloc[0]["domestic_units_count"] == 103


def test_detail_parser_uses_2020_shifted_unit_columns_not_unit_size():
    text = """
DETAILED INFORMATION
TABLE 5.6 COMPLETED NEW BUILDINGS FOR WHICH OCCUPATION PERMITS HAVE BEEN ISSUED
Address of Site Occupation Permit No. Blocks Storeys Building Type Domestic Units
"""
    words = [
        _word(100, 0, "Address of Site"),
        _word(100, 105, "Occupation Permit No."),
        _word(120, 0, "8 Test Road"),
        _word(120, 113, "HK54/2020(OP)"),
        _word(120, 161.9, "1"),
        _word(120, 231.6, "Apartment"),
        _word(120, 303.0, "622"),
        _word(120, 340.1, "12.9"),
    ]
    fake_pdf = _FakePdf([_FakePage(text, words)])
    with patch("src.hk_real_estate.sources.bd_history.pdfplumber.open", return_value=fake_pdf):
        result = parse_bd_detail_pdf(b"pdf", "2020-12-01", "https://bd.example/Md202012e.pdf", 2020)

    assert result.iloc[0]["domestic_units_count"] == 622
