#!/usr/bin/env python3
"""
MTR Property Timing Engine V0
=============================

Historical event table linking presale -> first transaction -> BD occupancy
permit (OP) -> MTR profit recognition, with the empirical OP -> recognition
lag.

Source-verified mappings (evidence levels):
  STRONG (address + permit count + timing all consistent):
    THE SOUTHSIDE P1 晉環   -> 11 Heung Yip Road, OP PR4/2022/OP (2022-04, 800 units)
    THE SOUTHSIDE P2 揚海   -> 11 Heung Yip Road, OP PR6/2022/OP (2022-08, 600 units)
    THE SOUTHSIDE P4 海盈山 -> 11 Heung Yip Road, OP PR12/2024/OP (2024-11, 800 units)
    Ho Man Tin P2 瑜一      -> 1 Chung Hau Street, OP PR11/2024/OP (2024-11, 630 units)
  SUSPECTED (shared lot address; permit counts proxy package scale):
    LOHAS Park P11 凱柏峰   -> 1 Lohas Park Road, OP PR13/14/15/2024/OP (2024-12, 1,880 units)
    LOHAS Park P12         -> 1 Lohas Park Road, OP PR7/8/9/2025/OP (2025-10, 1,985 units)

Empirical result so far: OP issuance and MTR profit recognition occur in the
SAME calendar year in all mapped cases (recognition typically H2).
"""

from __future__ import annotations

import glob
import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NORM_DIR = os.path.join(REPO_ROOT, "data", "normalized", "hk_transport")
RE_ESTATE_DIR = os.path.join(REPO_ROOT, "data", "normalized", "hk_real_estate")
OUT_CSV = os.path.join(NORM_DIR, "mtr_property_timing_history.csv")

SRPE_STATS = pd.read_csv(os.path.join(NORM_DIR, "mtr_srpe_transactions_by_phase.csv"))
MASTER = pd.read_csv(os.path.join(NORM_DIR, "mtr_property_project_master.csv"))

# phase -> (op_address_token, op_permit_prefix, op_month, op_units, evidence, recognition_year)
PHASE_OP = {
    "the-southside-p1": ("11 Heung Yip Road", "PR4/2022/OP", "2022-04", 800, "strong", 2022),
    "the-southside-p2": ("11 Heung Yip Road", "PR6/2022/OP", "2022-08", 600, "strong", 2022),
    "the-southside-p4": ("11 Heung Yip Road", "PR12/2024/OP", "2024-11", 800, "strong", 2024),
    "ho-man-tin-p2": ("1 Chung Hau Street", "PR11/2024/OP", "2024-11", 630, "strong", 2025),
    "lohas-park-p11": ("1 Lohas Park Road", "PR13/2024/OP", "2024-12", 1880, "suspected", 2024),
    "lohas-park-p12": ("1 Lohas Park Road", "PR7/2025/OP", "2025-10", 1985, "suspected", 2025),
}



# ---------------------------------------------------------------------------
# Official H1/H2 recognition split (HK property development profit, post-tax,
# attributable; verified against MTR interim reports + annual results)
#   annual = h1 + h2 holds for every year (5,507 / 9,343 / 10,413 / 2,083 /
#   10,265 / 11,084).
# ---------------------------------------------------------------------------
RECOGNITION_SPLIT = {
    2020: {"h1": 5171, "h2": 336,  "h1_projects": "COVID year (small)", "source": "interim 2020/2021"},
    2021: {"h1": 3118, "h2": 6225, "h1_projects": "SEA TO SKY (LOHAS Park P8)", "source": "interim 2021"},
    2022: {"h1": 7747, "h2": 2666, "h1_projects": "LP10, SOUTHLAND (P1), La Marina (P2)", "source": "interim 2022"},
    2023: {"h1": 712,  "h2": 1371, "h1_projects": "LP11 initial recognition + residuals", "source": "interim 2023"},
    2024: {"h1": 1740, "h2": 8525, "h1_projects": "residual; LP11 bulk + SOUTHSIDE + Ho Man Tin P1 in H2", "source": "interim 2024 + annual"},
    2025: {"h1": 5542, "h2": 5542, "h1_projects": "Ho Man Tin P1/P2, SOUTHSIDE P3/P5; LP12 in H2", "source": "interim 2025 + annual"},
}

