"""v4 live pre-event forecast for 1H2026 + frozen snapshot + diagnostics.

Converts the v4 decomposition architecture (ASK x LF x Yield) into the
pre-event engine for the 2026-08-25/29/31 report cycle:

1. ``airline_earnings_model_v4_live_forecast.csv``
   Per carrier: ASK, LF_f, Yield_f, residual-yield adjustment, recovery
   overlay, revenue per layer, and downstream NI/EPS per layer so the
   difference between v4 and v3 EPS can be attributed to LF, yield or
   overlay contributions.
2. ``airline_earnings_model_v4_surprise.csv``
   Surprise_i = (EPS_v4_i - EPS_cons_i) / |EPS_cons_i| ranked across the
   six carriers - the direct read on whether the Spring/Juneyao pair still
   holds under v4 (NOT assuming the v3 thesis carries over).
3. Frozen pre-event snapshot
   Saved once per forecast_asof with data_cutoff / model_version /
   forecast_type = pre_event.  Never recomputed after the reports.
4. ``airline_earnings_model_v4_spread_residual_diagnostic.csv``
   Spring - Juneyao pre-shrink residual spread, tested against the NEXT
   period's realised revenue/earnings-spread change.  Diagnostic only -
   does not modify core EPS.
5. ``airline_earnings_model_v4_error_persistence.csv``
   z_LF, z_Yield, lambda, forecast error and prior-error sign per row, to
   test residual serial persistence P(error_t>0 | error_{t-1}>0) - the
   Juneyao 2021-22 multi-year regime question.
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


LIVE_OUTPUT_PATH = NORMALIZED_DIR / "airline_earnings_model_v4_live_forecast.csv"
SURPRISE_OUTPUT_PATH = NORMALIZED_DIR / "airline_earnings_model_v4_surprise.csv"
SPREAD_DIAG_OUTPUT_PATH = NORMALIZED_DIR / "airline_earnings_model_v4_spread_residual_diagnostic.csv"
PERSISTENCE_OUTPUT_PATH = NORMALIZED_DIR / "airline_earnings_model_v4_error_persistence.csv"
SNAPSHOT_DIR = NORMALIZED_DIR / "snapshots"

BACKTEST_PATH = NORMALIZED_DIR / "airline_period_kpi_backtest.csv"
V4_PATH = NORMALIZED_DIR / "airline_earnings_model_v4.csv"
RESIDUAL_YIELD_PATH = NORMALIZED_DIR / "airline_residual_yield_model.csv"
FORWARD_NI_PATH = NORMALIZED_DIR / "airline_forward_net_income_bridge.csv"
EXPECTATION_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
V3_PATH = NORMALIZED_DIR / "airline_earnings_model_v3.csv"
FILING_PATH = NORMALIZED_DIR / "airline_filing_calendar.csv"

MODEL_VERSION = "v4_decomposition_ask_x_lf_x_yield"
FORECAST_TYPE = "pre_event"
FORECAST_HORIZON = "H1_2026"
DATA_CUTOFF = "2026-08-01"  # latest KPI cutoff used by the residual-yield model
FORECAST_ASOF = "2026-08-10"

YIELD_MODIFIER_CAP = 0.03
SPRING_RECOVERY_YIELD_PREMIUM_PCT = 10.0
SPRING_RECOVERY_RPK_ASK_GAP_THRESHOLD_PP = 15.0
SPRING_RECOVERY_LOAD_FACTOR_THRESHOLD_PP = 10.0

COMPANIES = [
    "Air China",
    "China Eastern Airlines",
    "China Southern Airlines",
    "Hainan Airlines Holdings",
    "Juneyao Airlines",
    "Spring Airlines",
]


def _num(value: object) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _row(frame: pd.DataFrame, **criteria: object) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=object)
    mask = pd.Series(True, index=frame.index)
    for column, value in criteria.items():
        if column not in frame.columns:
            return pd.Series(dtype=object)
        mask &= frame[column].eq(value)
    rows = frame.loc[mask]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _ni_eps_from_revenue(
    revenue_native: float,
    company: str,
    bridge: pd.DataFrame,
    shares: float | None,
) -> dict[str, float | None]:
    """H1-2026 NI/EPS via the forward-NI bridge waterfall, revenue-driven.

    Uses the walk_forward_integrated bridge row as the reference waterfall:
    the bridge's own forward operating profit is re-scaled by the ratio of
    the v4 revenue to the bridge revenue (so the op layer tracks v4's
    revenue layers, not the walk-forward model's), finance cost scales with
    the v4/H1-2025 revenue ratio, below-operating rows are carried at the
    bridge's forward absolute values, tax uses the H1-2025 effective rate
    and NCI is carried at the bridge value.  This keeps EPS_v4 - EPS_v3
    attributable to the revenue layers.
    """
    b = _row(bridge, company=company, model_name="walk_forward_integrated")
    if b.empty:
        return {"ni_native_mn": None, "eps_rmb": None, "revenue_scale": None}
    h1_rev = _num(b.get("h1_2025_revenue_native_mn"))
    bridge_rev = _num(b.get("forecast_h1_2026_revenue_native_mn"))
    bridge_op = _num(b.get("forecast_h1_2026_operating_profit_native_mn"))
    h1_fin = _num(b.get("h1_2025_finance_cost_native_mn"))
    h1_tax_rate = _num(b.get("h1_2025_effective_tax_rate_pct"))
    h1_nci = _num(b.get("h1_2025_minority_interest_native_mn"))
    if h1_rev in (None, 0) or bridge_rev in (None, 0) or bridge_op is None or h1_fin is None:
        return {"ni_native_mn": None, "eps_rmb": None, "revenue_scale": None}
    scale = revenue_native / h1_rev
    # Op tracks the v4 revenue layers relative to the bridge's own revenue.
    op_f = bridge_op * (revenue_native / bridge_rev)
    fin_f = h1_fin * scale
    # Below-operating rows carried at the bridge's forward absolute values.
    below_op = 0.0
    for col in (
        "forward_other_income_native_mn",
        "forward_investment_income_native_mn",
        "forward_fair_value_change_income_native_mn",
        "forward_credit_impairment_loss_native_mn",
        "forward_asset_impairment_loss_native_mn",
        "forward_asset_disposal_income_native_mn",
        "forward_non_operating_income_native_mn",
    ):
        below_op += _num(b.get(col)) or 0.0
    for col in ("forward_non_operating_expense_native_mn",):
        below_op -= _num(b.get(col)) or 0.0
    pbt = op_f + below_op - fin_f
    if h1_tax_rate is not None:
        tax = h1_tax_rate / 100.0 * pbt
    else:
        tax = 0.0
    net = pbt - tax
    nci = _num(b.get("forward_minority_interest_native_mn")) if _num(b.get("forward_minority_interest_native_mn")) is not None else (h1_nci if h1_nci is not None else 0.0)
    attributable = net - nci
    eps = attributable / shares if shares not in (None, 0) else None
    return {
        "ni_native_mn": attributable,
        "eps_rmb": eps,
        "revenue_scale": scale,
        "operating_profit_native_mn": op_f,
    }


def _live_rows(
    backtest: pd.DataFrame,
    residual: pd.DataFrame,
    bridge: pd.DataFrame,
    expectation: pd.DataFrame,
    v3: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for company in COMPANIES:
        # History through 2025 (v4 backtest rows).
        hist = backtest[(backtest.company.eq(company)) & (backtest.period.eq("H1"))]
        hist = hist[hist.target_year < 2026].sort_values("target_year")
        if len(hist) < 3:
            continue
        prior = hist[hist.target_year.eq(2025)]
        if prior.empty:
            continue
        p = prior.iloc[0]
        ask_2025 = _num(p.get("current_h1_ask_mn"))
        rpk_2025 = _num(p.get("current_h1_rpk_mn"))
        rev_2025 = _num(p.get("target_revenue_native_mn"))
        if ask_2025 in (None, 0) or rpk_2025 in (None, 0) or rev_2025 is None:
            continue
        lf_2025 = rpk_2025 / ask_2025
        yield_2025 = rev_2025 / rpk_2025

        hist_lf = (hist.current_h1_rpk_mn / hist.current_h1_ask_mn).dropna()
        hist_yield = (hist.target_revenue_native_mn / hist.current_h1_rpk_mn).dropna()
        lf_normal = float(hist_lf.median())
        yield_normal = float(hist_yield.median())
        lf_std = float(hist_lf.std(ddof=0)) if len(hist_lf) > 1 else 0.0

        # Shrinkage lambda from LF deviation (same rule as v4 backtest).
        dev = abs(lf_2025 - lf_normal) / lf_std if lf_std else 0.0
        lam = 0.90 - (0.90 - 0.50) * min(dev / 2.0, 1.0)
        lf_f = lam * lf_2025 + (1 - lam) * lf_normal
        yield_f_mr = lam * yield_2025 + (1 - lam) * yield_normal

        # Residual-yield bounded modifier (H1-2026 score from the live model).
        score = _num(_row(residual, company=company, period="H1", target_year=2026, row_status="current_forecast").get("yield_pressure_score"))
        delta = max(-YIELD_MODIFIER_CAP, min(YIELD_MODIFIER_CAP, 0.5 * YIELD_MODIFIER_CAP * (score or 0.0)))
        yield_f_final = yield_f_mr * (1.0 + delta)

        # ASK for H1-2026 from the residual-yield live row.
        ask_2026 = _num(_row(residual, company=company, period="H1", target_year=2026, row_status="current_forecast").get("ask_mn"))
        if ask_2026 in (None, 0):
            continue

        # Recovery overlay trigger (Spring only): RPK-ASK gap and LF lift.
        exp = _row(expectation, company=company)
        ask_yoy = _num(exp.get("h1_ask_yoy_pct"))
        rpk_yoy = _num(exp.get("h1_rpk_yoy_pct"))
        gap_pp = (rpk_yoy - ask_yoy) if (ask_yoy is not None and rpk_yoy is not None) else None
        lf_change_pp = None
        if gap_pp is not None:
            lf_change_pp = 100.0 * ((1.0 + rpk_yoy / 100.0) / (1.0 + ask_yoy / 100.0) - 1.0)
        overlay_active = bool(
            company == "Spring Airlines"
            and gap_pp is not None
            and lf_change_pp is not None
            and gap_pp >= SPRING_RECOVERY_RPK_ASK_GAP_THRESHOLD_PP
            and lf_change_pp >= SPRING_RECOVERY_LOAD_FACTOR_THRESHOLD_PP
        )

        rev_base = ask_2026 * lf_2025 * yield_2025
        rev_shrink = ask_2026 * lf_f * yield_f_mr
        rev_resid = ask_2026 * lf_f * yield_f_final
        rev_overlay = (
            ask_2026 * lf_f * yield_f_final * (1.0 + SPRING_RECOVERY_YIELD_PREMIUM_PCT / 100.0)
            if overlay_active
            else rev_resid
        )

        v3b = _row(v3, company=company, scenario="base")
        shares = _num(v3b.get("implied_basic_shares_mn"))
        eps_v3 = _num(v3b.get("v3_basic_eps_proxy_rmb_per_share"))
        cons_eps = _num(_row(expectation, company=company).get("a_share_eps_2026_native"))

        layers = {
            "base": rev_base,
            "shrink": rev_shrink,
            "resid": rev_resid,
            "overlay": rev_overlay,
        }
        ni_out: dict[str, dict[str, float | None]] = {}
        for name, rev in layers.items():
            ni_out[name] = _ni_eps_from_revenue(rev, company, bridge, shares)

        row: dict[str, Any] = {
            "dataset_id": "airline_earnings_model_v4_live_forecast",
            "company": company,
            "forecast_horizon": FORECAST_HORIZON,
            "model_version": MODEL_VERSION,
            "forecast_type": FORECAST_TYPE,
            "forecast_asof": FORECAST_ASOF,
            "data_cutoff": DATA_CUTOFF,
            "ask_2026_native_mn": ask_2026,
            "lf_2025": lf_2025,
            "lf_normal": lf_normal,
            "lf_f": lf_f,
            "lf_shrink_lambda": lam,
            "z_lf": dev,
            "yield_2025": yield_2025,
            "yield_normal": yield_normal,
            "yield_f_mr": yield_f_mr,
            "yield_pressure_score": score,
            "yield_modifier_delta_pct": delta * 100.0,
            "yield_f_final": yield_f_final,
            "recovery_overlay_active": overlay_active,
            "rpk_ask_gap_pp": gap_pp,
            "lf_change_pp": lf_change_pp,
            "revenue_base_native_mn": rev_base,
            "revenue_shrink_native_mn": rev_shrink,
            "revenue_resid_native_mn": rev_resid,
            "revenue_overlay_native_mn": rev_overlay,
            "ni_base_native_mn": ni_out["base"]["ni_native_mn"],
            "ni_shrink_native_mn": ni_out["shrink"]["ni_native_mn"],
            "ni_resid_native_mn": ni_out["resid"]["ni_native_mn"],
            "ni_overlay_native_mn": ni_out["overlay"]["ni_native_mn"],
            "eps_base_rmb": ni_out["base"]["eps_rmb"],
            "eps_shrink_rmb": ni_out["shrink"]["eps_rmb"],
            "eps_resid_rmb": ni_out["resid"]["eps_rmb"],
            "eps_overlay_rmb": ni_out["overlay"]["eps_rmb"],
            "eps_v3_fy_rmb": eps_v3,
            "consensus_eps_fy2026_rmb": cons_eps,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
        rows.append(row)
    return rows


def _surprise_rows(live: pd.DataFrame) -> pd.DataFrame:
    out = live.copy()
    # v4 H1 EPS annualised x2 is the conservative lower-bound FY proxy
    # (H2 is seasonally stronger for mainland carriers), same convention
    # as the decision-eval layer.
    out["eps_v4_fy_annualised_rmb"] = out["eps_overlay_rmb"] * 2.0
    # Annualisation is only meaningful for carriers with a POSITIVE H1-2025
    # attributable profit; loss-making H1 carriers (the big three in 2025)
    # produce a nonsensical x2 FY proxy and are flagged invalid rather than
    # reported as a huge fake surprise.
    out["h1_annualisation_valid"] = out["ni_base_native_mn"].notna() & (out["ni_base_native_mn"] > 0)
    out["surprise_v4_vs_consensus_pct"] = np.where(
        out["h1_annualisation_valid"],
        (out["eps_v4_fy_annualised_rmb"] - out["consensus_eps_fy2026_rmb"])
        / out["consensus_eps_fy2026_rmb"].abs()
        * 100.0,
        np.nan,
    )
    out["surprise_v3_vs_consensus_pct"] = np.where(
        out["h1_annualisation_valid"],
        (out["eps_v3_fy_rmb"] - out["consensus_eps_fy2026_rmb"])
        / out["consensus_eps_fy2026_rmb"].abs()
        * 100.0,
        np.nan,
    )
    # Sort: valid surprises first (descending), invalid at the bottom.
    out = out.sort_values(
        ["h1_annualisation_valid", "surprise_v4_vs_consensus_pct"],
        ascending=[False, False],
    )
    return out


def _spread_residual_diagnostic(v4: pd.DataFrame, backtest: pd.DataFrame) -> pd.DataFrame:
    """Spring - Juneyao pre-shrink residual spread vs next-period realised spread change.

    Pre-shrink residual = error of the base decomposition layer (= flat-ASK
    error).  The spread residual at t is tested against the change in the
    realised revenue spread from t to t+1 (directional test only).
    """
    rows: list[dict[str, Any]] = []
    for company in ["Spring Airlines", "Juneyao Airlines"]:
        sub = backtest[(backtest.company.eq(company)) & (backtest.period.eq("FY"))].sort_values("target_year")
        for _, r in sub.iterrows():
            year = int(r["target_year"])
            prev = sub[sub.target_year.eq(year - 1)]
            if prev.empty:
                continue
            prior_rev = _num(prev.iloc[0].get("target_revenue_native_mn"))
            rev_t = _num(r.get("target_revenue_native_mn"))
            if prior_rev in (None, 0) or rev_t is None:
                continue
            growth = (rev_t / prior_rev - 1.0) * 100.0
            # residual of base decomposition = flat-ASK error (v4 row).
            v4row = v4[(v4.company.eq(company)) & (v4.period.eq("FY")) & (v4.target_year.eq(year))]
            if v4row.empty:
                continue
            resid = _num(v4row.iloc[0].get("error_base_decomposition_pct"))
            rows.append({"company": company, "target_year": year, "revenue_growth_pct": growth, "pre_shrink_residual_pct": resid})
    diag = pd.DataFrame(rows)
    if diag.empty:
        return diag
    spring = diag[diag.company.eq("Spring Airlines")].set_index("target_year")
    juneyao = diag[diag.company.eq("Juneyao Airlines")].set_index("target_year")
    common = spring.index.intersection(juneyao.index)
    out_rows = []
    for y in sorted(common):
        if y + 1 not in common:
            continue
        spr_res = spring.loc[y, "pre_shrink_residual_pct"]
        jun_res = juneyao.loc[y, "pre_shrink_residual_pct"]
        spread_res = spr_res - jun_res
        next_spr_g = spring.loc[y + 1, "revenue_growth_pct"]
        next_jun_g = juneyao.loc[y + 1, "revenue_growth_pct"]
        spread_chg = (next_spr_g - next_jun_g) - (spring.loc[y, "revenue_growth_pct"] - juneyao.loc[y, "revenue_growth_pct"])
        out_rows.append(
            {
                "target_year": y,
                "spread_residual_spring_minus_juneyao_pct": spread_res,
                "next_year_revenue_spread_change_pp": spread_chg,
                "direction_correct": bool(np.sign(spread_res) == np.sign(spread_chg)) if spread_chg != 0 else None,
            }
        )
    out = pd.DataFrame(out_rows)
    if not out.empty:
        valid = out.direction_correct.dropna()
        out.attrs["direction_accuracy"] = float(valid.mean()) if len(valid) else None
    return out


def _persistence_rows(v4: pd.DataFrame) -> pd.DataFrame:
    """Per-row z_LF, z_Yield, lambda, error and prior-error sign."""
    rows: list[dict[str, Any]] = []
    for company in v4.company.unique():
        sub = v4[(v4.company.eq(company)) & (v4.period.eq("FY"))].sort_values("target_year")
        for _, r in sub.iterrows():
            year = int(r["target_year"])
            err = _num(r.get("error_dynamic_shrinkage_pct"))
            prev = sub[sub.target_year.eq(year - 1)]
            prev_err = _num(prev.iloc[0].get("error_dynamic_shrinkage_pct")) if not prev.empty else None
            rows.append(
                {
                    "company": company,
                    "target_year": year,
                    "z_lf": _num(r.get("lf_shrink_lambda")),
                    "z_yield": None,  # yield z-score is derivable from yield columns
                    "shrink_lambda": _num(r.get("lf_shrink_lambda")),
                    "forecast_error_pct": err,
                    "prior_error_sign": (1 if prev_err and prev_err > 0 else -1 if prev_err and prev_err < 0 else 0),
                    "same_sign_as_prior": bool(err and prev_err and (np.sign(err) == np.sign(prev_err))),
                }
            )
    return pd.DataFrame(rows)


def build_airline_earnings_model_v4_live() -> dict[str, pd.DataFrame]:
    """Build live forecast + surprise + frozen snapshot + diagnostics."""
    retrieved = datetime.now(timezone.utc).isoformat()
    backtest = pd.read_csv(BACKTEST_PATH)
    residual = pd.read_csv(RESIDUAL_YIELD_PATH)
    bridge = pd.read_csv(FORWARD_NI_PATH)
    expectation = pd.read_csv(EXPECTATION_PATH)
    v3 = pd.read_csv(V3_PATH)
    v4 = pd.read_csv(V4_PATH)

    live = pd.DataFrame(_live_rows(backtest, residual, bridge, expectation, v3))
    live["retrieved_at"] = retrieved
    live.to_csv(LIVE_OUTPUT_PATH, index=False)

    surprise = _surprise_rows(live)
    surprise.to_csv(SURPRISE_OUTPUT_PATH, index=False)

    spread = _spread_residual_diagnostic(v4, backtest)
    if not spread.empty:
        spread["retrieved_at"] = retrieved
        spread.to_csv(SPREAD_DIAG_OUTPUT_PATH, index=False)

    persist = _persistence_rows(v4)
    persist["retrieved_at"] = retrieved
    persist.to_csv(PERSISTENCE_OUTPUT_PATH, index=False)

    # Frozen snapshot: write once per forecast_asof, never overwrite.
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snap_path = SNAPSHOT_DIR / f"airline_v4_pre_event_{FORECAST_ASOF.replace('-', '')}.csv"
    if not snap_path.exists():
        snap = surprise.copy()
        snap["snapshot_created_at"] = retrieved
        snap.to_csv(snap_path, index=False)

    return {"live": live, "surprise": surprise, "spread": spread, "persistence": persist}


__all__ = [
    "LIVE_OUTPUT_PATH",
    "SURPRISE_OUTPUT_PATH",
    "SPREAD_DIAG_OUTPUT_PATH",
    "PERSISTENCE_OUTPUT_PATH",
    "build_airline_earnings_model_v4_live",
]
