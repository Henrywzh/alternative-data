from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SpPmiObservation:
    period: str
    region: str
    sector: str
    is_flash: bool
    headline_pmi: float | None
    new_orders_index: float | None
    output_index: float | None
    finished_goods_inventory_index: float | None
    input_prices_index: float | None
    output_prices_index: float | None
    employment_index: float | None
    orders_to_inventory_ratio: float | None
    price_pass_through_spread: float | None
    release_date: str
    fetched_at: str
    source_url: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
