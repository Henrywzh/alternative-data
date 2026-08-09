import pandas as pd
import pytest
from scripts.mtr_timing_engine import PHASE_OP


def test_phase_op_mapping_coverage():
    """All mapped phases must have an OP record with evidence labels."""
    assert len(PHASE_OP) >= 6
    assert all(len(v) == 6 for v in PHASE_OP.values())


@pytest.mark.parametrize(
    "project_id,expected_permit,expected_op_month",
    [
        ("the-southside-p1", "PR4/2022/OP", "2022-04"),
        ("the-southside-p2", "PR6/2022/OP", "2022-08"),
        ("the-southside-p4", "PR12/2024/OP", "2024-11"),
        ("ho-man-tin-p2", "PR11/2024/OP", "2024-11"),
        ("lohas-park-p11", "PR13/2024/OP", "2024-12"),
        ("lohas-park-p12", "PR7/2025/OP", "2025-10"),
    ],
)
def test_op_anchors(project_id, expected_permit, expected_op_month):
    """OP permit numbers/months must match the BD lifecycle history records."""
    addr, permit, month, units, evidence, rec_year = PHASE_OP[project_id]
    assert permit == expected_permit
    assert month == expected_op_month
    assert rec_year == int(month[:4]) or rec_year in (int(month[:4]) + 1,)


def test_timing_history_csv_exists_and_consistent():
    df = pd.read_csv("data/normalized/hk_transport/mtr_property_timing_history.csv")
    assert len(df) == len(PHASE_OP)
    assert "op_issuance_month" in df.columns
    assert "mtr_recognition_year" in df.columns
    assert "evidence_level" in df.columns
    assert (df["evidence_level"].isin(["strong", "suspected"])).all()
    # recognition year never precedes OP year by more than 1 (same-year or next)
    for _, r in df.iterrows():
        op_year = int(str(r["op_issuance_month"])[:4])
        assert r["mtr_recognition_year"] in (op_year, op_year + 1)


def test_recognition_split_self_consistent():
    """Official H1/H2 split must sum to the annual total for every year."""
    from scripts.mtr_timing_engine import RECOGNITION_SPLIT
    annual = {2020: 5507, 2021: 9343, 2022: 10413, 2023: 2083, 2024: 10265, 2025: 11084}
    for year, info in RECOGNITION_SPLIT.items():
        assert info["h1"] + info["h2"] == annual[year], year


def test_recognition_split_csv():
    df = pd.read_csv("data/normalized/hk_transport/mtr_property_recognition_h1h2.csv")
    assert len(df) == 6
    assert df["fiscal_year"].tolist() == [2020, 2021, 2022, 2023, 2024, 2025]
    row = df[df["fiscal_year"] == 2022].iloc[0]
    assert row["hk_property_dev_profit_post_tax_h1_hkdm"] == 7747
    assert row["hk_property_dev_profit_post_tax_h2_hkdm"] == 2666


def test_timing_history_has_recognition_half():
    df = pd.read_csv("data/normalized/hk_transport/mtr_property_timing_history.csv")
    assert "mtr_recognition_half" in df.columns
    assert "recognition_half_evidence" in df.columns
    # 晉環 strong 2022-H1; 瑜一 strong 2025-H1
    p1 = df[df["project_id"] == "the-southside-p1"].iloc[0]
    assert p1["mtr_recognition_half"] == "2022-H1"
    assert p1["recognition_half_evidence"] == "strong"
    hmt = df[df["project_id"] == "ho-man-tin-p2"].iloc[0]
    assert hmt["mtr_recognition_half"] == "2025-H1"
