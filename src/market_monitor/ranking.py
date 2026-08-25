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
# Three regimes, not two. Measured over two years of NAV-based premium for
# every tracked wrapper:
#
#     domestic (CSI 300/500/1000, dividend, growth)   median  0.00%, p95 0.2%
#     connect  (Hang Seng, HS Tech, HK dividend)      median -0.02%, p95 1.3%
#     quota    (Nasdaq 100, S&P 500 QDII)             median  3.1%,  p95 8.7%
#
# A Stock Connect wrapper is cross-border but not quota-constrained: arbitrage
# works, so it trades near NAV and only the session mismatch with Hong Kong
# widens it. Scored on the quota scale, a connect fund at its own 95th
# percentile of 1.3% reads FAIR -- a two-year extreme presented as ordinary.
_ENTRY_COST_ANCHORS: dict[str, tuple[list[float], list[float]]] = {
    "domestic": ([-200.0, -10.0, 20.0, 100.0, 300.0], [100.0, 75.0, 50.0, 25.0, 0.0]),
    "connect": ([-300.0, -10.0, 60.0, 160.0, 500.0], [100.0, 75.0, 50.0, 25.0, 0.0]),
    "quota": ([-500.0, 0.0, 150.0, 400.0, 1200.0], [100.0, 75.0, 50.0, 25.0, 0.0]),
}
# QDII wrappers live in the same quota-constrained premium regime, so they
# score on the same curve. The alias is spelled out rather than duplicated so
# the fact that the two are currently identical stays visible: if QDII ever
# earns its own curve, this line is where it stops being an alias.
_ENTRY_COST_ANCHORS["qdii"] = _ENTRY_COST_ANCHORS["quota"]

# The status bands are the anchors above read as percentages of premium, so a
# score and its label can never disagree.
_ENTRY_STATUS_BANDS: dict[str, tuple[float, float, float]] = {
    "domestic": (-0.1, 0.2, 1.0),
    "connect": (-0.1, 0.5, 1.5),
    "quota": (0.0, 1.5, 4.0),
    # QDII wrappers: NAV lag and FX make small premiums normal. These bands are
    # currently the quota bands exactly -- stated as its own entry so the two
    # can diverge, not because they differ today.
    "qdii": (0.0, 1.5, 4.0),
}

# Every regime that can produce a status must also be able to produce a score.
# The two tables drifted apart once already: "qdii" was added to the bands and
# not to the anchors, which left every QDII wrapper with a NaN buy_score and
# rank 99 -- the sentinel that means "no quote", so the rows claimed to be
# unmeasured while entry_status showed they had been measured.
assert set(_ENTRY_STATUS_BANDS) == set(_ENTRY_COST_ANCHORS), (
    "premium regimes must appear in both _ENTRY_STATUS_BANDS and "
    f"_ENTRY_COST_ANCHORS; got {sorted(_ENTRY_STATUS_BANDS)} vs "
    f"{sorted(_ENTRY_COST_ANCHORS)}"
)


def premium_regime(frame: pd.DataFrame) -> pd.Series:
    """Which premium regime each wrapper lives in.

    Declared per fund; falls back to the older is_cross_border flag so an
    artifact built before the column existed still scores.
    """
    if "premium_regime" in frame.columns:
        declared = frame["premium_regime"].astype("string")
        if declared.notna().any():
            fallback = frame["is_cross_border"] if "is_cross_border" in frame.columns else False
            legacy = pd.Series(fallback, index=frame.index).astype(bool).map(
                {True: "quota", False: "domestic"}
            )
            return declared.fillna(legacy).astype(str)
    cross = frame["is_cross_border"] if "is_cross_border" in frame.columns else False
    return pd.Series(cross, index=frame.index).astype(bool).map({True: "quota", False: "domestic"})

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
# Total holding cost (management + custody) in bp per year -- custody is
# 5-15bp and is charged to the same holder, so pricing management alone
# understated every fund by roughly the same amount it differentiated them by.
# 20bp is a price-war passive fund, 60bp the A-share standard, 100bp+ is being
# charged for beta.
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


