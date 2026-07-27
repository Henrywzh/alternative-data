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
from src.hk_real_estate.sources.landreg import fetch_landreg_monthly_sp, _clean_t6_region
from src.hk_real_estate.storage import save_normalized_dataset, save_raw_snapshot
from src.hk_real_estate.mapping.developer_registry import DeveloperRegistry
from src.hk_real_estate.sources.hkma import fetch_hkma_residential_mortgage_survey
from src.hk_real_estate.sources.bd_projects import parse_bd_xls_projects, fetch_bd_supply_leading_indicators
from src.hk_real_estate.sources.buildings_dept import _period_from_row, fetch_buildings_dept_monthly_stats
from src.hk_real_estate.mapping.developer_registry import GENERIC_FUZZY_EXCLUDED_ALIASES
from src.hk_real_estate.dedup.transaction_dedup import deduplicate_agency_transactions, generate_dedup_hash
from src.hk_real_estate.sources.srpe import fetch_srpe_firsthand_sales_digest
from src.hk_real_estate.sources.midland_transactions import _parse_building_payload


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


def test_midland_parse_uses_net_area_not_area():
    """Regression test for the LOHAS Park (日出康城) area bug.

    Confirmed live (data/raw/hk_real_estate/midland_transaction_buildings/
    2026-07-27/20260727T182255_652302Z_e64f4b4e119f_d858d13b.json): for
    estate 日出康城, Midland's API returns "area": "0" for every single
    transaction (83.6% of a live pilot run's rows), with the real saleable
    area only present under "net_area". Even where "area" is non-zero (e.g.
    宏福苑), Midland's own displayed net_ft_price is computed against
    net_area, not area -- so using "area" produces a systematic ~17% unit
    price mismatch. The parser must read net_area (falling back to area only
    when net_area is itself missing/zero).
    """
    payload = {
        "building": {"id": "B000005180", "name": "1座"},
        "data": [
            {
                "floor": "88",
                "flat_name": "1",
                "transactions": [
                    # Real shape for a 日出康城 duplex: area is always "0",
                    # only net_area carries the real saleable area.
                    {
                        "id": "TX-LOHAS-1",
                        "tx_date": "2026-01-15T16:00:00.000Z",
                        "area": "0",
                        "net_area": "3483",
                        "price": "93000000",
                        "net_ft_price": 26701,
                        "url_desc": "https://example.com/tx-lohas-1",
                    },
                    # Real shape for 宏福苑: area is non-zero but WRONG --
                    # net_ft_price is computed off net_area (467), not area (564).
                    {
                        "id": "TX-WFC-1",
                        "tx_date": "2021-07-26T16:00:00.000Z",
                        "area": "564",
                        "net_area": "467",
                        "price": "5100000",
                        "net_ft_price": 10921,
                        "url_desc": "https://example.com/tx-wfc-1",
                    },
                    # Edge case: net_area missing/zero, area populated --
                    # must fall back to area rather than producing no area at all.
                    {
                        "id": "TX-FALLBACK-1",
                        "tx_date": "2025-01-01T16:00:00.000Z",
                        "area": "500",
                        "net_area": "0",
                        "price": "4000000",
                        "net_ft_price": 8000,
                        "url_desc": "https://example.com/tx-fallback-1",
                    },
                ],
            }
        ],
    }

    df = _parse_building_payload(payload, estate_name="日出康城")
    by_id = df.set_index("source_record_id")

    # LOHAS Park: area="0" must not win -- net_area (3483) must be used.
    assert by_id.loc["TX-LOHAS-1", "saleable_area_sqft"] == 3483

    # 宏福苑: area (564) must not be used -- net_area (467) must be used,
    # and the resulting price/area must now be consistent with the stored
    # unit_price_hkd_sqft (net_ft_price), not off by the ~17% area/net_area gap.
    wfc = by_id.loc["TX-WFC-1"]
    assert wfc["saleable_area_sqft"] == 467
    computed_psf = wfc["price_hkd"] / wfc["saleable_area_sqft"]
    assert abs(computed_psf - wfc["unit_price_hkd_sqft"]) / wfc["unit_price_hkd_sqft"] < 0.01
    # Sanity: confirm the old (buggy) area-based computation would have been
    # off by roughly the documented ~17% systematic gap.
    wrong_psf = wfc["price_hkd"] / 564
    assert abs(wrong_psf - wfc["unit_price_hkd_sqft"]) / wfc["unit_price_hkd_sqft"] > 0.10

    # net_area missing/zero: falls back to area rather than dropping it.
    assert by_id.loc["TX-FALLBACK-1", "saleable_area_sqft"] == 500


