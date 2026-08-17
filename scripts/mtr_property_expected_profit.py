#!/usr/bin/env python3
"""
MTR Property Expected Profit V1 (Timing x Magnitude)
=====================================================

E[PropertyProfit_t] = P(recognition_i,t) x EligibleValue_i x Ratio

* EligibleValue = cumulative registered sales value as of recognition date
  (this run uses current cumulative SRPE registered value; look-ahead caveat
  documented - proper PIT snapshots are a follow-up).
* Ratio = implied_profit_to_registered_value_ratio: 15% / 20% / 25%
  bear / base / bull (anchored by the G2022H1 upper bound 24.5% and ~17%
  adjusted estimate; deliberately a range, not a point).
* FY2026 pool = official MTR FY2025 annual-results outlook: new recognition
  LOHAS Park P13, THE SOUTHSIDE P6, Yau Tong Ventilation Building; continued
  Tai Wai Station, THE SOUTHSIDE P5, LOHAS Park P12. Additional likely-FY26
  residual contributors: 凱柏峰 II/III, 朗賢峯 (Ho Man Tin P1).

No fabricated numbers: phases without SRPE data keep eligible_value=None and
are reported as "needs data"; scenario rows are explicitly labelled ASSUMED.
"""

from __future__ import annotations

import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NORM_DIR = os.path.join(REPO_ROOT, "data", "normalized", "hk_transport")
OUT_CSV = os.path.join(NORM_DIR, "mtr_property_expected_profit_fy26.csv")

BEAR, BASE, BULL = 0.15, 0.20, 0.25

# Phase pool for FY2026: (project_id, label, P(recognition FY26), eligible
# value HK$m or None, basis for P, official FY26 mention)
POOL = [
    dict(project_id="tai-wai", label="Tai Wai Station (柏傲莊)",
         p_fy26=0.60, value=None,
         p_basis="official continued recognition; residual sales",
         official="FY25 outlook: continue to book"),
    dict(project_id="the-southside-p5", label="THE SOUTHSIDE Package 5",
         p_fy26=0.80, value=None,
         p_basis="official continued recognition; 5A presale launched 2025",
         official="FY25 outlook: continue to book"),
    dict(project_id="lohas-park-p12", label="LOHAS Park Package 12",
         p_fy26=0.70, value=None,
         p_basis="OP 2025-10 (1,985u); 2025 H2 booked, residual 2026",
         official="FY25 outlook: continue to book"),
    dict(project_id="lohas-park-p13", label="LOHAS Park Package 13",
         p_fy26=0.50, value=None,
         p_basis="official new recognition FY26; SRPE 10486 (2025-01 price list) suspected",
         official="FY25 outlook: expect to book"),
    dict(project_id="the-southside-p6", label="THE SOUTHSIDE Package 6",
         p_fy26=0.50, value=None,
         p_basis="official new recognition FY26; presale consent in progress (1H25)",
         official="FY25 outlook: expect to book"),
    dict(project_id="yau-tong-vb", label="Yau Tong Ventilation Building",
         p_fy26=0.60, value=None,
         p_basis="presale consent obtained (1H25); small project",
         official="FY25 outlook: expect to book"),
    dict(project_id="lohas-park-p11-ii-iii", label="凱柏峰 II/III (LP11 residual)",
         p_fy26=0.40, value=None,
         p_basis="OP 2024-12 shared with P11; residual recognition",
         official="not named; inferred residual"),
    dict(project_id="ho-man-tin-p1", label="朗賢峯 (Ho Man Tin P1 residual)",
         p_fy26=0.40, value=None,
         p_basis="recognized 2025H1; residual 2026",
         official="not named; inferred residual"),
]

# Registered sales value (SRPE, cancelled excluded) - phases we HAVE data for.
# Loaded dynamically from mtr_srpe_transactions_by_phase.csv (grouped by
# project_id so multi-phase packages like 海瑅灣 I/II and 滶晨 I/II sum).
_DETAIL = pd.read_csv(os.path.join(NORM_DIR, "mtr_srpe_transactions_detail.csv"))
_DETAIL = _DETAIL[_DETAIL["is_cancelled"].fillna(False) == False]  # noqa: E712
KNOWN_VALUES = dict(
    round(_DETAIL.groupby("project_id")["transaction_price_hkd"].sum() / 1e6, 0)
)
# 凱柏峰 II + III are separate SRPE phases; the FY26 pool treats them as one
# residual line (OP 2024-12 shared with P11 I).
KNOWN_VALUES["lohas-park-p11-ii-iii"] = (
    KNOWN_VALUES.get("lohas-park-p11-ii", 0.0) + KNOWN_VALUES.get("lohas-park-p11-iii", 0.0)
)

