"""Project Margin v0.2 - consensus and sensitivity layer (Tier 1, step 3).

The aggregate EPS is now close to consensus (model 8.59 vs 8.65).  The
valuable output is therefore no longer the level but the conditional
disagreement: WHICH project KPIs could move FY2027 margin away from
29-30%, and by how much in EPS terms.

Four deliverables (user-directed):

1. 60 phases -> 5-8 material project groups with revenue weights.
2. Per-group 1pp-margin -> EPS sensitivity (recognised revenue x 1% /
   shares), so research effort concentrates on the few EPS-relevant
   projects instead of 60 phases equally.
3. Consensus-required margin per group: holding other groups at model
   assumptions, the margin a single group needs to explain the
   consensus-implied 29.6% (feasible combinations, not a unique
   decomposition - one equation, many unknowns).
4. Catalyst map: observable KPI -> margin revision direction -> EPS
   revision, per material group, so the model becomes a live earnings
   tracking tool rather than a frozen spreadsheet.
"""

from __future__ import annotations

from typing import Any
import uuid

import pandas as pd

from .storage import load_latest_normalized, save_normalized_dataset


GROUP_SENSITIVITY_DATASET = "shkp_margin_group_sensitivity"
CONSENSUS_REQUIRED_DATASET = "shkp_margin_consensus_required"
CATALYST_DATASET = "shkp_margin_catalyst_map"

SHARES_MILLION = 2896.0
# The 29.6% consensus-implied margin is derived from FY2027 broker EPS less
# non-residential run-rates.  It describes one year, so everything compared
# against it must be that same year -- see CONSENSUS_FISCAL_YEAR below.
CONSENSUS_IMPLIED_MARGIN = 0.296
CONSENSUS_FISCAL_YEAR = 2027


# Material project groups for FY2027 recognition (revenue weight >= ~1%).
# Grouping preserves margin-homogeneity: luxury/high-end vs mass-market.
_GROUP_RULES = [
    ("Sierra Sea", "SAI SHA RESIDENCES", "low"),
    ("Cullinan Sky", "CULLINAN SKY DEVELOPMENT", None),  # mixed: split by phase ASP
    ("NOVO LAND", "NOVO LAND", None),
    ("Lime Spark", "LIME SPARK", "low"),
    ("Cullinan Harbour", "CULLINAN HARBOUR DEVELOPMENT", "high"),
    ("Victoria Harbour", "VICTORIA HARBOUR DEVELOPMENT", "high"),
    ("St Michel", "ST MICHEL DEVELOPMENT", "high"),
    ("Other", None, None),
]


