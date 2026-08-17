"""Generate the SHKP skeleton backtest v2 report (charts + markdown).

Reads the persisted vintage-mode backtest and the margin decomposition,
renders charts into ``docs/asia-markets/charts/`` and writes a self-contained
markdown report with the full 9-year table and interpretation.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs" / "asia-markets"
CHARTS = DOCS / "charts"


def _latest(name: str) -> pd.DataFrame:
    files = glob.glob(str(REPO / "data" / "normalized" / "hk_real_estate" / name / "*" / "*.parquet"))
    if not files:
        return pd.DataFrame()

    def sort_key(path: str) -> tuple[str, float, str]:
        lineage_path = Path(path).with_name("lineage.json")
        created_at = ""
        try:
            payload = json.loads(lineage_path.read_text(encoding="utf-8"))
            created_at = str(payload.get("created_at") or "")
        except (OSError, json.JSONDecodeError, TypeError):
            pass
        return (created_at, Path(path).stat().st_mtime, path)

    return pd.read_parquet(max(files, key=sort_key))


def main() -> None:
    CHARTS.mkdir(exist_ok=True)
    bt = _latest("shkp_skeleton_historical_backtest")
    decomp = _latest("shkp_skeleton_margin_decomposition")
    mh = _latest("shkp_hk_development_margin_history")
    assert not bt.empty and not decomp.empty, "backtest / decomposition data missing; run the CLI commands first"

    # Chart 1: actual vs model underlying profit (retrospective replay)
    fig, ax = plt.subplots(figsize=(10, 5))
    labels = bt["fiscal_label"]
    x = range(len(bt))
    ax.bar([i - 0.2 for i in x], bt["actual_underlying_profit_hkd_m"], width=0.4, label="Actual", color="#8a8a8a")
    ax.bar([i + 0.2 for i in x], bt["model_underlying_profit_hkd_m"], width=0.4, label="Model (vintage calibration)", color="#2b7bb9")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45)
    ax.set_ylabel("Underlying profit (HK$m)")
    ax.set_title("SHKP underlying profit: actual vs retrospective vintage replay")
    ax.legend()
    fig.tight_layout()
    fig.savefig(CHARTS / "shkp_backtest_v2_actual_vs_model.png", dpi=150)
    plt.close(fig)

    # Chart 2: error % by margin mode
    fig, ax = plt.subplots(figsize=(10, 5))
    for mode in ["bucket", "vintage", "rolling_actual", "actual"]:
        sub = decomp[decomp["margin_mode"] == mode].set_index("fiscal_label")["underlying_error_pct"]
        ax.plot(sub.index, sub.values, marker="o", label=mode)
    ax.axhline(0, color="grey", lw=0.8)
    ax.set_ylabel("Underlying error (%)")
    ax.set_title("Retrospective replay error by margin treatment")
    ax.legend()
    for lbl in ax.get_xticklabels():
        lbl.set_rotation(45)
    fig.tight_layout()
    fig.savefig(CHARTS / "shkp_backtest_v2_margin_modes.png", dpi=150)
    plt.close(fig)

    # Chart 3: actual HK development margin time series
    fig, ax = plt.subplots(figsize=(10, 4.5))
    mh_s = mh.set_index("fiscal_year_end")
    ax.plot(mh_s.index, mh_s["development_margin_pct"], marker="o", color="#c0504d")
    ax.axhline(29.5, color="#2b7bb9", ls="--", lw=1, label="frozen bucket mid")
    ax.axhline(42.0, color="#4a8347", ls="--", lw=1, label="vintage 2014-19 cohort")
    ax.set_ylabel("HK development margin (%)")
    ax.set_title("Actual HK development margin (used for retrospective calibration)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(CHARTS / "shkp_backtest_v2_margin_history.png", dpi=150)
    plt.close(fig)

    mae_modes = decomp.groupby("margin_mode")["underlying_error_pct"].apply(lambda s: s.abs().mean()).round(2)
    mae_vintage = bt["underlying_error_pct"].abs().mean()

    rows = []
    for _, r in bt.iterrows():
        rows.append(
            f"| {r['fiscal_label']} | {r['actual_underlying_profit_hkd_m']:,.0f} | "
            f"{r['model_underlying_profit_hkd_m']:,.0f} | {r['underlying_error_pct']:+.2f}% | "
            f"{r['eps_actual']:.2f} | {r['eps_model']:.2f} | {r['eps_error']:+.2f} |"
        )
    table = "\n".join(rows)

    doc = f"""# SHKP Skeleton Historical Backtest v2 — vintage margin replay

