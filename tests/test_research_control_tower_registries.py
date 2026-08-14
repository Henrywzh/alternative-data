from __future__ import annotations

import csv
from dataclasses import replace
import hashlib
from pathlib import Path
import shutil

import pandas as pd
import pytest

from src.research_control_tower.contracts import ValidationIssue
from src.research_control_tower.registries import (
    load_registry_bundle,
    validate_registry_bundle,
)


@pytest.fixture()
def registry_root() -> Path:
    return Path(__file__).parents[1] / "config" / "research_control_tower"


REQUIRED_AI_ANCHORS = {
    "NVIDIA",
    "AMD",
    "BROADCOM",
    "MARVELL",
    "CAMBRICON",
    "SK_HYNIX",
    "MICRON",
    "SAMSUNG_ELECTRONICS",
    "NANYA_TECHNOLOGY",
    "WINBOND",
    "TSMC",
    "SMIC",
    "HUA_HONG_SEMICONDUCTOR",
    "UMC",
    "GLOBALFOUNDRIES",
    "ASE_TECHNOLOGY",
    "AMKOR",
    "BESI",
    "HANMI_SEMICONDUCTOR",
    "JCET",
    "ASML",
    "APPLIED_MATERIALS",
    "LAM_RESEARCH",
    "KLA",
    "ASM_INTERNATIONAL",
    "NAURA",
    "UNIMICRON",
    "NAN_YA_PCB",
    "IBIDEN",
    "AJINOMOTO",
    "ARISTA_NETWORKS",
    "LUMENTUM",
    "COHERENT",
    "ACCTON",
    "ZTE",
    "QUANTA",
    "WISTRON",
    "WIWYNN",
    "DELL",
    "HPE",
    "VERTIV",
    "EATON",
    "MONOLITHIC_POWER_SYSTEMS",
    "DELTA_ELECTRONICS",
    "SCHNEIDER_ELECTRIC",
    "GE_VERNOVA",
    "CONSTELLATION_ENERGY",
    "VISTRA",
    "SIEMENS_ENERGY",
    "MICROSOFT",
    "AMAZON",
    "ALPHABET",
    "META",
    "ORACLE",
    "TENCENT",
    "ALIBABA",
}


def _copy_registry_root(source: Path, target: Path) -> Path:
    target.mkdir()
    for path in source.glob("*.csv"):
        shutil.copy2(path, target / path.name)
    return target


def test_required_control_tower_registries_load(registry_root):
    bundle = load_registry_bundle(registry_root)

    assert {
        "US_VALUE",
        "US_GROWTH",
        "HK_VALUE",
        "HK_INTERNET",
        "HK_AI_THEMATIC",
        "AI_BOTTLENECKS_GLOBAL",
    } <= set(bundle.baskets["basket_id"])
    assert {"CSI500", "STOXX_EUROPE_600"} <= set(bundle.indices["index_id"])
    assert (
        bundle.indices.set_index("index_id").loc["CSI500", "official_code"]
        == "000905"
    )


def test_required_ai_anchor_coverage_and_sk_hynix_core(registry_root):
    bundle = load_registry_bundle(registry_root)
    ai = bundle.basket_memberships[
        bundle.basket_memberships["basket_id"] == "AI_BOTTLENECKS_GLOBAL"
    ]

    assert set(ai["entity_id"]) == REQUIRED_AI_ANCHORS
    sk_hynix = ai.set_index("entity_id").loc["SK_HYNIX"]
    assert sk_hynix["membership_tier"] == "core"

    listing_entities = set(bundle.listings["entity_id"])
    assert set(ai["entity_id"]) <= listing_entities
    eligible_by_entity = bundle.listings.groupby("entity_id")[
        "collection_eligible"
    ].any()
    for _, row in ai.iterrows():
        if row["membership_tier"] != "watch_only":
            assert bool(eligible_by_entity[row["entity_id"]])