def test_transaction_dedup_hse28_floor_level_fallback_uses_room_type():
    """Regression test: row.get('floor_level', row.get('room_type', '')) never
    fires its fallback once `combined` is a pd.concat() of frames with
    different native columns, because after concat every column exists on
    every row (NaN-filled where a source doesn't populate it) -- so the key
    is always "present" and pandas.Series.get never falls through to the
    default. hse28.py never populates floor_level/unit_flat (only
    room_type), so every 28Hse row silently hashed with floor="" instead of
    its actual room_type value.
    """
    hse_a = pd.DataFrame([{
        "estate_name": "Kai Ching Estate",
        "room_type": "3房",
        "transaction_date": "2026-07-20",
        "price_hkd": 8000000.0,
        "saleable_area_sqft": 600,
        "source_platform": "28Hse",
        "source_record_id": "hse-201",
    }])
    hse_b = pd.DataFrame([{
        "estate_name": "Kai Ching Estate",
        "room_type": "2房",
        "transaction_date": "2026-07-20",
        "price_hkd": 8000000.0,
        "saleable_area_sqft": 600,
        "source_platform": "28Hse",
        "source_record_id": "hse-202",
    }])
    # A Midland-shaped frame with floor_level populated -- concatenating this
    # in is what introduces a floor_level column (NaN-filled for the 28Hse
    # rows above), reproducing the exact defect condition from the bug report.
    midland = pd.DataFrame([{
        "estate_name": "Other Estate",
        "floor_level": "10",
        "unit_flat": "A",
        "transaction_date": "2026-07-21",
        "price_hkd": 5000000.0,
        "saleable_area_sqft": 500,
        "source_platform": "Midland Realty",
        "source_record_id": "midland-1",
    }])

    deduped = deduplicate_agency_transactions([hse_a, hse_b, midland])

    # Two structurally distinct 28Hse transactions (different room_type)
    # sharing estate/date/price must NOT collapse into one false-positive
    # merged record.
    assert len(deduped) == 3

    hse_a_row = deduped[deduped["source_record_ids"] == "hse-201"].iloc[0]
    expected_hash = generate_dedup_hash(
        estate_name="Kai Ching Estate",
        floor="3房",
        unit="",
        transaction_date="2026-07-20",
        price_hkd=8000000.0,
    )
    # The dedup id actually used must match what you'd get by resolving the
    # fallback to room_type's real value ("3房") -- not the hash you'd get
    # from an empty-string floor (which is what the unfixed .get() produced).
    assert hse_a_row["dedup_transaction_id"] == expected_hash
    wrong_hash_if_blank_floor = generate_dedup_hash(
        estate_name="Kai Ching Estate",
        floor="",
        unit="",
        transaction_date="2026-07-20",
        price_hkd=8000000.0,
    )
    assert hse_a_row["dedup_transaction_id"] != wrong_hash_if_blank_floor


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
                    "ir_new_loans_approved_other": 0.043,
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
    assert df.iloc[0]["other_pricing_pct_share"] == 4.3
    assert df.iloc[0]["delinquency_ratio_pct"] == 0.11
    assert df.iloc[0]["publication_date"] is None

    # The four rate-pricing shares should reconstruct to ~100% of new
    # mortgage approvals (confirmed live via HKMA's API: without the
    # "other" field the three original shares only summed to 92.8%-98.8%).
    total_share = (
        df.iloc[0]["hibor_pricing_pct_share"]
        + df.iloc[0]["blr_pricing_pct_share"]
        + df.iloc[0]["fixed_pricing_pct_share"]
        + df.iloc[0]["other_pricing_pct_share"]
    )
    assert total_share == pytest.approx(100.0, abs=0.5)


