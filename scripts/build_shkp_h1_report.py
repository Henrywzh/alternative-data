"""Render the reproducible SHKP H1 backtest report and charts."""

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
REPORT_PATH = ROOT / "docs/asia-markets/SHKP_H1_BACKTEST_REPORT.md"
CHART_DIR = ROOT / "docs/asia-markets/charts"


def _latest(name: str) -> pd.DataFrame:
    return load_latest_normalized(name)


def _pct(value: float | None) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{value:.1f}%"


def _m(value: float | None) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{value:,.0f}"


def _make_charts(panel: pd.DataFrame, bridge: pd.DataFrame, backtest: pd.DataFrame, component: pd.DataFrame) -> list[str]:
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    period_order = panel[["fiscal_year_end", "fiscal_label"]].drop_duplicates().sort_values("fiscal_year_end")

    # Consolidated H1 actuals.
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, constrained_layout=True)
    for metric, label, axis in (
        ("group_revenue", "Group revenue (HKD m)", axes[0]),
        ("underlying_profit_attributable", "Underlying profit attributable (HKD m)", axes[1]),
    ):
        data = panel.loc[panel["metric"].eq(metric)].copy().sort_values("fiscal_year_end")
        axis.plot(data["fiscal_label"], data["value"], marker="o", linewidth=2, color="#1f4e79")
        axis.set_ylabel(label)
        axis.grid(axis="y", alpha=0.25)
    axes[-1].tick_params(axis="x", rotation=35)
    fig.suptitle("SHKP official H1 consolidated actuals, FY2016/17–FY2025/26")
    path = CHART_DIR / "shkp_h1_consolidated_actuals.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    outputs.append(str(path))

    # Actual versus H1-to-FY nowcast baselines for group revenue.  Keep the
    # actual/model panel and the signed error panel together so this view has
    # the same reading order as the FY backtest charts.
    data = backtest.loc[backtest["metric"].eq("group_revenue")].copy().sort_values("target_fiscal_year")
    valid = data.loc[data["full_year_actual"].notna()].copy()
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True, constrained_layout=True, gridspec_kw={"height_ratios": [2, 1]})
    ax = axes[0]
    x = range(len(valid))
    width = 0.25
    ax.bar([v - width for v in x], valid["full_year_actual"], width=width, label="FY actual", color="#1f4e79")
    ax.bar(x, valid["h1_annualized_forecast"], width=width, label="2× H1", color="#b7c9e2")
    ax.bar([v + width for v in x], valid["prior_share_forecast"], width=width, label="Prior 3Y median H1 share", color="#e07a5f")
    ax.set_ylabel("HKD million")
    ax.set_title("FY group revenue forecast made at H1: actual versus baselines")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, ncol=3)
    error_ax = axes[1]
    error_ax.axhline(0, color="#555", linewidth=1)
    error_ax.plot(valid["fiscal_label"], valid["h1_annualized_error_pct"], marker="o", color="#5b7fa3", label="2× H1 error")
    error_ax.plot(valid["fiscal_label"], valid["prior_share_error_pct"], marker="o", color="#c55a3d", label="Prior-share error")
    error_ax.set_ylabel("Error (%)")
    error_ax.set_xlabel("Fiscal year")
    error_ax.tick_params(axis="x", rotation=35)
    error_ax.grid(axis="y", alpha=0.25)
    error_ax.legend(frameon=False, ncol=2)
    path = CHART_DIR / "shkp_h1_actual_vs_nowcast.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    outputs.append(str(path))

    # Component H2 bridge versus the two baselines.  The component model is
    # intentionally shown only where all four H1 components were observed and
    # a full-year actual exists; sparse years remain visible in the table.
    component_valid = component.loc[component["model_status"].eq("valid_holdout")].copy().sort_values("target_fiscal_year")
    if not component_valid.empty:
        baseline = valid.loc[valid["target_fiscal_year"].isin(component_valid["target_fiscal_year"])].copy()
        merged = component_valid.merge(baseline[["target_fiscal_year", "h1_annualized_forecast", "prior_share_forecast"]], on="target_fiscal_year", how="left")
        fig, ax = plt.subplots(figsize=(11, 5.5), constrained_layout=True)
        x = range(len(merged))
        width = 0.2
        ax.bar([v - 1.5 * width for v in x], merged["full_year_group_revenue_hkd_m"], width=width, label="FY actual", color="#1f4e79")
        ax.bar([v - 0.5 * width for v in x], merged["h1_annualized_forecast"], width=width, label="2× H1", color="#b7c9e2")
        ax.bar([v + 0.5 * width for v in x], merged["prior_share_forecast"], width=width, label="Prior-share", color="#e07a5f")
        ax.bar([v + 1.5 * width for v in x], merged["fy_component_forecast_hkd_m"], width=width, label="Component H2", color="#59a14f")
        ax.set_xticks(list(x), merged["fiscal_label"], rotation=35)
        ax.set_ylabel("HKD million")
        ax.set_title("FY group revenue: component H2 bridge versus H1 baselines")
        ax.grid(axis="y", alpha=0.25)
        ax.legend(frameon=False, ncol=4)
        path = CHART_DIR / "shkp_h1_component_actual_vs_nowcast.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        outputs.append(str(path))

    # Recognition shares.
    fig, ax = plt.subplots(figsize=(11, 5.5), constrained_layout=True)
    for metric, label, color in (
        ("group_revenue", "Group revenue", "#1f4e79"),
        ("reported_profit_attributable", "Reported profit", "#e07a5f"),
    ):
        data = bridge.loc[(bridge["metric"].eq(metric)) & bridge["full_year_actual"].notna()].sort_values("fiscal_year_end")
        ax.plot(data["fiscal_label"], data["h1_share_pct"], marker="o", linewidth=2, label=label, color=color)
    ax.axhline(50, color="#777", linestyle="--", linewidth=1, label="50% reference")
    ax.set_ylabel("H1 share of FY (%)")
    ax.set_ylim(0, 100)
    ax.set_title("Recognition seasonality: H1 share of full-year actual")
    ax.tick_params(axis="x", rotation=35)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, ncol=3)
    path = CHART_DIR / "shkp_h1_recognition_share.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    outputs.append(str(path))

    # HK commercial series.
    fig, ax = plt.subplots(figsize=(11, 5.5), constrained_layout=True)
    for metric, label, color in (
        ("hk_rental_revenue", "HK rental revenue", "#1f4e79"),
        ("hk_office_revenue", "HK office revenue", "#59a14f"),
        ("hk_retail_revenue", "HK retail revenue", "#e07a5f"),
    ):
        data = panel.loc[panel["metric"].eq(metric)].sort_values("fiscal_year_end")
        if data.empty:
            continue
        ax.plot(data["fiscal_label"], data["value"], marker="o", linewidth=2, label=label, color=color)
    ax.set_ylabel("HKD million")
    ax.set_title("Hong Kong commercial indicators disclosed in H1 reports")
    ax.tick_params(axis="x", rotation=35)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, ncol=3)
    path = CHART_DIR / "shkp_h1_hk_commercial.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    outputs.append(str(path))
    return outputs


