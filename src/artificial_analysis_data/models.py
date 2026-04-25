from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
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
        return self.scraped_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @property
    def as_of_date(self) -> str:
        return self.scraped_at.astimezone(timezone.utc).date().isoformat()


@dataclass(frozen=True)
class ArtificialAnalysisModelPoint:
    as_of_date: str
    model_id: str
    model_slug: str | None
    model_name: str
    creator_id: str | None
    creator_name: str | None
    creator_slug: str | None
    creator_country: str | None
    release_date: str | None
    release_quarter: str | None
    intelligence_index: float | None
    coding_index: float | None
    math_index: float | None
    gpqa: float | None
    scicode: float | None
    price_1m_blended_3_to_1: float | None
    price_1m_input_tokens: float | None
    price_1m_output_tokens: float | None
    median_output_tokens_per_second: float | None
    median_time_to_first_token_seconds: float | None
    context_window_tokens: int | None
    total_parameters_billions: float | None
    active_parameters_billions: float | None
    training_tokens_trillions: float | None
    open_source_categorization: str | None
    license_name: str | None
    is_open_weights: bool | None
    source_url: str
    source_run_id: str
    scraped_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LeadingModelByLabPoint:
    as_of_date: str
    creator_id: str | None
    creator_name: str | None
    creator_slug: str | None
    creator_country: str | None
    model_id: str
    model_slug: str | None
    model_name: str
    release_date: str | None
    intelligence_index: float | None
    source_run_id: str
    scraped_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContextWindowQuarterPoint:
    as_of_date: str
    release_quarter: str
    context_window_median_proprietary: float | None
    context_window_median_open_source_total: float | None
    proprietary_model_count: int
    open_source_model_count: int
    source_run_id: str
    scraped_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapexQuarterPoint:
    quarter_id: str
    quarter_label: str
    microsoft: float | None
    google: float | None
    meta: float | None
    amazon: float | None
    oracle: float | None
    apple: float | None
    page_url: str
    bundle_url: str
    source_run_id: str
    scraped_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    datasets_written: dict[str, int]
    raw_run_dir: str
    dataset_row_deltas: dict[str, int] = field(default_factory=dict)


def coerce_date_string(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    candidates = ("%Y-%m-%d", "%Y-%m", "%b %Y", "%B %Y", "%Y")
    for fmt in candidates:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt == "%Y":
            return date(parsed.year, 1, 1).isoformat()
        if fmt == "%Y-%m":
            return date(parsed.year, parsed.month, 1).isoformat()
        if fmt in {"%b %Y", "%B %Y"}:
            return date(parsed.year, parsed.month, 1).isoformat()
        return parsed.date().isoformat()
    return None


def quarter_label_for_date(value: str | None) -> str | None:
    normalized = coerce_date_string(value)
    if normalized is None:
        return None
    parsed = date.fromisoformat(normalized)
    quarter = ((parsed.month - 1) // 3) + 1
    return f"Q{quarter}-{parsed.year}"


def parse_quarter_sort_key(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"Q([1-4])-(\d{4})", value)
    if not match:
        return (9999, 9)
    return (int(match.group(2)), int(match.group(1)))
