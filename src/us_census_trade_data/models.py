from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Snapshot:
    name: str
    source_url: str
    body: str
    metadata: dict[str, Any] = field(default_factory=dict)


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


@dataclass
class MonthlyImportPoint:
    dataset_id: str
    period: str
    reporter_country_code: str
    reporter_country_name: str
    partner_country_code: str
    partner_country_name: str
    hs_code: str
    item_name: str | None
    general_import_value_usd: float | None
    general_import_quantity: float | None
    general_import_quantity_unit: str | None
    general_import_quantity_2: float | None
    general_import_quantity_2_unit: str | None
    air_import_value_usd: float | None
    air_shipping_weight: float | None
    containerized_vessel_import_value_usd: float | None
    containerized_vessel_shipping_weight: float | None
    vessel_import_value_usd: float | None
    vessel_shipping_weight: float | None
    consumption_import_value_usd: float | None
    consumption_import_quantity: float | None
    consumption_import_quantity_unit: str | None
    consumption_import_quantity_2: float | None
    consumption_import_quantity_2_unit: str | None
    general_value_per_quantity_unit_usd: float | None
    last_update: str | None
    source_name: str
    source_url: str
    source_run_id: str
    scraped_at: str
    parser_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PortMonthlyImportPoint:
    dataset_id: str
    period: str
    reporter_country_code: str
    reporter_country_name: str
    partner_country_code: str
    partner_country_name: str
    hs_code: str
    item_name: str | None
    port_code: str
    port_name: str | None
    general_import_value_usd: float | None
    air_import_value_usd: float | None
    air_shipping_weight: float | None
    containerized_vessel_import_value_usd: float | None
    containerized_vessel_shipping_weight: float | None
    vessel_import_value_usd: float | None
    vessel_shipping_weight: float | None
    last_update: str | None
    source_name: str
    source_url: str
    source_run_id: str
    scraped_at: str
    parser_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    datasets_written: dict[str, int]
    raw_run_dir: str
    dataset_row_deltas: dict[str, int] = field(default_factory=dict)
