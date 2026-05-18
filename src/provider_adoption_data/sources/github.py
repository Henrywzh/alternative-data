from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import date
from typing import Iterable

import requests

from provider_adoption_data.models import GithubRepository, GithubSignalMatch, ProviderConfig, Snapshot, sanitize_filename


class GithubSource:
    SEARCH_URL = "https://api.github.com/search/repositories"
    REPO_URL = "https://api.github.com/repos"
    SEARCH_LANGUAGE_BUCKETS = ("Python", "JavaScript", "TypeScript")
    EXACT_PATHS = ("requirements.txt", "pyproject.toml", "package.json", ".env.example", "Dockerfile")
    CODE_SUFFIXES = (".py", ".js", ".ts", ".tsx", ".mts", ".cts")

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        token: str | None = None,
        max_pages_per_language: int = 2,
        max_code_files_per_repo: int = 12,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault("Accept", "application/vnd.github+json")
        self.session.headers.setdefault("User-Agent", "alternative-data-provider-adoption/0.1")
        api_token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if api_token:
            self.session.headers.setdefault("Authorization", f"Bearer {api_token}")
        self.max_pages_per_language = max_pages_per_language
        self.max_code_files_per_repo = max_code_files_per_repo

    def fetch_snapshots(self, target_date: date) -> tuple[list[Snapshot], list[GithubRepository]]:
        snapshots: list[Snapshot] = []
        repositories: dict[str, GithubRepository] = {}
        date_str = target_date.isoformat()
        for language_bucket in self.SEARCH_LANGUAGE_BUCKETS:
            for page in range(1, self.max_pages_per_language + 1):
                params = {
                    "q": f"created:{date_str} fork:false archived:false is:public language:{language_bucket}",
                    "per_page": 100,
                    "page": page,
                }
                response = self.session.get(self.SEARCH_URL, params=params, timeout=30)
                response.raise_for_status()
                payload = response.json()
                snapshots.append(
                    Snapshot(
                        name=sanitize_filename(f"github_search_{language_bucket.lower()}_{page}"),
                        source_url=response.url,
                        body=json.dumps(payload),
                    )
                )
                items = payload.get("items", [])
                for item in items:
                    repository = self._normalize_repository(item, language_bucket)
                    if repository and repository.full_name not in repositories:
                        repositories[repository.full_name] = repository
                if len(items) < 100:
                    break
        return snapshots, sorted(repositories.values(), key=lambda repo: (repo.created_at, repo.full_name))

    def inspect_repositories(
        self,
        repositories: Iterable[GithubRepository],
        providers: Iterable[ProviderConfig],
        target_date: date,
    ) -> tuple[list[Snapshot], list[GithubSignalMatch]]:
        snapshots: list[Snapshot] = []
        matches: list[GithubSignalMatch] = []
        signal_date = target_date.isoformat()
        for repository in repositories:
            tree_snapshot, file_paths = self._fetch_tree(repository)
            if tree_snapshot is not None:
                snapshots.append(tree_snapshot)
            if not file_paths:
                continue

            candidate_paths = self._select_candidate_paths(file_paths)
            contents: dict[str, str] = {}
            for path in candidate_paths:
                snapshot, content = self._fetch_file(repository.full_name, path)
                if snapshot is not None:
                    snapshots.append(snapshot)
                if content is not None:
                    contents[path] = content
            matches.extend(self._detect_matches(repository, providers, contents, signal_date))
        return snapshots, matches

    def _normalize_repository(self, item: dict, language_bucket: str) -> GithubRepository | None:
        full_name = str(item.get("full_name") or "").strip()
        if not full_name or "/" not in full_name:
            return None
        if bool(item.get("fork")) or bool(item.get("archived")):
            return None
        owner, name = full_name.split("/", 1)
        return GithubRepository(
            full_name=full_name,
            owner=owner,
            name=name,
            html_url=str(item.get("html_url") or f"https://github.com/{full_name}"),
            created_at=str(item.get("created_at") or ""),
            created_date=str(item.get("created_at") or "")[:10],
            pushed_at=str(item.get("pushed_at") or ""),
            default_branch=str(item.get("default_branch") or "main"),
            language_bucket=language_bucket.lower(),
            is_fork=bool(item.get("fork")),
            is_archived=bool(item.get("archived")),
            stargazers_count=int(item.get("stargazers_count") or 0),
        )

    def _fetch_tree(self, repository: GithubRepository) -> tuple[Snapshot | None, list[str]]:
        url = f"{self.REPO_URL}/{repository.full_name}/git/trees/{repository.default_branch}"
        response = self.session.get(url, params={"recursive": 1}, timeout=30)
        if response.status_code >= 400:
            return None, []
        payload = response.json()
        snapshot = Snapshot(
            name=sanitize_filename(f"tree_{repository.full_name}"),
            source_url=response.url,
            body=json.dumps(payload),
        )
        if payload.get("truncated"):
            return snapshot, []
        paths = [str(node.get("path")) for node in payload.get("tree", []) if node.get("type") == "blob"]
        return snapshot, paths

    def _select_candidate_paths(self, file_paths: Iterable[str]) -> list[str]:
        exact_matches = [path for path in file_paths if path in self.EXACT_PATHS]
        code_matches = [
            path
            for path in file_paths
            if path.endswith(self.CODE_SUFFIXES)
            and (
                "/" not in path
                or path.startswith(("src/", "app/", "server/", "api/", "lib/", "packages/"))
            )
        ]
        selected = exact_matches + sorted(code_matches)[: self.max_code_files_per_repo]
        return list(dict.fromkeys(selected))

    def _fetch_file(self, full_name: str, path: str) -> tuple[Snapshot | None, str | None]:
        url = f"{self.REPO_URL}/{full_name}/contents/{path}"
        response = self.session.get(url, timeout=30)
        if response.status_code >= 400:
            return None, None
        payload = response.json()
        if not isinstance(payload, dict):
            logging.warning(
                "Skipping GitHub contents payload with unexpected shape repo=%s path=%s response_type=%s",
                full_name,
                path,
                type(payload).__name__,
            )
            snapshot = Snapshot(
                name=sanitize_filename(f"file_{full_name}_{path}"),
                source_url=response.url,
                body=json.dumps(
                    {
                        "path": path,
                        "response_type": type(payload).__name__,
                        "item_count": len(payload) if isinstance(payload, list) else None,
                    }
                ),
            )
            return snapshot, None
        snapshot = Snapshot(
            name=sanitize_filename(f"file_{full_name}_{path}"),
            source_url=response.url,
            body=json.dumps(
                {
                    "path": path,
                    "type": payload.get("type"),
                    "content": payload.get("content"),
                    "encoding": payload.get("encoding"),
                }
            ),
        )
        if payload.get("type") not in {None, "file"}:
            logging.warning(
                "Skipping non-file GitHub contents payload repo=%s path=%s type=%s",
                full_name,
                path,
                payload.get("type"),
            )
            return snapshot, None
        encoded = payload.get("content")
        if not encoded or payload.get("encoding") != "base64":
            logging.warning(
                "Skipping undecodable GitHub contents payload repo=%s path=%s encoding=%s",
                full_name,
                path,
                payload.get("encoding"),
            )
            return snapshot, None
        try:
            content = base64.b64decode(encoded).decode("utf-8", errors="ignore")
        except (ValueError, TypeError):
            return snapshot, None
        return snapshot, content

    def _detect_matches(
        self,
        repository: GithubRepository,
        providers: Iterable[ProviderConfig],
        contents: dict[str, str],
        signal_date: str,
    ) -> list[GithubSignalMatch]:
        found: dict[tuple[str, str], GithubSignalMatch] = {}
        for path, content in contents.items():
            lowered = content.lower()
            for provider in providers:
                if path in self.EXACT_PATHS:
                    self._maybe_add_match(
                        found,
                        repository,
                        provider.slug,
                        "manifest_dependency",
                        provider.manifest_patterns,
                        lowered,
                        path,
                        signal_date,
                    )
                self._maybe_add_match(
                    found,
                    repository,
                    provider.slug,
                    "code_import",
                    provider.import_patterns,
                    lowered,
                    path,
                    signal_date,
                )
                self._maybe_add_match(
                    found,
                    repository,
                    provider.slug,
                    "env_var",
                    provider.env_var_patterns,
                    lowered,
                    path,
                    signal_date,
                )
                self._maybe_add_match(
                    found,
                    repository,
                    provider.slug,
                    "model_name",
                    provider.model_patterns,
                    lowered,
                    path,
                    signal_date,
                )
        return list(found.values())

    def _maybe_add_match(
        self,
        found: dict[tuple[str, str], GithubSignalMatch],
        repository: GithubRepository,
        provider_slug: str,
        signal_type: str,
        patterns: Iterable[str],
        lowered_content: str,
        path: str,
        signal_date: str,
    ) -> None:
        key = (provider_slug, signal_type)
        if key in found:
            return
        for pattern in patterns:
            if pattern.lower() in lowered_content:
                found[key] = GithubSignalMatch(
                    provider=provider_slug,
                    signal_date=signal_date,
                    repo_full_name=repository.full_name,
                    signal_type=signal_type,
                    matched_file_path=path,
                    matched_pattern=pattern,
                    language_bucket=repository.language_bucket,
                    repo_created_at=repository.created_at,
                    repo_pushed_at=repository.pushed_at,
                    repo_default_branch=repository.default_branch,
                    is_fork=repository.is_fork,
                    is_archived=repository.is_archived,
                    stargazers_count=repository.stargazers_count,
                    source_url=repository.html_url,
                )
                return