def test_financial_data_security_id_crosswalk_is_exact(registry_root):
    bundle = load_registry_bundle(registry_root)
    verified = bundle.listings[
        bundle.listings["mapping_status"] == "verified"
    ]

    assert not verified.empty
    for _, row in verified.iterrows():
        expected = hashlib.sha256(
            "\x1f".join(("security", row["canonical_ticker"])).encode("utf-8")
        ).hexdigest()
        assert row["financial_data_security_id"] == expected
        assert row["collection_eligible"] is True or row["collection_eligible"] == True


def test_mapping_gate_and_watch_only_downgrade(registry_root):
    bundle = load_registry_bundle(registry_root)
    listings = bundle.listings.copy()
    verified_index = listings.index[listings["mapping_status"] == "verified"][0]
    listings.loc[verified_index, "financial_data_security_id"] = ""
    invalid = replace(bundle, listings=listings)

    issues = validate_registry_bundle(invalid)
    codes = {issue.code for issue in issues}
    assert "mapping_verified_missing_financial_data_security_id" in codes
    assert "mapping_gate_missing_crosswalk" in codes

    unresolved = bundle.listings[
        bundle.listings["mapping_status"] == "unresolved"
    ]
    assert not unresolved.empty
    assert (unresolved["collection_eligible"] == False).all()

    eligible_by_entity = bundle.listings.groupby("entity_id")[
        "collection_eligible"
    ].any()
    for entity_id in eligible_by_entity[~eligible_by_entity].index:
        memberships = bundle.basket_memberships[
            bundle.basket_memberships["entity_id"] == entity_id
        ]
        automated = memberships[~memberships["membership_tier"].eq("watch_only")]
        assert automated.empty


def test_mapping_gate_keeps_entity_membership_when_secondary_is_unresolved(registry_root):
    bundle = load_registry_bundle(registry_root)
    listings = bundle.listings.copy()
    jd_index = listings.index[listings["listing_id"] == "9618_HK"][0]
    for column in (
        "canonical_ticker",
        "financial_data_security_id",
        "financial_data_issuer_group_id",
        "mapping_verified_at",
        "mapping_source_url",
    ):
        listings.loc[jd_index, column] = ""
    listings.loc[jd_index, "mapping_status"] = "unresolved"
    listings.loc[jd_index, "collection_eligible"] = False
    invalid = replace(bundle, listings=listings)
    issues = validate_registry_bundle(invalid)

    jd = listings[listings["entity_id"] == "JD_COM"].set_index("listing_id")
    baidu = listings[listings["entity_id"] == "BAIDU"].set_index("listing_id")

    assert jd.loc["JD_US", "collection_eligible"] is True or jd.loc[
        "JD_US", "collection_eligible"
    ] == True
    assert baidu.loc["BIDU_US", "collection_eligible"] is True or baidu.loc[
        "BIDU_US", "collection_eligible"
    ] == True
    assert invalid.basket_memberships.set_index("entity_id").loc[
        "JD_COM", "membership_tier"
    ] == "core"
    assert not any(
        issue.code == "membership_requires_watch_only_without_eligible_listing"
        and issue.row_index in set(
            invalid.basket_memberships.index[
                invalid.basket_memberships["entity_id"] == "JD_COM"
            ]
        )
        for issue in issues
    )


def test_malformed_nonblank_dates_raise(registry_root, tmp_path):
    copied_root = _copy_registry_root(registry_root, tmp_path / "registry")
    entities_path = copied_root / "entities.csv"
    entities_path.write_text(
        entities_path.read_text().replace("2026-01-01", "not-a-date", 1)
    )

    with pytest.raises(ValueError, match="invalid active_from"):
        load_registry_bundle(copied_root)


