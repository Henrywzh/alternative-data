import json

import pandas as pd

from src.hk_real_estate.sources.land_planning import (
    extract_tpb_application_detail_urls,
    fetch_landsd_consent_facts,
    fetch_landsd_monthly_consent_facts,
    fetch_tpb_application_details,
    parse_landsd_monthly_consent_page_words,
    parse_landsd_consent_page_words,
    parse_tpb_application_detail_html,
)
from src.hk_real_estate.pipeline import _select_landsd_consent_urls


def test_tpb_listing_extracts_application_details_but_not_back_or_attachment_pages():
    html = """
    <a href="application_comment.html">Back</a>
    <a href="A_K10_281.html">A/K10/281</a>
    <a href="Y_TM-LTYY_12.html">Y/TM-LTYY/12</a>
    <a href="A_K10_281_ac.html">Applicant submission</a>
    """

    urls = extract_tpb_application_detail_urls(
        html, "https://www.tpb.gov.hk/en/plan_application/application_comment_list.html"
    )

    assert urls == [
        "https://www.tpb.gov.hk/en/plan_application/A_K10_281.html",
        "https://www.tpb.gov.hk/en/plan_application/Y_TM-LTYY_12.html",
    ]


def test_landsd_selector_prefers_one_accessible_since_1994_pdf_per_district():
    urls = [
        "https://www.landsd.gov.hk/doc/en/consent/district/since1994/pdf/KE[from%201994].pdf",
        "https://www.landsd.gov.hk/doc/en/consent/district/since1994/accessible/KE[from%201994]wac_e.pdf",
        "https://www.landsd.gov.hk/doc/en/consent/district/since1994/pdf/Tuen%20Mun[from%201994].pdf",
        "https://www.landsd.gov.hk/doc/en/consent/district/since1994/accessible/Tuen%20Mun[from%201994]wac_e.pdf",
        "https://www.landsd.gov.hk/doc/en/consent/district/since1994/pdf/Yuen%20Long[from%201994].pdf",
        "https://www.landsd.gov.hk/doc/en/consent/district/since1994/accessible/Yuen%20Long[from%201994]wac_e.pdf",
    ]
    selected = _select_landsd_consent_urls(
        urls,
        priority_districts=["Kowloon East", "Tuen Mun"],
        max_urls=3,
    )
    assert selected == [
        "https://www.landsd.gov.hk/doc/en/consent/district/since1994/accessible/KE[from%201994]wac_e.pdf",
        "https://www.landsd.gov.hk/doc/en/consent/district/since1994/accessible/Tuen%20Mun[from%201994]wac_e.pdf",
    ]


def test_tpb_detail_parser_keeps_source_fields_and_further_information_raw():
    html = """
    <h2>Section 16 Application</h2>
    <p class="title">Application No.</p><p>A/K10/281</p>
    <p class="title">Plan Area</p><p>Ma Tau Kok</p>
    <p class="title">District</p><p>Kowloon District</p>
    <p class="title">Date of Application Received</p><p>30/06/2026</p>
    <p class="title">Location</p><p>New Kowloon Inland Lot 6658</p>
    <p class="title">Proposal</p><p>Proposed residential development</p>
    <p class="title">Tentative Date of Meeting</p><p>28/08/2026</p>
    <p class="title">Expiry Date for Making Comments (No. of Comments)</p><p>31/07/2026 (1)</p>
    <p class="title">Remark</p><p>-</p>
    <table><tr><th>Further Information Received on</th><td>10/07/2026</td></tr>
    <tr><th>Nature</th><td>Revised traffic assessment</td></tr>
    <tr><th>Decision</th><td>Accepted</td></tr></table>
    """

    frame = parse_tpb_application_detail_html(
        html, "https://www.tpb.gov.hk/en/plan_application/A_K10_281.html"
    )

    row = frame.iloc[0]
    assert row["application_no"] == "A/K10/281"
    assert row["application_type"] == "Section 16"
    assert row["application_received_date"] == "2026-06-30"
    assert row["location_raw"] == "New Kowloon Inland Lot 6658"
    assert row["comment_expiry_date"] == "2026-07-31"
    assert row["comment_count"] == 1
    assert json.loads(row["further_information_json"]) == [
        {
            "received_date": "2026-07-10",
            "received_date_raw": "10/07/2026",
            "nature_raw": "Revised traffic assessment",
            "decision_raw": "Accepted",
        }
    ]


