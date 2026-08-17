#!/usr/bin/env python3
"""Generate charts for the MTR modelling report (docs/asia-markets/charts)."""
import os
import sys
import json

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


def chart1b_farebox_h1():
    """H1 Jan-Jun model estimate versus official interim actuals."""
    h1 = pd.read_csv(os.path.join(PROC, "mtr_farebox_revenue_h1_backtest.csv"))
    h1 = h1.sort_values("year")
    reported = h1[h1["actual_status"].eq("reported")]
    forecast = h1[h1["backtest_role"].eq("current_forecast")]

    fig, ax = plt.subplots(figsize=(10.5, 5.5))
    ax.plot(
        reported["year"],
        reported["h1_model_revenue_hkdm"],
        marker="o",
        lw=2,
        color=C["blue"],
        label="模型估算（Jan-Jun）",
    )
    if not forecast.empty:
        # Keep the current forecast visually separate from the historical
        # model-vs-actual comparison.
        ax.plot(
            [reported["year"].max(), *forecast["year"]],
            [reported["h1_model_revenue_hkdm"].iloc[-1], *forecast["h1_model_revenue_hkdm"]],
            marker="o",
            lw=2,
            ls="--",
            color=C["blue"],
            label="当前 H1 forecast（无实际值）",
        )
    ax.plot(
        reported["year"],
        reported["h1_actual_transport_ops_revenue_hkdm"],
        marker="s",
        lw=2,
        color=C["orange"],
        label="官方中报实际",
    )
    for _, row in reported.iterrows():
        ax.annotate(
            f"{row['model_error_pct']:+.1f}%",
            (row["year"], row["h1_actual_transport_ops_revenue_hkdm"]),
            textcoords="offset points",
            xytext=(0, 8),
            ha="center",
            fontsize=8,
            color=C["gray"],
        )
    if not forecast.empty:
        row = forecast.iloc[0]
        ax.annotate(
            f"{row['h1_model_revenue_hkdm']:,.0f}",
            (row["year"], row["h1_model_revenue_hkdm"]),
            textcoords="offset points",
            xytext=(0, 8),
            ha="center",
            fontsize=9,
            color=C["blue"],
        )
    ax.axvline(2024, color=C["red"], ls=":", lw=1)
    ax.text(2024.05, ax.get_ylim()[1] * 0.98, "2024 校准", color=C["red"], fontsize=8, va="top")
    ax.axvline(2025, color=C["green"], ls=":", lw=1)
    ax.text(2025.05, ax.get_ylim()[1] * 0.91, "2025 OOS", color=C["green"], fontsize=8, va="top")
    chart_years = sorted(
        set(reported["year"].astype(int)).union(set(forecast["year"].astype(int)))
    )
    ax.set_xticks(chart_years)
    ax.set_xlim(min(chart_years) - 0.4, max(chart_years) + 0.4)
    ax.set_xlabel("财政年度 H1（1–6月）")
    ax.set_ylabel("HK$ 百万")
    ax.set_title("MTR 客运营收 H1 Backtest：模型 vs 官方实际", pad=18)
    ax.text(
        0.5,
        1.01,
        "2017–2025 为官方中报实际；2026 为当前 forecast；百分比为模型误差",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=9,
        color=C["gray"],
    )
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.91])
    fig.savefig(os.path.join(CHART_DIR, "chart1b_farebox_h1.png"), dpi=150)
    plt.close(fig)


