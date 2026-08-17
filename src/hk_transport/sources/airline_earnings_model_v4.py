"""v4 decomposition revenue model (ASK x LF x Yield) with regime-aware shrinkage.

Motivation (2023-error autopsy): the flat-ASK / flat-RPK family assumes
yield is unchanged from the prior year.  In regime years (2020 COVID,
2022 lockdowns, 2023 reopening) the prior-year yield is distorted - in
OPPOSITE directions for LCCs vs the big three - so a single flat-yield
anchor fails.  Joint ASK+RPK regression is structurally impossible:
ASK and RPK growth correlate ~1.00 (load factor moves little), so the
coefficients are unidentified (66% of walk-forward fits had a negative
coefficient).

v4 architecture:

    Revenue_t = ASK_t x LF_f x Yield_f

where LF and yield-per-RPK each mean-revert to their company normal level
with an anomaly-dependent shrinkage lambda.  The lambda is an explicit
function of how far the prior-year load factor sits from the company's own
historical normal (LF is the cause; yield is the result - regime detection
uses LF, never yield).

Four stacked ablations (every stage adds exactly one component):

    1. base_decomposition  : Revenue = ASK x LF_{t-1} x Yield_{t-1}
                             (algebraically identical to flat-ASK; the
                             decomposition baseline)
    2. dynamic_shrinkage   : LF and Yield mean-revert to company normal
                             levels, lambda = f(|LF deviation|)
    3. residual_yield      : bounded multiplicative modifier from the
                             residual-yield pressure signal, |delta| <= cap
    4. recovery_overlay    : Spring-only pre-declared +10% yield premium
                             when RPK-ASK gap and LF lift clear thresholds
                             (explicitly labelled regime overlay, never
                             silently mixed into the generic model)

Every normal level is computed walk-forward: only rows with
target_year < t are visible, so there is no look-ahead.

Evaluation (per stage): FY/H1/H2 revenue MAE, acceleration-direction accuracy
(the sign of predicted versus actual growth acceleration), cross-sectional rank IC
(Spearman across carriers per period-year), and regime split
(2020-2023 vs normal years).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..config import NORMALIZED_DIR

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_earnings_model_v4.csv"
ABLATION_OUTPUT_PATH = NORMALIZED_DIR / "airline_earnings_model_v4_ablation.csv"
RANK_IC_OUTPUT_PATH = NORMALIZED_DIR / "airline_earnings_model_v4_rank_ic.csv"
DATASET_ID = "airline_earnings_model_v4"

BACKTEST_PATH = NORMALIZED_DIR / "airline_period_kpi_backtest.csv"
RESIDUAL_YIELD_PATH = NORMALIZED_DIR / "airline_residual_yield_model.csv"

COMPANIES = [
    "Air China",
    "China Eastern Airlines",
    "China Southern Airlines",
    "Hainan Airlines Holdings",
    "Juneyao Airlines",
    "Spring Airlines",
]
PERIODS = ["FY", "H1", "H2"]

# Dynamic shrinkage: lambda ramps from LAMBDA_MAX (trust prior year) to
# LAMBDA_MIN (trust normal level) as the prior-year LF deviation reaches
# KAPPA_SIGMA standard deviations of the company's own history.
# LAMBDA_MIN is fixed at 0.50 from an earlier exploratory sweep.  The sweep
# artifact is not persisted in this repository, so this is a design parameter
# rather than independent OOS evidence.  Keep the claim auditable by reporting
# the ablation result below, not by implying a reproducible tuning file exists.
LAMBDA_MAX = 0.90
LAMBDA_MIN = 0.50
KAPPA_SIGMA = 2.0

# Residual-yield modifier cap (bounded; a weak signal must not re-dominate
# the yield level).
YIELD_MODIFIER_CAP = 0.03

# Spring recovery overlay (pre-declared scenario rule, unchanged from v2).
SPRING_RECOVERY_YIELD_PREMIUM_PCT = 10.0
SPRING_RECOVERY_RPK_ASK_GAP_THRESHOLD_PP = 15.0
SPRING_RECOVERY_LOAD_FACTOR_THRESHOLD_PP = 10.0

# Regime split for honest reporting.
REGIME_YEARS = {2020, 2021, 2022, 2023}


def _num(value: object) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _ask_col(period: str) -> str:
    return {"FY": "current_fy_ask_mn", "H1": "current_h1_ask_mn", "H2": "current_h2_ask_mn"}[period]


def _rpk_col(period: str) -> str:
    return {"FY": "current_fy_rpk_mn", "H1": "current_h1_rpk_mn", "H2": "current_h2_rpk_mn"}[period]


def _ask_col_prior(period: str) -> str:
    return {"FY": "prior_fy_ask_mn", "H1": "prior_h1_ask_mn", "H2": "prior_h2_ask_mn"}[period]


def _rpk_col_prior(period: str) -> str:
    return {"FY": "prior_fy_rpk_mn", "H1": "prior_h1_rpk_mn", "H2": "prior_h2_rpk_mn"}[period]


def _lf(ask: float | None, rpk: float | None) -> float | None:
    if ask in (None, 0) or rpk is None:
        return None
    return rpk / ask


def _yield_per_rpk(revenue: float | None, rpk: float | None) -> float | None:
    if rpk in (None, 0) or revenue is None:
        return None
    return revenue / rpk


def _lambda_from_lf_deviation(lf_prior: float, lf_normal: float, lf_std: float) -> float:
    """Anomaly-dependent shrinkage: lambda = f(|LF deviation|)."""
    if lf_normal in (None, 0) or lf_prior is None:
        return LAMBDA_MAX
    if lf_std in (None, 0):
        return LAMBDA_MAX
    dev = abs(lf_prior - lf_normal) / lf_std
    lam = LAMBDA_MAX - (LAMBDA_MAX - LAMBDA_MIN) * min(dev / KAPPA_SIGMA, 1.0)
    return float(lam)


def _residual_yield_score(company: str, period: str, year: int, residual: pd.DataFrame) -> float | None:
    """Point-in-time yield-pressure score from the residual-yield model."""
    row = residual[
        residual.company.eq(company)
        & residual.period.eq(period)
        & residual.target_year.eq(year)
    ]
    if row.empty:
        return None
    return _num(row.iloc[0].get("yield_pressure_score"))


def _spring_recovery_signal(row: pd.Series) -> bool:
    gap = _num(row.get("rpk_minus_ask_growth_gap_pp"))
    lf_change = _num(row.get("load_factor_change_pp"))
    if gap is None or lf_change is None:
        return False
    return (
        gap >= SPRING_RECOVERY_RPK_ASK_GAP_THRESHOLD_PP
        and lf_change >= SPRING_RECOVERY_LOAD_FACTOR_THRESHOLD_PP
    )


def _build_series(
    panel: pd.DataFrame,
    company: str,
    period: str,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Walk-forward per-company/period rows with all four stacked stages."""
    sub = panel[
        (panel.company.eq(company))
        & (panel.period.eq(period))
    ].sort_values("target_year")
    ask_c, rpk_c = _ask_col(period), _rpk_col(period)

    rows: list[dict[str, Any]] = []
    for _, r in sub.iterrows():
        year = int(r["target_year"])
        prior_year = year - 1
        prior_row = sub[sub.target_year.eq(prior_year)]
        if prior_row.empty:
            continue
        p = prior_row.iloc[0]

        ask_t = _num(r.get(ask_c))
        target = _num(r.get("target_revenue_native_mn"))
        prior_rev = _num(p.get("target_revenue_native_mn"))
        prior_ask = _num(p.get(ask_c))
        prior_rpk = _num(p.get(rpk_c))
        if ask_t in (None, 0) or target is None or prior_rev is None or prior_ask in (None, 0):
            continue

        # ---- history visible at forecast time (walk-forward, no look-ahead) ----
        hist = sub[sub.target_year < year].copy()
        if len(hist) < 3:
            continue
        hist_ask = pd.to_numeric(hist[ask_c], errors="coerce")
        hist_rpk = pd.to_numeric(hist[rpk_c], errors="coerce")
        hist_rev = pd.to_numeric(hist["target_revenue_native_mn"], errors="coerce")
        # Load factor = RPK / ASK (NOT revenue/ASK - that is RASK).
        hist_lf = hist_rpk / hist_ask.replace(0, np.nan)
        hist_yield = hist_rev / hist_rpk.replace(0, np.nan)
        hist_lf = hist_lf.dropna()
        hist_yield = hist_yield.dropna()
        if len(hist_lf) < 2 or len(hist_yield) < 2:
            continue
        lf_normal = float(hist_lf.median())
        yield_normal = float(hist_yield.median())
        lf_std = float(hist_lf.std(ddof=0)) if len(hist_lf) > 1 else 0.0

        # ---- stage 1: base decomposition (identical to flat-ASK) ----
        lf_prior = _lf(prior_ask, prior_rpk)
        yield_prior = _yield_per_rpk(prior_rev, prior_rpk)
        if lf_prior is None or yield_prior is None:
            continue
        rev_base = ask_t * lf_prior * yield_prior

        # ---- stage 2: dynamic shrinkage ----
        lam = _lambda_from_lf_deviation(lf_prior, lf_normal, lf_std)
        lf_f = lam * lf_prior + (1.0 - lam) * lf_normal
        # Yield shrinks with the same anomaly lambda (LF-driven regime
        # detection; yield follows).
        yield_f = lam * yield_prior + (1.0 - lam) * yield_normal
        rev_shrink = ask_t * lf_f * yield_f

        # ---- stage 3: bounded residual-yield modifier ----
        score = _residual_yield_score(company, period, year, RESIDUAL_YIELD_CACHE)
        delta = max(-YIELD_MODIFIER_CAP, min(YIELD_MODIFIER_CAP, 0.5 * YIELD_MODIFIER_CAP * (score or 0.0)))
        yield_final = yield_f * (1.0 + delta)
        rev_resid = ask_t * lf_f * yield_final

        # ---- stage 4: Spring recovery overlay (labelled regime overlay) ----
        recovery_active = (
            company == "Spring Airlines"
            and _spring_recovery_signal(r)
        )
        yield_overlay = yield_final * (
            1.0 + SPRING_RECOVERY_YIELD_PREMIUM_PCT / 100.0
        ) if recovery_active else yield_final
        rev_overlay = ask_t * lf_f * yield_overlay

        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "ticker": r.get("ticker"),
                "period": period,
                "target_year": year,
                "row_status": "historical_evaluated",
                "ask_native_mn": ask_t,
                "target_revenue_native_mn": target,
                "lf_prior": lf_prior,
                "lf_normal": lf_normal,
                "lf_shrink_lambda": lam,
                "yield_prior": yield_prior,
                "yield_normal": yield_normal,
                "yield_pressure_score": score,
                "yield_modifier_delta_pct": delta * 100.0,
                "recovery_overlay_active": bool(recovery_active),
                "revenue_base_decomposition_native_mn": rev_base,
                "revenue_dynamic_shrinkage_native_mn": rev_shrink,
                "revenue_residual_yield_native_mn": rev_resid,
                "revenue_recovery_overlay_native_mn": rev_overlay,
                "error_base_decomposition_pct": (rev_base / target - 1.0) * 100.0,
                "error_dynamic_shrinkage_pct": (rev_shrink / target - 1.0) * 100.0,
                "error_residual_yield_pct": (rev_resid / target - 1.0) * 100.0,
                "error_recovery_overlay_pct": (rev_overlay / target - 1.0) * 100.0,
                "retrieved_at": r.get("retrieved_at"),
            }
        )
    return rows, {"lf_normal": lf_normal, "yield_normal": yield_normal}