def test_landsd_consent_parser_preserves_combined_source_entity_label_without_ownership_inference():
    words = [
        {"text": "1", "x0": 30, "top": 150},
        {"text": "Example", "x0": 40, "top": 150},
        {"text": "Heights", "x0": 80, "top": 150},
        {"text": "TMTL", "x0": 140, "top": 150},
        {"text": "422", "x0": 170, "top": 150},
        {"text": "Example Holdings Limited / Example Developer Limited", "x0": 230, "top": 150},
        {"text": "Consent to Sell", "x0": 340, "top": 150},
        {"text": "Example & Co.", "x0": 450, "top": 150},
        # Tai Po's official PDF places the date column near x=512; other
        # district layouts use x≈517–523.
        {"text": "26/02/2014", "x0": 512, "top": 150},
    ]

    frame = parse_landsd_consent_page_words(
        words,
        district="Tuen Mun",
        document_url="https://www.landsd.gov.hk/example.pdf",
        page_number=1,
        document_as_of_date="2026-06-30",
    )

    row = frame.iloc[0]
    assert row["development_name_raw"] == "Example Heights"
    assert row["lot_no_raw"] == "TMTL 422"
    assert row["parent_or_holding_company_or_developer_raw"] == "Example Holdings Limited / Example Developer Limited"
    assert row["consent_or_approval_date"] == "2014-02-26"
    assert "ownership" not in frame.columns


def test_landsd_consent_parser_handles_tai_po_column_boundaries():
    """Tai Po's PDF starts the lot/entity columns at x≈134.8/221.4."""
    words = [
        {"text": "1", "x0": 30, "top": 175},
        {"text": "SAI SHA RESIDENCES", "x0": 40, "top": 175},
        {"text": "TPTL", "x0": 134.8, "top": 175},
        {"text": "253 RP", "x0": 165, "top": 175},
        {"text": "Sun Hung Kai Properties Limited", "x0": 221.4, "top": 175},
        {"text": "Consent to Sell", "x0": 340, "top": 175},
        {"text": "Solicitor", "x0": 430, "top": 175},
        {"text": "26/02/2025", "x0": 512.2, "top": 175},
    ]

    frame = parse_landsd_consent_page_words(
        words,
        district="Tai Po",
        document_url="https://www.landsd.gov.hk/tai-po.pdf",
        page_number=10,
    )

    row = frame.iloc[0]
    assert row["development_name_raw"] == "SAI SHA RESIDENCES"
    assert row["lot_no_raw"] == "TPTL 253 RP"
    assert "Sun Hung Kai Properties Limited" in row[
        "parent_or_holding_company_or_developer_raw"
    ]
    assert "TPTL" not in row["development_name_raw"]


def test_landsd_consent_parser_accepts_hyphenated_official_dates():
    words = [
        {"text": "Cullinan Harbour Development", "x0": 30, "top": 200},
        {"text": "NKIL 6551", "x0": 135, "top": 200},
        {"text": "Sun Hung Kai Properties Limited", "x0": 221, "top": 200},
        {"text": "Consent to Sell", "x0": 340, "top": 200},
        {"text": "14-04-2023", "x0": 522, "top": 200},
    ]
    frame = parse_landsd_consent_page_words(
        words,
        district="Kowloon East",
        document_url="https://www.landsd.gov.hk/ke.pdf",
        page_number=8,
    )
    assert len(frame) == 1
    assert frame.loc[0, "consent_or_approval_date"] == "2023-04-14"


def test_landsd_monthly_consent_parser_keeps_vendor_and_holding_columns_separate():
    words = [
        {"text": "Lot 1071 in DD 103", "x0": 22, "top": 200},
        {"text": "No. 1A Ying Ho Road", "x0": 76, "top": 200},
        {"text": "Pending", "x0": 138, "top": 200},
        {"text": "Ease Gold Development Limited", "x0": 199, "top": 200},
        {"text": "Peak Harbour Development Limited", "x0": 261, "top": 200},
        {"text": "30/04/2027", "x0": 677, "top": 200},
        {"text": "566", "x0": 734, "top": 200},
    ]

    frame = parse_landsd_monthly_consent_page_words(
        words,
        document_url="https://www.landsd.gov.hk/doc/en/consent/monthly/t2_2601.pdf",
        page_number=1,
        document_as_of_date="2026-01-31",
        monthly_status="pending_approval",
    )

    row = frame.iloc[0]
    assert row["lot_no_raw"] == "Lot 1071 in DD 103"
    assert row["vendor_raw"] == "Ease Gold Development Limited"
    assert row["holding_company_raw"] == "Peak Harbour Development Limited"
    assert row["estimated_completion_date"] == "2027-04-30"
    assert row["residential_units"] == 566
    assert row["monthly_status"] == "pending_approval"


class _FakeResponse:
    def __init__(self, content):
        self.content = content
        self.text = content.decode("utf-8") if isinstance(content, bytes) else content

    def raise_for_status(self):
        return None


class _FakeSession:
    def __init__(self, responses):
        self.headers = {}
        self.responses = responses
        self.urls = []

    def get(self, url, timeout):
        self.urls.append(url)
        return _FakeResponse(self.responses[url])


