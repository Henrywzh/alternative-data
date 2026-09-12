from __future__ import annotations

from dataclasses import asdict, dataclass


# Which kind of publisher a row came from. The HIBOR history fallback is a
# third-party mirror (cdn.jin10.com), and it lands under the same HKMA_HIBOR_*
# series as the official API. Without an explicit tier the only distinguishing
# mark was source_url, and the dedupe key (series_id, date) let whichever ran
# last win -- so aggregator data could silently overwrite an official reading.
OFFICIAL_API = "official_api"
OFFICIAL_DOCUMENT = "official_document"
AGGREGATOR = "aggregator"

# Lower sorts first, and the dedupe keeps the best-ranked row per (series, date).
SOURCE_TIER_RANK = {OFFICIAL_API: 0, OFFICIAL_DOCUMENT: 1, AGGREGATOR: 2}


@dataclass(frozen=True)
class HkmaSeriesMeta:
    series_id: str
    title: str
    category: str
    frequency: str
    units: str
    fetched_at: str
    source_tier: str = OFFICIAL_API

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class HkmaObservation:
    date: str
    series_id: str
    value: float | None
    fetched_at: str
    source_url: str | None = None
    source_tier: str = OFFICIAL_API

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