def test_landreg_t6_region_strips_number_of_prefix_and_transactions_suffix():
    """Regression test: the raw t6.json ``Description`` field looks like
    "Number of Hong Kong transactions", "Number of Kowloon transactions", etc.
    (confirmed live via
    https://www.landreg.gov.hk/json/monthly_stat/monthly/t6.json). The old
    code only stripped the trailing " transactions" suffix, leaving values
    like "Number of Hong Kong" instead of the clean district name "Hong Kong".
    """
    assert _clean_t6_region("Number of Hong Kong transactions") == "Hong Kong"
    assert _clean_t6_region("Number of Kowloon transactions") == "Kowloon"
    assert _clean_t6_region("Number of Island transactions") == "Island"
    assert _clean_t6_region("Number of North transactions") == "North"
    assert _clean_t6_region("Number of Sai Kung transactions") == "Sai Kung"
    assert _clean_t6_region("Number of Tsuen Wan transactions") == "Tsuen Wan"
    assert _clean_t6_region("Number of Yuen Long transactions") == "Yuen Long"

    # No "Number of "/"transactions" tokens leak into any cleaned value.
    for raw in (
        "Number of Hong Kong transactions",
        "Number of Kowloon transactions",
        "Number of Island transactions",
    ):
        cleaned = _clean_t6_region(raw)
        assert "Number of" not in cleaned
        assert "transactions" not in cleaned


def test_landreg_t6_grand_total_row_does_not_produce_fake_district():
    """The grand-total row's raw description is "Total Number of
    transactions" -- naively applying the same strip rules produces the
    nonsensical pseudo-region "Total Number of", which looks like it could be
    a real district in downstream filtering. It must instead map to a
    distinct, unambiguous sentinel.
    """
    total_region = _clean_t6_region("Total Number of transactions")
    assert total_region != "Total Number of"
    assert "Number of" not in total_region
    # Must not collide with any real district value.
    real_districts = {
        _clean_t6_region(f"Number of {district} transactions")
        for district in ("Hong Kong", "Kowloon", "Island", "North", "Sai Kung",
                          "Shatin", "Tai Po", "Tsuen Wan", "Tuen Mun", "Yuen Long")
    }
    assert total_region not in real_districts


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
    assert "/test_dataset/run-123/" in result["parquet"]
    lineage = json.loads(Path(result["lineage"]).read_text())
    assert lineage["raw_snapshot"] == "/tmp/raw.csv"


def _rows_to_xls_bytes(rows: list[list], header: bool = False) -> bytes:
    """Round-trip a list-of-lists through an in-memory Excel file, mimicking
    the shape `pd.read_excel` hands back for a real BD monthly-digest sheet.
    """
    import io as _io
    buf = _io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False, header=header)
    buf.seek(0)
    return buf.read()


def test_bd_projects_merges_multi_tier_project_continuation_rows():
    """Regression test for Bug 1: BD repeats the "No. of Blocks" value on
    every unit-size-tier continuation row of a multi-tier project, and a
    project's own address can wrap onto a line that coincidentally reads
    exactly "New Territories" (matching the region-header branch). Confirmed
    live on Md56.xls rows ~65-70: ONE project "8 Hoi Ying Road, Tai Po, New
    Territories" (domestic UFA 19,525.8 sqm) broken into 5 unit-size tiers
    (86@17.2, 91@23.1, 365@25.2, 172@35.8, 13@45.3 -- summing
    tier_units * tier_size across all 5 reproduces 19,525.8 exactly). The
    old blocks-column-only anchor split this into 3 fake orphan projects and
    silently dropped 2 of the 5 tiers (378 units of real data lost).
    """
    header_row = [None] * 14
    filler_rows = [[None] * 14 for _ in range(7)]
    project_rows = [
        # Header row: address + permit + blocks + storeys + building type + tier 1 (86 units @ 17.2 sqm).
        ["8 Hoi Ying Road,", "NT32/2026/OP", 1, 16, "Apartment (phase 2A)", 86, 17.2, 37967.1, "-", 19525.8, "-", "AP", "RSE", "Applicant"],
        # Continuation: address wraps to "Tai Po,"; tier 2 (91 units @ 23.1 sqm). Blocks value repeated.
        ["Tai Po,", None, 1, 21, None, 91, 23.1, None, None, None, None, None, None, None],
        # Continuation: address wraps to exactly "New Territories" -- must NOT be treated as a region-header
        # switch while a project is in progress, and must NOT lose tier 3 (365 units @ 25.2 sqm).
        ["New Territories", None, 1, 23, None, 365, 25.2, None, None, None, None, None, None, None],
        # Continuation: site area line; tier 4 (172 units @ 35.8 sqm). Blocks value still repeated.
        ["Site Area: 157,343.4", None, 1, 26, None, 172, 35.8, None, None, None, None, None, None, None],
        # Continuation: class-of-site line; tier 5 (13 units @ 45.3 sqm). No blocks value this row.
        ["Class of Site: A", None, None, "all over 1", None, 13, 45.3, None, None, None, None, None, None, None],
        # Continuation: bare planning-reference line, no tier data.
        ["7.4.1/(6)", None, None, "lower ground level", None, None, None, None, None, None, None, None, None, None],
    ]
    rows = [header_row] + filler_rows + project_rows
    content = _rows_to_xls_bytes(rows)

    df = parse_bd_xls_projects(content, "Occupation Permits (OP) Issued")

    assert len(df) == 1, f"expected the 5 tiers to merge into exactly one project, got {len(df)}: {df['site_address'].tolist() if not df.empty else []}"
    row = df.iloc[0]
    assert "8 Hoi Ying Road" in row["site_address"]
    assert "Tai Po" in row["site_address"]
    assert "New Territories" in row["site_address"]
    # The bare planning-reference continuation line must not pollute the address.
    assert "7.4.1/(6)" not in row["site_address"]
    assert row["domestic_units_count"] == 86 + 91 + 365 + 172 + 13
    # GFA/UFA are the project's published total (from the header row), not re-summed across tiers.
    assert row["usable_floor_area_sqm"] == 19525.8
    assert row["site_area_sqm"] == 157343.4


