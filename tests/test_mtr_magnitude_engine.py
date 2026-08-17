import pandas as pd
import pytest
from scripts.mtr_magnitude_engine import CONFIRMATION_GROUPS


def test_group_definitions_cover_official_periods():
    labels = [g["group"] for g in CONFIRMATION_GROUPS]
    assert labels == ["G2022H1", "G2024H2", "G2025H1"]
    profits = {g["group"]: g["mtr_profit_post_tax_hkdm"] for g in CONFIRMATION_GROUPS}
    assert profits["G2022H1"] == 7747.0
    assert profits["G2024H2"] == 8525.0
    assert profits["G2025H1"] == 5542.0


def test_magnitude_csv_has_phase_stats():
    with open("data/normalized/hk_transport/mtr_magnitude_engine.csv") as f:
        head = f.read(3000)
    assert "registered_sales_value_hkdm" in head
    assert "registered_transaction_count" in head
    assert "price_median_hkd" in head


def test_sales_value_anchors():
    """Spot-check registered sales value from the parsed transaction detail."""
    det = pd.read_csv("data/normalized/hk_transport/mtr_srpe_transactions_detail.csv")
    det = det[det["is_cancelled"].fillna(False) == False]  # noqa: E712
    v = det[det["project_id"] == "the-southside-p1"]["transaction_price_hkd"].sum() / 1e6
    assert v == pytest.approx(16823, rel=0.005)
    v2 = det[det["project_id"] == "ho-man-tin-p2"]["transaction_price_hkd"].sum() / 1e6
    assert v2 == pytest.approx(6704, rel=0.005)


def test_take_rate_is_upper_bound_not_lower():
    """Missing members shrink the denominator, so ratios are upper bounds."""
    with open("data/normalized/hk_transport/mtr_magnitude_engine.csv") as f:
        content = f.read()
    assert "UPPER-bound" in content
    assert "NOT_CALCULABLE" in content or "78.4" in content