RESIDUAL_YIELD_CACHE: pd.DataFrame = pd.DataFrame()


def _ablation_metrics(df: pd.DataFrame, stage: str) -> dict[str, Any]:
    err_col = f"error_{stage}_pct"
    if df.empty or err_col not in df.columns:
        return {}
    err = df[err_col].dropna()
    if err.empty:
        return {}
    # Direction accuracy: does the model predict the sign of the ACCELERATION
    # (change in YoY growth rate)?  Simple sign-of-level-change is trivially
    # correct in a growing-revenue universe; the acceleration test has real
    # discrimination power (e.g. did the model predict 2023 would re-accelerate
    # vs 2022's collapse, or that 2024 would decelerate after the 2023 spike).
    dir_rows = df.dropna(subset=[err_col, "target_revenue_native_mn"])
    dir_correct = []
    for _, r in dir_rows.iterrows():
        prev = df[(df.company.eq(r["company"])) & (df.period.eq(r["period"])) & (df.target_year.eq(r["target_year"] - 1))]
        prev2 = df[(df.company.eq(r["company"])) & (df.period.eq(r["period"])) & (df.target_year.eq(r["target_year"] - 2))]
        if prev.empty or prev2.empty:
            continue
        prior_rev = prev.iloc[0]["target_revenue_native_mn"]
        prior_rev2 = prev2.iloc[0]["target_revenue_native_mn"]
        if prior_rev in (None, 0) or prior_rev2 in (None, 0):
            continue
        pred_level = r["target_revenue_native_mn"] * (1.0 + r[err_col] / 100.0)
        # Actual acceleration: (rev_t - rev_{t-1}) - (rev_{t-1} - rev_{t-2})
        actual_accel = (r["target_revenue_native_mn"] - prior_rev) - (prior_rev - prior_rev2)
        # Predicted acceleration: (pred_t - rev_{t-1}) - (rev_{t-1} - rev_{t-2})
        pred_accel = (pred_level - prior_rev) - (prior_rev - prior_rev2)
        if actual_accel != 0:
            dir_correct.append(int(np.sign(actual_accel) == np.sign(pred_accel)))
    direction_acc = float(np.mean(dir_correct)) if dir_correct else None

    return {
        "stage": stage,
        "n": int(len(err)),
        "mae_pct": float(err.abs().mean()),
        "bias_pct": float(err.mean()),
        "direction_accuracy": direction_acc,
        "n_direction": len(dir_correct),
        "mae_regime_years_pct": float(err[df.loc[err.index, "target_year"].isin(REGIME_YEARS)].abs().mean())
        if df.loc[err.index, "target_year"].isin(REGIME_YEARS).any()
        else None,
        "mae_normal_years_pct": float(err[~df.loc[err.index, "target_year"].isin(REGIME_YEARS)].abs().mean())
        if (~df.loc[err.index, "target_year"].isin(REGIME_YEARS)).any()
        else None,
    }


