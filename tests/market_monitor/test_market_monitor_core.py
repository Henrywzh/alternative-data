"""Offline unit tests for market_monitor derived-signal math."""

import json
import sys
import warnings
from pathlib import Path

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
    # a (best) ranks 1; the fully-missing c is unmeasured, not worst, so it
    # lands on the out-of-band 99 rather than being scored 0 and ranked last.
    assert ranked.loc[ranked["fund_id"] == "a", "buy_rank"].iloc[0] == 1
    assert ranked.loc[ranked["fund_id"] == "b", "buy_rank"].iloc[0] == 2
    assert ranked.loc[ranked["fund_id"] == "c", "buy_rank"].iloc[0] == 99
    assert pd.isna(ranked.loc[ranked["fund_id"] == "c", "buy_score"].iloc[0])


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
    # b has a premium and only lacks the (much smaller) spread term, so its
    # entry cost is still known to within a few bp; c is priced on both and is
    # genuinely worse. b must not collapse (the old NaN-propagation bug).
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

    # The cohort's only ATTRACTIVE wrapper must rank first outright, even
    # though it has the widest spread and the lowest turnover of the three.
    assert ranked.loc["510330", "entry_status"] == "ATTRACTIVE"
    assert ranked.loc["510330", "buy_rank"] == 1
    assert ranked.loc["510330", "buy_score"] > ranked.loc["510300", "buy_score"]
    assert ranked.loc["510330", "liquidity_score"] < ranked.loc["510300", "liquidity_score"]


def test_buy_score_separates_wrappers_with_different_premiums():
    """The cheaper wrapper must win, by the size of the gap, not a vote.

    Under min-max-within-cohort these two tied at exactly 50.0 and shared
    rank 1, four percentage points of premium apart: a two-member cohort maps
    every component to {0, 100}, so the score counted components won instead
    of pricing them. Both are still AVOID -- the point is that 7.01% is
    unambiguously the cheaper way in, and the ranking has to say so.
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
    assert ranked.loc["513500", "buy_rank"] == 1
    assert ranked.loc["513310", "buy_rank"] == 2
    assert ranked.loc["513500", "buy_score"] > ranked.loc["513310", "buy_score"]
    # Cross-border bands: both are past the AVOID edge, so both score under 25.
    assert ranked.loc["513500", "buy_score"] < 25.0
    # 513310 has the better spread and 20x the turnover; neither may rescue a
    # premium 410bp worse.
    assert ranked.loc["513310", "liquidity_score"] > ranked.loc["513500", "liquidity_score"]


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


@pytest.mark.parametrize("is_cross_border", [False, True])
def test_buy_score_and_entry_status_cannot_disagree(is_cross_border):
    """The score's band edges are entry_status's thresholds, by construction.

    75 / 50 / 25 are the ATTRACTIVE|FAIR, FAIR|EXPENSIVE and EXPENSIVE|AVOID
    boundaries. Pinning this is the reason the score is on an absolute scale
    at all: under min-max the score was cohort-relative, so a wrapper labelled
    AVOID could outscore one labelled ATTRACTIVE in a different cohort and the
    two readings on the same row told different stories.
    """
    floors = {"ATTRACTIVE": 75.0, "FAIR": 50.0, "EXPENSIVE": 25.0, "AVOID": 0.0}
    ceilings = {"ATTRACTIVE": 100.0, "FAIR": 75.0, "EXPENSIVE": 50.0, "AVOID": 25.0}
    premiums = [-3.0, -0.5, -0.11, -0.1, 0.0, 0.19, 0.2, 0.5, 1.0, 1.49, 1.5, 3.9, 4.0, 6.0, 11.0]
    frame = pd.DataFrame(
        {
            "exposure_id": ["cohort"] * len(premiums),
            "ticker": [str(i) for i in range(len(premiums))],
            "premium_pct": premiums,
            # zero spread so the cost is the premium exactly, which is what
            # entry_status reads -- any spread would legitimately shift the
            # score a fraction of a bp across a boundary.
            "spread_bp": [0.0] * len(premiums),
            "turnover": [1e9] * len(premiums),
            "is_cross_border": [is_cross_border] * len(premiums),
        }
    )
    ranked = rank_wrappers(frame)
    for _, row in ranked.iterrows():
        status = row["entry_status"]
        assert floors[status] <= row["buy_score"] <= ceilings[status], (
            f"{status} wrapper at premium {row['premium_pct']}% scored "
            f"{row['buy_score']}, outside [{floors[status]}, {ceilings[status]}]"
        )
    # And the score must be strictly monotone in cost across the whole range.
    ordered = ranked.sort_values("premium_pct")["buy_score"].tolist()
    assert ordered == sorted(ordered, reverse=True)


def test_liquidity_saturates_and_is_not_blended_into_buy_score():
    """Turnover must not buy its way past a worse entry cost."""
    frame = pd.DataFrame(
        {
            "exposure_id": ["cohort"] * 2,
            "ticker": ["cheap_thin", "dear_deep"],
            "premium_pct": [-0.25, 0.30],
            "spread_bp": [6.0, 1.0],
            "turnover": [3.0e8, 2.0e10],  # 60x the turnover
            "is_cross_border": [False] * 2,
        }
    )
    ranked = rank_wrappers(frame).set_index("ticker")
    assert ranked.loc["cheap_thin", "buy_rank"] == 1
    assert ranked.loc["dear_deep", "liquidity_score"] > ranked.loc["cheap_thin", "liquidity_score"]

    # Saturation: past ~1e9 CNY/day, another decade of turnover is worth
    # almost nothing, because it no longer changes what an entry costs.
    thin = pd.DataFrame({"exposure_id": ["c"], "ticker": ["t"], "premium_pct": [0.0], "turnover": [1e7], "is_cross_border": [False]})
    ample = thin.assign(turnover=[1e9])
    more = thin.assign(turnover=[1e10])
    score = lambda f: rank_wrappers(f)["liquidity_score"].iloc[0]
    assert score(ample) - score(thin) > 40.0
    assert score(more) - score(ample) < 10.0


def test_hold_score_is_absolute_not_cohort_relative():
    """A cohort where every fund charges the same must not fabricate a spread.

    Under min-max, three CSI 300 wrappers all charging 0.50% hit
    nunique() == 1, every one scored 50 on fee, and the remaining differences
    got stretched across the full 0-100 range -- a 1.4x size difference became
    a 58-point score gap (21.7 vs 80.3). On an absolute scale identical fees
    score identically because they *are* identical, and near-identical funds
    land near each other.
    """
    from market_monitor.ranking import _hold_quality_score

    frame = pd.DataFrame(
        {
            "exposure_id": ["csi300"] * 3,
            "ticker": ["510300", "510330", "159919"],
            "management_fee": [0.005] * 3,
            "aum_proxy": [107.2e9, 41.4e9, 29.7e9],
            "fund_age_days": [5196, 4985, 5217],
        }
    )
    scores = _hold_quality_score(frame)
    assert scores.max() - scores.min() < 10.0, f"near-identical funds spread {scores.tolist()}"

    # And a uniformly expensive cohort must score low, which a within-cohort
    # normalisation can never express.
    dear = frame.assign(management_fee=[0.015] * 3)
    assert _hold_quality_score(dear).max() < scores.min()


def test_hold_score_prices_a_fee_advantage_over_size():
    """512500 charges a third of its peers' fee and was ranked last for it."""
    frame = pd.DataFrame(
        {
            "exposure_id": ["csi500"] * 3,
            "ticker": ["512500", "510500", "159922"],
            "management_fee": [0.0015, 0.005, 0.005],
            "aum_proxy": [7.9e9, 40.1e9, 8.5e9],  # 512500 is the smallest
            "fund_age_days": [4125, 4928, 4928],
            "premium_pct": [-0.16, 0.24, 0.10],
            "is_cross_border": [False] * 3,
        }
    )
    ranked = rank_wrappers(frame).set_index("ticker")
    assert ranked.loc["512500", "hold_rank"] == 1, ranked["hold_score"].to_dict()


