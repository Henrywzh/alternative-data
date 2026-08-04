import sys

import pytest
import pandas as pd
from src.hk_population_migration.sources.immd_daily_traffic import fetch_immd_daily_traffic
from src.hk_population_migration.sources.csd_population import fetch_csd_population_estimates
from src.hk_population_migration.sources.mpfa_claims import fetch_mpfa_permanent_departure_claims
from src.hk_population_migration.sources.ugc_students import fetch_ugc_nonlocal_students
from src.hk_population_migration.sources.td_cross_border import fetch_td_cross_border_traffic
from src.hk_population_migration.sources.ia_premiums import fetch_ia_mainland_visitor_premiums
from src.hk_population_migration.pipeline import run_stage_1_pipeline
from src.hk_population_migration import cli as cli_mod
from src.hk_population_migration import pipeline as pipeline_mod
from src.hk_population_migration import storage as storage_mod


def test_immd_daily_traffic_fetch():
    df = fetch_immd_daily_traffic()
    assert isinstance(df, pd.DataFrame)
    if not df.empty:
        assert "date" in df.columns
        assert "hk_resident_net_flow" in df.columns
        assert "mainland_visitor_net_retention" in df.columns


def test_csd_population_estimates_fetch():
    # Hits the live censtatd.gov.hk API with no offline fixture path and
    # honestly returns an empty frame on network failure rather than
    # fabricating data. A transient failure of that external site is not a
    # code regression.
    df = fetch_csd_population_estimates()
    assert isinstance(df, pd.DataFrame)
    if df.empty:
        pytest.skip("C&SD population estimates live API unavailable (network fetch failed, not a code regression)")


def test_mpfa_claims_fetch():
    df = fetch_mpfa_permanent_departure_claims()
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "claims_count" in df.columns


def test_ugc_students_fetch():
    df = fetch_ugc_nonlocal_students()
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "mainland_students" in df.columns


def test_td_cross_border_fetch():
    df = fetch_td_cross_border_traffic()
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "hzmb_northbound_hk_vehicles" in df.columns


def test_ia_premiums_fetch_returns_empty_not_fabricated():
    """The regulator suspended this series (every release since Q1 2025 is
    under review); there is no real substitute source. This must stay empty
    rather than silently reintroducing invented quarters."""
    df = fetch_ia_mainland_visitor_premiums()
    assert isinstance(df, pd.DataFrame)
    assert df.empty
    assert list(df.columns) == ["quarter", "mainland_visitor_premium_mhkd", "share_of_total_new_office_pct"]


def test_run_stage_1_pipeline():
    results = run_stage_1_pipeline()
    assert isinstance(results, dict)
    assert "immd_daily_traffic" in results
    assert "csd_population_estimates" in results
    assert "mpfa_departure_claims" in results
    assert "ugc_nonlocal_students" in results
    assert "td_cross_border_traffic" in results
    assert "ia_mainland_visitor_premiums" in results


def test_stage_1_persists_normalized_runs_and_excludes_unused_visitor_departures(monkeypatch, tmp_path):
    normalized_dir = tmp_path / "normalized"
    monkeypatch.setattr(storage_mod, "NORMALIZED_DIR", normalized_dir)

    frames = {
        "immd_daily_traffic": pd.DataFrame({"date": ["2026-07-29"], "hk_resident_net_flow": [1]}),
        "csd_population_estimates": pd.DataFrame({"period": ["2025-12"], "mid_year_population_thousands": [7540]}),
        "mpfa_departure_claims": pd.DataFrame({"quarter": ["2026-Q1"], "claims_count": [1]}),
        "ugc_nonlocal_students": pd.DataFrame({"academic_year": ["2025/26"], "mainland_students": [1]}),
        "td_cross_border_traffic": pd.DataFrame({"month": ["2026-05"], "hzmb_vehicular_traffic": [1]}),
    }
    for name, frame in frames.items():
        frame.attrs["source_url"] = f"https://example.com/{name}"

    monkeypatch.setattr(pipeline_mod, "fetch_immd_daily_traffic", lambda: frames["immd_daily_traffic"])
    monkeypatch.setattr(pipeline_mod, "fetch_csd_population_estimates", lambda: frames["csd_population_estimates"])
    monkeypatch.setattr(pipeline_mod, "fetch_mpfa_permanent_departure_claims", lambda: frames["mpfa_departure_claims"])
    monkeypatch.setattr(pipeline_mod, "fetch_ugc_nonlocal_students", lambda: frames["ugc_nonlocal_students"])
    monkeypatch.setattr(pipeline_mod, "fetch_td_cross_border_traffic", lambda: frames["td_cross_border_traffic"])
    monkeypatch.setattr(pipeline_mod, "fetch_ia_mainland_visitor_premiums", lambda: pd.DataFrame())

    results = pipeline_mod.run_stage_1_pipeline()

    assert set(frames).issubset(results)
    assert "csd_visitor_departures" not in results
    for dataset_name, expected in frames.items():
        restored = storage_mod.load_latest_normalized(dataset_name)
        assert restored.to_dict(orient="records") == expected.to_dict(orient="records")


def test_cli_requires_explicit_run_flag(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["hk_population_migration"])
    with pytest.raises(SystemExit) as exc_info:
        cli_mod.main()
    assert exc_info.value.code == 2