def test_listing_roles_and_primary_flags_are_consistent(registry_root):
    bundle = load_registry_bundle(registry_root)
    listings = bundle.listings
    allowed_roles = {"primary", "dual_primary", "secondary", "depositary_receipt"}

    assert set(listings["listing_role"]) <= allowed_roles
    expected_primary = listings["listing_role"].isin({"primary", "dual_primary"})
    assert (listings["primary_listing"] == expected_primary).all()

    for entity_id in bundle.entities.loc[
        bundle.entities["active_status"] == "active", "entity_id"
    ]:
        entity_listings = listings[listings["entity_id"] == entity_id]
        assert entity_listings["primary_listing"].any()
        true_roles = entity_listings.loc[
            entity_listings["primary_listing"], "listing_role"
        ]
        assert len(true_roles) == 1 or set(true_roles) <= {"dual_primary"}

    assert listings.set_index("listing_id").loc[
        "JD_US", "listing_role"
    ] == "primary"
    assert listings.set_index("listing_id").loc[
        "9618_HK", "listing_role"
    ] == "secondary"
    assert listings.set_index("listing_id").loc[
        "BIDU_US", "listing_role"
    ] == "primary"
    assert listings.set_index("listing_id").loc[
        "9888_HK", "listing_role"
    ] == "secondary"


def test_membership_duplicate_overlap_and_containment_validation(registry_root):
    bundle = load_registry_bundle(registry_root)
    memberships = bundle.basket_memberships.copy()
    target_index = memberships.index[0]
    duplicate = memberships.loc[[target_index]].copy()
    overlap = memberships.loc[[target_index]].copy()
    overlap.loc[target_index, "active_from"] = pd.Timestamp("2025-12-01")
    overlap.loc[target_index, "active_to"] = pd.Timestamp("2026-02-01")
    invalid = replace(
        bundle,
        basket_memberships=pd.concat([memberships, duplicate, overlap], ignore_index=True),
    )

    issues = validate_registry_bundle(invalid)
    codes = {issue.code for issue in issues}
    assert "duplicate_membership_natural_key" in codes
    assert "overlapping_membership_intervals" in codes

    outside = memberships.copy()
    outside.loc[target_index, "active_from"] = pd.Timestamp("2025-01-01")
    outside.loc[target_index, "active_to"] = pd.Timestamp("2025-12-31")
    outside_issues = validate_registry_bundle(
        replace(bundle, basket_memberships=outside)
    )
    outside_codes = {issue.code for issue in outside_issues}
    assert "membership_outside_entity_interval" in outside_codes
    assert "membership_outside_basket_interval" in outside_codes


def test_membership_secondary_layers_contain_no_basket_ids(registry_root):
    bundle = load_registry_bundle(registry_root)
    basket_ids = set(bundle.baskets["basket_id"])

    for value in bundle.basket_memberships["secondary_layers"]:
        assert not basket_ids.intersection(
            {token.strip() for token in str(value).split(";") if token.strip()}
        )


def test_index_identifier_namespaces_are_explicit(registry_root):
    bundle = load_registry_bundle(registry_root)
    indices = bundle.indices

    assert {
        "official_code_namespace",
        "official_code_provider",
        "provider_symbol_namespace",
        "provider_symbol_provider",
    } <= set(indices.columns)
    for _, row in indices.iterrows():
        if str(row["official_code"]).strip():
            assert str(row["official_code_namespace"]).strip()
            assert str(row["official_code_provider"]).strip()
        if str(row["provider_symbol"]).strip():
            assert str(row["provider_symbol_namespace"]).strip()
            assert str(row["provider_symbol_provider"]).strip()

    by_id = indices.set_index("index_id")
    assert by_id.loc["CSI500", "official_code"] == "000905"
    assert by_id.loc["CSI500", "official_code_namespace"] == "CSI"
    assert by_id.loc["CSI500", "official_code_provider"] == "China Securities Index"
    assert by_id.loc["STOXX_EUROPE_600", "official_code_namespace"] == "STOXX"