def test_prune_runs_keeps_the_newest_and_reports_what_it_dropped(tmp_path):
    from market_monitor.storage import prune_runs, load_lineage_history, save_normalized

    root = tmp_path / "normalized"
    for day in range(1, 8):
        run_id = f"2026081{day}T000000-{day:08x}"
        target = root / "ds" / run_id
        target.mkdir(parents=True)
        pd.DataFrame({"a": [day]}).to_parquet(target / "ds.parquet", index=False)
        (target / "lineage.json").write_text(
            json.dumps({"run_id": run_id, "run_scope": "full", "records": day}), encoding="utf-8"
        )

    dropped = prune_runs(root, "ds", keep=3)
    kept = sorted(p.name for p in (root / "ds").iterdir())
    assert len(kept) == 3
    assert len(dropped) == 4
    # Newest by run_id, which embeds the timestamp -- not by mtime, which is
    # identical across every file of a fresh git checkout.
    assert kept == sorted(kept, key=str)[-3:]
    assert all(name < min(kept) for name in dropped)


def test_lineage_history_is_newest_first_and_scope_filtered(tmp_path):
    from market_monitor.storage import load_lineage_history

    root = tmp_path / "normalized"
    for run_id, scope in (
        ("20260819T010000-aaaa", "full"),
        ("20260819T020000-bbbb", "partial"),
        ("20260819T030000-cccc", "full"),
    ):
        target = root / "ds" / run_id
        target.mkdir(parents=True)
        (target / "lineage.json").write_text(
            json.dumps({"run_id": run_id, "run_scope": scope}), encoding="utf-8"
        )
    history = load_lineage_history(root, "ds", scope="full", limit=2)
    assert [h["run_id"] for h in history] == ["20260819T030000-cccc", "20260819T010000-aaaa"]


def test_lineage_measured_fields_survive_caller_metadata(tmp_path, monkeypatch):
    """Caller metadata must not overwrite the row count or digest."""
    import market_monitor.storage as storage

    monkeypatch.setattr(storage, "NORMALIZED_DIR", tmp_path)
    frame = pd.DataFrame({"a": [1, 2, 3]})
    info = storage.save_normalized(
        "ds", frame, metadata={"records": 999, "sha256": "not-a-digest", "type": "normalized"}
    )
    lineage = json.loads(Path(info["lineage"]).read_text(encoding="utf-8"))
    assert lineage["records"] == 3
    assert lineage["sha256"] != "not-a-digest"
    assert lineage["type"] == "normalized"


