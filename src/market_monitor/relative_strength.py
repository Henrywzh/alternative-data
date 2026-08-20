"""Relative-strength spreads and rolling z-scores across exposures.

The core decision signal is *relative* (spread between two exposures), not a
single absolute RSI. V1 computes size / style / region spreads:

    Small/Large   = R(csi1000) - R(csi300)
    Mid/Large     = R(csi500)  - R(csi300)
    Growth/Div    = R(growth)  - R(dividend)
    China/SP500   = R(csi300)  - R(SPX)

Each spread is evaluated over 5D / 20D / 60D / 120D and a full-history rolling
z-score of the 20D spread. ``trend`` compares the 5D vs 20D spread.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


WINDOWS = (5, 20, 60, 120)


def compute_spread_metrics(
    left_close: pd.Series,
    right_close: pd.Series,
    *,
    label: str,
) -> dict[str, float | None]:
    """Compute windowed relative returns + z-score for one spread.

    Both input series are expected to share the same monotonic date index
    (the caller aligns them with ``join="inner"``); positions therefore map to
    the same trading calendar.
    """
    out: dict[str, float | None] = {"label": label}
    joined = pd.concat([left_close.rename("l"), right_close.rename("r")], axis=1, join="inner").dropna()
    for window in WINDOWS:
        left_ret = joined["l"] / joined["l"].shift(window) - 1.0
        right_ret = joined["r"] / joined["r"].shift(window) - 1.0
        spread = ((left_ret - right_ret) * 100.0).dropna()
        out[f"spread_{window}d_pct"] = round(float(spread.iloc[-1]), 4) if not spread.empty else None

    z_window = 20
    # Use a fixed lookback (1 trading year) for the z-score mean/std so the
    # signal is stable to how much history the ingestion happened to load —
    # otherwise switching start_date from 2y to 1y silently rescales every
    # historical z-score.
    lookback = 252
    if len(joined) >= z_window + 1:
        left_ret_z = joined["l"] / joined["l"].shift(z_window) - 1.0
        right_ret_z = joined["r"] / joined["r"].shift(z_window) - 1.0
        roll = ((left_ret_z - right_ret_z) * 100.0).dropna()
        hist = roll.dropna()
        if len(hist) >= z_window:
            baseline = hist.tail(lookback)
            mean = float(baseline.mean())
            std = float(baseline.std(ddof=0))
            out["spread_20d_zscore"] = round(float((hist.iloc[-1] - mean) / std) if std else 0.0, 4)
            out["spread_20d_pct"] = round(float(hist.iloc[-1]), 4)
    return out


def build_relative_regime(close_by_exposure: dict[str, pd.Series]) -> list[dict]:
    """Build the relative-regime block for the dashboard."""
    rows = []
    pairs = (
        ("csi1000", "csi300", "Small / Large"),
        ("csi500", "csi300", "Mid / Large"),
        ("growth", "dividend", "Growth / Dividend"),
        ("csi300", "sp500", "China / S&P 500"),
    )
    for left_id, right_id, label in pairs:
        left_series = close_by_exposure.get(left_id)
        right_series = close_by_exposure.get(right_id)
        if left_series is None or right_series is None or left_series.empty or right_series.empty:
            rows.append({"label": label, "left": left_id, "right": right_id, "spread_20d_zscore": None, "trend": None})
            continue
        metrics = compute_spread_metrics(left_series, right_series, label=label)
        z = metrics.get("spread_20d_zscore")
        s5 = metrics.get("spread_5d_pct")
        s20 = metrics.get("spread_20d_pct")
        # Trend compares the most recent 5D momentum against the 20D window:
        # only if 5D is meaningfully stronger (positive) than the 20D run-rate
        # is it "up", otherwise if it is catching down it is "down".
        if s5 is None or s20 is None:
            trend = None
        else:
            run_rate_20 = s20 / 4.0  # levelise 20D to a 5D-equivalent scale
            trend = "UP" if s5 > run_rate_20 + 0.05 else ("DOWN" if s5 < run_rate_20 - 0.05 else "FLAT")
        rows.append(
            {
                "label": label,
                "left": left_id,
                "right": right_id,
                "spread_20d_zscore": z,
                "spread_5d_pct": s5,
                "spread_20d_pct": s20,
                "trend": trend,
            }
        )
    return rows


# --- Pair ratios ---------------------------------------------------------
#
# The z-score bar chart states one number per pair and nothing about how it
# got there, which is unreadable as a signal: -0.3 today means something very
# different at the end of a year-long slide than at the end of a bounce. The
# blocks below produce the series behind the number -- ratio, its 60-day
# trend, and the z-score of the ratio against its own trailing year -- so the
# dashboard can draw it.

RATIO_MA_WINDOW = 60
RATIO_Z_WINDOW = 252

# Each pair is two equal-weighted baskets. A single index is just a basket of
# one, so offensive-vs-defensive (three sectors a side) and small-vs-large
# (one index a side) go through exactly the same code.
RELATIVE_PAIRS: tuple[dict, ...] = (
    # --- China ---
    {"pair_id": "cn_small_large", "region": "China",
     "label": "Small / Large", "label_zh": "小盘 / 大盘",
     "left": ("csi1000",), "right": ("csi300",)},
    {"pair_id": "cn_mid_large", "region": "China",
     "label": "Mid / Large", "label_zh": "中盘 / 大盘",
     "left": ("csi500",), "right": ("csi300",)},
    {"pair_id": "cn_growth_value", "region": "China",
     "label": "Growth / Value", "label_zh": "成长 / 价值",
     "left": ("chinext",), "right": ("dividend",)},
    {"pair_id": "cn_risk_appetite", "region": "China",
     "label": "Offensive / Defensive", "label_zh": "进攻 / 防御",
     "left": ("cn_infotech",), "right": ("cn_staples",)},
    # --- Hong Kong ---
    {"pair_id": "hk_growth_value", "region": "HK",
     "label": "Growth / Value", "label_zh": "成长 / 价值",
     "left": ("hstech",), "right": ("hk_dividend",)},
    {"pair_id": "hk_large_mid", "region": "HK",
     "label": "Large / Mid", "label_zh": "大盘 / 中盘",
     "left": ("hsi",), "right": ("hk_midcap",)},
    {"pair_id": "hk_hshares", "region": "HK",
     "label": "H-shares / Hang Seng", "label_zh": "国企 / 恒生",
     "left": ("hk_hshares",), "right": ("hsi",)},
    # --- United States ---
    {"pair_id": "us_growth_value", "region": "US",
     "label": "Growth / Value", "label_zh": "成长 / 价值",
     "left": ("us_growth",), "right": ("us_value",)},
    {"pair_id": "us_small_large", "region": "US",
     "label": "Small / Large", "label_zh": "小盘 / 大盘",
     "left": ("us_small",), "right": ("us_broad",)},
    {"pair_id": "us_risk_appetite", "region": "US",
     "label": "Offensive / Defensive", "label_zh": "进攻 / 防御",
     "left": ("us_tech", "us_discretionary", "us_communication"),
     "right": ("us_staples", "us_utilities", "us_healthcare")},
    {"pair_id": "us_breadth", "region": "US",
     "label": "Equal weight / Cap weight", "label_zh": "等权 / 市值加权",
     "left": ("us_equal_weight",), "right": ("us_broad",)},
    # --- Cross-region ---
    {"pair_id": "cn_vs_us", "region": "Cross",
     "label": "China / US", "label_zh": "中国 / 美国",
     "left": ("csi300",), "right": ("us_broad",)},
)


def equal_weight_basket(
    close_by_exposure: dict[str, pd.Series],
    members: tuple[str, ...],
) -> pd.Series | None:
    """Cumulative return of an equally weighted, daily-rebalanced basket.

    Averaging returns rather than levels is what makes the basket meaningful:
    the members are indices and ETFs quoted on entirely different scales, so
    averaging prices would weight by quote size instead of equally.
    """
    available = [close_by_exposure[m] for m in members if close_by_exposure.get(m) is not None and not close_by_exposure[m].empty]
    if not available:
        return None
    if len(available) == 1:
        return available[0].dropna()
    frame = pd.concat(available, axis=1, join="inner").dropna()
    if frame.empty:
        return None
    returns = frame.pct_change(fill_method=None).mean(axis=1)
    return returns.add(1.0).cumprod().dropna()


def pair_ratio_frame(
    close_by_exposure: dict[str, pd.Series],
    pair: dict,
) -> pd.DataFrame:
    """Ratio, its 60D mean, and its z-score against a trailing year."""
    left = equal_weight_basket(close_by_exposure, tuple(pair["left"]))
    right = equal_weight_basket(close_by_exposure, tuple(pair["right"]))
    if left is None or right is None:
        return pd.DataFrame(columns=["date", "pair_id", "ratio", "ratio_ma", "zscore"])
    joined = pd.concat([left.rename("l"), right.rename("r")], axis=1, join="inner").dropna()
    joined = joined[joined["r"] > 0]
    if joined.empty:
        return pd.DataFrame(columns=["date", "pair_id", "ratio", "ratio_ma", "zscore"])
    # Rebased so every pair starts at 1.0 and the level is readable as
    # cumulative relative performance rather than as an artefact of the two
    # quote scales -- SPY/IWM would otherwise sit near 0.2 and CSI1000/CSI300
    # near 1.4 with neither number meaning anything.
    ratio = (joined["l"] / joined["r"])
    ratio = ratio / ratio.iloc[0]
    rolling_mean = ratio.rolling(RATIO_Z_WINDOW).mean()
    rolling_std = ratio.rolling(RATIO_Z_WINDOW).std()
    zscore = (ratio - rolling_mean) / rolling_std.replace(0.0, np.nan)
    return pd.DataFrame(
        {
            "date": ratio.index.strftime("%Y-%m-%d"),
            "pair_id": pair["pair_id"],
            "ratio": ratio.round(6).to_numpy(),
            "ratio_ma": ratio.rolling(RATIO_MA_WINDOW).mean().round(6).to_numpy(),
            "zscore": zscore.round(4).to_numpy(),
        }
    ).reset_index(drop=True)


def regime_label(zscore: float | None) -> tuple[str, str]:
    """Name the reading, in both languages.

    The thresholds are the ones the equity-research hub already uses, so the
    two surfaces call the same z-score the same thing.
    """
    if zscore is None or (isinstance(zscore, float) and np.isnan(zscore)):
        return ("Unavailable", "无数据")
    if zscore > 1.0:
        return ("Strongly favouring the numerator", "明显偏向分子")
    if zscore > 0.0:
        return ("Mildly favouring the numerator", "小幅偏向分子")
    if zscore > -1.0:
        return ("Mildly favouring the denominator", "小幅偏向分母")
    return ("Strongly favouring the denominator", "明显偏向分母")


def build_pair_history(close_by_exposure: dict[str, pd.Series]) -> pd.DataFrame:
    """Ratio history for every declared pair, stacked long."""
    parts = [
        frame
        for frame in (pair_ratio_frame(close_by_exposure, pair) for pair in RELATIVE_PAIRS)
        if not frame.empty
    ]
    if not parts:
        return pd.DataFrame(columns=["date", "pair_id", "ratio", "ratio_ma", "zscore"])
    return pd.concat(parts, ignore_index=True)


def build_pair_summary(
    close_by_exposure: dict[str, pd.Series],
    history: pd.DataFrame,
) -> pd.DataFrame:
    """One row per pair: where it stands now and what it is made of."""
    rows: list[dict] = []
    for pair in RELATIVE_PAIRS:
        series = history[history["pair_id"].eq(pair["pair_id"])] if not history.empty else pd.DataFrame()
        latest = series.iloc[-1] if not series.empty else None
        zscore = None
        if latest is not None and pd.notna(latest["zscore"]):
            zscore = float(latest["zscore"])
        label_en, label_zh = regime_label(zscore)
        ratio = float(latest["ratio"]) if latest is not None and pd.notna(latest["ratio"]) else None
        ratio_ma = float(latest["ratio_ma"]) if latest is not None and pd.notna(latest["ratio_ma"]) else None
        rows.append(
            {
                "pair_id": pair["pair_id"],
                "region": pair["region"],
                "label": pair["label"],
                "label_zh": pair["label_zh"],
                "left": "+".join(pair["left"]),
                "right": "+".join(pair["right"]),
                "ratio": round(ratio, 4) if ratio is not None else None,
                "ratio_ma60": round(ratio_ma, 4) if ratio_ma is not None else None,
                "zscore": round(zscore, 2) if zscore is not None else None,
                # Above its own 60-day mean the numerator is currently winning
                # regardless of where the z-score sits in its yearly range.
                "trend": None if ratio is None or ratio_ma is None else ("UP" if ratio > ratio_ma else "DOWN"),
                "regime": label_en,
                "regime_zh": label_zh,
                "observations": int(len(series)),
            }
        )
    return pd.DataFrame(rows)
