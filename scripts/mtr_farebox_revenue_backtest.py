#!/usr/bin/env python3
"""
MTR Farebox Revenue Backtest
============================

Purpose
-------
We only track MTR monthly patronage (passenger count), not ticket revenue.
MTR does not disclose monthly revenue, but it DOES disclose:
  * calendar-year passenger-service revenue by segment (annual results),
  * calendar-year Hong Kong transport operations revenue, and
  * the annual Fare Adjustment Mechanism (FAM) adjustment rate, which is the
    cumulative change in average fares (implemented every late June).

This script reconstructs a monthly farebox revenue estimate:

    farebox_revenue(m, y) = SUM_segments  patronage(seg, m, y) x yield(seg, y)

where the per-passenger yield anchors are calibrated to the disclosed FY2024
segment revenue divided by our own FY2024 patronage sums, and then evolved
backwards/forwards through the cumulative FAM adjustment series (the main
driver of average fares) with documented flat-yield assumptions for
Airport Express (fares frozen for years) and HSR (no FAM; fares set under
the mainland price framework).

The result is validated (backtested) against reported Hong Kong transport
operations revenue for 2019-2024.  Note that "passenger-service revenue"
(the farebox) was 22,908 of the 23,013 total transport operations revenue in
2024; the residual is "other transport revenue" (~0.5%), so the farebox
series should track the total series closely but slightly below it.

Anchors used (web-researched, source links in the docstring header):
  * FY2024 passenger-service revenue (HK$M): domestic 14,507; cross-boundary
    3,562; HSR & intercity 3,338; Airport Express 803; Light Rail & Bus 698;
    other transport revenue 105.  Source: MTR 2024 Annual Results.
  * FAM implemented adjustments 2010-2024 and the 2025/2026 fare freeze
    (announced 27 Mar 2026; second consecutive year without adjustment).
  * Historic HK transport operations revenue 2019-2024 used as the holdout
    actuals.

Assumptions / known limitations:
  * Pre-2010 (before FAM) yields are held flat at the 2010 level - fares did
    move in that era, but the backtest window only claims 2010+ accuracy.
  * Pre-2008 patronage covers MTR metro lines only: the MTR-KCR merger
    (Dec 2007) caused the sharp 2007->2008 step in the estimate, which is a
    coverage step, not a fare change.
  * Airport Express yield is held constant (AEL fares have largely been
    frozen); HSR yield is held constant from Sep 2018.  Intercity train
    revenue is included in the anchor but ceased in Jan 2020, so our HSR
    estimate slightly over-attributes early years - immaterial for 2020+.
  * FAM applies to average fares, not to journey-length mix: any drift in
    the long/short journey mix shows up as residual error.

Outputs
-------
  * data/processed/transport/mtr_farebox_revenue_monthly.csv
  * data/processed/transport/mtr_farebox_revenue_annual_backtest.csv
  * console summary table (annual estimates vs actuals + error metrics)

Usage
-----
    python scripts/mtr_farebox_revenue_backtest.py [--live]

By default the latest local raw snapshot of MTR patronage is used; --live
fetches the MTR investor-relations page instead (network required).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(REPO_ROOT, "data", "raw", "hk_transport")
OUT_DIR = os.path.join(REPO_ROOT, "data", "processed", "transport")
os.makedirs(OUT_DIR, exist_ok=True)

MONTHLY_CSV = os.path.join(OUT_DIR, "mtr_farebox_revenue_monthly.csv")
ANNUAL_CSV = os.path.join(OUT_DIR, "mtr_farebox_revenue_annual_backtest.csv")

# ---------------------------------------------------------------------------
# Web-researched anchors (sources cited in the module docstring)
# ---------------------------------------------------------------------------

# FY2024 passenger-service revenue split, HK$M (MTR 2024 annual results).
SEGMENT_REVENUE_2024_HKDM = {
    "domestic_service": 14507.0,
    "cross_boundary": 3562.0,
    "hsr": 3338.0,  # HSR + intercity combined disclosure
    "airport_express": 803.0,
    "light_rail_bus": 698.0,
}

# Reported HK transport operations revenue, HK$M (annual results).
TRANSPORT_OPS_REVENUE_HKDM = {
    2019: 19938.0,
    2020: 11896.0,
    2021: 13177.0,
    2022: 13404.0,
    2023: 20131.0,
    2024: 23013.0,
}

# FAM implemented adjustment (%, effective late June each year). 2025 and 2026
# were frozen (announced 27 Mar 2026 - second consecutive year without
# adjustment).
FAM_PCT = {
    2010: 2.05, 2011: 2.20, 2012: 5.40, 2013: 2.70, 2014: 3.60,
    2015: 4.30, 2016: 2.65, 2017: 0.00, 2018: 3.14, 2019: 3.30,
    2020: 0.00, 2021: -1.85, 2022: 0.00, 2023: 2.30, 2024: 3.09,
    2025: 0.00, 2026: 0.00,
}

# FAM-driven segments vs flat-yield segments.
FAM_SEGMENTS = {"domestic_service", "cross_boundary", "light_rail_bus"}
FLAT_SEGMENTS = {"airport_express", "hsr"}


def _load_patronage(live: bool) -> pd.DataFrame:
    """Load MTR monthly patronage from the latest raw snapshot or live fetch."""
    if live:
        try:
            sys.path.insert(0, REPO_ROOT)
            from src.hk_transport.sources.mtr_patronage import fetch_mtr_patronage

            df = fetch_mtr_patronage()
            df = df.rename(columns={"date": "month"})
        except Exception as exc:  # pragma: no cover - network fallback
            print(f"[warn] live fetch failed ({exc}); falling back to snapshot")
            live = False
    if not live:
        snapshots = sorted(glob.glob(os.path.join(RAW_DIR, "mtr_patronage_*.json")))
        if not snapshots:
            raise SystemExit("no local MTR patronage snapshots found")
        with open(snapshots[-1], "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        df = pd.DataFrame(raw["data"])
        df["month"] = pd.to_datetime(df["month"]).dt.to_period("M")
    df["month_dt"] = df["month"].dt.to_timestamp()
    df = df.sort_values("month_dt").reset_index(drop=True)
    return df


def _calibrate_yields(pat: pd.DataFrame) -> dict[str, float]:
    """Calibrate per-passenger yields (HK$) from FY2024 disclosed revenue."""
    pat24 = pat[pat["month_dt"].dt.year == 2024]
    yields: dict[str, float] = {}
    for seg, revenue_hkdm in SEGMENT_REVENUE_2024_HKDM.items():
        col = f"{seg}_thousands"
        patronage_m = pat24[col].sum() / 1000.0  # thousands -> millions
        if patronage_m <= 0:
            raise SystemExit(f"no FY2024 patronage for {seg}")
        yields[seg] = revenue_hkdm / patronage_m
    return yields


def _yield_for_year(yields: dict[str, float], year: int) -> dict[str, float]:
    """Evolve calibrated yields to a given calendar year via cumulative FAM."""
    out: dict[str, float] = {}
    for seg in FAM_SEGMENTS:
        mult = 1.0
        # FAM only exists from 2010 onward; before that yields are held flat
        # at the 2010 level (documented assumption).
        fam_years = [y for y in FAM_PCT if 2010 <= y]
        if year < 2024:
            for y in range(max(year + 1, 2011), 2025):
                mult /= 1.0 + FAM_PCT[y] / 100.0
        elif year > 2024:
            for y in range(2025, min(year, max(fam_years)) + 1):
                mult *= 1.0 + FAM_PCT[y] / 100.0
        out[seg] = yields[seg] * mult
    for seg in FLAT_SEGMENTS:
        out[seg] = yields[seg]
    return out


def _build_monthly_series(pat: pd.DataFrame, yields24: dict[str, float]) -> pd.DataFrame:
    rows = []
    for _, row in pat.iterrows():
        year = row["month_dt"].year
        y = _yield_for_year(yields24, year)
        est = sum(row[f"{seg}_thousands"] * y[seg] for seg in SEGMENT_REVENUE_2024_HKDM)
        rows.append(
            {
                "month": row["month"],
                "date": row["month_dt"],
                "farebox_revenue_hkdm": est / 1000.0,  # thousands -> HK$M
            }
        )
    out = pd.DataFrame(rows)
    # Segment-level detail for transparency.
    out["year"] = out["date"].dt.year
    for seg in SEGMENT_REVENUE_2024_HKDM:
        out[f"{seg}_yield_hkd"] = out["year"].apply(
            lambda yr: _yield_for_year(yields24, yr)[seg]
        )
        out[f"{seg}_rev_hkdm"] = [
            row[f"{seg}_thousands"]
            * _yield_for_year(yields24, row["month_dt"].year)[seg]
            / 1000.0
            for _, row in pat.iterrows()
        ]
    return out


def _annualize(monthly: pd.DataFrame) -> pd.DataFrame:
    ann = (
        monthly.groupby("year")
        .agg(farebox_revenue_hkdm=("farebox_revenue_hkdm", "sum"))
        .reset_index()
    )
    ann["transport_ops_revenue_hkdm"] = ann["year"].map(TRANSPORT_OPS_REVENUE_HKDM)
    ann["coverage_pct"] = (
        ann["farebox_revenue_hkdm"] / ann["transport_ops_revenue_hkdm"] * 100.0
    )
    ann["model_error_pct"] = (
        (ann["farebox_revenue_hkdm"] - ann["transport_ops_revenue_hkdm"])
        / ann["transport_ops_revenue_hkdm"]
        * 100.0
    )
    return ann


def main() -> int:
    parser = argparse.ArgumentParser(description="MTR farebox revenue backtest")
    parser.add_argument("--live", action="store_true", help="fetch patronage from MTR website")
    args = parser.parse_args()

    pat = _load_patronage(args.live)
    yields24 = _calibrate_yields(pat)
    print("Calibrated FY2024 per-passenger yields (HK$):")
    for seg, y in yields24.items():
        print(f"  {seg:18s} {y:8.3f}")

    monthly = _build_monthly_series(pat, yields24)
    monthly.to_csv(MONTHLY_CSV, index=False)
    annual = _annualize(monthly)
    annual.to_csv(ANNUAL_CSV, index=False)

    print("\nAnnual backtest (HK$M):")
    print(
        annual[
            [
                "year",
                "farebox_revenue_hkdm",
                "transport_ops_revenue_hkdm",
                "coverage_pct",
                "model_error_pct",
            ]
        ].to_string(index=False, float_format=lambda v: f"{v:,.1f}")
    )

    # Holdout MAPE: 2019-2023 (2024 is the calibration year).
    holdout = annual[
        annual["transport_ops_revenue_hkdm"].notna() & (annual["year"] < 2024)
    ]
    if not holdout.empty:
        mape = holdout["model_error_pct"].abs().mean()
        worst = holdout.loc[holdout["model_error_pct"].abs().idxmax()]
        print(
            f"\nHoldout MAPE 2019-2023 (calibration year 2024 excluded): {mape:.2f}%"
        )
        print(
            f"Worst year: {worst['year']} ({worst['model_error_pct']:+.2f}%)"
        )

    print(
        f"\nWrote {MONTHLY_CSV} ({len(monthly)} months, "
        f"{monthly['date'].min():%Y-%m} to {monthly['date'].max():%Y-%m})"
    )
    print(f"Wrote {ANNUAL_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
