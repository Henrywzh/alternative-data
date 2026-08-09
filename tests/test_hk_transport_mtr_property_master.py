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
        "cross_ref_hk_real_estate", "source",
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


def test_recognition_years_are_official_disclosures():
    """Spot-check recognition years against MTR official announcements."""
    df = load_mtr_property_project_master().set_index("project_id")
    # 2022 results: LP10, SOUTHLAND (P1), La Marina (P2)
    assert "2022" in str(df.loc["lohas-park-p10", "profit_recognition_year"])
    assert "2022" in str(df.loc["the-southside-p1", "profit_recognition_year"])
    assert "2022" in str(df.loc["the-southside-p2", "profit_recognition_year"])
    # 2025 results: THE SOUTHSIDE P3/P5, LOHAS Park P12, Ho Man Tin P1/P2
    assert "2025" in str(df.loc["the-southside-p3", "profit_recognition_year"])
    assert "2025" in str(df.loc["lohas-park-p12", "profit_recognition_year"])
    assert "2025" in str(df.loc["ho-man-tin-p2", "profit_recognition_year"])
    # 2024-12 tender: Tung Chung East P1
    assert "2024" in str(df.loc["tung-chung-east-p1", "tender_year"])
