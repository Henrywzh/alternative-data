from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class PriceSourceRecord:
    normalized_mineral_id: str
    mineral_name: str
    trackability_grade: str
    price_source_type: str
    price_symbol_or_series_id: str | None
    price_currency: str | None
    price_unit: str | None
    publish_lag_assumption_days: int
    is_active_for_v1: bool
    proxy_target: str | None = None
    proxy_type: str | None = None
    proxy_instrument: str | None = None
    proxy_display_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineResult:
    outputs: dict[str, str]
    diagnostics: dict[str, int | float | str]
