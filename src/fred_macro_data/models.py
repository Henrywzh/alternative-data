from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class FredSeriesMeta:
    """Metadata for a single FRED series."""
    series_id: str
    title: str
    frequency: str
    units: str
    seasonal_adjustment: str
    observation_start: str
    last_updated: str
    fetched_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass
class FredObservation:
    """A single (date, value) observation for a FRED series."""
    date: str
    series_id: str
    value: float
    fetched_at: str
    realtime_start: str = "1776-07-04"
    realtime_end: str = "9999-12-31"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
