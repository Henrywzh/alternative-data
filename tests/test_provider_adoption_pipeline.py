from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from provider_adoption_data.models import (
    GithubRepository,
    GithubSignalMatch,
    PypiDownloadPoint,
    Snapshot,
)
from provider_adoption_data.pipeline import ProviderAdoptionPipeline
from provider_adoption_data.sources.config import get_provider_registry
from provider_adoption_data.sources.github import GithubSource
from provider_adoption_data.sources.pypi import PypiStatsSource


class FakePypiSource:
    def fetch_snapshots(self, providers):
        payloads = []
        for provider in providers:
            for package in provider.pypi_packages:
                body = json.dumps(
                    {
                        "package": package.package_name,
                        "type": "overall_downloads",
                        "data": [
                            {"category": "without_mirrors", "date": "2026-04-04", "downloads": 100},
                            {"category": "without_mirrors", "date": "2026-04-05", "downloads": 120},
                            {"category": "with_mirrors", "date": "2026-04-05", "downloads": 150},
                        ],
                    }
                )
                payloads.append(
                    Snapshot(
                        name=f"pypi_{provider.slug}_{package.package_name}",
                        source_url=f"https://pypistats.org/api/packages/{package.package_name}/overall",
                        body=body,
                    )
                )
        return payloads

    def extract(self, snapshots, providers):
        by_package = {
            package.package_name: (provider.slug, provider.display_name, package.package_type)
            for provider in providers
            for package in provider.pypi_packages
        }
        records = []
        for snapshot in snapshots:
            payload = json.loads(snapshot.body)
            provider_slug, display_name, package_type = by_package[payload["package"]]
            for row in payload["data"]:
                records.append(
                    PypiDownloadPoint(
                        provider=provider_slug,
                        provider_display_name=display_name,
                        package_name=payload["package"],
                        package_type=package_type,
                        with_mirrors=row["category"] == "with_mirrors",
                        download_date=row["date"],
                        downloads=row["downloads"],
                        source_url=snapshot.source_url,
                    )
                )
        return records


class FakeGithubSource:
    SEARCH_LANGUAGE_BUCKETS = ("Python", "JavaScript", "TypeScript")

    def fetch_snapshots(self, target_date):
        repository = GithubRepository(
            full_name="openai/demo-repo",
            owner="openai",
            name="demo-repo",
            html_url="https://github.com/openai/demo-repo",
            created_at=f"{target_date.isoformat()}T10:00:00Z",
            created_date=target_date.isoformat(),
            pushed_at=f"{target_date.isoformat()}T11:00:00Z",
            default_branch="main",
            language_bucket="python",
            is_fork=False,
            is_archived=False,
            stargazers_count=5,
        )
        return [Snapshot(name="github_search_python_1", source_url="https://api.github.com/search/repositories", body="{}")], [repository]

    def inspect_repositories(self, repositories, providers, target_date):
        records = []
        snapshots = [Snapshot(name="tree_openai_demo_repo", source_url="https://api.github.com/repos/openai/demo-repo/git/trees/main", body="{}")]
        for provider in providers:
            if provider.slug == "openai":
                records.extend(
                    [
                        GithubSignalMatch(
                            provider="openai",
                            signal_date=target_date.isoformat(),
                            repo_full_name="openai/demo-repo",
                            signal_type="manifest_dependency",
                            matched_file_path="requirements.txt",
                            matched_pattern="openai",
                            language_bucket="python",
                            repo_created_at=f"{target_date.isoformat()}T10:00:00Z",
                            repo_pushed_at=f"{target_date.isoformat()}T11:00:00Z",
                            repo_default_branch="main",
                            is_fork=False,
                            is_archived=False,
                            stargazers_count=5,
                            source_url="https://github.com/openai/demo-repo",
                        ),
                        GithubSignalMatch(
                            provider="openai",
                            signal_date=target_date.isoformat(),
                            repo_full_name="openai/demo-repo",
                            signal_type="code_import",
                            matched_file_path="src/main.py",
                            matched_pattern="from openai import",
                            language_bucket="python",
                            repo_created_at=f"{target_date.isoformat()}T10:00:00Z",
                            repo_pushed_at=f"{target_date.isoformat()}T11:00:00Z",
                            repo_default_branch="main",
                            is_fork=False,
                            is_archived=False,
                            stargazers_count=5,
                            source_url="https://github.com/openai/demo-repo",
                        ),
                        GithubSignalMatch(
                            provider="openai",
                            signal_date=target_date.isoformat(),
                            repo_full_name="openai/demo-repo",
                            signal_type="env_var",
                            matched_file_path=".env.example",
                            matched_pattern="OPENAI_API_KEY",
                            language_bucket="python",
                            repo_created_at=f"{target_date.isoformat()}T10:00:00Z",
                            repo_pushed_at=f"{target_date.isoformat()}T11:00:00Z",
                            repo_default_branch="main",
                            is_fork=False,
                            is_archived=False,
                            stargazers_count=5,
                            source_url="https://github.com/openai/demo-repo",
                        ),
                        GithubSignalMatch(
                            provider="openai",
                            signal_date=target_date.isoformat(),
                            repo_full_name="openai/demo-repo",
                            signal_type="model_name",
                            matched_file_path="src/main.py",
                            matched_pattern="gpt-4o",
                            language_bucket="python",
                            repo_created_at=f"{target_date.isoformat()}T10:00:00Z",
                            repo_pushed_at=f"{target_date.isoformat()}T11:00:00Z",
                            repo_default_branch="main",
                            is_fork=False,
                            is_archived=False,
                            stargazers_count=5,
                            source_url="https://github.com/openai/demo-repo",
                        ),
                    ]
                )
        return snapshots, records


