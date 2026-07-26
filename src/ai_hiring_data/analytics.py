"""Pure, data-backed rollups used by the AI Hiring dashboard.

These helpers deliberately do not invent observations.  They only aggregate
the latest public ATS snapshot or the observed history and preserve empty
states when the cohort is not mature enough.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from ai_hiring_data.classify import SENIORITY_LEVELS
from ai_hiring_data.config import ROLE_FAMILIES


def _numeric(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column not in result:
            result[column] = 0
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0)
    return result


def build_company_intensity(
    demand: pd.DataFrame,
    parent_segment_by_company: Mapping[str, str],
) -> pd.DataFrame:
    """Return one latest all-role row per company for the intensity scatter."""

    if demand.empty:
        return pd.DataFrame(
            columns=[
                "company_id", "company_name", "company_segment", "parent_segment",
                "active_requisitions", "active_postings", "ai_role_postings", "ai_role_share_pct",
            ]
        )
    frame = demand.copy()
    frame["snapshot_date"] = pd.to_datetime(frame.get("snapshot_date"), errors="coerce")
    frame = frame[frame.get("role_family", "").astype(str).eq("All roles")]
    if frame.empty:
        return frame
    latest_date = frame["snapshot_date"].max()
    frame = frame[frame["snapshot_date"].eq(latest_date)].copy()
    frame = _numeric(frame, ("active_requisitions", "active_postings", "ai_role_postings"))
    frame["ai_role_share_pct"] = (
        frame["ai_role_postings"].div(frame["active_postings"].replace(0, pd.NA)).mul(100).fillna(0)
    )
    frame["parent_segment"] = frame["company_id"].map(parent_segment_by_company).fillna("Unmapped")
    return frame.sort_values(["active_requisitions", "company_name"], ascending=[False, True]).reset_index(drop=True)


def build_early_cohort_trend(demand: pd.DataFrame, min_observations: int = 2) -> pd.DataFrame:
    """Aggregate observed all-role history for the mature early cohort only."""

    if demand.empty:
        return pd.DataFrame()
    frame = demand.copy()
    frame["snapshot_date"] = pd.to_datetime(frame.get("snapshot_date"), errors="coerce")
    frame = frame[frame.get("role_family", "").astype(str).eq("All roles")].dropna(subset=["snapshot_date"])
    if frame.empty:
        return pd.DataFrame()
    counts = frame.groupby("company_id")["snapshot_date"].nunique()
    cohort = counts[counts >= int(min_observations)].index
    frame = frame[frame["company_id"].isin(cohort)].copy()
    if frame.empty:
        return pd.DataFrame()
    frame = _numeric(frame, ("active_requisitions", "active_postings", "ai_role_postings"))
    return (
        frame.groupby("snapshot_date", as_index=False)
        .agg(
            active_requisitions=("active_requisitions", "sum"),
            active_postings=("active_postings", "sum"),
            ai_role_postings=("ai_role_postings", "sum"),
            company_count=("company_id", "nunique"),
        )
        .sort_values("snapshot_date")
        .reset_index(drop=True)
    )


def build_role_seniority_matrix(jobs: pd.DataFrame, mode: str = "count") -> pd.DataFrame:
    """Build the exact role-family x production seniority matrix.

    ``mode='count'`` returns unique active postings; ``mode='share'`` returns
    each role family's percentage mix across seniority levels.
    """

    index = list(ROLE_FAMILIES)
    if jobs.empty:
        return pd.DataFrame(0.0, index=index, columns=SENIORITY_LEVELS)
    frame = jobs.copy()
    frame["status"] = frame.get("status", "").astype(str)
    frame = frame[frame["status"].eq("active")]
    if frame.empty:
        return pd.DataFrame(0.0, index=index, columns=SENIORITY_LEVELS)
    frame["role_family"] = frame.get("role_family", "Other").fillna("Other").astype(str)
    frame["seniority"] = frame.get("seniority", SENIORITY_LEVELS[1]).fillna(SENIORITY_LEVELS[1]).astype(str)
    values = frame.get("source_job_id", pd.Series(frame.index, index=frame.index)).astype(str)
    matrix = (
        pd.crosstab(frame["role_family"], frame["seniority"], values=values, aggfunc="nunique")
        .reindex(index=index, columns=SENIORITY_LEVELS, fill_value=0)
        .fillna(0)
        .astype(float)
    )
    if mode == "share":
        totals = matrix.sum(axis=1).replace(0, pd.NA)
        matrix = matrix.div(totals, axis=0).mul(100).fillna(0)
    return matrix


def build_seniority_totals(matrix: pd.DataFrame) -> pd.DataFrame:
    """Return a tidy seniority total table suitable for a concentration chart."""

    if matrix.empty:
        return pd.DataFrame(columns=["seniority", "active_postings"])
    return (
        matrix.sum(axis=0)
        .rename("active_postings")
        .rename_axis("seniority")
        .reset_index()
        .sort_values("active_postings", ascending=False)
        .reset_index(drop=True)
    )