## TL;DR

The historical replay (FY2017-FY2025, whole-company underlying profit) uses the
**launch-cohort ("vintage") margin calibration** as its default. Overall MAE
improves from **12.4% -> {mae_vintage:.1f}%** with no change to the frozen v1.0
forward engine — only the margin assumption used to replay history changes.
The legacy static bucket remains available as `margin_mode="bucket"`.

**Important scope:** this is a retrospective calibration/replay, not a strict
point-in-time (PIT) or out-of-sample (OOS) backtest. The vintage bands were
calibrated using the realised development-margin history, and the current
ownership snapshot is not reconstructed for every historical date. Treat the
MAE as a research diagnostic, not as a deployable historical forecast score.

## Why the old backtest under-estimated 2017-2022

The frozen margin bucket (22.5/29.5/37.5% by ASP) was calibrated to the
FY26/27 **low-margin** delivery mix, but actual HK development margins in
2017-2022 ran **32.8-45.1%**.  Overlaid on ~33-37bn of recognised revenue that
is a 10-15pp understatement per year - which is exactly the old -15% to -31%
backtest error.  It is **not** the mainland boom: mainland development profit
only spiked in FY2021 (6.4bn) and FY2025 (5.1bn), and in both years the
non-residential run-rate either captured it (FY2021: -135m error) or was
offset by residential (FY2025).

The replay assigns each phase a margin from its **`coverage_start` year** as a
land-cost-vintage proxy: low-land-cost 2014-2019 launches get ~42%, while
post-2021 high-cost cohorts get ~24%. This is useful for scenario analysis, but
it should not be described as PIT until ownership evidence, information dates,
and the calibration sample are rebuilt vintage by vintage.

## Full backtest table (vintage default)

| FY | Actual (m) | Model (m) | Error | EPS act | EPS model | EPS err |
|---|---:|---:|---:|---:|---:|---:|
{table}

MAE underlying = **{mae_vintage:.2f}%**.

## Error attribution by margin treatment

| margin mode | MAE |
|---|---:|
"""
    for k, v in mae_modes.items():
        doc += f"| {k} | {v}% |\n"
    doc += """
## Residual error after the margin fix

* **FY2021/22 (-16.1%) and FY2019/20 (+12.9%)** - non-residential run-rate
  swings around the Mainland/rental cycle, not a margin or coverage issue.
* **FY2016/17 (-7.6%)** - SRPE went live in 2013, so pre-2013 launches have no
  first-hand registers on the platform (documented data floor, kernel 0.36).
* **FY2024/25 (+0.05%)** - converged. The next forward estimate should be
  treated as a scenario output until the coverage and information-date gates
  are complete.

## Charts

![actual vs model](charts/shkp_backtest_v2_actual_vs_model.png)

![margin modes](charts/shkp_backtest_v2_margin_modes.png)

![margin history](charts/shkp_backtest_v2_margin_history.png)

## Engineering gate

* `build_shkp_skeleton_backtest(..., margin_mode="vintage")` is the default
  research replay; `margin_mode="bucket"` reproduces the legacy behaviour.
* Shared phase-prep / vintage helpers extracted so the decomposition and the
  backtest cannot drift apart.
* The report should be regenerated after any historical transaction or
  ownership rebuild; the resulting score remains retrospective until a strict
  PIT/OOS data contract is implemented.
"""
    out = DOCS / "SHKP_SKELETON_BACKTEST_V2_REPORT.md"
    out.write_text(doc, encoding="utf-8")
    print(f"report -> {out}")
    print("charts:")
    for p in sorted(CHARTS.glob("shkp_backtest_v2_*.png")):
        print("  ", p)


if __name__ == "__main__":
    main()
