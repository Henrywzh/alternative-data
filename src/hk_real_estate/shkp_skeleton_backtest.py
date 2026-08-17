"""Whole-company skeleton historical backtest (Tier 2, step 3).

Replays the frozen residential engine (lag kernel x margin) on historical
fiscal years FY2017-FY2025 and adds a point-in-time non-residential run-rate
(3-year rolling mean of actual underlying minus HK development profit, using
only data available before the target year).

Margin handling (2026-08-09, v2): the default is now the ``vintage``
launch-cohort calibration (margin from ``coverage_start`` year, a retrospective
for land-cost vintage) which fixes the static-bucket under-estimate of the
2017-2022 high-margin regime.  The legacy static bucket (calibrated to the
FY26/27 low-margin mix) remains available via ``margin_mode="bucket"``.
Attribute the residual error with ``run-shkp-skeleton-margin-decomposition``.
"""

from __future__ import annotations

from typing import Any
import uuid

import pandas as pd

from .storage import load_latest_normalized, save_normalized_dataset


BACKTEST_DATASET = "shkp_skeleton_historical_backtest"
SHARES_MILLION = 2896.0


def _bucket_margin(asp: float | None) -> float:
    if asp is None:
        return 0.295
    if asp >= 15_000_000:
        return 0.375
    if asp >= 10_000_000:
        return 0.295
    return 0.225


def _vintage_margin(year: int | None) -> float:
    """Launch-cohort margin calibrated to the realised HK dev-margin curve.

    Metrics delivered in FY2018-2022 (39-45%) came from LOW land-cost
    launches around FY2014-2019; margins collapsed from FY2023 as post-2021
    high land-cost cohorts delivered.  Bands below are retrospective
    sensitivity bands, not PIT: their thresholds use the realised historical
    margin curve.
    """
    if year is None:
        return 0.295
    if year <= 2013:
        return 0.36
    if year <= 2019:
        return 0.42
    if year <= 2021:
        return 0.34
    return 0.24


def _prepare_phase_maps(
    signals: pd.DataFrame,
) -> tuple[pd.DataFrame, dict, dict, pd.Series]:
    """Shared prep: FY tagging, attributable stake, per-phase ASP + vintage."""
    frame = signals.copy()
    frame["period"] = pd.to_datetime(frame["period"], errors="coerce")
    frame = frame[frame["period"].notna()].copy()
    frame["fy"] = frame["period"].dt.year + frame["period"].dt.month.ge(7).astype(int)
    frame["stake"] = frame.apply(
        lambda r: (
            r["sales_value_gross_hkd"] * r["indicative_ownership_pct"] / 100.0
            if pd.notna(r.get("indicative_ownership_pct")) and r.get("indicative_owner_status") == "likely_shkp_numeric_snapshot"
            else 0.5 * r["sales_value_gross_hkd"] if r.get("indicative_owner_status") == "likely_shkp_jv_unquantified"
            else 0.0
        ),
        axis=1,
    )
    asp_by_phase: dict = {}
    vintage_by_phase: dict = {}
    for (dev_id, dev_name, phase), group in frame.groupby(["development_id", "development_name", "phase_name"]):
        units = float(group["sales_units_gross"].sum())
        value = float(group["sales_value_gross_hkd"].sum())
        asp_by_phase[(dev_id, dev_name, phase)] = value / units if units else None
        cstart = group["coverage_start"].dropna()
        if not cstart.empty:
            vintage_by_phase[(dev_id, dev_name, phase)] = pd.to_datetime(cstart.iloc[0], errors="coerce").year
    pf = frame.groupby(["development_id", "development_name", "phase_name", "fy"])["stake"].sum().reset_index()
    piv = pf.pivot_table(index=["development_id", "development_name", "phase_name"], columns="fy", values="stake").fillna(0)
    contract_by_fy = frame.groupby("fy")["stake"].sum()
    return piv, asp_by_phase, vintage_by_phase, contract_by_fy


def _margin_for_phase(mode: str, asp: float | None, vintage_year: int | None) -> float:
    if mode == "vintage":
        return _vintage_margin(vintage_year)
    return _bucket_margin(asp)


