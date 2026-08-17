"""Catalyst underwriting + thesis scoreboard for the Spring/Juneyao pair.

Roadmap item 4.  Upgrades the event calendar into a decision tree: every
upcoming event is mapped Event -> OperatingKPI -> EPS -> Thesis, with an
expected sign, magnitude, observable KPI, thesis impact and an explicit
invalidation threshold.  Also produces the thesis scoreboard that
consolidates every layer built so far (unit economics, cost engine,
consensus reverse, valuation) into one row per thesis component.

This is underwriting, not an event calendar: each row answers "which
upcoming event can invalidate or confirm the thesis, and what will I
observe first?"
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR

logger = logging.getLogger(__name__)


CATALYST_OUTPUT_PATH = NORMALIZED_DIR / "airline_catalyst_underwriting.csv"
SCOREBOARD_OUTPUT_PATH = NORMALIZED_DIR / "airline_thesis_scoreboard.csv"
DATASET_ID = "airline_catalyst_underwriting"

CALENDAR_PATH = NORMALIZED_DIR / "airline_catalyst_calendar.csv"
SENSITIVITY_PATH = NORMALIZED_DIR / "airline_earnings_sensitivity.csv"
SURPRISE_PATH = NORMALIZED_DIR / "airline_earnings_model_v4_surprise.csv"
SANITY_PATH = NORMALIZED_DIR / "airline_consensus_reverse_v2_sanity.csv"
VALUATION_PATH = NORMALIZED_DIR / "airline_valuation_v2_pair.csv"
CAPACITY_PATH = NORMALIZED_DIR / "airline_capacity_pipeline.csv"
UNIT_ECONOMICS_PATH = NORMALIZED_DIR / "airline_unit_economics.csv"
COST_ABLATION_PATH = NORMALIZED_DIR / "airline_cost_engine_v2_ablation.csv"
REVERSE_SURFACE_PATH = NORMALIZED_DIR / "airline_consensus_reverse_v2_surface.csv"
SANITY_PATH = NORMALIZED_DIR / "airline_consensus_reverse_v2_sanity.csv"


def _num(value: object) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _row(frame: pd.DataFrame, **criteria: object) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=object)
    mask = pd.Series(True, index=frame.index)
    for column, value in criteria.items():
        if column not in frame.columns:
            return pd.Series(dtype=object)
        mask &= frame[column].eq(value)
    rows = frame.loc[mask]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _build_catalyst_rows(
    calendar: pd.DataFrame,
    sensitivity: pd.DataFrame,
    surprise: pd.DataFrame,
    sanity: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Pair-focused catalyst tree: Event -> KPI -> EPS -> Thesis."""
    # Seasonality-adjusted surprise (consensus-reverse-v2 sanity table), not
    # the x2 convention - consistent with the thesis scoreboard.
    sp_surprise = _num(_row(sanity, company="Spring Airlines").get("surprise_vs_consensus_season_adj_pct"))
    jy_surprise = _num(_row(sanity, company="Juneyao Airlines").get("surprise_vs_consensus_season_adj_pct"))
    # Fuel sensitivity from the 3D surface (yield 0, fuel +5, FX 0 for the
    # fuel-only shock on the pair).
    def fuel_eps_shock(company: str) -> float | None:
        row = _row(
            sensitivity,
            company=company,
            model_name="walk_forward_integrated",
            horizon="H1-2026",
            yield_shock_pct=0.0,
            fuel_shock_pct=5.0,
            fx_shock_pct=0.0,
        )
        base = _num(row.get("base_eps_rmb"))
        shocked = _num(row.get("shocked_eps_rmb"))
        if base in (None, 0) or shocked is None:
            return None
        return (shocked / base - 1.0) * 100.0

    def yield_eps_shock(company: str) -> float | None:
        row = _row(
            sensitivity,
            company=company,
            model_name="walk_forward_integrated",
            horizon="H1-2026",
            yield_shock_pct=-3.0,
            fuel_shock_pct=0.0,
            fx_shock_pct=0.0,
        )
        base = _num(row.get("base_eps_rmb"))
        shocked = _num(row.get("shocked_eps_rmb"))
        if base in (None, 0) or shocked is None:
            return None
        return (shocked / base - 1.0) * 100.0

    spring_fuel = fuel_eps_shock("Spring Airlines")
    juneyao_fuel = fuel_eps_shock("Juneyao Airlines")
    spring_yield = yield_eps_shock("Spring Airlines")
    juneyao_yield = yield_eps_shock("Juneyao Airlines")

    rows: list[dict[str, Any]] = []
    # ---- 1H2026 reports (the core catalyst) ----
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "event_id": "cat_earnings_1h26",
            "event_category": "earnings_report",
            "event_name": "1H2026 interim reports",
            "event_window_start": "2026-08-29",
            "event_window_end": "2026-08-31",
            "affected_companies": "Spring (08-29) / Juneyao (08-31)",
            "expected_sign": "Spring beat, Juneyao beat-less",
            "magnitude_hypothesis": (
                f"v4 season-adjusted surprise: Spring {sp_surprise:+.0f}% vs "
                f"Juneyao {jy_surprise:+.0f}% vs consensus"
                if sp_surprise is not None and jy_surprise is not None
                else "surprise data missing"
            ),
            "observable_kpi": "H1 ASK/RPK/LF, RASK, CASK, attributable profit",
            "earnings_link": "reported EPS vs consensus and vs v4 pre-event",
            "thesis_impact": "Confirms or invalidates the core expectation gap",
            "invalidation_threshold": (
                "Spring surprise < Juneyao surprise, or Spring misses "
                "consensus on season-adjusted EPS, or Juneyao beats by more "
                "than Spring on a season-adjusted basis."
            ),
        }
    )
    # ---- fuel (the largest shared risk) ----
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "event_id": "cat_fuel_h2",
            "event_category": "fuel",
            "event_name": "Jet fuel price into H2",
            "event_window_start": "2026-09-01",
            "event_window_end": "2026-12-31",
            "affected_companies": "both (relative sensitivity)",
            "expected_sign": "neutral-to-negative on both, pair roughly hedged",
            "magnitude_hypothesis": (
                f"fuel +5% EPS impact: Spring {spring_fuel:+.1f}% vs "
                f"Juneyao {juneyao_fuel:+.1f}%"
                if spring_fuel is not None and juneyao_fuel is not None
                else "fuel sensitivity missing"
            ),
            "observable_kpi": "EIA jet fuel benchmark, monthly",
            "earnings_link": "fuel CASK -> operating margin",
            "thesis_impact": "Shared risk; pair spread should be near-hedged",
            "invalidation_threshold": (
                "Juneyao's RELATIVE fuel sensitivity is materially higher "
                "(fuel +5% EPS impact Spring -11% vs Juneyao -36%) because "
                "its EPS base is smaller - this supports the short leg but "
                "means a large fuel move (>10% within the print month) "
                "would dominate the pair surprise either way."
            ),
        }
    )
    # ---- yield / pricing ----
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "event_id": "cat_yield_golden_week",
            "event_category": "yield",
            "event_name": "Golden Week + summer yield test",
            "event_window_start": "2026-10-01",
            "event_window_end": "2026-10-08",
            "affected_companies": "Spring (LCC elasticity) vs Juneyao",
            "expected_sign": "Spring RPK-ASK gap stays positive",
            "magnitude_hypothesis": (
                f"yield -3% EPS impact: Spring {spring_yield:+.1f}% vs "
                f"Juneyao {juneyao_yield:+.1f}%"
                if spring_yield is not None and juneyao_yield is not None
                else "yield sensitivity missing"
            ),
            "observable_kpi": "H1 RPK-ASK gap, LF, monthly revenue/ASK",
            "earnings_link": "yield -> RASK -> revenue",
            "thesis_impact": "Spring's yield elasticity is the edge; if it does not show, the LCC premium case weakens",
            "invalidation_threshold": "Spring RPK-ASK gap turns negative or LF gap vs Juneyao narrows below ~2pp.",
        }
    )
    # ---- Juneyao international ramp ----
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "event_id": "cat_juneyao_intl",
            "event_category": "international_ramp",
            "event_name": "Juneyao international capacity ramp",
            "event_window_start": "2026-09-01",
            "event_window_end": "2026-12-31",
            "affected_companies": "Juneyao (short leg)",
            "expected_sign": "negative for Juneyao margin conversion",
            "magnitude_hypothesis": "Consensus implies Juneyao RASK +14% vs our model - the market is more bullish on Juneyao yield than operations justify",
            "observable_kpi": "Juneyao international ASK mix, utilisation, yield",
            "earnings_link": "international mix -> utilisation + yield + airport cost -> margin",
            "thesis_impact": "Core of the short thesis: margin conversion from international recovery",
            "invalidation_threshold": "Juneyao reports international yield/margin conversion in line with consensus (RASK gap closes to <5%).",
        }
    )
    # ---- HSR (the structural substitute) ----
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "event_id": "cat_hsr",
            "event_category": "hsr",
            "event_name": "HSR openings on trunk routes",
            "event_window_start": "2026-09-01",
            "event_window_end": "2027-06-30",
            "affected_companies": "both domestic-heavy",
            "expected_sign": "mild negative on domestic yield",
            "magnitude_hypothesis": "HSR substitution caps domestic fare upside; more relevant for Juneyao's domestic trunk exposure",
            "observable_kpi": "new HSR line openings, domestic RASK",
            "earnings_link": "domestic trunk pricing -> yield -> RASK",
            "thesis_impact": "Supports the short leg if it pressures Juneyao's domestic mix",
            "invalidation_threshold": "Not a near-term catalyst before the print; monitor for H2 guidance.",
        }
    )
    # ---- RMB (cost side, leases/fuel) ----
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "event_id": "cat_fx",
            "event_category": "fx",
            "event_name": "RMB vs USD into H2",
            "event_window_start": "2026-09-01",
            "event_window_end": "2026-12-31",
            "affected_companies": "both (fuel + leases + finance)",
            "expected_sign": "RMB appreciation helps; depreciation hurts",
            "magnitude_hypothesis": "FX shock -3%/+3% in the 3D surface; second-order vs fuel",
            "observable_kpi": "USD/CNY, monthly",
            "earnings_link": "fuel/leases/finance -> NI",
            "thesis_impact": "Shared risk; small relative difference",
            "invalidation_threshold": "Only a >5% move within the month of the print would dominate.",
        }
    )
    return rows


