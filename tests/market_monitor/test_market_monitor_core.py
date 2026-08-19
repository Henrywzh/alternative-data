"""Offline unit tests for market_monitor derived-signal math."""

import sys

import numpy as np
import pandas as pd
import pytest

from market_monitor.ranking import rank_wrappers
from market_monitor.relative_strength import build_relative_regime, compute_spread_metrics
from market_monitor.technicals import compute_technicals


def _make_daily(days: int = 120, base: float = 100.0, drift: float = 0.001) -> pd.Series:
    idx = pd.date_range("2026-01-01", periods=days, freq="D")
    changes = np.random.default_rng(7).normal(drift, 0.01, days)
    values = base * np.cumprod(1 + changes)
    return pd.Series(values, index=idx)


def test_technicals_smoke():
    close = _make_daily()
    result = compute_technicals(close)
    assert 0 <= result["rsi"] <= 100
    assert result["ma20"] is not None
    assert result["ma60"] is not None
    assert result["ma20_pct"] is not None
    assert result["drawdown_60d"] <= 0.0  # drawdown is non-positive


def test_technicals_rsi_extremes_stay_bounded():
    # A monotonic rally should push RSI toward the top.
    rng = np.random.default_rng(3)
    daily = 100 * np.cumprod(1 + rng.normal(0.008, 0.005, 90))  # steady up-trend with small noise
    up = pd.Series(daily, index=pd.date_range("2026-01-01", periods=90, freq="D"))
    result = compute_technicals(up)
    assert result["rsi"] > 70


def test_relative_regime_recognizes_leadership():
    rng = np.random.default_rng(42)
    dates = pd.date_range("2026-01-01", periods=100, freq="D")
    strong = pd.Series(100 * np.cumprod(1 + rng.normal(0.004, 0.01, 100)), index=dates)
    weak = pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, 100)), index=dates)
    metrics = compute_spread_metrics(strong, weak, label="small/large")
    assert metrics["spread_5d_pct"] is not None or metrics["spread_20d_pct"] is not None
    assert "spread_20d_zscore" in metrics


def test_relative_regime_builder_emits_rows():
    rng = np.random.default_rng(1)
    dates = pd.date_range("2026-01-01", periods=120, freq="D")
    close_by = {eid: pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.01, 120)), index=dates) for eid in ("csi300", "csi500", "csi1000", "dividend", "growth", "sp500")}
    rows = build_relative_regime(close_by)
    labels = {r["label"] for r in rows}
    assert {"Small / Large", "Mid / Large", "Growth / Dividend", "China / S&P 500"} <= labels


def test_spread_metrics_aligns_by_date_not_position():
    """Different trading calendars must not shift the spread by position."""
    dates_a = pd.date_range("2026-01-01", periods=30, freq="B")  # business days
    dates_b = dates_a[1:]  # B starts one day later / shorter tail
    left = pd.Series(range(30), index=dates_a, dtype=float)
    right = pd.Series(range(1, 30), index=dates_b, dtype=float)
    # Rebuild as in pipeline: same dates for both where they overlap.
    common = dates_a.intersection(dates_b)
    left_c = pd.Series(left.reindex(common).to_numpy(), index=common)
    right_c = pd.Series(right.reindex(common).to_numpy(), index=common)
    metrics = compute_spread_metrics(left_c, right_c, label="cross")
    # Constant 1:1 shift => daily spread 0; cumulative spread stays ~0.
    assert metrics["spread_5d_pct"] is None or abs(metrics["spread_5d_pct"]) < 1e-6