def test_bd_projects_multi_house_project_does_not_split_into_blank_address_rows():
    """Regression test for Bug 1's second confirmed case: Md54.xls rows
    ~16-38, "30-38 Magazine Gap Road" with 4 sub-houses (3A/3B/4A/4B), each
    of which restarts the "No. of Blocks" column on its own row despite
    having a blank address. The old anchor split this into 4 blank-address
    rows, 3 of which then silently collapsed via drop_duplicates(subset=
    ['site_address', 'permit_stage']) since they shared an identical blank
    address -- losing 3 of 4 houses outright rather than merging them.
    """
    header_row = [None] * 14
    filler_rows = [[None] * 14 for _ in range(7)]
    project_rows = [
        ["30-38 Magazine Gap Road,", 2, 2, "Apartment with residents'", 1, 27, 4531, "-", 2916, "-", "AP", "RSE", "Applicant", None],
        # Building-type text itself wraps onto this continuation line -- no blocks value here.
        ["Hong Kong", None, "all over 1", None, 1, 47.7, None, None, None, None, None, None, None, None],
        ["1.8.4/(3)", None, "lower ground level", None, 1, 140, None, None, None, None, None, None, None, None],
        # House 3A: blocks value repeated, address blank.
        [None, 1, 3, None, 1, 261.2, None, None, None, None, None, None, None, None],
        [None, None, "(House 3A)", None, None, None, None, None, None, None, None, None, None, None],
        # House 4A: blocks value repeated again, address still blank.
        [None, 1, 3, None, None, None, None, None, None, None, None, None, None, None],
        [None, None, "(House 4A)", None, None, None, None, None, None, None, None, None, None, None],
    ]
    rows = [header_row] + filler_rows + project_rows
    content = _rows_to_xls_bytes(rows)

    df = parse_bd_xls_projects(content, "Consent to Commence")

    assert len(df) == 1, f"expected the multi-house project to stay merged into one row, got {len(df)}: {df['site_address'].tolist() if not df.empty else []}"
    assert "30-38 Magazine Gap Road" in df.iloc[0]["site_address"]
    assert df.iloc[0]["site_address"].strip() != ""


