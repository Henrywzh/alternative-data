from __future__ import annotations

import importlib.util
import pandas as pd
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "audit_hkex_filing_candidates.py"
SPEC = importlib.util.spec_from_file_location("audit_hkex_filing_candidates", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_classify_category_preserves_composite_boundary():
    family, composite = MODULE.classify_category(
        "Announcements and Notices - [Dividend or Distribution / Closure of Books]"
    )
    assert family == "dividend"
    assert composite is True


def test_classify_category_prioritizes_explicit_profit_warning():
    family, composite = MODULE.classify_category(
        "Announcements and Notices - [Inside Information / Profit Warning]"
    )
    assert family == "results"
    assert composite is True


def test_classify_category_does_not_treat_generic_inside_information_as_results():
    family, composite = MODULE.classify_category(
        "Announcements and Notices - [Inside Information]"
    )
    assert family == "inside_information"
    assert composite is False


def test_classify_filing_narrowly_promotes_material_repurchase_title():
    family, composite, basis = MODULE.classify_filing(
        "Announcements and Notices - [Other - Miscellaneous]",
        "VOLUNTARY ANNOUNCEMENT\nINTENTION TO CONDUCT ON-MARKET SHARE REPURCHASE",
        "",
    )
    assert family == "capital_action"
    assert composite is False
    assert basis == "title_material_repurchase_override"


def test_classify_filing_keeps_routine_next_day_buyback_return_as_other():
    family, composite, basis = MODULE.classify_filing(
        "Next Day Disclosure Returns - [Share Buyback]",
        "Next Day Disclosure Return (Equity issuer - changes in issued share capital and/or share buybacks)",
        "",
    )
    assert family == "other"
    assert composite is False
    assert basis == "category_rule"


def test_sidecar_ids_are_loaded_as_non_eligible(tmp_path: Path):
    path = tmp_path / "sidecar.parquet"
    pd.DataFrame(
        [{"filing_id": "legacy-1", "event_study_eligible": False}]
    ).to_parquet(path, index=False)
    assert MODULE.load_pit_recovery_ids(path) == {"legacy-1"}
