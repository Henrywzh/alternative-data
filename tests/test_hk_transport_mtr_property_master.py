import pandas as pd
import pytest
from src.hk_transport.sources.mtr_property_project_master import load_mtr_property_project_master


def test_master_loads_with_expected_schema():
    df = load_mtr_property_project_master()
    assert isinstance(df, pd.DataFrame)
    assert len(df) >= 15
    expected_cols = {
        "project_id", "station", "package_label", "project_name_official",
        "developer", "profit_recognition_year", "tender_year",
        "srpe_development_id", "srpe_phase_name", "srpe_first_price_list_date",
        "evidence_level", "cross_ref_hk_real_estate", "source",
    }
    assert expected_cols.issubset(set(df.columns))


@pytest.mark.parametrize(
    "project_id,expected_source_fragment",
    [
        ("lohas-park-p11", "Villa Garda"),
        ("the-southside-p1", "SOUTHLAND"),
        ("the-southside-p2", "La Marina"),
        ("the-southside-p4", "La Montagne"),
        ("ho-man-tin-p2", "IN ONE"),
        ("lohas-park-p4a", "Wings at Sea"),
    ],
)
def test_official_project_names(project_id, expected_source_fragment):
    df = load_mtr_property_project_master()
    row = df[df["project_id"] == project_id].iloc[0]
    assert expected_source_fragment in str(row["project_name_official"]) or \
           expected_source_fragment in str(row["package_label"])


@pytest.mark.parametrize(
    "project_id,srpe_id,expected_date",
    [
        ("the-southside-p1", "7585", "2021-04-19"),   # 晉環 SOUTHLAND
        ("the-southside-p2", "7787", "2021-08-17"),   # 揚海 La Marina
        ("the-southside-p4", "9345", "2023-06-27"),   # 海盈山 La Montagne
        ("ho-man-tin-p2", "8745", "2023-05-08"),      # 瑜一 IN ONE
        ("lohas-park-p11", "8545", "2022-06-20"),     # 凱柏峰 I Villa Garda
        ("lohas-park-p4a", "4745", "2017-09-08"),     # 晉海 Wings at Sea
        ("lohas-park-p4b", "4865", "2017-10-14"),     # 晉海II
    ],
)
def test_confirmed_srpe_crosswalk(project_id, srpe_id, expected_date):
    """SRPE crosswalk must match the official SRPE development index snapshot."""
    df = load_mtr_property_project_master()
    row = df[df["project_id"] == project_id].iloc[0]
    assert row["srpe_development_id"] == srpe_id
    assert str(row["srpe_first_price_list_date"]).startswith(expected_date)


def test_ambiguous_phases_stay_unmapped():
    """Phases without a confirmed mapping must keep NULL srpe ids (no guessing)."""
    df = load_mtr_property_project_master()
    for pid in ["the-southside-p3", "the-southside-p5", "the-southside-p6",
                "ho-man-tin-p1", "lohas-park-p12", "lohas-park-p10"]:
        row = df[df["project_id"] == pid].iloc[0]
        assert pd.isna(row["srpe_development_id"])
        assert row["evidence_level"] == "official_recognition_only"


def test_recognition_years_are_official_disclosures():
    df = load_mtr_property_project_master().set_index("project_id")
    assert "2022" in str(df.loc["lohas-park-p10", "profit_recognition_year"])
    assert "2022" in str(df.loc["the-southside-p1", "profit_recognition_year"])
    assert "2022" in str(df.loc["the-southside-p2", "profit_recognition_year"])
    assert "2025" in str(df.loc["the-southside-p3", "profit_recognition_year"])
    assert "2025" in str(df.loc["lohas-park-p12", "profit_recognition_year"])
    assert "2025" in str(df.loc["ho-man-tin-p2", "profit_recognition_year"])
    assert "2024" in str(df.loc["tung-chung-east-p1", "tender_year"])
