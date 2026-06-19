from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class MineralMasterRecord:
    mineral_id: str
    mineral_name: str
    usgs_section_name: str
    category: str
    is_critical_mineral_2025: bool
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MineralApplicationRecord:
    mineral_id: str
    application_text: str
    source_year: int
    source_type: str
    source_section_name: str
    source_page_hint: str | None
    extraction_confidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MineralMetricRecord:
    mineral_id: str
    metric_name: str
    metric_value: float | str
    metric_unit: str | None
    metric_period: str
    metric_year: int
    comparison_year: int | None
    source_year: int
    source_type: str
    source_section_name: str
    source_page_hint: str | None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
