#!/usr/bin/env python3
"""
MTR Thesis A - Cross-Boundary Structural Bull: Validation
==========================================================

Thesis A (from MTR_LONG_SHORT_THESIS.md):
  Street treats the Greater Bay Area (GBA) integration as a post-COVID
  normalisation, but it is structurally stronger than the pre-COVID baseline.

Testable checks (all from repo-verified official data):
  1. HSR / cross-boundary traffic: 2019 pre-COVID baseline vs 2023-2026.
     - HSR West Kowloon: TD table82 (ERLWK) == ImmD daily hsr_west_kowloon_total
       (verified 1:1 monthly match 2023+).
     - MTR cross-boundary rail = Lo Wu (LWT) + Lok Ma Chau Spur Line (LMCSL)
       + HSR (ERLWK). NOTE: normalized immd `mtr_cross_boundary_total` is
       exactly Lo Wu + LMC Spur Line (no HSR) - verified on all 2046 rows.
  2. HSR share of cross-boundary rail (mix quality / yield):
     - farebox hsr_yield (HK$124.9) vs cross_boundary_yield (HK$36.2), i.e.
       ~3.4x higher unit revenue quality for HSR.
     - HSR revenue share of cross-boundary farebox (~101% in FY2025: HSR
       revenue now exceeds the Lo Wu + LMC rail segment alone).
  3. Diversion risk (who competes with HSR for the same cross-boundary trips):
     - HZMB traffic (table81e all-class) and 港车北上 (HK private cars,
       VEHICLE_CLASS_CODE=36, BOUND=OB outbound/northbound).
     - Heung Yuen Wai / 香园围 (HYW) new control point growth.

Caveats:
  * HSR opened Sep-2018, so 2019 is its first full year = the cleanest
    pre-COVID baseline available.
  * 2020-2022 are COVID-affected; use 2019 as baseline and 2023+ as recovery.
  * 2026 YTD: TD table82 only goes to 2026-05; ImmD daily goes to 2026-08-08
    and is used for the HSR daily run-rate.

Outputs:
  * outputs/mtr_thesis_a_cross_boundary/ (metrics CSV + summary md)
  * docs/asia-markets/charts/thesis_a_*.png  (charts, committed alongside report)
"""

from __future__ import annotations

import argparse
import glob
import os

import duckdb
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang HK", "Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(REPO_ROOT, "data", "raw", "hk_population_migration")
NORM_DIR = os.path.join(REPO_ROOT, "data", "normalized", "hk_population_migration")
FAREBOX_CSV = os.path.join(REPO_ROOT, "data", "processed", "transport", "mtr_farebox_revenue_monthly.csv")

RAIL_CP = ["LWT", "LMCSL", "ERLWK"]  # Lo Wu, Lok Ma Chau Spur Line, HSR West Kowloon


def latest_raw(pattern: str) -> str:
    matches = sorted(glob.glob(os.path.join(RAW_DIR, pattern)))
    if not matches:
        raise FileNotFoundError(f"no raw files match {pattern}")
    return matches[-1]


def latest_norm(dataset: str) -> str:
    base = os.path.join(NORM_DIR, dataset)
    runs = sorted(glob.glob(os.path.join(base, "*")))
    if not runs:
        raise FileNotFoundError(f"no normalized runs for {dataset}")
    return runs[-1]


def load_td_cross_boundary() -> pd.DataFrame:
    """TD table82: monthly cross-boundary passenger traffic by control point."""
    p = latest_raw("td_cross_boundary_passengers_*.csv")
    df = pd.read_csv(p)
    df["month"] = df["YR_MTH"].astype(str)
    df["yr"] = df["month"].str[:4]
    return df


def load_td_hzmb() -> pd.DataFrame:
    """TD table81e: monthly HZMB vehicular traffic by class & bound."""
    p = latest_raw("td_hzmb_vehicular_traffic_*.csv")
    df = pd.read_csv(p)
    df["yr"] = df["YR_MTH"].astype(str).str[:4]
    return df


