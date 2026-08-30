import importlib
import json
import sys
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.hk_real_estate import pipeline as re_pipeline
from src.hk_real_estate.sources.midland import (
    build_midland_field_dictionary,
    parse_midland_mhpi,
    parse_midland_confidence,
    parse_midland_estate_counts,
    parse_midland_mhpi_monthly,
    parse_midland_economic_indicators,
    parse_midland_market_snapshots,
    parse_midland_transaction_summary_snapshot,
    parse_midland_property_event_hints,
)
from src.hk_real_estate.sources.centaline import (
    fetch_centaline_ccl,
    parse_centaline_ccl_payload,
    parse_centaline_index_history,
    parse_centaline_index_snapshots,
)
from src.hk_real_estate.sources.hse28 import fetch_28hse_new_projects
from src.hk_real_estate.sources.rvd import _parse_rvd_monthly_csv, _parse_rvd_commercial_csv
from src.hk_real_estate.sources.landreg import fetch_landreg_monthly_sp, fetch_landreg_monthly_statistics, _clean_t6_region
from src.hk_real_estate.storage import save_normalized_dataset, save_raw_snapshot
from src.hk_real_estate.mapping.developer_registry import DeveloperRegistry
from src.hk_real_estate.sources.hkma import fetch_hkma_residential_mortgage_survey
from src.hk_real_estate.sources.bd_projects import (
    parse_bd_xls_projects,
    fetch_bd_project_lifecycle_events,
    fetch_bd_supply_leading_indicators,
    _infer_region_from_address,
)
from src.hk_real_estate.sources.buildings_dept import _period_from_row, fetch_buildings_dept_monthly_stats


def test_bd_current_year_refresh_merges_new_digest_without_losing_history(monkeypatch):
    existing = pd.DataFrame(
        [
            {
                "observation_month": "2025-12-01",
                "permit_stage": "Occupation",
                "region": "All Hong Kong",
                "property_category": "All",
                "revision_status": "as_published",
                "total_domestic_units": 100,
            },
            {
                "observation_month": "2026-05-01",
                "permit_stage": "Occupation",
                "region": "All Hong Kong",
                "property_category": "All",
                "revision_status": "as_published",
                "total_domestic_units": 200,
            },
        ]
    )
    fresh = pd.DataFrame(
        [
            {
                "observation_month": "2026-05-01",
                "permit_stage": "Occupation",
                "region": "All Hong Kong",
                "property_category": "All",
                "revision_status": "as_published",
                "total_domestic_units": 210,
            },
            {
                "observation_month": "2026-06-01",
                "permit_stage": "Occupation",
                "region": "All Hong Kong",
                "property_category": "All",
                "revision_status": "as_published",
                "total_domestic_units": 220,
            },
        ]
    )
    fresh.attrs["source_url"] = "https://example.test/Md202606e.pdf"
    captured: dict[str, pd.DataFrame] = {}

    monkeypatch.setattr(
        re_pipeline,
        "fetch_bd_supply_pipeline_history",
        lambda **kwargs: fresh,
    )
    monkeypatch.setattr(
        re_pipeline,
        "load_latest_normalized",
        lambda dataset_name: existing,
    )
    monkeypatch.setattr(
        re_pipeline,
        "_record_many",
        lambda run_id, results, datasets: (
            captured.update(datasets),
            results.update(
                {
                    name: {"status": "success", "records": len(frame)}
                    for name, frame in datasets.items()
                }
            ),
        ),
    )

    result = re_pipeline.run_bd_history_current_year_refresh(
        year=2026,
        _raise_on_failure=True,
    )

    merged = captured["bd_supply_pipeline_history"]
    assert result["bd_supply_pipeline_history"]["status"] == "success"
    assert set(merged["observation_month"]) == {
        "2025-12-01",
        "2026-05-01",
        "2026-06-01",
    }
    assert (
        merged.loc[merged["observation_month"].eq("2026-05-01"), "total_domestic_units"].iloc[0]
        == 210
    )
