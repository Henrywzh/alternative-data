from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import requests

from src.hk_real_estate.sources import shkp
from src.hk_real_estate.shkp_srpe_backfill import (
    build_shkp_phase_candidates,
    select_recent_shkp_phase_candidates,
)


def _pipeline_fixture() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pipeline = pd.DataFrame(
        [
            {
                "pipeline_registry_key": "pipeline:future-active",
                "project_label": "Future Active Phase",
                "project_state": "planned_launch_10m",
                "geography": "Kai Tak",
                "publication_date": "2026-08-01",
                "evidence_status": "found",
                "source_url": "https://issuer.example/interim",
                "srpe_candidate_ids": "100",
            },
            {
                "pipeline_registry_key": "pipeline:future-pending",
                "project_label": "Future Pending Project",
                "project_state": "under_development",
                "geography": "Kwu Tung",
                "publication_date": "2026-08-01",
                "evidence_status": "found",
                "source_url": "https://issuer.example/interim",
                "srpe_candidate_ids": None,
            },
            {
                "pipeline_registry_key": "pipeline:commercial",
                "project_label": "Artist Square Towers",
                "project_state": "under_development",
                "geography": "West Kowloon",
                "publication_date": "2026-08-01",
                "evidence_status": "found",
                "source_url": "https://issuer.example/interim",
                "srpe_candidate_ids": None,
            },
        ]
    )
    resolution = pd.DataFrame(
        [
            {
                "pipeline_registry_key": "pipeline:future-active",
                "project_label": "Future Active Phase",
                "project_state": "planned_launch_10m",
                "asset_scope": "residential_first_hand_or_unknown",
                "publication_date": "2026-08-01",
                "linked_srpe_development_id": "100",
                "identity_bridge_lot_nos": "NKIL 0000",
                "resolution_status": "identity_phase_linked_review_required",
            },
            {
                "pipeline_registry_key": "pipeline:commercial",
                "project_label": "Artist Square Towers",
                "project_state": "under_development",
                "asset_scope": "commercial_investment_bot",
                "publication_date": "2026-08-01",
                "linked_srpe_development_id": None,
                "resolution_status": "resolved_non_srpe_commercial_bot",
            },
        ]
    )
    srpe = pd.DataFrame(
        [
            {
                "development_id": "100",
                "development_name_en": "FUTURE ACTIVE DEVELOPMENT",
                "phase_name_en": "FUTURE ACTIVE PHASE",
                "active": "Y",
                "srpe_earliest_publication": "2026-07-01",
                "srpe_date_suspend_sales": None,
                "srpe_date_complete_sales": None,
                "srpe_is_deleted": "N",
                "address_en": "KAI TAK",
                "source_url": "https://www.srpe.gov.hk/opip/all_development",
            }
        ]
    )
    identity = pd.DataFrame(
        [
            {
                "identity_evidence_id": "identity:future-pending",
                "project_label": "Future Pending Project",
                "asset_scope": "residential_first_hand_or_unknown",
                "canonical_identity_status": "lot_resolved_srpe_pending",
                "srpe_development_id": None,
                "srpe_match_status": "unmatched",
                "lot_no_raw": "DD 000",
                "phase_label": None,
                "evidence_date": "2026-08-01",
                "primary_source_url": "https://issuer.example/interim",
                "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
            }
        ]
    )
    return pipeline, resolution, srpe, identity


