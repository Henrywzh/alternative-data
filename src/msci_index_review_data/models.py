from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MsciReviewEvent:
    review_cycle: str
    announcement_date: str
    effective_date: str
    action: str
    index_name: str
    country: str
    ticker: str
    security_name: str
    size_segment: str
    sedol: str | None = None
    isin: str | None = None
    ric: str | None = None
    fetched_at: str = ""
    source_url: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
