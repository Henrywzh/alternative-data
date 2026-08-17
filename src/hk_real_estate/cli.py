import argparse
import json
import sys
from pathlib import Path

from .pipeline import (
    run_group_a_pipeline,
    run_group_b_pipeline,
    run_group_c_pipeline,
    run_all_pipelines,
    run_stage_1_pipeline,
    run_stage_2_pipeline,
    run_all_incomplete_pipelines,
    run_centaline_indices_pipeline,
    run_midland_monthly_pipeline,
    run_rvd_commercial_pipeline,
    run_hk_commercial_controls_pipeline,
    run_midland_snapshot_pipeline,
    run_policy_event_research_pipeline,
    run_bd_project_history_backfill,
    run_bd_project_history_local_reparse,
    run_bd_project_history_audit_backfill,
)
from .srpe_pilot import run_srpe_pilot, SRPE_PROJECT_REGISTRY_PATH
from .shkp_catalog import (
    build_shkp_historical_phase_roster,
    run_shkp_current_manifest_backfill,
    run_shkp_historical_phase_manifest_backfill,
    run_shkp_historical_transaction_backfill,
    run_shkp_history_milestones,
    run_shkp_historical_annual_backfill,
    import_shkp_land_registry_csv,
    import_shkp_phase_attribution_decisions_csv,
    run_shkp_catalog,
)
from .shkp_high_recall import run_shkp_high_recall_phase_candidates
from .shkp_unknown_phase_probe import run_shkp_unknown_phase_probe
from .shkp_financial_model import run_shkp_financial_model
from .shkp_h1_backtest import run_shkp_h1_backtest
from .shkp_sales_handover_bridge import run_shkp_sales_handover_revenue_bridge
from .shkp_price import run_shkp_price_history
from .shkp_forecast_backtest import run_shkp_forecast_backtest
from .shkp_srpe_backfill import (
    run_shkp_srpe_rendered_site_probe,
    run_shkp_srpe_site_probe,
    run_shkp_srpe_transaction_scratch,
)
from .shkp_signals import (
    run_shkp_all_history_signal_contract,
    run_shkp_indicative_signal_contract,
    run_shkp_srpe_signal_contract,
)
from .shkp_indicative_sales_model import run_shkp_indicative_sales_model
from .shkp_28hse_reconciliation import run_shkp_28hse_reconciliation, run_shkp_ownership_review_priority
from .shkp_commercial import run_shkp_commercial_recurring_contract
from .shkp_commercial_model import run_shkp_commercial_model
from .shkp_earnings_bridge import run_shkp_earnings_bridge
from .shkp_whole_company_model import run_shkp_whole_company_model
from .shkp_handover_lag import run_shkp_handover_lag
from .shkp_project_margin_model import run_shkp_project_margin_model
from .shkp_margin_variant import run_shkp_margin_variant
from .shkp_skeleton_backtest import run_shkp_skeleton_backtest, run_shkp_skeleton_margin_decomposition
from .shkp_bd_history import (
    run_shkp_bd_history_crosswalk,
    run_shkp_bd_history_entity_resolution_review,
)

