"""CLI for HK Stablecoin & Crypto Sector Pipeline."""

from __future__ import annotations

import argparse

from .pipeline import run_stage_1_pipeline
from .sources.crypto_tickers import fetch_all_crypto_signals
from .sources.defillama_stablecoins import fetch_stablecoin_supply
from .sources.hkex_etf_aum import fetch_all_etf_aum
from .sources.hkma_register import fetch_licensed_issuers
from .sources.polymarket_events import fetch_all_polymarket_catalysts
from .sources.sfc_vatp_register import fetch_vatp_register


def main():
    parser = argparse.ArgumentParser(description="HK Stablecoin & Crypto Sector Pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("run", help="Run full stage 1 pipeline across all sources")
    subparsers.add_parser("run-hkma", help="Run HKMA register fetch")
    subparsers.add_parser("run-sfc", help="Run SFC VATP register fetch")
    subparsers.add_parser("run-defillama", help="Run DefiLlama stablecoin supply fetch")
    subparsers.add_parser("run-etf-aum", help="Run HKEX ETF AUM fetch")
    subparsers.add_parser("run-crypto-tickers", help="Run crypto tickers fetch")
    subparsers.add_parser("run-polymarket", help="Run Polymarket catalysts fetch")

    args = parser.parse_args()

    try:
        if args.command == "run":
            results = run_stage_1_pipeline()
            print("\nStage 1 Ingestion completed across sources.")
        elif args.command == "run-hkma":
            df = fetch_licensed_issuers()
            print(f"Fetched HKMA register: {len(df)} records\n", df)
        elif args.command == "run-sfc":
            df = fetch_vatp_register()
            print(f"Fetched SFC register: {len(df)} records\n", df.head())
        elif args.command == "run-defillama":
            df = fetch_stablecoin_supply()
            print(f"Fetched DefiLlama stablecoins: {len(df)} records\n", df.head())
        elif args.command == "run-etf-aum":
            df = fetch_all_etf_aum()
            print(f"Fetched HKEX ETF AUM: {len(df)} records\n", df.head())
        elif args.command == "run-crypto-tickers":
            res = fetch_all_crypto_signals()
            print(f"Fetched crypto signals:\n", res)
        elif args.command == "run-polymarket":
            df = fetch_all_polymarket_catalysts()
            print(f"Fetched Polymarket events: {len(df)} records\n", df.head())
        else:
            parser.print_help()
    except Exception as e:
        print(f"Error executing command: {e}")


if __name__ == "__main__":
    main()
