from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class DatasetRecord:
    """One normalized Ramp row.

    A single record type spans both datasets (like vercel_ai_data): the
    monthly vendor time series and the category membership snapshot. Fields not
    relevant to a given dataset stay None and are dropped by the storage layer's
    per-dataset column projection.
    """

    dataset_id: str
    source_url: str
    source_run_id: str
    scraped_at: str

    # Identity (shared)
    vendor_slug: str | None = None
    vendor_name: str | None = None
    vendor_domain: str | None = None

    # Category membership snapshot (ramp_category_vendors)
    category_slug: str | None = None
    category_name: str | None = None

    # Monthly adoption time series (ramp_vendor_adoption_monthly)
    spend_month: str | None = None
    adoption_rate: float | None = None
    adoption_rate_yoy: float | None = None
    adoption_rank: int | None = None
    adoption_rank_mom: int | None = None
    adoption_rate_ent: float | None = None
    adoption_rate_mm: float | None = None
    adoption_rate_smb: float | None = None
    adoption_rate_growth_delta_mom: float | None = None
    adoption_rate_growth_rank_mom: int | None = None
    competitor_switch_rate: float | None = None
    new_adopter_share: float | None = None
    dominant_fte_segment: str | None = None
    dominant_fte_segment_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GenericRecord:
    """A config-driven record: fixed provenance columns + a free-form payload.

    Used by the AI Index and Jobs Impact sources, whose ~9 heterogeneous schemas
    would otherwise force a 60-field mega-dataclass. Storage projects ``to_dict``
    onto each dataset's configured columns, so extra payload keys are harmless.
    """

    dataset_id: str
    source_url: str
    source_run_id: str
    scraped_at: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "source_url": self.source_url,
            "source_run_id": self.source_run_id,
            "scraped_at": self.scraped_at,
            **self.payload,
        }


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
        return self.scraped_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