from src.hk_real_estate.sources.bd_history import (
    discover_bd_digest_archives,
    list_archive_pdf_members,
    parse_bd_history_text,
)
from src.hk_real_estate.mapping.developer_registry import GENERIC_FUZZY_EXCLUDED_ALIASES
from src.hk_real_estate.sources.policy_events import validate_developer_project_registry, build_primary_policy_sources_catalog
from src.hk_real_estate.dedup.transaction_dedup import deduplicate_agency_transactions, generate_dedup_hash
from src.hk_real_estate.sources.srpe import fetch_srpe_firsthand_sales_digest
from src.hk_real_estate.sources.midland_transactions import _parse_building_payload
from src.hk_real_estate.pipeline import _quality_errors
import src.hk_real_estate.pipeline as pipeline_module


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
        "src.hk_real_estate.sources.bd_history",
        "src.hk_real_estate.mapping.developer_registry",
        "src.hk_real_estate.dedup.transaction_dedup",
        "src.hk_real_estate.pipeline",
    ):
        assert importlib.import_module(module)


def test_bd_history_parses_stage_aggregates_without_inventing_md52_metrics():
    text = """
TABLE 1.2 CONSENT TO COMMENCE WORKS ISSUED BY THE BUILDING AUTHORITY
2024: Jan 2 3 4 5 14
      Feb 3 4 5 6 18
TABLE 1.3 OCCUPATION PERMITS ISSUED BY THE BUILDING AUTHORITY
2024: Jan 1 2 3 6 700
      Feb 2 3 4 9 800
TABLE 1.4 APPROVALS OF NEW AND MAJOR REVISION BUILDING PLANS
2024: Jan 10 2 12 7 1 8
      Feb 11 3 14 8 2 10
TABLE 1.5 CONSENT TO COMMENCE GENERAL BUILDING AND SUPERSTRUCTURE WORKS
2024: Jan First Submission 100.0 20.0 120.0 50.0 10.0 60.0 200
          Major Revision 10.0 2.0 12.0 5.0 1.0 6.0 20
      Feb First Submission 110.0 30.0 140.0 55.0 15.0 70.0 300
          Major Revision 11.0 3.0 14.0 6.0 2.0 8.0 30
TABLE 1.6 NOTIFICATION OF COMMENCEMENT OF GENERAL BUILDING
2024: Jan 120.0 30.0 150.0 60.0 15.0 75.0 250
      Feb 130.0 40.0 170.0 65.0 20.0 85.0 350
TABLE 1.7 COMPLETION OF NEW BUILDINGS
2024: Jan 200.0 50.0 250.0 100.0 25.0 125.0 700
      Feb 220.0 60.0 280.0 110.0 30.0 140.0 800
"""

    result = parse_bd_history_text(text, 2024, "https://bd.example/Md202412e.pdf", 2024)

    assert len(result) == 10
    jan = result[result["observation_month"].eq("2024-01-01")].set_index("permit_stage")
    demolition = jan.loc["Demolition Consents"]
    assert demolition["total_projects_count"] == 2.0
    assert pd.isna(demolition["total_domestic_units"])
    assert pd.isna(demolition["total_domestic_gfa_sqm"])
    commence = jan.loc["Consent to Commence"]
    assert commence["total_projects_count"] == 5.0
    assert commence["total_domestic_units"] == 220.0
    assert commence["total_domestic_gfa_sqm"] == 110.0
    occupation = jan.loc["Occupation Permits (OP) Issued"]
    assert occupation["total_projects_count"] == 6.0
    assert occupation["total_domestic_units"] == 700.0
    assert occupation["total_domestic_ufa_sqm"] == 100.0


def test_bd_history_accepts_month_names_with_pdf_character_spacing_or_no_colon():
    text = """
TABLE 1.2 CONSENT TO COMMENCE WORKS ISSUED BY THE BUILDING AUTHORITY
2018 Jan 2 3 4 5 14
TABLE 1.3 OCCUPATION PERMITS ISSUED BY THE BUILDING AUTHORITY
2018: J a n 1 2 3 6 700
"""
    result = parse_bd_history_text(text, 2018, "https://bd.example/Md201812e.pdf", 2018)
    assert result[["permit_stage", "observation_month"]].to_dict("records") == [
        {"permit_stage": "Demolition Consents", "observation_month": "2018-01-01"},
        {"permit_stage": "Occupation Permits (OP) Issued", "observation_month": "2018-01-01"},
    ]


def test_bd_history_recovers_table_14_total_when_pdf_merges_preceding_columns():
    text = """
TABLE 1.4 APPROVALS OF NEW AND MAJOR REVISION BUILDING PLANS
2013: Feb 15 5 20 44 8
"""
    result = parse_bd_history_text(text, 2013, "https://bd.example/Md201312e.pdf", 2013)
    assert result.iloc[0]["permit_stage"] == "Plans Approved"
    assert result.iloc[0]["total_projects_count"] == 8.0