def chart1c_farebox_walk_forward_practical_oos():
    """Show the chronological prior-period-yield practical OOS track only.

    This is intentionally separate from ``chart1_farebox_annual`` and
    ``chart1b_farebox_h1``.  Those charts use the legacy FY2024-anchor
    structural replay.  Here every plotted row is produced by
    ``build_mtr_walk_forward_oos.py`` using only an earlier same-period
    official actual.  The source is still labelled practical OOS because
    historical patronage release vintages are not captured.
    """
    path = os.path.join(PROC, "mtr_farebox_walk_forward_oos.csv")
    walk = pd.read_csv(path)
    valid = walk[
        walk["has_prediction"].astype(bool)
        & walk["has_actual"].astype(bool)
        & walk["evaluation_status"].eq("valid_practical_oos")
    ].copy()
    if valid.empty:
        raise ValueError(f"no valid practical OOS rows found in {path}")
    valid["target_year"] = valid["target_year"].astype(int)
    valid["predicted_value_hkdm"] = pd.to_numeric(valid["predicted_value_hkdm"])
    valid["actual_value_hkdm"] = pd.to_numeric(valid["actual_value_hkdm"])
    valid["error_pct"] = pd.to_numeric(valid["error_pct"])

    fig, axes = plt.subplots(
        2,
        2,
        figsize=(14, 8.5),
        gridspec_kw={"width_ratios": [2.4, 1.2]},
    )
    for row_index, period_type in enumerate(("FY", "H1")):
        frame = valid[valid["period_type"].eq(period_type)].sort_values("target_year")
        x = np.arange(len(frame))
        ax_level, ax_error = axes[row_index]
        width = 0.36
        ax_level.bar(
            x - width / 2,
            frame["predicted_value_hkdm"],
            width,
            color=C["blue"],
            label="OOS 预测",
        )
        ax_level.bar(
            x + width / 2,
            frame["actual_value_hkdm"],
            width,
            color=C["orange"],
            label="官方实际",
        )
        for i, (_, item) in enumerate(frame.iterrows()):
            ax_level.text(
                i,
                max(item["predicted_value_hkdm"], item["actual_value_hkdm"]) + 250,
                f"{item['error_pct']:+.1f}%",
                ha="center",
                va="bottom",
                fontsize=8,
                color=C["gray"],
            )
        ax_level.set_xticks(x)
        ax_level.set_xticklabels(frame["target_year"].astype(str))
        ax_level.set_ylabel("HK$ 百万")
        ax_level.set_title(f"{period_type}：预测 vs 官方实际")
        ax_level.grid(axis="y", alpha=0.3)
        if row_index == 0:
            ax_level.legend(loc="upper left")

        colors = [C["red"] if value > 0 else C["green"] for value in frame["error_pct"]]
        ax_error.axhline(0, color="black", lw=0.8)
        ax_error.bar(x, frame["error_pct"], color=colors, alpha=0.9)
        ax_error.set_xticks(x)
        ax_error.set_xticklabels(frame["target_year"].astype(str), rotation=45)
        ax_error.set_ylabel("误差 %")
        ax_error.set_title(f"{period_type}：预测误差")
        ax_error.grid(axis="y", alpha=0.3)
        for i, value in enumerate(frame["error_pct"]):
            ax_error.text(
                i,
                value + (1.0 if value >= 0 else -1.0),
                f"{value:+.1f}%",
                ha="center",
                va="bottom" if value >= 0 else "top",
                fontsize=8,
            )

    fig.suptitle(
        "MTR 客运营收：Chronological Walk-forward Practical OOS",
        fontsize=14,
        y=0.98,
    )
    fig.text(
        0.5,
        0.945,
        "每个目标期只使用更早一期已公布的同类财报实际估计 yield；没有使用 FY2024 anchor 或目标期财报实际",
        ha="center",
        fontsize=9,
        color=C["gray"],
    )
    fig.text(
        0.5,
        0.015,
        "FY MAPE 9.32%（2020–2025，n=6）｜H1 MAPE 8.10%（2018–2025，n=8）｜PIT grade B：历史客流 release vintages 未保存",
        ha="center",
        fontsize=9,
        color=C["gray"],
    )
    fig.tight_layout(rect=[0, 0.05, 1, 0.91])
    fig.savefig(
        os.path.join(CHART_DIR, "chart1c_farebox_walk_forward_practical_oos.png"),
        dpi=150,
    )
    plt.close(fig)