def _shipped_market_artifact():
    """The built artifact, or None in a checkout that has not built one."""
    path = (
        Path(__file__).resolve().parents[2]
        / "apps" / "asia-markets-dashboard" / ".generated" / "market-monitor-artifact.json"
    )
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_builder():
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    path = root / "apps" / "asia-markets-dashboard" / "scripts" / "build_market_monitor_artifact.py"
    spec = importlib.util.spec_from_file_location("_mm_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_coverage_regression_catches_the_2026_08_19_history_collapse():
    """The exact run pair that shipped a 38% shorter history as Healthy.

    At 11:25 the run held 5,541 rows over 7 exposures back to 2023-01-03; at
    12:28 it held 3,416 back to 2024-08-19. Both were labelled run_scope
    "full" -- the label is derived from the CLI arguments, so it reports what
    the run meant to fetch -- and load_latest picked the shorter one purely
    because its run_id sorts later.
    """
    builder = _load_builder()
    previous = {
        "rows_by_exposure": {
            "csi1000": 879, "csi300": 879, "csi500": 879, "dividend": 879,
            "growth": 879, "hstech": 645, "sp500": 501,
        },
        "missing_exposures": [],
    }
    current = {
        "rows_by_exposure": {
            "csi1000": 485, "csi300": 485, "csi500": 485, "dividend": 485,
            "growth": 485, "hstech": 490, "sp500": 501,
        },
        "missing_exposures": [],
    }
    notes = builder.coverage_regressions(current, previous)
    assert len(notes) == 6, notes
    assert any("csi300 485 rows vs 879" in note for note in notes)
    # sp500 was unchanged and hstech dropped only 24%... it did drop, so it is
    # reported; the one exposure that held steady must not be.
    assert not any(note.startswith("sp500") for note in notes)


def test_coverage_regression_tolerates_calendar_wobble_and_first_runs():
    builder = _load_builder()
    steady = {"rows_by_exposure": {"csi300": 879}, "missing_exposures": []}
    assert builder.coverage_regressions(steady, steady) == []
    # A holiday-shortened refresh is not a regression.
    assert builder.coverage_regressions(
        {"rows_by_exposure": {"csi300": 875}, "missing_exposures": []}, steady
    ) == []
    # Nothing to compare against yet.
    assert builder.coverage_regressions(steady, {}) == []
    # A vanished exposure is reported once, not twice.
    gone = {"rows_by_exposure": {}, "missing_exposures": ["csi300"]}
    assert builder.coverage_regressions(gone, steady) == ["no rows for csi300"]


def test_email_escapes_provider_supplied_text():
    """fund_name arrives from Eastmoney and goes straight into markup."""
    from market_monitor.alerts import build_email_html

    wrappers = pd.DataFrame(
        [
            {
                "ticker": "510300",
                "fund_name": "<script>alert(1)</script>华泰柏瑞",
                "premium_pct": -0.06,
                "relative_premium_pct": 0.0,
                "entry_status": "FAIR",
                "peer_rank": 1,
                "hold_rank": 1,
            }
        ]
    )
    html_out = build_email_html(
        report_date="2026-08-19",
        technicals=pd.DataFrame(),
        regime=pd.DataFrame(),
        wrappers=wrappers,
    )
    assert "<script>" not in html_out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;华泰柏瑞" in html_out


def test_merge_premium_does_not_mutate_the_caller_frame():
    """The pipeline hands merge_premium the same object it wrote to raw."""
    from market_monitor.metadata import build_metadata_frame
    from market_monitor.wrapper import merge_premium

    spot = pd.DataFrame(
        {
            "ticker": ["510300", "159919"],  # unpadded, as Eastmoney sends them
            "premium_pct": [-0.06, -0.05],
            "markcap": [1.07e11, 2.99e10],
            "turnover": [7.1e9, 1.1e9],
        }
    )
    snapshot = spot.copy(deep=True)
    merge_premium(spot, build_metadata_frame())
    pd.testing.assert_frame_equal(spot, snapshot)


def test_merge_premium_resolves_size_without_pandas_deprecation():
    """The registry's aum column is None for every fund.

    combine_first against an all-None column raised the empty-entry
    concatenation FutureWarning on every single production run.
    """
    from market_monitor.metadata import build_metadata_frame
    from market_monitor.wrapper import merge_premium

    spot = pd.DataFrame({"ticker": ["510300"], "premium_pct": [-0.06], "markcap": [1.07e11]})
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        merged = merge_premium(spot, build_metadata_frame())
    row = merged.loc[merged["ticker"] == "510300"].iloc[0]
    assert row["aum_proxy"] == 1.07e11
    # markcap is not carried through: it and aum_proxy were the same number
    # under two names, which is how "AUM" came to label a market-cap proxy.
    assert "markcap" not in merged.columns


def test_index_fetch_rejects_a_symbol_it_would_mangle():
    """_coerce_symbol zero-pads, turning "SPX" into "000SPX"."""
    from market_monitor.sources import akshare_etf

    with pytest.raises(ValueError, match="no Sina mapping"):
        akshare_etf.fetch_index_daily("SPX")


def test_fetch_errors_reach_lineage_not_just_stdout(monkeypatch, capsys):
    """A source that fails must leave a record, not only a printed line."""
    from market_monitor import pipeline as pl

    def _index_boom(index_id, start_date=None, end_date=None):
        raise RuntimeError("sina timed out")

    def _etf_boom(ticker, start_date=None, end_date=None):
        raise RuntimeError("etf endpoint refused")

    # Both fetch legs are stubbed. Leaving the ETF loop live made the test
    # depend on whether the worktree happened to hold a local capture: with
    # one it never raised, without one it raised a blocked-socket error whose
    # message is not the one under test.
    monkeypatch.setattr(pl.akshare_etf, "fetch_index_daily", _index_boom)
    monkeypatch.setattr(pl.akshare_etf, "fetch_etf_daily", _etf_boom)
    monkeypatch.setattr(pl.akshare_etf, "fetch_etf_spot", lambda: pd.DataFrame())
    monkeypatch.setattr(pl.yfinance, "fetch_daily", lambda *a, **k: pd.DataFrame())
    # The fee reconciliation is 26 live calls; unstubbed it spends 20s hitting
    # the offline socket guard for something this test is not about.
    monkeypatch.setattr(
        pl.eastmoney_fee, "fetch_fund_fees",
        lambda fund_id: {"management_fee": None, "custody_fee": None},
    )

    raw = pl.fetch_all_raw(limit_exposures=("csi300", "csi500"))
    errors = raw["_fetch_errors"]

    index_errors = [err for err in errors if "sina timed out" in err["error"]]
    assert {err["exposure_id"] for err in index_errors} == {"csi300", "csi500"}

    # The ETF loop only printed its failures before; a dashboard cannot show
    # a missing wrapper it was never told about.
    etf_errors = [err for err in errors if "etf endpoint refused" in err["error"]]
    assert etf_errors, "ETF fetch failures must reach lineage, not only stdout"
    assert {err["exposure_id"] for err in etf_errors} == {"csi300", "csi500"}


def test_every_exposure_declares_where_its_prices_come_from():
    """Source ownership is declared per exposure, not inferred by exclusion.

    Source health twice encoded "everything except sp500 is Sina": once for
    S&P 500 (fixed in cd09fd40) and again when Nasdaq 100 arrived on yfinance,
    which credited Sina with 501 rows of an index it does not serve while Yahoo
    reported 501 rows for the two it does. A per-exposure declaration cannot
    drift: a new index has to state its source or this test fails.
    """
    from market_monitor.config import EXPOSURES, exposures_by_price_source

    sina = exposures_by_price_source("sina")
    sina_hk = exposures_by_price_source("sina_hk")
    yahoo = exposures_by_price_source("yfinance")
    assert len(sina) + len(sina_hk) + len(yahoo) == len(EXPOSURES), (
        "an exposure declares an unknown price_source"
    )
    assert set(sina).isdisjoint(yahoo)
    # The US indexes are the ones yfinance serves, and both need a ticker.
    from market_monitor.pipeline import YFINANCE_SYMBOLS

    assert set(yahoo) == set(YFINANCE_SYMBOLS), "a yfinance exposure has no ticker, or vice versa"


def test_source_health_attributes_rows_to_the_provider_that_served_them():
    builder = _load_builder()
    from market_monitor.config import exposures_by_price_source

    sina = set(exposures_by_price_source("sina"))
    sina_hk = set(exposures_by_price_source("sina_hk"))
    yahoo = set(exposures_by_price_source("yfinance"))
    rows_by_exposure = {"csi300": 484, "hsi": 490, "hstech": 490, "ndx": 501, "sp500": 501}
    sina_rows = sum(n for e, n in rows_by_exposure.items() if e in sina)
    sina_hk_rows = sum(n for e, n in rows_by_exposure.items() if e in sina_hk)
    yahoo_rows = sum(n for e, n in rows_by_exposure.items() if e in yahoo)
    # Nasdaq 100 belongs to Yahoo; counting it under Sina is the regression.
    assert "ndx" in yahoo and "ndx" not in sina
    assert yahoo_rows == 1002
    # Hang Seng comes off Sina's separate HK endpoint, not the mainland one.
    assert {"hsi", "hstech"} <= sina_hk
    assert sina_rows + sina_hk_rows + yahoo_rows == sum(rows_by_exposure.values())
    assert builder is not None


def test_premium_history_accumulates_instead_of_being_rebuilt(tmp_path, monkeypatch):
    """Each run must carry the whole series forward, not recompute it.

    It was rebuilt from data/raw/etf_spot every run. That directory is
    gitignored, so CI starts with none and writes exactly one, and prune_runs
    caps local runs at five -- the shipped artifact held one observation per
    fund on a single date, behind a chart captioned as a growing history.
    """
    import market_monitor.pipeline as pl
    import market_monitor.storage as storage

    monkeypatch.setattr(storage, "DERIVED_DIR", tmp_path / "derived")
    monkeypatch.setattr(pl, "RAW_DIR", tmp_path / "raw")  # no raw snapshots at all

    meta = pd.DataFrame(
        {
            "ticker": ["510300.SH", "159919.SZ"],
            "fund_id": ["510300", "159919"],
            "exposure_id": ["csi300", "csi300"],
        }
    )

    def _spot(premium):
        return pd.DataFrame({"ticker": ["510300", "159919"], "premium_pct": premium,
                             "spread_bp": [2.0, 2.1], "market_price": [4.65, 4.85]})

    day1 = pl._build_premium_history(meta, _spot([-0.06, -0.05]), "2026-08-19")
    assert len(day1) == 2
    storage.save_derived("premium_history", day1, metadata={"run_scope": "full"})

    day2 = pl._build_premium_history(meta, _spot([0.11, 0.09]), "2026-08-20")
    assert sorted(day2["date"].unique()) == ["2026-08-19", "2026-08-20"]
    assert len(day2) == 4, "the previous day's observations were dropped"
    storage.save_derived("premium_history", day2, metadata={"run_scope": "full"})

    # A second run on the same day supersedes rather than duplicates.
    day2_again = pl._build_premium_history(meta, _spot([0.20, 0.18]), "2026-08-20")
    assert len(day2_again) == 4
    latest = day2_again[day2_again["date"].eq("2026-08-20")].set_index("ticker")["premium_pct"]
    assert latest.loc["510300"] == 0.20


def test_avg_premium_reports_how_many_days_it_averaged():
    """The card said 30D whatever the answer was."""
    builder = _load_builder()
    import inspect

    source = inspect.getsource(builder.build_artifact)
    assert "avg_premium_days" in source, "the window size must reach the renderer"

    app_source = (
        Path(__file__).resolve().parents[2]
        / "apps" / "asia-markets-streamlit" / "app.py"
    ).read_text(encoding="utf-8")
    assert "Premium (today)" in app_source
    assert 'f"Avg premium {premium_days}D"' in app_source


def test_chart_series_ships_a_date_window_not_a_row_count():
    """A row-count slice makes history depend on how many sessions a venue ran.

    The Sina and Yahoo calendars differ by ~17 sessions a year, so `.tail(250)`
    handed the US exposures a shorter calendar window than the CN/HK ones and
    put two different amounts of history on one shared x-axis.
    """
    builder = _load_builder()
    dates = pd.bdate_range("2020-01-01", "2026-08-19")
    frame = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "exposure_id": "csi300",
            "close": np.linspace(100.0, 200.0, len(dates)),
        }
    )

    rows = builder._chart_series(frame, "exposure_id", "close", years=2)

    assert rows, "a populated series must produce rows"
    assert rows[0]["date"] >= "2024-08-19"
    assert rows[-1]["date"] == "2026-08-19"
    # Two calendar years of business days, not a fixed 250.
    assert 480 <= len(rows) <= 530


