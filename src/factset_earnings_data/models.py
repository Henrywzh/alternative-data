from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FactsetEarningsObservation:
    report_date: str
    reference_quarter: str
    blended_earnings_growth_yoy: float | None
    blended_revenue_growth_yoy: float | None
    eps_beat_rate: float | None
    eps_surprise_pct: float | None
    revenue_beat_rate: float | None
    revenue_surprise_pct: float | None
    forward_12m_pe: float | None
    forward_12m_pe_10y_avg: float | None
    revision_breadth_score: float | None
    sector_growth_json: str | None
    fetched_at: str
    source_url: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
