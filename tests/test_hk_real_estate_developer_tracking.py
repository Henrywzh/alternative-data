"""Offline contracts for the developer-agnostic tracking layer and Sino adapter."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest
import requests

from src.hk_real_estate.developer_tracking import (
    MISSING_DATA_POLICY,
    build_developer_identity_crosswalk,
    build_developer_project_events,
    build_developer_project_snapshot,
    build_developer_sales_queue,
    normalize_developer_catalog,
)
from src.hk_real_estate.sources import sino_land


def _srpe_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "development_id": "1001",
                "display_name": "Grand Victoria",
                "development_name_en": "Grand Victoria",
                "development_name_zh": "維港匯",
                "phase_name_en": "Phase 1",
                "phase_name_zh": "第一期",
                "address_en": "2 LAI YING STREET",
                "active": "Y",
                "srpe_earliest_publication": "2021-06-01",
                "source_url": "https://www.srpe.gov.hk/opip/all_development",
            },
            {
                "development_id": "1999",
                "display_name": "Old Sino Project",
                "development_name_en": "Old Sino Project",
                "phase_name_en": "Phase 1",
                "active": "N",
                "srpe_date_complete_sales": "2024-01-01",
                "srpe_earliest_publication": "2020-01-01",
                "source_url": "https://www.srpe.gov.hk/opip/all_development",
            },
        ]
    )


def _catalog_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "company_id": "sino_land",
                "ticker": "0083.HK",
                "asset_type": "residential_for_sale",
                "subtype": "for_sale",
                "marketing_name": "Grand Victoria",
                "district": "Kowloon",
                "address": "2 Lai Ying Street",
                "external_project_url": "https://example.test/grand-victoria",
                "source_record_id": "gv-1",
                "source_page_url": "https://www.sino.com/en/",
                "source_url": "https://api.example.test/catalog?asset=residential",
                "listed_status": "for_sale",
                "raw_langcode": "en",
                "page_number": 0,
                "display_order": 1,
                "fetched_at": "2026-08-24T00:00:00+00:00",
                "source_adapter": "test",
            },
            {
                "company_id": "sino_land",
                "ticker": "0083.HK",
                "asset_type": "residential_for_lease",
                "subtype": "for_lease",
                "marketing_name": "Leased Residential Asset",
                "district": "Kowloon",
                "address": "2 Example Road",
                "external_project_url": None,
                "source_record_id": "lease-1",
                "source_page_url": "https://www.sino.com/en/",
                "source_url": "https://api.example.test/catalog?asset=lease",
                "listed_status": "for_lease",
                "raw_langcode": "en",
                "page_number": 0,
                "display_order": 4,
                "fetched_at": "2026-08-24T00:00:00+00:00",
                "source_adapter": "test",
            },
            {
                "company_id": "sino_land",
                "ticker": "0083.HK",
                "asset_type": "office",
                "subtype": "for_lease",
                "marketing_name": "Sino Office Tower",
                "district": "Central",
                "address": "1 Example Road",
                "external_project_url": None,
                "source_record_id": "office-1",
                "source_page_url": "https://www.sino.com/en/",
                "source_url": "https://api.example.test/catalog?asset=office",
                "listed_status": "for_lease",
                "raw_langcode": "en",
                "page_number": 0,
                "display_order": 2,
                "fetched_at": "2026-08-24T00:00:00+00:00",
                "source_adapter": "test",
            },
            {
                "company_id": "sino_land",
                "ticker": "0083.HK",
                "asset_type": "residential_for_sale",
                "subtype": "for_sale",
                "marketing_name": "Future Unresolved Project",
                "district": "New Territories",
                "address": None,
                "external_project_url": None,
                "source_record_id": "future-1",
                "source_page_url": "https://www.sino.com/en/",
                "source_url": "https://api.example.test/catalog?asset=residential",
                "listed_status": "for_sale",
                "raw_langcode": "en",
                "page_number": 0,
                "display_order": 3,
                "fetched_at": "2026-08-24T00:00:00+00:00",
                "source_adapter": "test",
            },
        ]
    )


def _registry_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "stock_code": "0083",
                "project_name_en": "Grand Victoria",
                "project_name_zh": "維港匯",
                "project_aliases": "Grand Victoria|維港匯 Phase 1",
                "ownership_pct": "22.5",
            }
        ]
    )


def test_identity_and_queue_are_conservative_and_separate_commercial_assets():
    from src.hk_real_estate.sources.sino_land import SINO_LAND_PROFILE

    catalog = _catalog_fixture()
    identity = build_developer_identity_crosswalk(
        SINO_LAND_PROFILE,
        catalog,
        _srpe_fixture(),
        registry=_registry_fixture(),
        source_dataset="test_catalog",
        observed_at="2026-08-24T00:00:00+00:00",
    )

    grand = identity.loc[identity["project_label"].eq("Grand Victoria")].iloc[0]
    assert grand["srpe_development_id"] == "1001"
    assert grand["match_status"] == "matched_needs_review"
    assert grand["ownership_pct_snapshot"] == pytest.approx(22.5)
    assert grand["ownership_scenario_status"] == "observed_snapshot_not_interval"
    unresolved = identity.loc[identity["project_label"].eq("Future Unresolved Project")].iloc[0]
    assert unresolved["match_status"] == "unmatched"
    assert pd.isna(unresolved["srpe_development_id"])

    events = build_developer_project_events(
        SINO_LAND_PROFILE,
        identity=identity,
        srpe_index=_srpe_fixture(),
        property_catalog=catalog,
        ownership_observations=pd.DataFrame([{"srpe_development_id": "1001", "ownership_pct": 22.5}]),
        observed_at="2026-08-24T00:00:00+00:00",
    )
    assert events["event_key"].is_unique
    assert set(events["missing_data_policy"]) == {MISSING_DATA_POLICY}

    snapshot = build_developer_project_snapshot(SINO_LAND_PROFILE, events)
    grand_snapshot = snapshot.loc[snapshot["project_label"].eq("Grand Victoria")].iloc[0]
    assert grand_snapshot["coverage_status"] == "srpe_identity_known_sales_queue_candidate"
    assert grand_snapshot["sales_queue_status"] == "eligible_for_recent_srpe_queue"
    queue = build_developer_sales_queue(SINO_LAND_PROFILE, snapshot, _srpe_fixture(), last_verified_at="2026-08-24")
    grand_queue = queue.loc[queue["project_label"].eq("Grand Victoria")].iloc[0]
    assert grand_queue["queue_status"] == "eligible_for_recent_srpe_queue"
    assert grand_queue["eligibility_status"] == "eligible"

    office_queue = queue.loc[queue["project_label"].eq("Sino Office Tower")].iloc[0]
    assert office_queue["queue_status"] == "not_applicable_non_residential"
    assert office_queue["eligibility_status"] == "not_applicable"
    lease_queue = queue.loc[queue["project_label"].eq("Leased Residential Asset")].iloc[0]
    assert lease_queue["queue_status"] == "not_applicable_non_first_hand_residential"
    assert lease_queue["eligibility_status"] == "not_applicable"
    future_queue = queue.loc[queue["project_label"].eq("Future Unresolved Project")].iloc[0]
    assert future_queue["queue_status"] == "not_ready_srpe_pending"
    assert future_queue["eligibility_status"] == "not_ready"
    assert (queue["queue_status"] != "zero_sales").all()


def test_not_found_pipeline_anchor_does_not_create_a_project_state():
    from src.hk_real_estate.sources.sino_land import SINO_LAND_PROFILE

    pipeline = pd.DataFrame(
        [
            {
                "pipeline_registry_key": "sino_land:ar:not-found",
                "project_label": "Unconfirmed Pipeline Anchor",
                "project_state": "under_development",
                "asset_scope": "residential_first_hand",
                "evidence_status": "not_found",
                "publication_date": "2025-09-25",
                "source_dataset": "test_report",
            }
        ]
    )
    events = build_developer_project_events(SINO_LAND_PROFILE, pipeline=pipeline, srpe_index=_srpe_fixture())
    row = events.loc[events["event_type"].eq("pipeline_disclosure")].iloc[0]
    assert pd.isna(row["state_after"])
    assert row["sales_queue_status"] == "not_evaluated_source_gap"


def test_catalog_rows_without_source_ids_are_not_collapsed():
    from src.hk_real_estate.sources.sino_land import SINO_LAND_PROFILE

    frame = pd.DataFrame(
        [
            {"marketing_name": "No ID A", "asset_type": "office"},
            {"marketing_name": "No ID B", "asset_type": "office"},
        ]
    )
    normalized = normalize_developer_catalog(SINO_LAND_PROFILE, frame, source_adapter="test")
    assert len(normalized) == 2


def test_generic_phase_label_cannot_crosswalk_an_unrelated_project():
    from src.hk_real_estate.sources.sino_land import SINO_LAND_PROFILE

    observation = pd.DataFrame([{"marketing_name": "Unrelated Phase 1"}])
    identity = build_developer_identity_crosswalk(SINO_LAND_PROFILE, observation, _srpe_fixture())
    assert identity.iloc[0]["match_status"] == "unmatched"
    assert pd.isna(identity.iloc[0]["srpe_development_id"])


def test_ownership_input_without_phase_column_is_ignored_not_fatal():
    from src.hk_real_estate.sources.sino_land import SINO_LAND_PROFILE

    events = build_developer_project_events(
        SINO_LAND_PROFILE,
        srpe_index=_srpe_fixture(),
        ownership_observations=pd.DataFrame([{"ownership_pct": 33.3}]),
    )
    assert events.empty


class _FakeResponse:
    def __init__(self, payload=None, *, status_code=200, text=None, content=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})
        self.content = content if content is not None else self.text.encode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _FakeSinoSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append((url, timeout))
        query = parse_qs(urlparse(url).query)
        asset_filter = query.get("elements.property_attribute__business_category[contains]", [""])[0]
        if asset_filter == "industrial":
            return _FakeResponse(status_code=503, text="upstream unavailable", content=b"upstream unavailable")
        title = {
            "residential": "Grand Victoria",
            "offices": "Sino Office Tower",
            "retail": "Sino Mall",
        }.get(asset_filter, "Sino Asset")
        property_filter = query.get("elements.property_attribute__property_type[contains]", [""])[0]
        payload = {
            "items": [
                {
                    "system": {"id": f"id-{asset_filter}-{property_filter}", "name": title},
                    "elements": {
                        "property__title": {"value": title},
                        "property_attribute__property_location": {"value": [{"name": "Hong Kong"}]},
                        "property__address": {"value": "1 Example Road"},
                        "property_attribute__rank": {"value": 1},
                        "property__website_url": {"value": "https://example.test/project"},
                    },
                }
            ],
            "pagination": {"count": 1},
        }
        return _FakeResponse(payload)


def test_sino_catalog_keeps_partial_category_failure_and_site_role_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sino_land,
        "save_raw_snapshot",
        lambda name, content, file_ext="json", source_url=None: tmp_path / f"{name}.{file_ext}",
    )
    session = _FakeSinoSession()
    catalog = sino_land.fetch_sino_property_catalog(session=session, timeout=1, max_pages=1)
    assert not catalog.empty
    assert set(catalog["ticker"]) == {"0083.HK"}
    summary = {item["asset_type"]: item for item in catalog.attrs["fetch_summary"]}
    assert summary["industrial"]["status"] == "failed"
    assert summary["residential_for_sale"]["status"] == "ok"

    def fake_site_get(url, timeout=None):
        return _FakeResponse(
            text=(
                "The vendor is Sino Land Company Limited. "
                "The holding company and person so engaged are stated here."
            ),
            content=b"<html>vendor Sino Land Company Limited</html>",
        )

    session.get = fake_site_get
    evidence = sino_land.fetch_sino_project_site_role_evidence(
        catalog.loc[catalog["asset_type"].eq("residential_for_sale")],
        session=session,
        timeout=1,
        max_projects=1,
    )
    assert len(evidence) == 1
    assert evidence.iloc[0]["site_evidence_status"] == "site_named_company_role"
    assert "sino land company limited" in evidence.iloc[0]["holding_company_hits_json"]


def test_sino_catalog_follows_explicit_next_page(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sino_land,
        "save_raw_snapshot",
        lambda name, content, file_ext="json", source_url=None: tmp_path / f"{name}-{len(list(tmp_path.iterdir()))}.{file_ext}",
    )

    class _PaginatedSession(_FakeSinoSession):
        def get(self, url, timeout=None):
            query = parse_qs(urlparse(url).query)
            category = query.get("elements.property_attribute__business_category[contains]", [""])[0]
            if category != "residential" or query.get("elements.property_attribute__property_type[contains]", [""])[0] != "for_sale":
                return _FakeResponse({"items": [], "pagination": {"count": 0}})
            skip = int(query.get("skip", [0])[0])
            item = {
                "system": {"id": f"page-{skip}", "name": f"Page Project {skip}"},
                "elements": {
                    "property__title": {"value": f"Page Project {skip}"},
                    "property_attribute__property_location": {"value": [{"name": "Hong Kong"}]},
                },
            }
            next_url = None
            if skip == 0:
                next_url = url.replace("&skip=0&", "&skip=1&", 1)
            return _FakeResponse({"items": [item], "pagination": {"count": 2, "next_page": next_url or ""}})

    catalog = sino_land.fetch_sino_property_catalog(session=_PaginatedSession(), timeout=1, max_pages=None)
    sale = catalog.loc[catalog["asset_type"].eq("residential_for_sale")]
    assert len(sale) == 2
    sale_summary = next(item for item in catalog.attrs["fetch_summary"] if item["asset_type"] == "residential_for_sale")
    assert sale_summary["pages_fetched"] == 2
    assert sale_summary["rows_emitted"] == 2


def test_sino_pipeline_equity_parser_only_accepts_explicit_equity_interest():
    assert sino_land._extract_group_equity_interest("The Group has 80% equity interest in the joint venture") == pytest.approx(80.0)
    assert sino_land._extract_group_equity_interest("The project is 96.5% sold") is None


def test_sino_srpe_manifest_is_a_routing_layer_and_preserves_no_documents(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sino_land,
        "save_raw_snapshot",
        lambda name, content, file_ext="json", source_url=None: tmp_path / f"{name}.{file_ext}",
    )

    class _ManifestSession:
        def __init__(self):
            self.headers = {}

        def post(self, url, json=None, timeout=None):
            assert "getSelectedDevResult" in url
            assert json["devId"] in {"1001", "1002"}
            if json["devId"] == "1002":
                return _FakeResponse({"resultData": {"devInfoResp": {}}})
            return _FakeResponse(
                {
                    "resultData": {
                        "devInfoResp": {
                            "transactions": [
                                {
                                    "id": "tx-1",
                                    "serialNo": "T1",
                                    "file": {
                                        "fileName": "transactions.pdf",
                                        "submissionTime": "2026-08-20T00:00:00Z",
                                        "fileSize": 1234,
                                    },
                                }
                            ],
                            "prices": [],
                            "salesArrangements": [],
                            "brochureList": [],
                        }
                    }
                }
            )

    queue = pd.DataFrame(
        [
            {
                "canonical_project_id": "sino_land:project:grandvictoria",
                "project_label": "Grand Victoria",
                "srpe_development_id": "1001",
                "srpe_phase_name": "Phase 1",
                "queue_status": "eligible_for_recent_srpe_queue",
            },
            {
                "canonical_project_id": "sino_land:project:pending",
                "project_label": "Future Project",
                "srpe_development_id": None,
                "queue_status": "not_ready_srpe_pending",
            },
            {
                "canonical_project_id": "sino_land:project:no-docs",
                "project_label": "No Documents Yet",
                "srpe_development_id": "1002",
                "srpe_phase_name": "Phase 1",
                "queue_status": "eligible_for_recent_srpe_queue",
            },
        ]
    )
    manifest = sino_land.fetch_sino_srpe_document_manifest(
        queue,
        session=_ManifestSession(),
        timeout=1,
        max_projects=2,
        request_delay=0,
    )
    assert len(manifest) == 2
    document_row = manifest.loc[manifest["manifest_status"].eq("manifest_document")].iloc[0]
    no_documents_row = manifest.loc[manifest["manifest_status"].eq("manifest_ok_no_documents")].iloc[0]
    assert document_row["document_category"] == "register_of_transactions"
    assert document_row["document_id"] == "tx-1"
    assert document_row["download_endpoint"].endswith("/download/downloadTrx")
    assert pd.isna(no_documents_row["document_id"])
    assert manifest.attrs["lineage_metadata"]["pdf_downloaded"] is False


def test_sino_transaction_ingestion_keeps_missing_register_as_coverage_gap(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sino_land,
        "save_raw_snapshot",
        lambda name, content, file_ext="json", source_url=None: tmp_path / f"{name}.{file_ext}",
    )
    monkeypatch.setattr(sino_land, "download_srpe_document", lambda *args, **kwargs: b"%PDF-1.4 fake")

    def fake_parse(content, **kwargs):
        return pd.DataFrame(
            [
                {
                    "source_agency": "SRPE",
                    "document_category": "register_of_transactions",
                    "development_id": kwargs["development_id"],
                    "development_name": kwargs["development_name"],
                    "phase_name": kwargs["phase_name"],
                    "development_address": None,
                    "document_id": kwargs["document_id"],
                    "document_serial_no": kwargs.get("document_serial_no"),
                    "document_hash": "hash",
                    "source_document": kwargs.get("source_document"),
                    "source_page": 1,
                    "date_of_pasp": "2026-08-01",
                    "date_of_asp": "2026-08-02",
                    "date_of_asp_termination": None,
                    "block_name": "Tower 1",
                    "floor": "10",
                    "unit": "A",
                    "car_parking_space": None,
                    "transaction_price_hkd": 10000000,
                    "price_revision_details": None,
                    "payment_terms": None,
                    "related_party_flag": None,
                    "is_cancelled": False,
                    "transaction_id": f"tx-{kwargs['development_id']}",
                }
            ]
        )

    monkeypatch.setattr(sino_land, "parse_srpe_transaction_pdf", fake_parse)
    manifest = pd.DataFrame(
        [
            {
                "canonical_project_id": "sino_land:project:one",
                "project_label": "One Project",
                "srpe_development_id": "1001",
                "srpe_phase_name": "Phase 1",
                "queue_status": "eligible_for_recent_srpe_queue",
                "manifest_status": "manifest_document",
                "document_category": "register_of_transactions",
                "document_id": "tx-doc-1",
                "file_name": "one.pdf",
                "download_endpoint": "https://example.test/downloadTrx",
            },
            {
                "canonical_project_id": "sino_land:project:two",
                "project_label": "No Register Project",
                "srpe_development_id": "1002",
                "srpe_phase_name": "Phase 1",
                "queue_status": "eligible_for_recent_srpe_queue",
                "manifest_status": "manifest_document",
                "document_category": "sales_brochure",
                "document_id": "brochure-1",
                "file_name": "brochure.pdf",
                "download_endpoint": "https://example.test/downloadBrochure",
            },
        ]
    )
    queue = manifest[
        ["canonical_project_id", "project_label", "srpe_development_id", "srpe_phase_name", "queue_status"]
    ].copy()
    layers = sino_land.fetch_sino_srpe_transaction_events(
        manifest,
        queue,
        price_lists=pd.DataFrame(
            [
                {
                    "development_id": "1001",
                    "development_name": "One Project",
                    "phase_name": "--",  # parser placeholder differs from the register
                    "total_residential_properties": 100,
                }
            ]
        ),
        timeout=1,
        max_documents=2,
        request_delay=0,
    )
    assert len(layers["transaction_events"]) == 1
    assert len(layers["monthly_signals"]) == 1
    coverage = layers["coverage"].set_index("project_label")
    assert coverage.loc["One Project", "coverage_status"] == "observed_transaction_register"
    assert coverage.loc["No Register Project", "coverage_status"] == "manifest_no_transaction_register"
    assert layers["document_audit"].iloc[0]["parse_status"] == "parsed"
    assert layers["monthly_signals"].iloc[0]["cumulative_net_sell_through_pct"] == pytest.approx(1.0)


def test_sino_price_list_inventory_keeps_explicit_total_and_missing_phase(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sino_land,
        "save_raw_snapshot",
        lambda name, content, file_ext="json", source_url=None: tmp_path / f"{name}.{file_ext}",
    )
    monkeypatch.setattr(sino_land, "download_srpe_document", lambda *args, **kwargs: b"%PDF-1.4 fake")

    def fake_parse(content, **kwargs):
        return pd.DataFrame(
            [
                {
                    "source_agency": "SRPE",
                    "document_category": "price_list",
                    "development_id": kwargs["development_id"],
                    "development_name": kwargs["development_name"],
                    "phase_name": kwargs["phase_name"],
                    "development_address": None,
                    "document_id": kwargs["document_id"],
                    "document_serial_no": kwargs.get("document_serial_no"),
                    "document_hash": "hash",
                    "source_document": kwargs.get("source_document"),
                    "source_page": 1,
                    "date_of_printing": "2026-08-01",
                    "price_list_number": "1",
                    "price_list_series_key": "series",
                    "price_list_version_key": "version",
                    "is_revision": False,
                    "total_residential_properties": 100,
                    "block_name": "Tower 1",
                    "floor": "10",
                    "unit": "A",
                    "saleable_area_sqm": 50.0,
                    "saleable_area_sqft": 538.2,
                    "price_hkd": 10000000.0,
                    "unit_rate_hkd_per_sqm": 200000.0,
                    "unit_rate_hkd_per_sqft": 18580.0,
                    "unit_key": "tower 1|10|a",
                },
                {
                    "source_agency": "SRPE",
                    "document_category": "price_list",
                    "development_id": kwargs["development_id"],
                    "development_name": kwargs["development_name"],
                    "phase_name": kwargs["phase_name"],
                    "development_address": None,
                    "document_id": kwargs["document_id"],
                    "document_serial_no": kwargs.get("document_serial_no"),
                    "document_hash": "hash",
                    "source_document": kwargs.get("source_document"),
                    "source_page": 2,
                    "date_of_printing": "2026-08-01",
                    "price_list_number": "1",
                    "price_list_series_key": "series",
                    "price_list_version_key": "version",
                    "is_revision": False,
                    "total_residential_properties": 100,
                    "block_name": "Tower 1",
                    "floor": "10",
                    "unit": "A",
                    "saleable_area_sqm": 50.0,
                    "saleable_area_sqft": 538.2,
                    "price_hkd": 10000000.0,
                    "unit_rate_hkd_per_sqm": 200000.0,
                    "unit_rate_hkd_per_sqft": 18580.0,
                    "unit_key": "tower 1|10|a",
                },
            ]
        )

    monkeypatch.setattr(sino_land, "parse_srpe_price_list_pdf", fake_parse)
    manifest = pd.DataFrame(
        [
            {
                "canonical_project_id": "sino_land:project:one",
                "project_label": "One Project",
                "srpe_development_id": "1001",
                "srpe_phase_name": "Phase 1",
                "queue_status": "eligible_for_recent_srpe_queue",
                "manifest_status": "manifest_document",
                "document_category": "price_list",
                "document_id": "price-doc-1",
                "file_name": "one-price.pdf",
                "submission_time": "2026-08-20T00:00:00Z",
                "date_of_printing": "2026-08-20",
                "expected_file_size_bytes": 100,
                "download_endpoint": "https://example.test/downloadPrice",
            },
            {
                "canonical_project_id": "sino_land:project:two",
                "project_label": "No Price Project",
                "srpe_development_id": "1002",
                "srpe_phase_name": "Phase 1",
                "queue_status": "eligible_for_recent_srpe_queue",
                "manifest_status": "manifest_document",
                "document_category": "sales_arrangement",
                "document_id": "arrangement-1",
                "file_name": "arrangement.pdf",
            },
        ]
    )
    queue = manifest[
        ["canonical_project_id", "project_label", "srpe_development_id", "srpe_phase_name", "queue_status"]
    ].copy()
    layers = sino_land.fetch_sino_srpe_price_list_inventory(
        manifest,
        queue,
        timeout=1,
        max_documents=2,
        request_delay=0,
    )
    assert len(layers["price_list_units"]) == 1
    assert layers["price_list_units"].iloc[0]["total_residential_properties"] == 100
    coverage = layers["coverage"].set_index("project_label")
    assert coverage.loc["One Project", "coverage_status"] == "observed_price_list"
    assert coverage.loc["One Project", "inventory_status"] == "total_units_observed"
    assert coverage.loc["No Price Project", "coverage_status"] == "manifest_no_price_list"


def test_sino_transaction_signals_use_price_list_total_for_sell_through():
    transactions = pd.DataFrame(
        [
            {
                "development_id": "1001",
                "development_name": "One Project",
                "phase_name": "Phase 1",
                "date_of_pasp": "2026-08-01",
                "date_of_asp": "2026-08-02",
                "date_of_asp_termination": None,
                "block_name": "Tower 1",
                "floor": "10",
                "unit": "A",
                "transaction_price_hkd": 10000000,
                "is_cancelled": False,
                "transaction_id": "tx-1",
            }
        ]
    )
    price_lists = pd.DataFrame(
        [
            {
                "development_id": "1001",
                "development_name": "One Project",
                "phase_name": "Phase 1",
                "total_residential_properties": 100,
            }
        ]
    )
    signals = sino_land.build_srpe_sales_signals(transactions, price_lists=price_lists)
    assert signals.iloc[0]["total_residential_properties"] == 100
    assert signals.iloc[0]["cumulative_net_sell_through_pct"] == pytest.approx(1.0)
