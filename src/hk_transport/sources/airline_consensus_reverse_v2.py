"""Consensus reverse engineering v2: sanity checks + implied RASK/CASK surface.

Purpose (roadmap item 2): the Spring +64.7% v4-vs-consensus surprise is
treated as a HYPOTHESIS to be aggressively audited, not a conclusion.
This module runs the four pre-agreed sanity checks and then reverses the
consensus EPS into an implied operating-profit / RASK / CASK surface.

Sanity checks:

    A. Annualisation mismatch - v4 forecasts H1 EPS; consensus is FY.
       v4's x2 annualisation is validated against each carrier's own
       historical H1/FY profit split (3-year average).  Spring's H1 share
       is ~49% (x2 ~correct) but Juneyao's is ~37% (x2.7 needed) - the
       x2 convention materially understates Juneyao's FY surprise.
    B. Share-count definition - consensus implied shares (NI/EPS) vs the
       model's implied shares (FY2025 attributable / basic EPS).
    C. Parent vs attributable - consensus profit is attributable net
       income; verify against reported attributable and minority stakes.
    D. One-offs - Spring's 1H2025 other_income (651m, 32% of H1 PBT) is
       carried into the v4 H1-2026 bridge; flag its size and persistence.

Implied surface (per carrier): from consensus FY EPS -> NI -> PBT ->
operating profit -> RASK/CASK, under three assumption modes:

    1. assuming OUR CASK  -> implied RASK (yield) required by consensus
    2. assuming OUR RASK  -> implied CASK required by consensus
    3. midpoint           -> both implied at the average of the two

The output answers: "Street needs Spring passenger yield to change X% /
CASK to change Y% to reconcile with consensus, while our operating data
imply Z."  That is the variant perception, stated as an assumption gap.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..config import NORMALIZED_DIR

logger = logging.getLogger(__name__)


SANITY_OUTPUT_PATH = NORMALIZED_DIR / "airline_consensus_reverse_v2_sanity.csv"
SURFACE_OUTPUT_PATH = NORMALIZED_DIR / "airline_consensus_reverse_v2_surface.csv"
SEASONALITY_OUTPUT_PATH = NORMALIZED_DIR / "airline_consensus_reverse_v2_seasonality.csv"
DATASET_ID = "airline_consensus_reverse_v2"

EXPECTATION_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
V3_PATH = NORMALIZED_DIR / "airline_earnings_model_v3.csv"
OFFICIAL_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
H1_BACKTEST_PATH = NORMALIZED_DIR / "airline_h1_kpi_backtest.csv"
PERIOD_BACKTEST_PATH = NORMALIZED_DIR / "airline_period_kpi_backtest.csv"
FORWARD_NI_PATH = NORMALIZED_DIR / "airline_forward_net_income_bridge.csv"
V4_LIVE_PATH = NORMALIZED_DIR / "airline_earnings_model_v4_live_forecast.csv"
UNIT_ECONOMICS_PATH = NORMALIZED_DIR / "airline_unit_economics.csv"
CONSENSUS_REVERSE_PATH = NORMALIZED_DIR / "airline_consensus_reverse.csv"

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
    if rows.empty:
        return pd.Series(dtype=object)
    if "market" in rows.columns:
        cn_a = rows[rows.market.eq("CN_A")]
        if not cn_a.empty:
            return cn_a.iloc[0]
    return rows.iloc[0]


def _seasonality(company: str, h1_bt: pd.DataFrame, fy_bt: pd.DataFrame) -> dict[str, float | None]:
    """3-year average H1 share of FY attributable profit."""
    h = h1_bt[h1_bt.company.eq(company)].sort_values("target_year")
    f = fy_bt[(fy_bt.company.eq(company)) & (fy_bt.period.eq("FY"))].sort_values("target_year")
    ratios: list[float] = []
    years: list[int] = []
    for y in [2023, 2024, 2025]:
        hr = h[h.target_year.eq(y)]
        fr = f[f.target_year.eq(y)]
        if hr.empty or fr.empty:
            continue
        h1p = _num(hr.iloc[0].get("target_h1_attributable_profit_native_mn"))
        fyp = _num(fr.iloc[0].get("target_attributable_profit_native_mn"))
        # Only PROFITABLE years carry seasonality information: a loss year
        # distorts the H1/FY ratio (and two loss years divide to a
        # meaningless positive number).
        if (
            h1p is not None
            and fyp not in (None, 0)
            and h1p > 0
            and fyp > 0
        ):
            ratios.append(h1p / fyp)
            years.append(y)
    if not ratios:
        return {"h1_share_3y_avg": None, "fy_multiplier": None, "years": []}
    if len(ratios) < 2:
        # A single profitable year cannot support a seasonality estimate
        # (Hainan 2025 alone would imply a 35x FY multiplier - absurd).
        return {
            "h1_share_3y_avg": None,
            "fy_multiplier": None,
            "years": years,
            "seasonality_unreliable": "single_profitable_year",
        }
    avg = float(np.mean(ratios))
    return {
        "h1_share_3y_avg": avg,
        "fy_multiplier": 1.0 / avg if avg > 0 else None,
        "years": years,
        "seasonality_unreliable": None,
    }


def _sanity_rows(
    expectation: pd.DataFrame,
    v3: pd.DataFrame,
    h1_bt: pd.DataFrame,
    fy_bt: pd.DataFrame,
    v4_live: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for company in COMPANIES:
        exp = _row(expectation, company=company)
        v3b = _row(v3, company=company, scenario="base")
        v4 = _row(v4_live, company=company)
        season = _seasonality(company, h1_bt, fy_bt)

        cons_eps = _num(exp.get("a_share_eps_2026_native"))
        cons_ni = _num(exp.get("fy2026_net_profit_avg_native_mn"))
        model_shares = _num(v3b.get("implied_basic_shares_mn"))
        fy25_attr = _num(v3b.get("fy2025_attributable_net_income_native_mn"))
        fy25_eps = _num(v3b.get("fy2025_basic_eps_rmb_per_share"))
        implied_shares_cons = cons_ni / cons_eps if (cons_ni is not None and cons_eps) else None
        implied_shares_model = fy25_attr / fy25_eps if (fy25_attr is not None and fy25_eps) else None
        share_gap_pct = (
            (implied_shares_cons / implied_shares_model - 1.0) * 100.0
            if implied_shares_cons and implied_shares_model
            else None
        )

        # A. annualisation
        h1_eps = _num(v4.get("eps_overlay_rmb"))
        h1_valid = bool(v4.get("h1_annualisation_valid")) if not v4.empty else False
        x2_eps = h1_eps * 2.0 if h1_eps is not None else None
        season_eps = h1_eps * season["fy_multiplier"] if (h1_eps is not None and season["fy_multiplier"]) else None
        surprise_x2 = (
            (x2_eps / cons_eps - 1.0) * 100.0
            if h1_valid and x2_eps is not None and cons_eps
            else None
        )
        surprise_season = (
            (season_eps / cons_eps - 1.0) * 100.0
            if h1_valid and season_eps is not None and cons_eps
            else None
        )
        annualisation_mismatch = bool(
            h1_valid
            and season["fy_multiplier"] is not None
            and abs(season["fy_multiplier"] - 2.0) > 0.25
        )

        # D. one-off: 1H2025 other_income share of H1 PBT
        h1_op = None
        h1_other = None
        h1_fin = None
        official = pd.read_csv(OFFICIAL_PATH)
        s25 = official[(official.company.eq(company)) & (official.statement_period.eq("1H2025"))]
        op_r = s25[s25.metric.eq("operating_profit")]
        oth_r = s25[s25.metric.eq("other_income")]
        fin_r = s25[s25.metric.eq("finance_cost")]
        if not op_r.empty:
            h1_op = _num(op_r.iloc[0].get("value_native"))
        if not oth_r.empty:
            h1_other = _num(oth_r.iloc[0].get("value_native"))
        if not fin_r.empty:
            h1_fin = _num(fin_r.iloc[0].get("value_native"))
        h1_pbt = None
        if h1_op is not None and h1_fin is not None:
            h1_pbt = h1_op + (h1_other or 0.0) - h1_fin
        other_share_pbt = (
            h1_other / h1_pbt if h1_other is not None and h1_pbt not in (None, 0) else None
        )

        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "consensus_eps_fy2026_rmb": cons_eps,
                "consensus_ni_fy2026_native_mn": cons_ni,
                "consensus_as_of_date": str(exp.get("profit_consensus_as_of_date", "")),
                "consensus_age_days": _num(exp.get("profit_consensus_age_days")),
                "consensus_freshness": str(exp.get("profit_consensus_freshness_band", "")),
                "model_implied_shares_mn": implied_shares_model,
                "consensus_implied_shares_mn": implied_shares_cons,
                "share_count_gap_pct": share_gap_pct,
                "share_count_sane": bool(share_gap_pct is not None and abs(share_gap_pct) < 5.0),
                "h1_share_of_fy_3y_avg_pct": season["h1_share_3y_avg"] * 100.0 if season["h1_share_3y_avg"] else None,
                "seasonality_fy_multiplier": season["fy_multiplier"],
                "v4_h1_eps_rmb": h1_eps,
                "v4_fy_eps_x2_rmb": x2_eps,
                "v4_fy_eps_season_adj_rmb": season_eps,
                "surprise_vs_consensus_x2_pct": surprise_x2,
                "surprise_vs_consensus_season_adj_pct": surprise_season,
                "h1_annualisation_valid": h1_valid,
                "annualisation_mismatch_flagged": annualisation_mismatch,
                "h1_other_income_native_mn": h1_other,
                "h1_other_income_share_of_pbt": other_share_pbt,
                "one_off_flagged": bool(other_share_pbt is not None and other_share_pbt > 0.15),
                "parent_vs_attributable_ni_fy2025_native_mn": fy25_attr,
            }
        )
    return rows


def _surface_rows(
    expectation: pd.DataFrame,
    v3: pd.DataFrame,
    unit: pd.DataFrame,
    reverse: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Implied RASK/CASK surface under three consensus assumptions."""
    rows: list[dict[str, Any]] = []
    for company in COMPANIES:
        exp = _row(expectation, company=company)
        v3b = _row(v3, company=company, scenario="base")
        ue = _row(unit, company=company, period="FY2025")
        rv = _row(reverse, company=company, fiscal_year=2026)

        cons_rev = _num(exp.get("fy2026_revenue_avg_native_mn"))
        cons_ni = _num(exp.get("fy2026_net_profit_avg_native_mn"))
        model_rask = _num(ue.get("rask_native"))
        model_cask = _num(ue.get("cask_native"))
        ask = _num(v3b.get("fy2025_ask_mn_seat_km")) or _num(rv.get("model_ask_mn"))
        if cons_rev is None or cons_ni is None or ask in (None, 0):
            continue
        if model_rask is None or model_cask is None:
            continue
        implied_rask = cons_rev / ask
        implied_cask = implied_rask - (model_rask - model_cask)
        rask_gap = (implied_rask / model_rask - 1.0) * 100.0
        cask_gap = (implied_cask / model_cask - 1.0) * 100.0
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "consensus_revenue_native_mn": cons_rev,
                "consensus_ni_native_mn": cons_ni,
                "model_rask_native": model_rask,
                "model_cask_native": model_cask,
                "consensus_implied_rask_native": implied_rask,
                "consensus_implied_cask_native": implied_cask,
                "implied_rask_gap_vs_model_pct": rask_gap,
                "implied_cask_gap_vs_model_pct": cask_gap,
                "interpretation": (
                    f"Consensus reconciles if {company} RASK is "
                    f"{rask_gap:+.1f}% vs our model (holding our CASK) or "
                    f"CASK is {cask_gap:+.1f}% vs our model (holding our RASK)."
                    if rask_gap is not None and cask_gap is not None
                    else "insufficient data"
                ),
            }
        )
    return rows


