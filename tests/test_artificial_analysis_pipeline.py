from __future__ import annotations

import json
import requests
import sys
from pathlib import Path

import pandas as pd
import pytest

from artificial_analysis_data import cli as artificial_analysis_cli
from artificial_analysis_data.cli import main as artificial_analysis_cli_main
from artificial_analysis_data.models import (
    ArtificialAnalysisModelPoint,
    CapexQuarterPoint,
    PipelineResult,
    Snapshot,
)
from artificial_analysis_data.pipeline import ArtificialAnalysisPipeline
from artificial_analysis_data.sources.api import ArtificialAnalysisApiSource
from artificial_analysis_data.sources.capex import ArtificialAnalysisCapexSource
from artificial_analysis_data.sources.config import resolve_api_key
from artificial_analysis_data.storage import StorageManager


FIXTURES = Path(__file__).parent / "fixtures"


def _load_api_payload() -> dict:
    return json.loads((FIXTURES / "artificial_analysis_llms_models.json").read_text(encoding="utf-8"))


def _load_capex_bundle() -> str:
    return (FIXTURES / "artificial_analysis_trends_page.js").read_text(encoding="utf-8")


def test_api_source_extracts_models_from_fixture_payload() -> None:
    source = ArtificialAnalysisApiSource()
    snapshot = Snapshot(
        name="llms_models",
        source_url="https://artificialanalysis.ai/api/v2/data/llms/models",
        body=json.dumps(_load_api_payload()),
    )

    points = source.extract(
        snapshot,
        run_id="run-123",
        scraped_at="2026-04-25T10:00:00Z",
        as_of_date="2026-04-25",
    )

    assert len(points) == 3
    first = points[0]
    assert first.dataset_id == "artificial_analysis_models_daily"
    assert first.as_of_date == "2026-04-25"
    assert first.model_id == "model-openai-1"
    assert first.creator_slug == "openai"
    assert first.intelligence_index == 42.5
    assert first.price_1m_blended_3_to_1 == 3.0
    assert first.total_parameters_billions == 400.0
    assert first.active_parameters_billions == 40.0
    assert first.training_tokens_trillions == 15.5
    assert first.is_open_weights is False

    second = points[1]
    assert second.scicode is None
    assert second.price_1m_blended_3_to_1 is None
    assert second.open_source_categorization == "Open Weights (Permissive License)"
    assert second.is_open_weights is True


class FakeArtificialAnalysisApiResponse:
    def __init__(self, *, status_code: int, text: str = "", headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class FakeArtificialAnalysisApiSession:
    def __init__(self, responses: list[FakeArtificialAnalysisApiResponse]) -> None:
        self._responses = list(responses)
        self.request_count = 0

    def get(self, url: str, headers: dict[str, str], timeout: int) -> FakeArtificialAnalysisApiResponse:
        self.request_count += 1
        assert headers["x-api-key"] == "test-key"
        if not self._responses:
            raise AssertionError(f"Unexpected Artificial Analysis request: {url}")
        return self._responses.pop(0)


def test_api_source_retries_rate_limit_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("artificial_analysis_data.sources.api.time.sleep", sleeps.append)
    session = FakeArtificialAnalysisApiSession(
        [
            FakeArtificialAnalysisApiResponse(status_code=429, headers={"Retry-After": "0"}),
            FakeArtificialAnalysisApiResponse(status_code=200, text=json.dumps(_load_api_payload())),
        ]
    )
    source = ArtificialAnalysisApiSource(session=session)

    snapshot = source.fetch_snapshot("test-key")

    assert session.request_count == 2
    assert sleeps == [0.0]
    assert snapshot.name == "llms_models"
    assert json.loads(snapshot.body)["data"][0]["id"] == "model-openai-1"


def test_resolve_api_key_prefers_env_then_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".config").write_text(
        "# comment\nARTIFICIAL_ANALYSIS_API_KEY=config-key\nOTHER_KEY=unused\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("ARTIFICIAL_ANALYSIS_API_KEY", raising=False)
    assert resolve_api_key(tmp_path) == "config-key"

    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "env-key")
    assert resolve_api_key(tmp_path) == "env-key"


