"""CLI for HK Transport Sector Pipeline."""

from __future__ import annotations

import argparse

from .pipeline import run_stage_1_pipeline
from .sources.cathay_traffic import fetch_cathay_traffic
from .sources.censtatd_boundary_movements import fetch_censtatd_boundary_movements
from .sources.mttd_passenger_journeys import fetch_mttd_passenger_journeys
from .sources.td_carpark_occupancy import fetch_td_carpark_occupancy
from .sources.td_first_registered_vehicle_details import fetch_td_first_registered_vehicle_details
from .sources.td_parking_vacancy import fetch_td_parking_vacancy
from .sources.td_private_car_first_reg import fetch_td_private_car_first_reg
from .sources.td_private_car_net_registration import fetch_td_private_car_net_registration
from .sources.td_vehicle_fleet_stock import fetch_td_vehicle_fleet_stock
from .sources.mtr_patronage import fetch_mtr_patronage
from .sources.energy_prices import fetch_eia_airline_energy_prices
from .sources.fuel_surcharge import fetch_fuel_surcharge_snapshots
from .sources.fx_rates import fetch_ecb_airline_fx_rates
from .sources.airline_financials import fetch_a_share_airline_financial_layers
from .sources.airline_financial_history import fetch_airline_financial_history
from .sources.airline_historical_earnings_bridge import fetch_airline_historical_earnings_bridge
from .sources.airline_pair_historical_bridge import fetch_airline_pair_historical_bridge
from .sources.airline_pair_scenarios import fetch_airline_pair_scenario_inputs
from .sources.airline_primary_financial_reconciliation import fetch_airline_primary_financial_reconciliation
from .sources.airline_core_pair_model import fetch_airline_core_pair_model_inputs
from .sources.airline_public_report_evidence import fetch_airline_public_report_evidence
from .sources.airline_revenue_consensus import fetch_airline_revenue_consensus
from .sources.airline_expectation_bridge import fetch_airline_expectation_bridge
from .sources.airline_sell_side_revenue import fetch_sell_side_revenue_layers
from .sources.cathay_annual_drivers import fetch_cathay_annual_drivers
from .sources.cathay_interim_drivers import fetch_cathay_interim_drivers
from .sources.airline_fuel_sensitivity import fetch_fuel_sensitivity_scenarios
from .sources.airline_filing_calendar import fetch_airline_filing_calendar
from .sources.airline_official_filing_watch import fetch_airline_official_filing_watch
from .sources.airline_market_snapshot import fetch_airline_market_snapshot
from .sources.airline_hk_consensus import fetch_hk_airline_consensus
from .sources.airline_sector_trends import fetch_airline_sector_trends
from .sources.airline_sector_expectations import fetch_airline_sector_expectation_snapshot
from .sources.cathay_sector_trends import fetch_cathay_sector_trends
from .sources.airline_official_reports import fetch_official_airline_report_drivers
from .sources.airline_hedging_disclosures import fetch_airline_hedging_disclosures
from .sources.airline_consensus_freshness import fetch_airline_consensus_freshness
from .sources.airline_consensus_dispersion import fetch_airline_consensus_dispersion
from .sources.airline_earnings_drivers import fetch_airline_earnings_driver_comparability
from .sources.airline_consensus_em import fetch_airline_consensus_em
from .sources.airline_cninfo_rating_events import fetch_cninfo_rating_events
from .sources.airline_revision_coverage import fetch_airline_revision_coverage
from .sources.airline_pair_readiness import fetch_airline_pair_readiness
from .sources.airline_news_events import fetch_airline_news_events
from .sources.airline_research_chain import fetch_airline_research_chain
from .sources.airline_consensus_dispersion_all import fetch_airline_consensus_dispersion_all
from .sources.airline_market_risk import fetch_airline_market_risk_metrics
from .sources.airline_pair_risk import fetch_airline_pair_risk_metrics
from .sources.airline_consensus_events import fetch_airline_consensus_events
from .sources.airline_consensus_revision_pulse import fetch_airline_consensus_revision_pulse
from .sources.airline_revision_evidence import fetch_airline_revision_evidence
from .sources.airline_revenue_consensus_coverage import fetch_airline_revenue_consensus_coverage
from .sources.airline_guidance_coverage import fetch_airline_guidance_coverage
from .sources.airline_sector_external_outlook import fetch_airline_sector_external_outlook
from .sources.airline_pair_screening import fetch_airline_pair_screening_matrix
from .sources.airline_factor_diagnostics import fetch_airline_pair_factor_diagnostics
from .sources.airline_yahoo_analyst_snapshot import fetch_airline_yahoo_analyst_snapshot
from .sources.airline_data_completeness import fetch_airline_data_completeness
from .sources.airline_operating_freshness import fetch_airline_operating_freshness
from .sources.airline_operating_diagnostics import fetch_airline_operating_diagnostics
from .sources.airline_short_side_proxies import fetch_airline_short_side_proxies
from .sources.airline_short_eligibility import fetch_airline_short_eligibility
from .sources.airline_hk_short_positions import fetch_airline_hk_short_positions
from .sources.airline_stock_connect_short_selling import fetch_airline_stock_connect_short_selling
from .sources.airline_hsr_enrichment import (
    fetch_12306_station_codes,
    fetch_airline_hsr_query_queue,
    fetch_ctrip_train_snapshot,
    run_airline_hsr_enrichment_pipeline,
    summarize_ctrip_route_observations,
)
from .sources.airline_route_capacity import build_airline_route_capacity_weights
from .sources.airline_pair_thesis_readiness import build_airline_pair_thesis_readiness
from .sources.airline_pre_h1_scenario_bridge import fetch_airline_pre_h1_scenario_bridge
from .sources.airline_forecast_risk_framework import fetch_airline_forecast_risk_framework
from .sources.airline_company_financial_forecast import fetch_airline_company_financial_forecast_bridge
from .sources.airline_h1_claim_validation import fetch_airline_h1_claim_validation_queue
from .sources.airline_juneyao_9air_scope import fetch_airline_juneyao_9air_scope_reconciliation
from .sources.airline_yield_fuel_hsr_framework import fetch_airline_yield_fuel_hsr_framework
from .sources.airline_forward_earnings_bridge import fetch_airline_forward_earnings_and_pair_scorecard
from .sources.airline_pair_thesis_working_set import fetch_airline_pair_thesis_working_set
from .sources.airline_pair_trade_thesis import fetch_airline_pair_trade_thesis_scenarios
from .sources.airline_pair_valuation_factor_review import fetch_airline_pair_valuation_factor_review
from .sources.airline_valuation_peer_comparability import fetch_airline_valuation_peer_comparability
from .sources.airline_historical_pb_valuation import fetch_airline_historical_pb_valuation
from .sources.airline_pair_pb_trade_diagnostic import fetch_airline_pair_pb_trade_diagnostic
from .sources.airline_pair_risk_budget_sizing import fetch_airline_pair_risk_budget_sizing
from .sources.airline_pair_direction_decision import fetch_airline_pair_direction_decision
from .sources.airline_pair_target_range import fetch_airline_pair_target_range
from .sources.airline_pair_revision_confirmation import fetch_airline_pair_revision_confirmation
from .sources.airline_pair_event_trade_triggers import fetch_airline_pair_event_trade_triggers
from .sources.airline_pair_branch_thesis import fetch_airline_pair_branch_thesis


