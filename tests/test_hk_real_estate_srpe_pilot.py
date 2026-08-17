import pandas as pd

from src.hk_real_estate.srpe_pilot import (
    SRPE_PROJECT_REGISTRY_PATH,
    load_srpe_project_registry,
    select_price_documents,
    select_transaction_documents,
    select_srpe_projects,
)
from src.hk_real_estate.srpe_pilot import _with_project_fields


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


def test_srpe_transaction_selection_can_switch_between_latest_and_full_history():
    documents = [
        {"id": "1", "dateOfPrinting": "2021-03-04", "file": {"fileName": "1.pdf"}},
        {"id": "2", "dateOfPrinting": "2022-03-04", "file": {"fileName": "2.pdf"}},
        {"id": "3", "dateOfPrinting": "2024-03-04", "file": {"fileName": "3.pdf"}},
    ]
    assert [item["id"] for item in select_transaction_documents(documents)] == ["3"]
    assert [item["id"] for item in select_transaction_documents(documents, all_transaction_documents=True)] == ["1", "2", "3"]


def test_srpe_project_selection_rejects_unknown_project():
    registry = load_srpe_project_registry()
    try:
        select_srpe_projects(registry, projects=["does-not-exist"])
    except ValueError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("unknown SRPE project should be rejected")


def test_srpe_project_fields_do_not_compute_attributable_value_without_approved_interval():
    project = pd.Series({
        "project_id": "legacy-pilot",
        "stock_code": "0016",
        "ownership_pct": 100.0,
        "srpe_dev_id": "9366",
        "srpe_development_id": "9366",
        "phase_no": "1",
        "ownership_attribution_ready": True,
        "ownership_effective_from": None,
        "ownership_effective_to": None,
        "ownership_interval_evidence_type": "",
        "ownership_attribution_decision_id": "",
        "ownership_interval_promotion_status": "approved_phase_attribution",
    })
    frame = _with_project_fields(pd.DataFrame([{"transaction_price_hkd": 100.0}]), project)
    assert frame.loc[0, "sales_attribution_status"] == "blocked_phase_specific_interval"
    assert pd.isna(frame.loc[0, "transaction_value_attributable_hkd"])
