from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ai_hiring_data.extract import extract_board, extract_indeed
from ai_hiring_data.models import Snapshot, SourceSpec
from ai_hiring_data.pipeline import AIHiringPipeline
from ai_hiring_data.quality import count_collapsed, validate_board, validate_indeed


MACRO_SPEC = SourceSpec("indeed_ai_tracker", "macro_csv", "https://example.test/AI_posting.csv")
BOARD_SPEC = SourceSpec(
    "ashby_example",
    "job_board",
    "https://api.ashbyhq.com/posting-api/job-board/example",
    company_id="example",
    company_name="Example AI",
    company_segment="Frontier model lab",
    source_platform="ashby",
    board_token="example",
    careers_url="https://jobs.ashbyhq.com/example",
)


def _snapshot(spec: SourceSpec, body: str | None, *, not_modified: bool = False, etag: str = 'W/"one"') -> Snapshot:
    return Snapshot(
        source_id=spec.source_id,
        source_kind=spec.source_kind,
        source_url=spec.source_url,
        body=body,
        content_type="text/csv" if spec.source_kind == "macro_csv" else "application/json",
        status_code=304 if not_modified else 200,
        response_ms=10,
        etag=etag,
        not_modified=not_modified,
    )


def _indeed_body() -> str:
    return "date,jobcountry,AI_share_postings\n2026-07-01,US,5.2\n2026-07-01,GB,4.1\n2026-07-02,US,5.3\n"


def _ashby_body(job_ids: tuple[str, ...] = ("job-1", "job-2")) -> str:
    jobs = []
    for index, job_id in enumerate(job_ids):
        jobs.append(
            {
                "id": job_id,
                "title": "Research Engineer" if index == 0 else "Enterprise Account Executive",
                "department": "Research" if index == 0 else "Sales",
                "team": "Models" if index == 0 else "GTM",
                "location": "San Francisco, United States",
                "address": {"postalAddress": {"addressCountry": "USA"}},
                "workplaceType": "Hybrid",
                "employmentType": "FullTime",
                "publishedAt": "2026-07-01T10:00:00Z",
                "jobUrl": f"https://jobs.ashbyhq.com/example/{job_id}",
                "applyUrl": f"https://jobs.ashbyhq.com/example/{job_id}/apply",
                "isListed": True,
            }
        )
    return json.dumps({"apiVersion": "1", "jobs": jobs})


def test_extracts_indeed_ai_share_with_explicit_units() -> None:
    rows = extract_indeed(_snapshot(MACRO_SPEC, _indeed_body()), run_id="run", scraped_at="2026-07-18T00:00:00Z")
    validate_indeed(rows, production=False)

    assert len(rows) == 3
    assert rows[0]["ai_share_pct"] == 5.2
    assert rows[0]["source_refresh_cadence"] == "monthly"
    assert rows[0]["license"] == "CC-BY-4.0"


def test_extracts_compact_ashby_jobs_without_descriptions() -> None:
    rows = extract_board(_snapshot(BOARD_SPEC, _ashby_body()), BOARD_SPEC)
    validate_board(rows, company_id="example", production=False)

    assert len(rows) == 2
    assert rows[0]["source_job_id"] == "job-1"
    assert rows[0]["country_code"] == "US"
    assert rows[0]["role_family"] == "Research"
    assert rows[0]["is_ai_role"] is True
    assert rows[1]["role_family"] == "Sales / GTM"
    assert "description" not in rows[0]


def test_extracts_greenhouse_requisition_identity() -> None:
    spec = SourceSpec(
        "greenhouse_example", "job_board", "https://boards-api.greenhouse.io/v1/boards/example/jobs",
        company_id="example", company_name="Example AI", company_segment="AI application",
        source_platform="greenhouse", board_token="example", careers_url="https://job-boards.greenhouse.io/example",
    )
    body = json.dumps(
        {
            "jobs": [
                {
                    "id": 123,
                    "internal_job_id": 999,
                    "title": "Machine Learning Engineer",
                    "location": {"name": "London, United Kingdom"},
                    "absolute_url": "https://job-boards.greenhouse.io/example/jobs/123",
                    "first_published": "2026-07-01T09:00:00Z",
                    "updated_at": "2026-07-02T09:00:00Z",
                }
            ]
        }
    )
    rows = extract_board(_snapshot(spec, body), spec)

    assert rows[0]["source_job_id"] == "123"
    assert rows[0]["source_requisition_id"] == "999"
    assert rows[0]["country_code"] == "GB"
    assert rows[0]["role_family"] == "AI / ML"


def test_count_collapse_uses_last_good_baseline() -> None:
    assert count_collapsed(4, 10)
    assert count_collapsed(0, 5)
    assert not count_collapsed(5, 10)
    assert not count_collapsed(0, None)


class _SequenceSource:
    def __init__(self, batches: list[list[Snapshot]]) -> None:
        self.specs = (MACRO_SPEC, BOARD_SPEC)
        self.batches = batches

    def fetch_all(self, validators=None):
        _ = validators
        return self.batches.pop(0), []


