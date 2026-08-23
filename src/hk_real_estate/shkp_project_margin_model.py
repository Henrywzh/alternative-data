"""SHKP FY2027 project-mix development margin model (Tier 1, step 2).

The consensus gap decomposition showed the entire FY2027E EPS gap is
development margin (model 24% vs consensus-implied ~29.6%).  This module
answers: can the FY2027 handover mix plausibly produce ~30%?

Method (user-directed):

* Step 2A (done): 13-year HK development-margin history
  (`shkp_hk_development_margin_history`): median 39.0%, mean 35.1%,
  25/75 pct 28.0%/41.8%, FY2025 trough 12.2%.  Consensus-implied 29.6%
  sits at the 31st historical percentile - below the historical median,
  above the last-3-year average (24.7%).
* Step 2B (here): feature-based margin buckets for FY2027-recognised
  phases.  Bucket boundaries are calibrated to the historical distribution
  (low = 20-25%, mid = 27-32%, high = 35-40%), and assignment uses:
    - ASP (pricing power): luxury > 15m/unit, mass < 8m/unit;
    - launch vintage (land-cost proxy): 2020-22 vintage = low, 2023-24 =
      mid, 2025+ = depends on launch price vs cost;
    - completion window (recognition confidence);
    - JV structure (YOHO WEST etc. at 50%).
  No fake precision: each phase gets a bucket and a point estimate, with
  the bucket range carried explicitly.
* Step 2C: revenue-weighted FY2027 margin =
      sum(R_i * M_i) / sum(R_i)
  over the FY2027 recognition schedule.
* Step 2D: consensus-required mix - what weighted margin/mix would produce
  the consensus-implied 29.6%?

Honest limitations: ASP is an observed contract-price signal, not a cost
base; land-vintage is proxied by launch year; no construction-cost or
capitalised-interest data.  Outputs are variant-perception diagnostics,
not audited margins.
"""

from __future__ import annotations

from typing import Any
import uuid

import pandas as pd

from .storage import load_latest_normalized, save_normalized_dataset


PROJECT_MARGIN_DATASET = "shkp_project_margin_model"
WEIGHTED_MARGIN_DATASET = "shkp_fy27_weighted_development_margin"


# Bucket boundaries calibrated to the FY2013-25 historical distribution
# (25th pct 28.0%, median 39.0%, 75th pct 41.8%; recent 3y mean 24.7%).
# A phase's point estimate is the bucket midpoint; the range is preserved.
MARGIN_BUCKETS = {
    "low": {"low": 0.20, "high": 0.25, "point": 0.225},
    "mid": {"low": 0.27, "high": 0.32, "point": 0.295},
    "high": {"low": 0.35, "high": 0.40, "point": 0.375},
}


def _assign_margin_bucket(*, asp_per_unit_hkd: float | None, launch_fy: int | None) -> str:
    """Feature-based bucket assignment (ASP pricing power + land vintage)."""
    # Luxury pricing power dominates: >15m/unit ASP is high-margin territory
    # (Cullinan Sky 2 at 22m, Cullinan Harbour at 43-67m).
    if asp_per_unit_hkd is not None and asp_per_unit_hkd >= 15_000_000:
        return "high"
    if asp_per_unit_hkd is not None and asp_per_unit_hkd >= 10_000_000:
        return "mid"
    # Mass-market / suburban projects: land vintage decides.
    if launch_fy is not None:
        if launch_fy <= 2022:
            return "mid"  # older land cost
        if launch_fy <= 2024:
            return "mid"
        return "low"  # 2025+ launches at recent land costs
    return "mid"