def test_membership_csv_versions_have_no_source_whitespace(registry_root):
    with (registry_root / "basket_memberships.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert {row["registry_version"] for row in rows} == {"v1"}


def test_validation_issue_severity_is_constrained():
    assert ValidationIssue("error", "example", "example").severity == "error"
    with pytest.raises(ValueError, match="unsupported validation severity"):
        ValidationIssue("fatal", "example", "example")


def test_registry_rows_are_versioned(registry_root):
    bundle = load_registry_bundle(registry_root)

    for name in ("entities", "listings", "baskets", "basket_memberships", "indices"):
        frame = getattr(bundle, name)
        assert set(frame["registry_version"]) == {"v1"}
        assert frame["active_from"].notna().all()


def test_memberships_reference_active_entity_and_basket(registry_root):
    bundle = load_registry_bundle(registry_root)
    issues = validate_registry_bundle(bundle)

    assert not [issue for issue in issues if issue.severity == "error"]


def test_one_entity_can_have_multiple_listings(registry_root):
    bundle = load_registry_bundle(registry_root)
    tsmc = bundle.listings[bundle.listings["entity_id"] == "TSMC"]

    assert {"2330_TW", "TSM_US"} <= set(tsmc["listing_id"])


@pytest.mark.parametrize(
    ("registry_name", "key"),
    [
        ("entities", "entity_id"),
        ("listings", "listing_id"),
        ("baskets", "basket_id"),
        ("indices", "index_id"),
    ],
)
def test_validation_rejects_duplicate_keys(registry_root, registry_name, key):
    bundle = load_registry_bundle(registry_root)
    frame = getattr(bundle, registry_name).copy()
    duplicate = frame.iloc[[0]].copy()
    frame = pd.concat([frame, duplicate], ignore_index=True)
    invalid = replace(bundle, **{registry_name: frame})

    issues = validate_registry_bundle(invalid)

    assert any(issue.code == f"duplicate_{key}" for issue in issues)


def test_validation_rejects_orphans_and_invalid_memberships(registry_root):
    bundle = load_registry_bundle(registry_root)
    memberships = bundle.basket_memberships.copy()
    memberships.loc[0, "entity_id"] = "MISSING_ENTITY"
    memberships.loc[1, "basket_id"] = "MISSING_BASKET"
    memberships.loc[2, "membership_tier"] = "invalid"
    invalid = replace(bundle, basket_memberships=memberships)

    issues = validate_registry_bundle(invalid)
    codes = {issue.code for issue in issues}

    assert {
        "orphan_membership_entity_id",
        "orphan_membership_basket_id",
        "invalid_membership_tier",
    } <= codes


def test_validation_rejects_invalid_dates_and_missing_ai_layer(registry_root):
    bundle = load_registry_bundle(registry_root)
    memberships = bundle.basket_memberships.copy()
    ai_core = memberships[
        (memberships["basket_id"] == "AI_BOTTLENECKS_GLOBAL")
        & (memberships["membership_tier"] == "core")
    ].index[0]
    memberships.loc[ai_core, "primary_layer"] = ""
    memberships.loc[ai_core, "active_to"] = "2020-01-01"
    memberships.loc[ai_core, "active_from"] = "2021-01-01"
    invalid = replace(bundle, basket_memberships=memberships)

    issues = validate_registry_bundle(invalid)
    codes = {issue.code for issue in issues}

    assert "active_to_not_after_active_from" in codes
    assert "ai_core_missing_primary_layer" in codes


def test_validation_rejects_listing_and_index_contract_errors(registry_root):
    bundle = load_registry_bundle(registry_root)
    listings = bundle.listings.copy()
    listings.loc[0, "entity_id"] = "MISSING_ENTITY"
    indices = bundle.indices.copy()
    indices.loc[0, "region"] = ""
    indices.loc[0, "display_name"] = ""
    indices.loc[0, "official_code"] = ""
    indices.loc[0, "provider_symbol"] = ""
    invalid = replace(bundle, listings=listings, indices=indices)

    issues = validate_registry_bundle(invalid)
    codes = {issue.code for issue in issues}

    assert "orphan_listing_entity_id" in codes
    assert "index_missing_region" in codes
    assert "index_missing_display_name" in codes
    assert "index_missing_code_or_provider_symbol" in codes