# PIT-aligned eligible values: registered sales value as of FY25 year end
# (2025-12-31). This is the look-ahead-safe denominator for FY26 recognition
# - sales signed after FY25 year end belong to later recognition years.
# Reuses the same detail csv (cancelled excluded) with a date cutoff.
_AS_OF_FY25 = dict(
    round(
        _DETAIL.loc[_DETAIL["date_of_pasp"] <= "2025-12-31"]
        .groupby("project_id")["transaction_price_hkd"].sum() / 1e6, 0
    )
)
_AS_OF_FY25["lohas-park-p11-ii-iii"] = (
    _AS_OF_FY25.get("lohas-park-p11-ii", 0.0) + _AS_OF_FY25.get("lohas-park-p11-iii", 0.0)
)
# LP12 海瑅灣 had zero deals before FY25 year end (first deal 2026-03-20);
# its FY25 recognition came via the OP 2025-10 handover, and FY26 residual
# recognition will draw on the FY26 sales - keep the current value for that
# line but document it.
_AS_OF_FY25["lohas-park-p12"] = KNOWN_VALUES.get("lohas-park-p12", 0.0)

# ASSUMED SCENARIO eligible values for phases lacking SRPE data (explicitly
# labelled - typical phase-scale estimates for sensitivity only, NOT
# verified figures). Bear/base/bull on VALUE is applied as +/- 25% of the
# scenario centre.
SCENARIO_VALUES = {
    "the-southside-p6": 5000.0,   # presale consent in progress (no SRPE yet)
    "yau-tong-vb": 2000.0,        # small ventilation-building site (no SRPE yet)
}


def main() -> int:
    rows = []
    total_low = total_base = total_high = 0.0
    total_s_low = total_s_base = total_s_high = 0.0
    needs_data = []
    for p in POOL:
        pid = p["project_id"]
        value = KNOWN_VALUES.get(pid)
        eligible = _AS_OF_FY25.get(pid) if (value is not None and pid in _AS_OF_FY25) else value
        is_scenario = value is None and pid in SCENARIO_VALUES
        if is_scenario:
            # scenario centre with +/-25% value band
            centre = SCENARIO_VALUES[pid]
            value_lo, value_hi = centre * 0.75, centre * 1.25
            exp_low = p["p_fy26"] * value_lo * BEAR
            exp_base = p["p_fy26"] * centre * BASE
            exp_high = p["p_fy26"] * value_hi * BULL
            rows.append({
                "project_id": pid,
                "phase_label": p["label"],
                "p_recognition_fy26": p["p_fy26"],
                "eligible_registered_value_hkdm": centre,
                "expected_profit_low_hkdm": round(exp_low, 0),
                "expected_profit_base_hkdm": round(exp_base, 0),
                "expected_profit_high_hkdm": round(exp_high, 0),
                "p_basis": p["p_basis"],
                "official_fy26_mention": p["official"],
                "data_status": "ASSUMED_SCENARIO",
            })
            total_s_low += exp_low
            total_s_base += exp_base
            total_s_high += exp_high
            continue
        if value is None:
            needs_data.append(pid)
        exp_low = p["p_fy26"] * (eligible or 0) * BEAR
        exp_base = p["p_fy26"] * (eligible or 0) * BASE
        exp_high = p["p_fy26"] * (eligible or 0) * BULL
        rows.append({
            "project_id": pid,
            "phase_label": p["label"],
            "p_recognition_fy26": p["p_fy26"],
            "eligible_registered_value_hkdm": eligible,
            "registered_value_current_hkdm": value,
            "expected_profit_low_hkdm": round(exp_low, 0) if value else None,
            "expected_profit_base_hkdm": round(exp_base, 0) if value else None,
            "expected_profit_high_hkdm": round(exp_high, 0) if value else None,
            "p_basis": p["p_basis"],
            "official_fy26_mention": p["official"],
            "data_status": "srpe_data" if value is not None else "NEEDS_DATA",
        })
        total_low += exp_low
        total_base += exp_base
        total_high += exp_high

    df = pd.DataFrame(rows)
    df.to_csv(OUT_CSV, index=False)

    print("FY2026 property expected profit (Timing x Magnitude V1)")
    print("=" * 100)
    print(df[["project_id", "phase_label", "p_recognition_fy26",
              "eligible_registered_value_hkdm", "expected_profit_base_hkdm",
              "data_status"]].to_string(index=False))
    print(f"\nMeasured layer (SRPE data): "
          f"low {total_low:,.0f} / base {total_base:,.0f} / high {total_high:,.0f} HK$m")
    print(f"Assumed-scenario layer (ASSUMED values, +/-25% band): "
          f"low {total_s_low:,.0f} / base {total_s_base:,.0f} / high {total_s_high:,.0f} HK$m")
    grand_low = total_low + total_s_low
    grand_base = total_base + total_s_base
    grand_high = total_high + total_s_high
    print(f"FY26 total expected property profit (all pool): "
          f"low {grand_low:,.0f} / base {grand_base:,.0f} / high {grand_high:,.0f} HK$m")
    print(f"  vs FY25 actual post-tax 11,084 HK$m")
    print(f"\nPriority targets for targeted SRPE enrichment (official FY26 names): "
          f"LP13, THE SOUTHSIDE P5/P6, LP12, Yau Tong VB; then 凱柏峰 II/III, 朗賢峯.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