def _rank_ic(df: pd.DataFrame, stage: str) -> pd.DataFrame:
    err_col = f"error_{stage}_pct"
    ic_rows = []
    for (period, year), grp in df.dropna(subset=[err_col]).groupby(["period", "target_year"]):
        if len(grp) < 4:
            continue
        # Cross-sectional rank IC on GROWTH RATES: does the model rank
        # carriers' revenue growth correctly?  (Ranking levels is trivially
        # near-perfect because pred is a small perturbation of actual.)
        acc = []
        for _, r in grp.iterrows():
            prev = df[(df.company.eq(r["company"])) & (df.period.eq(r["period"])) & (df.target_year.eq(r["target_year"] - 1))]
            if prev.empty:
                continue
            prior_rev = prev.iloc[0]["target_revenue_native_mn"]
            if prior_rev in (None, 0):
                continue
            pred_level = r["target_revenue_native_mn"] * (1.0 + r[err_col] / 100.0)
            acc.append(
                {
                    "company": r["company"],
                    "actual_growth_pct": (r["target_revenue_native_mn"] / prior_rev - 1.0) * 100.0,
                    "pred_growth_pct": (pred_level / prior_rev - 1.0) * 100.0,
                }
            )
        if len(acc) < 4:
            continue
        acc_df = pd.DataFrame(acc)
        ic = acc_df["actual_growth_pct"].rank().corr(acc_df["pred_growth_pct"].rank(), method="spearman")
        ic_rows.append(
            {
                "period": period,
                "target_year": int(year),
                "n_carriers": len(acc),
                f"rank_ic_{stage}": ic,
            }
        )
    return pd.DataFrame(ic_rows)


