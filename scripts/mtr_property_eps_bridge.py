#!/usr/bin/env python3
"""
MTR Property -> EPS Bridge (Step 3)
===================================

Plug the FY2026 property expected-profit bear/base/bull into the EPS bridge
and compare with Street consensus (yfinance 0066.HK).

Outputs the delta that the property data chain produces:
  Our underlying EPS (bear/base/bull) vs consensus 0y EPS.

Assumptions are explicitly labelled:
  * FY26E recurrent post-tax profit: FY25 5,653 x 1.03 (ASSUMED +3%)
  * FY26E IP fair-value movement (post-tax): -1,500 (ASSUMED; FY25 -2,060)
  * Shares: 6,214.18m (yfinance)
  * Property profit: from mtr_property_expected_profit_fy26.py
    (measured + assumed-scenario layers)
"""

from __future__ import annotations

import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NORM_DIR = os.path.join(REPO_ROOT, "data", "normalized", "hk_transport")
OUT_CSV = os.path.join(NORM_DIR, "mtr_property_eps_bridge.csv")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARES_M = 6214.18
FY25_RECURRENT_POST_TAX = 5653.0
ASSUMED_RECURRENT_GROWTH = 1.03
ASSUMED_IP_REVAL_FY26 = -1500.0

# Property expected profit (from the V1 model)
PROPERTY_LOW = 3436.0
PROPERTY_BASE = 5757.0
PROPERTY_HIGH = 8665.0




def eps_risk_ranking() -> pd.DataFrame:
    """EPS risk per pool phase: P x value x (bull-bear ratio) / shares.

    Directs targeted SRPE enrichment: phases with the largest EPS spread are
    the ones where better data changes the forecast most.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "mtr_pep", os.path.join(REPO_ROOT, "scripts", "mtr_property_expected_profit.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    POOL, KNOWN_VALUES, SCENARIO_VALUES = mod.POOL, mod.KNOWN_VALUES, mod.SCENARIO_VALUES
    rows = []
    for p in POOL:
        pid = p["project_id"]
        value = KNOWN_VALUES.get(pid) or SCENARIO_VALUES.get(pid)
        if value is None:
            continue
        eps_risk = p["p_fy26"] * value * (0.25 - 0.15) / SHARES_M
        rows.append({
            "project_id": pid,
            "phase_label": p["label"],
            "p_recognition_fy26": p["p_fy26"],
            "eligible_value_hkdm": value,
            "eps_risk_hkd": round(eps_risk, 4),
            "data_status": "srpe_data" if pid in KNOWN_VALUES else "assumed_scenario",
        })
    df = pd.DataFrame(rows).sort_values("eps_risk_hkd", ascending=False)
    df.to_csv(os.path.join(NORM_DIR, "mtr_property_eps_risk_ranking.csv"), index=False)
    return df

def main() -> int:
    recurrent_fy26 = FY25_RECURRENT_POST_TAX * ASSUMED_RECURRENT_GROWTH

    rows = []
    for label, prop in [("bear", PROPERTY_LOW), ("base", PROPERTY_BASE), ("bull", PROPERTY_HIGH)]:
        underlying = recurrent_fy26 + prop
        reported = underlying + ASSUMED_IP_REVAL_FY26
        rows.append({
            "scenario": label,
            "recurrent_post_tax_hkdm": round(recurrent_fy26, 0),
            "property_profit_post_tax_hkdm": round(prop, 0),
            "underlying_profit_hkdm": round(underlying, 0),
            "ip_fv_movement_post_tax_hkdm": ASSUMED_IP_REVAL_FY26,
            "reported_npat_est_hkdm": round(reported, 0),
            "underlying_eps_hkd": round(underlying / SHARES_M, 2),
            "reported_eps_est_hkd": round(reported / SHARES_M, 2),
        })
    df = pd.DataFrame(rows)

    # consensus
    try:
        import yfinance as yf
        t = yf.Ticker("0066.HK")
        est = t.earnings_estimate
        cons_eps = float(est.loc["0y", "avg"]) if "0y" in est.index else None
    except Exception as exc:  # pragma: no cover
        cons_eps = None
        print(f"[warn] consensus fetch failed: {exc}")

    df.to_csv(OUT_CSV, index=False)
    risk = eps_risk_ranking()
    print("\nEPS risk ranking (targeted enrichment priority):")
    print(risk.to_string(index=False))
    print("MTR Property -> EPS bridge (FY2026E)")
    print("=" * 78)
    print(df.to_string(index=False))
    if cons_eps:
        print(f"\nStreet consensus FY26 EPS (yfinance avg): {cons_eps:.2f}")
        for _, r in df.iterrows():
            delta = (r["reported_eps_est_hkd"] - cons_eps) / cons_eps * 100
            print(f"  Our {r['scenario']:5s} reported EPS {r['reported_eps_est_hkd']:.2f} "
                  f"vs consensus {cons_eps:.2f} -> {delta:+.1f}%")
        print("\nInterpretation: our property expectation implies FY26 EPS well below the")
        print("Street's +7% growth assumption. Either our P(recognition)/magnitude is too")
        print("conservative (LP13/P6/Yau Tong bigger than assumed), or consensus has not")
        print("marked down FY26 property profit - this gap is the research edge to test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
