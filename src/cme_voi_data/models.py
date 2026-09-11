from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CmeObservation:
    trade_date: str
    product_code: str
    contract_month: str
    settle_price: float | None
    price_change: float | None
    volume: int | None
    open_interest: int | None
    open_interest_change: int | None
    flow_regime: str
    fetched_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
