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

# Hold-side anchors, absolute for the same reason the buy side is. Min-max
# within a cohort cannot express "all three of these are expensive": when the
# three CSI 300 wrappers all charge exactly 0.50%, _norm sees nunique() == 1
# and hands every one of them 50, so a component advertised as differentiating
# on fee was only pulling every score toward the middle.
#
# Management fee in bp per year. 15bp is a price-war passive fund, 50bp is the
# A-share standard, 100bp+ is being charged for beta.
_FEE_BP_ANCHORS: tuple[list[float], list[float]] = (
    [5.0, 15.0, 50.0, 100.0, 200.0],
    [100.0, 90.0, 60.0, 30.0, 0.0],
)
# Fund size on log10 CNY, saturating: size is a survivorship proxy (closure and
# delisting risk), and past ~10bn CNY more size stops telling you anything.
_SIZE_LOG_ANCHORS: tuple[list[float], list[float]] = (
    [7.0, 8.0, 9.0, 10.0, 11.0],
    [0.0, 30.0, 70.0, 90.0, 100.0],
)
# Fund age in days, saturating: the risk being priced is an unproven fund, and
# a decade of operating history is not twice as reassuring as five years.
_AGE_DAY_ANCHORS: tuple[list[float], list[float]] = (
    [0.0, 365.0, 1095.0, 3650.0],
    [0.0, 50.0, 85.0, 100.0],
)
# Fee is a certain, compounding, annual cost; size and age are risk proxies.
# Weighting them equally said a fund's launch date matters as much as what it
# charges you every year for holding it.
_HOLD_WEIGHTS = {"fee": 2.0, "size": 1.0, "age": 1.0}


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


def _hold_quality_score(frame: pd.DataFrame) -> pd.Series:
    """Structural quality of holding one wrapper, on an absolute 0-100 scale.

    Each component is scored against what the number means in itself, not
    against the other wrappers in the cohort, so a cohort in which every fund
    is expensive scores low across the board instead of spreading 0/50/100.
    Components that are missing contribute no score and no weight; the rest are
    renormalised, and a row with nothing to score stays NaN rather than 0.
    """
    parts: list[tuple[pd.Series, float]] = []

    if "management_fee" in frame.columns:
        fee_bp = pd.to_numeric(frame["management_fee"], errors="coerce") * 10000.0
        parts.append((_interp_or_nan(fee_bp, *_FEE_BP_ANCHORS), _HOLD_WEIGHTS["fee"]))
    size_col = "aum_proxy" if "aum_proxy" in frame.columns else ("aum" if "aum" in frame.columns else None)
    if size_col:
        size = pd.to_numeric(frame[size_col], errors="coerce")
        parts.append((_interp_or_nan(np.log10(size.where(size > 0)), *_SIZE_LOG_ANCHORS), _HOLD_WEIGHTS["size"]))
    if "fund_age_days" in frame.columns:
        age = pd.to_numeric(frame["fund_age_days"], errors="coerce")
        parts.append((_interp_or_nan(age, *_AGE_DAY_ANCHORS), _HOLD_WEIGHTS["age"]))

    if not parts:
        return pd.Series(float("nan"), index=frame.index)
    total = pd.Series(0.0, index=frame.index)
    weight = pd.Series(0.0, index=frame.index)
    for scores, w in parts:
        valid = scores.notna()
        total = total + scores.where(valid, 0.0) * w
        weight = weight + valid.astype(float) * w
    return total / weight.replace(0.0, float("nan"))


def _interp_or_nan(values: pd.Series, xs: list[float], ys: list[float]) -> pd.Series:
    """np.interp that preserves NaN instead of clamping it to an endpoint."""
    arr = pd.to_numeric(values, errors="coerce")
    out = pd.Series(np.interp(arr.to_numpy(dtype=float), xs, ys), index=values.index)
    return out.where(arr.notna())


def rank_wrappers(frame: pd.DataFrame, *, group_col: str = "exposure_id") -> pd.DataFrame:
    """Score and rank wrappers within each same-index cohort.

    Reads premium_pct (IOPV premium %), spread_bp, turnover, aum_proxy (or
    aum), management_fee and fund_age_days; every one is optional and a row
    scores on whatever it has. Writes entry_cost_bp, buy_score,
    liquidity_score, hold_score, buy_rank / peer_rank, hold_rank and
    entry_status.

    Scores are absolute, not cohort-relative -- the cohort decides who is
    compared with whom, not what the numbers mean. Ranks are per cohort, so a
    QDII wrapper is never ranked against a mainland A-share ETF.
    """
    out = frame.copy()
    hold_score = _hold_quality_score(out)

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
