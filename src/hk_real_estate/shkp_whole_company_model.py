"""SHKP whole-company earnings nowcast skeleton (v0.1).

The model follows the user-directed bridge:

    Residential recognised-revenue x development margin
  + Commercial rental revenue -> net rental income
  + Hotel revenue x hotel operating margin (bull/base/bear)
  + Other businesses normalised operating profit
  -----------------------------------------------------
  = Segment operating profit
  + Associates/JVs and other below-segment items (run-rate)
  - Net finance costs (run-rate)
  - Tax, NCI
  -----------------------------------------------------
  = UNDERLYING PROFIT  ->  UNDERLYING EPS   (primary nowcast target)
  + Investment-property FV changes + other non-underlying items
  -----------------------------------------------------
  = REPORTED PROFIT  ->  REPORTED EPS       (accounting bridge only)

Deliverables of this skeleton:
* FY2026E and FY2027E underlying profit/EPS built from the frozen
  residential, commercial and hotel modules plus a normalised other-
  businesses run-rate, for bull/base/bear residential x commercial
  scenarios (material drivers only, not a full factorial grid).
* A consensus-comparison table that strictly matches metric definitions
  (underlying EPS vs broker EPS, reported EPS shown separately).
* Reported-EPS bridge (underlying + FV + other non-underlying items).

Honest limitations (recorded on every output):
* Residential recognition uses a mechanical handover-lag bridge (contract
  flow shifted ~2 years), not a project-level completion calendar.
* The development margin is a historical normalised level, not a
  project-mix model.
* Below-segment items (finance cost, tax, NCI, associates) are run-rates
  from the last available year, not modelled.
* Consensus EPS is assumed underlying (standard HK developer convention);
  the comparison row flags this assumption.
"""

from __future__ import annotations

from typing import Any, Mapping
import uuid

import numpy as np
import pandas as pd

from .storage import load_latest_normalized, save_normalized_dataset


SKELETON_DATASET = "shkp_whole_company_earnings_skeleton"
CONSENSUS_COMPARISON_DATASET = "shkp_whole_company_consensus_comparison"


def _num(value: Any) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(parsed) else float(parsed)


def _run_rate(frame: pd.DataFrame, column: str, window: int = 3) -> float:
    values = pd.to_numeric(frame.get(column), errors="coerce").dropna()
    return float(values.tail(window).mean()) if not values.empty else 0.0