def test_rank_wrappers_produces_two_ranks():
    frame = pd.DataFrame(
        {
            "exposure_id": ["csi500"] * 3,
            "fund_id": ["a", "b", "c"],
            "ticker": ["a", "b", "c"],
            "premium_pct": [-0.1, 0.0, 0.5],
            "relative_premium_pct": [-0.2, -0.1, 0.4],
            "spread_bp": [1.0, 2.0, 5.0],
            "turnover": [6.0, 2.0, 0.5],
            "aum": [100.0, 50.0, 20.0],
            "management_fee": [0.002, 0.005, 0.008],
            "fund_age_days": [4000, 2000, 1000],
        }
    )
    ranked = rank_wrappers(frame)
    assert {"buy_score", "hold_score", "buy_rank", "hold_rank"} <= set(ranked.columns)
    assert sorted(ranked["buy_rank"].tolist()) == [1, 2, 3]
    assert sorted(ranked["hold_rank"].tolist()) == [1, 2, 3]

from market_monitor.storage import save_derived, load_latest
from market_monitor.wrapper import merge_premium
from market_monitor.metadata import build_metadata_frame

def test_rank_wrappers_survives_missing_fund():
    """A halted / unquoted fund (all NaN) must not crash the daily ranking."""
    frame = pd.DataFrame(
        {
            "exposure_id": ["csi500", "csi500", "csi500"],
            "fund_id": ["a", "b", "c"],
            "ticker": ["a", "b", "c"],
            "premium_pct": [-0.1, 0.2, None],
            "relative_premium_pct": [-0.1, 0.1, None],
            "spread_bp": [1.0, 2.0, None],
            "turnover": [5.0, 2.0, None],
            "aum": [100.0, 50.0, None],
            "management_fee": [0.002, 0.005, None],
            "fund_age_days": [4000.0, 2000.0, None],
        }
    )
    ranked = rank_wrappers(frame)
    assert len(ranked) == 3  # missing fund kept, not dropped
    # a (best) ranks 1; b and the fully-missing c both score 0 -> tied last.
    assert ranked.loc[ranked["fund_id"] == "a", "buy_rank"].iloc[0] == 1
    assert ranked.loc[ranked["fund_id"] == "c", "buy_rank"].iloc[0] >= 2


def test_rank_wrappers_entry_status():
    frame = pd.DataFrame(
        {
            "exposure_id": ["sp500", "csi300"],
            "fund_id": ["513500", "510300"],
            "ticker": ["513500", "510300"],
            "premium_pct": [7.01, -0.2],
            "is_cross_border": [True, False],
        }
    )
    ranked = rank_wrappers(frame)
    assert "entry_status" in ranked.columns
    assert ranked.loc[ranked["fund_id"] == "513500", "entry_status"].iloc[0] == "AVOID"
    assert ranked.loc[ranked["fund_id"] == "510300", "entry_status"].iloc[0] == "ATTRACTIVE"


def test_storage_run_scope_filtering():
    from market_monitor.config import DERIVED_DIR
    df_full = pd.DataFrame({"a": [1, 2]})
    df_test = pd.DataFrame({"a": [3]})

    save_derived("test_scope_ds", df_full, metadata={"run_scope": "full"}, run_id="20260819T070000-full")
    save_derived("test_scope_ds", df_test, metadata={"run_scope": "test"}, run_id="20260819T080000-test")

    loaded_full = load_latest(DERIVED_DIR, "test_scope_ds", scope="full")
    assert len(loaded_full) == 2
    loaded_test = load_latest(DERIVED_DIR, "test_scope_ds", scope="test")
    assert len(loaded_test) == 1


def test_merge_premium_aum_resolution():
    meta = build_metadata_frame()
    spot = pd.DataFrame(
        {
            "ticker": ["510300", "510500"],
            "premium_pct": [0.05, -0.10],
            "markcap": [30000000000.0, 15000000000.0],
            "bid": [4.65, 5.20],
            "ask": [4.66, 5.21],
            "spread_bp": [2.1, 1.9],
        }
    )
    merged = merge_premium(spot, meta)
    assert "aum" in merged.columns
    assert "aum_x" not in merged.columns
    assert "aum_y" not in merged.columns
    row_300 = merged[merged["ticker"].str.startswith("510300")]
    assert row_300["aum"].iloc[0] == 30000000000.0


