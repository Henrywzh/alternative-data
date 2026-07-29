import pytest
import pandas as pd
from src.hk_real_estate.sources.bd_projects import (
    _STAGE_COLUMNS,
    fetch_bd_project_lifecycle_events,
    fetch_bd_supply_leading_indicators,
)


def test_bd_stage_columns_coverage():
    expected_stages = [
        "Demolition Consents",
        "Plans Approved",
        "Consent to Commence",
        "Notice of Commencement Received",
        "Occupation Permits (OP) Issued",
    ]
    for stage in expected_stages:
        assert stage in _STAGE_COLUMNS
        cols = _STAGE_COLUMNS[stage]
        assert "building_type_col" in cols


def test_fetch_bd_project_lifecycle_events_smoke():
    df = fetch_bd_project_lifecycle_events()
    assert isinstance(df, pd.DataFrame)
    if not df.empty:
        assert "permit_stage" in df.columns
        assert "site_address" in df.columns
        stages_found = set(df["permit_stage"].dropna().unique())
        assert len(stages_found) >= 1


def test_fetch_bd_supply_leading_indicators_smoke():
    df = fetch_bd_supply_leading_indicators()
    assert isinstance(df, pd.DataFrame)
    if not df.empty:
        assert "permit_stage" in df.columns
        assert "region" in df.columns
        assert "total_projects_count" in df.columns
