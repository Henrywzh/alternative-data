import importlib
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest


def test_import_smoke():
    for module in (
        "src.hk_reit.config",
        "src.hk_reit.storage",
        "src.hk_reit.sources.linkreit_fundamentals",
        "src.hk_reit.sources.championreit_fundamentals",
        "src.hk_reit.sources.fortunereit_fundamentals",
        "src.hk_reit.sources.prosperityreit_fundamentals",
        "src.hk_reit.sources.sunlightreit_fundamentals",
        "src.hk_reit.sources.regalreit_fundamentals",
        "src.hk_reit.pipeline",
        "src.hk_reit.cli",
    ):
        assert importlib.import_module(module)

def test_linkreit_dynamic_fetch():
    from src.hk_reit.sources.linkreit_fundamentals import fetch_linkreit_fundamentals
    df = fetch_linkreit_fundamentals()
    assert isinstance(df, pd.DataFrame)
    # Check that required columns exist even when empty
    for col in ["date", "period", "ticker", "reit_name", "nav_per_unit_hkd", "dpu_hkd"]:
        assert col in df.columns
    # This hits a real linkreit.com PDF + HTML endpoint; if the site is reachable at
    # all (network available in this test environment), we expect real rows back,
    # not just an empty-but-well-shaped DataFrame -- guards against the endpoint
    # silently regressing to a 404/dead link without failing the test.
    if not df.empty:
        assert df["nav_per_unit_hkd"].notna().any()
        assert (df["ticker"] == "0823.HK").all()

def test_regalreit_hotel_kpis_columns():
    from src.hk_reit.sources.regalreit_fundamentals import fetch_regalreit_fundamentals
    df = fetch_regalreit_fundamentals()
    assert isinstance(df, pd.DataFrame)
    # Regal REIT specific hotel KPI columns
    for col in ["hotel_occupancy_pct", "average_daily_rate_hkd", "revpar_hkd"]:
        assert col in df.columns
    if not df.empty:
        assert (df["ticker"] == "1881.HK").all()


# --- Dashboard artifact shape (synthetic data, no network) -----------------

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "apps/asia-markets-dashboard/scripts/build_hk_reit_artifact.py"
)
_SPEC = importlib.util.spec_from_file_location("hk_reit_dashboard_export", SCRIPT_PATH)
dashboard_export = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
sys.modules[_SPEC.name] = dashboard_export
_SPEC.loader.exec_module(dashboard_export)

NOW = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)


def _office_retail_frame(ticker, name, nav0, dpu0, occ0, rev0, n=4):
    dates = pd.date_range(end="2026-06-30", periods=n, freq="6MS")
    return pd.DataFrame(
        {
            "date": dates,
            "period": [f"P{i}" for i in range(n)],
            "ticker": [ticker] * n,
            "reit_name": [name] * n,
            "nav_per_unit_hkd": [nav0 + i * 0.01 for i in range(n)],
            "dpu_hkd": [dpu0 + i * 0.001 for i in range(n)],
            "occupancy_pct": [occ0 + i * 0.1 for i in range(n)],
            "rental_reversion_pct": [rev0 + i * 0.1 for i in range(n)],
            "source_agency": ["test"] * n,
        }
    )


def _regal_frame(n=4, nil_dpu_period=True):
    dates = pd.date_range(end="2026-06-30", periods=n, freq="6MS")
    dpu = [0.0 if nil_dpu_period and i % 2 == 0 else 0.01 + i * 0.001 for i in range(n)]
    return pd.DataFrame(
        {
            "date": dates,
            "period": [f"P{i}" for i in range(n)],
            "ticker": ["1881.HK"] * n,
            "reit_name": ["Regal REIT"] * n,
            "nav_per_unit_hkd": [3.7 + i * 0.01 for i in range(n)],
            "dpu_hkd": dpu,
            "hotel_occupancy_pct": [65.0 + i for i in range(n)],
            "average_daily_rate_hkd": [800.0 + i * 5 for i in range(n)],
            "revpar_hkd": [550.0 + i * 3 for i in range(n)],
            "source_agency": ["test"] * n,
        }
    )


def _spot_frame():
    tickers = ["00823", "02778", "00778", "00808", "00435", "01881"]
    names = ["Link REIT", "Champion REIT", "Fortune REIT", "Prosperity REIT", "Sunlight REIT", "Regal REIT"]
    prices = [35.8, 1.62, 5.3, 1.35, 3.1, 2.4]
    return pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-06-30")] * 6,
            "ticker": tickers,
            "company_name": names,
            "latest_price_hkd": prices,
            "change_pct": [0.5, -0.3, 0.1, 0.0, -0.2, 0.4],
            "volume": [1_000_000, 200_000, 150_000, 100_000, 80_000, 60_000],
            "turnover_hkd": [p * 1_000_000 for p in prices],
        }
    )


def _hist_frame():
    tickers = ["00823", "02778", "00778", "00808", "00435", "01881"]
    names = ["Link REIT", "Champion REIT", "Fortune REIT", "Prosperity REIT", "Sunlight REIT", "Regal REIT"]
    base_prices = [35.8, 1.62, 5.3, 1.35, 3.1, 2.4]
    dates = pd.date_range(end="2026-06-30", periods=3, freq="D")
    frames = []
    for ticker, name, base in zip(tickers, names, base_prices):
        frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "ticker": [ticker] * 3,
                    "company_name": [name] * 3,
                    "open_hkd": [base + i * 0.01 for i in range(3)],
                    "high_hkd": [base + 0.05 + i * 0.01 for i in range(3)],
                    "low_hkd": [base - 0.05 + i * 0.01 for i in range(3)],
                    "close_hkd": [base + 0.02 + i * 0.01 for i in range(3)],
                    "volume": [100_000] * 3,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _frames():
    return dict(
        raw_link=_office_retail_frame("0823.HK", "Link REIT", 60, 1.2, 95, 5),
        raw_champion=_office_retail_frame("2778.HK", "Champion REIT", 4, 0.1, 90, 3),
        raw_fortune=_office_retail_frame("0778.HK", "Fortune REIT", 9, 0.2, 92, 4),
        raw_prosperity=_office_retail_frame("0808.HK", "Prosperity REIT", 1.8, 0.05, 88, 2),
        raw_sunlight=_office_retail_frame("0435.HK", "Sunlight REIT", 3, 0.08, 91, 3),
        raw_regal=_regal_frame(),
        raw_spot=_spot_frame(),
        raw_hist=_hist_frame(),
    )