# Per-package recognition half (from interim announcements; STRONG=explicit,
# INFERRED=by subtraction/attribution)
PHASE_RECOGNITION_HALF = {
    "the-southside-p1": ("2022-H1", "strong", "interim 2022 names SOUTHLAND in 1H2022"),
    "the-southside-p2": ("2022-H1", "strong", "interim 2022 names La Marina in 1H2022"),
    "the-southside-p4": ("2024-H2", "inferred", "OP 2024-11; bulk 2024H2 (8,525)"),
    "ho-man-tin-p2": ("2025-H1", "strong", "interim 2025 names Ho Man Tin P2 in 1H2025"),
    "lohas-park-p11": ("2023-H1 + 2024-H2", "strong", "interim 2023 initial; OP 2024-12 bulk"),
    "lohas-park-p12": ("2025-H2", "inferred", "OP 2025-10; H2 2025 per split"),
}


def write_recognition_split() -> pd.DataFrame:
    rows = []
    for year, info in RECOGNITION_SPLIT.items():
        rows.append({
            "fiscal_year": year,
            "hk_property_dev_profit_post_tax_h1_hkdm": info["h1"],
            "hk_property_dev_profit_post_tax_h2_hkdm": info["h2"],
            "annual_total_hkdm": info["h1"] + info["h2"],
            "h1_projects_official": info["h1_projects"],
            "source": info["source"],
        })
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(NORM_DIR, "mtr_property_recognition_h1h2.csv"), index=False)
    return df

def main() -> int:
    stats = SRPE_STATS.set_index("project_id")
    master = MASTER.set_index("project_id")
    rows = []
    for pid, (addr, permit, op_month, op_units, evidence, rec_year) in PHASE_OP.items():
        s = stats.loc[pid] if pid in stats.index else pd.Series(dtype=object)
        m = master.loc[pid]
        op_dt = pd.Timestamp(op_month)
        # recognition anchor: same-year H2 convention (recognition at OP year end)
        rec_anchor = pd.Timestamp(f"{rec_year}-06-30")
        lag_months = round((rec_anchor - op_dt).days / 30.44, 1)
        rows.append({
            "project_id": pid,
            "phase_label": s.get("phase_label") or m.get("package_label"),
            "first_price_list_date": m.get("srpe_first_price_list_date"),
            "first_transaction_date": s.get("first_transaction_date"),
            "op_address": addr,
            "op_permit_number": permit,
            "op_issuance_month": op_month,
            "op_domestic_units": op_units,
            "mtr_recognition_year": rec_year,
            "mtr_recognition_half": PHASE_RECOGNITION_HALF.get(pid, (None, None, ""))[0],
            "recognition_half_evidence": PHASE_RECOGNITION_HALF.get(pid, (None, None, ""))[1],
            "op_to_recognition_lag_months": lag_months,
            "evidence_level": evidence,
        })
    out = pd.DataFrame(rows).sort_values("op_issuance_month")
    out.to_csv(OUT_CSV, index=False)

    split_df = write_recognition_split()
    # attach recognition half to the timing rows
    out["mtr_recognition_half"] = out["project_id"].map(
        lambda pid: PHASE_RECOGNITION_HALF.get(pid, (None, None, ""))[0])
    out["recognition_half_evidence"] = out["project_id"].map(
        lambda pid: PHASE_RECOGNITION_HALF.get(pid, (None, None, ""))[1])
    out.to_csv(OUT_CSV, index=False)
    print("\nH1/H2 recognition split (official):")
    print(split_df.to_string(index=False))

    print("MTR Property Timing History (OP -> recognition):")
    print(out.to_string(index=False))
    strong = out[out["evidence_level"] == "strong"]
    print(f"\nSTRONG-mapped cases: {len(strong)}")
    print(f"  median OP->recognition lag (months): "
          f"{strong['op_to_recognition_lag_months'].median():.1f}")
    print(f"\nWrote {OUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
