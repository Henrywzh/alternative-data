import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "apps/asia-markets-dashboard/scripts/build_hk_real_estate_artifact.py"
)
SPEC = importlib.util.spec_from_file_location("hk_real_estate_dashboard_export", SCRIPT_PATH)
dashboard_export = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = dashboard_export
SPEC.loader.exec_module(dashboard_export)


NOW = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)


def _frame(dates, column, base, step, *, provisional=False):
    result = pd.DataFrame(
        {
            "date": [date.strftime("%Y-%m-%d") for date in dates],
            column: [base + index * step for index in range(len(dates))],
        }
    )
    if provisional:
        result["is_provisional"] = False
        result.loc[result.index[-1], "is_provisional"] = True
    return result


def _frames():
    weekly_ccl = pd.date_range(end="2026-07-19", periods=1_100, freq="W-SUN")
    weekly_mhpi = pd.date_range(end="2026-07-20", periods=450, freq="W-MON")
    weekly_confidence = pd.date_range(end="2026-07-20", periods=350, freq="W-MON")
    monthly = pd.date_range(end="2026-06-01", periods=360, freq="MS")
    return {
        "ccl": _frame(weekly_ccl, "ccl_index", 70, 0.05),
        "mhpi": _frame(weekly_mhpi, "mhpi_overall", 100, 0.04),
        "confidence": _frame(weekly_confidence, "confidence_index", 45, 0.02),
        "rvd_price": _frame(monthly, "overall", 120, 0.3, provisional=True),
        "rvd_rent": _frame(monthly, "overall", 90, 0.2, provisional=True),
    }


def _hkma_frame(n=6):
    dates = pd.date_range(end="2026-06-01", periods=n, freq="MS")
    return pd.DataFrame(
        {
            "observation_date": [d.strftime("%Y-%m-%d") for d in dates],
            "new_applications_count": [10_000 + i * 50 for i in range(n)],
            "approved_loans_amount_mhkd": [30_000 + i * 100 for i in range(n)],
            "approved_primary_presales_amount_mhkd": [8_000 + i * 20 for i in range(n)],
            "approved_secondary_amount_mhkd": [15_000 + i * 30 for i in range(n)],
            "approved_refinancing_amount_mhkd": [5_000 + i * 10 for i in range(n)],
            "drawn_down_amount_mhkd": [25_000 + i * 80 for i in range(n)],
            "average_ltv_ratio_pct": [55.0 + i * 0.1 for i in range(n)],
            "hibor_pricing_pct_share": [70.0 + i for i in range(n)],
            "blr_pricing_pct_share": [10.0 - i * 0.1 for i in range(n)],
            "fixed_pricing_pct_share": [20.0 - i * 0.9 for i in range(n)],
            "delinquency_ratio_pct": [0.03 + i * 0.001 for i in range(n)],
            "rescheduled_loan_ratio_pct": [0.0 for _ in range(n)],
        }
    )


def _cnsd_frame(n=8):
    dates = pd.date_range(end="2026-03-31", periods=n, freq="QE")
    return pd.DataFrame(
        {
            "period": [f"{d.year}-Q{(d.month - 1) // 3 + 1}" for d in dates],
            "value": [50_000 + i * 500 for i in range(n)],
            "unit": ["HK$ million"] * n,
        }
    )


def test_build_artifact_is_source_backed_and_deterministic():
    first, first_status = dashboard_export.build_artifact(_frames(), raw_hkma=_hkma_frame(), raw_cnsd=_cnsd_frame(), now=NOW)
    second, second_status = dashboard_export.build_artifact(_frames(), raw_hkma=_hkma_frame(), raw_cnsd=_cnsd_frame(), now=NOW)

    assert first_status["snapshot_id"] == second_status["snapshot_id"]
    assert first_status["data_as_of"] == "2026-07-20"
    assert first["snapshot"]["status"] == "ready"
    assert first["snapshot"]["datasets"]["kpi_ccl"][0]["latest"] > 0
    assert first["snapshot"]["datasets"]["kpi_rvd_price"][0]["is_provisional"] is True
    assert len(first["snapshot"]["datasets"]["source_health"]) == 5
    # 6dd3693 wired up the two sources that used to carry "Planned" (28Hse,
    # Land Registry) into live data; SRPE is the one remaining non-live
    # source, and its status has always been "Catalog only", not "Planned".
    assert any(row["status"] == "Catalog only" for row in first["snapshot"]["datasets"]["source_coverage"])


def test_rebased_series_start_at_100():
    artifact, _ = dashboard_export.build_artifact(_frames(), raw_hkma=_hkma_frame(), raw_cnsd=_cnsd_frame(), now=NOW)
    rows = artifact["snapshot"]["datasets"]["rebased_five_year"]
    first_by_series = {}
    for row in rows:
        first_by_series.setdefault(row["series"], row["value"])
    assert set(first_by_series) == {"CCL", "MHPI", "RVD Price", "RVD Rent"}
    assert all(value == pytest.approx(100.0) for value in first_by_series.values())


def test_artifact_contains_no_machine_local_paths_or_secrets():
    artifact, _ = dashboard_export.build_artifact(_frames(), raw_hkma=_hkma_frame(), raw_cnsd=_cnsd_frame(), now=NOW)
    serialized = json.dumps(artifact)
    assert "/Users/" not in serialized
    assert "api_key" not in serialized.lower()
    assert ".config" not in serialized
    assert all(source.get("query", {}).get("url", "").startswith("https://") for source in artifact["sources"] if source.get("query", {}).get("url"))


def test_stale_or_duplicate_core_series_fails_closed():
    frames = _frames()
    frames["ccl"].loc[frames["ccl"].index[-1], "date"] = frames["ccl"].iloc[-2]["date"]
    with pytest.raises(ValueError, match="duplicate observation dates"):
        dashboard_export.build_artifact(frames, raw_hkma=_hkma_frame(), raw_cnsd=_cnsd_frame(), now=NOW)


def test_rvd_price_and_rent_must_align():
    frames = _frames()
    frames["rvd_rent"].loc[frames["rvd_rent"].index[-1], "date"] = "2026-07-01"
    with pytest.raises(ValueError, match="RVD price and rent observation dates do not align"):
        dashboard_export.build_artifact(frames, raw_hkma=_hkma_frame(), raw_cnsd=_cnsd_frame(), now=NOW)