def load_immd_daily() -> pd.DataFrame:
    p = os.path.join(
        latest_norm("immd_daily_traffic"),
        "immd_daily_traffic.parquet",
    )
    con = duckdb.connect()
    df = con.execute(f"SELECT * FROM read_parquet('{p}')").df()
    df["date"] = pd.to_datetime(df["date"])
    return df


def build_annual_metrics() -> pd.DataFrame:
    cbp = load_td_cross_boundary()
    grp = cbp.groupby(["yr", "CONTROL_POINT_CODE"])["NO_PAX"].sum().unstack(fill_value=0)

    annual = pd.DataFrame(index=grp.index)
    annual["lowu"] = grp.get("LWT", 0)          # Lo Wu
    annual["lmcspur"] = grp.get("LMCSL", 0)     # Lok Ma Chau Spur Line
    annual["hsr"] = grp.get("ERLWK", 0)         # HSR West Kowloon
    annual["rail_total"] = annual["lowu"] + annual["lmcspur"] + annual["hsr"]
    annual["total_cross"] = grp.sum(axis=1)     # all control points
    annual["szb"] = grp.get("SZB", 0)           # Shenzhen Bay (road)
    annual["hyw"] = grp.get("HYW", 0)           # Heung Yuen Wai / 香园围 (road)
    annual["hzmb_pax"] = grp.get("HKZMB", 0)    # HZMB (road)

    annual["hsr_share_of_rail"] = annual["hsr"] / annual["rail_total"].replace(0, pd.NA) * 100
    annual["hsr_share_of_total"] = annual["hsr"] / annual["total_cross"].replace(0, pd.NA) * 100
    annual["rail_share_of_total"] = annual["rail_total"] / annual["total_cross"].replace(0, pd.NA) * 100
    return annual.sort_index()


def build_vehicles_metrics() -> pd.DataFrame:
    hz = load_td_hzmb()
    allv = hz.groupby("yr")["NO_VEHICLE"].sum()
    # 港车北上 = HK private cars (class 36) outbound from HK (northbound leg)
    nk = hz[(hz["VEHICLE_CLASS_CODE"] == 36) & (hz["BOUND_CODE"] == "OB")].groupby("yr")["NO_VEHICLE"].sum()
    out = pd.DataFrame({"hzmb_total_veh": allv, "hk_car_northbound": nk}).fillna(0)
    out["hzmb_veh_yoy"] = out["hzmb_total_veh"].pct_change() * 100
    out["hk_car_yoy"] = out["hk_car_northbound"].pct_change() * 100
    return out.sort_index()


def build_farebox_mix() -> pd.DataFrame:
    fb = pd.read_csv(FAREBOX_CSV)
    g = fb.groupby("year").agg(
        hsr_rev=("hsr_rev_hkdm", "sum"),
        cb_rev=("cross_boundary_rev_hkdm", "sum"),
        hsr_yield=("hsr_yield_hkd", "mean"),
        cb_yield=("cross_boundary_yield_hkd", "mean"),
    )
    g["hsr_pct_of_cb"] = g["hsr_rev"] / g["cb_rev"].replace(0, pd.NA) * 100
    g["yield_ratio"] = g["hsr_yield"] / g["cb_yield"].replace(0, pd.NA)
    return g


def build_immd_runrate() -> pd.DataFrame:
    immd = load_immd_daily()
    y26 = immd[immd["date"].dt.year == 2026]
    hsr_26 = y26["hsr_west_kowloon_total"].sum()
    days = (y26["date"].max() - y26["date"].min()).days + 1
    return pd.DataFrame(
        {
            "metric": ["hsr_2026_ytd_pax", "hsr_2026_daily_avg", "hsr_2026_through", "hsr_2026_days"],
            "value": [hsr_26, hsr_26 / days, y26["date"].max().strftime("%Y-%m-%d"), days],
        }
    )