def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="HK Real Estate Alternative Data Pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("run-group-a", help="Run Group A data ingestion")
    subparsers.add_parser("run-group-b", help="Run Group B data ingestion")
    subparsers.add_parser("run-group-c", help="Run Group C data ingestion")
    subparsers.add_parser("run-all", help="Run full pipeline across all data sources")
    subparsers.add_parser("run-stage-1", help="Run Stage 1 source ingestion")
    subparsers.add_parser("run-stage-2", help="Run Stage 2 financing & stock attribution ingestion")
    bd_project_history_parser = subparsers.add_parser(
        "run-bd-project-history-backfill",
        help="Backfill detailed Buildings Department Md52-Md56 project rows from monthly PDFs",
    )
    bd_project_history_parser.add_argument("--start-year", type=int, default=2005)
    bd_project_history_parser.add_argument("--end-year", type=int)
    bd_project_history_parser.add_argument(
        "--month",
        type=int,
        action="append",
        dest="months",
        help="Restrict to one or more calendar months (repeat --month); default is all months",
    )
    bd_project_history_audit_parser = subparsers.add_parser(
        "run-bd-project-history-audit",
        help="Reconcile annual detailed Buildings Department Md52-Md56 rows against Section 1 aggregates",
    )
    bd_project_history_audit_parser.add_argument("--start-year", type=int, default=2005)
    bd_project_history_audit_parser.add_argument("--end-year", type=int)
    subparsers.add_parser(
        "run-bd-project-history-local-reparse",
        help="Reparse the latest detailed BD history from existing local raw PDFs (no network fetch)",
    )
    subparsers.add_parser("run-incomplete-5", help="Run digestion pipeline for the 5 incomplete data sources")
    subparsers.add_parser("run-centaline-indices", help="Run Tranche 1 CCI/CRI/CSI ingestion only")
    subparsers.add_parser("run-midland-monthly", help="Run Tranche 2 Midland monthly ingestion only")
    subparsers.add_parser("run-rvd-commercial", help="Run Tranche 3 RVD office/retail ingestion only")
    subparsers.add_parser(
        "run-hk-commercial-controls",
        help="Run SHKP Quarterly events, HK commercial asset master, RVD/C&SD/tourism controls",
    )
    subparsers.add_parser("run-midland-snapshots", help="Run Tranche 4 Midland snapshot ingestion only")
    subparsers.add_parser("run-policy-events", help="Run Tranche 5 policy-source and registry research contracts")
    shkp_parser = subparsers.add_parser(
        "run-shkp-catalog",
        help="Refresh the bounded SHKP/SRPE project-universe and ownership-review catalog",
    )
    shkp_parser.add_argument("--timeout", type=float, default=60)
    shkp_parser.add_argument("--max-pages", type=int)
    shkp_parser.add_argument("--max-manifest-developments", type=int, default=10)
    shkp_parser.add_argument("--site-project-limit", type=int, default=50)
    shkp_parser.add_argument("--skip-site-facts", action="store_true")
    shkp_parser.add_argument("--skip-deep-documents", action="store_true")
    shkp_parser.add_argument("--offline", action="store_true", help="Audit latest normalized snapshots without fetching")
    history_parser = subparsers.add_parser(
        "run-shkp-history-milestones",
        help="Fetch and persist the official SHKP History and Milestones project-evidence layer",
    )
    history_parser.add_argument("--timeout", type=float, default=60)
    subparsers.add_parser(
        "build-shkp-historical-roster",
        help="Build a discovery-only SHKP historical phase roster from the full SRPE index and latest evidence layers",
    )
    annual_backfill_parser = subparsers.add_parser(
        "run-shkp-historical-annual-backfill",
        help="Bounded official SHKP annual-report project evidence backfill",
    )
    annual_backfill_parser.add_argument("--max-reports", type=int, default=3)
    annual_backfill_parser.add_argument("--report-id", action="append", dest="report_ids")
    annual_backfill_parser.add_argument("--timeout", type=float, default=120)
    manifest_backfill_parser = subparsers.add_parser(
        "run-shkp-historical-phase-manifest-backfill",
        help="Fetch official SRPE document manifests for inactive SHKP-evidence phases",
    )
    manifest_backfill_parser.add_argument("--max-developments", type=int, default=25)
    manifest_backfill_parser.add_argument("--timeout", type=float, default=30)
    manifest_backfill_parser.add_argument(
        "--include-unobserved",
        action="store_true",
        help="Include inactive SRPE phases without prior SHKP evidence as discovery-only routing candidates",
    )
    current_manifest_parser = subparsers.add_parser(
        "run-shkp-current-manifest-backfill",
        help="Append official SRPE filing manifests for current SHKP directory candidates",
    )
    current_manifest_parser.add_argument("--max-developments", type=int, default=25)
    current_manifest_parser.add_argument("--timeout", type=float, default=30)
    transaction_backfill_parser = subparsers.add_parser(
        "run-shkp-historical-transaction-backfill",
        help="Parse all available SRPE transaction registers for routed inactive SHKP phases",
    )
    transaction_backfill_parser.add_argument("--max-phases", type=int, default=8)
    transaction_backfill_parser.add_argument("--timeout", type=float, default=30)
    transaction_backfill_parser.add_argument("--request-delay", type=float, default=0.25)
    transaction_backfill_parser.add_argument(
        "--phase-ids",
        type=str,
        default="",
        help="Optional comma-separated explicit SRPE phase ids to route instead of the manifest queue",
    )
    landreg_parser = subparsers.add_parser(
        "import-shkp-land-registry",
        help="Validate and persist a manual IRIS/Land Registry CSV evidence import",
    )
    landreg_parser.add_argument("csv_path", type=Path)
    landreg_parser.add_argument("--last-verified-at")
    decision_parser = subparsers.add_parser(
        "import-shkp-phase-decisions",
        help="Validate and persist manually reviewed SHKP phase-attribution decisions",
    )
    decision_parser.add_argument("csv_path", type=Path)
    decision_parser.add_argument("--last-verified-at")
    model_parser = subparsers.add_parser(
        "run-shkp-financial-model",
        help="Build SHKP financial-model inputs from official disclosures and the sibling financial-data DuckDB",
    )
    model_parser.add_argument("--financial-db", type=Path)
    model_parser.add_argument(
        "--include-price-history",
        action="store_true",
        help="Fetch and persist Yahoo daily OHLCV/adjusted-close history in this model run",
    )
    model_parser.add_argument("--price-start-date", default="2010-01-01")
    model_parser.add_argument("--price-end-date")
    h1_parser = subparsers.add_parser(
        "run-shkp-h1-backtest",
        help="Fetch official SHKP interim reports and build the H1 actual/recognition backtest",
    )
    h1_parser.add_argument("--timeout", type=float, default=45.0)
    h1_parser.add_argument("--request-delay", type=float, default=0.15)
    subparsers.add_parser(
        "run-shkp-sales-handover-bridge",
        help="Build the research-only SHKP phase sales / handover / revenue timing bridge",
    )
    price_parser = subparsers.add_parser(
        "run-shkp-price-history",
        help="Fetch and persist the reviewed SHKP daily price/total-return contract",
    )
    price_parser.add_argument("--start-date", default="2010-01-01")
    price_parser.add_argument("--end-date")
    subparsers.add_parser(
        "run-shkp-forecast-backtest",
        help="Build research-only SHKP current scenarios and release-event study",
    )
    srpe_parser = subparsers.add_parser(
        "run-srpe-pilot",
        help="Run bounded SRPE first-hand residential sales/price-list backfill",
    )
    site_probe_parser = subparsers.add_parser(
        "run-shkp-srpe-site-probe",
        help="Discover SHKP SRPE candidate phases and probe official project-site role evidence",
    )
    site_probe_parser.add_argument("--max-phases", type=int, default=25)
    site_probe_parser.add_argument("--timeout", type=float, default=20)
    site_probe_parser.add_argument("--request-delay", type=float, default=0.25)
    rendered_site_probe_parser = subparsers.add_parser(
        "run-shkp-srpe-rendered-site-probe",
        help="Run a bounded Playwright fallback for JS-heavy SHKP candidate sites",
    )
    rendered_site_probe_parser.add_argument("--max-phases", type=int, default=8)
    rendered_site_probe_parser.add_argument("--timeout", type=float, default=30)
    rendered_site_probe_parser.add_argument("--wait-ms", type=int, default=2500)
    rendered_site_probe_parser.add_argument("--request-delay", type=float, default=0.5)
    rendered_site_probe_parser.add_argument(
        "--all-candidates",
        action="store_true",
        help="Render the deterministic candidate queue instead of only prior HTTP JS/error rows",
    )
    transaction_scratch_parser = subparsers.add_parser(
        "run-shkp-srpe-transaction-scratch",
        help="Batch-download official SRPE transaction registers for SHKP candidates (routing-only)",
    )
    transaction_scratch_parser.add_argument("--max-phases", type=int, default=17)
    transaction_scratch_parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="Skip this many candidates in the deterministic exact/review queue before batching",
    )
    transaction_scratch_parser.add_argument(
        "--include-review",
        action="store_true",
        help="Include matched_needs_review and ambiguous candidates after exact matches",
    )
    transaction_scratch_parser.add_argument("--timeout", type=float, default=30)
    transaction_scratch_parser.add_argument("--request-delay", type=float, default=0.25)
    subparsers.add_parser(
        "run-shkp-srpe-signals",
        help="Consolidate all persisted SHKP SRPE scratch batches into project-month signals",
    )
    subparsers.add_parser(
        "run-shkp-indicative-signals",
        help="Apply approximate SHKP ownership evidence to phase-month signals without opening the strict gate",
    )
    subparsers.add_parser(
        "run-shkp-all-history-signals",
        help="Merge current SHKP candidate signals with the sparse historical SRPE transaction backfill",
    )
    subparsers.add_parser(
        "run-shkp-indicative-sales-model",
        help="Build research-only SHKP monthly sales/growth scenarios from indicative phase-month signals",
    )
    subparsers.add_parser(
        "run-shkp-commercial-recurring",
        help="Build SHKP commercial recurring-income and Mainland project coverage research layers",
    )
    subparsers.add_parser(
        "run-shkp-commercial-model",
        help="Build the SHKP HK commercial portfolio-level rental model (transmission + backtest)",
    )
    subparsers.add_parser(
        "run-shkp-earnings-bridge",
        help="Build the SHKP 16-year whole-company earnings bridge (segment -> underlying -> reported)",
    )
    subparsers.add_parser(
        "run-shkp-whole-company-model",
        help="Build the SHKP whole-company earnings skeleton (residential+commercial+hotel+other -> underlying EPS)",
    )
    subparsers.add_parser(
        "run-shkp-handover-lag",
        help="Build the SHKP residential handover-lag distribution and recognition schedule",
    )
    subparsers.add_parser(
        "run-shkp-project-margin-model",
        help="Build the FY2027 project-mix development margin model (buckets + weighted margin)",
    )
    subparsers.add_parser(
        "run-shkp-margin-variant",
        help="Build the margin group sensitivity + consensus-required analysis",
    )
    subparsers.add_parser(
        "run-shkp-skeleton-backtest",
        help="Build the whole-company skeleton historical backtest",
    )
    subparsers.add_parser(
        "run-shkp-skeleton-margin-decomposition",
        help="Attribute skeleton backtest error to margin assumption vs data coverage",
    )
    subparsers.add_parser(
        "run-shkp-28hse-reconciliation",
        help="Reconcile 28Hse new-project unit states against SHKP/SRPE phase signals",
    )
    subparsers.add_parser(
        "run-shkp-ownership-priority",
        help="Rank the SHKP ownership review queue using evidence and phase signal coverage",
    )
    subparsers.add_parser(
        "run-shkp-high-recall",
        help="Build a broad, review-only SHKP/SRPE phase candidate layer across the full SRPE index",
    )
    unknown_phase_probe_parser = subparsers.add_parser(
        "run-shkp-unknown-phase-probe",
        help="Quick-check official sites for SRPE phases still missing SHKP owner evidence",
    )
    unknown_phase_probe_parser.add_argument("--timeout", type=float, default=8.0)
    unknown_phase_probe_parser.add_argument("--max-workers", type=int, default=12)
    subparsers.add_parser(
        "run-shkp-bd-history-crosswalk",
        help="Build a research-only address candidate crosswalk from SHKP/SRPE phases to historical BD Md52-Md56 rows",
    )
    subparsers.add_parser(
        "run-shkp-bd-history-entity-review",
        help="Build a phase-level research-only entity-resolution review queue from the latest SHKP/BD crosswalk",
    )
    srpe_parser.add_argument(
        "--projects",
        nargs="+",
        help="Stable project_id values; omit to use the registry's core_pilot group",
    )
    srpe_parser.add_argument(
        "--pilot-group",
        default="core_pilot",
        help="Registry pilot_group used when --projects is omitted",
    )
    srpe_parser.add_argument("--registry-path", type=Path, default=SRPE_PROJECT_REGISTRY_PATH)
    srpe_parser.add_argument("--since", help="Minimum PASP/price-list date, YYYY-MM-DD")
    srpe_parser.add_argument("--until", help="Maximum PASP/price-list date, YYYY-MM-DD")
    srpe_parser.add_argument("--price-selection", choices=("first_latest", "all"), default="first_latest")
    srpe_parser.add_argument("--max-price-documents", type=int, default=0)
    srpe_parser.add_argument(
        "--all-transaction-documents",
        action="store_true",
        help="Download and parse every available transaction-register version instead of only the latest",
    )
    srpe_parser.add_argument(
        "--transactions-only",
        action="store_true",
        help="Skip price-list PDFs while testing transaction-register ingestion",
    )
    srpe_parser.add_argument("--request-delay", type=float, default=0.2)

    args = parser.parse_args(argv)

    try:
        if args.command == "run-group-a":
            results = run_group_a_pipeline()
            print("\nGroup A Ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-group-b":
            results = run_group_b_pipeline()
            print("\nGroup B Ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-group-c":
            results = run_group_c_pipeline()
            print("\nGroup C Ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-all":
            results = run_all_pipelines()
            print("\nFull Ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-stage-1":
            results = run_stage_1_pipeline()
            print("\nStage 1 Ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-stage-2":
            results = run_stage_2_pipeline()
            print("\nStage 2 Ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-bd-project-history-backfill":
            results = run_bd_project_history_backfill(
                start_year=args.start_year,
                end_year=args.end_year,
                months=args.months,
            )
        elif args.command == "run-bd-project-history-local-reparse":
            results = run_bd_project_history_local_reparse()
            print("\nBD detailed project-history local reparse completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-bd-project-history-audit":
            results = run_bd_project_history_audit_backfill(
                start_year=args.start_year,
                end_year=args.end_year,
            )
            print("\nBD detailed project-history backfill completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-incomplete-5":
            results = run_all_incomplete_pipelines()
            print("\nIncomplete 5 Ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-centaline-indices":
            results = run_centaline_indices_pipeline()
            print("\nCentaline Tranche 1 ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-midland-monthly":
            results = run_midland_monthly_pipeline()
            print("\nMidland Tranche 2 ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-rvd-commercial":
            results = run_rvd_commercial_pipeline()
            print("\nRVD Tranche 3 ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-hk-commercial-controls":
            results = run_hk_commercial_controls_pipeline()
            print("\nHK commercial controls ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-midland-snapshots":
            results = run_midland_snapshot_pipeline()
            print("\nMidland Tranche 4 ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-policy-events":
            results = run_policy_event_research_pipeline()
            print("\nPolicy/event Tranche 5 ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-shkp-catalog":
            results = run_shkp_catalog(
                timeout=args.timeout,
                max_pages=args.max_pages,
                max_manifest_developments=args.max_manifest_developments,
                site_project_limit=args.site_project_limit,
                skip_site_facts=args.skip_site_facts,
                skip_deep_documents=args.skip_deep_documents,
                offline=args.offline,
            )
            print("\nSHKP project-universe catalog completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "build-shkp-historical-roster":
            results = build_shkp_historical_phase_roster()
            print("\nSHKP historical phase roster completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-historical-annual-backfill":
            results = run_shkp_historical_annual_backfill(
                max_reports=args.max_reports,
                report_ids=args.report_ids,
                timeout=args.timeout,
            )
            print("\nSHKP historical annual-report backfill completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-historical-phase-manifest-backfill":
            results = run_shkp_historical_phase_manifest_backfill(
                max_developments=args.max_developments,
                timeout=args.timeout,
                include_unobserved=args.include_unobserved,
            )
            print("\nSHKP historical phase manifest backfill completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-current-manifest-backfill":
            results = run_shkp_current_manifest_backfill(
                max_developments=args.max_developments,
                timeout=args.timeout,
            )
            print("\nSHKP current manifest backfill completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-historical-transaction-backfill":
            explicit_ids = (
                [value.strip() for value in args.phase_ids.split(",") if value.strip()]
                if args.phase_ids
                else None
            )
            results = run_shkp_historical_transaction_backfill(
                max_phases=args.max_phases,
                timeout=args.timeout,
                request_delay=args.request_delay,
                phase_ids=explicit_ids,
            )
            print("\nSHKP historical transaction backfill completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-history-milestones":
            results = run_shkp_history_milestones(timeout=args.timeout)
            print("\nSHKP History and Milestones ingestion completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "import-shkp-land-registry":
            results = import_shkp_land_registry_csv(
                args.csv_path,
                last_verified_at=args.last_verified_at,
            )
            print("\nSHKP Land Registry evidence import completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "import-shkp-phase-decisions":
            results = import_shkp_phase_attribution_decisions_csv(
                args.csv_path,
                last_verified_at=args.last_verified_at,
            )
            print("\nSHKP phase-attribution decision import completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-financial-model":
            model_kwargs = {
                "include_price_history": args.include_price_history,
                "price_start_date": args.price_start_date,
                "price_end_date": args.price_end_date,
            }
            results = run_shkp_financial_model(db_path=args.financial_db, **model_kwargs) if args.financial_db else run_shkp_financial_model(**model_kwargs)
            print("\nSHKP financial model input build completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-h1-backtest":
            results = run_shkp_h1_backtest(timeout=args.timeout, request_delay=args.request_delay)
            print("\nSHKP H1 actual/backtest build completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-sales-handover-bridge":
            results = run_shkp_sales_handover_revenue_bridge()
            print("\nSHKP sales/handover/revenue bridge build completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-price-history":
            results = run_shkp_price_history(
                start_date=args.start_date,
                end_date=args.end_date,
            )
            print("\nSHKP price history ingestion completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-forecast-backtest":
            results = run_shkp_forecast_backtest()
            print("\nSHKP forecast/backtest research build completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-srpe-site-probe":
            results = run_shkp_srpe_site_probe(
                max_phases=args.max_phases,
                timeout=args.timeout,
                request_delay=args.request_delay,
            )
            print("\nSHKP SRPE site probe completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-srpe-rendered-site-probe":
            results = run_shkp_srpe_rendered_site_probe(
                max_phases=args.max_phases,
                timeout=args.timeout,
                wait_ms=args.wait_ms,
                request_delay=args.request_delay,
                only_js_candidates=not args.all_candidates,
            )
            print("\nSHKP SRPE rendered site probe completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-srpe-transaction-scratch":
            results = run_shkp_srpe_transaction_scratch(
                max_phases=args.max_phases,
                start_index=args.start_index,
                include_review=args.include_review,
                timeout=args.timeout,
                request_delay=args.request_delay,
            )
            print("\nSHKP SRPE transaction scratch completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-srpe-signals":
            results = run_shkp_srpe_signal_contract()
            print("\nSHKP SRPE signal contract completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-indicative-signals":
            results = run_shkp_indicative_signal_contract()
            print("\nSHKP indicative signal contract completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-all-history-signals":
            results = run_shkp_all_history_signal_contract()
            print("\nSHKP all-history signal contract completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-indicative-sales-model":
            results = run_shkp_indicative_sales_model()
            print("\nSHKP indicative sales model completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-commercial-recurring":
            results = run_shkp_commercial_recurring_contract()
            print("\nSHKP commercial recurring/Mainland coverage completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-commercial-model":
            results = run_shkp_commercial_model()
            print("\nSHKP commercial portfolio model completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-earnings-bridge":
            results = run_shkp_earnings_bridge()
            print("\nSHKP historical earnings bridge completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-whole-company-model":
            results = run_shkp_whole_company_model()
            print("\nSHKP whole-company earnings skeleton completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-handover-lag":
            results = run_shkp_handover_lag()
            print("\nSHKP handover-lag analysis completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-project-margin-model":
            results = run_shkp_project_margin_model()
            print("\nSHKP project-mix margin model completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-margin-variant":
            results = run_shkp_margin_variant()
            print("\nSHKP margin variant analysis completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-skeleton-backtest":
            results = run_shkp_skeleton_backtest()
            print("\nSHKP skeleton backtest completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-skeleton-margin-decomposition":
            results = run_shkp_skeleton_margin_decomposition()
            print("\nSHKP skeleton margin decomposition completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-28hse-reconciliation":
            results = run_shkp_28hse_reconciliation()
            print("\nSHKP 28Hse reconciliation completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-ownership-priority":
            results = run_shkp_ownership_review_priority()
            print("\nSHKP ownership review priority completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-high-recall":
            results = run_shkp_high_recall_phase_candidates()
            print("\nSHKP high-recall phase candidate layer completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-unknown-phase-probe":
            results = run_shkp_unknown_phase_probe(
                timeout=args.timeout,
                max_workers=args.max_workers,
            )
            print("\nSHKP unknown-phase quick web probe completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-bd-history-crosswalk":
            results = run_shkp_bd_history_crosswalk()
            print("\nSHKP historical BD crosswalk completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-shkp-bd-history-entity-review":
            results = run_shkp_bd_history_entity_resolution_review()
            print("\nSHKP historical BD entity-resolution review completed:\n" + json.dumps(results, indent=2, default=str))
        elif args.command == "run-srpe-pilot":
            results = run_srpe_pilot(
                registry_path=args.registry_path,
                projects=args.projects,
                pilot_group=args.pilot_group,
                since=args.since,
                until=args.until,
                price_selection=args.price_selection,
                max_price_documents=args.max_price_documents,
                all_transaction_documents=args.all_transaction_documents,
                transactions_only=args.transactions_only,
                request_delay=args.request_delay,
            )
            print("\nSRPE bounded pilot completed:\n" + json.dumps(results, indent=2, default=str))
        else:
            parser.print_help()
    except Exception as e:
        print(f"\nFATAL: Ingestion failed with error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
