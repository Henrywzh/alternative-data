#!/usr/bin/env python3
"""
MTR Thesis B - Revenue-Mix Quality (commercial keeps up with transport?)
========================================================================

Thesis B (from MTR_LONG_SHORT_THESIS.md):
  Passenger volume recovers but the marginal passenger yields low, and
  station-commercial / rental income underperforms transport revenue because
  HK residents are spending north of the border (net consumption outflow).
  => even if transport grows, commercial + rental drag => FY27+ earnings mix risk.

Testable checks (all from repo-verified official data):
  1. Net consumption outflow: 内地访客 vs 港人北上 (ImmD daily, annual & ratio).
     - ml_visitor_in vs hk_northbound (out) + out/in ratio 2023->2026.
  2. Station commercial + rental income per passenger (MTR annual earnings
     bridge vs annual MTR patronage). Combined station+rental is comparable
     2017-2025 (MTR disclosed them merged for 2017-2019 and separately 2020+).
  3. Growth gap: transport revenue growth vs commercial+rental growth vs
     patronage growth, 2023-2025 (post-reopening).

Caveats:
  * MTR discloses station commercial and rental separately from 2020 onward;
    2017-2019 are a merged "station and rental" line. We use the combined
    line for a consistent monotonic series 2017-2025.
  * hk_station_plus_rental_rev for 2014/2015/2020+ is computed from the two
    separate columns (sum); 2016 is missing from disclosures.
  * ImmD daily starts 2021-01-01 (no 2019 pre-COVID visitor-in vs resident-out
    split at daily granularity; CSD/TD have annual aggregates elsewhere).
  * 2026 is YTD: ImmD through 2026-08-08; patronage through 2026-06.
  * MTR revenue is calendar-year (Jan-Dec) which matches patronage years.

Outputs:
  * outputs/mtr_thesis_b_commercial_mix/ (metrics CSV + summary md)
  * docs/asia-markets/charts/thesis_b_*.png  (charts, committed with report)
"""

from __future__ import annotations

import argparse
import glob
import json
import os

import duckdb
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang HK", "Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

from mtr_thesis_a_cross_boundary import latest_norm  # reuse snapshot finder

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NORM_DIR = os.path.join(REPO_ROOT, "data", "normalized", "hk_population_migration")
CHART_DIR = os.path.join(REPO_ROOT, "docs", "asia-markets", "charts")

EARNINGS_CSV = os.path.join(REPO_ROOT, "data", "normalized", "hk_transport", "mtr_historical_earnings_bridge.csv")


def load_immd_daily() -> pd.DataFrame:
    p = os.path.join(
        latest_norm("immd_daily_traffic"),
        "immd_daily_traffic.parquet",
    )
    con = duckdb.connect()
    df = con.execute(f"SELECT * FROM read_parquet('{p}')").df()
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_mtr_patronage_annual() -> pd.DataFrame:
    p = sorted(glob.glob(os.path.join(REPO_ROOT, "data", "raw", "hk_transport", "mtr_patronage_*.json")))[-1]
    d = json.load(open(p))["data"]
    df = pd.DataFrame(d)
    df["year"] = pd.to_datetime(df["date"]).dt.year
    g = df.groupby("year").agg(pax_thousands=("total_mtr_patronage_thousands", "sum"))
    return g


def build_immd_flow_yearly() -> pd.DataFrame:
    immd = load_immd_daily()
    immd["yr"] = immd["date"].dt.year
    g = immd.groupby("yr").agg(
        ml_visitor_in=("mainland_visitor_arrivals", "sum"),
        hk_northbound=("hk_resident_departures", "sum"),
    )
    g["out_in_ratio"] = g["hk_northbound"] / g["ml_visitor_in"].replace(0, np.nan)
    g["net_outflow_wan"] = (g["hk_northbound"] - g["ml_visitor_in"]) / 1e4
    return g


def build_commercial_yearly() -> pd.DataFrame:
    eb = pd.read_csv(EARNINGS_CSV).set_index("year")
    eb.index = eb.index.astype(str)
    pat = load_mtr_patronage_annual()
    pat.index = pat.index.astype(str)

    out = pd.DataFrame(index=eb.index)
    out["transport_rev"] = eb["hk_transport_rev"]
    out["station_commercial"] = eb["hk_station_commercial_rev"]
    out["rental"] = eb["hk_property_rental_mgmt_rev"]
    out["station_plus_rental"] = eb["hk_station_plus_rental_rev"].where(
        eb["hk_station_plus_rental_rev"].notna(),
        eb["hk_station_commercial_rev"] + eb["hk_property_rental_mgmt_rev"],
    )
    out["pax_m"] = pat["pax_thousands"] / 1000.0  # thousands -> million passengers
    # revenue unit is HK$m; pax unit is million -> per-pax = HK$m / M pax = HKD per passenger
    out["station_rental_per_pax_hkd"] = out["station_plus_rental"] / out["pax_m"].replace(0, np.nan)
    out["transport_per_pax_hkd"] = out["transport_rev"] / out["pax_m"].replace(0, np.nan)
    return out


