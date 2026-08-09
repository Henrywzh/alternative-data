#!/usr/bin/env python3
"""Generate charts for the MTR modelling report (docs/asia-markets/charts)."""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np

plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang HK", "Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NORM = os.path.join(REPO, "data", "normalized", "hk_transport")
PROC = os.path.join(REPO, "data", "processed", "transport")
CHART_DIR = os.path.join(REPO, "docs", "asia-markets", "charts")
os.makedirs(CHART_DIR, exist_ok=True)

C = {"blue": "#1f77b4", "orange": "#ff7f0e", "green": "#2ca02c", "red": "#d62728",
     "gray": "#7f7f7f", "purple": "#9467bd"}


def chart1_farebox_annual():
    """Farebox annual backtest: model vs actual 2019-2025 + error bars."""
    ann = pd.read_csv(os.path.join(PROC, "mtr_farebox_revenue_annual_backtest.csv"))
    years = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
    ann = ann[ann["year"].isin(years)].sort_values("year")
    fig, ax = plt.subplots(figsize=(10, 5.5))
    x = np.arange(len(ann))
    ax.bar(x - 0.2, ann["farebox_revenue_hkdm"], 0.4, label="模型估算", color=C["blue"])
    ax.bar(x + 0.2, ann["transport_ops_revenue_hkdm"], 0.4, label="官方实际", color=C["orange"])
    for i, (m, a) in enumerate(zip(ann["farebox_revenue_hkdm"], ann["transport_ops_revenue_hkdm"])):
        if np.isnan(a):
            continue
        err = (m - a) / a * 100
        ax.text(i, max(m, a) + 500, f"{err:+.1f}%", ha="center", fontsize=9, color=C["gray"])
    ax.text(3.15, 22500, "2024 = 校准年", fontsize=9, color=C["red"], ha="center")
    ax.text(6.15, 24200, "2025 OOS +0.4%", fontsize=9, color=C["green"], ha="center")
    ax.set_xticks(x)
    ax.set_xticklabels(ann["year"].astype(int))
    ax.set_ylabel("HK$ 百万")
    ax.set_title("MTR 客运营收 Farebox 年度 Backtest（2019–2025）")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "chart1_farebox_annual.png"), dpi=150)
    plt.close(fig)


def chart2_farebox_monthly():
    """Monthly farebox revenue series 2000-2026 with COVID annotation."""
    monthly = pd.read_csv(os.path.join(PROC, "mtr_farebox_revenue_monthly.csv"))
    monthly["date"] = pd.to_datetime(monthly["date"])
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(monthly["date"], monthly["farebox_revenue_hkdm"], lw=0.8, color=C["blue"])
    ax.axvspan(pd.Timestamp("2020-01-01"), pd.Timestamp("2023-01-31"), color=C["red"], alpha=0.12)
    ax.text(pd.Timestamp("2021-07-01"), 480, "COVID 封关期", color=C["red"], fontsize=9)
    ax.set_ylabel("HK$ 百万/月")
    ax.set_title("MTR 月度票务营收估算（2000-01 至 2026-06，318 个月）")
    ax.xaxis.set_major_locator(mdates.YearLocator(4))
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "chart2_farebox_monthly.png"), dpi=150)
    plt.close(fig)


def chart3_property_history():
    """Historical HK property development profit (post-tax) with milestones."""
    hist = pd.read_csv(os.path.join(NORM, "mtr_historical_earnings_bridge.csv"))
    h = hist[["year", "hk_pdp_post_tax"]].dropna().sort_values("year")
    fig, ax = plt.subplots(figsize=(10, 5))
    colors = [C["orange"] if y in (2022, 2024, 2025) else C["blue"] for y in h["year"]]
    ax.bar(h["year"].astype(int), h["hk_pdp_post_tax"], color=colors, alpha=0.9)
    notes = {2021: "LP7-9", 2022: "LP10+SOUTHSIDE P1/2", 2023: "低谷 20.8亿",
             2024: "凱柏峰+海盈山+HMT P1", 2025: "P3/P5+LP12+HMT P1/2"}
    for y, note in notes.items():
        v = h[h["year"] == y]["hk_pdp_post_tax"].iloc[0]
        ax.annotate(note, (y, v), textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=8, color=C["gray"])
    ax.set_ylabel("HK$ 百万（税后）")
    ax.set_title("香港物业发展利润历史（2014–2025）—— 大年/小年周期")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "chart3_property_history.png"), dpi=150)
    plt.close(fig)


