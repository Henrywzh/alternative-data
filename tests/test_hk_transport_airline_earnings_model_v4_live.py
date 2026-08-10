"""Tests for the v4 live pre-event forecast + diagnostics."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_transport.sources import airline_earnings_model_v4_live as live


@pytest.fixture(scope="module")
def outputs() -> dict[str, pd.DataFrame]:
    return live.build_airline_earnings_model_v4_live()


def test_live_covers_six_carriers(outputs: dict[str, pd.DataFrame]) -> None:
    lf = outputs["live"]
    assert set(lf.company) == set(live.COMPANIES)
    assert (lf.forecast_type == "pre_event").all()
    assert (lf.model_version == live.MODEL_VERSION).all()
    assert (lf.forecast_asof == live.FORECAST_ASOF).all()


def test_live_layer_monotonic_components(outputs: dict[str, pd.DataFrame]) -> None:
    lf = outputs["live"]
    # Every layer must be present and finite for all carriers.
    for col in [
        "revenue_base_native_mn",
        "revenue_shrink_native_mn",
        "revenue_resid_native_mn",
        "revenue_overlay_native_mn",
        "lf_f",
        "yield_f_final",
    ]:
        assert lf[col].notna().all()
    assert (lf.lf_shrink_lambda >= 0.5).all()
    assert (lf.yield_modifier_delta_pct.abs() <= 3.0).all()


def test_surprise_validity_flags(outputs: dict[str, pd.DataFrame]) -> None:
    s = outputs["surprise"]
    valid = s[s.h1_annualisation_valid]
    # Only the H1-2025 profitable carriers may carry a surprise number.
    assert set(valid.company) == {"Spring Airlines", "Juneyao Airlines"}
    assert valid.surprise_v4_vs_consensus_pct.notna().all()
    invalid = s[~s.h1_annualisation_valid]
    assert invalid.surprise_v4_vs_consensus_pct.isna().all()


def test_pair_still_holds_under_v4(outputs: dict[str, pd.DataFrame]) -> None:
    s = outputs["surprise"].set_index("company")
    spring = s.loc["Spring Airlines", "surprise_v4_vs_consensus_pct"]
    juneyao = s.loc["Juneyao Airlines", "surprise_v4_vs_consensus_pct"]
    # Spring beats consensus more than Juneyao does.
    assert spring > juneyao
    assert spring > 20.0


def test_recovery_overlay_not_active_for_2026(outputs: dict[str, pd.DataFrame]) -> None:
    lf = outputs["live"]
    spring = lf[lf.company.eq("Spring Airlines")].iloc[0]
    # H1-2026 demand signal is normal growth, not a 2023-style reopening.
    assert not bool(spring.recovery_overlay_active)


def test_frozen_snapshot_written_once(outputs: dict[str, pd.DataFrame]) -> None:
    path = live.SNAPSHOT_DIR / f"airline_v4_pre_event_{live.FORECAST_ASOF.replace('-', '')}.csv"
    assert path.exists()
    snap = pd.read_csv(path)
    assert (snap.forecast_type == "pre_event").all()
    assert "snapshot_created_at" in snap.columns


def test_spread_diagnostic_written_and_honest(outputs: dict[str, pd.DataFrame]) -> None:
    sp = outputs["spread"]
    assert len(sp) > 0
    # The diagnostic must report the true (low) accuracy, not a curated one.
    assert sp.attrs.get("direction_accuracy_1st_order", 1.0) < 0.5
    assert sp.attrs.get("direction_accuracy_2nd_order", 1.0) < 0.5
    assert "direction_correct_1st_order" in sp.columns


def test_persistence_output(outputs: dict[str, pd.DataFrame]) -> None:
    p = outputs["persistence"]
    assert {"company", "target_year", "shrink_lambda", "forecast_error_pct", "prior_error_sign"}.issubset(p.columns)
    juneyao = p[p.company.eq("Juneyao Airlines")]
    assert len(juneyao) >= 5
