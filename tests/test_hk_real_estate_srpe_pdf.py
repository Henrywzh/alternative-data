import pandas as pd
import pytest

from src.hk_real_estate.sources.srpe import (
    SRPEDocumentDownloadError,
    download_srpe_document,
)
from src.hk_real_estate.sources.srpe_pdf import (
    _parse_date,
    build_srpe_sales_signals,
    parse_srpe_price_list_metadata,
    parse_srpe_price_list_tables,
    parse_srpe_transaction_tables,
)
from src.hk_real_estate.mapping.developer_registry import DeveloperRegistry


def _transaction_table():
    return [
        ["(A)", "(B)", "(C)", "(D)", None, None, None, "(E)", "(F)", "(G)", "(H)"],
        [
            "Date of PASP\n(DD-MM-YYYY)",
            "Date of ASP\n(DD-MM-YYYY)",
            "Date of termination of ASP",
            "Description of Residential Property",
            None,
            None,
            None,
            "Transaction\nPrice",
            "Details and date of revision",
            "Terms of Payment",
            "The purchaser is a related party",
        ],
        [None, None, None, "Block Name", "Floor", "Unit", "Car-parking space", None, None, None, None],
        [
            "13/03/2021",
            "19/03/2021",
            "",
            "Tower 1\n第1座",
            "20",
            "A",
            "",
            "$47,090,000",
            "",
            "Payment Plan A",
            "",
        ],
        [
            "13/03/2021",
            "",
            "23/02/2024",
            "Tower 1\n第1座",
            "21",
            "A",
            "P-10",
            "$49,000,000",
            "Price list 2A 01/04/2021",
            "Payment Plan B",
            "Yes",
        ],
    ]


def _price_table():
    return [
        [
            "Description of Residential Property",
            None,
            None,
            "Saleable Area\nsq. metre (sq. ft.)",
            "Price ($)",
            "Unit Rate of Saleable Area",
        ],
        ["Block Name", "Floor", "Unit", None, None, None],
        ["Tower 1", "20", "A", "77.533 (835)\nBalcony: 2.702", "47,090,000", "607,000\n(56,395)"],
        ["Tower 1", "21", "A", "77.533 (835)", "49,000,000", "632,000\n(58,683)"],
    ]


def _price_metadata():
    first_page_tables = [
        [
            ["Name of the Phase", "維港滙 I\nGRAND VICTORIA I", "Phase No.", "第一期\nPhase 1"],
            ["Location of the Phase", "荔盈街6號\n6 Lai Ying Street", None, None],
            ["The total number of residential properties in the Phase", None, None, "524"],
        ],
        [["Date of Printing", "Number of Price List"], ["04/03/2021", "1"]],
    ]
    metadata = parse_srpe_price_list_metadata(first_page_tables)
    return first_page_tables, metadata


def test_parse_date_handles_iso_and_display_formats_without_ambiguity():
    assert _parse_date("2026-08-01") == "2026-08-01"
    assert _parse_date("01/08/2026") == "2026-08-01"


def test_transaction_tables_parse_bilingual_headers_and_cancellation():
    result = parse_srpe_transaction_tables(
        [(2, [_transaction_table()])],
        metadata={
            "development_id": "7405",
            "development_name": "GRAND VICTORIA",
            "phase_name": "Phase 1",
            "development_address": "6 Lai Ying Street",
        },
        document_id="104088",
        document_hash="hash",
    )

    assert len(result) == 2
    assert result.iloc[0]["date_of_pasp"] == "2021-03-13"
    assert result.iloc[0]["transaction_price_hkd"] == 47090000
    assert result.iloc[1]["date_of_asp_termination"] == "2024-02-23"
    assert result.iloc[1]["is_cancelled"] == True
    assert result.iloc[1]["related_party_flag"] == "Yes"