def _entry_cost_score(cost: pd.Series, regime: pd.Series) -> pd.Series:
    """Map entry cost to 0-100 against the absolute band for its regime."""
    out = pd.Series(float("nan"), index=cost.index, dtype=float)
    for name, (xs, ys) in _ENTRY_COST_ANCHORS.items():
        mask = regime.eq(name)
        if not mask.any():
            continue
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
        fee = pd.to_numeric(frame["management_fee"], errors="coerce")
        if "custody_fee" in frame.columns:
            fee = fee.add(pd.to_numeric(frame["custody_fee"], errors="coerce").fillna(0.0))
        parts.append((_interp_or_nan(fee * 10000.0, *_FEE_BP_ANCHORS), _HOLD_WEIGHTS["fee"]))
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
    # A last-close reconstruction is useful context for an audit trail, but it
    # is not a current quote. Keep the value in the row so the provenance is
    # inspectable while removing it from every entry-cost decision. The same
    # gate also handles a quote explicitly marked stale/unavailable by a
    # provider-aware caller.
    quote_is_current = pd.Series(True, index=out.index)
    if "premium_pct" in out.columns:
        quote_is_current &= pd.to_numeric(out["premium_pct"], errors="coerce").notna()
    if "quote_basis" in out.columns:
        quote_is_current &= ~out["quote_basis"].astype(str).eq("last_close")
    if "quote_status" in out.columns:
        status = out["quote_status"].fillna("").astype(str)
        quote_is_current &= status.isin({"", "Fresh"})

    # Relative premium is a current-cohort comparison, not an audit value for
    # last-close or unverified rows. Recompute it after the quote gate so a
    # stale row cannot become the median anchor for today's comparison. Keep
    # the raw premium itself for provenance; derived current-signal fields are
    # cleared below when the quote is not verified.
    if "premium_pct" in out.columns:
        current_premium = pd.to_numeric(out["premium_pct"], errors="coerce").where(quote_is_current)
        out["relative_premium_pct"] = current_premium.groupby(out[group_col]).transform(
            lambda values: values - values.median() if values.notna().any() else values
        )
    elif "relative_premium_pct" in out.columns:
        out.loc[~quote_is_current, "relative_premium_pct"] = float("nan")

    hold_score = _hold_quality_score(out)

    regime = premium_regime(out)
    out["premium_regime"] = regime
    out["entry_cost_bp"] = entry_cost_bp(out).where(quote_is_current).round(2)
    out["buy_score"] = _entry_cost_score(out["entry_cost_bp"], regime).round(1)
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
        if str(row.get("quote_basis") or "") == "last_close":
            return "UNAVAILABLE"
        quote_status = row.get("quote_status")
        if pd.notna(quote_status) and str(quote_status) not in {"", "Fresh"}:
            return "UNAVAILABLE"
        if pd.isna(row.get("premium_pct")):
            return "UNAVAILABLE"
        p = row.get("premium_pct")
        if pd.isna(p):
            return "UNAVAILABLE"
        p = float(p)
        declared = str(row.get("premium_regime") or "domestic")
        # An unrecognised regime must not be scored against domestic bands: a
        # QDII wrapper silently judged on a +/-0.1% band reads as AVOID for a
        # premium that is ordinary for its regime.
        if declared not in _ENTRY_STATUS_BANDS:
            return "UNAVAILABLE"
        attractive, fair, expensive = _ENTRY_STATUS_BANDS[declared]
        if p <= attractive:
            return "ATTRACTIVE"
        if p <= fair:
            return "FAIR"
        if p <= expensive:
            return "EXPENSIVE"
        return "AVOID"

    out["entry_status"] = out.apply(_calc_entry_status, axis=1)
    return out