class FakeResponse:
    def __init__(self, payload: dict, url: str = "https://api.github.com/search/repositories") -> None:
        self._payload = payload
        self.url = url
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self) -> None:
        self.headers = {}
        self.calls = 0

    def get(self, url, params=None, timeout=30):
        self.calls += 1
        if self.calls == 1:
            return FakeResponse(
                {
                    "items": [
                        {
                            "full_name": "openai/alpha",
                            "html_url": "https://github.com/openai/alpha",
                            "created_at": "2026-04-05T10:00:00Z",
                            "pushed_at": "2026-04-05T10:05:00Z",
                            "default_branch": "main",
                            "fork": False,
                            "archived": False,
                            "stargazers_count": 3,
                        },
                        {
                            "full_name": "openai/archived",
                            "html_url": "https://github.com/openai/archived",
                            "created_at": "2026-04-05T10:00:00Z",
                            "pushed_at": "2026-04-05T10:05:00Z",
                            "default_branch": "main",
                            "fork": False,
                            "archived": True,
                            "stargazers_count": 1,
                        },
                    ]
                }
            )
        return FakeResponse({"items": []})


def test_pypi_source_extracts_with_and_without_mirrors() -> None:
    source = PypiStatsSource()
    providers = get_provider_registry(["openai"])
    payload = {
        "package": "openai",
        "type": "overall_downloads",
        "data": [
            {"category": "without_mirrors", "date": "2026-04-04", "downloads": 123},
            {"category": "with_mirrors", "date": "2026-04-04", "downloads": 456},
        ],
    }

    points = source.extract(
        [Snapshot(name="pypi_openai", source_url="https://pypistats.org/api/packages/openai/overall", body=json.dumps(payload))],
        providers,
    )

    assert [(point.with_mirrors, point.downloads) for point in points] == [(False, 123), (True, 456)]


def test_provider_registry_excludes_qwen_from_active_defaults() -> None:
    providers = get_provider_registry()

    assert [provider.slug for provider in providers] == ["openai", "anthropic", "google"]


def test_github_source_fetch_snapshots_handles_pagination_and_filters_archived() -> None:
    source = GithubSource(session=FakeSession(), max_pages_per_language=2)

    snapshots, repositories = source.fetch_snapshots(date.fromisoformat("2026-04-05"))

    assert len(snapshots) == 3
    assert [repo.full_name for repo in repositories] == ["openai/alpha"]


def test_github_source_detects_signal_types_from_candidate_contents() -> None:
    source = GithubSource()
    providers = get_provider_registry(["openai"])
    repository = GithubRepository(
        full_name="openai/demo",
        owner="openai",
        name="demo",
        html_url="https://github.com/openai/demo",
        created_at="2026-04-05T10:00:00Z",
        created_date="2026-04-05",
        pushed_at="2026-04-05T11:00:00Z",
        default_branch="main",
        language_bucket="python",
        is_fork=False,
        is_archived=False,
        stargazers_count=10,
    )
    contents = {
        "requirements.txt": "openai>=1.0.0",
        ".env.example": "OPENAI_API_KEY=\n",
        "src/main.py": "from openai import OpenAI\nMODEL = 'gpt-4o'\n",
    }

    matches = source._detect_matches(repository, providers, contents, "2026-04-05")

    assert {match.signal_type for match in matches} == {
        "manifest_dependency",
        "code_import",
        "env_var",
        "model_name",
    }


def test_provider_pipeline_repeated_runs_are_idempotent_and_write_manifest(tmp_path: Path) -> None:
    pipeline = ProviderAdoptionPipeline(tmp_path, pypi_source=FakePypiSource(), github_source=FakeGithubSource())

    first_pypi = pipeline.run_pypi_daily_update(target_date="2026-04-05", provider_slugs=["openai", "anthropic"])
    second_pypi = pipeline.run_pypi_daily_update(target_date="2026-04-05", provider_slugs=["openai", "anthropic"])
    pipeline.run_github_daily_update(target_date="2026-04-05", provider_slugs=["openai", "anthropic"])
    pipeline.run_github_daily_update(target_date="2026-04-05", provider_slugs=["openai", "anthropic"])
    pipeline.run_derived_daily_update(target_date="2026-04-05", provider_slugs=["openai", "anthropic"])
    derived = pipeline.run_derived_daily_update(target_date="2026-04-05", provider_slugs=["openai", "anthropic"])

    pypi = pd.read_csv(tmp_path / "data" / "normalized" / "provider_adoption" / "pypi_downloads_daily.csv")
    rollup = pd.read_csv(tmp_path / "data" / "normalized" / "provider_adoption" / "github_repo_rollup_daily.csv")
    momentum_csv = pd.read_csv(tmp_path / "data" / "normalized" / "provider_adoption" / "provider_momentum_daily.csv")
    momentum_parquet = pd.read_parquet(tmp_path / "data" / "normalized" / "provider_adoption" / "provider_momentum_daily.parquet")

    assert first_pypi.datasets_written["pypi_downloads_daily"] == second_pypi.datasets_written["pypi_downloads_daily"]
    assert pypi[["provider", "package_name", "with_mirrors", "download_date"]].duplicated().sum() == 0
    assert rollup[["provider", "repo_full_name", "signal_date"]].duplicated().sum() == 0
    assert list(momentum_csv.columns) == list(momentum_parquet.columns)
    assert (Path(derived.raw_run_dir) / "manifest.json").exists()
