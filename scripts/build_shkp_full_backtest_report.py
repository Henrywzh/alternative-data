"""Build the consolidated SHKP FY + H1 prediction-vs-actual report."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.hk_real_estate.storage import load_latest_normalized


REPORT_PATH = ROOT / "docs/asia-markets/SHKP_FULL_BACKTEST_REPORT.md"
CHART_DIR = ROOT / "docs/asia-markets/charts"


def _latest(name: str) -> pd.DataFrame:
    return load_latest_normalized(name)


def _m(value: object) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):,.0f}"


def _p(value: object) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):+.1f}%"


def _eps(value: object) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):.2f}"


def _eps_delta(value: object) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):+.2f}"


def _make_fy_commercial_chart(commercial: pd.DataFrame) -> Path:
    data = commercial.pivot(index=["fiscal_year_end", "fiscal_label"], columns="method", values="forecast_rental_revenue_hkd_m").reset_index()
    actual = commercial.groupby(["fiscal_year_end", "fiscal_label"], as_index=False)["actual_rental_revenue_hkd_m"].first()
    data = data.merge(actual, on=["fiscal_year_end", "fiscal_label"], how="left").sort_values("fiscal_year_end")
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True, constrained_layout=True, gridspec_kw={"height_ratios": [2, 1]})
    x = list(range(len(data)))
    width = 0.2
    axes[0].bar([v - 1.5 * width for v in x], data["actual_rental_revenue_hkd_m"], width=width, label="FY actual", color="#1f4e79")
    axes[0].bar([v - 0.5 * width for v in x], data["distributed_lag"], width=width, label="Distributed lag", color="#59a14f")
    axes[0].bar([v + 0.5 * width for v in x], data["contemporaneous"], width=width, label="Contemporaneous", color="#b7c9e2")
    axes[0].bar([v + 1.5 * width for v in x], data["naive_flat"], width=width, label="Naive", color="#e07a5f")
    axes[0].set_ylabel("HKD million")
    axes[0].set_title("FY Hong Kong rental revenue: actual versus walk-forward forecasts")
    axes[0].grid(axis="y", alpha=0.25)
    axes[0].legend(frameon=False, ncol=4)
    for method, color, label in (("distributed_lag", "#3f7f4f", "Distributed lag error"), ("contemporaneous", "#5b7fa3", "Contemporaneous error"), ("naive_flat", "#c55a3d", "Naive error")):
        errors = commercial.loc[commercial["method"].eq(method)].sort_values("fiscal_year_end")
        axes[1].plot(errors["fiscal_label"], errors["error_hkd_m"] / errors["actual_rental_revenue_hkd_m"] * 100.0, marker="o", label=label, color=color)
    axes[1].axhline(0, color="#555", linewidth=1)
    axes[1].set_ylabel("Error (%)")
    axes[1].set_xlabel("Fiscal year")
    axes[1].tick_params(axis="x", rotation=35)
    axes[1].grid(axis="y", alpha=0.25)
    axes[1].legend(frameon=False, ncol=3)
    path = CHART_DIR / "shkp_full_fy_commercial_actual_vs_models.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def build_report() -> Path:
    commercial = _latest("shkp_commercial_backtest")
    skeleton = _latest("shkp_skeleton_historical_backtest")
    h1 = _latest("shkp_h1_actual_vs_nowcast")
    component = _latest("shkp_h1_component_actual_vs_nowcast")
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    commercial_chart = _make_fy_commercial_chart(commercial)

    commercial_summary = []
    for method, group in commercial.groupby("method"):
        commercial_summary.append(
            f"| {method} | {len(group)} | {group['absolute_percentage_error'].mean():.2f}% | {group['error_hkd_m'].abs().mean():,.0f} | {group['error_hkd_m'].mean():+,.0f} |"
        )
    skeleton_valid = skeleton["underlying_error_pct"].dropna()
    h1_group = h1.loc[(h1["metric"].eq("group_revenue")) & h1["model_status"].eq("valid_prior_share_holdout")]
    h1_profit = h1.loc[(h1["metric"].eq("reported_profit_attributable")) & h1["model_status"].eq("valid_prior_share_holdout")]
    h1_sales = h1.loc[(h1["metric"].eq("hk_property_sales_revenue")) & h1["model_status"].eq("valid_prior_share_holdout")]
    component_valid = component.loc[component["model_status"].eq("valid_holdout")]

    fy_rows = "\n".join(
        f"| {row.fiscal_label} | {_m(row.actual_underlying_profit_hkd_m)} | {_m(row.model_underlying_profit_hkd_m)} | {_p(row.underlying_error_pct)} | {_eps(row.eps_actual)} | {_eps(row.eps_model)} | {_eps_delta(row.eps_error)} |"
        for row in skeleton.sort_values("fiscal_year_end").itertuples()
    )
    commercial_rows = "\n".join(
        f"| {label} | {_m(actual)} | {_m(values.get('distributed_lag'))} ({_p(apes.get('distributed_lag'))}) | {_m(values.get('contemporaneous'))} ({_p(apes.get('contemporaneous'))}) | {_m(values.get('naive_flat'))} ({_p(apes.get('naive_flat'))}) |"
        for (year, label), group in commercial.groupby(["fiscal_year_end", "fiscal_label"], sort=True)
        for actual, values, apes in [(group.actual_rental_revenue_hkd_m.iloc[0], group.set_index("method").forecast_rental_revenue_hkd_m.to_dict(), group.set_index("method").absolute_percentage_error.to_dict())]
    )
    h1_rows = "\n".join(
        f"| {row.fiscal_label} | {row.metric} | {_m(row.h1_actual)} | {_m(row.full_year_actual)} | {_m(row.h1_annualized_forecast)} ({_p(row.h1_annualized_error_pct)}) | {_m(row.prior_share_forecast)} ({_p(row.prior_share_error_pct)}) | {row.model_status} |"
        for row in h1.sort_values(["metric", "target_fiscal_year"]).itertuples()
    )
    component_rows = "\n".join(
        f"| {row.fiscal_label} | {_m(row.full_year_group_revenue_hkd_m)} | {_m(row.fy_component_forecast_hkd_m)} | {_p(row.component_error_pct)} | {row.training_years or '—'} | {row.model_status} |"
        for row in component.sort_values("target_fiscal_year").itertuples()
    )
    report = f"""# SHKP Full Backtest: FY and H1 Predictions versus Actuals