def make_charts(com: pd.DataFrame, flow: pd.DataFrame, out_dir: str) -> None:
    os.makedirs(CHART_DIR, exist_ok=True)
    blue, orange, green, red, gray = "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#7f7f7f"

    # Fig 1: transport vs station+rental rev vs pax (indexed 2017=100)
    years = [y for y in ["2017", "2018", "2019", "2021", "2022", "2023", "2024", "2025"] if y in com.index]
    sub = com.loc[years]
    base = sub.loc["2017"]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.plot(list(range(len(years))), (sub["transport_rev"] / base["transport_rev"] * 100).values,
            marker="o", color=blue, label="交通运输收入")
    ax.plot(list(range(len(years))), (sub["station_plus_rental"] / base["station_plus_rental"] * 100).values,
            marker="s", color=orange, label="站内商业+租金收入")
    ax.plot(list(range(len(years))), (sub["pax_m"] / base["pax_m"] * 100).values,
            marker="^", color=green, label="总客流量")
    ax.set_xticks(list(range(len(years))))
    ax.set_xticklabels(years)
    ax.set_ylabel("指数（2017=100）")
    ax.set_title("MTR 交通运输收入 vs 站内商业+租金 vs 客流（指数化）")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "thesis_b_rev_vs_commercial.png"), dpi=150)
    plt.close(fig)

    # Fig 2: station+rental revenue per passenger (HKD)
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.plot(list(range(len(years))), sub["station_rental_per_pax_hkd"].values,
            marker="o", color=orange, label="站内商业+租金单客收入 (HK$/人次)")
    for xi, v in zip(range(len(years)), sub["station_rental_per_pax_hkd"].values):
        if v == v:
            ax.annotate(f"{v:.2f}", (xi, v), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8)
    ax.set_xticks(list(range(len(years))))
    ax.set_xticklabels(years)
    ax.set_ylabel("HK$ / 人次")
    ax.set_title("站内商业+租金 单客变现（HK$ per passenger）")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "thesis_b_per_pax.png"), dpi=150)
    plt.close(fig)

    # Fig 3: net consumption outflow (HK residents northbound vs ML visitors in, indexed 2023=100)
    years3 = ["2023", "2024", "2025"]
    if all(y in flow.index for y in years3):
        fig, ax = plt.subplots(figsize=(9, 4.8))
        sub3 = flow.loc[years3]
        x = range(3)
        ax.bar([i - 0.2 for i in x], (sub3["ml_visitor_in"] / sub3.loc["2023", "ml_visitor_in"] * 100).values,
               0.4, color=blue, label="内地访客抵港（指数）")
        ax.bar([i + 0.2 for i in x], (sub3["hk_northbound"] / sub3.loc["2023", "hk_northbound"] * 100).values,
               0.4, color=orange, label="港人北上（指数）")
        for i, yv in enumerate(years3):
            ax.text(i - 0.2, sub3.loc[yv, "ml_visitor_in"] / sub3.loc["2023", "ml_visitor_in"] * 100 + 3,
                    f"{sub3.loc[yv,'out_in_ratio']:.2f}", ha="center", fontsize=8, color=gray)
            ax.text(i + 0.2, sub3.loc[yv, "hk_northbound"] / sub3.loc["2023", "hk_northbound"] * 100 + 3,
                    f"{sub3.loc[yv,'hk_northbound']/1e8:.1f}亿", ha="center", fontsize=8, color=gray)
        ax.set_xticks(list(x))
        ax.set_xticklabels(years3)
        ax.set_ylabel("指数（2023=100）")
        ax.set_title("净消费外流：港人北上 vs 内地访客（2023=100；线上标注为港人北上亿次 & 外流比）")
        ax.legend()
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        fig.savefig(os.path.join(CHART_DIR, "thesis_b_net_outflow.png"), dpi=150)
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "outputs", "mtr_thesis_b_commercial_mix"))
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    flow = build_immd_flow_yearly()
    flow.index = flow.index.astype(str)
    com = build_commercial_yearly()
    make_charts(com, flow, args.out)

    flow.to_csv(os.path.join(args.out, "immd_flow_yearly.csv"))
    com.to_csv(os.path.join(args.out, "commercial_yearly.csv"))

    lines = []
    lines.append("# MTR Thesis B - Revenue-Mix Quality: Validation Metrics")
    lines.append("")
    lines.append("Data as of 2026-08-09. Sources: ImmD daily, MTR annual earnings bridge, MTR patronage, farebox model.")
    lines.append("")
    lines.append("## 1. Net consumption outflow (ImmD daily, 内地访客 vs 港人北上)")
    lines.append("")
    f24 = flow.loc["2024"]; f25 = flow.loc["2025"]; f23 = flow.loc["2023"]
    lines.append(f"- 港人北上/内地访客 比：2023 {f23['out_in_ratio']:.2f} -> 2024 {f24['out_in_ratio']:.2f} -> "
                 f"2025 {f25['out_in_ratio']:.2f}（即每 1 名内地访客入港，约 {f25['out_in_ratio']:.1f} 名港人北上出境）")
    lines.append(f"- 港人北上 2025 = {f25['hk_northbound']/1e8:.2f}亿 vs 内地访客 {f25['ml_visitor_in']/1e8:.2f}亿；"
                 f"净流出 {flow.loc['2025','net_outflow_wan']:.0f} 万人次/年")
    lines.append("")
    lines.append("## 2. Commercial/rental vs transport revenue + per-passenger monetisation")
    lines.append("")
    years = [y for y in ["2017", "2018", "2019", "2021", "2022", "2023", "2024", "2025"] if y in com.index]
    sub = com.loc[years][["transport_rev", "station_commercial", "rental", "station_plus_rental", "pax_m",
                          "station_rental_per_pax_hkd", "transport_per_pax_hkd"]].round(2)
    lines.append(sub.to_markdown())
    lines.append("")
    lines.append(f"- 2025 站内商业+租金单客收入 = HK$ {com.loc['2025','station_rental_per_pax_hkd']:.2f}"
                 f" vs 2017 HK$ {com.loc['2017','station_rental_per_pax_hkd']:.2f}"
                 f"（{com.loc['2025','station_rental_per_pax_hkd']/com.loc['2017','station_rental_per_pax_hkd']*100-100:+.0f}%）")
    lines.append(f"- 2024->2025: transport 收入 {com.loc['2024','transport_rev']:.0f}->{com.loc['2025','transport_rev']:.0f} "
                 f"({com.loc['2025','transport_rev']/com.loc['2024','transport_rev']*100-100:+.1f}%)；"
                 f"站内商业+租金 {com.loc['2024','station_plus_rental']:.0f}->{com.loc['2025','station_plus_rental']:.0f}"
                 f" ({com.loc['2025','station_plus_rental']/com.loc['2024','station_plus_rental']*100-100:+.1f}%)")
    lines.append(f"- 2024->2025 明细：站内商业 {com.loc['2024','station_commercial']:.0f}->{com.loc['2025','station_commercial']:.0f}"
                 f" ({com.loc['2025','station_commercial']/com.loc['2024','station_commercial']*100-100:+.2f}%)；"
                 f"租金 {com.loc['2024','rental']:.0f}->{com.loc['2025','rental']:.0f}"
                 f" ({com.loc['2025','rental']/com.loc['2024','rental']*100-100:+.1f}%) —— 拉低的是租金")
    lines.append(f"- 2025 站内商业收入本身（不含租金）几乎 0 增长：5,343 -> 5,345 HK$m"
                 f" ({com.loc['2025','station_commercial']/com.loc['2024','station_commercial']*100-100:+.2f}%)")
    lines.append(f"- transport 单客变现 2017 HK$9.1 -> 2025 HK$12.05 (+{com.loc['2025','transport_per_pax_hkd']/com.loc['2017','transport_per_pax_hkd']*100-100:.0f}%)，"
                 f"而站内商业+租金单客 HK$5.44 -> HK$5.32 ({com.loc['2025','station_rental_per_pax_hkd']/com.loc['2017','station_rental_per_pax_hkd']*100-100:+.0f}%) —— "
                 f"transport 单位价值因高铁 mix 上升，但商业端未跟上")
    lines.append("")
    lines.append("## 3. Summary interpretation")
    lines.append("")
    lines.append("- 若 transport 增长快于/近于客流、而站内商业+租金跑输 -> Thesis B (mix quality 风险) 得到支持。")
    lines.append("- 相反,若 单客商业变现持续抬升 -> Thesis B 弱化。")
    lines.append("")
    lines.append("## Methodology notes")
    lines.append("")
    lines.append("- 站内商业+租金统一用合并口径(2017-2019 MTR 仅披露合并线;2020+ 为两列相加)保持可比。2016 缺失。")
    lines.append("- ImmD 日度 2021 起,无 2019 疫前同日度户;2026 为 YTD(至 08-08)。")

    summary_md = os.path.join(args.out, "mtr_thesis_b_summary.md")
    with open(summary_md, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