def build_shkp_margin_group_sensitivity(
    project_model: pd.DataFrame,
    target_fiscal_year: int = CONSENSUS_FISCAL_YEAR,
) -> pd.DataFrame:
    """Group one fiscal year's projects into weights, margins and 1pp EPS sensitivity.

    ``shkp_project_margin_model`` holds both FY2026 and FY2027 rows, so pooling
    it unfiltered blends two years of recognised revenue into one weight base
    and then compares it against a single-year consensus margin.  The year is
    therefore explicit and carried on the output.
    """
    if project_model is None or project_model.empty:
        return pd.DataFrame()
    frame = project_model.copy()
    if "fiscal_year" in frame.columns:
        frame = frame[frame["fiscal_year"].astype(int).eq(int(target_fiscal_year))].copy()
    if frame.empty:
        return pd.DataFrame()
    # Cullinan Sky phase split: phase 2 (ASP 22m) is high, phase 1 (ASP 13m)
    # is mid - keep them separate as Cullinan Sky 2 / Cullinan Sky 1.
    def _group_name(row: pd.Series) -> str:
        dev = str(row.get("development_name") or "")
        if dev == "CULLINAN SKY DEVELOPMENT":
            asp = row.get("asp_per_unit_hkd")
            return "Cullinan Sky 2 (luxury)" if asp is not None and asp >= 18_000_000 else "Cullinan Sky 1"
        if dev == "SAI SHA RESIDENCES":
            return "Sierra Sea"
        if dev == "NOVO LAND":
            return "NOVO LAND"
        if dev == "LIME SPARK":
            return "Lime Spark"
        if dev == "CULLINAN HARBOUR DEVELOPMENT":
            return "Cullinan Harbour"
        if dev == "VICTORIA HARBOUR DEVELOPMENT":
            return "Victoria Harbour"
        if dev == "ST MICHEL DEVELOPMENT":
            return "St Michel"
        return "Other"

    frame["group"] = frame.apply(_group_name, axis=1)
    # Revenue-weighted, not a plain phase mean: the caveat below has always
    # described it that way, and an unweighted mean lets a small phase move a
    # group's margin as much as a large one -- so the group margins would not
    # aggregate back to the portfolio margin they are compared against.
    def _weighted(column: str) -> pd.Series:
        weighted = frame["recognised_revenue_hkd"] * frame[column]
        return weighted.groupby(frame["group"]).sum() / frame.groupby("group")["recognised_revenue_hkd"].sum()

    grouped = frame.groupby("group").agg(
        recognised_revenue_hkd=("recognised_revenue_hkd", "sum"),
        n_phases=("phase_name", "count"),
    ).reset_index()
    for column in ("margin_point", "margin_low", "margin_high"):
        grouped[column] = grouped["group"].map(_weighted(column))
    grouped.insert(0, "fiscal_year", int(target_fiscal_year))
    total = float(grouped["recognised_revenue_hkd"].sum())
    grouped["revenue_weight_pct"] = grouped["recognised_revenue_hkd"] / total * 100.0
    grouped["eps_per_1pp_margin"] = grouped["recognised_revenue_hkd"] * 0.01 / (SHARES_MILLION * 1e6)
    grouped["eps_range_margin_bucket"] = (
        grouped["recognised_revenue_hkd"] * (grouped["margin_high"] - grouped["margin_low"]) / (SHARES_MILLION * 1e6)
    )
    grouped = grouped.sort_values("recognised_revenue_hkd", ascending=False).reset_index(drop=True)
    grouped["model_use"] = "margin_group_sensitivity"
    grouped["research_only"] = True
    grouped["caveat"] = (
        "EPS per 1pp margin = recognised revenue x 1% / shares. Group margin is the revenue-weighted "
        "phase mean; Cullinan Sky is split by phase ASP (luxury 2 vs 1). Concentrate research on "
        "groups with high EPS-per-1pp."
    )
    return grouped


def build_shkp_margin_consensus_required(group_sensitivity: pd.DataFrame) -> pd.DataFrame:
    """Feasible margin per group needed to explain the consensus margin."""
    if group_sensitivity is None or group_sensitivity.empty:
        return pd.DataFrame()
    frame = group_sensitivity.copy()
    # CONSENSUS_IMPLIED_MARGIN describes one fiscal year.  Comparing it against
    # groups built for another year (or a blend of years) silently yields a
    # required-margin delta with the wrong magnitude and, when the two years
    # straddle consensus, the wrong sign.
    years = {int(year) for year in frame.get("fiscal_year", pd.Series(dtype=int)).dropna().unique()}
    if years and years != {CONSENSUS_FISCAL_YEAR}:
        raise ValueError(
            f"consensus-required margin is defined for FY{CONSENSUS_FISCAL_YEAR} only, "
            f"but the group sensitivity covers {sorted(years)}"
        )
    model_weighted = float((frame["recognised_revenue_hkd"] * frame["margin_point"]).sum() / frame["recognised_revenue_hkd"].sum())
    delta_total = CONSENSUS_IMPLIED_MARGIN - model_weighted
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        weight = row["revenue_weight_pct"] / 100.0
        required_delta = delta_total / weight if weight > 0 else None
        required_margin = row["margin_point"] + required_delta if required_delta is not None else None
        feasible = bool(
            required_margin is not None
            and required_margin >= row["margin_low"] - 0.02
            and required_margin <= row["margin_high"] + 0.02
        )
        rows.append(
            {
                "group": row["group"],
                "revenue_weight_pct": row["revenue_weight_pct"],
                "model_margin_point": row["margin_point"],
                "model_margin_range": f"{row['margin_low']:.1%}-{row['margin_high']:.1%}",
                "consensus_required_margin_delta_pp": (required_delta * 100.0) if required_delta is not None else None,
                "consensus_required_margin": required_margin,
                "feasible_within_bucket_plus_2pp": feasible,
                "eps_impact_if_at_required_margin": (
                    row["eps_per_1pp_margin"] * (required_delta * 100.0) if required_delta is not None else None
                ),
                "model_use": "consensus_required_margin_feasibility",
                "research_only": True,
                "caveat": (
                    "One equation (weighted margin = 29.6%) with many unknowns: each row shows the margin "
                    "a SINGLE group would need if all other groups stay at model assumptions. This is a "
                    "feasibility check, NOT a unique decomposition of what consensus believes."
                ),
            }
        )
    return pd.DataFrame(rows)