## Scope

This report puts the major SHKP prediction-versus-actual layers on one page.
They are kept as separate targets: FY underlying profit, FY Hong Kong rental
revenue, H1-to-FY group revenue recognition, and the experimental H2 component
bridge. Error is forecast / actual − 1; positive means over-forecast.

## Headline comparison

| Layer | Valid periods | Method | Mean APE | Notes |
|---|---:|---|---:|---|
| FY underlying profit | {len(skeleton)} | Vintage margin replay | {skeleton_valid.abs().mean():.2f}% | Retrospective research replay; not strict PIT/OOS |
| FY HK rental revenue | {len(commercial.loc[commercial.method.eq('distributed_lag')])} | Distributed lag | {commercial.loc[commercial.method.eq('distributed_lag'),'absolute_percentage_error'].mean():.2f}% | Walk-forward OOS; scenario-grade elasticities |
| H1 group revenue | {len(h1_group)} | 2×H1 | {h1_group.h1_annualized_ape_pct.mean():.2f}% | Recognition baseline |
| H1 reported profit | {len(h1_profit)} | 2×H1 | {h1_profit.h1_annualized_ape_pct.mean():.2f}% | More volatile than revenue |
| H1 HK property sales | {len(h1_sales)} | 2×H1 | {h1_sales.h1_annualized_ape_pct.mean():.2f}% | Handover-driven, lumpy |
| H1 component bridge | {len(component_valid)} | Component H2 | {component_valid.component_ape_pct.mean():.2f}% | Experimental; currently worse than 2×H1 |

## FY whole-company underlying profit

| FY | Actual | Model | Error | EPS actual | EPS model | EPS error |
|---|---:|---:|---:|---:|---:|---:|
{fy_rows}

![FY underlying profit actual versus model](charts/shkp_backtest_v2_actual_vs_model.png)

The vintage replay has a 6.37% mean absolute error, but it uses retrospective
margin calibration and a current ownership snapshot. Treat it as a portability
diagnostic, not a clean historical trading forecast.

## FY Hong Kong rental revenue

| FY | Actual | Distributed lag | Contemporaneous | Naive |
|---|---:|---:|---:|---:|
{commercial_rows}

| Method | Periods | Mean APE | MAE (HKD m) | Mean signed error (HKD m) |
|---|---:|---:|---:|---:|
{chr(10).join(commercial_summary)}

![FY commercial actual versus models](charts/{commercial_chart.name})

## H1-to-FY recognition backtest

`2×H1` annualises the current interim actual. `Prior-share` divides H1 by the
median H1/FY share from strictly earlier years. Neither is a complete earnings
model; they are recognition baselines.

| FY | Metric | H1 actual | FY actual | 2×H1 (error) | Prior-share (error) | Status |
|---|---|---:|---:|---:|---:|---|
{h1_rows}

![H1 group revenue actual versus baselines](charts/shkp_h1_actual_vs_nowcast.png)

## Component H2 bridge

```text
FY group revenue = H1 actual + H2 HK development + H2 HK rental + H2 hotel + H2 residual
```

| FY | FY actual | Component forecast | Error | Training years | Status |
|---|---:|---:|---:|---|---|
{component_rows}

![H1 component bridge](charts/shkp_h1_component_actual_vs_nowcast.png)

The component bridge is intentionally retained even though its current mean
APE is about 28.5%. The FY2024/25 overshoot demonstrates that historical
component H2/H1 ratios are not stationary when handover timing changes. The
next upgrade should use PIT project completion/recognition schedules, not
window-tuning after observing the FY result.

## Data-quality and PIT notes

- The latest H1 run has 149 parsed facts across 10 official interim PDFs.
- H1 training years are strictly earlier than each target; no future-year
  training leakage was detected.
- FY2017–FY2020 consolidated annual fallback rows remain non-PIT because the
  original announcement dates are unavailable.
- FY2025/26 H1 has a current component forecast but no FY actual, so it is not
  scored.
- Consensus and broker snapshots are not included as historical forecasts;
  the repository still lacks a complete announcement-vintage consensus tape.

Source reports:

- [SHKP H1 backtest report](SHKP_H1_BACKTEST_REPORT.md)
- [SHKP skeleton backtest v2](SHKP_SKELETON_BACKTEST_V2_REPORT.md)
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    return REPORT_PATH


if __name__ == "__main__":
    print(build_report())
