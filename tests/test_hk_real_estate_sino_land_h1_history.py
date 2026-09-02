import pytest

from src.hk_real_estate import sino_land_h1_history as history


class _FakePage:
    def __init__(self, text: str):
        self._text = text

    def extract_text(self):
        return self._text


class _FakeReader:
    pages = []

    def __init__(self, _stream):
        self.pages = [_FakePage(text) for text in self.__class__.pages]


def _item() -> dict[str, str]:
    return {
        "report_id": "sino_ir_test_2025_26",
        "fiscal_label": "FY2025/26",
        "period_end": "2025-12-31",
        "fiscal_year_end": "2026-06-30",
        "release_date": "2026-03-17",
        "source_url": "https://example.test/sino-interim.pdf",
    }


def test_parser_uses_current_period_and_keeps_group_segment_scopes(monkeypatch):
    statement = """
    For the six months ended 31st December, 2025
    Consolidated statement of profit or loss
    HK$ Million
    Revenue 3, 4 5,185 3,854
    Profit for the period attributable to:
    The Company’s shareholders 1,533 1,820
    """
    revenue_note = """
    For the six months ended 31st December, 2025
    3. Revenue
    Sales of properties 2,543 1,212
    Rental income from operating leases 1,337 1,378
    Hotel operations 515 495
    """
    segments = """
    For the six months ended 31st December, 2025
    4. Segment information
    Segment revenue Segment results
    Property sales 2,543 721 4,369 (226) 6,912 495
    Property rental 1,337 1,059 381 305 1,718 1,364
    Property management and other services 730 132 62 9 792 141
    Hotel operations 515 207 307 82 822 289
    Investments in securities 26 26 – – 26 26
    Financing 34 34 4 4 38 38
    """
    narrative = "The underlying profit attributable to shareholders was HK$2,220 million."
    _FakeReader.pages = [statement, revenue_note, segments, narrative]
    monkeypatch.setattr(history, "PdfReader", _FakeReader)

    facts, audit = history.parse_sino_land_interim_report(b"%PDF-test", _item())

    assert audit["parse_status"] == "pass"
    assert audit["missing_metrics"] == "[]"
    assert len(facts) == 18
    assert facts["fact_id"].is_unique

    revenue = facts.loc[facts["metric"].eq("consolidated_revenue")].iloc[0]
    assert revenue["value"] == 5185.0
    assert revenue["attribution_scope"] == "consolidated_group"

    profit = facts.loc[facts["metric"].eq("profit_attributable")].iloc[0]
    assert profit["value"] == 1533.0

    segment = facts.loc[
        facts["segment"].eq("property_sales")
        & facts["metric"].eq("segment_revenue")
    ].iloc[0]
    assert segment["value"] == 6912.0
    assert "associates/JVs" in segment["caveat"]


def test_parser_scales_legacy_raw_hkd_to_hkd_m(monkeypatch):
    pages = [
        """
        For the six months ended 31st December, 2020
        Revenue 3, 4 4,097,517,736 3,168,550,076
        Profit for the period attributable to:
        The Company ’s shareholders 1,286,638,929 2,780,790,532
        """,
        """
        For the six months ended 31st December, 2020
        3. Revenue
        Sales of properties 1,949,855,362 412,238,609
        Rental income from operating leases 1,416,839,350 1,646,263,431
        Hotel operations 128,844,437 484,398,475
        """,
        """
        For the six months ended 31st December, 2020
        4. Segment information
        Segment revenue Segment results
        Property sales 1,949,855,362 781,561,052 61,996,405 26,312,573 2,011,851,767 807,873,625
        Property rental 1,416,839,350 1,244,022,804 436,947,039 394,948,371 1,853,786,389 1,638,971,175
        Property management and other services 565,387,525 229,914,328 56,758,764 8,697,434 622,146,289 238,611,762
        Hotel operations 128,844,437 (20,454,154) 34,697,242 (32,488,876) 163,541,679 (52,943,030)
        Investments in securities 2,169,998 2,169,998 1,950 1,950 2,171,948 2,171,948
        Financing 34,421,064 34,421,064 5,332,125 5,332,125 39,753,189 39,753,189
        """,
        "underlying profit attributable to shareholders was HK$2,142.5 million.",
    ]
    _FakeReader.pages = pages
    monkeypatch.setattr(history, "PdfReader", _FakeReader)

    item = dict(history.INTERIM_REPORT_REGISTRY[0])
    facts, audit = history.parse_sino_land_interim_report(b"%PDF-test", item)

    assert audit["parse_status"] == "pass"
    assert audit["unit_scale"] == 1e-6
    consolidated = facts.loc[facts["metric"].eq("consolidated_revenue")].iloc[0]
    assert consolidated["value"] == 4097.517736
    segment = facts.loc[
        facts["segment"].eq("property_rental")
        & facts["metric"].eq("segment_revenue")
    ].iloc[0]
    assert segment["value"] == pytest.approx(1853.786389)