def test_job_lifecycle_requires_two_successful_absences_and_reopens(tmp_path: Path) -> None:
    source = _SequenceSource(
        [
            [_snapshot(MACRO_SPEC, _indeed_body()), _snapshot(BOARD_SPEC, _ashby_body())],
            [_snapshot(MACRO_SPEC, None, not_modified=True), _snapshot(BOARD_SPEC, _ashby_body(("job-1",)))],
            [_snapshot(MACRO_SPEC, None, not_modified=True), _snapshot(BOARD_SPEC, _ashby_body(("job-1",)))],
            [_snapshot(MACRO_SPEC, None, not_modified=True), _snapshot(BOARD_SPEC, _ashby_body())],
        ]
    )
    pipeline = AIHiringPipeline(tmp_path, source=source, production_quality=False)

    pipeline.run_daily_update(target_date=pd.Timestamp("2026-07-18").date())
    seeded = pipeline.storage.load("hiring_jobs").set_index("source_job_id")
    events = pipeline.storage.load("hiring_job_events")
    assert set(seeded["status"].astype(str)) == {"active"}
    assert set(events["event_type"].astype(str)) == {"seeded"}

    pipeline.run_daily_update(target_date=pd.Timestamp("2026-07-19").date())
    missing = pipeline.storage.load("hiring_jobs").set_index("source_job_id")
    assert missing.loc["job-2", "status"] == "missing"
    assert missing.loc["job-2", "consecutive_missing_runs"] == 1

    pipeline.run_daily_update(target_date=pd.Timestamp("2026-07-20").date())
    closed = pipeline.storage.load("hiring_jobs").set_index("source_job_id")
    assert closed.loc["job-2", "status"] == "closed"
    assert closed.loc["job-2", "consecutive_missing_runs"] == 2

    pipeline.run_daily_update(target_date=pd.Timestamp("2026-07-21").date())
    reopened = pipeline.storage.load("hiring_jobs").set_index("source_job_id")
    events = pipeline.storage.load("hiring_job_events")
    assert reopened.loc["job-2", "status"] == "active"
    assert reopened.loc["job-2", "consecutive_missing_runs"] == 0
    assert "reopened" in set(events["event_type"].astype(str))

    demand = pipeline.storage.load("hiring_demand_daily")
    totals = demand[demand["role_family"].astype(str) == "All roles"].sort_values("snapshot_date")
    assert totals["active_postings"].astype(int).tolist() == [2, 1, 1, 2]
    assert totals.iloc[0]["new_postings_28d"] == 0


def test_repeated_not_modified_run_is_byte_identical(tmp_path: Path) -> None:
    source = _SequenceSource(
        [
            [_snapshot(MACRO_SPEC, _indeed_body()), _snapshot(BOARD_SPEC, _ashby_body())],
            [
                _snapshot(MACRO_SPEC, None, not_modified=True, etag='W/"two"'),
                _snapshot(BOARD_SPEC, None, not_modified=True, etag='W/"two"'),
            ],
        ]
    )
    pipeline = AIHiringPipeline(tmp_path, source=source, production_quality=False)
    target = pd.Timestamp("2026-07-18").date()
    pipeline.run_daily_update(target_date=target)
    root = tmp_path / "data/normalized/ai_hiring"
    before = {path.name: path.read_bytes() for path in root.glob("*.parquet")}

    pipeline.run_daily_update(target_date=target)
    after = {path.name: path.read_bytes() for path in root.glob("*.parquet")}

    assert before == after


def test_continuous_coverage_resets_after_source_warning(tmp_path: Path) -> None:
    pipeline = AIHiringPipeline(tmp_path, source=_SequenceSource([]), production_quality=False)
    previous = pd.DataFrame(
        [
            {
                "company_id": "example",
                "coverage_start_date": "2026-01-01",
                "continuous_coverage_start_date": "2026-01-01",
            }
        ]
    )
    prior_ok = pd.DataFrame([{"source_id": "ashby_example", "status": "ok"}])
    warning_rows = [{"source_id": "ashby_example", "status": "warning"}]

    warned = pipeline._company_rows(
        run_id="run-warning",
        scraped_at="2026-02-01T00:00:00Z",
        snapshot_date=pd.Timestamp("2026-02-01").date(),
        previous=previous,
        previous_health=prior_ok,
        health_rows=warning_rows,
        board_specs=(BOARD_SPEC,),
    )[0]
    assert warned["coverage_start_date"] == "2026-01-01"
    assert warned["continuous_coverage_start_date"] is None

    warned_company = pd.DataFrame([warned])
    prior_warning = pd.DataFrame([{"source_id": "ashby_example", "status": "warning"}])
    recovered = pipeline._company_rows(
        run_id="run-recovered",
        scraped_at="2026-02-02T00:00:00Z",
        snapshot_date=pd.Timestamp("2026-02-02").date(),
        previous=warned_company,
        previous_health=prior_warning,
        health_rows=[{"source_id": "ashby_example", "status": "ok"}],
        board_specs=(BOARD_SPEC,),
    )[0]
    assert recovered["coverage_start_date"] == "2026-01-01"
    assert recovered["continuous_coverage_start_date"] == "2026-02-02"


def test_same_day_rerun_does_not_double_count_an_absence(tmp_path: Path) -> None:
    source = _SequenceSource(
        [
            [_snapshot(MACRO_SPEC, _indeed_body()), _snapshot(BOARD_SPEC, _ashby_body())],
            [_snapshot(MACRO_SPEC, None, not_modified=True), _snapshot(BOARD_SPEC, _ashby_body(("job-1",)))],
            [_snapshot(MACRO_SPEC, None, not_modified=True), _snapshot(BOARD_SPEC, _ashby_body(("job-1",)))],
        ]
    )
    pipeline = AIHiringPipeline(tmp_path, source=source, production_quality=False)
    first_day = pd.Timestamp("2026-07-18").date()
    missing_day = pd.Timestamp("2026-07-19").date()

    pipeline.run_daily_update(target_date=first_day)
    pipeline.run_daily_update(target_date=missing_day)
    pipeline.run_daily_update(target_date=missing_day)

    jobs = pipeline.storage.load("hiring_jobs").set_index("source_job_id")
    events = pipeline.storage.load("hiring_job_events")
    assert jobs.loc["job-2", "status"] == "missing"
    assert jobs.loc["job-2", "consecutive_missing_runs"] == 1
    assert (events["event_type"].astype(str) == "missing").sum() == 1