def _residential_profit(
    piv: pd.DataFrame,
    asp_by_phase: dict,
    vintage_by_phase: dict,
    t: int,
    margin_mode: str,
    *,
    w0: float = 0.2857,
    w1: float = 0.4762,
    w2: float = 0.2381,
) -> float:
    total = 0.0
    for idx, row in piv.iterrows():
        c_t = float(row.get(t, 0))
        c_t1 = float(row.get(t - 1, 0))
        c_t2 = float(row.get(t - 2, 0))
        recog = w0 * c_t + w1 * c_t1 + w2 * c_t2
        if recog <= 0:
            continue
        total += recog * _margin_for_phase(margin_mode, asp_by_phase.get(idx), vintage_by_phase.get(idx))
    return total


def build_shkp_skeleton_backtest(
    earnings_bridge: pd.DataFrame,
    margin_history: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    start_year: int = 2017,
    end_year: int = 2025,
    margin_mode: str = "vintage",
) -> pd.DataFrame:
    """Run the retrospective skeleton backtest.

    ``margin_mode``: ``"vintage"`` (default, launch-cohort calibration) or
    ``"bucket"`` (legacy static FY26/27-calibrated bucket).  Neither mode is
    strict PIT: current ownership snapshots and hindsight-calibrated margin
    bands are retained for research diagnostics only.
    """
    if earnings_bridge is None or earnings_bridge.empty or signals is None or signals.empty:
        return pd.DataFrame()
    piv, asp_by_phase, vintage_by_phase, _ = _prepare_phase_maps(signals)

    bridge = earnings_bridge.set_index("fiscal_year_end")
    mh = margin_history.set_index("fiscal_year_end") if margin_history is not None and not margin_history.empty else pd.DataFrame()
    non_res_actual = {}
    for t in bridge.index:
        if not mh.empty and t in mh.index:
            dev_profit = float(mh.loc[t, "development_profit_combined_hkd_m"])
            non_res_actual[int(t)] = float(bridge.loc[t, "underlying_profit_hkd_m"]) - dev_profit

    rows: list[dict[str, Any]] = []
    for t in range(int(start_year), int(end_year) + 1):
        if t not in bridge.index or t not in non_res_actual:
            continue
        total_profit = 0.0
        resid_model = _residential_profit(piv, asp_by_phase, vintage_by_phase, t, margin_mode) / 1e6
        prior = [non_res_actual[y] for y in range(t - 3, t) if y in non_res_actual]
        non_res_model = sum(prior) / len(prior) if prior else float("nan")
        model_underlying = resid_model + non_res_model
        actual = float(bridge.loc[t, "underlying_profit_hkd_m"])
        rows.append(
            {
                "fiscal_year_end": t,
                "fiscal_label": f"FY{t - 1}/{str(t)[-2:]}",
                "actual_underlying_profit_hkd_m": actual,
                "model_underlying_profit_hkd_m": model_underlying,
                "residential_model_profit_hkd_m": resid_model,
                "non_residential_model_runrate_hkd_m": non_res_model,
                "non_residential_actual_hkd_m": non_res_actual[t],
                "non_residential_error_pct": (non_res_model - non_res_actual[t]) / non_res_actual[t] * 100.0 if non_res_actual[t] else None,
                "underlying_error_pct": (model_underlying - actual) / actual * 100.0,
                "eps_model": model_underlying / SHARES_MILLION,
                "eps_actual": float(bridge.loc[t, "underlying_eps_hkd"]),
                "eps_error": model_underlying / SHARES_MILLION - float(bridge.loc[t, "underlying_eps_hkd"]),
                "model_use": "skeleton_historical_backtest",
                "research_only": True,
                "margin_mode": margin_mode,
                "caveat": (
                    f"Retrospective research calibration: residential uses the lag kernel x {margin_mode} margin; "
                    "non-residential is a 3-year rolling mean of prior actuals. Current indicative ownership "
                    "snapshots and hindsight-calibrated margin bands are not strict PIT. "
                    "Vintage = launch-cohort calibration. "
                    "Residual FY2016/17 reflects the SRPE-2013 data floor and recent-year swings reflect "
                    "the Mainland dev cycle (see margin decomposition)."
                ),
            }
        )
    return pd.DataFrame(rows)


