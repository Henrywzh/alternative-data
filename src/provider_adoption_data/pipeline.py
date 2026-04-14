from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pandas as pd

from provider_adoption_data.models import (
    DatasetRecord,
    GithubSignalMatch,
    PipelineResult,
    RunContext,
    Snapshot,
    coerce_target_date,
)
from provider_adoption_data.sources.config import get_provider_registry
from provider_adoption_data.sources.github import GithubSource
from provider_adoption_data.sources.npm import NpmDownloadsSource
from provider_adoption_data.sources.pypi import PypiStatsSource
from provider_adoption_data.storage import StorageManager


DATASET_IDS = (
    "pypi_downloads_daily",
    "npm_downloads_daily",
    "github_repo_candidates_daily",
    "github_provider_signals_daily",
    "github_repo_rollup_daily",
    "provider_momentum_daily",
)


@dataclass(frozen=True)
class BackfillResult:
    run_id: str
    datasets_written: dict[str, int]
    raw_run_dir: str


class ProviderAdoptionPipeline:
    def __init__(
        self,
        base_dir: Path,
        *,
        pypi_source: PypiStatsSource | None = None,
        npm_source: NpmDownloadsSource | None = None,
        github_source: GithubSource | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.storage = StorageManager(base_dir)
        self.pypi_source = pypi_source or PypiStatsSource()
        self.npm_source = npm_source or NpmDownloadsSource()
        self.github_source = github_source or GithubSource()
        self.score_weights = {"github": 0.6, "pypi": 0.4}

    def run_pypi_daily_update(self, *, target_date: str | date | None = None, provider_slugs: list[str] | None = None) -> PipelineResult:
        providers = get_provider_registry(provider_slugs)
        context = self._create_context()
        snapshots = self.pypi_source.fetch_snapshots(providers)
        manifest = self._build_manifest("pypi-daily-update", context, target_date=coerce_target_date(target_date), providers=providers)
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)
        points = self.pypi_source.extract(snapshots, providers)

        records = [
            DatasetRecord(
                dataset_id="pypi_downloads_daily",
                source_url=point.source_url,
                source_run_id=context.run_id,
                scraped_at=context.scraped_at_iso,
                provider=point.provider,
                provider_display_name=point.provider_display_name,
                package_name=point.package_name,
                package_type=point.package_type,
                with_mirrors=point.with_mirrors,
                download_date=point.download_date,
                downloads=point.downloads,
            )
            for point in points
        ]
        existing = self.storage.load_dataset("pypi_downloads_daily")
        written = self.storage.upsert_dataset("pypi_downloads_daily", records)
        deltas = {"pypi_downloads_daily": max(len(written) - len(existing), 0)}
        return PipelineResult(context.run_id, {"pypi_downloads_daily": len(written)}, str(raw_run_dir), deltas)

    def run_npm_daily_update(self, *, target_date: str | date | None = None, provider_slugs: list[str] | None = None) -> PipelineResult:
        providers = get_provider_registry(provider_slugs)
        resolved_date = coerce_target_date(target_date)
        context = self._create_context()
        start_date = self._resolve_npm_start_date(resolved_date, providers)
        snapshots = self.npm_source.fetch_snapshots(providers, start_date, resolved_date)
        manifest = self._build_manifest(
            "npm-daily-update",
            context,
            target_date=resolved_date,
            providers=providers,
            range_start_date=start_date,
        )
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)
        points = self.npm_source.extract(snapshots, providers)

        records = [
            DatasetRecord(
                dataset_id="npm_downloads_daily",
                source_url=point.source_url,
                source_run_id=context.run_id,
                scraped_at=context.scraped_at_iso,
                provider=point.provider,
                provider_display_name=point.provider_display_name,
                package_name=point.package_name,
                package_type=point.package_type,
                package_category=point.package_category,
                download_date=point.download_date,
                downloads=point.downloads,
            )
            for point in points
        ]
        existing = self.storage.load_dataset("npm_downloads_daily")
        written = self.storage.upsert_dataset("npm_downloads_daily", records)
        deltas = {"npm_downloads_daily": max(len(written) - len(existing), 0)}
        return PipelineResult(context.run_id, {"npm_downloads_daily": len(written)}, str(raw_run_dir), deltas)

    def run_github_daily_update(self, *, target_date: str | date | None = None, provider_slugs: list[str] | None = None) -> PipelineResult:
        providers = get_provider_registry(provider_slugs)
        resolved_date = coerce_target_date(target_date)
        context = self._create_context()
        search_snapshots, repositories = self.github_source.fetch_snapshots(resolved_date)
        inspect_snapshots, matches = self.github_source.inspect_repositories(repositories, providers, resolved_date)
        snapshots = search_snapshots + inspect_snapshots
        manifest = self._build_manifest("github-daily-update", context, target_date=resolved_date, providers=providers)
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)

        candidate_records = self._build_candidate_records(context, providers, repositories)
        signal_records = self._build_signal_records(context, matches)
        rollup_records = self._build_rollup_records(context, providers, repositories, matches, resolved_date.isoformat())

        existing_candidates = self.storage.load_dataset("github_repo_candidates_daily")
        existing_signals = self.storage.load_dataset("github_provider_signals_daily")
        existing_rollups = self.storage.load_dataset("github_repo_rollup_daily")
        written_candidates = self.storage.upsert_dataset("github_repo_candidates_daily", candidate_records)
        written_signals = self.storage.upsert_dataset("github_provider_signals_daily", signal_records)
        written_rollups = self.storage.upsert_dataset("github_repo_rollup_daily", rollup_records)
        written = {
            "github_repo_candidates_daily": len(written_candidates),
            "github_provider_signals_daily": len(written_signals),
            "github_repo_rollup_daily": len(written_rollups),
        }
        deltas = {
            "github_repo_candidates_daily": max(len(written_candidates) - len(existing_candidates), 0),
            "github_provider_signals_daily": max(len(written_signals) - len(existing_signals), 0),
            "github_repo_rollup_daily": max(len(written_rollups) - len(existing_rollups), 0),
        }
        return PipelineResult(context.run_id, written, str(raw_run_dir), deltas)

    def run_derived_daily_update(self, *, target_date: str | date | None = None, provider_slugs: list[str] | None = None) -> PipelineResult:
        providers = get_provider_registry(provider_slugs)
        resolved_date = coerce_target_date(target_date)
        context = self._create_context()
        raw_run_dir = self.storage.write_raw_run(
            context.run_id,
            [
                Snapshot(
                    name="derived_context",
                    source_url="derived://provider_momentum_daily",
                    body=json.dumps({"target_date": resolved_date.isoformat(), "providers": [provider.slug for provider in providers]}),
                )
            ],
            self._build_manifest("derived-daily-update", context, target_date=resolved_date, providers=providers),
        )
        records = self._build_momentum_records(context, providers, resolved_date)
        existing = self.storage.load_dataset("provider_momentum_daily")
        written = self.storage.upsert_dataset("provider_momentum_daily", records)
        deltas = {"provider_momentum_daily": max(len(written) - len(existing), 0)}
        return PipelineResult(context.run_id, {"provider_momentum_daily": len(written)}, str(raw_run_dir), deltas)

    def run_backfill(
        self,
        *,
        start_date: str | date,
        end_date: str | date,
        provider_slugs: list[str] | None = None,
    ) -> BackfillResult:
        providers = get_provider_registry(provider_slugs)
        start = coerce_target_date(start_date)
        end = coerce_target_date(end_date)
        if end < start:
            raise ValueError("end_date must be greater than or equal to start_date")

        pypi_result = self.run_pypi_daily_update(target_date=end, provider_slugs=[provider.slug for provider in providers])
        npm_result = self.run_npm_daily_update(target_date=end, provider_slugs=[provider.slug for provider in providers])
        totals = dict(pypi_result.datasets_written)
        totals.update(npm_result.datasets_written)
        current = start
        last_raw_run_dir = npm_result.raw_run_dir
        while current <= end:
            github_result = self.run_github_daily_update(target_date=current, provider_slugs=[provider.slug for provider in providers])
            derived_result = self.run_derived_daily_update(target_date=current, provider_slugs=[provider.slug for provider in providers])
            for result in (github_result, derived_result):
                for dataset_id, rows in result.datasets_written.items():
                    totals[dataset_id] = rows
                last_raw_run_dir = result.raw_run_dir
            current += timedelta(days=1)
        return BackfillResult(run_id=pypi_result.run_id, datasets_written=totals, raw_run_dir=last_raw_run_dir)

    def validate(self, *, provider_slugs: list[str] | None = None) -> dict[str, int]:
        providers = get_provider_registry(provider_slugs)
        return {
            "providers": len(providers),
            "pypi_packages": sum(len(provider.pypi_packages) for provider in providers),
            "npm_packages": sum(len(provider.npm_packages) for provider in providers),
            "github_languages": len(self.github_source.SEARCH_LANGUAGE_BUCKETS),
        }

    def _create_context(self) -> RunContext:
        return RunContext(
            run_id=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8],
            scraped_at=datetime.now(UTC),
        )

    def _build_manifest(
        self,
        mode: str,
        context: RunContext,
        *,
        target_date: date,
        providers,
        range_start_date: date | None = None,
    ) -> dict:
        manifest = {
            "run_id": context.run_id,
            "mode": mode,
            "scraped_at": context.scraped_at_iso,
            "target_date": target_date.isoformat(),
            "providers": [provider.slug for provider in providers],
            "datasets": list(DATASET_IDS),
            "parser_version": "0.1.0",
        }
        if range_start_date is not None:
            manifest["range_start_date"] = range_start_date.isoformat()
        return manifest

    def _build_candidate_records(self, context: RunContext, providers, repositories) -> list[DatasetRecord]:
        records: list[DatasetRecord] = []
        for provider in providers:
            for repository in repositories:
                records.append(
                    DatasetRecord(
                        dataset_id="github_repo_candidates_daily",
                        source_url=repository.html_url,
                        source_run_id=context.run_id,
                        scraped_at=context.scraped_at_iso,
                        provider=provider.slug,
                        provider_display_name=provider.display_name,
                        repo_full_name=repository.full_name,
                        repo_owner=repository.owner,
                        repo_name=repository.name,
                        repo_html_url=repository.html_url,
                        repo_created_date=repository.created_date,
                        repo_created_at=repository.created_at,
                        repo_pushed_at=repository.pushed_at,
                        repo_default_branch=repository.default_branch,
                        language_bucket=repository.language_bucket,
                        is_fork=repository.is_fork,
                        is_archived=repository.is_archived,
                        stargazers_count=repository.stargazers_count,
                    )
                )
        return records

    def _build_signal_records(self, context: RunContext, matches: list[GithubSignalMatch]) -> list[DatasetRecord]:
        records: list[DatasetRecord] = []
        for match in matches:
            owner, name = match.repo_full_name.split("/", 1)
            records.append(
                DatasetRecord(
                    dataset_id="github_provider_signals_daily",
                    source_url=match.source_url,
                    source_run_id=context.run_id,
                    scraped_at=context.scraped_at_iso,
                    provider=match.provider,
                    repo_full_name=match.repo_full_name,
                    repo_owner=owner,
                    repo_name=name,
                    repo_html_url=match.source_url,
                    repo_created_date=match.repo_created_at[:10],
                    repo_created_at=match.repo_created_at,
                    repo_pushed_at=match.repo_pushed_at,
                    repo_default_branch=match.repo_default_branch,
                    language_bucket=match.language_bucket,
                    signal_date=match.signal_date,
                    signal_type=match.signal_type,
                    matched_file_path=match.matched_file_path,
                    matched_pattern=match.matched_pattern,
                    is_fork=match.is_fork,
                    is_archived=match.is_archived,
                    stargazers_count=match.stargazers_count,
                )
            )
        return records

    def _build_rollup_records(
        self,
        context: RunContext,
        providers,
        repositories,
        matches: list[GithubSignalMatch],
        signal_date: str,
    ) -> list[DatasetRecord]:
        grouped: dict[tuple[str, str], list[GithubSignalMatch]] = {}
        for match in matches:
            grouped.setdefault((match.provider, match.repo_full_name), []).append(match)

        records: list[DatasetRecord] = []
        by_repo = {repository.full_name: repository for repository in repositories}
        for provider in providers:
            for repository in repositories:
                signal_matches = grouped.get((provider.slug, repository.full_name), [])
                signal_types = {match.signal_type for match in signal_matches}
                records.append(
                    DatasetRecord(
                        dataset_id="github_repo_rollup_daily",
                        source_url=repository.html_url,
                        source_run_id=context.run_id,
                        scraped_at=context.scraped_at_iso,
                        provider=provider.slug,
                        provider_display_name=provider.display_name,
                        repo_full_name=repository.full_name,
                        repo_owner=repository.owner,
                        repo_name=repository.name,
                        repo_html_url=repository.html_url,
                        repo_created_date=repository.created_date,
                        repo_created_at=repository.created_at,
                        repo_pushed_at=repository.pushed_at,
                        repo_default_branch=repository.default_branch,
                        language_bucket=repository.language_bucket,
                        signal_date=signal_date,
                        is_fork=repository.is_fork,
                        is_archived=repository.is_archived,
                        stargazers_count=repository.stargazers_count,
                        has_manifest_dependency="manifest_dependency" in signal_types,
                        has_code_import="code_import" in signal_types,
                        has_env_var="env_var" in signal_types,
                        has_model_name="model_name" in signal_types,
                        matched_signal_count=len(signal_types),
                    )
                )
        return records

    def _resolve_npm_start_date(self, target_date: date, providers) -> date:
        pypi = self.storage.load_dataset("pypi_downloads_daily")
        if not pypi.empty:
            provider_slugs = [provider.slug for provider in providers]
            filtered = pypi[pypi["provider"].isin(provider_slugs)].copy()
            filtered["download_date"] = filtered["download_date"].astype("string")
            date_values = filtered["download_date"].dropna().astype(str)
            if not date_values.empty:
                return date.fromisoformat(min(date_values))
        return target_date - timedelta(days=180)

    def _build_momentum_records(self, context: RunContext, providers, target_date: date) -> list[DatasetRecord]:
        pypi = self.storage.load_dataset("pypi_downloads_daily")
        github = self.storage.load_dataset("github_repo_rollup_daily")
        records: list[DatasetRecord] = []

        provider_slugs = [provider.slug for provider in providers]
        provider_display = {provider.slug: provider.display_name for provider in providers}

        if not pypi.empty:
            pypi = pypi[pypi["provider"].isin(provider_slugs)].copy()
            pypi["download_date"] = pypi["download_date"].astype("string")
            pypi = pypi[pypi["with_mirrors"] == False]
        if not github.empty:
            github = github[github["provider"].isin(provider_slugs)].copy()
            github["signal_date"] = github["signal_date"].astype("string")

        target_str = target_date.isoformat()
        github_day = github[github["signal_date"] == target_str].copy() if not github.empty else pd.DataFrame()
        pypi_grouped = (
            pypi.groupby(["provider", "download_date"], dropna=False)["downloads"].sum().reset_index()
            if not pypi.empty
            else pd.DataFrame(columns=["provider", "download_date", "downloads"])
        )

        pypi_totals = {}
        if not pypi_grouped.empty:
            for provider in provider_slugs:
                provider_df = (
                    pypi_grouped[pypi_grouped["provider"] == provider]
                    .sort_values("download_date")
                    .set_index("download_date")
                )
                if target_str not in provider_df.index:
                    continue
                current_position = provider_df.index.tolist().index(target_str)
                current_downloads = provider_df["downloads"]
                trailing_7 = current_downloads.iloc[max(0, current_position - 6) : current_position + 1]
                trailing_28 = current_downloads.iloc[max(0, current_position - 27) : current_position + 1]
                previous_28 = current_downloads.iloc[max(0, current_position - 55) : max(0, current_position - 27)]
                pypi_totals[provider] = {
                    "pypi_7d_avg": float(trailing_7.mean()) if not trailing_7.empty else 0.0,
                    "pypi_28d_avg": float(trailing_28.mean()) if not trailing_28.empty else 0.0,
                    "pypi_28d_sum": float(trailing_28.sum()) if not trailing_28.empty else 0.0,
                    "previous_28d_sum": float(previous_28.sum()) if not previous_28.empty else 0.0,
                }

        total_pypi_28d = sum(value["pypi_28d_sum"] for value in pypi_totals.values()) or 0.0
        total_github_new = float(len(github_day["repo_full_name"].dropna().unique().tolist())) if not github_day.empty else 0.0

        for provider in provider_slugs:
            github_provider = github_day[github_day["provider"] == provider].copy() if not github_day.empty else pd.DataFrame()
            github_new_repo_count = float(len(github_provider["repo_full_name"].dropna().unique().tolist())) if not github_provider.empty else 0.0
            github_import_repo_count = (
                float(github_provider[github_provider["has_code_import"] == True]["repo_full_name"].nunique())
                if not github_provider.empty
                else 0.0
            )
            github_env_repo_count = (
                float(github_provider[github_provider["has_env_var"] == True]["repo_full_name"].nunique())
                if not github_provider.empty
                else 0.0
            )
            github_model_repo_count = (
                float(github_provider[github_provider["has_model_name"] == True]["repo_full_name"].nunique())
                if not github_provider.empty
                else 0.0
            )
            github_repo_share = github_new_repo_count / total_github_new if total_github_new else 0.0

            pypi_stats = pypi_totals.get(
                provider,
                {
                    "pypi_7d_avg": 0.0,
                    "pypi_28d_avg": 0.0,
                    "pypi_28d_sum": 0.0,
                    "previous_28d_sum": 0.0,
                },
            )
            pypi_share_28d = pypi_stats["pypi_28d_sum"] / total_pypi_28d if total_pypi_28d else 0.0
            previous_sum = pypi_stats["previous_28d_sum"]
            if previous_sum:
                pypi_growth_28d = (pypi_stats["pypi_28d_sum"] - previous_sum) / previous_sum
            else:
                pypi_growth_28d = 0.0

            github_block = (
                0.4 * github_repo_share
                + 0.3 * (github_import_repo_count / github_new_repo_count if github_new_repo_count else 0.0)
                + 0.15 * (github_env_repo_count / github_new_repo_count if github_new_repo_count else 0.0)
                + 0.15 * (github_model_repo_count / github_new_repo_count if github_new_repo_count else 0.0)
            )
            pypi_block = 0.6 * pypi_share_28d + 0.4 * max(pypi_growth_28d, 0.0)
            momentum_score = self.score_weights["github"] * github_block + self.score_weights["pypi"] * pypi_block

            records.append(
                DatasetRecord(
                    dataset_id="provider_momentum_daily",
                    source_url="derived://provider_momentum_daily",
                    source_run_id=context.run_id,
                    scraped_at=context.scraped_at_iso,
                    provider=provider,
                    provider_display_name=provider_display.get(provider),
                    signal_date=target_str,
                    pypi_7d_avg=pypi_stats["pypi_7d_avg"],
                    pypi_28d_avg=pypi_stats["pypi_28d_avg"],
                    pypi_share_28d=pypi_share_28d,
                    pypi_growth_28d=pypi_growth_28d,
                    github_new_repo_count=github_new_repo_count,
                    github_repo_share=github_repo_share,
                    github_import_repo_count=github_import_repo_count,
                    github_env_repo_count=github_env_repo_count,
                    github_model_repo_count=github_model_repo_count,
                    momentum_score=momentum_score,
                )
            )
        return records