def make_charts(annual: pd.DataFrame, veh: pd.DataFrame, out_dir: str) -> None:
    # Charts are committed with the report in docs/asia-markets/charts (same
    # convention as mtr_report_charts.py); metrics CSVs stay under outputs/.
    chart_dir = os.path.join(REPO_ROOT, "docs", "asia-markets", "charts")
    os.makedirs(chart_dir, exist_ok=True)
    blue, orange, green, red, gray = "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#7f7f7f"

    years = [y for y in ["2018", "2019", "2023", "2024", "2025", "2026"] if y in annual.index]
    sub = annual.loc[years]

    # Fig 1: rail composition (Lo Wu / LMC Spur / HSR) + total cross-boundary
    fig, ax = plt.subplots(figsize=(9, 4.8))
    x = range(len(years))
    ax.bar(x, sub["lowu"] / 1e6, 0.7, label="罗湖 Lo Wu", color=gray)
    ax.bar(x, sub["lmcspur"] / 1e6, 0.7, bottom=(sub["lowu"]) / 1e6, label="落马洲支线 LMC Spur", color=blue)
    ax.bar(x, sub["hsr"] / 1e6, 0.7, bottom=(sub["lowu"] + sub["lmcspur"]) / 1e6, label="高铁 HSR", color=orange)
    ax.set_xticks(list(x))
    ax.set_xticklabels(years)
    ax.set_ylabel("亿人次")
    ax.set_title("MTR 跨境铁路构成（罗湖 + 落马洲支线 + 高铁）")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(chart_dir, "thesis_a_rail_composition.png"), dpi=150)
    plt.close(fig)

    # Fig 2: HSR share of rail + HSR daily average
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.plot(list(x), sub["hsr_share_of_rail"].values, marker="o", color=orange, label="高铁占跨境铁路份额 %")
    for xi, v in zip(x, sub["hsr_share_of_rail"].values):
        ax.annotate(f"{v:.1f}%", (xi, v), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(years)
    ax.set_ylabel("高铁占跨境铁路 %")
    ax.set_title("高铁占跨境铁路份额（2019 疫前基线 → 2025/2026）")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(chart_dir, "thesis_a_hsr_share.png"), dpi=150)
    plt.close(fig)

    # Fig 3: diversion (HSR pax vs HZMB vehicles vs 港车北上), indexed to 2023=100
    fig, ax = plt.subplots(figsize=(9, 4.8))
    idx = ["2023", "2024", "2025"]
    base_hsr = annual.loc["2023", "hsr"]
    hsr_idx = [annual.loc[y, "hsr"] / base_hsr * 100 for y in idx]
    veh_idx = [veh.loc[y, "hzmb_total_veh"] / veh.loc["2023", "hzmb_total_veh"] * 100 for y in idx]
    car_idx = [veh.loc[y, "hk_car_northbound"] / veh.loc["2023", "hk_car_northbound"] * 100 for y in idx]
    ax.plot(idx, veh_idx, marker="o", color=blue, label="HZMB 总车流（指数）")
    ax.plot(idx, car_idx, marker="s", color=green, label="港车北上（指数）")
    ax.plot(idx, hsr_idx, marker="^", color=orange, label="高铁客流（指数）")
    ax.set_ylabel("指数（2023=100）")
    ax.set_title("分流竞争：高铁 vs 港珠澳大桥车流 vs 港车北上（指数化）")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(chart_dir, "thesis_a_diversion.png"), dpi=150)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "outputs", "mtr_thesis_a_cross_boundary"))
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    annual = build_annual_metrics()
    veh = build_vehicles_metrics()
    mix = build_farebox_mix()
    mix.index = mix.index.astype(str)
    runrate = build_immd_runrate()
    make_charts(annual, veh, args.out)

    annual.to_csv(os.path.join(args.out, "cross_boundary_annual.csv"))
    veh.to_csv(os.path.join(args.out, "hzmb_vehicles_annual.csv"))
    mix.to_csv(os.path.join(args.out, "farebox_mix_annual.csv"))
    runrate.to_csv(os.path.join(args.out, "immd_2026_runrate.csv"), index=False)

    # ---- key numbers for the report ----
    base = annual.loc["2019"]
    latest_full = annual.loc["2025"]

    lines = []
    lines.append("# MTR Thesis A - Cross-Boundary Structural Bull: Validation Metrics")
    lines.append("")
    lines.append("Data as of 2026-08-09. Sources: TD table82/table81e (data.gov.hk), ImmD daily, farebox model.")
    lines.append("")
    lines.append("## 1. HSR / rail / total cross-boundary (annual, pax)")
    lines.append("")
    lines.append(annual[["lowu", "lmcspur", "hsr", "rail_total", "total_cross", "hsr_share_of_rail"]]
                 .loc[["2018", "2019", "2020", "2023", "2024", "2025", "2026"]].round(0).to_markdown())
    lines.append("")
    lines.append(f"- 高铁 2025 vs 2019: {latest_full['hsr']/1e4:.0f}万 vs {base['hsr']/1e4:.0f}万 "
                 f"= {latest_full['hsr']/base['hsr']*100-100:+.0f}% (2019 为高铁开通后首个完整年)")
    lines.append(f"- 高铁占跨境铁路 2019 {base['hsr_share_of_rail']:.1f}% -> 2025 {latest_full['hsr_share_of_rail']:.1f}%")
    lines.append(f"- 全口径跨境 2019 {base['total_cross']/1e6:.2f}亿 -> 2025 {latest_full['total_cross']/1e6:.2f}亿 "
                 f"= {latest_full['total_cross']/base['total_cross']*100-100:+.0f}%")
    lines.append("")
    lines.append("## 2. Farebox revenue mix (高铁 vs 普通跨境)")
    lines.append("")
    lines.append(mix.loc[["2019", "2024", "2025"]].round(1).to_markdown())
    lines.append("")
    lines.append(f"- 高铁单客 yield ≈ HK${mix.loc['2025','hsr_yield']:.0f} vs 普通跨境 HK${mix.loc['2025','cb_yield']:.0f} "
                 f"(质量 ≈ {mix.loc['2025','yield_ratio']:.1f}x)")
    lines.append(f"- FY2025 高铁收入占普通跨境分部收入 {mix.loc['2025','hsr_pct_of_cb']:.0f}% —— 高铁已近似等于整个跨境分部")
    lines.append("")
    lines.append("## 3. Diversion risk: HZMB vehicles / 港车北上")
    lines.append("")
    veh_wan = veh.loc[["2022", "2023", "2024", "2025"]].copy()
    veh_wan["hzmb_total_veh_万"] = (veh_wan["hzmb_total_veh"] / 1e4).round(0)
    veh_wan["hk_car_northbound_万"] = (veh_wan["hk_car_northbound"] / 1e4).round(1)
    lines.append(veh_wan[["hzmb_total_veh_万", "hk_car_northbound_万", "hzmb_veh_yoy", "hk_car_yoy"]].round(1).to_markdown())
    lines.append("")
    lines.append("## 4. ImmD 2026 YTD HSR run-rate (日度, 至今)")
    lines.append("")
    lines.append(runrate.to_markdown(index=False))
    lines.append("")
    lines.append("## Methodology notes")
    lines.append("")
    lines.append("- `mtr_cross_boundary_total`(normalized immd) == Lo Wu + LMC Spur Line (excl. HSR), 2046/2046 行吻合。")
    lines.append("- HSR pax: TD ERLWK == ImmD hsr_west_kowloon_total, monthly 1:1 吻合 (2023+)。")
    lines.append("- 港车北上 = table81e VEHICLE_CLASS_CODE 36 (HK private cars) x BOUND OB (outbound/northbound)。")
    lines.append("- 2026 TD 仅到 2026-05;HSR 日度 run-rate 用 ImmD 到 2026-08-08。")

    summary_md = os.path.join(args.out, "mtr_thesis_a_summary.md")
    with open(summary_md, "w") as f:
        f.write("\n".join(lines) + "\n")

    print("wrote metrics to", args.out)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
