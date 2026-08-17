#!/usr/bin/env python3
"""
MTR Broker-Level Consensus Snapshot & Reverse Engineering
=========================================================

Freezes the 2026-08-09 broker consensus for 0066.HK (external verification
provided by the user from ET Net / MarketScreener; dates recorded so the
2026-08-13 interim results can be compared against revisions).

Verified readings (2026-08-09):
  * FY25 actual reported EPS: 2.36 (official)
  * FY26E consensus: ET Net consolidated 2.69 (5 brokers 2.39-3.23);
    another aggregate (12 analysts) 2.76. yfinance 0y 2.52 appears to be a
    misread of YEAR_AGO_EPS - 2.69 is the more credible FY26 reading.
  * FY27E: JPM 1.87 / CLSA 0.943 / MS 1.65 / Citi 1.43 / UBS 1.72;
    ET Net consolidated 1.65, simple mean ~1.52. Dispersion 0.94-1.87 is a
    large Street-visibility signal.
  * FY28E: ~1.26.

Reverse engineering per broker:
  FY27 NPAT = EPS x 6,214.18m shares
  Residual for property + IP reval + one-offs =
      FY27 NPAT - assumed recurrent profit (FY26 5,653 x 1.03 = 5,823;
      FY27 ~6,000 flat assumption, ASSUMED)
  => compared against our FY27 property pool base (6,222m).

Outputs:
  * data/normalized/hk_transport/mtr_broker_consensus_snapshot.csv
"""

from __future__ import annotations

import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NORM_DIR = os.path.join(REPO_ROOT, "data", "normalized", "hk_transport")
OUT_CSV = os.path.join(NORM_DIR, "mtr_broker_consensus_snapshot.csv")

SHARES_M = 6214.18
SNAPSHOT_DATE = "2026-08-09"
NEXT_EARNINGS = "2026-08-13"

# FY27 EPS estimates (ET Net, verified 2026-08-09)
BROKERS = [
    ("JPMorgan", 2.75, 1.87),
    ("CLSA", 3.23, 0.943),
    ("Morgan Stanley", 2.51, 1.65),
    ("Citi", 2.39, 1.43),
    ("UBS", 2.69, 1.72),
]

# FY27 recurrent profit assumption (ASSUMED; FY25 5,653 x 1.03, flat into FY27)
ASSUMED_FY27_RECURRENT = 6000.0

OUR_FY27_PROPERTY_BASE = 6222.0  # HK$m, from mtr_property_expected_profit_fy27.py


def main() -> int:
    rows = []
    for name, fy26, fy27 in BROKERS:
        npat27 = fy27 * SHARES_M
        residual = npat27 - ASSUMED_FY27_RECURRENT
        delta_vs_ours = residual - OUR_FY27_PROPERTY_BASE
        rows.append({
            "broker": name,
            "fy26_eps": fy26,
            "fy27_eps": fy27,
            "fy27_implied_decline_pct": round((fy27 / fy26 - 1) * 100, 1),
            "fy27_npat_hkdm": round(npat27, 0),
            "fy27_residual_prop_ip_oneoffs_hkdm": round(residual, 0),
            "delta_vs_our_property_base_hkdm": round(delta_vs_ours, 0),
            "snapshot_date": SNAPSHOT_DATE,
        })
    df = pd.DataFrame(rows)
    df.to_csv(OUT_CSV, index=False)

    print("MTR broker-level consensus snapshot (2026-08-09, pre-interim)")
    print("=" * 108)
    print(df.to_string(index=False))
    print(f"\nAssumed FY27 recurrent profit: {ASSUMED_FY27_RECURRENT:,.0f} HK$m (flat, ASSUMED)")
    print(f"Our FY27 property pool base: {OUR_FY27_PROPERTY_BASE:,.0f} HK$m")
    print(f"\nKEY QUESTION: brokers leave {df['fy27_residual_prop_ip_oneoffs_hkdm'].min():,.0f} to "
          f"{df['fy27_residual_prop_ip_oneoffs_hkdm'].max():,.0f} HK$m for property + IP reval + "
          f"one-offs. Our property base alone is {OUR_FY27_PROPERTY_BASE:,.0f} HK$m - implying "
          f"negative/zero IP reval and one-offs for most brokers.")
    print(f"\nNext event: interim results {NEXT_EARNINGS} - re-snapshot to capture revisions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
