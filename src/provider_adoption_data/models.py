from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any


@dataclass(frozen=True)
class Snapshot:
    name: str
    source_url: str
    body: str


@dataclass(frozen=True)
class RunContext:
    run_id: str
    scraped_at: datetime

    @property
    def scraped_at_iso(self) -> str:
        value = self.scraped_at
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ProviderPackageConfig:
    package_name: str
    package_type: str


@dataclass(frozen=True)
class ProviderConfig:
    slug: str
    display_name: str
    enabled: bool
    pypi_packages: tuple[ProviderPackageConfig, ...]
    npm_packages: tuple[ProviderPackageConfig, ...]
    manifest_patterns: tuple[str, ...]
    import_patterns: tuple[str, ...]
    env_var_patterns: tuple[str, ...]
    model_patterns: tuple[str, ...]


@dataclass(frozen=True)
class GithubRepository:
    full_name: str
    owner: str
    name: str
    html_url: str
    created_at: str
    created_date: str
    pushed_at: str
    default_branch: str
    language_bucket: str
    is_fork: bool
    is_archived: bool
    stargazers_count: int


@dataclass(frozen=True)
class GithubSignalMatch:
    provider: str
    signal_date: str
    repo_full_name: str
    signal_type: str
    matched_file_path: str | None
    matched_pattern: str | None
    language_bucket: str
    repo_created_at: str
    repo_pushed_at: str
    repo_default_branch: str
    is_fork: bool
    is_archived: bool
    stargazers_count: int
    source_url: str


@dataclass(frozen=True)
class PypiDownloadPoint:
    provider: str
    provider_display_name: str
    package_name: str
    package_type: str
    with_mirrors: bool
    download_date: str
    downloads: int
    source_url: str


@dataclass(frozen=True)
class NpmDownloadPoint:
    provider: str
    provider_display_name: str
    package_name: str
    package_type: str
    download_date: str
    downloads: int
    source_url: str


@dataclass
class DatasetRecord:
    dataset_id: str
    source_url: str
    source_run_id: str
    scraped_at: str

    provider: str | None = None
    provider_display_name: str | None = None
    package_name: str | None = None
    package_type: str | None = None
    with_mirrors: bool | None = None
    download_date: str | None = None
    downloads: float | None = None

    repo_full_name: str | None = None
    repo_owner: str | None = None
    repo_name: str | None = None
    repo_html_url: str | None = None
    repo_created_date: str | None = None
    repo_created_at: str | None = None
    repo_pushed_at: str | None = None
    repo_default_branch: str | None = None
    language_bucket: str | None = None
    signal_date: str | None = None
    signal_type: str | None = None
    matched_file_path: str | None = None
    matched_pattern: str | None = None
    is_fork: bool | None = None
    is_archived: bool | None = None
    stargazers_count: float | None = None

    has_manifest_dependency: bool | None = None
    has_code_import: bool | None = None
    has_env_var: bool | None = None
    has_model_name: bool | None = None
    matched_signal_count: float | None = None

    pypi_7d_avg: float | None = None
    pypi_28d_avg: float | None = None
    pypi_share_28d: float | None = None
    pypi_growth_28d: float | None = None
    github_new_repo_count: float | None = None
    github_repo_share: float | None = None
    github_import_repo_count: float | None = None
    github_env_repo_count: float | None = None
    github_model_repo_count: float | None = None
    momentum_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    datasets_written: dict[str, int]
    raw_run_dir: str
    dataset_row_deltas: dict[str, int] = field(default_factory=dict)


def coerce_target_date(value: str | date | None) -> date:
    if value is None:
        return datetime.now(UTC).date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)