def _build_scoreboard(
    unit: pd.DataFrame,
    capacity: pd.DataFrame,
    surprise: pd.DataFrame,
    valuation: pd.DataFrame,
    cost_abl: pd.DataFrame,
    reverse_surface: pd.DataFrame,
    sanity: pd.DataFrame,
) -> list[dict[str, Any]]:
    """One row per thesis component with the Spring/Juneyao edge."""
    def ue_val(company: str, col: str) -> float | None:
        return _num(_row(unit, company=company, period="FY2025").get(col))

    def cap_val(company: str, col: str) -> float | None:
        return _num(_row(capacity, company=company).get(col))

    # Use the SEASONALITY-ADJUSTED surprise (consensus-reverse-v2 sanity
    # table), not the x2 convention - Juneyao's x2 understates its FY EPS.
    sp_surp = _num(_row(sanity, company="Spring Airlines").get("surprise_vs_consensus_season_adj_pct"))
    jy_surp = _num(_row(sanity, company="Juneyao Airlines").get("surprise_vs_consensus_season_adj_pct"))
    sp_rask_gap = _num(_row(reverse_surface, company="Spring Airlines").get("implied_rask_gap_vs_model_pct"))
    jy_rask_gap = _num(_row(reverse_surface, company="Juneyao Airlines").get("implied_rask_gap_vs_model_pct"))

    rows = [
        {
            "dataset_id": "airline_thesis_scoreboard",
            "component": "Capacity",
            "spring": "ASK +15.4% H1 (strong)",
            "juneyao": "ASK +1.1% H1 (muted)",
            "edge": "Spring",
            "evidence": "H1 ASK YoY from expectation bridge / capacity pipeline",
            "status": "confirmed_pre_event",
        },
        {
            "dataset_id": "airline_thesis_scoreboard",
            "component": "Load factor",
            "spring": f"LF {ue_val('Spring Airlines','passenger_load_factor_pct'):.1f}% (FY25)",
            "juneyao": f"LF {ue_val('Juneyao Airlines','passenger_load_factor_pct'):.1f}% (FY25)",
            "edge": "Spring",
            "evidence": "unit economics FY2025",
            "status": "confirmed_pre_event",
        },
        {
            "dataset_id": "airline_thesis_scoreboard",
            "component": "Yield (key uncertainty)",
            "spring": f"consensus needs RASK {sp_rask_gap:+.1f}% vs ours" if sp_rask_gap is not None else "n/a",
            "juneyao": f"consensus needs RASK {jy_rask_gap:+.1f}% vs ours" if jy_rask_gap is not None else "n/a",
            "edge": "Spring (consensus asks less of Spring yield)",
            "evidence": "consensus reverse surface",
            "status": "variant_perception",
        },
        {
            "dataset_id": "airline_thesis_scoreboard",
            "component": "Fuel CASK",
            "spring": "0.167 (FY25 anchor, +66% spot vs FY25 avg flagged)",
            "juneyao": "0.182",
            "edge": "Spring (lower fuel intensity)",
            "evidence": "cost engine v2",
            "status": "shared_risk_hedged",
        },
        {
            "dataset_id": "airline_thesis_scoreboard",
            "component": "Non-fuel CASK",
            "spring": "0.199 (FY25)",
            "juneyao": "0.235",
            "edge": "Spring (+15% structural advantage)",
            "evidence": "unit economics FY2025",
            "status": "confirmed_pre_event",
        },
        {
            "dataset_id": "airline_thesis_scoreboard",
            "component": "International mix",
            "spring": "low intl share (LCC domestic)",
            "juneyao": "international ramp underway",
            "edge": "Juneyao risk (margin conversion unknown)",
            "evidence": "capacity pipeline / thesis docs",
            "status": "key_uncertainty_short_leg",
        },
        {
            "dataset_id": "airline_thesis_scoreboard",
            "component": "Earnings vs Street",
            "spring": f"{sp_surp:+.1f}% (season-adj)" if sp_surp is not None else "n/a",
            "juneyao": f"{jy_surp:+.1f}% (season-adj)" if jy_surp is not None else "n/a",
            "edge": "Spring, but gap narrowed from 46pp (x2) to ~9pp (season-adj)",
            "evidence": "consensus-reverse-v2 sanity (seasonality-adjusted)",
            "status": "confirmed_pre_event",
        },
        {
            "dataset_id": "airline_thesis_scoreboard",
            "component": "Valuation",
            "spring": "PE_street 20.9x / PE_own 12.5x / P/B 1y pct 10%",
            "juneyao": "PE_street 27.0x / PE_own 17.1x / P/B 1y pct 18%",
            "edge": "Spring (cheaper both ways + low P/B percentile)",
            "evidence": "valuation v2",
            "status": "confirmed_pre_event",
        },
        {
            "dataset_id": "airline_thesis_scoreboard",
            "component": "Cost model improvement",
            "spring": "n/a (pair-level)",
            "juneyao": "n/a",
            "edge": "cost MAE 18.8% -> 11.6% (engine-wide)",
            "evidence": "cost engine v2 ablation",
            "status": "engine_upgrade",
        },
        {
            "dataset_id": "airline_thesis_scoreboard",
            "component": "Catalyst",
            "spring": "1H26 report 08-29",
            "juneyao": "1H26 report 08-31",
            "edge": "Spring prints first",
            "evidence": "catalyst calendar",
            "status": "upcoming_2_3_weeks",
        },
        {
            "dataset_id": "airline_thesis_scoreboard",
            "component": "Risk (one-offs)",
            "spring": "1H25 other income 651m = 32% of PBT - persistence unknown",
            "juneyao": "1H25 other income 577m = 98% of PBT",
            "edge": "both flagged; Spring less exposed in % terms",
            "evidence": "consensus reverse sanity checks",
            "status": "watch_item",
        },
    ]
    return rows