def build_shkp_project_margin_model(
    recognition_schedule: pd.DataFrame,
    *,
    signals: pd.DataFrame | None = None,
    phase_roster: pd.DataFrame | None = None,
    target_fiscal_year: int = 2027,
) -> pd.DataFrame:
    """Assign margin buckets to recognised phases of a target fiscal year.

    For the target year t, recognised revenue per phase =
    w0*contract_t + w1*contract_{t-1} + w2*contract_{t-2}.  When t is the
    current/future year and the t contract activity is not yet observable
    (partial-year signals), the sales-model forecast for t is distributed
    by phase share of the latest complete year's contracts.  For FY2026
    all inputs are actual (contracts to FY2026 are observable), so no
    forecast substitution occurs.
    """
    if recognition_schedule is None or recognition_schedule.empty:
        return pd.DataFrame()
    # Build the FY2027 per-phase recognised revenue (same decomposition as
    # the recognition schedule but at phase level).
    frame = signals.copy() if signals is not None and not signals.empty else pd.DataFrame()
    roster = phase_roster if phase_roster is not None else pd.DataFrame()
    if frame.empty:
        return pd.DataFrame()
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
    per_phase_fy = frame.groupby(["development_id", "development_name", "phase_name", "fy"]).agg(
        stake=("stake", "sum"),
        units=("sales_units_gross", "sum"),
        value=("sales_value_gross_hkd", "sum"),
    ).reset_index()
    piv = per_phase_fy.pivot_table(
        index=["development_id", "development_name", "phase_name"],
        columns="fy",
        values="stake",
    )
    target = int(target_fiscal_year)
    piv = piv.reindex(columns=[target - 2, target - 1, target], fill_value=0).fillna(0)
    prior_full_total = piv[target - 1].sum()
    # Do not freeze a previously observed forecast value in code.  The
    # current sales-model artifact is the only source for the target-year
    # contract sensitivity; if it is unavailable, leave the target-year
    # contract flow unobserved rather than inventing a stale number.
    target_forecast = None
    # Use the FY2027 base forecast for the unobservable target-year
    # contracts only when the target year is not yet complete.
    weights = dict(recognition_schedule.attrs.get("lag_weights") or {})
    w0 = float(weights.get("lag_0_weight", 0.2857))
    w1 = float(weights.get("lag_1_weight", 0.4762))
    w2 = float(weights.get("lag_2_weight", 0.2381))
    forecast = load_latest_normalized("shkp_indicative_sales_model_forecast")
    if target_forecast is None and not forecast.empty:
        rows_fc = forecast[
            forecast["forecast_fiscal_year_end"].eq(target)
            & forecast["growth_scenario"].eq("base")
            & forecast["ownership_scenario"].eq("base")
        ]
        if not rows_fc.empty:
            forecast_column = (
                "forecast_total_sales_hkd"
                if "forecast_total_sales_hkd" in rows_fc.columns
                else "forecast_numeric_stake_sales_hkd"
            )
            if forecast_column in rows_fc.columns:
                target_forecast = float(rows_fc[forecast_column].iloc[0])

    # ASP per phase (all-period average) for pricing-power signal.
    asp_by_phase = {}
    for (dev_id, dev_name, phase_name), group in frame.groupby(["development_id", "development_name", "phase_name"]):
        units = float(group["sales_units_gross"].sum())
        value = float(group["sales_value_gross_hkd"].sum())
        asp_by_phase[(dev_id, dev_name, phase_name)] = value / units if units else None
    launch_by_phase = {}
    if not roster.empty and {"srpe_development_id", "srpe_earliest_publication"}.issubset(roster.columns):
        for _, row in roster.iterrows():
            launch = pd.to_datetime(row.get("srpe_earliest_publication"), errors="coerce")
            if pd.notna(launch):
                launch_by_phase[str(row["srpe_development_id"])] = int(launch.year + (1 if launch.month >= 7 else 0))

    rows: list[dict[str, Any]] = []
    total_recognised = 0.0
    for idx, row in piv.iterrows():
        dev_id = str(idx[0])
        c_prev2 = float(row[target - 2])
        c_prev1 = float(row[target - 1])
        c_target = float(row[target])
        if target_forecast is not None and prior_full_total > 0:
            c_target = target_forecast * (c_prev1 / prior_full_total)
        recognised = w0 * c_target + w1 * c_prev1 + w2 * c_prev2
        if recognised <= 0:
            continue
        asp = asp_by_phase.get((idx[0], idx[1], idx[2]))
        launch_fy = launch_by_phase.get(dev_id)
        bucket = _assign_margin_bucket(asp_per_unit_hkd=asp, launch_fy=launch_fy)
        bucket_def = MARGIN_BUCKETS[bucket]
        rows.append(
            {
                "development_id": dev_id,
                "development_name": idx[1],
                "phase_name": idx[2],
                "fiscal_year": target,
                "recognised_revenue_hkd": recognised,
                "asp_per_unit_hkd": asp,
                "launch_fy": launch_fy,
                "margin_bucket": bucket,
                "margin_low": bucket_def["low"],
                "margin_high": bucket_def["high"],
                "margin_point": bucket_def["point"],
                "recognised_weight_pct": 0.0,  # filled after total
                "model_use": "fy27_project_mix_margin",
                "research_only": True,
                "caveat": (
                    "Bucket assigned from ASP (pricing power) and launch vintage (land-cost proxy); "
                    "no construction-cost or capitalised-interest data. Point estimate is the bucket "
                    "midpoint; range is explicit. Not an audited margin."
                ),
            }
        )
        total_recognised += recognised
    out = pd.DataFrame(rows)
    if not out.empty and total_recognised > 0:
        out["recognised_weight_pct"] = out["recognised_revenue_hkd"] / total_recognised * 100.0
        out = out.sort_values("recognised_revenue_hkd", ascending=False).reset_index(drop=True)
        out.attrs["total_recognised_hkd"] = total_recognised
    return out