def chart4_timing():
    """Timing timeline: price list -> first deal -> OP -> recognition."""
    timing = pd.read_csv(os.path.join(NORM, "mtr_property_timing_history.csv"))
    fig, ax = plt.subplots(figsize=(11, 6))
    labels = {"the-southside-p1": "晉環", "the-southside-p2": "揚海",
              "the-southside-p4": "海盈山", "ho-man-tin-p2": "瑜一",
              "lohas-park-p11": "凱柏峰I", "lohas-park-p12": "LP12"}
    for i, (_, r) in enumerate(timing.iterrows()):
        pid = r["project_id"]
        y = len(timing) - i - 1
        pl = pd.to_datetime(r["first_price_list_date"], errors="coerce")
        ft = pd.to_datetime(r["first_transaction_date"], errors="coerce")
        op = pd.to_datetime(r["op_issuance_month"], errors="coerce")
        rec = pd.Timestamp(f"{int(r['mtr_recognition_year'])}-06-30")
        if pd.notna(pl):
            ax.plot([pl, pl], [y - 0.25, y + 0.25], color=C["purple"], lw=3)
        if pd.notna(ft):
            ax.plot([ft, ft], [y - 0.25, y + 0.25], color=C["blue"], lw=3)
        if pd.notna(op):
            ax.plot([op, op], [y - 0.25, y + 0.25], color=C["orange"], lw=3)
        ax.plot([rec, rec], [y - 0.25, y + 0.25], color=C["green"], lw=3)
        ax.text(pd.Timestamp("2019-12-01"), y, labels.get(pid, pid), fontsize=9)
    ax.plot([], [], color=C["purple"], lw=3, label="首张价单")
    ax.plot([], [], color=C["blue"], lw=3, label="首笔交易")
    ax.plot([], [], color=C["orange"], lw=3, label="入伙纸 OP")
    ax.plot([], [], color=C["green"], lw=3, label="MTR 确认利润")
    ax.set_xlim(pd.Timestamp("2020-01-01"), pd.Timestamp("2026-12-31"))
    ax.set_yticks([])
    ax.set_ylim(-0.6, len(timing) - 0.4)
    ax.set_title("物业事件时间线：价单 → 交易 → 入伙纸 → 利润确认")
    ax.legend(loc="upper left", fontsize=9)
    ax.xaxis.set_major_locator(mdates.YearLocator(1))
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "chart4_timing.png"), dpi=150)
    plt.close(fig)


def chart5_expected_profit():
    """FY26 expected property profit by phase (base) + bear/base/bull total."""
    exp = pd.read_csv(os.path.join(NORM, "mtr_property_expected_profit_fy26.csv"))
    exp = exp[exp["data_status"].notna()].sort_values("expected_profit_base_hkdm", ascending=True)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5), gridspec_kw={"width_ratios": [1.6, 1]})
    names = {"tai-wai": "Tai Wai", "the-southside-p5": "P5 滶晨", "lohas-park-p12": "LP12 海瑅灣",
             "lohas-park-p13": "LP13", "the-southside-p6": "P6", "yau-tong-vb": "Yau Tong VB",
             "lohas-park-p11-ii-iii": "凱柏峰II/III", "ho-man-tin-p1": "朗賢峯"}
    vals = exp["expected_profit_base_hkdm"].fillna(0)
    labels = [names.get(p, p) for p in exp["project_id"]]
    colors = [C["blue"] if s == "srpe_data" else C["gray"] for s in exp["data_status"]]
    ax1.barh(labels, vals / 1000, color=colors, alpha=0.9)
    ax1.set_xlabel("期望利润 HK$ 十亿（base）")
    ax1.set_title("FY26 期望物业利润构成（按项目）")
    total = vals.sum() / 1000
    low = exp["expected_profit_low_hkdm"].fillna(0).sum() / 1000
    high = exp["expected_profit_high_hkdm"].fillna(0).sum() / 1000
    ax2.bar(["Bear", "Base", "Bull"], [low, total, high], color=[C["red"], C["blue"], C["green"]])
    ax2.axhline(11.084, color=C["gray"], ls="--")
    ax2.text(2.4, 11.3, "FY25 实际 110.8亿", fontsize=8, color=C["gray"], ha="right")
    ax2.set_ylabel("HK$ 十亿")
    ax2.set_title("FY26 物业利润区间")
    fig.suptitle("FY26 期望物业利润（Timing × Magnitude V1）", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "chart5_expected_profit.png"), dpi=150)
    plt.close(fig)


def chart6_eps_bridge():
    """EPS bridge: our bear/base/bull vs Street."""
    eps = pd.read_csv(os.path.join(NORM, "mtr_property_eps_bridge.csv"))
    fig, ax = plt.subplots(figsize=(9, 5.5))
    x = np.arange(3)
    ours = eps["reported_eps_est_hkd"].values
    ax.bar(x, ours, 0.5, color=[C["red"], C["blue"], C["green"]], label="我们的 FY26E EPS")
    ax.axhline(2.52, color=C["purple"], ls="--", lw=1.5)
    ax.text(2.55, 2.53, "Street 共识 2.52", color=C["purple"], fontsize=10)
    ax.axhline(2.36, color=C["gray"], ls=":", lw=1.5)
    ax.text(2.55, 2.37, "FY25 实际 2.36", color=C["gray"], fontsize=10)
    for i, v in enumerate(ours):
        ax.text(i, v + 0.05, f"{v:.2f}", ha="center", fontsize=11, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(["Bear", "Base", "Bull"])
    ax.set_ylim(0, 3.0)
    ax.set_ylabel("Reported EPS（HK$）")
    ax.set_title("FY26E EPS：我们的区间 vs Street")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "chart6_eps_bridge.png"), dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    chart1_farebox_annual()
    chart2_farebox_monthly()
    chart3_property_history()
    chart4_timing()
    chart5_expected_profit()
    chart6_eps_bridge()
    print("charts written to", CHART_DIR)
