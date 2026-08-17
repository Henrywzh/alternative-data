#!/usr/bin/env python3
"""
MTR Thesis B - Revenue-Mix Quality (commercial keeps up with transport?)
========================================================================

Thesis B (from MTR_LONG_SHORT_THESIS.md):
  Passenger volume recovers but station-commercial / rental income may
  underperform transport revenue. Cross-border land-departure flow is used as
  a demand-side risk proxy; it is not a consumption-value series and does not
  establish causality.
  => even if transport grows, commercial + rental drag => FY27+ earnings mix risk.

Testable checks (all from repo-verified official data):
  1. Cross-border flow proxy: Mainland visitors and HK residents departing via
     the same Mainland-oriented land checkpoints (ImmD raw daily, annual ratio).
  2. Station commercial + rental income intensity normalized by total MTR
     passenger journeys (MTR annual earnings bridge vs annual patronage).
     This is not realized spend per passenger. Combined station+rental is
     comparable 2017-2025 (merged disclosure 2017-2019, separate 2020+).
  3. Growth gap: transport revenue growth vs commercial+rental growth vs
     patronage growth, 2023-2025 (post-reopening).

Caveats:
  * MTR discloses station commercial and rental separately from 2020 onward;
    2017-2019 are a merged "station and rental" line. We use the combined
    line for a consistent monotonic series 2017-2025.
  * hk_station_plus_rental_rev for 2014/2015/2020+ is computed from the two
    separate columns (sum); 2016 is missing from disclosures.
  * ImmD daily starts 2021-01-01 (no 2019 pre-COVID daily split).
  * The normalized ImmD aggregate has no nationality-by-control-point split;
    therefore this script reads the retained raw CSV to calculate matched
    Mainland-oriented land-checkpoint arrivals and departures. The Hong Kong-
    Zhuhai-Macao Bridge is reported separately because it is not Mainland-only.
  * 2026 is partial and is not compared with complete years in the charts.
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

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang HK", "Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_POPULATION_DIR = os.path.join(REPO_ROOT, "data", "raw", "hk_population_migration")
RAW_TRANSPORT_DIR = os.path.join(REPO_ROOT, "data", "raw", "hk_transport")
CHART_DIR = os.path.join(REPO_ROOT, "docs", "asia-markets", "charts")

EARNINGS_CSV = os.path.join(REPO_ROOT, "data", "normalized", "hk_transport", "mtr_historical_earnings_bridge.csv")

MAINLAND_LAND_CONTROL_POINTS = {
    "Lo Wu",
    "Lok Ma Chau Spur Line",
    "Shenzhen Bay",
    "Heung Yuen Wai",
    "Express Rail Link West Kowloon",
    "Lok Ma Chau",
    "Man Kam To",
    "Sha Tau Kok",
}
HZMB_CONTROL_POINT = "Hong Kong-Zhuhai-Macao Bridge"


def latest_raw(directory: str, pattern: str) -> str:
    matches = sorted(glob.glob(os.path.join(directory, pattern)))
    if not matches:
        raise FileNotFoundError(f"no raw files match {directory}/{pattern}")
    return matches[-1]


def load_immd_raw() -> pd.DataFrame:
    """Load and validate full-grain ImmD data, retaining control points."""
    path = latest_raw(RAW_POPULATION_DIR, "immd_daily_traffic_*.csv")
    df = pd.read_csv(path)
    required = {
        "Date", "Control Point", "Arrival / Departure", "Hong Kong Residents",
        "Mainland Visitors", "Other Visitors", "Total",
    }
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"ImmD raw schema missing columns: {sorted(missing)}")
    df["date"] = pd.to_datetime(df["Date"], format="%d-%m-%Y", errors="coerce")
    if df["date"].isna().any():
        raise ValueError("ImmD raw data contains unparseable dates")
    numeric = ["Hong Kong Residents", "Mainland Visitors", "Other Visitors", "Total"]
    for column in numeric:
        df[column] = pd.to_numeric(
            df[column].astype(str).str.replace(",", "", regex=False), errors="coerce"
        )
    if df[numeric].isna().any().any() or (df[numeric] < 0).any().any():
        raise ValueError("ImmD raw data contains null or negative passenger values")
    key = ["date", "Control Point", "Arrival / Departure"]
    if df.duplicated(key).any():
        raise ValueError("ImmD raw data has duplicate date/control-point/direction rows")
    if (df["Total"] != df[["Hong Kong Residents", "Mainland Visitors", "Other Visitors"]].sum(axis=1)).any():
        raise ValueError("ImmD raw component counts do not reconcile to Total")
    df.attrs.update(
        source_path=path,
        source_date_min=df["date"].min().strftime("%Y-%m-%d"),
        source_date_max=df["date"].max().strftime("%Y-%m-%d"),
    )
    return df


def load_mtr_patronage_annual() -> pd.DataFrame:
    p = latest_raw(RAW_TRANSPORT_DIR, "mtr_patronage_*.json")
    with open(p) as handle:
        payload = json.load(handle)
    d = payload.get("data", [])
    df = pd.DataFrame(d)
    required = {
        "month", "date", "domestic_service_thousands", "airport_express_thousands",
        "cross_boundary_thousands", "light_rail_bus_thousands", "hsr_thousands",
        "total_mtr_patronage_thousands",
    }
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"MTR patronage schema missing columns: {sorted(missing)}")
    if df["month"].duplicated().any():
        raise ValueError("MTR patronage has duplicate months")
    value_columns = sorted(required.difference({"month", "date"}))
    if df[value_columns].isna().any().any() or (df[value_columns] < 0).any().any():
        raise ValueError("MTR patronage contains null or negative values")
    segment_columns = [
        "domestic_service_thousands", "airport_express_thousands",
        "cross_boundary_thousands", "light_rail_bus_thousands", "hsr_thousands",
    ]
    if (df["total_mtr_patronage_thousands"] - df[segment_columns].sum(axis=1)).abs().gt(1e-6).any():
        raise ValueError("MTR patronage total does not reconcile to segment sum")
    parsed_dates = pd.to_datetime(df["date"], errors="coerce")
    if parsed_dates.isna().any():
        raise ValueError("MTR patronage contains unparseable dates")
    if not parsed_dates.dt.strftime("%Y-%m").eq(df["month"].astype(str)).all():
        raise ValueError("MTR patronage month and date fields do not reconcile")
    df["year"] = parsed_dates.dt.year
    g = df.groupby("year").agg(pax_thousands=("total_mtr_patronage_thousands", "sum"))
    g.attrs.update(
        source_path=p,
        source_fetched_at=payload.get("fetched_at"),
        source_month_min=df["month"].min(),
        source_month_max=df["month"].max(),
    )
    return g


def build_immd_flow_yearly() -> pd.DataFrame:
    immd = load_immd_raw()
    arrivals = immd[immd["Arrival / Departure"].eq("Arrival")]
    departures = immd[immd["Arrival / Departure"].eq("Departure")]
    mainland_land_arrivals = arrivals[arrivals["Control Point"].isin(MAINLAND_LAND_CONTROL_POINTS)]
    mainland_land = departures[departures["Control Point"].isin(MAINLAND_LAND_CONTROL_POINTS)]
    land_including_hzmb_arrivals = arrivals[
        arrivals["Control Point"].isin(MAINLAND_LAND_CONTROL_POINTS | {HZMB_CONTROL_POINT})
    ]
    land_including_hzmb = departures[
        departures["Control Point"].isin(MAINLAND_LAND_CONTROL_POINTS | {HZMB_CONTROL_POINT})
    ]
    g = arrivals.groupby(arrivals["date"].dt.year).agg(
        mainland_visitor_arrivals_all_points=("Mainland Visitors", "sum"),
    )
    g["hk_resident_departures_all_points"] = departures.groupby(departures["date"].dt.year)[
        "Hong Kong Residents"
    ].sum()
    g["hk_resident_mainland_land_departures"] = mainland_land.groupby(
        mainland_land["date"].dt.year
    )["Hong Kong Residents"].sum()
    g["hk_resident_land_departures_including_hzmb"] = land_including_hzmb.groupby(
        land_including_hzmb["date"].dt.year
    )["Hong Kong Residents"].sum()
    g["mainland_visitor_arrivals_mainland_land"] = mainland_land_arrivals.groupby(
        mainland_land_arrivals["date"].dt.year
    )["Mainland Visitors"].sum()
    g["mainland_visitor_arrivals_land_including_hzmb"] = land_including_hzmb_arrivals.groupby(
        land_including_hzmb_arrivals["date"].dt.year
    )["Mainland Visitors"].sum()
    # Matched ratios use the same checkpoint universe in numerator and
    # denominator. The all-point denominator is retained separately for
    # context, but is deliberately not used as the primary comparison.
    g["mainland_land_departure_to_matching_land_visitor_ratio"] = (
        g["hk_resident_mainland_land_departures"]
        / g["mainland_visitor_arrivals_mainland_land"].replace(0, np.nan)
    )
    g["land_including_hzmb_departure_to_matching_visitor_ratio"] = (
        g["hk_resident_land_departures_including_hzmb"]
        / g["mainland_visitor_arrivals_land_including_hzmb"].replace(0, np.nan)
    )
    g["mainland_land_share_of_all_hk_departures"] = (
        g["hk_resident_mainland_land_departures"]
        / g["hk_resident_departures_all_points"].replace(0, np.nan)
    )
    g.attrs.update(
        source_path=immd.attrs["source_path"],
        source_date_min=immd.attrs["source_date_min"],
        source_date_max=immd.attrs["source_date_max"],
    )
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
    separate = eb[["hk_station_commercial_rev", "hk_property_rental_mgmt_rev"]].sum(axis=1, min_count=1)
    out["station_plus_rental"] = eb["hk_station_plus_rental_rev"].combine_first(separate)
    out["station_rental_source_scope"] = np.where(
        eb["hk_station_plus_rental_rev"].notna(),
        "merged_station_plus_rental_disclosure",
        np.where(separate.notna(), "sum_of_separate_disclosures", "unavailable"),
    )
    out["pax_m"] = pat["pax_thousands"] / 1000.0  # thousands -> million passengers
    # HK$m / million journeys is numerically HK$/journey, but the commercial
    # denominator is only a rough portfolio-exposure normalizer, not unique
    # people or realized spend.
    denominator = out["pax_m"].replace(0, np.nan)
    out["station_rental_intensity_hkd_per_mtr_journey"] = out["station_plus_rental"] / denominator
    out["station_commercial_intensity_hkd_per_mtr_journey"] = out["station_commercial"] / denominator
    out["rental_intensity_hkd_per_mtr_journey"] = out["rental"] / denominator
    out["transport_intensity_hkd_per_mtr_journey"] = out["transport_rev"] / denominator
    out.attrs.update(
        source_path=EARNINGS_CSV,
        patronage_source_path=pat.attrs.get("source_path"),
        patronage_source_month_max=pat.attrs.get("source_month_max"),
        earnings_year_min=int(eb.index.min()),
        earnings_year_max=int(eb.index.max()),
    )
    return out


def make_charts(com: pd.DataFrame, flow: pd.DataFrame, out_dir: str) -> None:
    os.makedirs(CHART_DIR, exist_ok=True)
    blue, orange, green, red, gray = "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#7f7f7f"

    # Fig 1: include every available full year and use numeric year coordinates
    # so 2020 is not silently removed or given the wrong visual spacing.
    available_years = sorted(int(y) for y in com.index if str(y).isdigit())
    years = [str(y) for y in available_years if y >= 2017]
    latest_chart_year = max(available_years)
    sub = com.loc[years]
    base = sub.loc["2017"]
    x = sub.index.astype(int).to_numpy()
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.plot(x, (sub["transport_rev"] / base["transport_rev"] * 100).values,
            marker="o", color=blue, label="交通运输收入")
    ax.plot(x, (sub["station_plus_rental"] / base["station_plus_rental"] * 100).values,
            marker="s", color=orange, label="站内商业+租金收入")
    ax.plot(x, (sub["pax_m"] / base["pax_m"] * 100).values,
            marker="^", color=green, label="总客流量")
    ax.set_xticks(x)
    ax.set_xticklabels(years)
    ax.set_ylabel("指数（2017=100）")
    ax.set_title("MTR 交通运输收入、站内商业+租金与总客流", pad=28)
    ax.text(0.5, 1.01, f"FY2017–FY{latest_chart_year}；收入为 HK$m，客流为百万人次；2017=100",
            transform=ax.transAxes, ha="center", va="bottom", fontsize=9, color=gray)
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.90])
    fig.savefig(os.path.join(CHART_DIR, "thesis_b_rev_vs_commercial.png"), dpi=150)
    plt.close(fig)

    # Fig 2: station+rental revenue intensity normalized by total MTR journeys.
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.plot(x, sub["station_rental_intensity_hkd_per_mtr_journey"].values,
            marker="o", color=orange, label="站内商业+租金 / 总客流（强度 proxy）")
    for xi, v in zip(x, sub["station_rental_intensity_hkd_per_mtr_journey"].values):
        if v == v:
            ax.annotate(f"{v:.2f}", (xi, v), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(years)
    ax.set_ylabel("HKD million / 百万人次（数值等同 HKD/人次）")
    ax.set_title("站内商业+租金相对总客流的收入强度", pad=28)
    ax.text(0.5, 1.01, f"FY2017–FY{latest_chart_year}；总客流仅作归一化分母，不代表真实单客消费或公司单客收入",
            transform=ax.transAxes, ha="center", va="bottom", fontsize=9, color=gray)
    ax.grid(alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.90])
    fig.savefig(os.path.join(CHART_DIR, "thesis_b_per_pax.png"), dpi=150)
    plt.close(fig)

    # Fig 3: mainland-oriented land departures vs mainland visitor arrivals.
    years3 = ["2023", "2024", "2025"]
    if all(y in flow.index for y in years3):
        fig, ax = plt.subplots(figsize=(9, 4.8))
        sub3 = flow.loc[years3]
        x = range(3)
        ax.bar([i - 0.2 for i in x], (sub3["mainland_visitor_arrivals_mainland_land"] / sub3.loc["2023", "mainland_visitor_arrivals_mainland_land"] * 100).values,
               0.4, color=blue, label="同口岸内地访客抵港（指数）")
        ax.bar([i + 0.2 for i in x], (sub3["hk_resident_mainland_land_departures"] / sub3.loc["2023", "hk_resident_mainland_land_departures"] * 100).values,
               0.4, color=orange, label="香港居民内地陆路口岸出境（指数）")
        for i, yv in enumerate(years3):
            ax.text(i - 0.2, sub3.loc[yv, "mainland_visitor_arrivals_mainland_land"] / sub3.loc["2023", "mainland_visitor_arrivals_mainland_land"] * 100 + 3,
                    f"{sub3.loc[yv,'mainland_land_departure_to_matching_land_visitor_ratio']:.2f}x", ha="center", fontsize=8, color=gray)
            ax.text(i + 0.2, sub3.loc[yv, "hk_resident_mainland_land_departures"] / sub3.loc["2023", "hk_resident_mainland_land_departures"] * 100 + 3,
                    f"{sub3.loc[yv,'hk_resident_mainland_land_departures']/1e8:.1f}亿", ha="center", fontsize=8, color=gray)
        ax.set_xticks(list(x))
        ax.set_xticklabels(years3)
        ax.set_ylabel("指数（2023=100）")
        ax.set_title("香港居民内地陆路出境与内地访客抵港", pad=28)
        ax.text(0.5, 1.01, "2023–2025；核心内地陆路口岸的匹配口径，不含港珠澳大桥；标注为出境/访客流量比",
                transform=ax.transAxes, ha="center", va="bottom", fontsize=9, color=gray)
        ax.legend()
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout(rect=[0, 0, 1, 0.90])
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
    latest_earnings_year = com.attrs["earnings_year_max"]
    prior_earnings_year = latest_earnings_year - 1
    latest_year = str(latest_earnings_year)
    prior_year = str(prior_earnings_year)
    lines.append(
        f"Run at {pd.Timestamp.now(tz='UTC').isoformat()}. "
        f"ImmD observation through {flow.attrs['source_date_max']}; "
        f"MTR patronage through {com.attrs['patronage_source_month_max']}; "
        f"MTR earnings bridge through FY{latest_earnings_year}."
    )
    lines.append("")
    lines.append("## 1. Cross-border flow proxy (ImmD daily, 内地访客 vs 内地陆路口岸出境)")
    lines.append("")
    f24 = flow.loc["2024"]; f25 = flow.loc["2025"]; f23 = flow.loc["2023"]
    lines.append(
        f"- 核心内地陆路口岸的香港居民出境 / 内地访客抵港比："
        f"2023 {f23['mainland_land_departure_to_matching_land_visitor_ratio']:.2f}x -> "
        f"2024 {f24['mainland_land_departure_to_matching_land_visitor_ratio']:.2f}x -> "
        f"2025 {f25['mainland_land_departure_to_matching_land_visitor_ratio']:.2f}x（同一组口岸）。"
    )
    lines.append(
        f"- 2025 核心内地陆路口岸香港居民出境 = {f25['hk_resident_mainland_land_departures']/1e8:.2f}亿，"
        f"同口岸内地访客抵港 = {f25['mainland_visitor_arrivals_mainland_land']/1e8:.2f}亿；"
        f"含港珠澳大桥的出境 / 访客比为 {f25['land_including_hzmb_departure_to_matching_visitor_ratio']:.2f}x。"
    )
    lines.append(
        "- 这是跨境流量/出境代理，不是消费金额；ImmD 不提供每名出境居民的消费额，"
        "不能单凭该比值证明租金下跌由北上消费造成。"
    )
    lines.append("")
    lines.append("## 2. Commercial/rental vs transport revenue + normalized intensity")
    lines.append("")
    years = [str(y) for y in sorted(int(y) for y in com.index if str(y).isdigit()) if y >= 2017]
    sub = com.loc[years][["transport_rev", "station_commercial", "rental", "station_plus_rental", "pax_m",
                          "station_rental_intensity_hkd_per_mtr_journey",
                          "transport_intensity_hkd_per_mtr_journey"]].round(2)
    lines.append(sub.to_markdown())
    lines.append("")
    lines.append(f"- {latest_earnings_year} 站内商业+租金 / 总客流收入强度 = HK$ {com.loc[latest_year,'station_rental_intensity_hkd_per_mtr_journey']:.2f}"
                 f" vs 2017 HK$ {com.loc['2017','station_rental_intensity_hkd_per_mtr_journey']:.2f}"
                 f"（{com.loc[latest_year,'station_rental_intensity_hkd_per_mtr_journey']/com.loc['2017','station_rental_intensity_hkd_per_mtr_journey']*100-100:+.0f}%；仅为 proxy）")
    lines.append(f"- {prior_earnings_year}->{latest_earnings_year}: transport 收入 {com.loc[prior_year,'transport_rev']:.0f}->{com.loc[latest_year,'transport_rev']:.0f} "
                 f"({com.loc[latest_year,'transport_rev']/com.loc[prior_year,'transport_rev']*100-100:+.1f}%)；"
                 f"站内商业+租金 {com.loc[prior_year,'station_plus_rental']:.0f}->{com.loc[latest_year,'station_plus_rental']:.0f}"
                 f" ({com.loc[latest_year,'station_plus_rental']/com.loc[prior_year,'station_plus_rental']*100-100:+.1f}%)")
    lines.append(f"- {prior_earnings_year}->{latest_earnings_year} 明细：站内商业 {com.loc[prior_year,'station_commercial']:.0f}->{com.loc[latest_year,'station_commercial']:.0f}"
                 f" ({com.loc[latest_year,'station_commercial']/com.loc[prior_year,'station_commercial']*100-100:+.2f}%)；"
                 f"租金 {com.loc[prior_year,'rental']:.0f}->{com.loc[latest_year,'rental']:.0f}"
                 f" ({com.loc[latest_year,'rental']/com.loc[prior_year,'rental']*100-100:+.1f}%) —— 拉低的是租金")
    lines.append(f"- {latest_earnings_year} 站内商业收入本身（不含租金）几乎 0 增长："
                 f"{com.loc[prior_year,'station_commercial']:,.0f} -> {com.loc[latest_year,'station_commercial']:,.0f} HK$m"
                 f" ({com.loc[latest_year,'station_commercial']/com.loc[prior_year,'station_commercial']*100-100:+.2f}%)")
    lines.append(f"- transport / 总客流收入强度 2017 HK$ {com.loc['2017','transport_intensity_hkd_per_mtr_journey']:.2f} -> {latest_earnings_year} HK$ {com.loc[latest_year,'transport_intensity_hkd_per_mtr_journey']:.2f} (+{com.loc[latest_year,'transport_intensity_hkd_per_mtr_journey']/com.loc['2017','transport_intensity_hkd_per_mtr_journey']*100-100:.0f}%)，"
                 f"而站内商业+租金强度 HK$ {com.loc['2017','station_rental_intensity_hkd_per_mtr_journey']:.2f} -> HK$ {com.loc[latest_year,'station_rental_intensity_hkd_per_mtr_journey']:.2f} ({com.loc[latest_year,'station_rental_intensity_hkd_per_mtr_journey']/com.loc['2017','station_rental_intensity_hkd_per_mtr_journey']*100-100:+.0f}%) —— "
                 "transport 端的高铁/票价 mix 改善，与商业/租金端的弱增长并存")
    lines.append("")
    lines.append("## 3. Summary interpretation")
    lines.append("")
    lines.append("- transport 收入相对总客流增长，而站内商业+租金收入强度下降，支持 Thesis B 的 mix-risk 方向。")
    lines.append("- 但出境流量与租金收入之间没有项目级/因果识别；它是需求背景 proxy，不是租金下跌的单一证明。")
    lines.append("")
    lines.append("## Methodology notes")
    lines.append("")
    lines.append("- 站内商业+租金统一用合并口径(2017-2019 MTR 仅披露合并线;2020+ 为两列相加)保持可比。2016 缺失。")
    lines.append("- ImmD 日度 2021 起,无 2019 疫前同日度户;2026 为 YTD(至 08-08)。")

    lines = [
        line for line in lines
        if not line.startswith("- 站内商业+租金统一用合并口径")
        and not line.startswith("- ImmD 日度 2021 起")
    ]
    lines.extend([
        "- 站内商业+租金统一用合并口径（2017-2019 MTR 仅披露合并线；2020+ 为两列相加），2016 缺失。",
        "- 商业/租金除以总客流只是暴露强度 proxy：还受出租面积、租户组合、reversion、广告/电信合同和商场客流影响。",
        "- 核心内地陆路口岸包括罗湖、落马洲、深圳湾、香园围、西九龙高铁等，不含港珠澳大桥；含港珠澳大桥的替代口径另列。",
        "- ImmD 原始数据从 2021-01-01 起；2026 是部分年度，不能与完整年度直接比较。",
    ])

    summary_md = os.path.join(args.out, "mtr_thesis_b_summary.md")
    with open(summary_md, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
