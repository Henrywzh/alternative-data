from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class OfrMnemonic:
    """Represents a data series mnemonic and its metadata from the OFR API."""
    mnemonic: str
    name: str
    notes: str
    frequency: str
    start_date: str
    last_update: str
    fetched_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass
class OfrDataPoint:
    """Represents a single time series data point (date, value) for a mnemonic."""
    date: str
    mnemonic: str
    value: float
    fetched_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
