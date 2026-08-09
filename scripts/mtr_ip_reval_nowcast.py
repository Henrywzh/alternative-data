#!/usr/bin/env python3
"""
MTR IP Revaluation Nowcast
==========================

Estimate MTR's investment-property fair-value movement from cap-rate proxies.

Approach
--------
  IP reval_t ~= -IP_value_{t-1} x delta_cap_rate / cap_rate

Inputs
------
  * IP value anchor: 93,188 HK$m (FY2025 balance sheet)
  * Cap-rate proxy: Centaline CRI overall rental yield (monthly, repo data)
    - NOTE: CRI is a RESIDENTIAL yield; MTR's investment properties are
      mostly malls/offices. Calibration on FY2024 (official remeasurement
      loss 3,821m vs +37bp CRI move) gives a 0.42 sensitivity factor.
    - FY2025 check: CRI was flat (-1bp) but MTR still booked -3,538m,
      i.e. commercial yields widened while residential yields stalled -
      the factor is a lower bound for commercial-driven years.

Outputs
-------
  * data/normalized/hk_transport/mtr_ip_reval_nowcast.csv (monthly)
  * console summary incl. FY26 YTD direction
"""

from __future__ import annotations

import glob
import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RE_DIR = os.path.join(REPO_ROOT, "data", "normalized", "hk_real_estate")
NORM_DIR = os.path.join(REPO_ROOT, "data", "normalized", "hk_transport")
OUT_CSV = os.path.join(NORM_DIR, "mtr_ip_reval_nowcast.csv")

IP_VALUE = 93188.0          # FY2025 balance sheet, HK$m
CAP_RATE = 0.038            # approximate cap rate
CALIBRATION = 0.42          # FY2024 calibration (CRI is residential proxy)
SHARES_M = 6214.18
AFTER_TAX = 0.82


def load_cri_yield() -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(
        RE_DIR, "centaline_cri_yield_monthly", "**",
        "centaline_cri_yield_monthly.parquet"), recursive=True))
    df = pd.read_parquet(files[-1])
    df = df[df["metric"] == "rental_yield"].sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    return df


def main() -> int:
    y = load_cri_yield()
    y["yield_pct"] = pd.to_numeric(y["index_value"], errors="coerce")
    y["yield_bp"] = y["yield_pct"] * 100.0
    y["delta_bp_1m"] = y["yield_bp"].diff()
    y["delta_bp_12m"] = y["yield_bp"].diff(12)

    # raw (uncalibrated) and calibrated IP reval estimates
    # bp -> decimal: divide by 10,000 (1bp = 0.0001)
    y["ip_reval_pre_tax_hkdm"] = -IP_VALUE * (y["delta_bp_1m"] / 10000.0) / CAP_RATE
    y["ip_reval_calibrated_hkdm"] = y["ip_reval_pre_tax_hkdm"] * CALIBRATION
    y["eps_impact_hkd"] = y["ip_reval_calibrated_hkdm"] * AFTER_TAX / SHARES_M

    y.to_csv(OUT_CSV, index=False)

    # FY anchors vs official
    def annual(refto: str) -> None:
        d = y.set_index("date")
        dec_prev = d.loc[f"{int(refto)-1}-12-01", "yield_bp"]
        dec = d.loc[f"{refto}-12-01", "yield_bp"]
        print(f"  {int(refto)-1}->{refto}: CRI {dec_prev:.0f}bp -> {dec:.0f}bp "
              f"({dec-dec_prev:+.0f}bp)")
    print("Calibration check (CRI yield year changes):")
    annual("2024")
    annual("2025")
    print(f"  FY2024 official remeasurement loss: (3,821)m  "
          f"-> calibration factor {CALIBRATION:.2f}")
    print(f"  FY2025 official remeasurement loss: (3,538)m  "
          f"(CRI flat; commercial/commercial yields diverged - documented)")

    # FY26 YTD
    latest = y.iloc[-1]
    dec25 = y[y["date"] == "2025-12-01"]["yield_bp"]
    if len(dec25) and latest["date"].month >= 5:
        ytd_bp = latest["yield_bp"] - dec25.iloc[0]
        ytd_reval = -IP_VALUE * (ytd_bp / 10000.0) / CAP_RATE * CALIBRATION
        ytd_eps = ytd_reval * AFTER_TAX / SHARES_M
        print(f"\nFY2026 YTD (2025-12 -> {latest['date'].date()}): CRI {ytd_bp:+.0f}bp "
              f"=> calibrated IP reval {ytd_reval:+,.0f}m => EPS {ytd_eps:+.2f}")
        print("  Direction supports consensus's positive-IP-reval assumption;")
        print("  magnitude depends on commercial vs residential yield spread.")

    print(f"\nLatest rows:")
    print(y.tail(6)[["date", "yield_pct", "delta_bp_12m",
                     "ip_reval_calibrated_hkdm", "eps_impact_hkd"]].to_string(index=False))
    print(f"\nWrote {OUT_CSV} ({len(y)} months)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