def build_report() -> Path:
    registry = _latest("shkp_h1_report_registry")
    panel = _latest("shkp_h1_actual_panel")
    bridge = _latest("shkp_h1_to_fy_bridge")
    backtest = _latest("shkp_h1_actual_vs_nowcast")
    component = _latest("shkp_h1_component_actual_vs_nowcast")
    chart_paths = _make_charts(panel, bridge, backtest, component)

    group_bt = backtest.loc[(backtest["metric"].eq("group_revenue")) & backtest["model_status"].eq("valid_prior_share_holdout")]
    profit_bt = backtest.loc[(backtest["metric"].eq("reported_profit_attributable")) & backtest["model_status"].eq("valid_prior_share_holdout")]
    hk_sales_bt = backtest.loc[(backtest["metric"].eq("hk_property_sales_revenue")) & backtest["model_status"].eq("valid_prior_share_holdout")]
    component_bt = component.loc[component["model_status"].eq("valid_holdout")].copy().sort_values("target_fiscal_year")
    latest_h1 = panel.loc[panel["fiscal_label"].eq("FY2025/26")]
    def value(metric: str, scope: str | None = None) -> float | None:
        subset = latest_h1.loc[latest_h1["metric"].eq(metric)]
        if scope is not None:
            subset = subset.loc[subset["scope"].eq(scope)]
        return float(subset.iloc[0]["value"]) if not subset.empty else None

    summary_rows = []
    for metric, label, data in (
        ("group_revenue", "Group revenue", group_bt),
        ("reported_profit_attributable", "Reported profit", profit_bt),
        ("hk_property_sales_revenue", "HK property-sales revenue", hk_sales_bt),
    ):
        summary_rows.append(
            f"| {label} | {len(data)} | {_pct(data['h1_annualized_ape_pct'].mean() if not data.empty else None)} | {_pct(data['prior_share_ape_pct'].mean() if not data.empty else None)} |"
        )

    component_summary = (
        f"| Component H2 bridge | {len(component_bt)} | {_pct(component_bt['component_ape_pct'].mean() if not component_bt.empty else None)} | "
        f"{_pct(component_bt['component_ape_pct'].median() if not component_bt.empty else None)} | "
        f"{_pct(component_bt['component_error_pct'].mean() if not component_bt.empty else None)} |"
    )
    component_rows = "\n".join(
        f"| {row.fiscal_label} | {_m(row.full_year_group_revenue_hkd_m)} | {_m(row.fy_component_forecast_hkd_m)} | {_pct(row.component_error_pct)} | {_pct(row.component_ape_pct)} | {row.training_years or '—'} |"
        for row in component.itertuples()
        if row.model_status in {"valid_holdout", "valid_current_h1_only"}
    )

    bridge_table = bridge.loc[(bridge["metric"].eq("group_revenue")) & bridge["full_year_actual"].notna()].copy().sort_values("fiscal_year_end")
    bridge_rows = "\n".join(
        f"| {row.fiscal_label} | {_m(row.h1_actual)} | {_m(row.h2_actual)} | {_m(row.full_year_actual)} | {_pct(row.h1_share_pct)} | {('official' if 'official' in str(row.pit_quality) else 'fallback non-PIT')} |"
        for row in bridge_table.itertuples()
    )
    report = f"""# SHKP H1 Actual Panel and Recognition Backtest

## Technical summary

- The official issuer catalogue now covers **10 interim reports from FY2016/17 through FY2025/26**. All 10 PDFs fetched successfully and all panel rows carry the report release date as the earliest availability date.
- The H1 actual panel contains **{len(panel):,} fact rows**. The core consolidated metrics (revenue, reported/underlying profit, gross/net rental income, EPS and interim dividend) have one observation in every report year.
- In FY2025/26 H1, SHKP reported group revenue of **HKD {_m(value('group_revenue'))}m**, underlying profit attributable of **HKD {_m(value('underlying_profit_attributable'))}m**, Hong Kong rental revenue of **HKD {_m(value('hk_rental_revenue'))}m**, office revenue of **HKD {_m(value('hk_office_revenue'))}m**, and retail revenue of **HKD {_m(value('hk_retail_revenue'))}m**.
- The expanding holdout is useful as a recognition diagnostic, not a finished earnings forecast. For group revenue, the simple 2×H1 baseline has mean APE **{_pct(group_bt['h1_annualized_ape_pct'].mean())}** across {len(group_bt)} valid holdouts; the prior-three-year median H1-share baseline is **{_pct(group_bt['prior_share_ape_pct'].mean())}**. The difference is not stable enough to justify a complex model yet.

## Key findings: recognition seasonality is the main H1 risk

    The H1-to-FY bridge shows that SHKP's group revenue H1 share ranged from roughly 39% to 76% in the available history. Hong Kong property-sales recognition is much more seasonal and lumpy: the corrected segment-table history ranges from roughly 12% to 89% across the available FY2017/18–FY2024/25 observations. A half-year run-rate should therefore be treated as a scenario, not a point forecast.

![SHKP H1 consolidated actuals](charts/shkp_h1_consolidated_actuals.png)

![SHKP H1 actual versus nowcast](charts/shkp_h1_actual_vs_nowcast.png)

## H1-to-FY recognition bridge

The following table is the arithmetic bridge for consolidated group revenue. H2 is calculated as FY actual minus H1 actual; it is not a separately filed observation.

| Fiscal year | H1 actual (HKD m) | H2 arithmetic (HKD m) | FY actual (HKD m) | H1 share | Annual source quality |
|---|---:|---:|---:|---:|---|
{bridge_rows}

![Recognition seasonality](charts/shkp_h1_recognition_share.png)

## H1 actual-vs-nowcast results

The backtest compares two pre-FY baselines: (1) annualise H1 by multiplying by two; and (2) divide H1 by the median H1/FY share from up to the prior three fiscal years. Training years are stored per row and are strictly earlier than the target year.

| Metric | Valid holdouts | Mean APE: 2× H1 | Mean APE: prior-share median |
|---|---:|---:|---:|
{chr(10).join(summary_rows)}

The HK property-sales result is deliberately shown separately from consolidated revenue: its recognition timing is project-handover driven, so its errors are expected to be much larger and it should not be used as a stable recurring-income proxy.

## Component H2 revenue bridge

The next model keeps the same FY group-revenue target but forecasts the remaining half-year by component:

```text
FY group revenue = H1 actual + H2 HK development + H2 HK rental + H2 hotel + H2 residual
```

Each H2 component uses the median H2/H1 ratio from strictly earlier fiscal years. The residual is explicit and absorbs Mainland, telecom/infrastructure, other businesses and JV/scope differences. It is a rough recognition bridge, not a project-level handover forecast.

| Model | Valid holdouts | Mean APE | Median APE | Mean signed error |
|---|---:|---:|---:|---:|
{component_summary}

| Fiscal year | FY actual | Component forecast | Error | APE | Training years |
|---|---:|---:|---:|---:|---|
{component_rows}

![Component H2 bridge](charts/shkp_h1_component_actual_vs_nowcast.png)

The component bridge is retained as a diagnostic even when it loses to 2×H1. A large miss means the H2/FY recognition ratios are not stationary enough; it is not a reason to tune the window after seeing the target year.

## Hong Kong commercial observations

The official H1 reports provide a useful commercial series, but the disclosure grain changes over time. Hong Kong rental revenue is available for most years from the financial-review narrative; explicit office/retail revenue is consistently available only in the recent three reports. This is enough to anchor the current commercial module, not enough to claim a long clean office/retail panel.

![Hong Kong commercial H1 indicators](charts/shkp_h1_hk_commercial.png)

## Scope, data and metric definitions

- **H1 period:** six months ended 31 December of each fiscal year. Values are HKD million unless labelled per share.
- **Availability/PIT:** `release_date` from the official interim report is used as `availability_date`; the H1 actual itself is not treated as available at 31 December.
- **Consolidated metrics:** taken from the report's financial-highlights table; rental metrics include joint ventures and associates where the report footnote says so.
- **Hong Kong commercial metrics:** taken from the financial-review narrative and retained only when an explicit HKD amount is printed beside the relevant Hong Kong/office/retail label.
- **Contracted sales:** preserved as contracted-sales flow or backlog and never renamed as revenue.
- **Annual actuals:** official curated annual summary/segment history is preferred. FY2017–FY2020 consolidated fallback values come from the sibling financial-data source and are explicitly labelled non-PIT because original announcement timestamps are not present.

## Method and validation

1. Fetch the official PDF URL in the report registry and save an immutable raw snapshot.
2. Extract PDF text with `pypdf`, apply narrow legacy text repairs, and parse only labelled current-period figures. Missing splits remain missing.
3. Build the recognition bridge by joining H1 to the aligned fiscal-year actual; compute H2 as an arithmetic residual.
4. For each target fiscal year, fit the prior-share baseline using only earlier complete bridge rows; store the training years and both model errors.

The current automated checks cover registry completeness, legacy footnote parsing, missing-split behavior, H2 arithmetic, and no-future-training-year leakage (`pytest -q tests/test_hk_real_estate_shkp_h1_backtest.py`).

## Limitations and uncertainty

- The FY2026 H1 row has no FY2026 actual yet, so it is a current H1 observation only and is excluded from holdout scoring.
- Consolidated FY2017–FY2020 annual fallback values are source-selected rather than strict announcement-vintage values. They are suitable for a rough recognition diagnostic, not a PIT earnings backtest claim.
- The H1 panel is issuer-reported and therefore includes accounting recognition timing, JV/associate scope and property handovers. It is not a direct proxy for project-level contract activity.
- Consensus/analyst estimates are not included here; this deliverable is an actuals and recognition-seasonality layer.

## Recommended next steps

- Pull official annual-report PDFs for FY2017–FY2020 and replace the consolidated fallback rows with primary annual-report facts and release dates.
- Extend the office/retail H1 split backwards only where the report prints a level; do not manufacture a split from a percentage change.
- Use the recognition-share distribution as a bounded H2 scenario input in the whole-company model, with a separate property-sales handover module.

## Further questions

- Can the annual-report segment notes provide a stable HK office/retail/residential-serviced-apartment split before FY2022/23?
- Which reported H1 commercial changes are explained by occupancy, rental reversion, new openings, or JV scope rather than market-rent indices?

Source registry and datasets:

- `data/normalized/hk_real_estate/shkp_h1_report_registry/`
- `data/normalized/hk_real_estate/shkp_h1_actual_panel/`
- `data/normalized/hk_real_estate/shkp_h1_to_fy_bridge/`
- `data/normalized/hk_real_estate/shkp_h1_actual_vs_nowcast/`
- `src/hk_real_estate/shkp_h1_backtest.py`
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    return REPORT_PATH


if __name__ == "__main__":
    print(build_report())
