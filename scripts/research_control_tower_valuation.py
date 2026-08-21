"""Offline collector and calculator for valuation snapshots and internal estimates.

Generates valuation_snapshots and internal_estimates data marts for Research Control Tower.
Follows strict fail-closed validation, offline deterministic execution, and currency alignment logging.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pandas as pd

from src.research_control_tower.valuation import (
    INTERNAL_ESTIMATES_COLUMNS,
    VALUATION_SNAPSHOTS_COLUMNS,
    ValuationInput,
    build_valuation_snapshot_row,
    load_internal_estimates_csv,
    validate_internal_estimates_df,
    validate_valuation_snapshots_df,
)


logger = logging.getLogger(__name__)


def compute_tencent_valuation_snapshots(
    quote_snapshots_df: pd.DataFrame | None,
    consensus_snapshots_df: pd.DataFrame | None,
    earnings_actuals_df: pd.DataFrame | None,
    fx_rates_df: pd.DataFrame | None = None,
    as_of_utc: datetime | None = None,
) -> pd.DataFrame:
    """Compute valuation snapshots for Tencent (0700_HK) only when verified inputs exist.

    If inputs are missing or unverified, returns an empty DataFrame with standard columns.
    Never fabricates or hardcodes multiples without local source records.
    """
    rows: list[dict] = []
    current_asof = as_of_utc or datetime.now(timezone.utc)

    if quote_snapshots_df is None or quote_snapshots_df.empty:
        return pd.DataFrame(columns=VALUATION_SNAPSHOTS_COLUMNS)

    # Filter for 0700_HK quote
    t_quotes = quote_snapshots_df[quote_snapshots_df["listing_id"] == "0700_HK"]
    if t_quotes.empty:
        return pd.DataFrame(columns=VALUATION_SNAPSHOTS_COLUMNS)

    latest_quote = t_quotes.sort_values(by="retrieved_at_utc", ascending=False).iloc[0]
    price = latest_quote.get("price")
    quote_ref = latest_quote.get("quote_snapshot_id", "quote:0700_HK_latest")
    quote_curr = str(latest_quote.get("currency", "HKD")).upper().strip()

    # If we have valid consensus EPS for FY1 (e.g. FY26E)
    if consensus_snapshots_df is not None and not consensus_snapshots_df.empty:
        t_cons = consensus_snapshots_df[
            (consensus_snapshots_df["listing_id"] == "0700_HK")
            & (consensus_snapshots_df["metric"] == "diluted_eps")
            & (consensus_snapshots_df["horizon"].isin(["FY1", "FY26"]))
        ]
        if not t_cons.empty:
            cons_row = t_cons.sort_values(by="retrieved_at_utc", ascending=False).iloc[0]
            eps_val = cons_row.get("value")
            eps_curr = str(cons_row.get("currency", "CNY")).upper().strip()
            snap_ref = cons_row.get("snapshot_id", "cons:0700_HK_eps")
            basis = cons_row.get("metric_basis", "NON_IFRS_MANAGEMENT")

            if price and eps_val and eps_val > 0:
                fx_rate = None
                fx_src = None
                fx_ts = None
                if quote_curr != eps_curr:
                    # If currency conversion needed, must be explicitly provided
                    pass
                
                if quote_curr == eps_curr or (fx_rate is not None and fx_src is not None):
                    inp = ValuationInput(
                        listing_id="0700_HK",
                        valuation_at=current_asof,
                        metric_name="forward_pe",
                        metric_basis=basis,
                        numerator_value=float(price),
                        numerator_currency=quote_curr,
                        numerator_ref=str(quote_ref),
                        denominator_value=float(eps_val),
                        denominator_currency=eps_curr,
                        denominator_ref=str(snap_ref),
                        fx_rate_applied=fx_rate,
                        fx_source=fx_src,
                        fx_snapshot_at_utc=fx_ts,
                        source_id="valuation_collector",
                        pit_class="snapshot_from_delayed_source",
                        percentile_history_status="unavailable",
                    )
                    rows.append(build_valuation_snapshot_row(inp))

    if not rows:
        return pd.DataFrame(columns=VALUATION_SNAPSHOTS_COLUMNS)

    df = pd.DataFrame(rows)
    issues = validate_valuation_snapshots_df(df)
    if issues:
        raise ValueError(f"Generated valuation snapshots failed validation: {issues}")
    return df


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect and build valuation and internal estimates marts")
    parser.add_argument("--config-dir", type=Path, default=Path("config/research_control_tower"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/research_control_tower"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    logger.info("Loading internal estimates from %s", args.config_dir)

    est_csv = args.config_dir / "internal_estimates.csv"
    est_df = load_internal_estimates_csv(est_csv)
    est_issues = validate_internal_estimates_df(est_df)
    if est_issues:
        logger.error("Internal estimates validation failed: %s", est_issues)
        return 1

    logger.info("Internal estimates validated successfully. Total rows: %d", len(est_df))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