def build_airline_earnings_model_v4() -> pd.DataFrame:
    """Build the v4 decomposition backtest with stacked ablations."""
    global RESIDUAL_YIELD_CACHE
    panel = pd.read_csv(BACKTEST_PATH)
    RESIDUAL_YIELD_CACHE = pd.read_csv(RESIDUAL_YIELD_PATH)
    retrieved = datetime.now(timezone.utc).isoformat()

    all_rows: list[dict[str, Any]] = []
    for company in COMPANIES:
        for period in PERIODS:
            rows, _ = _build_series(panel, company, period)
            all_rows.extend(rows)

    df = pd.DataFrame(all_rows)
    df["retrieved_at"] = retrieved
    df = df.sort_values(["company", "period", "target_year"]).reset_index(drop=True)
    df.to_csv(OUTPUT_PATH, index=False)

    # Ablation metrics (all stages, plus flat-ASK reference).
    stages = [
        "base_decomposition",
        "dynamic_shrinkage",
        "residual_yield",
        "recovery_overlay",
    ]
    metrics = []
    for stage in stages:
        m = _ablation_metrics(df, stage)
        if m:
            metrics.append(m)
    # FY/H1/H2 breakdown for the final stage.
    for period in PERIODS:
        p = df[df.period.eq(period)]
        m = _ablation_metrics(p, "recovery_overlay")
        if m:
            m = {"stage": f"recovery_overlay_{period}", **m}
            metrics.append(m)
    abl = pd.DataFrame(metrics)
    abl["retrieved_at"] = retrieved
    abl.to_csv(ABLATION_OUTPUT_PATH, index=False)

    # Rank IC per period-year for each stage.
    ic_frames = []
    for stage in stages:
        ic = _rank_ic(df, stage)
        if not ic.empty:
            ic_frames.append(ic)
    if ic_frames:
        ic_all = ic_frames[0]
        for ic in ic_frames[1:]:
            ic_all = ic_all.merge(
                ic.drop(columns=["n_carriers"]),
                on=["period", "target_year"],
                how="outer",
            )
        ic_all = ic_all.sort_values(["period", "target_year"]).reset_index(drop=True)
        ic_all["retrieved_at"] = retrieved
        ic_all.to_csv(RANK_IC_OUTPUT_PATH, index=False)

    return df


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "ABLATION_OUTPUT_PATH",
    "RANK_IC_OUTPUT_PATH",
    "build_airline_earnings_model_v4",
    "source_path",
]