def test_chart_series_carries_only_what_a_chart_reads():
    """Every unread field is paid for in every row of every daily artifact."""
    builder = _load_builder()
    frame = pd.DataFrame(
        {
            "date": ["2026-08-18", "2026-08-19"],
            "exposure_id": ["csi300", "csi300"],
            "close": [1.0, 2.0],
            "open": [1.0, 2.0],
            "high": [1.0, 2.0],
            "low": [1.0, 2.0],
            "volume": [1, 2],
            "amount": [1, 2],
            "index_id": ["000300.SH", "000300.SH"],
        }
    )

    rows = builder._chart_series(frame, "exposure_id", "close")

    assert set(rows[0]) == {"date", "exposure_id", "close"}


def test_etf_prices_key_on_the_same_id_as_wrapper_metrics():
    """The per-index "all ETFs" chart joins these two datasets by ticker.

    The price series carried the exchange-qualified `159919.SZ` while wrapper
    metrics carried the bare `159919`, so the join matched nothing and the
    chart drew no lines without ever raising.
    """
    builder = _load_builder()
    prices = pd.DataFrame(
        {
            "date": ["2026-08-19", "2026-08-19"],
            "fund_id": ["159919", "510300"],
            "ticker": ["159919.SZ", "510300.SH"],
            "close": [4.1, 3.9],
        }
    )

    rows = builder._chart_series(prices, "fund_id", "close", id_as="ticker")

    assert {row["ticker"] for row in rows} == {"159919", "510300"}


