from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EiaGridHourlyObservation:
    timestamp_utc: str
    respondent: str
    fuel_type: str
    generation_mwh: float | None
    fetched_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
