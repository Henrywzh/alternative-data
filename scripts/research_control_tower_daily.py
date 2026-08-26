#!/usr/bin/env python3
"""Daily freshness collectors for Research Control Tower overlays.

Does not rebuild the published generation. Writes quote, southbound, news,
and official-filing marts that the local app already overlays. Valuation
snapshots stay fail-closed when consensus basis is unverified.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.research_control_tower.official_filings import collect_official_filings, load_source_identity
from src.research_control_tower.quote_collector import collect_yfinance_quotes, write_quote_snapshot
from src.research_control_tower.registries import load_registry_bundle
from src.research_control_tower.southbound_holdings import collect_stage1_southbound


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-network-heavy", action="store_true")
    args = parser.parse_args()
    registries = load_registry_bundle(REPO_ROOT / "config" / "research_control_tower")
    quotes_path = REPO_ROOT / "data" / "normalized" / "research_control_tower" / "quote_snapshots_v1.parquet"
    result = collect_yfinance_quotes(
        registries.listings,
        entities=registries.entities,
        baskets=registries.baskets,
        basket_memberships=registries.basket_memberships,
        stage1_only=True,
    )
    write_quote_snapshot(result.frame, quotes_path, result=result)
    print(f"quotes {result.aggregate_status} rows={len(result.frame)}")
    southbound = collect_stage1_southbound(registries.listings, repo_root=REPO_ROOT)
    print(f"southbound listings={len(southbound)}")
    if not args.skip_network_heavy:
        identity = load_source_identity(
            REPO_ROOT / "config" / "research_control_tower" / "official_source_identity.csv"
        )
        filings, state = collect_official_filings(
            identity,
            lookback_days=30,
            output_dir=REPO_ROOT / "data" / "normalized" / "research_control_tower",
            raw_root=REPO_ROOT,
        )
        print(f"filings rows={len(filings)} states={len(state)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
