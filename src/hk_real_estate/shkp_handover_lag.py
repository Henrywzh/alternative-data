"""SHKP residential handover / revenue-recognition lag analysis.

The whole-company skeleton previously assumed a mechanical ~2-year lag
between contract signing and recognised revenue.  This module replaces that
with an evidence-based lag distribution estimated from SHKP projects that
have BOTH a launch date (SRPE earliest publication, the first sales-brochure
filing) AND a handover confirmation (annual-report handover disclosure).

Estimate (2026-08-09, n=21 SHKP phases):

    P(lag=0) = 6/21 = 29%   (recognised in the same fiscal year)
    P(lag=1) = 10/21 = 48%  (recognised in the following fiscal year)
    P(lag=2) = 5/21 = 24%   (recognised two fiscal years later)

    mean lag = 1.0 fiscal year, median = 1.0

The mechanical 2-year assumption was therefore too conservative: the modal
SHKP presale is handed over about one fiscal year after launch.  The
distribution is applied as recognition weights to the *actual* contract
activity series (all-history signals) to derive recognised residential
revenue by fiscal year.

Limitations (kept visible in every output):
* n=21 is small and skews to recent launches (NOVO LAND, YOHO, Wetland,
  Sierra Sea); the distribution is scenario-grade, not a precise calendar.
* ``handover_report_period_end`` is the annual report's handover-completed
  year for the phase, not a unit-level handover calendar.
* Phase-level mix (small luxury vs large suburban estates) may shift the
  true lag; the output exposes the per-phase lags for inspection.
"""

from __future__ import annotations

from typing import Any
import re
import uuid

import pandas as pd

from .storage import load_latest_normalized, save_normalized_dataset


LAG_DISTRIBUTION_DATASET = "shkp_handover_lag_distribution"
RECOGNITION_DATASET = "shkp_residential_recognition_schedule"


def _latest_fiscal_year(window_text: Any) -> int | None:
    fys = re.findall(r"(?:FY|1H of FY|2H of FY)(\d{4}/\d{2})", str(window_text or ""))
    return max(int(f.split("/")[0]) for f in fys) if fys else None


def build_shkp_handover_lag_distribution(
    handover_bridge: pd.DataFrame,
    phase_roster: pd.DataFrame,
) -> pd.DataFrame:
    """Estimate the launch-to-handover lag distribution from paired phases."""
    if handover_bridge is None or handover_bridge.empty or phase_roster is None or phase_roster.empty:
        return pd.DataFrame()
    both = handover_bridge[
        handover_bridge.get("completion_window", pd.Series(dtype=object)).notna()
        & handover_bridge.get("handover_report_period_end", pd.Series(dtype=object)).notna()
    ].copy()
    if both.empty:
        return pd.DataFrame()
    roster = phase_roster[["srpe_development_id", "srpe_earliest_publication"]].copy()
    both = both.merge(roster, on="srpe_development_id", how="left")
    both["completion_fy"] = both["completion_window"].apply(_latest_fiscal_year)
    both["handover_fy"] = pd.to_datetime(both["handover_report_period_end"], errors="coerce").dt.year
    both["launch"] = pd.to_datetime(both["srpe_earliest_publication"], errors="coerce")
    both["launch_fy"] = both["launch"].dt.year + both["launch"].dt.month.ge(7).astype(int)
    valid = both.dropna(subset=["launch_fy", "handover_fy"]).copy()
    if valid.empty:
        return pd.DataFrame()
    valid["lag_years"] = (valid["handover_fy"] - valid["launch_fy"]).astype(int)
    dist = valid["lag_years"].value_counts(normalize=True).sort_index()
    weights = {
        "lag_0_weight": float(dist.get(0, 0.0)),
        "lag_1_weight": float(dist.get(1, 0.0)),
        "lag_2_weight": float(dist.get(2, 0.0)),
        "mean_lag_years": float(valid["lag_years"].mean()),
        "median_lag_years": float(valid["lag_years"].median()),
        "n_phases": int(len(valid)),
    }
    rows = [
        {
            "srpe_development_id": str(row["srpe_development_id"]),
            "development_name": row.get("development_name"),
            "phase_name": row.get("phase_name"),
            "launch_fy": row["launch_fy"],
            "completion_fy": row["completion_fy"],
            "handover_fy": row["handover_fy"],
            "lag_years": row["lag_years"],
            "model_use": "handover_lag_estimation",
            "research_only": True,
            "caveat": (
                "Per-phase launch-to-handover lag in fiscal years. handover_fy is the annual report's "
                "handover-completed year, not a unit-level calendar."
            ),
        }
        for _, row in valid.iterrows()
    ]
    frame = pd.DataFrame(rows)
    frame.attrs["lag_weights"] = weights
    return frame