def _build_catalyst_map(group_sensitivity: pd.DataFrame) -> pd.DataFrame:
    """Observable KPI -> margin revision -> EPS revision per material group.

    Each row names the KPIs that can be tracked from public sources (SRPE
    register batches, project websites, press) and the direction each KPI
    moves the group's margin estimate, plus the EPS magnitude of a +-3pp
    margin revision (the consensus-risk band).  This turns the static
    bucket model into a live earnings-tracking tool.
    """
    if group_sensitivity is None or group_sensitivity.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for _, row in group_sensitivity.iterrows():
        group = row["group"]
        if group == "Other":
            kpis = "dispersed; follow aggregate SRPE register volume and discounting press"
        elif group in ("Sierra Sea", "Lime Spark"):
            kpis = "launch vs subsequent batch ASP; rebates/incentives; sales velocity; unit mix; premium vs nearby secondary"
        elif group in ("NOVO LAND",):
            kpis = "batch ASP trend; incentive packages; absorption pace; Tuen Mun secondary premium"
        elif group in ("Cullinan Sky 1", "Cullinan Sky 2 (luxury)"):
            kpis = "high-end ASP momentum; buyer profile; luxury secondary premium; sales velocity at top price points"
        elif group in ("Cullinan Harbour", "Victoria Harbour"):
            kpis = "super-luxury ASP; single-transaction level; demand concentration; price negotiation depth"
        else:
            kpis = "batch ASP and sell-through"
        eps_3pp = float(row["eps_per_1pp_margin"] * 3.0)
        rows.append(
            {
                "group": group,
                "revenue_weight_pct": row["revenue_weight_pct"],
                "observable_kpis": kpis,
                "bull_direction": "ASP upside / no discounting / strong velocity -> margin toward bucket high",
                "bear_direction": "price cuts / incentives / weak absorption -> margin toward bucket low",
                "eps_revision_per_3pp_margin": eps_3pp,
                "research_priority": (
                    "high"
                    if eps_3pp >= 0.05
                    else "medium" if eps_3pp >= 0.02
                    else "low"
                ),
                "model_use": "margin_catalyst_map",
                "research_only": True,
                "caveat": (
                    "Catalyst map is directional: observable KPIs revise the margin ESTIMATE within the "
                    "bucket range, they do not measure actual project costs. EPS revision uses +-3pp as "
                    "the consensus-risk band."
                ),
            }
        )
    return pd.DataFrame(rows)


def run_shkp_margin_variant() -> dict[str, Any]:
    """Persist the group sensitivity and consensus-required layers."""
    run_id = f"shkp-margin-variant-{uuid.uuid4()}"
    projects = load_latest_normalized("shkp_project_margin_model")
    groups = build_shkp_margin_group_sensitivity(projects)
    required = build_shkp_margin_consensus_required(groups)
    catalysts = _build_catalyst_map(groups)
    lineage = {
        "lineage_type": "shkp_margin_variant_analysis",
        "run_id": run_id,
        "research_only": True,
        "consensus_implied_margin": CONSENSUS_IMPLIED_MARGIN,
    }
    normalized = {
        GROUP_SENSITIVITY_DATASET: save_normalized_dataset(
            GROUP_SENSITIVITY_DATASET,
            groups,
            run_id=run_id,
            lineage_metadata={**lineage, "contract_dataset": GROUP_SENSITIVITY_DATASET},
        ),
        CONSENSUS_REQUIRED_DATASET: save_normalized_dataset(
            CONSENSUS_REQUIRED_DATASET,
            required,
            run_id=run_id,
            lineage_metadata={**lineage, "contract_dataset": CONSENSUS_REQUIRED_DATASET},
        ),
        CATALYST_DATASET: save_normalized_dataset(
            CATALYST_DATASET,
            catalysts,
            run_id=run_id,
            lineage_metadata={**lineage, "contract_dataset": CATALYST_DATASET},
        ),
    }
    return {
        "mode": "shkp_margin_variant_analysis",
        "run_id": run_id,
        "group_rows": int(len(groups)),
        "required_rows": int(len(required)),
        "catalyst_rows": int(len(catalysts)),
        "normalized": normalized,
        "research_only": True,
    }