def test_fetch_tpb_details_archives_and_skips_navigation_urls(monkeypatch, tmp_path):
    url = "https://www.tpb.gov.hk/en/plan_application/A_K10_281.html"
    html = b"""
    <h2>Section 16 Application</h2>
    <p class='title'>Application No.</p><p>A/K10/281</p>
    <p class='title'>Location</p><p>New Kowloon Inland Lot 6658</p>
    """
    session = _FakeSession({url: html})
    monkeypatch.setattr(
        "src.hk_real_estate.sources.land_planning.save_raw_snapshot",
        lambda *args, **kwargs: tmp_path / "detail.html",
    )

    frame = fetch_tpb_application_details(
        ["https://www.tpb.gov.hk/en/plan_application/application_comment.html", url],
        session=session,
        max_records=1,
    )

    assert session.urls == [url]
    assert frame.loc[0, "application_no"] == "A/K10/281"
    assert frame.loc[0, "raw_snapshot"] == str(tmp_path / "detail.html")
    assert frame.attrs["lineage_metadata"]["fetched_documents"] == 1


def test_fetch_landsd_consent_archives_pdf_and_explicitly_skips_image_only(monkeypatch, tmp_path):
    text_url = "https://www.landsd.gov.hk/doc/en/consent/district/since1994/accessible/Tuen%20Mun[from%201994]wac_e.pdf"
    image_url = "https://www.landsd.gov.hk/doc/en/consent/district/since1994/pdf/Tai%20Po[from%201994].pdf"
    session = _FakeSession({text_url: b"text-native", image_url: b"image-only"})
    monkeypatch.setattr(
        "src.hk_real_estate.sources.land_planning.save_raw_snapshot",
        lambda *args, **kwargs: tmp_path / "consent.pdf",
    )

    def fake_parser(pdf_bytes, *, district, document_url):
        if pdf_bytes == b"image-only":
            return pd.DataFrame()
        return pd.DataFrame(
            [{
                "development_name_raw": "Example Heights",
                "lot_no_raw": "TMTL 422",
                "parent_or_holding_company_or_developer_raw": "Example Holdings / Example Developer",
                "consent_or_approval_date": "2014-02-26",
                "document_url": document_url,
                "page_number": 1,
            }]
        )

    monkeypatch.setattr(
        "src.hk_real_estate.sources.land_planning.parse_landsd_consent_pdf", fake_parser
    )

    frame = fetch_landsd_consent_facts(
        [text_url, image_url], session=session, max_documents=2
    )

    assert len(frame) == 1
    assert frame.loc[0, "district"] == "Tuen Mun"
    assert frame.loc[0, "raw_snapshot"] == str(tmp_path / "consent.pdf")
    assert frame.attrs["skipped_documents"] == [
        {"document_url": image_url, "reason": "image_only_or_unparseable_pdf"}
    ]


def test_fetch_landsd_monthly_consent_filters_target_lots_and_preserves_lineage(monkeypatch, tmp_path):
    url = "https://www.landsd.gov.hk/doc/en/consent/monthly/t1_2606.pdf"
    session = _FakeSession({url: b"monthly-pdf"})
    monkeypatch.setattr(
        "src.hk_real_estate.sources.land_planning.save_raw_snapshot",
        lambda *args, **kwargs: tmp_path / "monthly.pdf",
    )
    monkeypatch.setattr(
        "src.hk_real_estate.sources.land_planning.parse_landsd_monthly_consent_pdf",
        lambda *args, **kwargs: pd.DataFrame([
            {
                "lot_no_raw": "Lot 1071 in DD 103",
                "vendor_raw": "Ease Gold Development Limited",
                "holding_company_raw": "Peak Harbour Development Limited and Sun Hung Kai Properties Limited",
                "monthly_status": "issued",
                "document_as_of_date": "2026-06-30",
                "document_url": url,
                "page_number": 1,
            },
            {
                "lot_no_raw": "OTHER LOT",
                "vendor_raw": "Other Vendor",
                "holding_company_raw": "Other Holding",
                "monthly_status": "issued",
                "document_as_of_date": "2026-06-30",
                "document_url": url,
                "page_number": 1,
            },
        ])
    )

    frame = fetch_landsd_monthly_consent_facts(
        [url], lot_patterns=["1071"], session=session, max_documents=1
    )

    assert session.urls == [url]
    assert len(frame) == 1
    assert frame.loc[0, "vendor_raw"] == "Ease Gold Development Limited"
    assert frame.loc[0, "raw_snapshot"] == str(tmp_path / "monthly.pdf")
    assert frame.attrs["lineage_metadata"]["lineage_type"] == "official_landsd_monthly_consent_fetch"