def test_buildings_dept_annual_row_and_monthly_row_have_matching_shape_and_distinct_dates():
    """Regression test for Bug 2: the annual-summary row's own year cell
    (e.g. a bare "2024") was included in the generic numeric-value scan,
    giving it one more element than an ordinary monthly row in the same
    table (confirmed on tables 1.1, 1.3, 1.4, 1.7 of the live Md11-Md17
    files) -- and it resolved to the same "YYYY-01-01" date as that year's
    real January row, producing duplicate dates within one table.
    """
    header_row = ["Year/month", None, None, "Domestic", None, "Non-domestic", None, "Composite", None, "Total", None, "domestic units"]
    annual_row = [2024, None, None, 54, None, 120, None, 42, None, 216, None, 34040]
    monthly_row = [None, "Jun", None, 4, None, 7, None, 8, None, 19, None, 3517]
    xls_bytes = _rows_to_xls_bytes([header_row, annual_row, monthly_row], header=False)

    index_html = '<html><a href="/doc/en/whats-new/monthly-digests/Md11.xls">Table 1.1</a></html>'

    def fake_get(url, headers=None, timeout=None):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        if url.endswith("index.html"):
            resp.text = index_html
        else:
            resp.content = xls_bytes
        return resp

    with patch("src.hk_real_estate.sources.buildings_dept.requests.get", side_effect=fake_get):
        df = fetch_buildings_dept_monthly_stats()

    assert not df.empty
    annual = df[df["date"] == "2024-12-31"]
    monthly = df[df["date"] == "2024-06-01"]
    assert len(annual) == 1, "annual-total row should be stamped on a sentinel date distinct from any real month"
    assert len(monthly) == 1
    assert annual.iloc[0]["period_type"] == "annual"
    assert monthly.iloc[0]["period_type"] == "monthly"

    annual_values = json.loads(annual.iloc[0]["numeric_values"])
    monthly_values = json.loads(monthly.iloc[0]["numeric_values"])
    assert annual_values == [54.0, 120.0, 42.0, 216.0, 34040.0]
    assert monthly_values == [4.0, 7.0, 8.0, 19.0, 3517.0]
    assert len(annual_values) == len(monthly_values), (
        "annual and monthly rows in the same table must have the same numeric_values shape"
    )
    # No duplicate dates within the table -- the old "-01-01" stamping collided here.
    assert df["date"].duplicated().sum() == 0


def test_period_from_row_classifies_annual_vs_monthly():
    year, period, _, is_annual = _period_from_row(["2025", "", ""], None, None)
    assert is_annual is True
    assert period == "2025-12-31"

    year, period, _, is_annual = _period_from_row(["2025: ", "Jan", ""], year, period)
    assert is_annual is False
    assert period == "2025-01-01"


def test_generic_street_district_aliases_do_not_produce_false_fuzzy_matches():
    """Regression test for Bug 3: several registry aliases are bare
    street/district names ("Murray Road", "Canton Road", "Salisbury Road",
    "Queensway", "Quarry Bay") rather than specific development names.
    FUZZY's plain substring-containment check used to match any address on
    these streets to the wrong developer. Confirmed false positives via 5
    plausible unrelated addresses.
    """
    registry = DeveloperRegistry()
    unrelated_addresses = [
        "15 Murray Road, Central, Hong Kong",
        "88 Canton Road, Tsim Sha Tsui, Kowloon",
        "10 Salisbury Road, Tsim Sha Tsui",
        "1 Queensway, Admiralty",
        "100 Quarry Bay, Hong Kong",
    ]
    for address in unrelated_addresses:
        match, tier = registry.match_project(address)
        assert tier == "UNMATCHED", f"{address!r} should not confidently match via a bare street/district alias, got {tier}"
        assert match is None


def test_generic_fuzzy_excluded_aliases_stay_in_sync_with_registry_csv():
    """GENERIC_FUZZY_EXCLUDED_ALIASES is a hand-maintained allowlist (like
    test_cn_airline_scraper.py's KNOWN_UNRECOVERABLE_MONTHS) -- every entry
    must still exist as a real alias in the registry CSV, or it's stale.
    """
    registry = DeveloperRegistry()
    all_aliases = set()
    for _, reg_row in registry.df.iterrows():
        for alias in str(reg_row.get("project_aliases", "")).split("|"):
            if alias:
                all_aliases.add(alias.strip().lower())
    stale = GENERIC_FUZZY_EXCLUDED_ALIASES - all_aliases
    assert not stale, f"GENERIC_FUZZY_EXCLUDED_ALIASES lists aliases no longer present in the registry CSV: {stale}"


def test_specific_numbered_street_alias_still_fuzzy_matches():
    """A generic street name alone is excluded from FUZZY (Bug 3), but a
    more specific alias that includes a building number (e.g. "2 Murray
    Road", distinct from the bare "Murray Road" alias) should still be
    eligible for a FUZZY substring match -- the fix must not be so broad
    that it disables fuzzy matching on that developer's other aliases.
    """
    registry = DeveloperRegistry()
    match, tier = registry.match_project("2 Murray Road, Central, Hong Kong office tower")
    assert tier == "FUZZY"
    assert match["stock_code"] == "0012"