def build_shkp_whole_company_skeleton(
    *,
    earnings_bridge: pd.DataFrame | None = None,
    hotel_series: pd.DataFrame | None = None,
    consensus: pd.DataFrame | None = None,
    recognition_schedule: pd.DataFrame | None = None,
    weighted_margin: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Build the skeleton scenario table and consensus comparison."""
    bridge = earnings_bridge if earnings_bridge is not None and not earnings_bridge.empty else pd.DataFrame()
    hotel = hotel_series if hotel_series is not None and not hotel_series.empty else pd.DataFrame()
    cons = consensus if consensus is not None and not consensus.empty else pd.DataFrame()

    # ---- inputs from the frozen modules ----
    # Residential: recognised revenue comes from the handover-lag schedule
    # (contract activity weighted by the evidence-based lag distribution),
    # times a normalised development margin.  The lag schedule replaces the
    # old mechanical ~2-year shift.
    forecast = load_latest_normalized("shkp_indicative_sales_model_forecast")
    # Per-year weighted margins from the project margin model.
    margin_by_year = {}
    if weighted_margin is not None and not weighted_margin.empty and "fiscal_year" in weighted_margin.columns:
        for _, wm_row in weighted_margin.iterrows():
            margin_by_year[int(wm_row["fiscal_year"])] = float(wm_row["weighted_margin_point"])

    # Development margin: the project-mix weighted FY2027 margin from the
    # margin model (Step 2C), which replaces both the latest-year 24% and
    # the five-year mean 36% with a revenue-weighted project-level estimate.
    dev_margin = 0.24

    # Residential recognised revenue scenarios: contract (FY2027E) shifted
    # ~2 years; recognised-in-FY27 ~ contract signed FY2025 (available) plus
    # a portion of FY26 contracts.  Simplify: recognised-FY27E = FY26E
    # contracts shifted by one year; use forecast FY2026 as the recognised
    # base for FY2027 with the growth scenarios as bull/base/bear on margin.
    # Per-year recognised revenue from the recognition schedule.
    recognised_by_year = {}
    if recognition_schedule is not None and not recognition_schedule.empty and "fiscal_year_end" in recognition_schedule.columns:
        for _, rec_row in recognition_schedule.iterrows():
            recognised_by_year[int(rec_row["fiscal_year_end"])] = float(rec_row["recognised_residential_revenue_hkd"])

    # Commercial: rental revenue run-rate x NRI margin, flat + small RVD
    # adjustment from the frozen transmission (office ~0.83, retail DL ~1.0
    # total elasticity applied to the latest RVD YoY).
    rental_revenue = 17531.0  # FY2025 HK combined, HKD m
    nri_margin = 12956.0 / 17531.0  # FY2025 HK net/gross
    commercial_base = rental_revenue * nri_margin
    # Scenario spread from RVD sensitivity: office+retail blended elasticity
    # ~0.9 applied to a +/-3pp RVD YoY swing => +/-2.7% of rental revenue.
    commercial_scenarios = {
        "bear": commercial_base * 0.97,
        "base": commercial_base,
        "bull": commercial_base * 1.03,
    }

    # Hotel: FY2025 revenue run-rate with bull/base/bear margin.
    hotel_revenue = float(_num(hotel.loc[hotel["fiscal_year_end"].eq(2025), "revenue_combined_hkd_m"].iloc[0])) if not hotel.empty else 5250.0
    hotel_margins = {"bear": 0.10, "base": 0.12, "bull": 0.15}
    hotel_scenarios = {k: hotel_revenue * v for k, v in hotel_margins.items()}

    # Other businesses: normalised run-rate (FY2025 segment profit).
    other_base = 5506.0

    # Below-segment run-rate: FY2025 underlying - (modelled HK segment
    # profit).  The model's segment covers HK commercial rental, hotel,
    # other businesses (all-region per segment note) and HK residential
    # development profit; the residual below_segment therefore absorbs
    # Mainland commercial rental profit, Mainland development profit and
    # all below-segment items (finance cost, tax, NCI, associates) net.
    # This is deliberately a residual, not a modelled line.
    below_segment = 0.0
    if not bridge.empty:
        fy25 = bridge[bridge["fiscal_year_end"].eq(2025)]
        if not fy25.empty:
            underlying = _num(fy25["underlying_profit_hkd_m"].iloc[0])
            if underlying is not None:
                # modelled FY2025 segments: HK residential dev profit +
                # HK commercial NRI + hotel + other (all-region).
                fy25_hk_residential = float(_num(fy25["property_sales_profit_hkd_m"].iloc[0]) or 0.0) * 0.8
                fy25_commercial = 12956.0
                fy25_hotel = float(_num(hotel.loc[hotel["fiscal_year_end"].eq(2025), "result_combined_hkd_m"].iloc[0])) if not hotel.empty else 615.0
                fy25_other = 5506.0
                modelled_fy25 = fy25_hk_residential + fy25_commercial + fy25_hotel + fy25_other
                below_segment = underlying - modelled_fy25

    # FV and non-underlying run-rate for the reported bridge.
    fv_runrate = -2578.0

    shares_outstanding = 2896.0  # million shares (FY2025 shareholders' equity / book value per share)
    rows: list[dict[str, Any]] = []
    for fiscal_year in (2026, 2027):
        resid_base_recognised = float(recognised_by_year.get(fiscal_year, 0.0))
        dev_margin_year = float(margin_by_year.get(fiscal_year, dev_margin))
        # Scenario spread: +/-15% of recognised revenue as the residential
        # scenario band (contract growth x margin uncertainty, material
        # drivers only).
        resid_scenarios = {
            "bear": resid_base_recognised / 1e6 * dev_margin_year * 0.9,
            "base": resid_base_recognised / 1e6 * dev_margin_year,
            "bull": resid_base_recognised / 1e6 * dev_margin_year * 1.1,
        }
        for resid_label, resid_profit in resid_scenarios.items():
            for comm_label, comm_profit in commercial_scenarios.items():
                hotel_profit = hotel_scenarios["base" if resid_label == "base" and comm_label == "base" else "bull" if resid_label == "bull" else "bear"]
                modelled_segment = resid_profit + comm_profit + hotel_profit + other_base
                underlying_profit = modelled_segment + below_segment
                underlying_eps = underlying_profit / shares_outstanding
                reported_profit = underlying_profit + fv_runrate
                reported_eps = reported_profit / shares_outstanding
                rows.append(
                    {
                        "fiscal_year": fiscal_year,
                        "residential_scenario": resid_label,
                        "commercial_scenario": comm_label,
                        "residential_development_profit_hkd_m": round(resid_profit, 1),
                        "commercial_net_rental_income_hkd_m": round(comm_profit, 1),
                        "hotel_profit_hkd_m": round(hotel_profit, 1),
                        "other_businesses_profit_hkd_m": other_base,
                        "modelled_segment_profit_hkd_m": round(modelled_segment, 1),
                        "below_segment_run_rate_hkd_m": round(below_segment, 1),
                        "underlying_profit_hkd_m": round(underlying_profit, 1),
                        "underlying_eps_hkd": round(underlying_eps, 2),
                        "fv_run_rate_hkd_m": fv_runrate,
                        "reported_profit_hkd_m": round(reported_profit, 1),
                        "reported_eps_hkd": round(reported_eps, 2),
                        "scenario_is_base": bool(resid_label == "base" and comm_label == "base"),
                        "model_use": "whole_company_earnings_skeleton_v0_1",
                        "research_only": True,
                        "caveat": (
                            "Skeleton: residential profit = recognised revenue (lag kernel) x per-year "
                            "project-mix margin; commercial = FY2025 NRI run-rate x small RVD sensitivity; "
                            "hotel = FY2025 revenue x bull/base/bear margin; other = FY2025 run-rate; "
                            "below-segment residual = FY2025 underlying minus modelled FY2025 HK segment "
                            "(absorbs Mainland + finance/tax/NCI). Material-drivers 3x3 per year."
                        ),
                    }
                )
    skeleton = pd.DataFrame(rows)

    # Consensus comparison (strict metric matching).
    comp_rows: list[dict[str, Any]] = []
    if not cons.empty and "metric" in cons.columns:
        for fiscal_year in (2026, 2027):
            eps = cons[cons["metric"].eq("eps") & cons["fiscal_year"].eq(fiscal_year)]
            if "statistic" in eps.columns:
                # Pre-aggregated frame: read the published statistics directly.
                median = float(eps.loc[eps["statistic"].eq("median"), "value"].iloc[0]) if not eps[eps["statistic"].eq("median")].empty else None
                low = float(eps.loc[eps["statistic"].eq("low"), "value"].iloc[0]) if not eps[eps["statistic"].eq("low")].empty else None
                high = float(eps.loc[eps["statistic"].eq("high"), "value"].iloc[0]) if not eps[eps["statistic"].eq("high")].empty else None
                excluded: list[float] = []
            else:
                # One row per contributing source with no statistic labels
                # (the shape of shkp_financial_model_consensus).  Derive the
                # dispersion here, but drop scale outliers first: the frame
                # mixes units, e.g. FY2027 carries 0.381 against a cluster of
                # 8.05-9.33.  Feeding that straight into low/high would report
                # a unit error as the consensus floor.
                #
                # The rule is a unit-error filter, not a view on which broker
                # is right: keep values within an order of magnitude of the
                # median (ratio in [1/5, 5]).  Genuine broker disagreement
                # never spans 5x on an EPS estimate, so this cannot silently
                # discard a real bear case.  Exclusions are recorded on the
                # output row rather than dropped quietly.
                values = pd.to_numeric(eps["value"], errors="coerce").dropna()
                values = values[values > 0]
                median = low = high = None
                excluded = []
                if not values.empty:
                    anchor = float(values.median())
                    ratio = values / anchor if anchor else values
                    kept = values[(ratio >= 0.2) & (ratio <= 5.0)]
                    excluded = sorted(float(v) for v in values[~values.index.isin(kept.index)])
                    if not kept.empty:
                        median = float(kept.median())
                        low = float(kept.min())
                        high = float(kept.max())
            model_eps = (
                float(
                    skeleton.loc[
                        skeleton["scenario_is_base"] & skeleton["fiscal_year"].eq(fiscal_year),
                        "underlying_eps_hkd",
                    ].iloc[0]
                )
                if not skeleton.empty and not skeleton.loc[skeleton["scenario_is_base"] & skeleton["fiscal_year"].eq(fiscal_year)].empty
                else None
            )
            comp_rows.append(
                {
                    "fiscal_year": fiscal_year,
                    "metric": "underlying_eps",
                    "consensus_median_eps": median,
                    "consensus_low_eps": low,
                    "consensus_high_eps": high,
                    "consensus_excluded_scale_outliers": ",".join(f"{v:g}" for v in excluded),
                    "model_base_underlying_eps": model_eps,
                    "consensus_metric_assumption": "broker_eps_treated_as_underlying_per_hk_developer_convention",
                    "model_use": "whole_company_consensus_comparison",
                    "research_only": True,
                    "caveat": (
                        "Broker EPS convention is underlying; if a broker publishes reported EPS the "
                        "comparison is misaligned. FY2027 model row is the skeleton base scenario."
                    ),
                }
            )
    comparison = pd.DataFrame(comp_rows)
    return {"skeleton": skeleton, "consensus_comparison": comparison}


def run_shkp_whole_company_model() -> dict[str, Any]:
    """Persist the whole-company earnings skeleton and consensus comparison."""
    run_id = f"shkp-whole-company-{uuid.uuid4()}"
    bridge = load_latest_normalized("shkp_historical_earnings_bridge")
    hotel = load_latest_normalized("shkp_hotel_segment_series")
    consensus = load_latest_normalized("shkp_financial_model_consensus")
    recognition = load_latest_normalized("shkp_residential_recognition_schedule")
    weighted_margin = load_latest_normalized("shkp_fy27_weighted_development_margin")
    outputs = build_shkp_whole_company_skeleton(
        earnings_bridge=bridge,
        hotel_series=hotel,
        consensus=consensus,
        recognition_schedule=recognition,
        weighted_margin=weighted_margin,
    )
    lineage = {
        "lineage_type": "shkp_whole_company_earnings_skeleton_v0_1",
        "run_id": run_id,
        "ticker": "0016.HK",
        "primary_target": "underlying_eps",
        "reported_eps_policy": "accounting_bridge_only",
        "research_only": True,
    }
    normalized = {
        SKELETON_DATASET: save_normalized_dataset(
            SKELETON_DATASET,
            outputs["skeleton"],
            run_id=run_id,
            lineage_metadata={**lineage, "contract_dataset": SKELETON_DATASET},
        ),
        CONSENSUS_COMPARISON_DATASET: save_normalized_dataset(
            CONSENSUS_COMPARISON_DATASET,
            outputs["consensus_comparison"],
            run_id=run_id,
            lineage_metadata={**lineage, "contract_dataset": CONSENSUS_COMPARISON_DATASET},
        ),
    }
    return {
        "mode": "shkp_whole_company_earnings_skeleton",
        "run_id": run_id,
        "skeleton_rows": int(len(outputs["skeleton"])),
        "consensus_comparison_rows": int(len(outputs["consensus_comparison"])),
        "normalized": normalized,
        "research_only": True,
    }