def test_transaction_tables_carry_schema_to_headerless_following_pages():
    header = _transaction_table()[:3]
    data_page = [_transaction_table()[3]]
    result = parse_srpe_transaction_tables(
        [(2, [header]), (3, [data_page])],
        metadata={"development_id": "7705", "development_name": "THE PAVILIA FARM"},
        document_id="pavilia-register",
        document_hash="hash",
    )
    assert len(result) == 1
    assert result.iloc[0]["source_page"] == 3
    assert result.iloc[0]["unit"] == "A"


def test_transaction_tables_skip_unrelated_headerless_tables_after_schema():
    unrelated = [
        [
            "01/04/2024",
            "",
            "",
            "Annual project summary",
            "",
            "",
            "",
            "$123,000,000",
            "",
            "",
            "",
        ],
    ]
    result = parse_srpe_transaction_tables(
        [
            (2, [_transaction_table()[:3]]),
            (3, [[_transaction_table()[3]]]),
            (4, [unrelated]),
        ],
        metadata={"development_id": "7705", "development_name": "THE PAVILIA FARM"},
        document_id="pavilia-register",
        document_hash="hash",
    )
    assert len(result) == 1
    assert result.iloc[0]["block_name"] == "Tower 1\n第1座"


def test_transaction_tables_accept_statutory_no_asp_marker():
    no_asp = list(_transaction_table()[3])
    no_asp[1] = (
        "簽訂臨時買賣合約後交易再未有進展\n"
        "The PASP has not proceeded further"
    )
    result = parse_srpe_transaction_tables(
        [(2, [[*_transaction_table()[:3], no_asp]])],
        metadata={"development_id": "7705", "development_name": "THE PAVILIA FARM"},
        document_id="pavilia-register",
        document_hash="hash",
    )
    assert len(result) == 1
    assert result.iloc[0]["date_of_asp"] is None


def test_transaction_tables_preserve_distinct_price_revisions():
    first = _transaction_table()[3]
    revised = list(first)
    revised[7] = "$48,090,000"
    revised[8] = "Price revised on 01/04/2021"
    result = parse_srpe_transaction_tables(
        [(2, [[*_transaction_table()[:3], first, revised]])],
        metadata={"development_id": "7405", "development_name": "GRAND VICTORIA"},
        document_id="revision-register",
        document_hash="hash",
    )
    assert result["transaction_price_hkd"].tolist() == [47090000, 48090000]
    assert result["transaction_id"].nunique() == 2
    assert result.iloc[1]["price_revision_details"] == "Price revised on 01/04/2021"


def test_transaction_tables_align_compact_old_tender_rows():
    compact = [
        ["13-10-2016", "16-10-2016", "", "17G Shouson Hill Road", "", "$228,420,000", "", "Payment Plan A", ""],
    ]
    result = parse_srpe_transaction_tables(
        [(3, [_transaction_table()[:3]]), (4, [compact])],
        metadata={"development_id": "285", "development_name": "SHOUSON PEAK"},
        document_id="compact-old-register",
        document_hash="hash",
    )
    row = result.loc[result["date_of_pasp"].eq("2016-10-13")].iloc[0]
    assert row["transaction_price_hkd"] == 228420000
    assert row["unit"] == ""
    assert row["payment_terms"] == "Payment Plan A"


def test_transaction_tables_do_not_treat_numeric_floor_as_shifted_price():
    ordinary_short_row = [
        [
            "13-10-2016",
            "16-10-2016",
            "",
            "Tower 1",
            "10",
            "A",
            "",
            "$22,842,000",
            "",
        ],
    ]
    result = parse_srpe_transaction_tables(
        [(3, [_transaction_table()[:3]]), (4, [ordinary_short_row])],
        metadata={"development_id": "test", "development_name": "TEST"},
        document_id="ordinary-short-register",
        document_hash="hash",
    )
    row = result.iloc[0]
    assert row["floor"] == "10"
    assert row["unit"] == "A"
    assert row["transaction_price_hkd"] == 22842000