def test_registry_is_reconciled_against_the_exchanges_own_fund_name():
    """513310 sat in the S&P 500 cohort as "景顺长城标普500ETF(QDII)".

    It is 中韩半导体ETF华泰柏瑞, a China/Korea semiconductor fund: +271% over
    two years against the index's +38%, correlating 0.13 with what it was
    filed under. Nothing detected it because the universe is hand-typed and
    the only check was someone looking at a chart.
    """
    from market_monitor.metadata import reconcile_registry_names

    metadata = pd.DataFrame(
        [
            {"exposure_id": "sp500", "fund_id": "513500", "fund_name": "博时标普500ETF(QDII)"},
            {"exposure_id": "sp500", "fund_id": "513310", "fund_name": "景顺长城标普500ETF(QDII)"},
            {"exposure_id": "csi300", "fund_id": "510300", "fund_name": "华泰柏瑞沪深300ETF"},
        ]
    )
    spot = pd.DataFrame(
        [
            {"ticker": "513500", "fund_name": "标普500ETF博时"},
            {"ticker": "513310", "fund_name": "中韩半导体ETF华泰柏瑞"},
            {"ticker": "510300", "fund_name": "沪深300ETF华泰柏瑞"},
        ]
    )

    problems = reconcile_registry_names(metadata, spot)

    assert [p["fund_id"] for p in problems] == ["513310"]
    assert problems[0]["exchange_name"] == "中韩半导体ETF华泰柏瑞"
    # Word order differs between our naming and the venue's; that is not a
    # contradiction and must not be reported as one.
    assert all(p["fund_id"] != "510300" for p in problems)


def test_hang_seng_cohort_does_not_swallow_hang_seng_tech():
    """恒生科技 contains 恒生, so the broad cohort needs the explicit exclusion."""
    from market_monitor.metadata import reconcile_registry_names

    metadata = pd.DataFrame(
        [{"exposure_id": "hsi", "fund_id": "513180", "fund_name": "华夏恒生ETF"}]
    )
    spot = pd.DataFrame([{"ticker": "513180", "fund_name": "恒生科技ETF华夏"}])

    assert reconcile_registry_names(metadata, spot)


def test_every_exposure_has_a_name_token_to_reconcile_against():
    """A new exposure without tokens would be silently exempt from the check.

    Benchmarks are exempt by construction: they have no ETF wrapper, so there
    is no exchange fund name to reconcile against.
    """
    from market_monitor.config import investable_exposures
    from market_monitor.metadata import EXPOSURE_NAME_TOKENS

    missing = [
        spec["exposure_id"]
        for spec in investable_exposures()
        if spec["exposure_id"] not in EXPOSURE_NAME_TOKENS
    ]
    assert not missing, f"no fund-name token declared for {missing}"


def test_shipped_registry_agrees_with_itself():
    """Our own fund_name must carry the token of the exposure it is filed under."""
    from market_monitor.metadata import EXPOSURE_NAME_TOKENS, build_metadata_frame

    frame = build_metadata_frame()
    wrong = [
        (row.exposure_id, row.fund_id, row.fund_name)
        for row in frame.itertuples()
        if not any(token in str(row.fund_name) for token in EXPOSURE_NAME_TOKENS[row.exposure_id])
    ]
    assert not wrong, f"registry names contradict their exposure: {wrong}"


def test_premium_from_nav_prices_the_wrapper_against_its_own_valuation():
    from market_monitor.sources.eastmoney_nav import premium_from_nav

    prices = pd.DataFrame(
        [
            {"date": "2026-08-17", "fund_id": "513500", "close": 2.748},
            {"date": "2026-08-18", "fund_id": "513500", "close": 2.688},
            # No NAV published for this day: an inner join must drop it rather
            # than emit a gap in a series meant to be continuous.
            {"date": "2026-08-19", "fund_id": "513500", "close": 2.642},
        ]
    )
    nav = pd.DataFrame(
        [
            {"fund_id": "513500", "date": "2026-08-17", "nav": 2.4847},
            {"fund_id": "513500", "date": "2026-08-18", "nav": 2.4683},
        ]
    )

    out = premium_from_nav(prices, nav)

    assert out["date"].tolist() == ["2026-08-17", "2026-08-18"]
    assert out["premium_pct"].round(2).tolist() == [10.60, 8.90]
    assert set(out["basis"]) == {"nav"}


def test_premium_from_nav_refuses_a_non_positive_nav():
    """A zero NAV would render as a -100% premium instead of as missing."""
    from market_monitor.sources.eastmoney_nav import premium_from_nav

    prices = pd.DataFrame([{"date": "2026-08-18", "fund_id": "513500", "close": 2.688}])
    nav = pd.DataFrame([{"fund_id": "513500", "date": "2026-08-18", "nav": 0.0}])

    assert premium_from_nav(prices, nav).empty


