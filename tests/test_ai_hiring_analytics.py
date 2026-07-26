from __future__ import annotations

import pandas as pd

from ai_hiring_data.analytics import (
    SENIORITY_LEVELS,
    build_company_intensity,
    build_early_cohort_trend,
    build_role_seniority_matrix,
    build_seniority_totals,
)
from ai_hiring_data.config import BOARD_SPECS, ROLE_FAMILIES
from ai_hiring_data.segments import PARENT_SEGMENT_BY_COMPANY, parent_segment_for_company


def test_parent_segment_mapping_covers_every_configured_board() -> None:
    company_ids = {spec.company_id for spec in BOARD_SPECS}
    assert company_ids == set(PARENT_SEGMENT_BY_COMPANY)
    assert parent_segment_for_company("unknown") == "Unmapped"


def test_company_intensity_uses_latest_all_role_rows_only() -> None:
    demand = pd.DataFrame(
        [
            {"snapshot_date": "2026-07-01", "company_id": "a", "company_name": "A", "role_family": "All roles", "active_requisitions": 4, "active_postings": 8, "ai_role_postings": 2},
            {"snapshot_date": "2026-07-02", "company_id": "a", "company_name": "A", "role_family": "All roles", "active_requisitions": 6, "active_postings": 10, "ai_role_postings": 5},
            {"snapshot_date": "2026-07-02", "company_id": "a", "company_name": "A", "role_family": "Research", "active_requisitions": 2, "active_postings": 3, "ai_role_postings": 3},
        ]
    )
    result = build_company_intensity(demand, {"a": "Foundation & model platforms"})
    assert len(result) == 1
    assert result.iloc[0]["active_requisitions"] == 6
    assert result.iloc[0]["ai_role_share_pct"] == 50


def test_early_cohort_requires_repeated_observations() -> None:
    demand = pd.DataFrame(
        [
            {"snapshot_date": "2026-07-01", "company_id": "a", "role_family": "All roles", "active_requisitions": 2, "active_postings": 3, "ai_role_postings": 1},
            {"snapshot_date": "2026-07-02", "company_id": "a", "role_family": "All roles", "active_requisitions": 3, "active_postings": 4, "ai_role_postings": 2},
            {"snapshot_date": "2026-07-02", "company_id": "b", "role_family": "All roles", "active_requisitions": 99, "active_postings": 99, "ai_role_postings": 99},
        ]
    )
    result = build_early_cohort_trend(demand)
    assert result["active_requisitions"].tolist() == [2, 3]
    assert result["company_count"].tolist() == [1, 1]


def test_role_seniority_matrix_reconciles_to_active_jobs() -> None:
    jobs = pd.DataFrame(
        [
            {"status": "active", "source_job_id": "1", "role_family": "Research", "seniority": "Early career"},
            {"status": "active", "source_job_id": "1", "role_family": "Research", "seniority": "Early career"},
            {"status": "active", "source_job_id": "2", "role_family": "Research", "seniority": "Senior / Staff / Principal"},
            {"status": "closed", "source_job_id": "3", "role_family": "Other", "seniority": "Senior / Staff / Principal"},
        ]
    )
    matrix = build_role_seniority_matrix(jobs)
    assert list(matrix.index) == list(ROLE_FAMILIES)
    assert list(matrix.columns) == list(SENIORITY_LEVELS)
    assert matrix.to_numpy().sum() == 2
    assert build_seniority_totals(matrix).set_index("seniority").loc["Senior / Staff / Principal", "active_postings"] == 1
    shares = build_role_seniority_matrix(jobs, mode="share")
    assert shares.loc["Research"].sum() == 100
