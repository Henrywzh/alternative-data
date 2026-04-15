from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
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
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Source-internal point types (typed intermediates, not stored directly)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdataRawPoint:
    month: str           # "YYYY-MM"
    url: str
    fetch_time: str      # ISO8601
    title: str
    raw_text: str
    raw_html_path: str   # relative path from repo root; filled by pipeline after saving


@dataclass(frozen=True)
class AdataImagePoint:
    month: str
    page_url: str
    image_url: str
    local_path: str      # relative path from repo root; filled by pipeline after download
    image_type: str      # inferred from filename segment (e.g. "nand", "dram_price")
    vision_extracted: bool = False
    vision_result_json: str | None = None
    extracted_at: str | None = None


@dataclass(frozen=True)
class AdataMonthlyPoint:
    month: str
    title: str
    narrative_nand_supply: str
    narrative_nand_price: str
    narrative_dram_supply: str
    narrative_dram_price: str
    mentions_hbm: bool
    mentions_csp: bool
    mentions_server: bool
    mentions_ddr4: bool
    mentions_reallocate_capacity: bool
    mentions_shortage: bool
    mentions_oversupply: bool
    nand_regime_label: str    # "shortage" | "oversupply" | "balanced"
    dram_regime_label: str
    source_url: str


@dataclass(frozen=True)
class FredPoint:
    date: str        # "YYYY-MM-DD"
    series_id: str
    series_name: str
    value: float


# ---------------------------------------------------------------------------
# Unified DatasetRecord — all 5 tables share this class
# ---------------------------------------------------------------------------

@dataclass
class DatasetRecord:
    dataset_id: str
    source_url: str
    source_run_id: str
    scraped_at: str

    # adata_marketwatch_raw
    month: str | None = None
    fetch_time: str | None = None
    title: str | None = None
    raw_text: str | None = None
    raw_html_path: str | None = None

    # adata_marketwatch_images
    page_url: str | None = None
    image_url: str | None = None
    local_path: str | None = None
    image_type: str | None = None
    vision_extracted: bool | None = None
    vision_result_json: str | None = None
    extracted_at: str | None = None

    # adata_marketwatch_monthly
    narrative_nand_supply: str | None = None
    narrative_nand_price: str | None = None
    narrative_dram_supply: str | None = None
    narrative_dram_price: str | None = None
    mentions_hbm: bool | None = None
    mentions_csp: bool | None = None
    mentions_server: bool | None = None
    mentions_ddr4: bool | None = None
    mentions_reallocate_capacity: bool | None = None
    mentions_shortage: bool | None = None
    mentions_oversupply: bool | None = None
    nand_regime_label: str | None = None
    dram_regime_label: str | None = None

    # fred_semiconductor_ppi
    date: str | None = None
    series_id: str | None = None
    series_name: str | None = None
    value: float | None = None

    # semiconductor_memory_regime_monthly (derived)
    fred_ppi_value: float | None = None
    fred_ppi_mom_pct: float | None = None
    fred_ppi_3m_trend: float | None = None
    adata_freshness_days: float | None = None
    fred_release_lag_days: float | None = None
    data_completeness: str | None = None  # "full"|"adata_only"|"fred_only"|"empty"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    datasets_written: dict[str, int]
    raw_run_dir: str
    dataset_row_deltas: dict[str, int] = field(default_factory=dict)