def build_shkp_skeleton_margin_decomposition(
    earnings_bridge: pd.DataFrame,
    margin_history: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    start_year: int = 2017,
    end_year: int = 2025,
) -> pd.DataFrame:
    """Attribute the backtest error to margin assumption vs data coverage.

    Replays the same frozen residential engine (lag kernel x margin) and the
    same point-in-time non-residential run-rate, but for each fiscal year
    reports the underlying error under THREE margin treatments so the
    structural causes are separated without touching the frozen v1.0 output:

    * ``bucket``        - the frozen FY2026/27-calibrated static bucket
                          (22.5/29.5/37.5% by ASP). Default/current behaviour.
    * ``rolling_actual`` - point-in-time prior-3-year mean of the actual HK
                          development margin (only data available before t).
    * ``actual``        - hindsight: the actual margin of year t itself. Not
                          PIT; included only as the ceiling of what a perfect
                          margin model could achieve (isolates data gaps).
    * ``vintage``       - retrospective sensitivity: assigns each phase a
                          margin from its launch-era cohort (``coverage_start``
                          year, a land-cost/launch-vintage proxy) calibrated
                          to the historical HK development-margin curve. This
                          is not a strict PIT estimate.

    The gap between ``rolling_actual`` and ``actual`` is the residual margin
    uncertainty under PIT; the gap between ``bucket`` and ``rolling_actual``
    is the systematic conservatism of the frozen static bucket in the
    high-margin 2017-2020 regime; the gap between ``actual`` and the total
    error is the non-residential run-rate plus recognition-coverage effect.
    """
    if earnings_bridge is None or earnings_bridge.empty or signals is None or signals.empty:
        return pd.DataFrame()
    piv, asp_by_phase, vintage_by_phase, _ = _prepare_phase_maps(signals)

    bridge = earnings_bridge.set_index("fiscal_year_end")
    mh = margin_history.set_index("fiscal_year_end") if margin_history is not None and not margin_history.empty else pd.DataFrame()
    non_res_actual = {}
    for t in bridge.index:
        if not mh.empty and t in mh.index:
            dev_profit = float(mh.loc[t, "development_profit_combined_hkd_m"])
            non_res_actual[int(t)] = float(bridge.loc[t, "underlying_profit_hkd_m"]) - dev_profit

    def _year_actual_margin(t: int) -> float | None:
        if mh.empty or t not in mh.index:
            return None
        return float(mh.loc[t, "development_margin_pct"]) / 100.0

    def _year_rolling_margin(t: int) -> float | None:
        prior = [_year_actual_margin(y) for y in range(t - 3, t)]
        prior = [p for p in prior if p is not None]
        return sum(prior) / len(prior) if prior else None

    def _recognised(t: int) -> float:
        w0, w1, w2 = 0.2857, 0.4762, 0.2381
        total = 0.0
        for idx, row in piv.iterrows():
            c_t = float(row.get(t, 0))
            c_t1 = float(row.get(t - 1, 0))
            c_t2 = float(row.get(t - 2, 0))
            recog = w0 * c_t + w1 * c_t1 + w2 * c_t2
            if recog <= 0:
                continue
            total += recog
        return total

    def _bucket_residential(t: int) -> float:
        return _residential_profit(piv, asp_by_phase, vintage_by_phase, t, "bucket")

    def _vintage_residential(t: int) -> float:
        return _residential_profit(piv, asp_by_phase, vintage_by_phase, t, "vintage")

    rows: list[dict[str, Any]] = []
    for t in range(int(start_year), int(end_year) + 1):
        if t not in bridge.index or t not in non_res_actual:
            continue
        actual = float(bridge.loc[t, "underlying_profit_hkd_m"])
        prior = [non_res_actual[y] for y in range(t - 3, t) if y in non_res_actual]
        non_res_model = sum(prior) / len(prior) if prior else float("nan")
        recog = _recognised(t)
        resid_bucket = _bucket_residential(t) / 1e6
        resid_vintage = _vintage_residential(t) / 1e6
        m_rolling = _year_rolling_margin(t)
        m_actual = _year_actual_margin(t)
        resid_rolling = (recog * m_rolling / 1e6) if m_rolling else float("nan")
        resid_actual = (recog * m_actual / 1e6) if m_actual else float("nan")
        for mode, resid in (
            ("bucket", resid_bucket),
            ("vintage", resid_vintage),
            ("rolling_actual", resid_rolling),
            ("actual", resid_actual),
        ):
            model = resid + non_res_model
            rows.append(
                {
                    "fiscal_year_end": t,
                    "fiscal_label": f"FY{t - 1}/{str(t)[-2:]}",
                    "margin_mode": mode,
                    "recognised_contract_hkd_m": recog / 1e6,
                    "residential_model_profit_hkd_m": resid,
                    "non_residential_model_runrate_hkd_m": non_res_model,
                    "non_residential_actual_hkd_m": non_res_actual[t],
                    "actual_underlying_profit_hkd_m": actual,
                    "model_underlying_profit_hkd_m": model,
                    "underlying_error_pct": (model - actual) / actual * 100.0 if actual else None,
                    "rolling_margin_pct": (m_rolling * 100.0) if m_rolling else None,
                    "actual_margin_pct": (m_actual * 100.0) if m_actual else None,
                    "model_use": "shkp_skeleton_margin_decomposition",
                    "research_only": True,
                }
            )
    return pd.DataFrame(rows)


