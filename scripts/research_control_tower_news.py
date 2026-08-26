#!/usr/bin/env python3
"""Collect Marketaux/Finnhub news metadata for Control Tower overlays."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# src/ too, as the other collectors here already do: pyproject maps these
# packages to the top level (package-dir = {"" = "src"}) and they import each
# other by those names, so the repo root alone is not enough.
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from research_control_tower.live_refresh import load_news_api_keys
from research_control_tower.news_collector import collect_news
from research_control_tower.registries import load_news_entity_aliases, load_registry_bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "data" / "normalized" / "marts")
    parser.add_argument("--providers", default="marketaux,finnhub")
    parser.add_argument("--lookback-days", type=int, default=14)
    args = parser.parse_args()
    registries = load_registry_bundle(REPO_ROOT / "config" / "research_control_tower")
    aliases = load_news_entity_aliases(
        REPO_ROOT / "config" / "research_control_tower" / "news_entity_aliases.csv"
    )
    keys = load_news_api_keys(REPO_ROOT)
    providers = tuple(item.strip() for item in args.providers.split(",") if item.strip())
    written, results = collect_news(
        args.output_dir,
        providers=providers,
        api_keys=keys,
        listings=registries.listings,
        entities=registries.entities,
        aliases=aliases,
        lookback_days=args.lookback_days,
        max_rows_per_symbol=20,
    )
    for result in results:
        print(
            f"{result.provider}: status={result.aggregate_status} rows={len(result.frame)} "
            f"path={written.get(result.source_id)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
