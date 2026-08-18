#!/usr/bin/env python3
"""Build a Research Control Tower generation from this repository's own data.

The Control Tower builder is path-explicit and network-free: it reads
standardized local inputs and publishes an immutable generation.  Which files
those are was, until now, decided at the call site, so nothing connected the
builder to the datasets this repository already collects.  The result was a
dashboard reporting ``fred_observations`` as ``optional_source_not_configured``
while ``data/normalized/fred_macro/fred_observations.parquet`` sat beside it
with 19,757 rows.

This script is that missing wiring, and the single place where the mapping
from a Control Tower ``source_id`` to a local file is recorded.

Inputs come from two places:

* ``REPO_SOURCES`` -- datasets this repository's own pipelines already
  produce.  Nothing needs to be collected for these; they satisfy the
  Control Tower's schema contracts as they stand.
* ``COLLECTOR_SOURCES`` -- outputs of the Control Tower's own collectors
  under ``scripts/research_control_tower_*.py``, which reach the network and
  must be run separately.  Each is optional here: a missing one is reported
  by name and the build continues, because a partial build with the reason
  stated is more useful than no build.

Usage::

    python scripts/build_research_control_tower.py
    python scripts/build_research_control_tower.py --publish
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import uuid

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_control_tower.build import (  # noqa: E402
    BuildConfig,
    LocalInput,
    build_control_tower_marts,
)

REGISTRY_ROOT = REPO_ROOT / "config" / "research_control_tower"
PUBLISH_DIR = REPO_ROOT / "apps" / "research-control-tower" / ".generated"
COLLECTOR_DIR = REPO_ROOT / "data" / "normalized" / "research_control_tower"

# (build kind, source_id, path relative to the repo root, expected schema,
#  pit_class, license_class, cadence, source_url)
#
# pit_class is inherited from what the local dataset actually is, never
# upgraded here.  None of these carry revision vintages -- the FRED extract
# has no realtime_start/realtime_end, so it is a current-vintage snapshot and
# says so.  Declaring otherwise would launder provenance: a research result
# would look point-in-time reproducible when it is not.
REPO_SOURCES: tuple[tuple[str, str, str, str, str, str, str, str], ...] = (
    (
        "macro", "fred_observations",
        "data/normalized/fred_macro/fred_observations.parquet",
        "fred_observations_v1", "current_vintage", "official_public",
        "daily", "https://fred.stlouisfed.org/",
    ),
    (
        "macro", "fred_series_meta",
        "data/normalized/fred_macro/fred_series_meta.parquet",
        "fred_series_meta_v1", "current_vintage", "official_public",
        "daily", "https://fred.stlouisfed.org/",
    ),
    (
        "macro", "ofr_timeseries",
        "data/normalized/ofr_macro/ofr_timeseries.parquet",
        "ofr_timeseries_v1", "current_vintage", "official_public",
        "daily", "https://www.financialresearch.gov/",
    ),
    (
        "macro", "ofr_mnemonics",
        "data/normalized/ofr_macro/ofr_mnemonics.parquet",
        "ofr_mnemonics_v1", "current_vintage", "official_public",
        "daily", "https://www.financialresearch.gov/",
    ),
    (
        "macro", "tw_monthly_revenue",
        "data/normalized/taiwan_semiconductor_revenue/tw_monthly_revenue.parquet",
        "tw_monthly_revenue_v1", "current_vintage", "official_public",
        "monthly", "https://mops.twse.com.tw/",
    ),
    (
        # Collected by the hk-transport airline pipeline as airline_fx_rates;
        # the Control Tower's schema alias already maps that name onto
        # ecb_fx_rates_v1, so it is the same contract under two labels.
        "macro", "ecb_fx_rates",
        "data/normalized/hk_transport/airline_fx_rates.parquet",
        "ecb_fx_rates_v1", "current_vintage", "official_public",
        "daily", "https://www.ecb.europa.eu/stats/eurofxref/",
    ),
    (
        "filing", "filings_sec_edgar",
        "data/normalized/sec_edgar/edgar_filings.parquet",
        "sec_edgar_filings_v1", "current_vintage", "official_public",
        "daily", "https://www.sec.gov/edgar",
    ),
)

# Produced by the Control Tower's own network-reaching collectors.  Absent
# until those are run; see --help output for the commands.
COLLECTOR_SOURCES: tuple[tuple[str, str, str, str, str, str, str, str], ...] = (
    (
        "official_filing", "official_filings",
        "data/normalized/research_control_tower/official_filings_v1.parquet",
        "official_filings_v1", "current_vintage", "official_public",
        "daily", "https://www.sec.gov/edgar",
    ),
    (
        "official_filing", "official_filings_state",
        "data/normalized/research_control_tower/official_filings_state.parquet",
        "source_state_v1", "current_vintage", "official_public",
        "daily", "",
    ),
    (
        "earnings", "earnings_actuals",
        "data/normalized/research_control_tower/earnings_actuals_v1.parquet",
        "earnings_actuals_v1", "current_vintage", "official_public",
        "quarterly", "https://www.sec.gov/edgar",
    ),
    (
        "earnings", "earnings_actuals_state",
        "data/normalized/research_control_tower/earnings_actuals_state.parquet",
        "source_state_v1", "current_vintage", "official_public",
        "quarterly", "",
    ),
    (
        "market", "quote_snapshots",
        "data/normalized/research_control_tower/quote_snapshots_v1.parquet",
        "quote_snapshots_v1", "snapshot_from_delayed_source", "personal_use_terms_unverified",
        "intraday", "https://finance.yahoo.com/",
    ),
)

COLLECTOR_COMMANDS = {
    "official_filings": (
        "python scripts/research_control_tower_official_filings.py "
        "--identity config/research_control_tower/official_source_identity.csv "
        f"--output-dir {COLLECTOR_DIR.relative_to(REPO_ROOT)}"
    ),
    "earnings_actuals": (
        "python scripts/research_control_tower_earnings_actuals.py "
        "--identity config/research_control_tower/official_source_identity.csv "
        f"--output-dir {COLLECTOR_DIR.relative_to(REPO_ROOT)}"
    ),
    "quote_snapshots": (
        "python scripts/research_control_tower_quote_collector.py "
        "--listings config/research_control_tower/listings.csv "
        f"--output {COLLECTOR_DIR.relative_to(REPO_ROOT)}/quote_snapshots_v1.parquet"
    ),
}


def _descriptor(row: tuple[str, str, str, str, str, str, str, str]) -> tuple[str, LocalInput]:
    kind, source_id, rel_path, schema, pit_class, license_class, cadence, url = row
    return kind, LocalInput(
        source_id=source_id,
        path=REPO_ROOT / rel_path,
        format="parquet",
        expected_schema=schema,
        pit_class=pit_class,
        license_class=license_class,
        cadence=cadence,
        source_url=url or None,
    )


def _collect_inputs(verbose: bool = True) -> tuple[dict[str, list[LocalInput]], list[str]]:
    by_kind: dict[str, list[LocalInput]] = {
        "macro": [], "news": [], "filing": [],
        "official_filing": [], "earnings": [], "market": [],
    }
    missing: list[str] = []
    for row in REPO_SOURCES + COLLECTOR_SOURCES:
        kind, descriptor = _descriptor(row)
        if descriptor.path.is_file():
            by_kind[kind].append(descriptor)
            if verbose:
                rows = len(pd.read_parquet(descriptor.path))
                rel = descriptor.path.relative_to(REPO_ROOT)
                print(f"  wired   {descriptor.source_id:24s} {rows:>7,} rows  {rel}")
        else:
            missing.append(descriptor.source_id)
            if verbose:
                rel = descriptor.path.relative_to(REPO_ROOT)
                print(f"  absent  {descriptor.source_id:24s} {'':>7s}       {rel}")
    return by_kind, missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="where to write the generation (default: a temporary staging dir)",
    )
    parser.add_argument(
        "--publish", action="store_true",
        help=f"write into {PUBLISH_DIR.relative_to(REPO_ROOT)} and move CURRENT to the new generation",
    )
    parser.add_argument("--as-of-utc", default=None, help="default: now")
    parser.add_argument("--build-id", default=None)
    args = parser.parse_args(argv)

    as_of = pd.Timestamp(args.as_of_utc) if args.as_of_utc else pd.Timestamp.now(tz="UTC")
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    build_id = args.build_id or f"local-sources-{as_of.strftime('%Y%m%dT%H%M%SZ')}"

    if args.publish:
        output_dir = PUBLISH_DIR
    elif args.output_dir is not None:
        output_dir = args.output_dir
    else:
        output_dir = REPO_ROOT / ".rct-staging" / uuid.uuid4().hex[:12]

    print(f"as_of  {as_of.isoformat()}")
    print(f"build  {build_id}")
    print("inputs:")
    by_kind, missing = _collect_inputs()

    config = BuildConfig(
        registry_root=REGISTRY_ROOT,
        event_root=REGISTRY_ROOT,
        output_dir=output_dir,
        as_of_utc=as_of,
        build_id=build_id,
        macro_inputs=tuple(by_kind["macro"]),
        news_inputs=tuple(by_kind["news"]),
        filing_inputs=tuple(by_kind["filing"]),
        official_filing_inputs=tuple(by_kind["official_filing"]),
        earnings_inputs=tuple(by_kind["earnings"]),
        quote_inputs=tuple(by_kind["market"]),
    )
    manifest = build_control_tower_marts(config)

    print(f"\nbuild status: {manifest.status}")
    print("artifacts:")
    for name, artifact in sorted(manifest.artifacts.items()):
        if name == "build_manifest.json":
            continue
        rows = artifact["row_count"] if isinstance(artifact, dict) else artifact.row_count
        status = artifact["status"] if isinstance(artifact, dict) else artifact.status
        print(f"  {name:34s} {rows:>7,} rows  {status}")

    if missing:
        print("\nnot built -- these collectors have not been run:")
        for source_id in missing:
            command = COLLECTOR_COMMANDS.get(source_id)
            print(f"  {source_id}")
            if command:
                print(f"      {command}")
    print(f"\noutput: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
