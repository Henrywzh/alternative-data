import pandas as pd

from src.hk_real_estate.srpe_pilot import (
    SRPE_PROJECT_REGISTRY_PATH,
    load_srpe_project_registry,
    select_price_documents,
    select_srpe_projects,
)


def test_srpe_pilot_registry_has_core_projects_and_optional_mtr_control():
    registry = load_srpe_project_registry(SRPE_PROJECT_REGISTRY_PATH)
    core = select_srpe_projects(registry)
    optional = select_srpe_projects(registry, pilot_group="optional_mtr_control")

    assert len(core) == 6
    assert set(core["stock_code"]) == {"0012", "0016", "0017", "0083"}
    assert optional.iloc[0]["stock_code"] == "0066"
    assert core["ownership_pct"].between(0, 100).all()


def test_srpe_price_selection_preserves_first_and_latest_version():
    documents = [
        {"id": "1", "dateOfPrinting": "2021-03-04", "file": {"fileName": "1.pdf"}},
        {"id": "2", "dateOfPrinting": "2022-03-04", "file": {"fileName": "2.pdf"}},
        {"id": "3", "dateOfPrinting": "2024-03-04", "file": {"fileName": "3.pdf"}},
    ]
    selected = select_price_documents(
        documents,
        since=pd.Timestamp("2022-01-01", tz="UTC"),
        selection="first_latest",
    )
    assert [item["id"] for item in selected] == ["2", "3"]


def test_srpe_project_selection_rejects_unknown_project():
    registry = load_srpe_project_registry()
    try:
        select_srpe_projects(registry, projects=["does-not-exist"])
    except ValueError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("unknown SRPE project should be rejected")
