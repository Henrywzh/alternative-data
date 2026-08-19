"""Wrapper ranking: separate 'Buy Now' from 'Hold'.

Buy-Now weighs entry cost (premium, relative premium, spread, turnover,
market depth proxy). Hold weighs structural quality (fee, AUM, fund age,
tracking proxy). Both are normalized to 0-100 within the same-index cohort.
"""

from __future__ import annotations

import pandas as pd


def _norm(series: pd.Series, *, invert: bool) -> pd.Series:
    """Min-max normalize to 0-100. If invert, higher raw => lower score."""
    s = series.astype(float)
    finite = s.replace([float("inf"), float("-inf")], float("nan")).dropna()
    if finite.empty or finite.nunique() <= 1:
        return pd.Series(50.0, index=series.index)
    lo, hi = finite.min(), finite.max()
    norm = (s - lo) / (hi - lo) * 100.0
    if invert:
        norm = 100.0 - norm
    return norm.clip(0, 100)


def _z_score(series: pd.Series) -> pd.Series:
    s = series.astype(float)
    finite = s.dropna()
    if finite.empty or finite.std(ddof=0) == 0:
        return pd.Series(0.0, index=series.index)
    return ((s - finite.mean()) / finite.std(ddof=0)).fillna(0.0)


def rank_wrappers(frame: pd.DataFrame, *, group_col: str = "exposure_id") -> pd.DataFrame:
    """Add buy_now_score / hold_score / buy_rank / hold_rank for each cohort.

    Expects columns: premium_pct (IOPV premium %), relative_premium_pct,
    spread_bp, turnover (amount), aum, management_fee, fund_age_days.
    """
    out = frame.copy()
    if "relative_premium_pct" in out.columns and group_col in out.columns:
        out["relative_premium_z"] = out.groupby(group_col)["relative_premium_pct"].transform(_z_score)
    elif "relative_premium_pct" in out.columns:
        out["relative_premium_z"] = _z_score(out["relative_premium_pct"])
    else:
        out["relative_premium_z"] = 0.0
    BUY_COMPONENTS = {
        "premium_pct": -1.0,  # negative premium (discount) preferred
        "relative_premium_pct": -1.0,
        "spread_bp": -1.0,
        "turnover": 1.0,
    }
    HOLD_COMPONENTS = {
        "management_fee": -1.0,
        "aum": 1.0,
        "fund_age_days": 1.0,
    }

    buy_score = pd.Series(0.0, index=out.index)
    hold_score = pd.Series(0.0, index=out.index)
    # Normalize each component *within* the same-index cohort (group_col), not
    # globally, so QDII wrappers are never scored against mainland A-share ETFs
    # on fee/AUM. Missing components contribute neither score nor weight; the
    # remaining weights are renormalised so a funded cohort still gets 0-100.
    for cohort, cohort_rows in out.groupby(group_col):
        cohort_index = cohort_rows.index
        buy_i = pd.Series(0.0, index=cohort_index)
        hold_i = pd.Series(0.0, index=cohort_index)
        buy_w, hold_w = 0.0, 0.0
        for col, direction in BUY_COMPONENTS.items():
            if col in out.columns:
                sub = out.loc[cohort_index, col]
                if sub.notna().any():
                    buy_i = buy_i + _norm(sub, invert=bool(direction == -1.0))
                    buy_w += 1.0
        for col, direction in HOLD_COMPONENTS.items():
            if col in out.columns:
                sub = out.loc[cohort_index, col]
                if sub.notna().any():
                    hold_i = hold_i + _norm(sub, invert=bool(direction == -1.0))
                    hold_w += 1.0
        if buy_w:
            buy_score.loc[cohort_index] = buy_i / buy_w
        if hold_w:
            hold_score.loc[cohort_index] = hold_i / hold_w

    # A component that is entirely missing (e.g. a newly-listed or halted ETF
    # with no Eastmoney spot row) would make the fund's score NaN. NaN rows
    # previously crashed .astype(int) via IntCastingNaNError; fill to 0 so the
    # halted fund is ranked last instead of breaking the whole daily run.
    out["buy_score"] = buy_score.fillna(0.0).round(1)
    out["hold_score"] = hold_score.fillna(0.0).round(1)
    out["buy_rank"] = out.groupby(group_col)["buy_score"].rank(ascending=False, method="dense", na_option="keep").fillna(99).astype(int)
    out["hold_rank"] = out.groupby(group_col)["hold_score"].rank(ascending=False, method="dense", na_option="keep").fillna(99).astype(int)
    out["peer_rank"] = out["buy_rank"]

    def _calc_entry_status(row: pd.Series) -> str:
        p = row.get("premium_pct")
        if pd.isna(p):
            return "UNAVAILABLE"
        p = float(p)
        is_cross = bool(row.get("is_cross_border", False))
        if is_cross:
            if p <= 0.0:
                return "ATTRACTIVE"
            if p <= 1.5:
                return "FAIR"
            if p <= 4.0:
                return "EXPENSIVE"
            return "AVOID"
        if p <= -0.1:
            return "ATTRACTIVE"
        if p <= 0.2:
            return "FAIR"
        if p <= 1.0:
            return "EXPENSIVE"
        return "AVOID"

    out["entry_status"] = out.apply(_calc_entry_status, axis=1)
    return out