def test_bd_history_archive_discovery_and_member_contract():
    import io
    import zipfile

    html = '<a href="/doc/en/whats-new/monthly-digests/Md2024e.zip">2024</a>'
    assert discover_bd_digest_archives(html) == {
        2024: "https://www.bd.gov.hk/doc/en/whats-new/monthly-digests/Md2024e.zip"
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for month in range(1, 13):
            archive.writestr(f"Md2024{month:02d}e.pdf", b"%PDF-1.4")
    assert list_archive_pdf_members(buffer.getvalue(), 2024) == [
        f"Md2024{month:02d}e.pdf" for month in range(1, 13)
    ]


def test_bd_history_accepts_official_revised_archive_member():
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for month in range(1, 13):
            name = f"Md2012{month:02d}e.pdf"
            if month == 4:
                name = "Md201204e_revised.pdf"
            archive.writestr(name, b"%PDF-1.4")
    assert "Md201204e_revised.pdf" in list_archive_pdf_members(buffer.getvalue(), 2012)


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


def test_dedup_hash_normalizes_comma_formatted_prices():
    """Price formatting must not disappear from the cross-agency identity.

    Some agency feeds expose display-formatted prices such as ``12,500,000``.
    The old digit check rejected the comma string and hashed it as an empty
    price, causing distinct units to collide when the other fields matched.
    """
    first = generate_dedup_hash("Estate", "10", "A", "2026-07-20", "12,500,000")
    second = generate_dedup_hash("Estate", "10", "A", "2026-07-20", "13,500,000")
    assert first != second


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


def test_landreg_t2_comparison_rows_keep_change_semantics():
    """Land Registry t2 mixes level rows with year-on-year change rows.

    The comparison flag is part of the official JSON contract.  A change row
    must not be labelled as a registration-month level observation, otherwise
    signed deltas get plotted and aggregated as transaction counts.
    """
    from src.hk_real_estate.sources import landreg as landreg_source

    responses = {
        "t1": [{
            "Year": 2026,
            "Month": 6,
            "Description": "Total Number of Urban & New Territories deeds received for registration (ASP Building Units)",
            "Units": "9,434",
            "Consideration (nearest $ million)": "82,845",
        }],
        "t2": [
            {
                "Year": 2026,
                "Month": 6,
                "Increase (+) or Decrease (-) as compared with": "False",
                "Description": "Total Number of Urban & New Territories deeds received for registration Assignment of Building Units",
                "Units": "13,305",
                "Consideration (nearest $ million)": "79,240",
            },
            {
                "Year": 2025,
                "Month": 6,
                "Increase (+) or Decrease (-) as compared with": "True",
                "Description": "Total Number of Urban & New Territories deeds received for registration Assignment of Building Units",
                "Units": "-2",
                "Consideration (nearest $ million)": "-2,810",
            },
        ],
        "t3": [],
        "t6": [],
    }

    def fake_get(url, **kwargs):
        response = MagicMock()
        response.raise_for_status.return_value = None
        if url.endswith("monthly.htm"):
            response.text = "<html></html>"
        else:
            table = url.rsplit("/", 1)[-1].split(".", 1)[0]
            response.json.return_value = responses[table]
        return response

    with patch.object(landreg_source.requests, "get", side_effect=fake_get), patch.object(
        landreg_source, "save_raw_snapshot", return_value="/tmp/landreg.json"
    ):
        facts, _ = fetch_landreg_monthly_statistics()

    t2 = facts[facts["table_id"] == "t2"].sort_values("date")
    assert list(t2["comparison_type"]) == ["year_over_year_change", "level"]
    assert list(t2["is_comparison_change"]) == [True, False]
    assert t2.iloc[0]["basis"] == "year_over_year_change"
    assert t2.iloc[1]["basis"] == "registration_receipt_month"


def test_landreg_quality_key_keeps_levels_and_changes_at_distinct_grain():
    facts = pd.DataFrame(
        [
            {
                "date": "2026-06-01",
                "statistic_name": "same metric",
                "table_id": "t2",
                "units": 100,
                "comparison_type": "level",
            },
            {
                "date": "2026-06-01",
                "statistic_name": "same metric",
                "table_id": "t2",
                "units": -2,
                "comparison_type": "year_over_year_change",
            },
        ]
    )
    assert _quality_errors("landreg_monthly_facts", facts) == []


def test_landreg_archive_series_keeps_archive_lineage():
    from src.hk_real_estate.sources import landreg as landreg_source

    def fake_get(url, **kwargs):
        response = MagicMock(status_code=200)
        response.raise_for_status.return_value = None
        if url.endswith("monthly.htm"):
            response.text = "<html></html>"
        elif "monthly_agt" in url:
            response.json.return_value = [{
                "Date": "1996-01-01",
                "Year": 1996,
                "Month": 1,
                "Number of ASP for Residential Building Units": 100,
                "Number of ASP for All Building Units": 120,
            }]
        else:
            table = url.rsplit("/", 1)[-1].split(".", 1)[0]
            response.json.return_value = []
        return response

    def fake_snapshot(name, content, file_ext="json", **kwargs):
        return f"/tmp/{name}.{file_ext}"

    with patch.object(landreg_source.requests, "get", side_effect=fake_get), patch.object(
        landreg_source, "save_raw_snapshot", side_effect=fake_snapshot
    ):
        _, series = fetch_landreg_monthly_statistics()

    raw_paths = json.loads(series.attrs["raw_snapshot"])
    source_urls = json.loads(series.attrs["source_url"])
    assert any("agt-1" in path for path in raw_paths)
    assert any("monthly_agt/agt-1/t1.json" in url for url in source_urls)


def test_parse_midland_mhpi():
    df = parse_midland_mhpi({"mrIndexWeekly": [{"date": "2026-03-14T00:00:00.000Z", "mr_index": 124.7, "mr_index_hk": 140.5, "mr_index_kln": 121.2, "mr_index_nt": 116.5, "weekly_perc": -0.5}]})
    assert len(df) == 1
    assert df.iloc[0]["date"] == "2026-03-14"
    assert df.iloc[0]["mhpi_overall"] == 124.7


def test_parse_midland_monthly_preserves_volume_and_price_fields():
    df = parse_midland_mhpi_monthly(
        {
            "mrIndex": [
                {
                    "date": "2025-01-01T00:00:00.000Z",
                    "mr_index": 100,
                    "mr_index_hk": 101,
                    "mr_index_kln": 99,
                    "mr_index_nt": 98,
                    "tx_count": 1000,
                    "tx_count_hk": 300,
                    "tx_count_kln": 350,
                    "tx_count_nt": 350,
                    "fh_tx_count": 120,
                    "net_ft_price": 12000,
                    "ft_price": 11000,
                    "net_ft_rent": 35.0,
                    "ft_rent": 30.0,
                }
            ]
        }
    )
    assert len(df) == 1
    assert df.iloc[0]["transaction_count_total"] == 1000
    assert df.iloc[0]["net_ft_price_overall"] == 12000


def test_midland_field_dictionary_persists_units_for_wide_and_long_contracts():
    dictionary = build_midland_field_dictionary()
    assert {
        "midland_mhpi_monthly",
        "midland_economic_indicators_monthly",
        "midland_market_snapshots",
        "midland_transaction_summary_snapshot",
    }.issubset(set(dictionary["dataset"]))
    assert dictionary.loc[dictionary["source_field"].eq("net_ft_price_overall"), "unit"].iloc[0] == "HKD_per_sqft_net"
    assert dictionary.loc[dictionary["source_field"].eq("amount"), "unit"].iloc[0] == "HKD_bn"


def test_parse_midland_economic_indicators_is_long_and_preserves_source_fields():
    df = parse_midland_economic_indicators(
        {
            "economicIndicators": [
                {
                    "date": "2025-01-01T00:00:00.000Z",
                    "Mortgage_Interest_Rate": 3.5,
                    "House_Price_to_Income_Ratio": 10.2,
                }
            ]
        }
    )
    assert set(df["indicator_name"]) == {"Mortgage_Interest_Rate", "House_Price_to_Income_Ratio"}
    assert set(df["unit"]) == {"percent", "ratio"}
    assert set(df["source_field"]) == set(df["indicator_name"])


def test_parse_midland_snapshots_preserves_windows_and_as_of_date():
    props = {
        "marketStatAll": [
            {
                "id": "ALL",
                "daily": {
                    "date": "2026-07-29T16:00:00.000Z",
                    "avg_net_ft_price": 14925,
                    "pre_avg_net_ft_price": 14924,
                    "total_tx_count": 3382,
                    "pre_total_tx_count": 5029,
                    "window_start": "2026-07-01",
                    "window_end": "2026-07-29",
                    "pre_window_start": "2026-06-01",
                    "pre_window_end": "2026-06-30",
                },
            }
        ],
        "marketStatRegion": [],
        "marketStatDistrict": [],
        "langRegRecords": [
            {
                "firsthand_private": {"number": 726, "amount": 138.75, "number_chg": -62.2, "amount_chg": -50},
                "as_of_date": "2026-07-29T00:00:00.000Z",
                "update_date": "2026-07-30T05:55:33.757Z",
            }
        ],
    }
    market = parse_midland_market_snapshots(props)
    assert set(market["period_type"]) == {"current", "previous_window"}
    assert market[market["metric"].eq("avg_net_ft_price")]["value"].tolist() == [14925.0, 14924.0]
    current = market[(market["period_type"] == "current") & market["metric"].eq("avg_net_ft_price")].iloc[0]
    previous = market[(market["period_type"] == "previous_window") & market["metric"].eq("avg_net_ft_price")].iloc[0]
    assert current["unit"] == "HKD_per_sqft_net"
    assert current["window_start"] == "2026-07-01"
    assert previous["window_end"] == "2026-06-30"
    summary = parse_midland_transaction_summary_snapshot(props)
    assert set(summary["asset_class"]) == {"firsthand_private"}
    assert summary[summary["metric"].eq("number")].iloc[0]["value"] == 726
    amount = summary[summary["metric"].eq("amount")].iloc[0]
    assert amount["unit"] == "HKD_bn"
    assert amount["as_of_date"] == "2026-07-29"
    assert amount["update_date"].startswith("2026-07-30T05:55:33")


def test_property_events_are_research_hints_and_registry_contract_is_explicit():
    hints = parse_midland_property_event_hints(
        {"propertyEvent": [{"post_date": "2026-02-25T04:00:00Z", "id": "A", "description": "Stamp duty hint"}]}
    )
    assert hints.iloc[0]["status"] == "research_only"
    assert hints.iloc[0]["source_agency"] == "Midland Realty"
    catalog = build_primary_policy_sources_catalog()
    assert len(catalog) >= 4
    assert catalog["status"].eq("catalog_only").all()
    registry = pd.DataFrame(
        [{
            "stock_code": "0016", "listed_company_en": "SHKP", "subsidiary_spv_name": "SPV",
            "project_name_en": "Project", "project_aliases": "Alias", "asset_type": "residential_dev",
            "ownership_pct": 50, "source_document": "Annual report", "last_verified_date": "2026-01-01",
            "effective_from": "2025-01-01", "effective_to": "",
        }]
    )
    _, errors = validate_developer_project_registry(registry)
    assert errors == []


def test_registry_validator_rejects_missing_stock_code_and_required_text():
    registry = pd.DataFrame([{
        "stock_code": None, "listed_company_en": "", "subsidiary_spv_name": "SPV",
        "project_name_en": "Project", "project_aliases": "Alias", "asset_type": "residential_dev",
        "ownership_pct": 50, "source_document": "Annual report", "last_verified_date": "2026-01-01",
        "effective_from": "2025-01-01", "effective_to": "",
    }])
    _, errors = validate_developer_project_registry(registry)
    assert "stock_code contains empty values" in errors
    assert "listed_company_en contains empty values" in errors


def test_parse_centaline_cci_cri_and_csi_history_contracts():
    cci = parse_centaline_index_history(
        {
            "cci": {"chartData": {"date": ["2025-01-01", "2025-02-01"], "index": [100, 101.5]}}
        },
        "CCI",
    )
    assert cci[["date", "series_id", "metric", "index_value"]].to_dict("records") == [
        {"date": "2025-01-01", "series_id": "overall", "metric": "price_index", "index_value": 100.0},
        {"date": "2025-02-01", "series_id": "overall", "metric": "price_index", "index_value": 101.5},
    ]

    cri = parse_centaline_index_history(
        {
            "cri": {"chartData": {"date": ["2025-01-01", "2025-02-01"], "index": [100, 101]}},
            "criYield": {"chartData": {"date": ["2025-01-01", "2025-02-01"], "index": [4.0, 3.9]}},
        },
        "CRI",
    )
    assert set(cri["metric"]) == {"rental_index", "rental_yield"}
    assert len(cri) == 4

    csi = parse_centaline_index_history(
        {
            "chartData": {
                "date": ["2025-01-06", "2025-01-13"],
                "residPrice": [60, 61],
                "residRental": [None, 62],
            }
        },
        "CSI",
    )
    assert set(csi["series_id"]) == {"residential_price", "residential_rental"}
    assert len(csi) == 3


def test_parse_centaline_snapshots_keeps_current_cross_section_separate():
    snapshots = parse_centaline_index_snapshots(
        {
            "cci": {"index": 155.7, "voteDate": "2026-05-01T00:00:00", "publishDate": "2026-07-18T16:00:00"},
            "hk": {"index": 150.1, "voteDate": "2026-05-01T00:00:00", "publishDate": "2026-07-18T16:00:00"},
            "dateRange": {"start": "1994-01-01", "end": "2026-05-01"},
        },
        "CCI",
    )
    assert set(snapshots["series_id"]) == {"overall", "hk_island"}
    assert snapshots["date"].eq("2026-05-01").all()


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


def test_parse_rvd_commercial_csv_preserves_office_grades_and_retail_metrics():
    office = _parse_rvd_commercial_csv(
        "PRIVATE OFFICES,,,,,,,,\nMonth,Grade A,Grade A - Remarks,Grade B,Grade B - Remarks,Grade C,Grade C - Remarks,Overall,Overall - Remarks\n01-2026,120.0,,110.0,P,100.0,,115.0,\n",
        "office",
    )
    assert set(office["segment"]) == {"grade_a", "grade_b", "grade_c", "overall"}
    assert bool(office[office["segment"].eq("grade_b")].iloc[0]["is_provisional"]) is True
    retail = _parse_rvd_commercial_csv(
        "PRIVATE RETAIL,,,,\nMonth,Rents,Rents - Remarks,Prices,Prices - Remarks\n01-2026,105.0,,98.0,P\n",
        "retail",
    )
    assert set(retail["metric"]) == {"rental_index", "price_index"}
    assert bool(retail[retail["metric"].eq("price_index")].iloc[0]["is_provisional"]) is True


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
    assert lineage["raw_snapshots"] == ["/tmp/raw.csv"]


def test_save_normalized_dataset_supports_multi_parent_lineage():
    result = save_normalized_dataset(
        "multi_parent",
        pd.DataFrame([{"date": "2026-07-22", "val": 100.0}]),
        run_id="run-multi",
        raw_snapshots=["/tmp/a.json", "/tmp/b.json"],
        source_urls=["https://a.test", "https://b.test"],
        lineage_metadata={"lineage_type": "combined_snapshot"},
    )
    lineage = json.loads(Path(result["lineage"]).read_text())
    assert lineage["raw_snapshot"] is None
    assert lineage["raw_snapshots"] == ["/tmp/a.json", "/tmp/b.json"]
    assert lineage["source_urls"] == ["https://a.test", "https://b.test"]
    assert lineage["lineage_type"] == "combined_snapshot"


def test_quality_gate_rejects_non_numeric_or_negative_new_measures():
    invalid = pd.DataFrame([{
        "date": "2026-07-22", "series_id": "overall", "metric": "price_index", "index_value": "bad"
    }])
    assert _quality_errors("centaline_cci_monthly", invalid) == ["index_value contains non-numeric values"]
    negative = invalid.assign(index_value=-1)
    assert _quality_errors("centaline_cci_monthly", negative) == ["index_value contains negative values"]
    out_of_scale = invalid.assign(index_value=101)
    assert _quality_errors("centaline_csi_weekly", out_of_scale) == ["index_value is outside the allowed range [0, 100]"]
    market_change = pd.DataFrame([{
        "date": "2026-07-22", "as_of_date": "2026-07-22", "scope_type": "all", "scope_id": "ALL",
        "period_type": "current", "metric": "avg_net_ft_price_chg", "value": -2.5, "unit": "percent",
    }])
    assert _quality_errors("midland_market_snapshots", market_change) == []


def test_run_all_includes_new_tranches(monkeypatch):
    runner_names = {
        "run_group_a_pipeline": "group_a_dataset",
        "run_group_b_pipeline": "group_b_dataset",
        "run_group_c_pipeline": "group_c_dataset",
        "run_stage_2_pipeline": "stage_2_dataset",
        "run_all_incomplete_pipelines": "incomplete_dataset",
        "run_midland_monthly_pipeline": "midland_monthly_dataset",
        "run_rvd_commercial_pipeline": "rvd_commercial_dataset",
        "run_hk_commercial_controls_pipeline": "hk_commercial_controls_dataset",
        "run_midland_snapshot_pipeline": "midland_snapshot_dataset",
        "run_policy_event_research_pipeline": "policy_dataset",
    }
    called = []
    for function_name, dataset_name in runner_names.items():
        def fake_runner(run_id=None, *, _raise_on_failure=True, _dataset_name=dataset_name):
            called.append(_dataset_name)
            return {_dataset_name: {"status": "success", "records": 1}}
        monkeypatch.setattr(pipeline_module, function_name, fake_runner)
    monkeypatch.setattr(pipeline_module, "write_run_manifest", lambda *args, **kwargs: "/tmp/manifest.json")
    monkeypatch.delenv(pipeline_module.SKIP_MIDLAND_ENV_VAR, raising=False)
    result = pipeline_module.run_all_pipelines()
    assert set(called) == set(runner_names.values())
    assert set(result) == set(runner_names.values())


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
    assert row["region"] == "New Territories"
    # The bare planning-reference continuation line must not pollute the address.
    assert "7.4.1/(6)" not in row["site_address"]
    assert row["domestic_units_count"] == 86 + 91 + 365 + 172 + 13
    # GFA/UFA are the project's published total (from the header row), not re-summed across tiers.
    assert row["usable_floor_area_sqm"] == 19525.8
    assert row["site_area_sqm"] == 157343.4


def test_bd_project_region_uses_address_when_section_state_is_wrong():
    """A wrapped address can contain the authoritative region label.

    Section-header state is easy to misalign when an XLS has continuation
    rows or a new file layout.  Prefer an explicit address region over the
    last section seen, while retaining the parser's fallback for addresses
    that do not name a region.
    """
    assert _infer_region_from_address("8 Hoi Ying Road, Tai Po, New Territories", "Hong Kong Island") == "New Territories"
    assert _infer_region_from_address("Kai Tak Area 2A Site 2, Kowloon N.K.I.L. 6590", "Hong Kong Island") == "Kowloon"
    assert _infer_region_from_address("12 Mount Cameron Road, Mid-Levels, Hong Kong", "Kowloon") == "Hong Kong Island"
    assert _infer_region_from_address("Yellow Area", "Kowloon") == "Kowloon"


def test_bd_project_fetch_preserves_lineage_for_each_xls_source():
    from src.hk_real_estate.sources import bd_projects as bd_source

    response = MagicMock(status_code=200, content=b"xls")
    parsed = pd.DataFrame([{"site_address": "Example Road", "permit_stage": "Plans Approved"}])
    raw_paths = ["/tmp/Md52.xls", "/tmp/Md53.xls", "/tmp/Md54.xls", "/tmp/Md55.xls", "/tmp/Md56.xls"]

    with patch.object(bd_source.requests, "get", return_value=response), patch.object(
        bd_source, "parse_bd_xls_projects", return_value=parsed.copy()
    ), patch.object(bd_source, "save_raw_snapshot", side_effect=raw_paths):
        result = fetch_bd_project_lifecycle_events()

    assert json.loads(result.attrs["raw_snapshot"]) == raw_paths
    assert json.loads(result.attrs["source_url"]) == [
        f"{bd_source.BD_MONTHLY_DIGEST_XLS_BASE}/Md52.xls",
        f"{bd_source.BD_MONTHLY_DIGEST_XLS_BASE}/Md53.xls",
        f"{bd_source.BD_MONTHLY_DIGEST_XLS_BASE}/Md54.xls",
        f"{bd_source.BD_MONTHLY_DIGEST_XLS_BASE}/Md55.xls",
        f"{bd_source.BD_MONTHLY_DIGEST_XLS_BASE}/Md56.xls",
    ]


def test_bd_project_concat_has_stable_nullable_numeric_types():
    from src.hk_real_estate.sources import bd_projects as bd_source

    response = MagicMock(status_code=200, content=b"xls")
    frames = [
        pd.DataFrame([{"permit_stage": "Demolition Consents", "site_area_sqm": None, "domestic_units_count": None}]),
        pd.DataFrame([{"permit_stage": "Plans Approved", "site_area_sqm": None, "domestic_units_count": None}]),
        pd.DataFrame([{"permit_stage": "Consent to Commence", "site_area_sqm": 12.5, "domestic_units_count": 2}]),
        pd.DataFrame([{"permit_stage": "Notice of Commencement Received", "site_area_sqm": 13.0, "domestic_units_count": 2}]),
        pd.DataFrame([{"permit_stage": "Occupation Permits (OP) Issued", "site_area_sqm": 15.0, "domestic_units_count": 3}]),
    ]

    with patch.object(bd_source.requests, "get", return_value=response), patch.object(
        bd_source, "parse_bd_xls_projects", side_effect=frames
    ), patch.object(bd_source, "save_raw_snapshot", return_value="/tmp/bd.xls"):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = fetch_bd_project_lifecycle_events()

    assert not any(issubclass(item.category, FutureWarning) for item in caught)
    assert pd.api.types.is_numeric_dtype(result["site_area_sqm"])


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


def test_bd_md55_repeated_header_continuation_stays_with_its_site():
    """Md55 repeats blocks/type on an address continuation for the same site.

    The live July 2026 file has ``145-149 Third Street,`` followed by a
    ``Hong Kong`` row carrying a second building type.  The second row is a
    component of the same site, not a project literally located at "Hong
    Kong".
    """
    header_row = [None] * 13
    filler_rows = [[None] * 13 for _ in range(7)]
    project_rows = [
        ["145-149 Third Street,", 1, 1, "Residence", 1, 9.5, 21.5, "-", 9.5, "-", "AP", "RSE", "Applicant"],
        ["Hong Kong", 1, 1, "Plant room", None, None, None, None, None, None, None, None, None],
        ["1.1.2/(33)", None, None, None, None, None, None, None, None, None, None, None, None],
    ]

    df = parse_bd_xls_projects(
        _rows_to_xls_bytes([header_row] + filler_rows + project_rows),
        "Notice of Commencement Received",
    )

    assert len(df) == 1
    assert df.iloc[0]["site_address"] == "145-149 Third Street, Hong Kong"
    assert df.iloc[0]["domestic_units_count"] == 1


def test_bd_supply_keeps_metrics_null_when_stage_does_not_publish_them():
    """Demolition-consent rows are project counts, not zero-unit projects."""
    projects = pd.DataFrame(
        [
            {
                "permit_stage": "Demolition Consents",
                "region": "Hong Kong Island",
                "property_category": "Unknown",
                "domestic_units_count": None,
                "usable_floor_area_sqm": None,
                "site_area_sqm": None,
            }
        ]
    )
    with patch("src.hk_real_estate.sources.bd_projects.fetch_bd_project_lifecycle_events", return_value=projects):
        indicators = fetch_bd_supply_leading_indicators()

    assert len(indicators) == 1
    assert pd.isna(indicators.iloc[0]["total_domestic_units"])
    assert pd.isna(indicators.iloc[0]["total_usable_floor_area_sqm"])


def test_bd_demolition_projects_are_not_classified_as_domestic_supply():
    header_row = [None] * 4
    filler_rows = [[None] * 4 for _ in range(7)]
    project_rows = [
        ["66 Deep Water Bay Road,", "Single family house", "AP", "Applicant"],
        ["Hong Kong", None, None, None],
    ]

    df = parse_bd_xls_projects(
        _rows_to_xls_bytes([header_row] + filler_rows + project_rows),
        "Demolition Consents",
    )

    assert len(df) == 1
    assert df.iloc[0]["property_category"] == "Unknown"


def test_bd_md55_resolves_footnoted_domestic_unit_count():
    """Md55 uses # in the unit cell and publishes the actual count in a note."""
    header_row = [None] * 13
    filler_rows = [[None] * 13 for _ in range(7)]
    project_rows = [
        ["3A Kung Ngam Road,", 1, 33, "Public rental housing", "#", "-", 72289.9, 8387.9, 32387.2, 5366.9, "AP", "RSE", "Applicant"],
        ["Hong Kong", None, None, None, None, None, None, None, None, None, None, None, None],
        [None] * 13,
        ["# 1 595 units for public rental housing.", None, None, None, None, None, None, None, None, None, None, None, None],
    ]

    df = parse_bd_xls_projects(
        _rows_to_xls_bytes([header_row] + filler_rows + project_rows),
        "Notice of Commencement Received",
    )

    assert len(df) == 1
    assert df.iloc[0]["domestic_units_count"] == 1595


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
        resp.status_code = 200
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