def test_future_project_events_are_append_only_and_snapshot_is_not_zero_filled():
    pipeline, resolution, srpe, identity = _pipeline_fixture()
    first = shkp.build_shkp_future_project_events(
        pipeline,
        pipeline,
        resolution,
        identity,
        srpe,
        observed_at="2026-08-24T00:00:00+00:00",
    )
    second = shkp.build_shkp_future_project_events(
        pipeline,
        pipeline,
        resolution,
        identity,
        srpe,
        prior_events=first,
        observed_at="2026-08-25T00:00:00+00:00",
    )
    assert len(second) == len(first)
    assert second["event_key"].is_unique
    assert second["missing_data_policy"].eq("unknown_is_not_zero; no_srpe_is_not_no_sales").all()

    snapshot = shkp.build_shkp_future_project_snapshot(second).set_index("canonical_project_id")
    active = snapshot.loc["srpe:100"]
    assert active["current_state"] == "srpe_active_prelaunch"
    assert active["sales_queue_status"] == "eligible_for_recent_srpe_queue"
    pending = snapshot.loc["pipeline:futurependingproject"]
    assert pending["current_state"] == "under_development"
    assert pending["coverage_status"] == "future_project_srpe_pending_or_unresolved"
    assert pd.isna(pending["units"])
    commercial = snapshot.loc["pipeline:artistsquaretowers"]
    assert commercial["coverage_status"] == "commercial_separate_registry"
    assert commercial["sales_queue_status"] == "not_applicable_non_residential"


def test_future_resolution_promotes_active_srpe_phase_to_recent_candidate_queue():
    _, resolution, srpe, _ = _pipeline_fixture()
    candidates = build_shkp_phase_candidates(
        srpe,
        pd.DataFrame(),
        None,
        None,
        future_resolution=resolution,
    )
    selected = select_recent_shkp_phase_candidates(
        candidates,
        pd.DataFrame(),
        now=pd.Timestamp("2026-08-24", tz="UTC"),
        recent_days=90,
        recent_years=2,
        allowed_statuses={"matched_needs_review"},
    )
    assert selected["srpe_development_id"].tolist() == ["100"]
    assert selected.iloc[0]["recent_phase_reason"] == "recent_publication"


def test_shkp_catalog_continues_after_one_category_waf_failure(monkeypatch, tmp_path: Path):
    class Response:
        def __init__(self, *, status_code=200, payload=None, text="<html></html>"):
            self.status_code = status_code
            self._payload = payload
            self.text = text
            self.content = text.encode("utf-8")

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(f"status={self.status_code}")

        def json(self):
            if self._payload is None:
                raise ValueError("not json")
            return self._payload

    configs = (
        {
            "asset_type": "residential_for_sale",
            "subtype": "for_sale",
            "path": "residential-for-sale",
            "container_id": "major_forsales",
            "endpoint_suffix": "",
            "query": {},
        },
        {
            "asset_type": "hotel",
            "subtype": "hotel_type_a",
            "path": "hotels-and-serviced-suites",
            "container_id": "major_hotels",
            "endpoint_suffix": "/ss",
            "query": {},
        },
    )

    class Session:
        headers: dict[str, str] = {}

        def get(self, url, timeout=60):
            if "residential-for-sale" in url and "getList" not in url:
                return Response()
            if "residential-for-sale" in url and "getList" in url:
                return Response(payload=[{"name": "Future Active Phase", "districtLabel": "Kai Tak"}])
            return Response(status_code=999, text="<html>blocked</html>")

    monkeypatch.setattr(shkp, "SHKP_LISTING_CONFIGS", configs)
    monkeypatch.setattr(shkp, "_page_href", lambda html, container_id, landing_url: landing_url)
    monkeypatch.setattr(shkp, "_page_total", lambda html, container_id: 1)
    monkeypatch.setattr(shkp, "save_raw_snapshot", lambda *args, **kwargs: tmp_path / "capture")

    frame = shkp.fetch_shkp_property_catalog(session=Session(), timeout=1)
    assert frame["marketing_name"].tolist() == ["Future Active Phase"]
    summary = frame.attrs["lineage_metadata"]["fetch_summary"]
    assert {row["status"] for row in summary} == {"success", "failed"}
    failed = next(row for row in summary if row["status"] == "failed")
    assert failed["asset_type"] == "hotel"
    assert frame.attrs["lineage_metadata"]["partial_source_refresh"] is True