def chart1d_farebox_half_year_walk_forward_oos():
    """Continuous H1/H2 chart for the same-half chronological OOS track."""
    path = os.path.join(PROC, "mtr_farebox_half_year_walk_forward_oos.csv")
    half = pd.read_csv(path)
    half["target_year"] = half["target_year"].astype(int)
    half["half_order"] = half["period_type"].map({"H1": 1, "H2": 2})
    # Match the useful comparable window in the reference image.  Earlier
    # rows are intentionally retained in the CSV, but contribute no observed
    # actual or prediction and only create a misleading block of empty space.
    half = (
        half[half["target_year"].ge(2017)]
        .sort_values(["target_year", "half_order"])
        .reset_index(drop=True)
    )
    half["label"] = half["target_year"].astype(str) + " " + half["period_type"]
    x = np.arange(len(half))

    actual_mask = half["has_actual"].astype(bool)
    oos_mask = half["has_prediction"].astype(bool) & actual_mask
    forecast = half[half["evaluation_status"].eq("current_forecast")].copy()

    fig, ax = plt.subplots(figsize=(16, 7.5))
    # Shade alternate calendar years without implying data availability.
    for year in sorted(half["target_year"].unique()):
        year_rows = half[half["target_year"].eq(year)]
        if year % 2 == 0:
            ax.axvspan(
                year_rows.index.min() - 0.5,
                year_rows.index.max() + 0.5,
                color="#f2f5f9",
                zorder=0,
            )

    oos_values = half["predicted_value_hkdm"].where(oos_mask, np.nan)
    actual_values = half["actual_value_hkdm"].where(actual_mask, np.nan)
    ax.plot(
        x,
        oos_values,
        color="#2f6fed",
        marker="o",
        lw=2.5,
        ms=5,
        label="同半年度 chronological OOS 预测",
        zorder=3,
    )
    ax.plot(
        x,
        actual_values,
        color="#18212f",
        marker="o",
        lw=2.5,
        ms=5,
        label="官方实际（H1）/ FY−H1 派生实际（H2）",
        zorder=4,
    )
    if not forecast.empty:
        ax.scatter(
            forecast.index,
            forecast["predicted_value_hkdm"],
            s=115,
            facecolors="white",
            edgecolors="#d95b64",
            linewidths=2.5,
            label="当前 H1 forecast（不计入 OOS）",
            zorder=6,
        )
        for _, row in forecast.iterrows():
            ax.annotate(
                f"{row['period_label']} forecast",
                (row.name, row["predicted_value_hkdm"]),
                xytext=(8, -16),
                textcoords="offset points",
                color="#d95b64",
                fontsize=9,
                ha="left",
            )

    for index, row in half[oos_mask].iterrows():
        ax.annotate(
            f"{row['error_pct']:+.1f}%",
            (index, row["predicted_value_hkdm"]),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            color="#2f6fed",
            fontsize=8,
        )

    ax.set_xticks(x)
    ax.set_xticklabels(half["label"], rotation=45, ha="right")
    ax.set_ylabel("HK$ million")
    ax.set_xlabel("Half-year period")
    ax.set_title("")
    fig.suptitle(
        "MTR transport operations revenue — sequential half-year practical OOS",
        x=0.04,
        y=0.975,
        ha="left",
        fontsize=17,
        fontweight="bold",
    )
    fig.text(
        0.04,
        0.935,
        "H1 and H2 are forecast separately using only the latest earlier actual for the same half; FY is not plotted separately.",
        color="#718096",
        fontsize=10,
    )
    ax.axvline(
        forecast.index.min() - 0.5 if not forecast.empty else len(half) - 0.5,
        color="#d95b64",
        ls=":",
        lw=1.5,
        alpha=0.8,
    )
    ax.legend(loc="upper left", frameon=False, ncol=3)
    ax.grid(axis="y", color="#d9e0ea", alpha=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_ylim(bottom=0)

    summary_path = os.path.join(PROC, "mtr_farebox_half_year_walk_forward_summary.json")
    with open(summary_path, "r", encoding="utf-8") as handle:
        summary = json.load(handle)
    h1 = summary["metrics"]["H1"]
    h2 = summary["metrics"]["H2"]
    fig.text(
        0.01,
        0.01,
        f"H1 MAPE {h1['mape_pct']:.2f}% (n={h1['n']})  |  H2 MAPE {h2['mape_pct']:.2f}% (n={h2['n']})  |  PIT grade B: historical patronage release vintages not captured",
        color="#718096",
        fontsize=9,
    )
    fig.tight_layout(rect=[0, 0.04, 1, 0.90])
    fig.savefig(
        os.path.join(CHART_DIR, "chart1d_farebox_half_year_walk_forward_oos.png"),
        dpi=150,
    )
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
    chart1b_farebox_h1()
    chart1c_farebox_walk_forward_practical_oos()
    chart1d_farebox_half_year_walk_forward_oos()
    chart2_farebox_monthly()
    chart3_property_history()
    chart4_timing()
    chart5_expected_profit()
    chart6_eps_bridge()
    print("charts written to", CHART_DIR)
