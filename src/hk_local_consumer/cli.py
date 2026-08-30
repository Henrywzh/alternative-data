import argparse
import json
import sys

from .pipeline import (
    run_stage_1_pipeline,
    run_all_pipelines,
    run_dashboard_history_sources,
)
from .sources.afcd_food import fetch_afcd_food_prices
from .sources.consumer_council import fetch_consumer_council_prices
from .sources.sge_gold import fetch_sge_gold_benchmark
from .sources.hk_valuation import fetch_hk_consumer_valuations
from .sources.cnsd_retail import fetch_cnsd_retail_sales
from .sources.censtatd_restaurant import fetch_censtatd_restaurant_survey
from .sources.immigration_flow import fetch_immigration_flow
from .sources.weather_demand_drivers import fetch_weather_demand_drivers


def main():
    parser = argparse.ArgumentParser(description="HK Local Consumer Alternative Data Pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    stage_1_parser = subparsers.add_parser("run-stage-1", help="Run Stage 1 ready-to-build ingestion")
    stage_1_parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when any registered source fails or is invalid.",
    )
    all_parser = subparsers.add_parser("run-all", help="Run full pipeline across Stage 1 sources")
    all_parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when any registered source fails or is invalid.",
    )
    subparsers.add_parser("run-afcd", help="Run AFCD food price ingestion")
    subparsers.add_parser("run-consumer-council", help="Run Consumer Council price watch ingestion")
    subparsers.add_parser("run-sge-gold", help="Run SGE gold benchmark ingestion")
    subparsers.add_parser("run-valuations", help="Run HK consumer stock valuation ingestion")
    subparsers.add_parser("run-cnsd", help="Run C&SD retail sales index ingestion")
    subparsers.add_parser("run-censtatd", help="Run CenStatD restaurant survey ingestion")
    subparsers.add_parser("run-immigration", help="Run HK Immigration Department daily traffic ingestion")
    subparsers.add_parser("run-weather", help="Run HKO weather & FX demand drivers ingestion")
    subparsers.add_parser("run-dashboard-history", help="Materialise immigration checkpoints and HKO warning events")

    args = parser.parse_args()

    try:
        if args.command in ("run-stage-1", "run-all"):
            results = run_stage_1_pipeline(_raise_on_failure=args.strict)
            print("\nStage 1 Ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-dashboard-history":
            print(json.dumps(run_dashboard_history_sources(), indent=2))
        elif args.command == "run-afcd":
            df = fetch_afcd_food_prices()
            print(f"Fetched AFCD food prices: {len(df)} records\n", df.head())
        elif args.command == "run-consumer-council":
            df = fetch_consumer_council_prices()
            print(f"Fetched Consumer Council price watch: {len(df)} records\n", df.head())
        elif args.command == "run-sge-gold":
            df = fetch_sge_gold_benchmark()
            print(f"Fetched SGE Gold Benchmark: {len(df)} records\n", df.head())
        elif args.command == "run-valuations":
            df = fetch_hk_consumer_valuations()
            print(f"Fetched HK Valuation metrics: {len(df)} records\n", df.head())
        elif args.command == "run-cnsd":
            df = fetch_cnsd_retail_sales()
            print(f"Fetched C&SD Retail Sales: {len(df)} records\n", df.head())
        elif args.command == "run-censtatd":
            df = fetch_censtatd_restaurant_survey()
            print(f"Fetched CenStatD Restaurant Survey: {len(df)} records\n", df.head())
        elif args.command == "run-immigration":
            df = fetch_immigration_flow()
            print(f"Fetched Immigration Passenger Traffic: {len(df)} records\n", df.head())
        elif args.command == "run-weather":
            df = fetch_weather_demand_drivers()
            print(f"Fetched Weather & Demand Drivers: {len(df)} records\n", df.head())
        else:
            parser.print_help()
    except Exception as e:
        print(f"\nFATAL: Ingestion failed with error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
