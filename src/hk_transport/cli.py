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


def main():
    parser = argparse.ArgumentParser(description="HK Transport Sector Alternative Data Pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("run-stage-1", help="Run Stage 1 ready-to-build ingestion")
    subparsers.add_parser("run-all", help="Run full pipeline across all sources")
    subparsers.add_parser("run-mtr", help="Run MTR patronage ingestion")
    subparsers.add_parser("run-cathay", help="Run Cathay & HKIA traffic ingestion")
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
