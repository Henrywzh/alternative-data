from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class BisSeriesMeta:
    series_id: str
    country: str
    indicator: str
    title: str
    frequency: str
    units: str
    fetched_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BisObservation:
    period: str
    series_id: str
    country: str
    value: float | None
    release_date: str
    fetched_at: str
    # Set by the parser from BIS's own observation status; it was previously
    # declared here and written by nothing, so every row read False whether or
    # not the value was an estimate.
    is_projected: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
