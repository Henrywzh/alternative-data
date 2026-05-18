from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path
from contextlib import redirect_stdout

import pandas as pd
import pytest
import requests

from provider_adoption_data.models import (
    GithubRepository,
    GithubSignalMatch,
    HuggingFaceModelPoint,
    NpmDownloadPoint,
    PypiDownloadPoint,
    Snapshot,
    sanitize_filename,
)
from provider_adoption_data.cli import _print_result
from provider_adoption_data.pipeline import ProviderAdoptionPipeline
from provider_adoption_data.sources.config import get_provider_registry
from provider_adoption_data.sources.github import GithubSource
from provider_adoption_data.sources.huggingface import HuggingFaceSource
from provider_adoption_data.sources.npm import NpmDownloadsSource
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
            package.package_name: (provider.slug, provider.display_name, package.package_type, package.package_category)
            for provider in providers
            for package in provider.pypi_packages
        }
        records = []
        for snapshot in snapshots:
            payload = json.loads(snapshot.body)
            provider_slug, display_name, package_type, package_category = by_package[payload["package"]]
            for row in payload["data"]:
                records.append(
                    PypiDownloadPoint(
                        provider=provider_slug,
                        provider_display_name=display_name,
                        package_name=payload["package"],
                        package_type=package_type,
                        package_category=package_category,
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


class FakeNpmSource:
    def fetch_snapshots(self, providers, start_date, end_date):
        payloads = []
        for provider in providers:
            for package in provider.npm_packages:
                body = json.dumps(
                    {
                        "package": package.package_name,
                        "start": start_date.isoformat(),
                        "end": end_date.isoformat(),
                        "downloads": [
                            {"day": "2026-04-04", "downloads": 200},
                            {"day": "2026-04-05", "downloads": 240},
                        ],
                    }
                )
                payloads.append(
                    Snapshot(
                        name=f"npm_{provider.slug}_{package.package_name}".replace("/", "_"),
                        source_url=f"https://api.npmjs.org/downloads/range/{start_date.isoformat()}:{end_date.isoformat()}/{package.package_name}",
                        body=body,
                    )
                )
        return payloads

    def extract(self, snapshots, providers):
        by_package = {
            package.package_name: (provider.slug, provider.display_name, package.package_type, package.package_category)
            for provider in providers
            for package in provider.npm_packages
        }
        records = []
        for snapshot in snapshots:
            payload = json.loads(snapshot.body)
            provider_slug, display_name, package_type, package_category = by_package[payload["package"]]
            for row in payload["downloads"]:
                records.append(
                    NpmDownloadPoint(
                        provider=provider_slug,
                        provider_display_name=display_name,
                        package_name=payload["package"],
                        package_type=package_type,
                        package_category=package_category,
                        download_date=row["day"],
                        downloads=row["downloads"],
                        source_url=snapshot.source_url,
                    )
                )
        return records


class FakeHuggingFaceResponse:
    def __init__(self, payload, *, links=None, url: str = "https://huggingface.co/api/models") -> None:
        self._payload = payload
        self.links = links or {}
        self.url = url
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class FakeHuggingFaceSession:
    def __init__(self, responses=None) -> None:
        self.headers = {}
        self._responses = list(responses or [])
        self.requested_urls: list[str] = []

    def get(self, url, timeout=30):
        self.requested_urls.append(url)
        if not self._responses:
            raise AssertionError(f"Unexpected Hugging Face request: {url}")
        return self._responses.pop(0)


class FakeHuggingFaceSource:
    def __init__(self, points_by_call: list[list[HuggingFaceModelPoint]]) -> None:
        self.points_by_call = points_by_call
        self.calls = 0
        self._current_points: list[HuggingFaceModelPoint] = []

    def fetch_snapshots(self, providers):
        index = min(self.calls, len(self.points_by_call) - 1)
        self._current_points = self.points_by_call[index]
        return [
            Snapshot(
                name=f"huggingface_{point.provider}",
                source_url=point.source_url,
                body="[]",
            )
            for point in self._current_points
        ]

    def extract(self, snapshots, providers):
        points = self._current_points
        self.calls += 1
        return points


class FakePypiResponse:
    def __init__(
        self,
        *,
        status_code: int,
        text: str = "",
        url: str = "https://pypistats.org/api/packages/openai/overall",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.url = url
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error for {self.url}", response=self)


class FakePypiSession:
    def __init__(self, responses) -> None:
        self.headers = {}
        self._responses = list(responses)
        self.requested_urls: list[str] = []

    def get(self, url, timeout=30):
        self.requested_urls.append(url)
        if not self._responses:
            raise AssertionError(f"Unexpected PyPI request: {url}")
        return self._responses.pop(0)


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


class FakeGithubApiResponse:
    def __init__(self, payload, *, url: str, status_code: int = 200) -> None:
        self._payload = payload
        self.url = url
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeGithubApiSession:
    def __init__(self, responses) -> None:
        self.headers = {}
        self._responses = list(responses)
        self.requested_urls: list[str] = []

    def get(self, url, params=None, timeout=30):
        self.requested_urls.append(url)
        if not self._responses:
            raise AssertionError(f"Unexpected GitHub contents request: {url}")
        return self._responses.pop(0)


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
    assert all(point.package_category == "core_sdk" for point in points)


def test_pypi_source_retries_rate_limit_and_recovers() -> None:
    session = FakePypiSession(
        [
            FakePypiResponse(status_code=429, headers={"Retry-After": "0"}),
            FakePypiResponse(
                status_code=200,
                text=json.dumps(
                    {
                        "package": "openai",
                        "type": "overall_downloads",
                        "data": [{"category": "without_mirrors", "date": "2026-04-05", "downloads": 120}],
                    }
                ),
            ),
        ]
    )
    source = PypiStatsSource(session=session)

    snapshots = source.fetch_snapshots(get_provider_registry(["openai"]))

    assert len(snapshots) == 1
    assert len(session.requested_urls) == 2
    assert json.loads(snapshots[0].body)["package"] == "openai"


def test_pypi_source_skips_package_after_repeated_rate_limits() -> None:
    session = FakePypiSession(
        [
            FakePypiResponse(status_code=429, url="https://pypistats.org/api/packages/openai/overall", headers={"Retry-After": "0"}),
            FakePypiResponse(status_code=429, url="https://pypistats.org/api/packages/openai/overall", headers={"Retry-After": "0"}),
            FakePypiResponse(status_code=429, url="https://pypistats.org/api/packages/openai/overall", headers={"Retry-After": "0"}),
            FakePypiResponse(
                status_code=200,
                url="https://pypistats.org/api/packages/anthropic/overall",
                text=json.dumps(
                    {
                        "package": "anthropic",
                        "type": "overall_downloads",
                        "data": [{"category": "without_mirrors", "date": "2026-04-05", "downloads": 220}],
                    }
                ),
            ),
        ]
    )
    source = PypiStatsSource(session=session)

    snapshots = source.fetch_snapshots(get_provider_registry(["openai", "anthropic"]))

    assert len(snapshots) == 1
    assert json.loads(snapshots[0].body)["package"] == "anthropic"
    assert session.requested_urls.count("https://pypistats.org/api/packages/openai/overall") == 3


def test_npm_source_extracts_scoped_package_downloads() -> None:
    source = NpmDownloadsSource()
    providers = get_provider_registry(["anthropic"])
    payload = {
        "package": "@anthropic-ai/sdk",
        "start": "2026-04-01",
        "end": "2026-04-05",
        "downloads": [
            {"day": "2026-04-04", "downloads": 321},
            {"day": "2026-04-05", "downloads": 654},
        ],
    }

    points = source.extract(
        [
            Snapshot(
                name="npm_anthropic_sdk",
                source_url="https://api.npmjs.org/downloads/range/2026-04-01:2026-04-05/@anthropic-ai%2Fsdk",
                body=json.dumps(payload),
            )
        ],
        providers,
    )

    assert [(point.package_name, point.downloads) for point in points] == [
        ("@anthropic-ai/sdk", 321),
        ("@anthropic-ai/sdk", 654),
    ]
    assert all(point.package_category == "core_sdk" for point in points)


def test_huggingface_source_fetches_paginated_snapshots_and_sets_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf-test-token")
    session = FakeHuggingFaceSession(
        responses=[
            FakeHuggingFaceResponse(
                [{"id": "deepseek-ai/DeepSeek-R1", "author": "deepseek-ai", "downloads": 10, "downloadsAllTime": 100}],
                links={"next": {"url": "https://huggingface.co/api/models?author=deepseek-ai&cursor=next"}},
            ),
            FakeHuggingFaceResponse(
                [{"id": "deepseek-ai/DeepSeek-V3", "author": "deepseek-ai", "downloads": 20, "downloadsAllTime": 200}]
            ),
        ]
    )
    source = HuggingFaceSource(session=session)

    snapshots = source.fetch_snapshots(get_provider_registry(["deepseek"]))

    assert session.headers["Authorization"] == "Bearer hf-test-token"
    assert len(session.requested_urls) == 2
    assert len(snapshots) == 1
    payload = json.loads(snapshots[0].body)
    assert [row["id"] for row in payload] == ["deepseek-ai/DeepSeek-R1", "deepseek-ai/DeepSeek-V3"]


def test_huggingface_source_extracts_author_fallback_and_metrics() -> None:
    source = HuggingFaceSource(session=FakeHuggingFaceSession())
    providers = get_provider_registry(["openai"])
    payload = [
        {
            "id": "openai/gpt-oss-20b",
            "downloads": 321,
            "downloadsAllTime": 4321,
            "likes": 44,
            "lastModified": "2026-04-05T12:00:00.000Z",
        }
    ]

    points = source.extract(
        [
            Snapshot(
                name="huggingface_openai_openai",
                source_url="https://huggingface.co/api/models?author=openai&expand=author&expand=downloads",
                body=json.dumps(payload),
            )
        ],
        providers,
    )

    assert len(points) == 1
    assert points[0].author == "openai"
    assert points[0].model_id == "openai/gpt-oss-20b"
    assert points[0].downloads_30d == 321
    assert points[0].downloads_all_time == 4321
    assert points[0].likes == 44
    assert points[0].last_modified == "2026-04-05T12:00:00.000Z"


def test_provider_registry_includes_hf_defaults() -> None:
    providers = get_provider_registry()

    assert [provider.slug for provider in providers] == [
        "openai",
        "anthropic",
        "google",
        "deepseek",
        "meta",
        "mistral",
        "qwen",
        "moonshot",
        "minimax",
        "zai",
        "langchain",
        "pydantic_ai",
    ]
    assert {provider.slug: [(package.package_name, package.package_category) for package in provider.npm_packages] for provider in providers} == {
        "openai": [
            ("openai", "core_sdk"),
            ("@openai/agents", "agent_sdk"),
            ("@openai/codex", "cli"),
            ("@openai/codex-sdk", "agent_sdk"),
        ],
        "anthropic": [
            ("@anthropic-ai/sdk", "core_sdk"),
            ("@anthropic-ai/claude-agent-sdk", "agent_sdk"),
            ("@anthropic-ai/claude-code", "cli"),
        ],
        "google": [
            ("@google/genai", "core_sdk"),
            ("@google/gemini-cli", "cli"),
            ("@google/generative-ai", "legacy_sdk"),
        ],
        "deepseek": [],
        "meta": [],
        "mistral": [("@mistralai/mistralai", "core_sdk")],
        "qwen": [],
        "moonshot": [],
        "minimax": [],
        "zai": [],
        "langchain": [
            ("@langchain/core", "framework_core"),
            ("@langchain/langgraph", "framework_graph"),
        ],
        "pydantic_ai": [],
    }
    assert {provider.slug: [(package.package_name, package.package_category) for package in provider.pypi_packages] for provider in providers}["langchain"] == [
        ("langchain", "framework_core"),
        ("langgraph", "framework_graph"),
    ]
    assert {provider.slug: [(package.package_name, package.package_category) for package in provider.pypi_packages] for provider in providers}["pydantic_ai"] == [
        ("pydantic-ai", "framework_agent"),
    ]


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


def test_github_source_fetch_file_skips_list_payloads_without_crashing() -> None:
    session = FakeGithubApiSession(
        [
            FakeGithubApiResponse(
                [{"name": "nested.txt"}],
                url="https://api.github.com/repos/openai/demo/contents/package.json",
            )
        ]
    )
    source = GithubSource(session=session)

    snapshot, content = source._fetch_file("openai/demo", "package.json")

    assert content is None
    assert snapshot is not None
    body = json.loads(snapshot.body)
    assert body["path"] == "package.json"
    assert body["response_type"] == "list"
    assert body["item_count"] == 1


def test_github_source_fetch_file_skips_non_base64_payloads() -> None:
    session = FakeGithubApiSession(
        [
            FakeGithubApiResponse(
                {"type": "file", "encoding": "utf-8", "content": "plain-text"},
                url="https://api.github.com/repos/openai/demo/contents/src/main.py",
            )
        ]
    )
    source = GithubSource(session=session)

    snapshot, content = source._fetch_file("openai/demo", "src/main.py")

    assert content is None
    assert snapshot is not None
    body = json.loads(snapshot.body)
    assert body["type"] == "file"
    assert body["encoding"] == "utf-8"


def test_github_source_inspect_repositories_continues_after_unprocessable_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    monkeypatch.setattr(
        source,
        "_fetch_tree",
        lambda repo: (
            Snapshot(
                name="tree_openai_demo",
                source_url="https://api.github.com/repos/openai/demo/git/trees/main",
                body="{}",
            ),
            ["package.json", "src/main.py"],
        ),
    )

    def fake_fetch_file(full_name: str, path: str) -> tuple[Snapshot, str | None]:
        snapshot = Snapshot(
            name=f"file_{path}",
            source_url=f"https://api.github.com/repos/{full_name}/contents/{path}",
            body=json.dumps({"path": path}),
        )
        if path == "package.json":
            return snapshot, None
        return snapshot, "from openai import OpenAI\n"

    monkeypatch.setattr(source, "_fetch_file", fake_fetch_file)

    snapshots, matches = source.inspect_repositories([repository], providers, date.fromisoformat("2026-04-05"))

    assert len(snapshots) == 3
    assert {match.signal_type for match in matches} == {"code_import"}
    assert matches[0].matched_file_path == "src/main.py"


def test_sanitize_filename_replaces_artifact_invalid_characters() -> None:
    sanitized = sanitize_filename("file_9261834245z-ui/ultracore-rft-solana-demo_test:invariant_test.js")

    assert sanitized == "file_9261834245z-ui__ultracore-rft-solana-demo_test_invariant_test_js"
    assert not any(char in sanitized for char in "\"<>|*?:\r\n")


def test_provider_pipeline_repeated_runs_are_idempotent_and_write_manifest(tmp_path: Path) -> None:
    pipeline = ProviderAdoptionPipeline(
        tmp_path,
        pypi_source=FakePypiSource(),
        npm_source=FakeNpmSource(),
        github_source=FakeGithubSource(),
    )

    first_pypi = pipeline.run_pypi_daily_update(target_date="2026-04-05", provider_slugs=["openai", "anthropic", "google"])
    second_pypi = pipeline.run_pypi_daily_update(target_date="2026-04-05", provider_slugs=["openai", "anthropic", "google"])
    first_npm = pipeline.run_npm_daily_update(target_date="2026-04-05", provider_slugs=["openai", "anthropic", "google"])
    second_npm = pipeline.run_npm_daily_update(target_date="2026-04-05", provider_slugs=["openai", "anthropic", "google"])
    pipeline.run_github_daily_update(target_date="2026-04-05", provider_slugs=["openai", "anthropic", "google"])
    pipeline.run_github_daily_update(target_date="2026-04-05", provider_slugs=["openai", "anthropic", "google"])
    pipeline.run_derived_daily_update(target_date="2026-04-05", provider_slugs=["openai", "anthropic", "google"])
    derived = pipeline.run_derived_daily_update(target_date="2026-04-05", provider_slugs=["openai", "anthropic", "google"])

    pypi = pd.read_csv(tmp_path / "data" / "normalized" / "provider_adoption" / "pypi_downloads_daily.csv")
    npm = pd.read_csv(tmp_path / "data" / "normalized" / "provider_adoption" / "npm_downloads_daily.csv")
    rollup = pd.read_csv(tmp_path / "data" / "normalized" / "provider_adoption" / "github_repo_rollup_daily.csv")
    gold = pd.read_csv(tmp_path / "data" / "normalized" / "provider_adoption" / "github_provider_adoption_daily.csv")
    momentum_csv = pd.read_csv(tmp_path / "data" / "normalized" / "provider_adoption" / "provider_momentum_daily.csv")
    momentum_parquet = pd.read_parquet(tmp_path / "data" / "normalized" / "provider_adoption" / "provider_momentum_daily.parquet")

    assert first_pypi.datasets_written["pypi_downloads_daily"] == second_pypi.datasets_written["pypi_downloads_daily"]
    assert first_npm.datasets_written["npm_downloads_daily"] == second_npm.datasets_written["npm_downloads_daily"]
    assert pypi[["provider", "package_name", "with_mirrors", "download_date"]].duplicated().sum() == 0
    assert npm[["provider", "package_name", "package_category", "download_date"]].duplicated().sum() == 0
    assert rollup[["provider", "repo_full_name", "signal_date"]].duplicated().sum() == 0
    assert gold[["provider", "signal_date"]].duplicated().sum() == 0
    assert list(momentum_csv.columns) == list(momentum_parquet.columns)
    assert (Path(derived.raw_run_dir) / "manifest.json").exists()


def test_github_signal_records_include_provider_display_name(tmp_path: Path) -> None:
    pipeline = ProviderAdoptionPipeline(
        tmp_path,
        github_source=FakeGithubSource(),
    )

    pipeline.run_github_daily_update(target_date="2026-04-05", provider_slugs=["openai", "anthropic", "google"])

    signals = pd.read_csv(tmp_path / "data" / "normalized" / "provider_adoption" / "github_provider_signals_daily.csv")
    rollup = pd.read_csv(tmp_path / "data" / "normalized" / "provider_adoption" / "github_repo_rollup_daily.csv")
    gold = pd.read_csv(tmp_path / "data" / "normalized" / "provider_adoption" / "github_provider_adoption_daily.csv")

    assert set(signals["provider_display_name"].dropna().unique()) == {"OpenAI"}
    assert set(signals["signal_type"].unique()) == {"manifest_dependency", "code_import", "env_var", "model_name"}
    assert int(rollup.loc[rollup["provider"] == "openai", "matched_signal_count"].iloc[0]) == 4
    assert bool(rollup.loc[rollup["provider"] == "openai", "has_manifest_dependency"].iloc[0]) is True
    assert bool(rollup.loc[rollup["provider"] == "anthropic", "has_manifest_dependency"].iloc[0]) is False

    openai = gold[gold["provider"] == "openai"].iloc[0]
    anthropic = gold[gold["provider"] == "anthropic"].iloc[0]
    assert int(openai["github_new_repo_count"]) == 1
    assert int(openai["github_signal_repo_count"]) == 1
    assert int(openai["github_manifest_repo_count"]) == 1
    assert int(openai["github_import_repo_count"]) == 1
    assert int(openai["github_env_repo_count"]) == 1
    assert int(openai["github_model_repo_count"]) == 1
    assert int(openai["matched_signal_count"]) == 4
    assert int(anthropic["github_new_repo_count"]) == 1
    assert int(anthropic["github_signal_repo_count"]) == 0
    assert int(anthropic["matched_signal_count"]) == 0


def test_huggingface_pipeline_first_snapshot_is_blank_and_same_day_rerun_is_idempotent(tmp_path: Path) -> None:
    pipeline = ProviderAdoptionPipeline(
        tmp_path,
        hf_source=FakeHuggingFaceSource(
            points_by_call=[
                [
                    HuggingFaceModelPoint(
                        provider="openai",
                        author="openai",
                        model_id="openai/gpt-oss-20b",
                        downloads_30d=100.0,
                        downloads_all_time=1000.0,
                        likes=10.0,
                        last_modified="2026-04-05T12:00:00.000Z",
                        scraped_at="2026-04-05T12:00:00Z",
                        source_url="https://huggingface.co/api/models?author=openai",
                    )
                ]
            ]
        ),
    )

    first = pipeline.run_huggingface_daily_update(target_date="2026-04-05", provider_slugs=["openai"])
    second = pipeline.run_huggingface_daily_update(target_date="2026-04-05", provider_slugs=["openai"])

    hf = pd.read_csv(tmp_path / "data" / "normalized" / "provider_adoption" / "huggingface_models_daily.csv")

    assert first.datasets_written["huggingface_models_daily"] == second.datasets_written["huggingface_models_daily"]
    assert hf[["provider", "author", "model_id", "download_date"]].duplicated().sum() == 0
    assert pd.isna(hf.loc[0, "hf_downloads_daily_est"])
    assert hf.loc[0, "provider_display_name"] == "OpenAI"


def test_huggingface_pipeline_uses_latest_prior_snapshot_only(tmp_path: Path) -> None:
    pipeline = ProviderAdoptionPipeline(
        tmp_path,
        hf_source=FakeHuggingFaceSource(
            points_by_call=[
                [
                    HuggingFaceModelPoint(
                        provider="openai",
                        author="openai",
                        model_id="openai/gpt-oss-20b",
                        downloads_30d=100.0,
                        downloads_all_time=1000.0,
                        likes=10.0,
                        last_modified="2026-04-05T12:00:00.000Z",
                        scraped_at="2026-04-05T12:00:00Z",
                        source_url="https://huggingface.co/api/models?author=openai",
                    )
                ],
                [
                    HuggingFaceModelPoint(
                        provider="openai",
                        author="openai",
                        model_id="openai/gpt-oss-20b",
                        downloads_30d=120.0,
                        downloads_all_time=1250.0,
                        likes=12.0,
                        last_modified="2026-04-06T12:00:00.000Z",
                        scraped_at="2026-04-06T12:00:00Z",
                        source_url="https://huggingface.co/api/models?author=openai",
                    )
                ],
                [
                    HuggingFaceModelPoint(
                        provider="openai",
                        author="openai",
                        model_id="openai/gpt-oss-20b",
                        downloads_30d=90.0,
                        downloads_all_time=900.0,
                        likes=9.0,
                        last_modified="2026-04-04T12:00:00.000Z",
                        scraped_at="2026-04-04T12:00:00Z",
                        source_url="https://huggingface.co/api/models?author=openai",
                    )
                ],
            ]
        ),
    )

    pipeline.run_huggingface_daily_update(target_date="2026-04-05", provider_slugs=["openai"])
    pipeline.run_huggingface_daily_update(target_date="2026-04-06", provider_slugs=["openai"])
    pipeline.run_huggingface_daily_update(target_date="2026-04-04", provider_slugs=["openai"])

    hf = pd.read_csv(tmp_path / "data" / "normalized" / "provider_adoption" / "huggingface_models_daily.csv")
    by_date = hf.set_index("download_date")

    assert pd.isna(by_date.loc["2026-04-04", "hf_downloads_daily_est"])
    assert pd.isna(by_date.loc["2026-04-05", "hf_downloads_daily_est"])
    assert float(by_date.loc["2026-04-06", "hf_downloads_daily_est"]) == 250.0


def test_npm_start_date_aligns_to_existing_pypi_history(tmp_path: Path) -> None:
    pipeline = ProviderAdoptionPipeline(tmp_path, pypi_source=FakePypiSource(), npm_source=FakeNpmSource(), github_source=FakeGithubSource())

    pipeline.run_pypi_daily_update(target_date="2026-04-05", provider_slugs=["openai", "anthropic"])
    start_date = pipeline._resolve_npm_start_date(date.fromisoformat("2026-04-05"), get_provider_registry(["openai", "anthropic"]))

    assert start_date.isoformat() == "2026-04-04"


def test_framework_package_daily_updates_write_requested_langchain_and_pydantic_ai_series(tmp_path: Path) -> None:
    pipeline = ProviderAdoptionPipeline(
        tmp_path,
        pypi_source=FakePypiSource(),
        npm_source=FakeNpmSource(),
    )

    pipeline.run_pypi_daily_update(target_date="2026-04-05", provider_slugs=["langchain", "pydantic_ai"])
    pipeline.run_npm_daily_update(target_date="2026-04-05", provider_slugs=["langchain"])

    pypi = pd.read_csv(tmp_path / "data" / "normalized" / "provider_adoption" / "pypi_downloads_daily.csv")
    npm = pd.read_csv(tmp_path / "data" / "normalized" / "provider_adoption" / "npm_downloads_daily.csv")

    assert set(pypi["provider"].unique()) == {"langchain", "pydantic_ai"}
    assert set(pypi["package_name"].unique()) == {"langchain", "langgraph", "pydantic-ai"}
    assert set(pypi["package_category"].dropna().unique()) == {"framework_core", "framework_graph", "framework_agent"}
    assert set(npm["provider"].unique()) == {"langchain"}
    assert set(npm["package_name"].unique()) == {"@langchain/core", "@langchain/langgraph"}
    assert set(npm["package_category"].dropna().unique()) == {"framework_core", "framework_graph"}


def test_backfill_returns_all_raw_run_directories_and_preserves_last_raw_run_dir(tmp_path: Path) -> None:
    pipeline = ProviderAdoptionPipeline(
        tmp_path,
        pypi_source=FakePypiSource(),
        npm_source=FakeNpmSource(),
        github_source=FakeGithubSource(),
    )

    result = pipeline.run_backfill(
        start_date="2026-04-04",
        end_date="2026-04-05",
        provider_slugs=["openai", "anthropic"],
    )

    assert len(result.raw_run_dirs) == 6
    assert result.raw_run_dir == result.raw_run_dirs[-1]
    assert len(set(result.raw_run_dirs)) == len(result.raw_run_dirs)
    assert all((Path(raw_run_dir) / "manifest.json").exists() for raw_run_dir in result.raw_run_dirs)


def test_print_result_emits_each_backfill_raw_run_directory_once() -> None:
    buffer = io.StringIO()

    with redirect_stdout(buffer):
        _print_result(
            type(
                "BackfillLikeResult",
                (),
                {
                    "run_id": "run-123",
                    "datasets_written": {"provider_momentum_daily": 2},
                    "raw_run_dir": "/tmp/raw-2",
                    "raw_run_dirs": ["/tmp/raw-1", "/tmp/raw-2", "/tmp/raw-2"],
                },
            )()
        )

    assert buffer.getvalue().splitlines() == [
        "run_id=run-123",
        "provider_momentum_daily: 2 rows written",
        "raw_run_dir=/tmp/raw-1",
        "raw_run_dir=/tmp/raw-2",
    ]