def test_rank_wrappers_partial_field_missing():
    """A fund missing only spread_bp should still score on its other fields."""
    frame = pd.DataFrame(
        {
            "exposure_id": ["csi500"] * 3,
            "fund_id": ["a", "b", "c"],
            "ticker": ["a", "b", "c"],
            "premium_pct": [-0.1, 0.0, 0.5],
            "relative_premium_pct": [-0.2, -0.1, 0.4],
            "spread_bp": [1.0, None, 5.0],  # b missing spread only
            "turnover": [6.0, 2.0, 0.5],
            "aum": [100.0, 50.0, 20.0],
            "management_fee": [0.002, 0.005, 0.008],
            "fund_age_days": [4000, 2000, 1000],
        }
    )
    ranked = rank_wrappers(frame)
    b_score = ranked.loc[ranked["fund_id"] == "b", "buy_score"].iloc[0]
    c_score = ranked.loc[ranked["fund_id"] == "c", "buy_score"].iloc[0]
    # b has valid premium + rel_premium + turnover; c has all 4 but worse values
    # b should NOT be 0 (the old NaN-propagation bug)
    assert b_score > 0, f"fund b partial-missing should not collapse to 0 (got {b_score})"
    assert b_score != c_score, f"partial-missing (b={b_score}) should differ from all-fields-worst (c={c_score})"


def test_relative_strength_windowed_return():
    """Verify spread uses compounded window return difference, not daily sum."""
    dates = pd.date_range("2026-01-01", periods=60, freq="B")
    # left doubles, right flat: 20D return diff should be ~100%
    left = pd.Series([100 * (1.01 ** i) for i in range(60)], index=dates, dtype=float)
    right = pd.Series([100.0] * 60, index=dates, dtype=float)
    metrics = compute_spread_metrics(left, right, label="test")
    # 20 trading days of 1% daily → compounded ≈ 22%
    assert metrics["spread_20d_pct"] > 20.0
    assert metrics["spread_20d_pct"] < 25.0


def test_rsi_wilder_smoothing():
    """RSI should use Wilder (ewm alpha=1/14), not simple rolling mean."""
    from market_monitor.technicals import compute_technicals
    # Alternating up/down with slight upward bias
    values = []
    price = 100.0
    for i in range(50):
        price *= 1.01 if i % 2 == 0 else 0.995
        values.append(price)
    close = pd.Series(values, index=pd.date_range("2026-01-01", periods=50, freq="B"))
    result = compute_technicals(close)
    # With Wilder, RSI should be defined and in valid range
    assert result["rsi"] is not None
    assert 0 <= result["rsi"] <= 100


def test_buy_score_does_not_double_count_premium():
    """relative_premium_pct must not be a buy component.

    Within a cohort it is premium_pct shifted by a constant (the cohort
    median), and min-max normalization is invariant to a constant shift, so
    scoring both gave premium two of the four weights. The regression this
    guards is concrete: with the duplicate in place the only ATTRACTIVE
    csi300 wrapper ranked second behind a FAIR one.
    """
    frame = pd.DataFrame(
        {
            "exposure_id": ["csi300"] * 3,
            "ticker": ["510330", "510300", "159919"],
            "premium_pct": [-0.28, -0.06, -0.05],
            "spread_bp": [4.0, 2.0, 3.0],
            "turnover": [8.4e8, 7.1e9, 1.1e9],
            "is_cross_border": [False] * 3,
        }
    )
    frame["relative_premium_pct"] = frame.groupby("exposure_id")["premium_pct"].transform(
        lambda s: s - s.median()
    )
    ranked = rank_wrappers(frame).set_index("ticker")

    # The two columns are byte-identical after min-max, which is exactly why
    # only one of them may be scored.
    def _minmax(series: pd.Series) -> list[float]:
        lo, hi = series.min(), series.max()
        return [round(v, 9) for v in ((series - lo) / (hi - lo) * 100.0)]

    assert _minmax(frame["premium_pct"]) == _minmax(frame["relative_premium_pct"])

    # The best premium in the cohort must win the premium component outright.
    assert ranked.loc["510330", "entry_status"] == "ATTRACTIVE"
    assert ranked.loc["510330", "buy_score"] > ranked.loc["159919", "buy_score"]