def build_shkp_residential_recognition_schedule(
    lag_distribution: pd.DataFrame,
    *,
    contract_activity_hkd: dict[int, float],
    target_fiscal_years: list[int] | None = None,
) -> pd.DataFrame:
    """Apply the lag distribution to actual contract activity.

    ``contract_activity_hkd`` maps fiscal year -> attributable HK residential
    contract value (HKD).  Recognised revenue in fiscal year t =
    w0*contract_t + w1*contract_{t-1} + w2*contract_{t-2}, where w0/w1/w2 are
    the estimated lag-0/lag-1/lag-2 weights.  Rows are one per fiscal year
    with the contract input, recognised output and the weight vector used.
    """
    weights = dict(lag_distribution.attrs.get("lag_weights") or {})
    if not weights:
        return pd.DataFrame()
    w0 = float(weights.get("lag_0_weight", 0.0))
    w1 = float(weights.get("lag_1_weight", 0.0))
    w2 = float(weights.get("lag_2_weight", 0.0))
    years = sorted(target_fiscal_years or contract_activity_hkd)
    rows: list[dict[str, Any]] = []
    for year in years:
        c0 = float(contract_activity_hkd.get(year, 0.0))
        c1 = float(contract_activity_hkd.get(year - 1, 0.0))
        c2 = float(contract_activity_hkd.get(year - 2, 0.0))
        recognised = w0 * c0 + w1 * c1 + w2 * c2
        rows.append(
            {
                "fiscal_year_end": year,
                "contract_activity_hkd": c0,
                "prior_year_contract_hkd": c1,
                "two_years_prior_contract_hkd": c2,
                "lag_0_weight": w0,
                "lag_1_weight": w1,
                "lag_2_weight": w2,
                "recognised_residential_revenue_hkd": recognised,
                "model_use": "residential_recognition_schedule",
                "research_only": True,
                "caveat": (
                    f"Recognition weights from {weights.get('n_phases', 0)} paired phases "
                    f"(mean lag {weights.get('mean_lag_years', float('nan')):.1f} FY). Scenario-grade."
                ),
            }
        )
    return pd.DataFrame(rows)


def run_shkp_handover_lag() -> dict[str, Any]:
    """Persist the lag distribution and recognition schedule."""
    run_id = f"shkp-handover-lag-{uuid.uuid4()}"
    bridge = load_latest_normalized("shkp_sales_handover_revenue_bridge")
    roster = load_latest_normalized("shkp_historical_phase_roster")
    lag = build_shkp_handover_lag_distribution(bridge, roster)
    weights = lag.attrs.get("lag_weights") or {}
    # Actual attributable HK residential contract activity by fiscal year
    # from the indicative all-history signals (numeric stake + JV at base).
    signals = load_latest_normalized("shkp_indicative_project_month_signals_all_history")
    contract_by_fy: dict[int, float] = {}
    if not signals.empty:
        frame = signals.copy()
        frame["period"] = pd.to_datetime(frame["period"], errors="coerce")
        frame = frame[frame["period"].notna()].copy()
        frame["fy"] = frame["period"].dt.year + frame["period"].dt.month.ge(7).astype(int)
        frame["stake_value"] = frame.apply(
            lambda r: (
                r["sales_value_gross_hkd"] * r["indicative_ownership_pct"] / 100.0
                if pd.notna(r.get("indicative_ownership_pct")) and r.get("indicative_owner_status") == "likely_shkp_numeric_snapshot"
                else 0.5 * r["sales_value_gross_hkd"] if r.get("indicative_owner_status") == "likely_shkp_jv_unquantified"
                else 0.0
            ),
            axis=1,
        )
        for fy, value in frame.groupby("fy")["stake_value"].sum().items():
            contract_by_fy[int(fy)] = float(value)
    # FY2027 contract activity is not yet observable (signals end 2026-08);
    # substitute the sales-model FY2027 base forecast for that input so the
    # FY2027 recognition row reflects expected future contracts, not a
    # partial-year artifact.
    forecast = load_latest_normalized("shkp_indicative_sales_model_forecast")
    if not forecast.empty:
        fy27 = forecast[
            forecast["forecast_fiscal_year_end"].eq(2027)
            & forecast["growth_scenario"].eq("base")
            & forecast["ownership_scenario"].eq("base")
        ]
        if not fy27.empty:
            # The base ownership/growth row already combines numeric stake
            # activity with the explicit base JV sensitivity.  Using only the
            # numeric component here would silently drop JV contract flow from
            # the recognition schedule.
            forecast_column = (
                "forecast_total_sales_hkd"
                if "forecast_total_sales_hkd" in fy27.columns
                else "forecast_numeric_stake_sales_hkd"
            )
            if forecast_column in fy27.columns:
                contract_by_fy[2027] = float(fy27[forecast_column].iloc[0])
    recognition = build_shkp_residential_recognition_schedule(
        lag,
        contract_activity_hkd=contract_by_fy,
        target_fiscal_years=[2026, 2027],
    )
    lineage = {
        "lineage_type": "shkp_handover_lag_analysis",
        "run_id": run_id,
        "n_paired_phases": weights.get("n_phases"),
        "mean_lag_years": weights.get("mean_lag_years"),
        "research_only": True,
    }
    normalized = {
        LAG_DISTRIBUTION_DATASET: save_normalized_dataset(
            LAG_DISTRIBUTION_DATASET,
            lag,
            run_id=run_id,
            lineage_metadata={**lineage, "contract_dataset": LAG_DISTRIBUTION_DATASET},
        ),
        RECOGNITION_DATASET: save_normalized_dataset(
            RECOGNITION_DATASET,
            recognition,
            run_id=run_id,
            lineage_metadata={**lineage, "contract_dataset": RECOGNITION_DATASET},
        ),
    }
    return {
        "mode": "shkp_handover_lag_analysis",
        "run_id": run_id,
        "lag_weights": weights,
        "recognition_rows": int(len(recognition)),
        "normalized": normalized,
        "research_only": True,
    }
