from __future__ import annotations

from pathlib import Path

from factset_earnings_data.client import FactsetEarningsClient
from factset_earnings_data.models import FactsetEarningsObservation
from factset_earnings_data.storage import FactsetEarningsStorage


def _fs_obs(report_date: str, ref_q: str, eps_growth: float, fwd_pe: float, fetched_at: str) -> FactsetEarningsObservation:
    return FactsetEarningsObservation(
        report_date=report_date,
        reference_quarter=ref_q,
        blended_earnings_growth_yoy=eps_growth,
        blended_revenue_growth_yoy=5.2,
        eps_beat_rate=78.0,
        eps_surprise_pct=4.3,
        revenue_beat_rate=60.0,
        revenue_surprise_pct=1.2,
        forward_12m_pe=fwd_pe,
        forward_12m_pe_10y_avg=18.5,
        revision_breadth_score=0.62,
        sector_growth_json=None,
        fetched_at=fetched_at,
    )


def test_factset_upsert_observations_dedupes(tmp_path: Path) -> None:
    storage = FactsetEarningsStorage(tmp_path)
    storage.upsert_observations([
        _fs_obs("2026-08-07", "2026Q2", 10.5, 21.2, "t1"),
        _fs_obs("2026-08-14", "2026Q2", 10.8, 21.4, "t1"),
    ])
    merged = storage.upsert_observations([
        _fs_obs("2026-08-07", "2026Q2", 10.6, 21.2, "t2"),
        _fs_obs("2026-08-21", "2026Q2", 11.1, 21.5, "t2"),
    ])
    assert len(merged) == 3
    rec_0807 = merged[merged["report_date"] == "2026-08-07"]
    assert len(rec_0807) == 1
    assert rec_0807.iloc[0]["blended_earnings_growth_yoy"] == 10.6


def test_factset_regex_parsing() -> None:
    sample_text = """
    For Q2 2026, the blended earnings growth rate of 11.5% is higher than last week.
    The blended revenue growth rate of 5.4% is reported.
    79.0% of S&P 500 companies have reported actual EPS above EPS estimates.
    In aggregate, companies are reporting earnings are reporting 4.5% above estimates.
    The forward 12-month P/E ratio is 21.3, which is above the 10-year average (18.5).
    """
    obs = FactsetEarningsClient.parse_summary_metrics(sample_text, "2026-08-28", "2026Q2")
    assert obs.blended_earnings_growth_yoy == 11.5
    assert obs.blended_revenue_growth_yoy == 5.4
    assert obs.eps_beat_rate == 79.0
    assert obs.eps_surprise_pct == 4.5
    assert obs.forward_12m_pe == 21.3
    assert obs.forward_12m_pe_10y_avg == 18.5


def test_factset_forward_pe_does_not_capture_sp500_constituent_count() -> None:
    text = "On November 7, the forward 12-month P/E ratio for the S&P 500 was 22.2."
    obs = FactsetEarningsClient.parse_summary_metrics(text, "2024-11-11", "2024Q3")
    assert obs.forward_12m_pe == 22.2
    assert FactsetEarningsClient.infer_reference_quarter(text, "", "2024-11-11") == "2024Q3"

    declining = "The forward 12-month P/E ratio for the S&P 500 declined to 19.5 from 21.3."
    assert FactsetEarningsClient.parse_summary_metrics(declining, "2022-04-01", "2022Q1").forward_12m_pe == 19.5

    weekly = "86% of companies beat estimates versus the 10-year average of 76%. The forward 12-month P/E ratio is 20.0, above the 10-year average (19.0)."
    assert FactsetEarningsClient.parse_summary_metrics(weekly, "2026-08-07", "2026Q2").forward_12m_pe_10y_avg == 19.0


def test_factset_metadata_ignores_related_article_footer() -> None:
    html = """
    <html><body>
      <h1>S&amp;P 500 CY 2024 Earnings Preview</h1>
      <div id="hs_cos_wrapper_post_body">
        <p>For Q1 2024 through Q3 2024, analysts are projecting earnings growth.</p>
        <p>For Q4 2024, analysts are projecting earnings growth of 18.2%.</p>
      </div>
      <footer><a href="/earnings-insight-infographic-q2-2026-by-the-numbers">Q2 2026</a></footer>
    </body></html>
    """
    metadata = FactsetEarningsClient.extract_article_metadata(html)
    assert FactsetEarningsClient.infer_reference_quarter(metadata["text"], metadata["title"]) == "2024Q4"


def test_factset_reference_quarter_uses_publication_season() -> None:
    text = "The Q2 2025 earnings season is progressing; forecasts include Q2 2026."
    assert FactsetEarningsClient.infer_reference_quarter(text, "", "2025-08-29") == "2025Q2"
