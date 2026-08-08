from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = ROOT / "data" / "normalized" / "hk_transport"
PROCESSED = ROOT / "data" / "processed" / "airline_traffic"


def test_airline_pit_layers_have_unique_keys_and_complete_lineage() -> None:
    kpi = pd.read_parquet(PROCESSED / "china_airlines_monthly.parquet")
    key = ["airline_code", "month", "metric", "region"]
    assert kpi.duplicated(key).sum() == 0
    required = ["announcement_date", "announcement_id", "source_pdf_url", "source_quality", "retrieved_at"]
    assert kpi[required].notna().all().all()

    registry = pd.read_csv(TRANSPORT / "airline_operating_release_registry.csv")
    assert registry.duplicated(["airline_code", "month"]).sum() == 0
    assert registry["announcement_date"].notna().all()

    official = pd.read_csv(TRANSPORT / "airline_official_report_drivers.csv")
    assert official.duplicated(["ticker", "statement_period", "metric"]).sum() == 0
    assert official[["source_page", "source_url"]].notna().all().all()

    filing_watch = pd.read_csv(TRANSPORT / "airline_official_filing_watch.csv")
    assert filing_watch.duplicated(["ticker", "snapshot_date"]).sum() == 0
    assert len(filing_watch.loc[filing_watch["snapshot_date"].eq(filing_watch["snapshot_date"].max())]) == 6
    assert filing_watch["scheduled_date"].notna().all()
    assert filing_watch["source_quality"].eq("cninfo_official_query").all()


def test_airline_derived_layers_preserve_coverage_and_scope_guards() -> None:
    bridge = pd.read_csv(TRANSPORT / "airline_expectation_bridge.csv")
    assert bridge.duplicated("market_ticker").sum() == 0
    assert bridge["formal_report_status"].notna().all()

    sector = pd.read_csv(TRANSPORT / "airline_sector_expectation_snapshot.csv")
    aggregate = sector.loc[sector["scope_type"].eq("sector_aggregate")].iloc[0]
    assert aggregate["company_count"] == 6
    assert aggregate["latest_report_revenue_coverage_n"] == 6
    assert aggregate["latest_report_profit_coverage_n"] == 6
    assert aggregate["fy2026_revenue_consensus_coverage_n"] == 6

    cathay = sector.loc[sector["ticker"].eq("0293.HK")].iloc[0]
    assert cathay["native_currency"] == "HKD"
    assert pd.isna(cathay["fy2026_revenue_growth_vs_latest_actual_pct"])
    assert pd.isna(cathay["fy2026_net_profit_delta_vs_latest_actual_native_mn"])


def test_energy_and_fx_observation_grains_are_unique() -> None:
    energy = pd.read_parquet(TRANSPORT / "airline_energy_prices.parquet")
    fx = pd.read_parquet(TRANSPORT / "airline_fx_rates.parquet")

    # Daily and weekly EIA observations can share a calendar date; frequency
    # is therefore part of the natural key rather than a duplicate.
    assert energy.duplicated(["frequency", "series_id", "observation_date"]).sum() == 0
    assert fx.duplicated(["pair", "observation_date"]).sum() == 0


def test_consensus_layers_preserve_point_in_time_order_and_coverage_labels() -> None:
    ashare_consensus = pd.read_csv(TRANSPORT / "airline_consensus_ashare_snapshot.csv")
    detailed_consensus = pd.read_csv(TRANSPORT / "airline_consensus_ashare_detailed.csv")
    mainland_forecasts = pd.read_csv(TRANSPORT / "airline_sell_side_revenue_forecasts.csv")
    mainland_revisions = pd.read_csv(TRANSPORT / "airline_sell_side_revenue_revisions.csv")
    hk_forecasts = pd.read_csv(TRANSPORT / "airline_hk_sell_side_forecasts.csv")
    hk_revisions = pd.read_csv(TRANSPORT / "airline_hk_forecast_revisions.csv")

    latest_consensus_date = ashare_consensus["snapshot_date"].max()
    latest_consensus = ashare_consensus.loc[ashare_consensus["snapshot_date"].eq(latest_consensus_date)]
    latest_detailed_date = detailed_consensus["snapshot_date"].max()
    latest_detailed = detailed_consensus.loc[detailed_consensus["snapshot_date"].eq(latest_detailed_date)]
    assert len(latest_consensus) == 36
    assert latest_consensus["company"].nunique() == 6
    assert ashare_consensus.duplicated(["ticker", "snapshot_date", "fiscal_year", "metric"]).sum() == 0
    assert len(latest_detailed) == 108
    assert latest_detailed["company"].nunique() == 6
    assert detailed_consensus.duplicated(["ticker", "snapshot_date", "fiscal_year", "metric"]).sum() == 0

    assert len(mainland_forecasts) == 95
    assert len(mainland_revisions) == 95
    assert mainland_forecasts[["report_date", "source_page", "report_url"]].notna().all().all()
    mainland_prior = mainland_revisions[mainland_revisions["prior_report_date"].notna()].copy()
    assert len(mainland_prior) == 48
    assert (pd.to_datetime(mainland_prior["prior_report_date"]) < pd.to_datetime(mainland_prior["report_date"])).all()

    assert len(hk_forecasts) >= 82
    assert hk_forecasts[["report_date", "institution", "fiscal_year", "source_url"]].notna().all().all()
    hk_prior = hk_revisions[hk_revisions["prior_report_date"].notna()].copy()
    if not hk_prior.empty:
        assert (pd.to_datetime(hk_prior["prior_report_date"]) < pd.to_datetime(hk_prior["report_date"])).all()


def test_airline_research_layers_use_canonical_eastern_ticker() -> None:
    """Prevent a legacy 00670.HK alias from breaking cross-layer joins."""
    paths = [
        "airline_consensus_ashare_snapshot.csv",
        "airline_consensus_ashare_detailed.csv",
        "airline_consensus_em_snapshot.csv",
        "airline_consensus_dispersion_all.csv",
        "airline_consensus_freshness.csv",
        "airline_cninfo_rating_events.csv",
        "airline_revision_evidence.csv",
        "airline_earnings_driver_comparability.csv",
        "airline_filing_calendar.csv",
        "airline_financial_actuals_akshare_snapshot.csv",
        "airline_news_events.csv",
        "airline_official_report_drivers.csv",
        "airline_official_report_registry.csv",
        "airline_hedging_disclosures.csv",
        "airline_official_filing_watch.csv",
        "airline_yahoo_analyst_snapshot.csv",
        "airline_sell_side_forecast_revisions.csv",
        "airline_sell_side_reports_akshare_snapshot.csv",
        "airline_public_report_evidence.csv",
        "airline_short_eligibility.csv",
        "airline_hk_short_positions.csv",
        "airline_sell_side_revenue_forecasts.csv",
        "airline_sell_side_revenue_revisions.csv",
    ]
    for filename in paths:
        frame = pd.read_csv(TRANSPORT / filename)
        ticker_columns = [column for column in frame.columns if "ticker" in column.lower()]
        for column in ticker_columns:
            assert not frame[column].astype(str).str.contains("00670\\.HK", regex=True).any(), (filename, column)