def test_storage_upserts_models_by_as_of_date_and_model_id(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    original = ArtificialAnalysisModelPoint(
        as_of_date="2026-04-25",
        model_id="model-1",
        model_slug="model-one",
        model_name="Model One",
        creator_id="creator-1",
        creator_name="Creator One",
        creator_slug="creator-one",
        creator_country="us",
        release_date="2025-04-01",
        release_quarter="Q2-2025",
        intelligence_index=30.0,
        coding_index=None,
        math_index=None,
        gpqa=None,
        scicode=None,
        price_1m_blended_3_to_1=None,
        price_1m_input_tokens=None,
        price_1m_output_tokens=None,
        median_output_tokens_per_second=None,
        median_time_to_first_token_seconds=None,
        context_window_tokens=32000,
        total_parameters_billions=10.0,
        active_parameters_billions=None,
        training_tokens_trillions=None,
        open_source_categorization="Proprietary",
        license_name="Commercial",
        is_open_weights=False,
        source_url="fixture://api",
        source_run_id="run-1",
        scraped_at="2026-04-25T00:00:00Z",
    )
    updated = ArtificialAnalysisModelPoint(**{**original.to_dict(), "intelligence_index": 32.0, "source_run_id": "run-2"})

    written = storage.upsert_dataset("artificial_analysis_models_daily", [original, updated])

    assert len(written) == 1
    assert float(written.iloc[0]["intelligence_index"]) == 32.0
    assert written.iloc[0]["source_run_id"] == "run-2"


def test_pipeline_derives_leading_models_and_context_window_quarters(tmp_path: Path) -> None:
    pipeline = ArtificialAnalysisPipeline(tmp_path)
    points = ArtificialAnalysisApiSource().extract(
        Snapshot(
            name="llms_models",
            source_url="fixture://api",
            body=json.dumps(_load_api_payload()),
        ),
        run_id="run-123",
        scraped_at="2026-04-25T10:00:00Z",
        as_of_date="2026-04-25",
    )

    leaders = pipeline._derive_leading_models_by_lab(points, run_id="run-123", scraped_at="2026-04-25T10:00:00Z")
    quarters = pipeline._derive_context_window_quarter(points, run_id="run-123", scraped_at="2026-04-25T10:00:00Z")

    assert {(row.creator_slug, row.model_id) for row in leaders} == {
        ("anthropic", "model-anthropic-1"),
        ("openai", "model-openai-1"),
    }
    assert all(row.dataset_id == "artificial_analysis_leading_models_by_lab_daily" for row in leaders)
    assert all(row.source_url == "fixture://api" for row in leaders)
    by_quarter = {row.release_quarter: row for row in quarters}
    assert all(row.dataset_id == "artificial_analysis_context_window_quarter_daily" for row in quarters)
    assert all(row.source_url == "fixture://api" for row in quarters)
    assert by_quarter["Q2-2025"].context_window_median_proprietary == 200000.0
    assert by_quarter["Q2-2025"].context_window_median_open_source_total == 131072.0
    assert by_quarter["Q2-2025"].proprietary_model_count == 1
    assert by_quarter["Q2-2025"].open_source_model_count == 1
    assert by_quarter["Q2-2024"].context_window_median_proprietary == 100000.0


def test_capex_source_extracts_quarters_from_bundle_fixture() -> None:
    source = ArtificialAnalysisCapexSource()
    snapshots = [
        Snapshot(
            name="trends_page",
            source_url="https://artificialanalysis.ai/trends",
            body='<html><script src="/_next/static/chunks/app/(pages)/trends/page-demo.js"></script></html>',
        ),
        Snapshot(
            name="trends_bundle",
            source_url="https://artificialanalysis.ai/_next/static/chunks/app/(pages)/trends/page-demo.js",
            body=_load_capex_bundle(),
        ),
    ]

    points = source.extract(
        snapshots,
        run_id="run-123",
        scraped_at="2026-04-25T10:00:00Z",
    )

    assert [point.quarter_id for point in points] == ["2025-q2", "2025-q1", "2024-q4"]
    assert points[0].dataset_id == "artificial_analysis_capex_quarterly"
    assert points[0].source_url == "https://artificialanalysis.ai/trends"
    assert points[0].microsoft == 17.079
    assert points[0].bundle_url.endswith("page-demo.js")


def test_capex_source_fetches_shared_capex_data_bundle_when_page_bundle_only_imports_provider() -> None:
    page_html = (
        '<html><script src="/_next/static/chunks/app/(pages)/trends/page-demo.js"></script>'
        '<script>self.__next_f.push([1,"3b:I[70276,[\\"73848\\",'
        '\\"static/chunks/73848-demo.js\\",\\"28155\\",'
        '\\"static/chunks/app/(pages)/trends/page-demo.js\\"],'
        '\\"CapexQuarterContextProvider\\"]"])</script></html>'
    )
    page_bundle = "70276:(e,t,l)=>{l.d(t,{CapexQuarterContextProvider:()=>u})}"
    capex_bundle = (
        '70276:(e,l,o)=>{o.r(l),o.d(l,{CapexQuarterContext:()=>s,'
        'CapexQuarterContextProvider:()=>u});let n=[{id:"2025-q3",label:"Q3-2025",'
        "microsoft:19.394,google:23.953,meta:18.829,amazon:34.228,oracle:8.502,apple:0}];"
        "let s={}}"
    )

    class FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

    class FakeSession:
        def get(self, url: str, timeout: int) -> FakeResponse:
            if url == "https://artificialanalysis.ai/trends":
                return FakeResponse(page_html)
            if url.endswith("/_next/static/chunks/app/(pages)/trends/page-demo.js"):
                return FakeResponse(page_bundle)
            if url.endswith("/_next/static/chunks/73848-demo.js"):
                return FakeResponse(capex_bundle)
            raise AssertionError(f"Unexpected URL: {url}")

    source = ArtificialAnalysisCapexSource(session=FakeSession())

    snapshots = source.fetch_snapshots()
    points = source.extract(snapshots, run_id="run-123", scraped_at="2026-04-25T10:00:00Z")

    assert [snapshot.name for snapshot in snapshots] == ["trends_page", "trends_bundle", "capex_data_bundle"]
    assert points[0].quarter_id == "2025-q3"
    assert points[0].microsoft == 19.394
    assert points[0].bundle_url.endswith("73848-demo.js")


class FakeApiSource:
    def fetch_snapshot(self, api_key: str) -> Snapshot:
        assert api_key == "test-key"
        return Snapshot(
            name="llms_models",
            source_url="fixture://api",
            body=json.dumps(_load_api_payload()),
        )

    def extract(self, snapshot: Snapshot, run_id: str, scraped_at: str, as_of_date: str) -> list[ArtificialAnalysisModelPoint]:
        return ArtificialAnalysisApiSource().extract(snapshot, run_id=run_id, scraped_at=scraped_at, as_of_date=as_of_date)


class FakeCapexSource:
    def fetch_snapshots(self) -> list[Snapshot]:
        return [
            Snapshot(name="trends_page", source_url="fixture://trends", body="<html></html>"),
            Snapshot(name="trends_bundle", source_url="fixture://bundle", body=_load_capex_bundle()),
        ]

    def extract(self, snapshots: list[Snapshot], run_id: str, scraped_at: str) -> list[CapexQuarterPoint]:
        return ArtificialAnalysisCapexSource().extract(
            [
                Snapshot(
                    name="trends_page",
                    source_url="https://artificialanalysis.ai/trends",
                    body='<html><script src="/_next/static/chunks/app/(pages)/trends/page-demo.js"></script></html>',
                ),
                Snapshot(
                    name="trends_bundle",
                    source_url="https://artificialanalysis.ai/_next/static/chunks/app/(pages)/trends/page-demo.js",
                    body=_load_capex_bundle(),
                ),
            ],
            run_id=run_id,
            scraped_at=scraped_at,
        )


def test_pipeline_daily_update_writes_raw_and_normalized_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "test-key")
    pipeline = ArtificialAnalysisPipeline(tmp_path, api_source=FakeApiSource(), capex_source=FakeCapexSource())

    result = pipeline.run_daily_update()

    assert result.datasets_written["artificial_analysis_models_daily"] == 3
    assert result.datasets_written["artificial_analysis_leading_models_by_lab_daily"] == 2
    assert result.datasets_written["artificial_analysis_context_window_quarter_daily"] == 2
    assert result.datasets_written["artificial_analysis_capex_quarterly"] == 3
    manifest = json.loads((Path(result.raw_run_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "artificial_analysis"
    assert (tmp_path / "data" / "normalized" / "artificial_analysis" / "artificial_analysis_models_daily.csv").exists()
    assert (tmp_path / "data" / "normalized" / "artificial_analysis" / "artificial_analysis_models_daily.parquet").exists()
    assert (tmp_path / "data" / "normalized" / "artificial_analysis" / "artificial_analysis_capex_quarterly.csv").exists()


def test_validate_returns_api_and_capex_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "test-key")
    pipeline = ArtificialAnalysisPipeline(tmp_path, api_source=FakeApiSource(), capex_source=FakeCapexSource())

    counts = pipeline.validate()

    assert counts == {"api_models": 3, "capex_quarters": 3, "context_window_fields_missing": 0}


class FakeApiSourceNoContext:
    def fetch_snapshot(self, api_key: str) -> Snapshot:
        assert api_key == "test-key"
        payload = _load_api_payload()
        for item in payload["data"]:
            item.pop("context_window_tokens", None)
            item.pop("context_window", None)
        return Snapshot(
            name="llms_models",
            source_url="fixture://api",
            body=json.dumps(payload),
        )

    def extract(self, snapshot: Snapshot, run_id: str, scraped_at: str, as_of_date: str) -> list[ArtificialAnalysisModelPoint]:
        points = ArtificialAnalysisApiSource().extract(snapshot, run_id=run_id, scraped_at=scraped_at, as_of_date=as_of_date)
        return [ArtificialAnalysisModelPoint(**{**point.to_dict(), "context_window_tokens": None}) for point in points]


def test_pipeline_skips_writing_empty_context_window_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "test-key")
    pipeline = ArtificialAnalysisPipeline(tmp_path, api_source=FakeApiSourceNoContext(), capex_source=FakeCapexSource())

    result = pipeline.run_daily_update()

    assert "artificial_analysis_context_window_quarter_daily" not in result.datasets_written
    assert not (tmp_path / "data" / "normalized" / "artificial_analysis" / "artificial_analysis_context_window_quarter_daily.csv").exists()


def test_validate_reports_missing_context_window_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "test-key")
    pipeline = ArtificialAnalysisPipeline(tmp_path, api_source=FakeApiSourceNoContext(), capex_source=FakeCapexSource())

    counts = pipeline.validate()

    assert counts["api_models"] == 3
    assert counts["capex_quarters"] == 3
    assert counts["context_window_fields_missing"] == 1