def test_premium_history_prefers_nav_and_keeps_iopv_for_the_tail(tmp_path, monkeypatch):
    """NAV is the fund's own valuation, so it wins where both describe a day.

    IOPV still carries today and the extra session a QDII lags by, which NAV
    has not published yet.
    """
    from market_monitor import pipeline as pl
    from market_monitor.sources import eastmoney_nav

    meta = pd.DataFrame(
        [{"ticker": "513500.SH", "fund_id": "513500", "exposure_id": "sp500"}]
    )
    prices = pd.DataFrame(
        [
            {"date": "2026-08-17", "fund_id": "513500", "close": 2.748},
            {"date": "2026-08-18", "fund_id": "513500", "close": 2.688},
            {"date": "2026-08-19", "fund_id": "513500", "close": 2.642},
        ]
    )
    spot = pd.DataFrame(
        [{"ticker": "513500", "premium_pct": 99.0, "spread_bp": 3.8, "market_price": 2.642}]
    )

    monkeypatch.setattr(
        eastmoney_nav,
        "fetch_nav_history",
        lambda fund_id, start, end, session=None, pause=0.0: pd.DataFrame(
            [
                {"fund_id": "513500", "date": "2026-08-17", "nav": 2.4847},
                {"fund_id": "513500", "date": "2026-08-18", "nav": 2.4683},
            ]
        ),
    )
    monkeypatch.setattr(pl, "_premium_rows_from_raw_snapshots", lambda tracked: [])
    monkeypatch.setattr(pl, "load_latest_derived", lambda name: None)

    # The snapshot is taken on the 18th, a day NAV has also published, so the
    # two measurements collide there on purpose.
    same_day = pl._build_premium_history(meta, spot, "2026-08-18", prices=prices)
    row = same_day.set_index("date").loc["2026-08-18"]
    assert row["basis"] == "nav", "the fund's own valuation must win over IOPV"
    assert round(float(row["premium_pct"]), 2) == 8.90

    # Taken on the 19th, which NAV has not reached: IOPV holds the tail so the
    # series still ends on the latest session.
    tail = pl._build_premium_history(meta, spot, "2026-08-19", prices=prices)
    by_date = tail.set_index("date")
    assert sorted(by_date.index) == ["2026-08-17", "2026-08-18", "2026-08-19"]
    assert by_date.loc["2026-08-19", "basis"] == "iopv"
    assert by_date.loc["2026-08-18", "basis"] == "nav"


def test_premium_history_only_refetches_the_nav_tail(monkeypatch):
    """A full 2-year backfill is 25 pages per fund; do it once, not daily."""
    from market_monitor import pipeline as pl
    from market_monitor.sources import eastmoney_nav

    meta = pd.DataFrame([{"ticker": "513500.SH", "fund_id": "513500"}])
    prices = pd.DataFrame([{"date": "2026-08-18", "fund_id": "513500", "close": 2.688}])
    previous = pd.DataFrame(
        [
            {"date": "2026-08-17", "ticker": "513500", "fund_id": "513500",
             "premium_pct": 10.6, "spread_bp": float("nan"),
             "market_price": float("nan"), "basis": "nav"},
        ]
    )

    windows: list[str] = []

    def _record(fund_id, start, end, session=None, pause=0.0):
        windows.append(start)
        return pd.DataFrame(columns=["fund_id", "date", "nav"])

    monkeypatch.setattr(eastmoney_nav, "fetch_nav_history", _record)

    pl._nav_premium_rows(meta, prices, previous)

    assert windows, "the tail must still be refreshed"
    # Ten days back from the newest stored NAV, not two years back.
    assert windows[0] == "2026-08-07"


def test_a_stale_spot_quote_does_not_cost_a_fund_its_premium():
    """513100 sat at 08:30 while its peers refreshed at 10:02.

    Eastmoney stamps each row with its own update time; a fund it has not
    touched since before the open returns an IOPV and no last price. That
    dropped a 20.8bn wrapper to UNAVAILABLE and rank 99 over a stale quote.
    """
    from market_monitor.wrapper import fill_premium_from_last_close

    merged = pd.DataFrame(
        [
            {"exposure_id": "ndx", "ticker": "513100", "fund_id": "513100",
             "market_price": float("nan"), "iopv": 1.9903, "premium_pct": float("nan")},
            {"exposure_id": "ndx", "ticker": "513300", "fund_id": "513300",
             "market_price": 2.697, "iopv": 2.4681, "premium_pct": 9.27},
        ]
    )
    prices = pd.DataFrame(
        [
            {"date": "2026-08-18", "fund_id": "513100", "close": 2.100},
            {"date": "2026-08-19", "fund_id": "513100", "close": 2.185},
            {"date": "2026-08-19", "fund_id": "513300", "close": 2.690},
        ]
    )

    out = fill_premium_from_last_close(merged, prices).set_index("ticker")

    # 2.185 / 1.9903 - 1 = 9.78%
    assert round(float(out.loc["513100", "premium_pct"]), 2) == 9.78
    assert out.loc["513100", "premium_basis"] == "last_close"
    # A row the feed did price is left exactly as the feed priced it.
    assert out.loc["513300", "premium_pct"] == 9.27
    assert out.loc["513300", "premium_basis"] == "live"


def test_a_missing_iopv_is_an_absence_not_a_stale_quote():
    """Without an IOPV there is nothing to price against; stay unavailable."""
    from market_monitor.wrapper import fill_premium_from_last_close

    merged = pd.DataFrame(
        [{"exposure_id": "ndx", "ticker": "513100", "fund_id": "513100",
          "market_price": float("nan"), "iopv": float("nan"), "premium_pct": float("nan")}]
    )
    prices = pd.DataFrame([{"date": "2026-08-19", "fund_id": "513100", "close": 2.185}])

    out = fill_premium_from_last_close(merged, prices)

    assert pd.isna(out.loc[0, "premium_pct"])


def test_every_yfinance_exposure_resolves_to_a_provider_symbol():
    """index_id names the index; yf_symbol names what the provider calls it.

    Deriving one from the other asked yfinance for "SPX", which answers
    "possibly delisted" and an empty frame rather than an error, so the S&P
    500 leg of every US pair would have silently vanished.
    """
    from market_monitor.config import exposures_by_price_source
    from market_monitor.pipeline import YFINANCE_SYMBOLS

    assert set(YFINANCE_SYMBOLS) == set(exposures_by_price_source("yfinance"))
    assert all(str(symbol).strip() for symbol in YFINANCE_SYMBOLS.values())
    assert YFINANCE_SYMBOLS["sp500"] == "^GSPC"
    assert YFINANCE_SYMBOLS["ndx"] == "^NDX"


