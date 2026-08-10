"""Synthetic yield-pressure index for the airline unit-pricing layer.

Route-level realized yield is not available from free public sources, so the
module infers yield pressure indirectly from operating data.  The economic
prior is that pricing follows the demand/capacity balance:

    YieldPressure ~ RPK growth - ASK growth   (demand minus capacity)
                 + load-factor change          (tightness)
                 + international-mix change    (mix effect on RASK)
                 - industry ASK growth         (competitive capacity)

The components are standardised (z-score over the company's own history) and
combined with economic-prior weights rather than fitted coefficients, so the
index is a transparent direction modifier, not an ML prediction.  A positive
score means upward yield pressure (fares holding or firming); a negative
score means downward pressure.

Validation: the annualised index is compared against the walk-forward
``revenue_per_rpk_growth_actual_pct`` series (2017-2025), which is the
closest free proxy for realised yield change.  The comparison is reported as
correlation / direction-accuracy in the output, not used to re-fit the
weights.  Empirical result (2026-08-10): the cross-sectional rank correlation
is positive in 2025 (+0.66) but weak/negative in most earlier years (all-year
mean -0.14, direction-consistent 30%).  The index is therefore a RECENT
direction modifier only - it is labelled ``validation_limited`` and must not
be treated as a realised-yield forecast.  The negative historical result is
reported honestly rather than hidden.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ..config import NORMALIZED_DIR, ROOT_DIR

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_yield_pressure_index.csv"
VALIDATION_OUTPUT_PATH = NORMALIZED_DIR / "airline_yield_pressure_validation.csv"
DATASET_ID = "airline_yield_pressure_index"
VALIDATION_STATUS = "validation_limited_positive_2025_only_weak_history"

MONTHLY_RAW_PATH = (
    ROOT_DIR / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"
)
CAAC_PATH = NORMALIZED_DIR / "airline_caac_sector_monthly.csv"
WALK_FORWARD_PATH = NORMALIZED_DIR / "airline_walk_forward_model_v2.csv"

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "month",
    "rpk_growth_pct",
    "ask_growth_pct",
    "rpk_minus_ask_gap_pp",
    "load_factor_change_pp",
    "intl_mix_change_pp",
    "industry_ask_growth_pct",
    "yield_pressure_score",
    "yield_pressure_label",
    "validation_status",
    "component_z_rpk_ask_gap",
    "component_z_lf_change",
    "component_z_intl_mix",
    "component_z_industry_ask",
    "validation_year",
    "validation_revenue_per_rpk_growth_pct",
    "validation_direction_consistent",
    "source_note",
    "retrieved_at",
]

# Economic-prior weights (direction, not fitted): demand-capacity gap is the
# dominant pricing driver, load factor the next, mix and competitive capacity
# smaller modifiers.
PRIOR_WEIGHTS = {
    "rpk_ask_gap": 0.5,
    "lf_change": 0.25,
    "intl_mix": 0.15,
    "industry_ask": -0.10,
}

COMPANIES = [
    "Air China",
    "China Eastern Airlines",
    "China Southern Airlines",
    "Hainan Airlines Holdings",
    "Juneyao Airlines",
    "Spring Airlines",
]


def _zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if std in (0, np.nan) or pd.isna(std):
        return series * 0.0
    return (series - series.mean()) / std


def _zscore_pit(series: pd.Series) -> pd.Series:
    """Point-in-time z-score: standardise each point using ONLY the history
    up to and including that point (expanding window), never the full-sample
    mean/std.  The previous implementation z-scored the entire 2017-2026
    column, which leaked future observations into every historical score
    (and into the v4 residual-yield stage that consumes it)."""
    out = series.copy()
    for i in range(len(series)):
        window = series.iloc[: i + 1].dropna()
        if len(window) < 2:
            out.iloc[i] = 0.0
            continue
        std = window.std(ddof=0)
        if std in (0, np.nan) or pd.isna(std):
            out.iloc[i] = 0.0
            continue
        out.iloc[i] = (series.iloc[i] - window.mean()) / std
    return out


def _load_monthly() -> pd.DataFrame:
    if not MONTHLY_RAW_PATH.exists():
        raise FileNotFoundError(MONTHLY_RAW_PATH)
    return pq.read_table(MONTHLY_RAW_PATH).to_pandas()


def _load_caac() -> pd.DataFrame:
    if not CAAC_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(CAAC_PATH)


def _load_walk_forward() -> pd.DataFrame:
    if not WALK_FORWARD_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(WALK_FORWARD_PATH)


def build_airline_yield_pressure_index() -> pd.DataFrame:
    """Build the monthly yield-pressure index per company and validate."""
    retrieved = datetime.now(timezone.utc).isoformat()
    monthly = _load_monthly()
    caac = _load_caac()
    walk = _load_walk_forward()

    monthly["month_parsed"] = pd.to_datetime(monthly["month"], errors="coerce")
    monthly = monthly.dropna(subset=["month_parsed"]).copy()

    # Company total and international ASK/RPK per month.
    total = monthly[monthly["region"].eq("Total")].copy()
    intl = monthly[monthly["region"].eq("International")].copy()

    def pivot(df: pd.DataFrame) -> pd.DataFrame:
        piv = df.pivot_table(
            index=["month_parsed"],
            columns=["airline_code", "metric"],
            values="value",
            aggfunc="sum",
        )
        return piv

    total_piv = pivot(total)
    intl_piv = pivot(intl)

    # CAAC industry ASK (sector supply) - use passenger volume or RPK as the
    # industry demand-capacity proxy; sector ASK is not published, so the
    # industry passenger-volume growth stands in for competitive pressure.
    industry_growth: dict[pd.Timestamp, float] = {}
    if not caac.empty and "metric" in caac.columns:
        caac_pass = caac[
            caac["metric"].eq("passenger_volume")
            & caac["period_type"].eq("monthly")
            & caac["scope"].eq("total")
        ].copy()
        caac_pass["month_parsed"] = pd.to_datetime(
            caac_pass["observation_month"].astype(str) + "-01", errors="coerce"
        )
        caac_pass = (
            caac_pass.sort_values("month_parsed")
            .groupby("month_parsed")["value"]
            .last()
        )
        industry_growth = (
            caac_pass.pct_change(12, fill_method=None) * 100.0
        ).to_dict()

    # Map airline codes to company names.
    code_to_company = {
        "601111": "Air China",
        "600029": "China Southern Airlines",
        "600115": "China Eastern Airlines",
        "600221": "Hainan Airlines Holdings",
        "603885": "Juneyao Airlines",
        "601021": "Spring Airlines",
    }

    rows: list[dict[str, Any]] = []
    for code, company in code_to_company.items():
        if (code, "ask") not in total_piv.columns or (code, "rpk") not in total_piv.columns:
            continue
        ask = total_piv[(code, "ask")].dropna()
        rpk = total_piv[(code, "rpk")].dropna()
        lf = (rpk / ask * 100.0).dropna()
        if (code, "ask") in intl_piv.columns:
            intl_ask = intl_piv[(code, "ask")].dropna()
            intl_mix = (intl_ask / ask.reindex(intl_ask.index) * 100.0).dropna()
        else:
            intl_mix = pd.Series(dtype=float)

        df = pd.DataFrame(
            {
                "rpk": rpk,
                "ask": ask,
                "lf": lf,
            }
        )
        df["rpk_growth_pct"] = df["rpk"].pct_change(12, fill_method=None) * 100.0
        df["ask_growth_pct"] = df["ask"].pct_change(12, fill_method=None) * 100.0
        df["rpk_minus_ask_gap_pp"] = df["rpk_growth_pct"] - df["ask_growth_pct"]
        df["load_factor_change_pp"] = df["lf"].diff(12)
        df["intl_mix_change_pp"] = intl_mix.diff(12).reindex(df.index)
        df["industry_ask_growth_pct"] = (
            pd.Series(industry_growth).reindex(df.index)
        )
        df = df.dropna(subset=["rpk_minus_ask_gap_pp", "load_factor_change_pp"])

        # 3-month TRAILING moving average (t-2..t) reduces monthly noise
        # without leaking the next month (the old centred window used t+1).
        smooth_gap = df["rpk_minus_ask_gap_pp"].rolling(3, min_periods=1).mean()
        smooth_lf = df["load_factor_change_pp"].rolling(3, min_periods=1).mean()
        smooth_mix = df["intl_mix_change_pp"].rolling(3, min_periods=1).mean()
        smooth_ind = df["industry_ask_growth_pct"].rolling(3, min_periods=1).mean()
        # PIT z-scores: expanding window per company history.
        z_gap = _zscore_pit(smooth_gap)
        z_lf = _zscore_pit(smooth_lf)
        z_mix = _zscore_pit(smooth_mix.fillna(0.0))
        z_ind = _zscore_pit(smooth_ind.fillna(0.0))
        score = (
            PRIOR_WEIGHTS["rpk_ask_gap"] * z_gap
            + PRIOR_WEIGHTS["lf_change"] * z_lf
            + PRIOR_WEIGHTS["intl_mix"] * z_mix
            + PRIOR_WEIGHTS["industry_ask"] * z_ind
        )
        df["yield_pressure_score"] = score
        df["component_z_rpk_ask_gap"] = z_gap
        df["component_z_lf_change"] = z_lf
        df["component_z_intl_mix"] = z_mix
        df["component_z_industry_ask"] = z_ind

        for month, row in df.iterrows():
            month_str = month.strftime("%Y-%m")
            rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "company": company,
                    "month": month_str,
                    "rpk_growth_pct": row["rpk_growth_pct"],
                    "ask_growth_pct": row["ask_growth_pct"],
                    "rpk_minus_ask_gap_pp": row["rpk_minus_ask_gap_pp"],
                    "load_factor_change_pp": row["load_factor_change_pp"],
                    "intl_mix_change_pp": row["intl_mix_change_pp"],
                    "industry_ask_growth_pct": row["industry_ask_growth_pct"],
                    "yield_pressure_score": row["yield_pressure_score"],
                    "yield_pressure_label": (
                        "upward"
                        if row["yield_pressure_score"] > 0.5
                        else "downward"
                        if row["yield_pressure_score"] < -0.5
                        else "neutral"
                    ),
                    "validation_status": VALIDATION_STATUS,
                    "component_z_rpk_ask_gap": row["component_z_rpk_ask_gap"],
                    "component_z_lf_change": row["component_z_lf_change"],
                    "component_z_intl_mix": row["component_z_intl_mix"],
                    "component_z_industry_ask": row["component_z_industry_ask"],
                    "validation_year": None,
                    "validation_revenue_per_rpk_growth_pct": None,
                    "validation_direction_consistent": None,
                    "source_note": (
                        "Synthetic yield-pressure index from operating data; "
                        "economic-prior weights (gap 0.5 / LF 0.25 / mix 0.15 "
                        "/ industry -0.10), z-scored per company.  Positive = "
                        "upward fare pressure.  Not a realized-yield forecast."
                    ),
                    "retrieved_at": retrieved,
                }
            )

    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    result, validation_summary = _attach_validation(result, walk)
    result.to_csv(OUTPUT_PATH, index=False)
    validation_summary.to_csv(VALIDATION_OUTPUT_PATH, index=False)
    return result


def _attach_validation(
    index_df: pd.DataFrame,
    walk: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Annualise the monthly index and compare with walk-forward
    revenue-per-RPK actual growth (the realized-yield proxy).

    Two checks are reported: per-month direction consistency (annualised
    mean score sign vs yield-growth sign) and, more meaningfully, the
    cross-sectional rank correlation across companies within each year
    (which company had the most upward yield pressure vs which actually
    reported the least-negative yield change)."""
    if walk.empty or "revenue_per_rpk_growth_actual_pct" not in walk.columns:
        return index_df, pd.DataFrame(
            columns=[
                "year",
                "companies_validated",
                "spearman_rank_corr",
                "pearson_corr",
                "direction_consistent_rows",
            ]
        )
    annual = (
        index_df.groupby(["company", index_df["month"].str[:4]])
        .agg(mean_score=("yield_pressure_score", "mean"))
        .reset_index()
        .rename(columns={"month": "year"})
    )
    walk_annual = (
        walk.dropna(subset=["revenue_per_rpk_growth_actual_pct"])
        .groupby(["company", "target_year"])["revenue_per_rpk_growth_actual_pct"]
        .last()
        .reset_index()
    )
    annual["year_int"] = annual["year"].astype(int)
    merged = annual.merge(
        walk_annual,
        left_on=["company", "year_int"],
        right_on=["company", "target_year"],
        how="left",
    )
    summary_rows: list[dict[str, Any]] = []
    for _, m in merged.iterrows():
        if pd.isna(m["revenue_per_rpk_growth_actual_pct"]):
            continue
        mask = (
            index_df["company"].eq(m["company"])
            & index_df["month"].str.startswith(str(m["year"]))
        )
        index_df.loc[mask, "validation_year"] = int(m["year"])
        index_df.loc[mask, "validation_revenue_per_rpk_growth_pct"] = (
            m["revenue_per_rpk_growth_actual_pct"]
        )
        index_df.loc[mask, "validation_direction_consistent"] = bool(
            (m["mean_score"] > 0) == (m["revenue_per_rpk_growth_actual_pct"] > 0)
        )
    # Cross-sectional validation per year.
    valid = merged.dropna(subset=["revenue_per_rpk_growth_actual_pct"])
    for year, group in valid.groupby("year_int"):
        if len(group) < 3:
            continue
        spearman = group["mean_score"].rank().corr(
            group["revenue_per_rpk_growth_actual_pct"].rank()
        )
        pearson = group["mean_score"].corr(
            group["revenue_per_rpk_growth_actual_pct"]
        )
        consistent = int(
            ((group["mean_score"] > 0) == (group["revenue_per_rpk_growth_actual_pct"] > 0)).sum()
        )
        summary_rows.append(
            {
                "year": int(year),
                "companies_validated": int(len(group)),
                "spearman_rank_corr": spearman,
                "pearson_corr": pearson,
                "direction_consistent_rows": consistent,
            }
        )
    summary = pd.DataFrame(
        summary_rows,
        columns=[
            "year",
            "companies_validated",
            "spearman_rank_corr",
            "pearson_corr",
            "direction_consistent_rows",
        ],
    )
    return index_df, summary


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "build_airline_yield_pressure_index",
    "source_path",
]