def main():
    parser = argparse.ArgumentParser(description="HK Transport Sector Alternative Data Pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("run-stage-1", help="Run Stage 1 ready-to-build ingestion")
    subparsers.add_parser("run-all", help="Run full pipeline across all sources")
    subparsers.add_parser("run-mtr", help="Run MTR patronage ingestion")
    subparsers.add_parser("run-cathay", help="Run Cathay & HKIA traffic ingestion")
    subparsers.add_parser("run-energy-prices", help="Run free EIA daily/weekly crude and jet-fuel ingestion")
    subparsers.add_parser("run-fuel-surcharges", help="Run official Cathay and mainland fuel-surcharge ingestion")
    subparsers.add_parser("run-fx-rates", help="Run free ECB USD/CNY and USD/HKD reference-rate ingestion")
    subparsers.add_parser(
        "run-airline-financials",
        help="Run free A-share airline actuals, consensus and sell-side discovery ingestion",
    )
    subparsers.add_parser(
        "run-airline-financial-history",
        help="Build the historical A-share financial trend layer with explicit PIT limitations",
    )
    subparsers.add_parser(
        "run-airline-historical-earnings-bridge",
        help="Align airline financial history, monthly operating KPIs, fuel/FX benchmarks and current consensus",
    )
    subparsers.add_parser(
        "run-airline-pair-historical-bridge",
        help="Build pair-level historical earnings differentials for thesis preparation",
    )
    subparsers.add_parser(
        "run-airline-pair-scenarios",
        help="Build transparent bear/base/bull scenario inputs from current FY2026 expectations",
    )
    subparsers.add_parser(
        "run-airline-pre-h1-scenario-bridge",
        help="Build the non-directional Spring/Juneyao pre-H1 actuals-consensus-fuel scenario bridge",
    )
    subparsers.add_parser(
        "run-airline-forecast-risk-framework",
        help="Build research-only sector/company forecast assumptions and risk-invalidation matrices",
    )
    subparsers.add_parser(
        "run-airline-company-financial-forecast",
        help="Build non-directional FY2026 airline driver-to-earnings forecast bridge",
    )
    subparsers.add_parser(
        "run-airline-h1-claim-validation",
        help="Build the formal 1H2026 claim-validation queue for airline research",
    )
    subparsers.add_parser(
        "run-airline-juneyao-9air-scope",
        help="Build the point-in-time Juneyao Group versus 9 Air scope reconciliation",
    )
    subparsers.add_parser(
        "run-airline-yield-fuel-hsr-framework",
        help="Build comparable yield/pricing, fuel/hedge, research-queue and HSR coverage layers",
    )
    subparsers.add_parser(
        "run-airline-forward-earnings-scorecard",
        help="Build the six-company forward earnings bridge and 21-pair research scorecard",
    )
    subparsers.add_parser(
        "run-airline-pair-thesis-working-set",
        help="Build the priority-pair thesis working set with valuation, catalysts and trade-risk fields",
    )
    subparsers.add_parser(
        "run-airline-pair-trade-thesis",
        help="Build provisional target/payoff and risk scenarios for priority airline pairs",
    )
    subparsers.add_parser(
        "run-airline-pair-valuation-factor-review",
        help="Stress provisional pair directions for valuation premium, factor gaps and market-scope mismatch",
    )
    subparsers.add_parser(
        "run-airline-valuation-peer-comparability",
        help="Build the peer-comparability and historical-valuation evidence gate for priority airline pairs",
    )
    subparsers.add_parser(
        "run-airline-historical-pb-valuation",
        help="Fetch dated public airline P/B history and build asset-value target diagnostics",
    )
    subparsers.add_parser(
        "run-airline-pair-pb-trade-diagnostic",
        help="Apply historical P/B percentile diagnostics to provisional priority-pair payoffs",
    )
    subparsers.add_parser(
        "run-airline-pair-risk-budget-sizing",
        help="Build direction-aware drawdown, factor and configurable loss-budget sizing diagnostics",
    )
    subparsers.add_parser(
        "run-airline-pair-direction-decision",
        help="Compare earnings-model and P/B directions and assign the provisional direction gate",
    )
    subparsers.add_parser(
        "run-airline-pair-target-range",
        help="Build transparent target/payoff ranges from earnings/P-S and historical P/B diagnostics",
    )
    subparsers.add_parser(
        "run-airline-pair-revision-confirmation",
        help="Build point-in-time consensus-revision confirmation for provisional pair directions",
    )
    subparsers.add_parser(
        "run-airline-pair-event-trade-triggers",
        help="Build conditional post-interim-event entry and invalidation triggers for priority pairs",
    )
    subparsers.add_parser(
        "run-airline-pair-branch-thesis",
        help="Build fundamental-resilience and valuation-mean-reversion branches for each priority pair",
    )
    subparsers.add_parser(
        "run-airline-primary-reconciliation",
        help="Reconcile provider financial history against covered primary issuer reports",
    )
    subparsers.add_parser(
        "run-airline-core-pair-model",
        help="Build compact Spring–Juneyao model inputs for thesis drafting",
    )
    subparsers.add_parser(
        "run-airline-public-report-evidence",
        help="Fetch structured public 10jqka institution forecast evidence",
    )
    subparsers.add_parser(
        "run-airline-revenue-consensus",
        help="Run free Yahoo Finance airline revenue-estimate discovery ingestion",
    )
    subparsers.add_parser(
        "run-airline-expectation-bridge",
        help="Build the derived airline demand-to-expectations research bridge",
    )
    subparsers.add_parser(
        "run-airline-sell-side-revenue",
        help="Extract dated revenue forecasts and revisions from public sell-side PDFs",
    )
    subparsers.add_parser(
        "run-cathay-annual-drivers",
        help="Run Cathay FY2025 official annual-report driver extraction",
    )
    subparsers.add_parser(
        "run-cathay-interim-drivers",
        help="Run Cathay 1H2026 official interim-report driver extraction",
    )
    subparsers.add_parser(
        "run-airline-fuel-sensitivity",
        help="Build airline fuel-price shock scenarios from reported cost/sensitivity data",
    )
    subparsers.add_parser(
        "run-airline-filing-calendar",
        help="Run public discovery ingestion for mainland airline interim-report dates",
    )
    subparsers.add_parser(
        "run-airline-official-filing-watch",
        help="Verify mainland airline interim-report announcements directly on CNINFO",
    )
    subparsers.add_parser(
        "run-airline-market-snapshot",
        help="Run current airline price and market-cap snapshot ingestion",
    )
    subparsers.add_parser(
        "run-airline-hk-consensus",
        help="Run dated Hong Kong airline broker forecast and revision ingestion",
    )
    subparsers.add_parser(
        "run-airline-sector-trends",
        help="Build H1 airline capacity, traffic, cargo and load-factor trend snapshot",
    )
    subparsers.add_parser(
        "run-airline-sector-expectations",
        help="Build company and mainland-sector expectation snapshot for long/short research",
    )
    subparsers.add_parser(
        "run-cathay-sector-trends",
        help="Build Cathay H1 capacity, traffic, cargo and load-factor trend snapshot",
    )
    subparsers.add_parser(
        "run-airline-official-reports",
        help="Run curated Cninfo annual/interim airline report driver extraction",
    )
    subparsers.add_parser(
        "run-airline-hedging-disclosures",
        help="Build point-in-time primary-report fuel-hedging disclosure coverage",
    )
    subparsers.add_parser(
        "run-airline-consensus-freshness",
        help="Build point-in-time consensus freshness and coverage contract",
    )
    subparsers.add_parser(
        "run-airline-consensus-dispersion",
        help="Build USD A/H consensus dispersion and reconciliation layer",
    )
    subparsers.add_parser(
        "run-airline-earnings-drivers",
        help="Build canonical airline earnings-driver comparability layer",
    )
    subparsers.add_parser(
        "run-airline-consensus-em",
        help="Run current free Eastmoney airline EPS and rating-count snapshot",
    )
    subparsers.add_parser(
        "run-airline-cninfo-ratings",
        help="Run dated Cninfo airline rating-event discovery layer",
    )
    subparsers.add_parser(
        "run-airline-revision-coverage",
        help="Build airline consensus and sell-side revision coverage summary",
    )
    subparsers.add_parser(
        "run-airline-pair-readiness",
        help="Build non-directional airline pair research readiness gate",
    )
    subparsers.add_parser(
        "run-airline-news",
        help="Run current public airline news discovery layer",
    )
    subparsers.add_parser(
        "run-airline-research-chain",
        help="Build auditable airline revenue-to-expectations research chain",
    )
    subparsers.add_parser(
        "run-airline-consensus-dispersion-all",
        help="Build all-name HK/A-share consensus dispersion reconciliation",
    )
    subparsers.add_parser(
        "run-airline-market-risk",
        help="Build free historical airline beta, drawdown and liquidity metrics",
    )
    subparsers.add_parser(
        "run-airline-pair-risk",
        help="Build pair-level correlation and beta-hedge diagnostics",
    )
    subparsers.add_parser(
        "run-airline-consensus-events",
        help="Build unified point-in-time consensus revision and rating-event timeline",
    )
    subparsers.add_parser(
        "run-airline-consensus-revision-pulse",
        help="Build dated public-sample consensus revision pulses",
    )
    subparsers.add_parser(
        "run-airline-revision-evidence",
        help="Build unified dated revision and vendor-signal evidence layer",
    )
    subparsers.add_parser(
        "run-airline-revenue-consensus-coverage",
        help="Build direct/fallback/missing revenue-consensus coverage contract",
    )
    subparsers.add_parser(
        "run-airline-guidance-coverage",
        help="Build company guidance, warning and formal-result coverage contract",
    )
    subparsers.add_parser(
        "run-airline-sector-external-outlook",
        help="Build dated IATA/CAAC sector outlook and schedule context",
    )
    subparsers.add_parser(
        "run-airline-pair-screening",
        help="Build non-directional airline pair data-comparability matrix",
    )
    subparsers.add_parser(
        "run-airline-factor-diagnostics",
        help="Build free-data Barra-like pair factor diagnostics",
    )
    subparsers.add_parser(
        "run-airline-yahoo-analyst-snapshot",
        help="Fetch free Yahoo analyst estimates, revision signals and recommendation trends",
    )
    subparsers.add_parser(
        "run-airline-data-completeness",
        help="Build the auditable airline long/short data-completeness contract",
    )
    subparsers.add_parser(
        "run-airline-operating-freshness",
        help="Verify the next mainland airline operating-release month at a point-in-time cutoff",
    )
    subparsers.add_parser(
        "run-airline-operating-diagnostics",
        help="Build Q2/June mainland airline operating diagnostics from monthly releases",
    )
    subparsers.add_parser(
        "run-airline-short-side-proxies",
        help="Fetch free HKEX and SSE public short-side proxy snapshots",
    )
    subparsers.add_parser(
        "run-airline-short-eligibility",
        help="Fetch HKEX designated-short and SSE margin eligibility evidence",
    )
    subparsers.add_parser(
        "run-airline-hk-short-positions",
        help="Fetch free SFC aggregate reportable short-position history for HK airlines",
    )
    subparsers.add_parser(
        "run-airline-stock-connect-short-selling",
        help="Fetch free HKEX Stock Connect short-selling history for A-share airlines",
    )
    subparsers.add_parser(
        "run-airline-hsr-query-queue",
        help="Expand airline HSR route candidates into a leg-level queue without scoring",
    )
    subparsers.add_parser(
        "run-airline-hsr-station-codes",
        help="Fetch the live 12306 station-name and telecode dictionary",
    )
    ctrip_parser = subparsers.add_parser(
        "run-airline-hsr-ctrip-snapshot",
        help="Fetch a dated Ctrip SSR train snapshot for one city pair",
    )
    ctrip_parser.add_argument("--origin", required=True, help="Ctrip origin pinyin, e.g. shanghai")
    ctrip_parser.add_argument("--destination", required=True, help="Ctrip destination pinyin, e.g. guangzhou")
    ctrip_parser.add_argument("--date", dest="observation_date", required=True, help="YYYY-MM-DD observation date")
    subparsers.add_parser(
        "run-airline-hsr-route-observations",
        help="Summarize train-level snapshots into route-leg observations with explicit station scope",
    )
    subparsers.add_parser(
        "run-airline-hsr-enrichment-pipeline",
        help="Run end-to-end airline HSR enrichment pipeline with access latency and diagnostic scoring",
    )
    subparsers.add_parser(
        "run-airline-route-capacity-weights",
        help="Build auditable route capacity proxies and fleet seat weights without total ASK allocations",
    )
    subparsers.add_parser(
        "run-airline-pair-thesis-readiness",
        help="Build non-directional pair thesis readiness snapshot separating Juneyao Mainline from 9 Air",
    )
    subparsers.add_parser("run-vehicle-first-reg", help="Run TD monthly private-car first-registration ingestion")
    subparsers.add_parser("run-vehicle-details", help="Run TD latest private-car make/model detail ingestion")
    subparsers.add_parser("run-parking", help="Run TD parking-vacancy snapshot ingestion")
    subparsers.add_parser("run-carpark-occupancy", help="Run TD metered-space parking occupancy ingestion")
    subparsers.add_parser("run-mttd-passenger-journeys", help="Run MTTD Table 2.3 passenger journeys ingestion")
    subparsers.add_parser("run-boundary-movements", help="Run C&SD Table E705 boundary movements ingestion")
    subparsers.add_parser("run-vehicle-fleet", help="Run TD Table 4.1(a) private-car fleet stock ingestion")
    subparsers.add_parser("run-vehicle-net-registration", help="Run TD Table 4.1(c) net-registration ingestion")

    args = parser.parse_args()

    try:
        if args.command in ("run-stage-1", "run-all"):
            results = run_stage_1_pipeline()
            print("\nStage 1 Ingestion completed across sources.")
        elif args.command == "run-mtr":
            df = fetch_mtr_patronage()
            print(f"Fetched MTR patronage: {len(df)} records\n", df.head())
        elif args.command == "run-cathay":
            df = fetch_cathay_traffic()
            print(f"Fetched Cathay & HKIA traffic: {len(df)} records\n", df.head())
        elif args.command == "run-energy-prices":
            df = fetch_eia_airline_energy_prices()
            print(f"Fetched EIA airline energy prices: {len(df)} records\n", df.tail())
        elif args.command == "run-fuel-surcharges":
            df = fetch_fuel_surcharge_snapshots()
            print(f"Fetched airline fuel surcharges: {len(df)} records\n", df)
        elif args.command == "run-fx-rates":
            df = fetch_ecb_airline_fx_rates()
            print(f"Fetched airline FX rates: {len(df)} records\n", df.tail())
        elif args.command == "run-airline-financials":
            results = fetch_a_share_airline_financial_layers()
            print(
                "Fetched A-share airline financial layers: "
                + ", ".join(f"{name}={len(frame)}" for name, frame in results.items())
            )
        elif args.command == "run-airline-financial-history":
            df = fetch_airline_financial_history()
            print(f"Built airline historical financial trend layer: {len(df)} records\n", df.head())
        elif args.command == "run-airline-historical-earnings-bridge":
            df = fetch_airline_historical_earnings_bridge()
            print(f"Built airline historical earnings bridge: {len(df)} records\n", df.head())
        elif args.command == "run-airline-pair-historical-bridge":
            df = fetch_airline_pair_historical_bridge()
            print(f"Built airline pair historical bridge: {len(df)} records\n", df.head())
        elif args.command == "run-airline-pair-scenarios":
            df = fetch_airline_pair_scenario_inputs()
            print(f"Built airline pair scenario inputs: {len(df)} records\n", df.head())
        elif args.command == "run-airline-primary-reconciliation":
            df = fetch_airline_primary_financial_reconciliation()
            print(f"Built airline primary financial reconciliation: {len(df)} records\n", df.head())
        elif args.command == "run-airline-core-pair-model":
            df = fetch_airline_core_pair_model_inputs()
            print(f"Built airline core-pair model inputs: {len(df)} records\n", df.head())
        elif args.command == "run-airline-public-report-evidence":
            df = fetch_airline_public_report_evidence()
            print(f"Fetched public airline report evidence: {len(df)} records\n", df.head())
        elif args.command == "run-airline-revenue-consensus":
            df = fetch_airline_revenue_consensus()
            print(f"Fetched airline revenue consensus: {len(df)} records\n", df)
        elif args.command == "run-airline-expectation-bridge":
            df = fetch_airline_expectation_bridge()
            print(f"Built airline expectation bridge: {len(df)} records\n", df)
        elif args.command == "run-airline-sell-side-revenue":
            results = fetch_sell_side_revenue_layers()
            print(
                "Fetched sell-side revenue layers: "
                + ", ".join(f"{name}={len(frame)}" for name, frame in results.items())
            )
        elif args.command == "run-cathay-annual-drivers":
            df = fetch_cathay_annual_drivers()
            print(f"Fetched Cathay annual drivers: {len(df)} records\n", df)
        elif args.command == "run-cathay-interim-drivers":
            df = fetch_cathay_interim_drivers()
            print(f"Fetched Cathay interim drivers: {len(df)} records\n", df)
        elif args.command == "run-airline-fuel-sensitivity":
            df = fetch_fuel_sensitivity_scenarios()
            print(f"Built airline fuel sensitivity scenarios: {len(df)} records\n", df.head())
        elif args.command == "run-airline-filing-calendar":
            df = fetch_airline_filing_calendar()
            print(f"Fetched airline filing calendar: {len(df)} records\n", df)
        elif args.command == "run-airline-official-filing-watch":
            df = fetch_airline_official_filing_watch()
            print(f"Fetched official airline filing watch: {len(df)} records\n", df)
        elif args.command == "run-airline-market-snapshot":
            df = fetch_airline_market_snapshot()
            print(f"Fetched airline market snapshot: {len(df)} records\n", df)
        elif args.command == "run-airline-hk-consensus":
            results = fetch_hk_airline_consensus()
            print(
                "Fetched HK airline broker layers: "
                + ", ".join(f"{name}={len(frame)}" for name, frame in results.items())
            )
        elif args.command == "run-airline-sector-trends":
            df = fetch_airline_sector_trends()
            print(f"Built airline sector trend snapshot: {len(df)} records\n", df.head())
        elif args.command == "run-airline-sector-expectations":
            df = fetch_airline_sector_expectation_snapshot()
            print(f"Built airline sector expectation snapshot: {len(df)} records\n", df)
        elif args.command == "run-cathay-sector-trends":
            df = fetch_cathay_sector_trends()
            print(f"Built Cathay sector trend snapshot: {len(df)} records\n", df)
        elif args.command == "run-airline-official-reports":
            results = fetch_official_airline_report_drivers()
            print(
                "Fetched official airline report layers: "
                + ", ".join(f"{name}={len(frame)}" for name, frame in results.items())
            )
        elif args.command == "run-airline-hedging-disclosures":
            df = fetch_airline_hedging_disclosures()
            print(f"Built airline hedging disclosure layer: {len(df)} records\n", df)
        elif args.command == "run-airline-consensus-freshness":
            df = fetch_airline_consensus_freshness()
            print(f"Built airline consensus freshness layer: {len(df)} records\n", df)
        elif args.command == "run-airline-consensus-dispersion":
            df = fetch_airline_consensus_dispersion()
            print(f"Built airline consensus dispersion layer: {len(df)} records\n", df)
        elif args.command == "run-airline-earnings-drivers":
            df = fetch_airline_earnings_driver_comparability()
            print(f"Built airline earnings-driver comparability layer: {len(df)} records\n", df.head())
        elif args.command == "run-airline-consensus-em":
            df = fetch_airline_consensus_em()
            print(f"Fetched Eastmoney airline consensus snapshot: {len(df)} records\n", df)
        elif args.command == "run-airline-cninfo-ratings":
            df = fetch_cninfo_rating_events()
            print(f"Fetched Cninfo airline rating events: {len(df)} records\n", df.tail())
        elif args.command == "run-airline-revision-coverage":
            df = fetch_airline_revision_coverage()
            print(f"Built airline revision coverage summary: {len(df)} records\n", df)
        elif args.command == "run-airline-pair-readiness":
            df = fetch_airline_pair_readiness()
            print(f"Built airline pair readiness gate: {len(df)} records\n", df)
        elif args.command == "run-airline-news":
            df = fetch_airline_news_events()
            print(f"Fetched airline news events: {len(df)} records\n", df.head())
        elif args.command == "run-airline-research-chain":
            df = fetch_airline_research_chain()
            print(f"Built airline research chain: {len(df)} records\n", df.head())
        elif args.command == "run-airline-consensus-dispersion-all":
            df = fetch_airline_consensus_dispersion_all()
            print(f"Built all-name consensus dispersion: {len(df)} records\n", df)
        elif args.command == "run-airline-market-risk":
            df = fetch_airline_market_risk_metrics()
            print(f"Built airline market-risk metrics: {len(df)} records\n", df)
        elif args.command == "run-airline-pair-risk":
            df = fetch_airline_pair_risk_metrics()
            print(f"Built airline pair-risk metrics: {len(df)} records\n", df.head())
        elif args.command == "run-airline-consensus-events":
            df = fetch_airline_consensus_events()
            print(f"Built airline consensus event timeline: {len(df)} records\n", df.head())
        elif args.command == "run-airline-consensus-revision-pulse":
            df = fetch_airline_consensus_revision_pulse()
            print(f"Built airline consensus revision pulse: {len(df)} records\n", df.head())
        elif args.command == "run-airline-revision-evidence":
            df = fetch_airline_revision_evidence()
            print(f"Built airline revision evidence layer: {len(df)} records\n", df.head())
        elif args.command == "run-airline-revenue-consensus-coverage":
            df = fetch_airline_revenue_consensus_coverage()
            print(f"Built airline revenue-consensus coverage: {len(df)} records\n", df)
        elif args.command == "run-airline-guidance-coverage":
            df = fetch_airline_guidance_coverage()
            print(f"Built airline guidance coverage: {len(df)} records\n", df)
        elif args.command == "run-airline-sector-external-outlook":
            df = fetch_airline_sector_external_outlook()
            print(f"Built airline sector external outlook: {len(df)} records\n", df)
        elif args.command == "run-airline-pair-screening":
            df = fetch_airline_pair_screening_matrix()
            print(f"Built airline pair screening matrix: {len(df)} records\n", df)
        elif args.command == "run-airline-factor-diagnostics":
            df = fetch_airline_pair_factor_diagnostics()
            print(f"Built airline pair factor diagnostics: {len(df)} records\n", df)
        elif args.command == "run-airline-yahoo-analyst-snapshot":
            df = fetch_airline_yahoo_analyst_snapshot()
            print(f"Fetched Yahoo airline analyst snapshot: {len(df)} records\n", df.head())
        elif args.command == "run-airline-data-completeness":
            df = fetch_airline_data_completeness()
            print(f"Built airline data-completeness contract: {len(df)} records\n", df.head())
        elif args.command == "run-airline-operating-freshness":
            df = fetch_airline_operating_freshness()
            print(f"Built airline operating-release freshness contract: {len(df)} records\n", df)
        elif args.command == "run-airline-operating-diagnostics":
            df = fetch_airline_operating_diagnostics()
            print(f"Built airline operating diagnostics: {len(df)} records\n", df)
        elif args.command == "run-airline-short-side-proxies":
            df = fetch_airline_short_side_proxies()
            print(f"Built airline short-side proxy snapshot: {len(df)} records\n", df)
        elif args.command == "run-airline-short-eligibility":
            df = fetch_airline_short_eligibility()
            print(f"Built airline short-eligibility evidence: {len(df)} records\n", df)
        elif args.command == "run-airline-hk-short-positions":
            df = fetch_airline_hk_short_positions()
            print(f"Built HK airline short-position history: {len(df)} records\n", df.tail())
        elif args.command == "run-airline-stock-connect-short-selling":
            df = fetch_airline_stock_connect_short_selling()
            print(f"Built A-share airline Stock Connect short-selling history: {len(df)} records\n", df.tail())
        elif args.command == "run-airline-hsr-query-queue":
            df = fetch_airline_hsr_query_queue()
            print(f"Built airline HSR route query queue: {len(df)} legs\n", df.head())
        elif args.command == "run-airline-hsr-station-codes":
            df = fetch_12306_station_codes()
            print(f"Fetched 12306 station codes: {len(df)} stations\n", df.head())
        elif args.command == "run-airline-hsr-ctrip-snapshot":
            df = fetch_ctrip_train_snapshot(args.origin, args.destination, args.observation_date)
            print(f"Fetched Ctrip train snapshot: {len(df)} trains\n", df.head())
        elif args.command == "run-airline-hsr-route-observations":
            df = summarize_ctrip_route_observations()
            print(f"Summarized airline HSR route observations: {len(df)} records\n", df.head())
        elif args.command == "run-airline-hsr-enrichment-pipeline":
            df = run_airline_hsr_enrichment_pipeline()
            print(f"Executed airline HSR enrichment pipeline: {len(df)} legs\n", df.head())
        elif args.command == "run-airline-route-capacity-weights":
            df = build_airline_route_capacity_weights()
            print(f"Built airline route capacity weights: {len(df)} records\n", df.head())
        elif args.command == "run-airline-pair-thesis-readiness":
            df = build_airline_pair_thesis_readiness()
            print(f"Built airline pair thesis readiness snapshot: {len(df)} records\n", df.head())
        elif args.command == "run-airline-pre-h1-scenario-bridge":
            df = fetch_airline_pre_h1_scenario_bridge()
            print(f"Built airline pre-H1 scenario bridge: {len(df)} records\n", df.head())
        elif args.command == "run-airline-forecast-risk-framework":
            assumptions, risks = fetch_airline_forecast_risk_framework()
            print(f"Built airline forecast assumptions: {len(assumptions)} rows; risk matrix: {len(risks)} rows\n", assumptions.head())
        elif args.command == "run-airline-company-financial-forecast":
            df = fetch_airline_company_financial_forecast_bridge()
            print(f"Built airline company financial forecast bridge: {len(df)} rows\n", df.head())
        elif args.command == "run-airline-h1-claim-validation":
            df = fetch_airline_h1_claim_validation_queue()
            print(f"Built airline H1 claim-validation queue: {len(df)} rows\n", df.head())
        elif args.command == "run-airline-juneyao-9air-scope":
            df = fetch_airline_juneyao_9air_scope_reconciliation()
            print(f"Built Juneyao/9 Air scope reconciliation: {len(df)} rows\n", df.head())
        elif args.command == "run-airline-yield-fuel-hsr-framework":
            yield_matrix, fuel_matrix, research_queue, hsr_coverage = fetch_airline_yield_fuel_hsr_framework()
            print(
                "Built airline yield/pricing matrix: "
                f"{len(yield_matrix)} rows; fuel/hedge matrix: {len(fuel_matrix)} rows; "
                f"research queue: {len(research_queue)} rows; HSR coverage: {len(hsr_coverage)} rows\n",
                yield_matrix.head(),
            )
        elif args.command == "run-airline-forward-earnings-scorecard":
            bridge, scorecard, risks = fetch_airline_forward_earnings_and_pair_scorecard()
            print(
                "Built six-company forward earnings bridge: "
                f"{len(bridge)} rows; pair scorecard: {len(scorecard)} rows; invalidation rules: {len(risks)} rows\n",
                scorecard[["rank", "pair_id", "selection_score", "selection_bucket"]].head(10),
            )
        elif args.command == "run-airline-pair-thesis-working-set":
            df = fetch_airline_pair_thesis_working_set()
            print(f"Built airline pair thesis working set: {len(df)} rows\n", df[["priority_rank", "pair_id", "selection_bucket", "mechanical_direction_hint"]])
        elif args.command == "run-airline-pair-trade-thesis":
            df = fetch_airline_pair_trade_thesis_scenarios()
            print(f"Built provisional airline pair trade-thesis scenarios: {len(df)} rows\n", df[["pair_id", "scenario", "long_leg", "short_leg", "beta_hedged_pair_payoff_pct"]].head(15))
        elif args.command == "run-airline-pair-valuation-factor-review":
            df = fetch_airline_pair_valuation_factor_review()
            print(f"Built airline pair valuation/factor review: {len(df)} rows\n", df[["pair_id", "base_beta_hedged_payoff_pct", "long_multiple_compression_10pct_payoff_pct", "factor_risk_status", "trade_readiness_status"]])
        elif args.command == "run-airline-valuation-peer-comparability":
            df = fetch_airline_valuation_peer_comparability()
            print(
                f"Built airline peer-comparability valuation gate: {len(df)} rows\n",
                df[["pair_id", "business_model_match_status", "valuation_method_status", "valuation_target_readiness"]],
            )
        elif args.command == "run-airline-historical-pb-valuation":
            df = fetch_airline_historical_pb_valuation()
            print(
                f"Built airline historical P/B valuation diagnostics: {len(df)} rows\n",
                df[["asset", "company", "current_pb", "pb_median_1y", "current_pb_percentile_1y", "valuation_status"]],
            )
        elif args.command == "run-airline-pair-pb-trade-diagnostic":
            df = fetch_airline_pair_pb_trade_diagnostic()
            print(
                f"Built airline pair P/B trade diagnostics: {len(df)} rows\n",
                df[["pair_id", "scenario", "long_leg", "short_leg", "equal_notional_gross_pair_payoff_pct", "beta_hedged_pair_payoff_pct", "valuation_conflict_flag"]],
            )
        elif args.command == "run-airline-pair-risk-budget-sizing":
            df = fetch_airline_pair_risk_budget_sizing()
            print(
                f"Built airline pair risk-budget sizing diagnostics: {len(df)} rows\n",
                df[["pair_id", "portfolio_loss_budget_pct", "long_leg", "short_leg", "direction_aware_hedged_spread_max_drawdown_pct", "diagnostic_gross_notional_pct_nav", "risk_status"]],
            )
        elif args.command == "run-airline-pair-direction-decision":
            df = fetch_airline_pair_direction_decision()
            print(
                f"Built airline pair direction decision gate: {len(df)} rows\n",
                df[["pair_id", "earnings_model_direction", "pb_median_direction", "direction_concordance", "selected_direction_status", "selected_direction"]],
            )
        elif args.command == "run-airline-pair-target-range":
            df = fetch_airline_pair_target_range()
            print(
                f"Built airline pair target/payoff ranges: {len(df)} rows\n",
                df[["pair_id", "scenario", "selected_direction_status", "equal_notional_pair_payoff_low_pct", "equal_notional_pair_payoff_high_pct", "beta_hedged_pair_payoff_low_pct", "beta_hedged_pair_payoff_high_pct"]],
            )
        elif args.command == "run-airline-pair-revision-confirmation":
            df = fetch_airline_pair_revision_confirmation()
            print(
                f"Built airline pair revision confirmation: {len(df)} rows\n",
                df[["pair_id", "model_long_leg", "model_short_leg", "long_latest_signal_direction", "short_latest_signal_direction", "revision_confirmation_status"]],
            )
        elif args.command == "run-airline-pair-event-trade-triggers":
            df = fetch_airline_pair_event_trade_triggers()
            print(
                f"Built airline pair event trade triggers: {len(df)} rows\n",
                df[["pair_id", "conditional_direction", "event_window", "minimum_surprise_gap_for_entry_pp", "current_revision_status", "trade_status"]],
            )
        elif args.command == "run-airline-pair-branch-thesis":
            df = fetch_airline_pair_branch_thesis()
            print(
                f"Built airline pair branch theses: {len(df)} rows\n",
                df[["pair_id", "branch", "long_leg", "short_leg", "target_payoff_low_pct", "target_payoff_high_pct", "branch_status"]],
            )
        elif args.command == "run-vehicle-first-reg":
            df = fetch_td_private_car_first_reg()
            print(f"Fetched TD private-car first registrations: {len(df)} records\n", df.head())
        elif args.command == "run-vehicle-details":
            df = fetch_td_first_registered_vehicle_details()
            print(f"Fetched TD private-car make/model details: {len(df)} records\n", df.head())
        elif args.command == "run-parking":
            df = fetch_td_parking_vacancy()
            print(f"Fetched TD parking vacancy: {len(df)} records\n", df.head())
        elif args.command == "run-carpark-occupancy":
            df = fetch_td_carpark_occupancy()
            print(f"Fetched TD metered-space parking occupancy: {len(df)} records\n", df.head())
        elif args.command == "run-mttd-passenger-journeys":
            df = fetch_mttd_passenger_journeys()
            print(f"Fetched MTTD Table 2.3 passenger journeys: {len(df)} records\n", df.head())
        elif args.command == "run-boundary-movements":
            df = fetch_censtatd_boundary_movements()
            print(f"Fetched C&SD Table E705 boundary movements: {len(df)} records\n", df.head())
        elif args.command == "run-vehicle-fleet":
            df = fetch_td_vehicle_fleet_stock()
            print(f"Fetched TD private-car fleet stock: {len(df)} records\n", df.tail())
        elif args.command == "run-vehicle-net-registration":
            df = fetch_td_private_car_net_registration()
            print(f"Fetched TD private-car net registration: {len(df)} records\n", df.tail())
        else:
            parser.print_help()
    except Exception as e:
        print(f"Error executing command: {e}")


if __name__ == "__main__":
    main()