def test_every_sina_exposure_has_a_sina_symbol():
    """A Sina index with no mapping raises; one with a stale mapping does not.

    Sina answers 200 for 中证800成长 (000967) and 中证800价值 (000969) with
    data that stopped in 2016 and 2019, so those are deliberately absent from
    the universe -- see the benchmark block in config.
    """
    from market_monitor.config import exposures_by_price_source, exposure_by_id
    from market_monitor.sources.akshare_etf import SINA_INDEX_SYMBOLS

    for exposure_id in exposures_by_price_source("sina"):
        index_id = exposure_by_id(exposure_id)["index_id"]
        assert index_id in SINA_INDEX_SYMBOLS, f"{exposure_id} ({index_id}) has no Sina mapping"


def test_benchmarks_do_not_appear_on_the_etf_monitor():
    """A benchmark is one leg of a ratio; there is no ETF wrapper to rank."""
    from market_monitor.config import EXPOSURES, exposure_role, investable_exposures
    from market_monitor.metadata import build_metadata_frame

    investable = {spec["exposure_id"] for spec in investable_exposures()}
    benchmarks = {spec["exposure_id"] for spec in EXPOSURES if exposure_role(spec) == "benchmark"}

    assert investable and benchmarks
    assert not (investable & benchmarks)
    wrapped = set(build_metadata_frame()["exposure_id"].astype(str))
    assert wrapped == investable, "every investable exposure needs wrappers, and only those"


def test_equal_weight_basket_averages_returns_not_prices():
    """The members are quoted on unrelated scales.

    Averaging levels would weight XLK's ~$250 quote about five times XLC's
    ~$50 one; averaging returns is what makes "equal weight" true.
    """
    from market_monitor.relative_strength import equal_weight_basket

    index = pd.bdate_range("2026-01-01", periods=4)
    cheap = pd.Series([10.0, 11.0, 12.1, 13.31], index=index)   # +10% a day
    dear = pd.Series([1000.0, 1000.0, 1000.0, 1000.0], index=index)  # flat

    basket = equal_weight_basket({"cheap": cheap, "dear": dear}, ("cheap", "dear"))

    # Equal weight on returns compounds at +5% a day. A price average would
    # have moved about +0.1%, dominated entirely by the flat 1000 quote.
    assert round(float(basket.iloc[-1] / basket.iloc[0] - 1.0), 6) == round(1.05**2 - 1.0, 6)


def test_pair_ratio_is_rebased_and_carries_its_own_zscore():
    from market_monitor.relative_strength import pair_ratio_frame

    index = pd.bdate_range("2022-01-03", periods=400)
    winner = pd.Series(np.linspace(100.0, 200.0, 400), index=index)
    loser = pd.Series(np.linspace(500.0, 500.0, 400), index=index)

    frame = pair_ratio_frame(
        {"a": winner, "b": loser},
        {"pair_id": "demo", "left": ("a",), "right": ("b",)},
    )

    assert frame["ratio"].iloc[0] == 1.0, "every pair starts at 1.0, whatever the quote scales"
    assert frame["ratio"].iloc[-1] > 1.9
    # 252 observations of baseline before the first z-score exists.
    assert frame["zscore"].iloc[:251].isna().all()
    assert frame["zscore"].iloc[-1] > 0


def test_regime_label_names_both_directions_and_the_gap():
    from market_monitor.relative_strength import regime_label

    assert regime_label(1.5)[0].endswith("numerator")
    assert regime_label(-1.5)[0].endswith("denominator")
    assert regime_label(None) == ("Unavailable", "无数据")


def test_shipped_artifact_carries_pair_ratios_with_a_full_zscore():
    """The five-year store exists so the first day shown already has a z-score.

    With a two-year store the ratio's trailing-year baseline eats the first
    year, and the z-score panel would be blank across half the chart.
    """
    artifact = _shipped_market_artifact()
    if artifact is None:
        pytest.skip("no built market-monitor artifact in this checkout")
    datasets = artifact["snapshot"]["datasets"]

    summary = pd.DataFrame(datasets["relative_pairs"])
    history = pd.DataFrame(datasets["relative_pair_history"])
    assert not summary.empty and not history.empty
    assert set(summary["pair_id"]) == set(history["pair_id"])
    assert history["zscore"].notna().all(), "every plotted day must have a z-score"
    assert {"China", "US", "Cross"} <= set(summary["region"])


def test_shipped_artifact_does_not_ship_benchmark_price_series():
    """Benchmarks feed the ratios server-side; their closes are not charted."""
    artifact = _shipped_market_artifact()
    if artifact is None:
        pytest.skip("no built market-monitor artifact in this checkout")
    from market_monitor.config import EXPOSURES, exposure_role

    benchmarks = {spec["exposure_id"] for spec in EXPOSURES if exposure_role(spec) == "benchmark"}
    shipped = {row["exposure_id"] for row in artifact["snapshot"]["datasets"]["index_price_daily_tail"]}

    assert benchmarks
    assert not (shipped & benchmarks), f"benchmark closes are dead weight in the artifact: {shipped & benchmarks}"


def test_fee_reconciliation_reports_a_registry_that_disagrees_with_the_issuer():
    """16 of 23 hand-typed fees were wrong, mostly a placeholder 0.50%.

    The uniformity was worse than the error: all three CSI 300 wrappers
    carried the same wrong number, so the fee component of the hold score
    could not differentiate them while holding weight 2.0.
    """
    from market_monitor.sources.eastmoney_fee import reconcile_fees

    metadata = pd.DataFrame(
        [
            {"fund_id": "510300", "management_fee": 0.005},
            {"fund_id": "512500", "management_fee": 0.0015},
            {"fund_id": "159655", "management_fee": None},
            {"fund_id": "999999", "management_fee": 0.005},
        ]
    )
    observed = {
        "510300": {"management_fee": 0.0015},
        "512500": {"management_fee": 0.0015},
        "159655": {"management_fee": 0.006},
        # 999999 not answered for: an absence, not a contradiction.
    }

    problems = {p["fund_id"] for p in reconcile_fees(metadata, observed)}

    assert problems == {"510300", "159655"}