def test_cli_smoke_commands(monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path) -> None:
    class FakePipeline:
        def __init__(self, base_dir: Path) -> None:
            self.base_dir = base_dir

        def run_daily_update(self) -> PipelineResult:
            return PipelineResult(
                run_id="run-123",
                datasets_written={"artificial_analysis_models_daily": 3},
                raw_run_dir=str(self.base_dir / "raw"),
                dataset_row_deltas={"artificial_analysis_models_daily": 3},
            )

        def run_capex_update(self) -> PipelineResult:
            return PipelineResult(
                run_id="run-456",
                datasets_written={"artificial_analysis_capex_quarterly": 5},
                raw_run_dir=str(self.base_dir / "raw-capex"),
                dataset_row_deltas={"artificial_analysis_capex_quarterly": 0},
            )

        def validate(self) -> dict[str, int]:
            return {"api_models": 7, "capex_quarters": 21}

    monkeypatch.setattr(artificial_analysis_cli, "ArtificialAnalysisPipeline", FakePipeline)

    monkeypatch.setattr(sys, "argv", ["artificial-analysis-data", "--base-dir", str(tmp_path), "daily-update"])
    artificial_analysis_cli_main()
    out = capsys.readouterr().out
    assert "run_id=run-123" in out
    assert "artificial_analysis_models_daily: total_rows=3 new_rows=3" in out

    monkeypatch.setattr(sys, "argv", ["artificial-analysis-data", "--base-dir", str(tmp_path), "capex-update"])
    artificial_analysis_cli_main()
    out = capsys.readouterr().out
    assert "run_id=run-456" in out
    assert "artificial_analysis_capex_quarterly: total_rows=5 new_rows=0" in out

    monkeypatch.setattr(sys, "argv", ["artificial-analysis-data", "--base-dir", str(tmp_path), "validate"])
    artificial_analysis_cli_main()
    out = capsys.readouterr().out
    assert "api_models: 7" in out
    assert "capex_quarters: 21" in out


def test_pyproject_exposes_artificial_analysis_cli_script() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")

    assert 'artificial-analysis-data = "artificial_analysis_data.cli:main"' in text