def test_price_list_tables_parse_inventory_and_version_identity():
    first_page_tables, metadata = _price_metadata()
    assert metadata["development_name"] == "GRAND VICTORIA I"
    assert metadata["phase_name"] == "Phase 1"
    assert metadata["total_residential_properties"] == 524
    assert metadata["date_of_printing"] == "2021-03-04"

    result = parse_srpe_price_list_tables(
        [(1, first_page_tables), (2, [_price_table()])],
        metadata={"development_id": "7405", **metadata},
        document_id="21990",
        document_hash="price-hash",
    )
    assert len(result) == 2
    assert result.iloc[0]["price_hkd"] == 47090000
    assert result.iloc[0]["saleable_area_sqft"] == 835
    assert result.iloc[0]["unit_rate_hkd_per_sqft"] == 56395
    assert result.iloc[0]["total_residential_properties"] == 524
    assert result.iloc[0]["price_list_version_key"] == result.iloc[1]["price_list_version_key"]


def test_price_list_tables_accept_tower_number_and_flat_labels():
    first_page_tables, metadata = _price_metadata()
    tower_table = _price_table()
    tower_table[1][0] = "Tower Number"
    tower_table[1][2] = "Flat"
    result = parse_srpe_price_list_tables(
        [(2, [tower_table])],
        metadata={"development_id": "7705", **metadata},
        document_id="22731",
        document_hash="pavilia-price-hash",
    )
    assert len(result) == 2


def test_sales_signals_join_inventory_by_development_id_even_when_names_differ():
    transactions = pd.DataFrame(
        [
            {
                "development_id": "7405",
                "development_name": "GRAND VICTORIA",
                "phase_name": "Phase 1",
                "date_of_pasp": "2021-03-13",
                "date_of_asp_termination": None,
                "transaction_price_hkd": 47090000,
                "transaction_id": "a",
            },
            {
                "development_id": "7405",
                "development_name": "GRAND VICTORIA",
                "phase_name": "Phase 1",
                "date_of_pasp": "2021-04-13",
                "date_of_asp_termination": "2021-05-01",
                "transaction_price_hkd": 49000000,
                "transaction_id": "b",
            },
        ]
    )
    price_lists = pd.DataFrame(
        [{
            "development_id": "7405",
            "development_name": "GRAND VICTORIA I",
            "phase_name": "Phase 1",
            "total_residential_properties": 524,
        }]
    )

    signals = build_srpe_sales_signals(transactions, price_lists)
    april = signals.loc[signals["period"].eq("2021-04-01")].iloc[0]
    may = signals.loc[signals["period"].eq("2021-05-01")].iloc[0]
    assert april["total_residential_properties"] == 524
    assert april["cumulative_net_sell_through_pct"] == pytest.approx(1 / 524 * 100)
    assert may["cancelled_units"] == 1
    assert may["cumulative_net_units"] == 1


class _Response:
    def __init__(self, status_code, content=b"%PDF-1.4 test"):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Session:
    def __init__(self, responses):
        self.headers = {}
        self.responses = iter(responses)

    def post(self, *args, **kwargs):
        return next(self.responses)


def test_srpe_downloader_retries_transient_404_and_validates_pdf():
    content = download_srpe_document(
        "register_of_transactions",
        "103954",
        "9146",
        session=_Session([_Response(404, b""), _Response(200)]),
    )
    assert content.startswith(b"%PDF")


def test_srpe_downloader_does_not_accept_html_as_pdf():
    with pytest.raises(SRPEDocumentDownloadError, match="non-PDF"):
        download_srpe_document(
            "price_list",
            "1",
            "7405",
            session=_Session([_Response(200, b"<html>not a pdf</html>")]),
        )


def test_srpe_project_registry_maps_park_yoho_alias_to_shkp():
    match, tier = DeveloperRegistry().match_project("PARK VISTA DEVELOPMENT")
    assert tier == "ALIAS"
    assert match["stock_code"] == "0016"
