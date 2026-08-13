"""Regression checks for the MTR H1 transport-revenue backtest."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mtr_farebox_revenue_backtest.py"
SPEC = importlib.util.spec_from_file_location("mtr_farebox_revenue_backtest", MODULE_PATH)
assert SPEC and SPEC.loader
mtr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mtr)


def _build_monthly():
    patronage = mtr._load_patronage(False)
    yields = mtr._calibrate_yields(patronage)
    return mtr._build_monthly_series(patronage, yields, pd.DataFrame())


def test_official_h1_actuals_are_complete_and_source_backed():
    annual, actuals = mtr._load_transport_ops_actuals()

    assert actuals["year"].tolist() == list(range(2017, 2026))
    assert actuals["h1_actual_transport_ops_revenue_hkdm"].notna().all()
    assert actuals["source_url"].str.startswith("https://").all()
    assert actuals["release_source_url"].str.startswith("https://").all()
    assert pd.to_datetime(actuals["actual_available_at"], errors="coerce").notna().all()
    assert actuals["release_source_url"].ne(actuals["source_url"]).any()
    assert actuals.loc[actuals["year"].eq(2025), "actual_available_at"].iloc[0] == "2025-08-14"
    assert actuals.loc[actuals["year"].eq(2022), "h1_actual_transport_ops_revenue_hkdm"].iloc[0] == 5815.0
    assert actuals.loc[actuals["year"].eq(2025), "h1_actual_transport_ops_revenue_hkdm"].iloc[0] == 11509.0
    assert annual[2024] == 23013.0
    assert annual[2025] == 23595.0
    assert 2026 not in annual


def test_default_immigration_input_uses_local_snapshot_without_fetch():
    traffic = mtr._load_immd_daily_traffic(False)
    assert not traffic.empty
    assert traffic["date"].notna().all()
    assert traffic["mtr_cross_boundary_total"].ge(0).all()


def test_immigration_loader_falls_back_from_invalid_latest_snapshot(monkeypatch, tmp_path):
    good = tmp_path / "immd_daily_traffic_20260101_000000.csv"
    bad = tmp_path / "immd_daily_traffic_20260102_000000.csv"
    source = pd.DataFrame(
        [
            {
                "Date": "01-01-2026",
                "Arrival / Departure": "Arrival",
                "Control Point": "Lo Wu",
                "Hong Kong Residents": 10,
                "Mainland Visitors": 20,
                "Other Visitors": 1,
                "Total": 31,
            }
        ]
    )
    source.to_csv(good, index=False)
    bad.write_text("not,a,valid,snapshot\n", encoding="utf-8")
    monkeypatch.setattr(mtr, "IMMD_RAW_DIR", str(tmp_path))
    traffic = mtr._load_immd_daily_traffic(False)
    assert len(traffic) == 1
    assert traffic.iloc[0]["mtr_cross_boundary_total"] == 31


def test_h1_backtest_has_2025_oos_and_2026_forecast_only():
    _, h1_actuals = mtr._load_transport_ops_actuals()
    h1, metrics = mtr._h1_backtest(_build_monthly(), h1_actuals)

    row_2025 = h1[h1["year"].eq(2025)].iloc[0]
    row_2026 = h1[h1["year"].eq(2026)].iloc[0]

    assert row_2025["backtest_role"] == "practical_forward_validation"
    assert row_2025["h1_actual_transport_ops_revenue_hkdm"] == pytest.approx(11509.0)
    assert row_2025["h1_model_revenue_hkdm"] == pytest.approx(11548.02, rel=1e-4)
    assert row_2025["model_error_pct"] == pytest.approx(0.339, rel=1e-2)
    assert row_2026["backtest_role"] == "current_forecast"
    assert pd.isna(row_2026["h1_actual_transport_ops_revenue_hkdm"])
    assert row_2026["actual_status"] == "not_yet_reported"
    assert metrics["oos_2025_error_pct"] == pytest.approx(0.339, rel=1e-2)
    assert metrics["structural_replay_mape_2019_2023"] == pytest.approx(5.99, rel=1e-2)


def test_h1_backtest_does_not_crash_when_2025_actual_is_unavailable():
    _, h1_actuals = mtr._load_transport_ops_actuals()
    h1_actuals = h1_actuals.loc[h1_actuals["year"].ne(2025)].copy()
    _, metrics = mtr._h1_backtest(_build_monthly(), h1_actuals)
    assert pd.isna(metrics["oos_2025_error_pct"])
