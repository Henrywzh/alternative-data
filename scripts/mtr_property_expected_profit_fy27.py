#!/usr/bin/env python3
"""
MTR FY27 Property Expected Profit (research-horizon shift)
==========================================================

After FY26 reconciles with consensus, move the research horizon to FY27
property-recognition timing - where lumpy recognition and market error are
more likely.

Pool construction (conservative, official-first):
  * FY26-named projects with FY27 residual recognition (LP13, SOUTHSIDE P6,
    Yau Tong VB, P5, LP12)
  * sold-but-unrecognized inventory from SRPE data (凱柏峰 II/III, 朗賢峯,
    海盈山 II suspected 9346, SOUTHSIDE unlabelled phases 9827/9828)
  * forward projects (YOHO WEST PARKSIDE, Tung Chung East P1 - tendered)
  Values: SRPE registered sales where available; ASSUMED labelled otherwise.
  P(recognition FY27) is rule-based (presale year + 2-3y recognition window,
  OP status) - documented per row.

E[profit] = P x eligible value x 15/20/25% (same implied ratio anchor).
"""

from __future__ import annotations

import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NORM_DIR = os.path.join(REPO_ROOT, "data", "normalized", "hk_transport")
OUT_CSV = os.path.join(NORM_DIR, "mtr_property_expected_profit_fy27.csv")
SHARES_M = 6214.18

BEAR, BASE, BULL = 0.15, 0.20, 0.25

# project_id -> (label, P(FY27), value HK$m or None, value source, P basis)
POOL = [
    ("lohas-park-p13", "LP13", 0.80, None, "srpe_current_41.6bn", "2025 presale -> FY27 residual window"),
    ("the-southside-p6", "SOUTHSIDE P6", 0.70, None, "assumed_50bn", "presale in progress; FY27 main recognition"),
    ("the-southside-p5", "SOUTHSIDE P5 滶晨", 0.70, None, "srpe_139.8bn", "2025 presale; FY27 handover window"),
    ("lohas-park-p12", "LP12 海瑅灣", 0.60, None, "srpe_87.4bn", "2026 sales; FY27-28 handover"),
    ("yau-tong-vb", "Yau Tong VB", 0.30, None, "assumed_20bn", "small; mostly FY26"),
    ("lohas-park-p11-ii-iii", "凱柏峰 II/III residual", 0.40, None, "srpe_93.1bn", "OP 2024-12; residual"),
    ("ho-man-tin-p1", "朗賢峯 residual", 0.30, None, "srpe_31.4bn", "sold 2024; residual handover"),
    ("the-southside-p4-ii", "海盈山 II (suspected 9346)", 0.50, None, "assumed_30bn", "2026 price list; FY27-28"),
    ("yoho-west-parkside", "YOHO WEST PARKSIDE", 0.50, None, "assumed_50bn", "2025 presale (SHKP-MTR); FY27-28"),
    ("tung-chung-east-p1", "Tung Chung East P1", 0.0, None, "tendered_2024", "presale 2027+; recognition 2029+"),
]


def main() -> int:
    # Load SRPE values for phases we have data for
    det = pd.read_csv(os.path.join(NORM_DIR, "mtr_srpe_transactions_detail.csv"))
    det = det[det["is_cancelled"].fillna(False) == False]  # noqa: E712
    known = dict(round(det.groupby("project_id")["transaction_price_hkd"].sum() / 1e6, 0))
    known["lohas-park-p11-ii-iii"] = known.get("lohas-park-p11-ii", 0.0) + known.get("lohas-park-p11-iii", 0.0)

    assumed = {
        "the-southside-p6": 5000.0,
        "yau-tong-vb": 2000.0,
        "the-southside-p4-ii": 3000.0,
        "yoho-west-parkside": 5000.0,
    }

    rows = []
    for pid, label, p, _v, vsrc, pbasis in POOL:
        value = known.get(pid) or assumed.get(pid)
        rows.append({
            "project_id": pid,
            "phase_label": label,
            "p_recognition_fy27": p,
            "eligible_value_hkdm": value,
            "value_source": vsrc,
            "expected_profit_low_hkdm": round(p * value * BEAR, 0) if value else None,
            "expected_profit_base_hkdm": round(p * value * BASE, 0) if value else None,
            "expected_profit_high_hkdm": round(p * value * BULL, 0) if value else None,
            "p_basis": pbasis,
            "data_status": "srpe_data" if pid in known else "assumed_scenario",
        })

    df = pd.DataFrame(rows).sort_values("p_recognition_fy27", ascending=False)
    df.to_csv(OUT_CSV, index=False)

    low = df["expected_profit_low_hkdm"].fillna(0).sum()
    base = df["expected_profit_base_hkdm"].fillna(0).sum()
    high = df["expected_profit_high_hkdm"].fillna(0).sum()

    print("FY27 property expected profit (research horizon shift)")
    print("=" * 100)
    print(df[["project_id", "phase_label", "p_recognition_fy27", "eligible_value_hkdm",
              "expected_profit_base_hkdm", "data_status"]].to_string(index=False))
    print(f"\nFY27 total: low {low:,.0f} / base {base:,.0f} / high {high:,.0f} HK$m")
    print(f"FY26 total (for reference): base 6,330")
    eps_base = base / SHARES_M
    print(f"FY27 property profit EPS contribution (post-tax): {eps_base:.2f} (base)")
    print(f"\nNote: FY27 pool is broader and less understood than FY26 - this is")
    print(f"where consensus uncertainty (and variant perception) is materially higher.")
    print(f"Priorities to verify: LP13 identity/value, P6 scale, YOHO WEST PARKSIDE scale.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