def test_hold_score_prices_management_plus_custody():
    """Custody is charged to the same holder and is 5-15bp of real money."""
    from market_monitor.ranking import _hold_quality_score

    frame = pd.DataFrame(
        [
            {"management_fee": 0.0015, "custody_fee": 0.0005},
            {"management_fee": 0.0015, "custody_fee": 0.0015},
        ]
    )

    scores = _hold_quality_score(frame)

    assert scores.iloc[0] > scores.iloc[1], "the cheaper custodian must score better"


@pytest.mark.parametrize(
    ("regime", "premium", "expected"),
    [
        # A Stock Connect wrapper at +1.3% is at its own two-year 95th
        # percentile. On the quota scale that read FAIR.
        ("connect", 1.3, "EXPENSIVE"),
        ("connect", -0.2, "ATTRACTIVE"),
        ("quota", 1.3, "FAIR"),
        ("domestic", 0.3, "EXPENSIVE"),
    ],
)
def test_entry_status_uses_the_regime_the_wrapper_actually_lives_in(regime, premium, expected):
    from market_monitor.ranking import rank_wrappers

    frame = pd.DataFrame(
        [{
            "exposure_id": "x", "fund_id": "1", "ticker": "1", "premium_pct": premium,
            "spread_bp": 10.0, "premium_regime": regime, "is_cross_border": regime != "domestic",
        }]
    )

    assert rank_wrappers(frame)["entry_status"].iloc[0] == expected


def test_a_one_day_nav_misprint_is_not_a_premium_observation():
    """159922 came back at +149.7% on 2024-11-29, between 0.09% and 0.00%.

    A local median rather than a fixed cap, so a fund genuinely trading at a
    sustained 13% premium keeps every one of those days.
    """
    from market_monitor.sources.eastmoney_nav import premium_from_nav

    dates = pd.bdate_range("2024-11-01", periods=30).strftime("%Y-%m-%d")
    prices = pd.DataFrame({"date": dates, "fund_id": "159922", "close": 1.0})
    nav = pd.DataFrame({"fund_id": "159922", "date": dates, "nav": 1.0})
    nav.loc[15, "nav"] = 0.4  # implies +150%

    out = premium_from_nav(prices, nav)

    assert len(out) == 29
    assert out["premium_pct"].abs().max() < 1.0

    # A sustained high premium survives.
    sustained = pd.DataFrame({"date": dates, "fund_id": "513500", "close": 1.13})
    sustained_nav = pd.DataFrame({"fund_id": "513500", "date": dates, "nav": 1.0})
    kept = premium_from_nav(sustained, sustained_nav)
    assert len(kept) == 30
    assert round(float(kept["premium_pct"].iloc[0]), 1) == 13.0


def test_fee_fetch_cannot_stall_the_run(monkeypatch):
    """A reconciliation check must not be able to block what it checks.

    akshare's fund_fee_em exposes no timeout, so a connection the server holds
    open blocks forever. Twenty-one minutes of a daily run were spent inside
    one such call before this bound existed.
    """
    import time as _time

    from market_monitor import pipeline as pl
    from market_monitor.sources import eastmoney_fee

    calls: list[str] = []

    def _slow(fund_id):
        calls.append(fund_id)
        # Simulate the budget being consumed without actually sleeping.
        monkeypatch.setattr(pl.time, "monotonic", lambda: 1e9)
        return {"management_fee": 0.005, "custody_fee": 0.001}

    monkeypatch.setattr(eastmoney_fee, "fetch_fund_fees", _slow)
    monkeypatch.setattr(pl, "load_latest_derived", lambda name: None)
    monkeypatch.setattr(pl.time, "monotonic", _time.monotonic)

    meta = pd.DataFrame([{"fund_id": f"{i:06d}"} for i in range(10)])
    schedule = pl._published_fee_schedule(meta)

    assert len(calls) == 1, "the budget must stop the loop, not merely slow it"
    assert len(schedule) == 1


def test_fees_are_not_refetched_every_day(monkeypatch):
    """A published fee changes on an announcement, not daily."""
    from datetime import date as _date

    from market_monitor import pipeline as pl
    from market_monitor.sources import eastmoney_fee

    calls: list[str] = []
    monkeypatch.setattr(
        eastmoney_fee, "fetch_fund_fees",
        lambda fund_id: (calls.append(fund_id), {"management_fee": 0.005, "custody_fee": 0.001})[1],
    )
    today = _date.today().strftime("%Y-%m-%d")
    cached = pd.DataFrame(
        [
            {"fund_id": "510300", "management_fee": 0.0015, "custody_fee": 0.0005, "fetched_at": today},
            {"fund_id": "510330", "management_fee": 0.0015, "custody_fee": 0.0005, "fetched_at": "2020-01-01"},
        ]
    )
    monkeypatch.setattr(pl, "load_latest_derived", lambda name: cached)

    meta = pd.DataFrame([{"fund_id": "510300"}, {"fund_id": "510330"}])
    schedule = pl._published_fee_schedule(meta)

    assert calls == ["510330"], "only the stale entry should be refetched"
    assert schedule["510300"]["management_fee"] == 0.0015


def test_a_failed_fee_fetch_keeps_the_cached_fee(monkeypatch):
    """Losing a fee to a bad network call would score the fund as unmeasured."""
    from market_monitor import pipeline as pl
    from market_monitor.sources import eastmoney_fee

    monkeypatch.setattr(
        eastmoney_fee, "fetch_fund_fees",
        lambda fund_id: {"management_fee": None, "custody_fee": None},
    )
    cached = pd.DataFrame(
        [{"fund_id": "510300", "management_fee": 0.0015, "custody_fee": 0.0005, "fetched_at": "2020-01-01"}]
    )
    monkeypatch.setattr(pl, "load_latest_derived", lambda name: cached)

    schedule = pl._published_fee_schedule(pd.DataFrame([{"fund_id": "510300"}]))

    assert schedule["510300"]["management_fee"] == 0.0015