def build_airline_catalyst_underwriting() -> dict[str, pd.DataFrame]:
    """Build catalyst tree + thesis scoreboard."""
    retrieved = datetime.now(timezone.utc).isoformat()
    calendar = pd.read_csv(CALENDAR_PATH)
    sensitivity = pd.read_csv(SENSITIVITY_PATH)
    surprise = pd.read_csv(SURPRISE_PATH)
    sanity = pd.read_csv(SANITY_PATH)
    valuation = pd.read_csv(VALUATION_PATH)
    capacity = pd.read_csv(CAPACITY_PATH)
    unit = pd.read_csv(UNIT_ECONOMICS_PATH)
    cost_abl = pd.read_csv(COST_ABLATION_PATH)
    reverse_surface = pd.read_csv(REVERSE_SURFACE_PATH)
    sanity = pd.read_csv(SANITY_PATH)

    catalyst = pd.DataFrame(_build_catalyst_rows(calendar, sensitivity, surprise, sanity))
    catalyst["retrieved_at"] = retrieved
    catalyst.to_csv(CATALYST_OUTPUT_PATH, index=False)

    scoreboard = pd.DataFrame(
        _build_scoreboard(unit, capacity, surprise, valuation, cost_abl, reverse_surface, sanity)
    )
    scoreboard["retrieved_at"] = retrieved
    scoreboard.to_csv(SCOREBOARD_OUTPUT_PATH, index=False)

    return {"catalyst": catalyst, "scoreboard": scoreboard}


__all__ = [
    "CATALYST_OUTPUT_PATH",
    "SCOREBOARD_OUTPUT_PATH",
    "build_airline_catalyst_underwriting",
]
