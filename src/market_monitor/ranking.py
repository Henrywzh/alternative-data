"""Wrapper ranking: separate 'Buy Now' from 'Hold'.

Buy-Now is priced, not voted on. Entry cost is a real quantity in basis
points -- the premium paid over IOPV plus the half-spread crossed -- and the
score is that cost read against the same absolute bands ``entry_status`` uses.
This replaces an earlier min-max-within-cohort scheme that normalised each
component to 0-100 and averaged them. Min-max is invariant to scale, so it
discarded magnitude entirely: in a two-member cohort every component collapsed
to {0, 100} and the score degenerated into a tally of components won. Two S&P
500 wrappers 4 percentage points apart in premium both scored exactly 50.0 and
tied for rank 1.

Liquidity is reported beside the score rather than blended into it, because
its value saturates: above roughly a billion CNY of daily turnover, more
turnover does not make an entry cheaper, and averaging it in let a wrapper
with 8x the turnover outrank one that was 22bp cheaper to buy.

Hold still weighs structural quality (fee, size proxy, fund age) comparatively
within the same-index cohort, where a relative reading is what is wanted.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# Entry cost in basis points mapped to a 0-100 score. The interior
# breakpoints are exactly _calc_entry_status's thresholds converted to bp, so
# the score and the status label can never disagree about what "expensive"
# means: 75 is the ATTRACTIVE/FAIR boundary, 50 the FAIR/EXPENSIVE boundary,
# 25 the EXPENSIVE/AVOID boundary. The outer points extend the scale far
# enough that real quotes land inside it and stay strictly ordered.
_ENTRY_COST_ANCHORS: dict[bool, tuple[list[float], list[float]]] = {
    False: ([-200.0, -10.0, 20.0, 100.0, 300.0], [100.0, 75.0, 50.0, 25.0, 0.0]),
    True: ([-500.0, 0.0, 150.0, 400.0, 1200.0], [100.0, 75.0, 50.0, 25.0, 0.0]),
}

# Turnover on a log10 scale, deliberately saturating: the step from 1e6 to 1e7
# CNY/day is the difference between untradeable and thin, the step from 1e9 to
# 1e10 is the difference between ample and more ample.
_LIQUIDITY_LOG_ANCHORS: tuple[list[float], list[float]] = (
    [6.0, 7.0, 8.0, 9.0, 10.0],
    [0.0, 40.0, 75.0, 95.0, 100.0],
)


def entry_cost_bp(frame: pd.DataFrame) -> pd.Series:
    """Cost of entering one wrapper, in basis points.

    The premium over IOPV is paid in full; crossing the book costs half the
    quoted spread. Both are expressed in bp so they simply add -- which is the
    whole point, since on live quotes the premium spread across a cohort is
    5-400bp while the half-spread is 0.6-8.5bp. Scoring them as equal-weight
    0-100 components inflated the smaller one by two orders of magnitude.

    A missing spread is treated as zero rather than voiding the row: it
    flatters the wrapper by at most a few bp, where voiding it would discard a
    premium reading worth up to 400.  A missing premium yields NaN, because
    without it there is no entry cost to speak of.
    """
    premium = pd.to_numeric(frame.get("premium_pct"), errors="coerce")
    if "spread_bp" in frame.columns:
        spread = pd.to_numeric(frame["spread_bp"], errors="coerce").fillna(0.0)
    else:
        spread = pd.Series(0.0, index=frame.index)
    return premium * 100.0 + spread / 2.0


def _entry_cost_score(cost: pd.Series, cross_border: pd.Series) -> pd.Series:
    """Map entry cost to 0-100 against the absolute band for its regime."""
    out = pd.Series(float("nan"), index=cost.index, dtype=float)
    for is_cross in (False, True):
        mask = cross_border.astype(bool).eq(is_cross)
        if not mask.any():
            continue
        xs, ys = _ENTRY_COST_ANCHORS[is_cross]
        out.loc[mask] = np.interp(cost.loc[mask].to_numpy(dtype=float), xs, ys)
    return out


def _liquidity_score(turnover: pd.Series) -> pd.Series:
    positive = pd.to_numeric(turnover, errors="coerce")
    positive = positive.where(positive > 0)
    xs, ys = _LIQUIDITY_LOG_ANCHORS
    return pd.Series(np.interp(np.log10(positive.to_numpy(dtype=float)), xs, ys), index=turnover.index)


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
    HOLD_COMPONENTS = {
        "management_fee": -1.0,
        "aum": 1.0,
        "fund_age_days": 1.0,
    }

    hold_score_sum = pd.Series(0.0, index=out.index)
    hold_weight = pd.Series(0.0, index=out.index)
    # Normalize each component *within* the same-index cohort (group_col), not
    # globally, so QDII wrappers are never scored against mainland A-share ETFs
    # on fee/AUM. Missing components contribute neither score nor weight; the
    # remaining weights are renormalised so a funded cohort still gets 0-100.
    for cohort, cohort_rows in out.groupby(group_col):
        cohort_index = cohort_rows.index
        for col, direction in HOLD_COMPONENTS.items():
            if col in out.columns:
                sub = out.loc[cohort_index, col]
                if sub.notna().any():
                    norm_scores = _norm(sub, invert=bool(direction == -1.0))
                    valid = sub.notna()
                    hold_score_sum.loc[cohort_index] = hold_score_sum.loc[cohort_index] + norm_scores.where(valid, 0.0)
                    hold_weight.loc[cohort_index] = hold_weight.loc[cohort_index] + valid.astype(float)

    # Row-level normalization: score = sum(valid scores) / count(valid weights)
    # A fund with only 2 of 3 hold fields gets scored on those 2.
    hold_score = hold_score_sum / hold_weight.replace(0, float("nan"))

    cross_border = out["is_cross_border"] if "is_cross_border" in out.columns else pd.Series(False, index=out.index)
    out["entry_cost_bp"] = entry_cost_bp(out).round(2)
    out["buy_score"] = _entry_cost_score(out["entry_cost_bp"], cross_border).round(1)
    out["liquidity_score"] = (
        _liquidity_score(out["turnover"]).round(1)
        if "turnover" in out.columns
        else pd.Series(float("nan"), index=out.index)
    )
    out["hold_score"] = hold_score.round(1)

    # A fund with no quote (halted, or newly listed with no Eastmoney spot row)
    # keeps a NaN score and lands on rank 99 -- outside the 1..n a real cohort
    # produces, so "not measured" stays readable as itself. Scoring it 0 would
    # have ranked it last, which asserts it is the worst wrapper rather than an
    # unmeasured one; entry_status already reports UNAVAILABLE for the same row.
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