def run_shkp_skeleton_margin_decomposition() -> dict[str, Any]:
    """Persist the margin-vs-data error attribution."""
    run_id = f"shkp-skeleton-margin-decomposition-{uuid.uuid4()}"
    bridge = load_latest_normalized("shkp_historical_earnings_bridge")
    margin_history = load_latest_normalized("shkp_hk_development_margin_history")
    signals = load_latest_normalized("shkp_indicative_project_month_signals_all_history")
    decomp = build_shkp_skeleton_margin_decomposition(bridge, margin_history, signals)
    normalized = save_normalized_dataset(
        "shkp_skeleton_margin_decomposition",
        decomp,
        run_id=run_id,
        lineage_metadata={
            "lineage_type": "shkp_skeleton_margin_decomposition",
            "run_id": run_id,
            "research_only": True,
            "caveat": (
                "margin_mode=actual is hindsight (not PIT), included only as the "
                "ceiling of what a perfect margin model could achieve; the gap to "
                "rolling_actual is PIT margin uncertainty; reset between modes."
            ),
        },
    )
    mae = (
        decomp.groupby("margin_mode")["underlying_error_pct"].apply(lambda s: s.abs().mean())
        if not decomp.empty and "margin_mode" in decomp.columns
        else pd.Series(dtype="float64")
    )
    return {
        "mode": "shkp_skeleton_margin_decomposition",
        "run_id": run_id,
        "rows": int(len(decomp)),
        "mae_underlying_pct_by_margin_mode": mae.to_dict() if not decomp.empty else {},
        "normalized": normalized,
        "research_only": True,
    }


def run_shkp_skeleton_backtest() -> dict[str, Any]:
    """Persist the skeleton historical backtest."""
    run_id = f"shkp-skeleton-backtest-{uuid.uuid4()}"
    bridge = load_latest_normalized("shkp_historical_earnings_bridge")
    margin_history = load_latest_normalized("shkp_hk_development_margin_history")
    signals = load_latest_normalized("shkp_indicative_project_month_signals_all_history")
    backtest = build_shkp_skeleton_backtest(bridge, margin_history, signals)
    normalized = save_normalized_dataset(
        BACKTEST_DATASET,
        backtest,
        run_id=run_id,
        lineage_metadata={
            "lineage_type": "shkp_skeleton_historical_backtest",
            "run_id": run_id,
            "research_only": True,
        },
    )
    mae = float(backtest["underlying_error_pct"].abs().mean()) if not backtest.empty else None
    return {
        "mode": "shkp_skeleton_historical_backtest",
        "run_id": run_id,
        "rows": int(len(backtest)),
        "mae_underlying_pct": mae,
        "normalized": normalized,
        "research_only": True,
    }
