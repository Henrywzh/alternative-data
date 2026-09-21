from __future__ import annotations

from dataclasses import asdict, dataclass


FACTSET_BASE_NUMERIC_FIELDS = (
    "blended_earnings_growth_yoy",
    "blended_revenue_growth_yoy",
    "eps_beat_rate",
    "eps_surprise_pct",
    "revenue_beat_rate",
    "revenue_surprise_pct",
    "forward_12m_pe",
    "forward_12m_pe_10y_avg",
)

FACTSET_REVISION_NUMERIC_FIELDS = (
    "quarterly_eps_revision_pct",
    "annual_eps_revision_pct",
    "positive_eps_guidance_count",
    "negative_eps_guidance_count",
    "eps_guidance_total_count",
)

FACTSET_NUMERIC_FIELDS = FACTSET_BASE_NUMERIC_FIELDS + FACTSET_REVISION_NUMERIC_FIELDS
FACTSET_PAYLOAD_FIELDS = FACTSET_NUMERIC_FIELDS + ("sector_revision_json",)


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
    quarterly_eps_revision_pct: float | None = None
    annual_eps_revision_pct: float | None = None
    positive_eps_guidance_count: float | None = None
    negative_eps_guidance_count: float | None = None
    eps_guidance_total_count: float | None = None
    sector_revision_json: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FactsetArticleRecord:
    """Audit/catalog row for a relevant public FactSet Insight article."""

    article_url: str
    title: str
    report_date: str
    reference_quarter: str
    article_type: str
    raw_run_id: str
    ocr_image_count: int
    body_char_count: int
    supported_field_count: int
    extraction_status: str
    fetched_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