def build_shkp_fy27_weighted_margin(project_model: pd.DataFrame) -> pd.DataFrame:
    """Revenue-weighted margin and consensus-required comparison."""
    if project_model is None or project_model.empty:
        return pd.DataFrame()
    target = int(project_model["fiscal_year"].iloc[0])
    total_rev = float(project_model["recognised_revenue_hkd"].sum())
    weighted_point = float((project_model["recognised_revenue_hkd"] * project_model["margin_point"]).sum() / total_rev) if total_rev else float("nan")
    weighted_low = float((project_model["recognised_revenue_hkd"] * project_model["margin_low"]).sum() / total_rev) if total_rev else float("nan")
    weighted_high = float((project_model["recognised_revenue_hkd"] * project_model["margin_high"]).sum() / total_rev) if total_rev else float("nan")
    # The 29.6% figure is a FY2027 consensus-implied margin.  Do not attach it
    # to the FY2026 diagnostic row merely because the same weighted-margin
    # helper is used for both target years.
    consensus_margin = 0.296 if target == 2027 else None
    consensus_profit = total_rev * consensus_margin if consensus_margin is not None else None
    model_profit = total_rev * weighted_point
    gap_profit = consensus_profit - model_profit if consensus_profit is not None else None
    # Named in millions to match SHARES_MILLION elsewhere in this package, and
    # converted explicitly at the point of use.  ``gap_profit`` is an absolute
    # HKD figure (recognised revenue is in HKD, not HKD millions), so dividing
    # it by 2896.0 gives HKD per million shares -- a per-share number 10^6 too
    # large, and one nothing downstream range-checks.
    shares_million = 2896.0
    shares_outstanding = shares_million * 1e6
    return pd.DataFrame(
        [
            {
                "fiscal_year": target,
                "consensus_comparison_fiscal_year": 2027,
                "total_recognised_revenue_hkd": total_rev,
                "weighted_margin_low": weighted_low,
                "weighted_margin_point": weighted_point,
                "weighted_margin_high": weighted_high,
                "consensus_implied_margin": consensus_margin,
                "model_development_profit_hkd": model_profit,
                "consensus_implied_development_profit_hkd": consensus_profit,
                "margin_gap_profit_hkd": gap_profit,
                "margin_gap_eps_hkd": gap_profit / shares_outstanding if gap_profit is not None else None,
                "model_use": "fy27_weighted_development_margin_variant",
                "research_only": True,
                "caveat": (
                    "Weighted margin uses bucket midpoints; low/high bracket the range. Consensus-implied "
                    "29.6% is a FY2027-only comparison derived from broker EPS 8.65 less non-residential "
                    "run-rates; the FY2026 row is a project-mix diagnostic and has no consensus gap."
                ),
            }
        ]
    )


def run_shkp_project_margin_model() -> dict[str, Any]:
    """Persist the project-mix margin model outputs."""
    run_id = f"shkp-project-margin-{uuid.uuid4()}"
    recognition = load_latest_normalized("shkp_residential_recognition_schedule")
    signals = load_latest_normalized("shkp_indicative_project_month_signals_all_history")
    roster = load_latest_normalized("shkp_historical_phase_roster")
    project_models = []
    weighted_rows = []
    for target in (2026, 2027):
        pm = build_shkp_project_margin_model(
            recognition,
            signals=signals,
            phase_roster=roster,
            target_fiscal_year=target,
        )
        if pm.empty:
            continue
        project_models.append(pm)
        weighted_rows.append(build_shkp_fy27_weighted_margin(pm))
    project_model = pd.concat(project_models, ignore_index=True) if project_models else pd.DataFrame()
    weighted = pd.concat(weighted_rows, ignore_index=True) if weighted_rows else pd.DataFrame()
    lineage = {
        "lineage_type": "shkp_project_mix_margin",
        "run_id": run_id,
        "research_only": True,
        "method": "feature_based_bucket_calibrated_to_historical_margin_distribution",
    }
    normalized = {
        PROJECT_MARGIN_DATASET: save_normalized_dataset(
            PROJECT_MARGIN_DATASET,
            project_model,
            run_id=run_id,
            lineage_metadata={**lineage, "contract_dataset": PROJECT_MARGIN_DATASET},
        ),
        WEIGHTED_MARGIN_DATASET: save_normalized_dataset(
            WEIGHTED_MARGIN_DATASET,
            weighted,
            run_id=run_id,
            lineage_metadata={**lineage, "contract_dataset": WEIGHTED_MARGIN_DATASET},
        ),
    }
    return {
        "mode": "shkp_project_mix_margin",
        "run_id": run_id,
        "project_rows": int(len(project_model)),
        "weighted_rows": int(len(weighted)),
        "normalized": normalized,
        "research_only": True,
    }