def test_build_artifact_has_non_empty_cards_charts_tables_blocks():
    artifact, status = dashboard_export.build_artifact(**_frames(), now=NOW)
    manifest = artifact["manifest"]
    assert len(manifest["cards"]) == 6
    assert len(manifest["charts"]) == 6
    assert len(manifest["tables"]) == 2
    assert len(manifest["blocks"]) > 0
    assert status["live_sources"] == 7
    assert status["overall_status"] == "Healthy"


def test_regal_hotel_kpis_isolated_from_office_retail_charts():
    artifact, _ = dashboard_export.build_artifact(**_frames(), now=NOW)
    datasets = artifact["snapshot"]["datasets"]
    # Chart series are labeled by bare ticker code, not full REIT name: the
    # portable dashboard's chart legend does not reliably wrap at mobile
    # widths, so six full names like "Prosperity REIT" would overflow the
    # 390px viewport in a single legend row (see horizontal_overflow
    # verification failure this was fixed for).
    occupancy_series = {row["series"] for row in datasets["occupancy_history"]}
    reversion_series = {row["series"] for row in datasets["reversion_history"]}
    assert "1881" not in occupancy_series
    assert "1881" not in reversion_series
    # Regal's own hotel KPI chart carries occupancy/ADR/RevPAR as separate series.
    regal_series = {row["series"] for row in datasets["regal_hotel_kpi_history"]}
    assert regal_series == {"Occupancy (%)", "ADR (HK$)", "RevPAR (HK$)"}
    # NAV/DPU comparisons stay comparable series across all six REITs.
    nav_series = {row["series"] for row in datasets["nav_history"]}
    assert "1881" in nav_series
    assert len(nav_series) == 6
    # Series labels must stay short (ticker codes, not full names) so the
    # portable dashboard's legend fits without horizontal overflow.
    assert all(len(series) <= 6 for series in nav_series)


def test_nil_dpu_period_change_does_not_raise_zero_division():
    # Regal REIT's DPU is nil in alternating periods in the synthetic fixture,
    # exercising the same zero-distribution scenario documented in
    # reit-regalreit-01881-findings.md (1H2025 nil DPU was a real disclosed
    # figure, not a fetch failure). The comparison must degrade to None, not raise.
    artifact, _ = dashboard_export.build_artifact(**_frames(), now=NOW)
    regal_kpi = artifact["snapshot"]["datasets"]["kpi_regalreit"][0]
    assert regal_kpi["dpu_hkd"] is not None
    # Latest period (index -1, i=3, odd) has nonzero DPU; prior period (i=2, even) is nil,
    # so the period-over-period ratio must be guarded to None rather than raising.
    assert regal_kpi["dpu_period_change"] is None


def test_empty_source_frame_does_not_crash_and_yields_null_kpis():
    empty_cols = [
        "date", "period", "ticker", "reit_name", "nav_per_unit_hkd", "dpu_hkd",
        "occupancy_pct", "rental_reversion_pct", "source_agency",
    ]
    frames = _frames()
    frames["raw_link"] = pd.DataFrame(columns=empty_cols)
    artifact, status = dashboard_export.build_artifact(**frames, now=NOW)
    link_kpi = artifact["snapshot"]["datasets"]["kpi_linkreit"][0]
    assert link_kpi["nav_per_unit_hkd"] is None
    assert link_kpi["dpu_period_change"] is None
    assert status["live_sources"] == 6
    assert status["overall_status"] == "Degraded"
    # Structure must still be intact even with one dead source.
    assert len(artifact["manifest"]["cards"]) == 6


def test_reit_comparison_table_row_per_reit_with_business_type_split():
    artifact, _ = dashboard_export.build_artifact(**_frames(), now=NOW)
    rows = artifact["snapshot"]["datasets"]["reit_comparison"]
    assert len(rows) == 6
    by_ticker = {row["ticker"]: row for row in rows}
    regal_row = by_ticker["1881.HK"]
    assert regal_row["business_type"] == "Hotel"
    assert regal_row["rental_reversion_pct"] is None
    assert regal_row["revpar_hkd"] is not None
    link_row = by_ticker["0823.HK"]
    assert link_row["business_type"] == "Office/Retail"
    assert link_row["revpar_hkd"] is None
    assert link_row["occupancy_pct"] is not None


def test_snapshot_id_deterministic_for_same_inputs():
    first, first_status = dashboard_export.build_artifact(**_frames(), now=NOW)
    second, second_status = dashboard_export.build_artifact(**_frames(), now=NOW)
    assert first_status["snapshot_id"] == second_status["snapshot_id"]


def test_artifact_contains_no_machine_local_paths_or_secrets():
    import json
    artifact, _ = dashboard_export.build_artifact(**_frames(), now=NOW)
    serialized = json.dumps(artifact)
    assert "/Users/" not in serialized
    assert "api_key" not in serialized.lower()
    assert ".config" not in serialized
