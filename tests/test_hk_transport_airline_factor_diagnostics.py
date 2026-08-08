from __future__ import annotations

import pandas as pd


def test_pair_factor_diagnostics_covers_all_pairs_and_core_proxies() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_pair_factor_diagnostics.csv")
    assert len(frame) == 21
    assert frame.duplicated("pair_id").sum() == 0
    required = [
        "beta_gap_a_minus_b", "log_size_gap_a_minus_b",
        "momentum_3m_gap_a_minus_b_pct", "volatility_gap_a_minus_b_pct",
        "max_drawdown_gap_a_minus_b_pct",
    ]
    assert frame[required].notna().all().all()
    assert frame["source_quality"].eq("derived_free_factor_proxies").all()


def test_pair_factor_diagnostics_is_explicitly_not_formal_barra_or_borrow_data() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_pair_factor_diagnostics.csv")
    assert frame["source_note"].str.contains("not formal Barra exposures").all()
    assert frame["borrow_data_available_a"].eq(False).all()
    assert frame["borrow_data_available_b"].eq(False).all()