def build_airline_consensus_reverse_v2() -> dict[str, pd.DataFrame]:
    """Build sanity checks, seasonality table and implied surface."""
    retrieved = datetime.now(timezone.utc).isoformat()
    expectation = pd.read_csv(EXPECTATION_PATH)
    v3 = pd.read_csv(V3_PATH)
    h1_bt = pd.read_csv(H1_BACKTEST_PATH)
    fy_bt = pd.read_csv(PERIOD_BACKTEST_PATH)
    v4_live = pd.read_csv(V4_LIVE_PATH)
    unit = pd.read_csv(UNIT_ECONOMICS_PATH)
    reverse = pd.read_csv(CONSENSUS_REVERSE_PATH)

    sanity = pd.DataFrame(_sanity_rows(expectation, v3, h1_bt, fy_bt, v4_live))
    sanity["retrieved_at"] = retrieved
    sanity.to_csv(SANITY_OUTPUT_PATH, index=False)

    season_rows = []
    for company in COMPANIES:
        s = _seasonality(company, h1_bt, fy_bt)
        season_rows.append({"company": company, **s, "retrieved_at": retrieved})
    season = pd.DataFrame(season_rows)
    season.to_csv(SEASONALITY_OUTPUT_PATH, index=False)

    surface = pd.DataFrame(_surface_rows(expectation, v3, unit, reverse))
    surface["retrieved_at"] = retrieved
    surface.to_csv(SURFACE_OUTPUT_PATH, index=False)

    return {"sanity": sanity, "seasonality": season, "surface": surface}


__all__ = [
    "SANITY_OUTPUT_PATH",
    "SURFACE_OUTPUT_PATH",
    "SEASONALITY_OUTPUT_PATH",
    "build_airline_consensus_reverse_v2",
]