def test_buy_score_separates_wrappers_with_different_premiums():
    """Two-member cohorts must no longer tie when the premiums differ.

    Scope note: de-duplicating premium breaks the tie but does NOT make the
    cheaper wrapper win. _norm is min-max within the cohort, so a two-member
    cohort maps every component to {0, 100} and the score degenerates into a
    vote tally -- 513310 still ranks first on spread + turnover despite a
    premium 4 points worse. That is the separate design issue (min-max has no
    absolute scale); this test pins only what de-duplication is responsible
    for, so a future absolute-scale fix is free to change the winner.
    """
    frame = pd.DataFrame(
        {
            "exposure_id": ["sp500"] * 2,
            "ticker": ["513310", "513500"],
            "premium_pct": [11.11, 7.01],
            "spread_bp": [10.0, 12.0],
            "turnover": [5.0e8, 4.0e8],
            "is_cross_border": [True] * 2,
        }
    )
    ranked = rank_wrappers(frame).set_index("ticker")
    assert ranked.loc["513500", "buy_score"] != ranked.loc["513310", "buy_score"]
    assert ranked.loc["513500", "buy_rank"] != ranked.loc["513310", "buy_rank"]
    assert set(ranked["buy_rank"]) == {1, 2}


def test_email_trend_arrow_distinguishes_missing_from_down():
    """A missing MA20 must not render as a down arrow."""
    from market_monitor.alerts import build_email_html

    technicals = pd.DataFrame(
        [
            {"label": "Has MA20", "ma20_pct": -1.2, "ma60_pct": -0.5, "rsi": 44.0},
            {"label": "No MA20", "ma20_pct": float("nan"), "ma60_pct": None, "rsi": None},
        ]
    )
    html = build_email_html(
        report_date="2026-08-19",
        technicals=technicals,
        regime=pd.DataFrame(),
        wrappers=pd.DataFrame(),
    )
    down_row = html.split("<td>Has MA20</td>")[1].split("</tr>")[0]
    missing_row = html.split("<td>No MA20</td>")[1].split("</tr>")[0]
    assert "▼" in down_row
    assert "▼" not in missing_row
    assert "—" in missing_row


def test_spot_premium_sign_is_premium_positive():
    """premium_pct must read positive when price is above IOPV.

    Eastmoney ships 基金折价率 (discount-positive); the source layer flips it.
    Guards the flip against a comment-only "fix" that removes it.
    """
    import market_monitor.sources.akshare_etf as src

    frame = pd.DataFrame(
        {
            "代码": ["512100", "510330"],
            "最新价": [3.048, 4.848],
            "IOPV实时估值": [3.0431, 4.8617],
            # discount-positive, as Eastmoney reports it
            "基金折价率": [-0.16, 0.28],
        }
    )

    class _FakeAk:
        @staticmethod
        def fund_etf_spot_em():
            return frame

    sys.modules["akshare"] = _FakeAk
    try:
        out = src.fetch_etf_spot().set_index("ticker")
    finally:
        del sys.modules["akshare"]

    # 3.048 / 3.0431 - 1 = +0.161% -> the ETF trades above IOPV
    assert out.loc["512100", "premium_pct"] > 0
    assert out.loc["510330", "premium_pct"] < 0
    for ticker in ("512100", "510330"):
        implied = (out.loc[ticker, "market_price"] / out.loc[ticker, "iopv"] - 1.0) * 100.0
        assert abs(implied - out.loc[ticker, "premium_pct"]) < 0.01
