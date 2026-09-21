from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from factset_earnings_data.client import FactsetEarningsClient
from factset_earnings_data.models import FactsetEarningsObservation
from factset_earnings_data.storage import FactsetEarningsStorage


def _fs_obs(
    report_date: str,
    ref_q: str,
    eps_growth: float,
    fwd_pe: float,
    fetched_at: str,
    source_url: str | None = None,
) -> FactsetEarningsObservation:
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
        source_url=source_url,
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


def test_factset_surprise_parser_preserves_below_direction() -> None:
    text = (
        "Companies are reporting earnings that are 3.2% below estimates. "
        "Companies are reporting revenues that are 1.1% below estimates."
    )
    obs = FactsetEarningsClient.parse_summary_metrics(text, "2026-08-07", "2026Q2")
    assert obs.eps_surprise_pct == -3.2
    assert obs.revenue_surprise_pct == -1.1


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


def test_factset_parser_extracts_revision_guidance_and_sector_payload() -> None:
    text = """
    The Q3 bottom-up EPS estimate (which is an aggregation of median estimates)
    increased by 1.2% (to $89.69 from $88.64) from June 30 to August 31.
    At the sector level, the Energy (+11.8%) sector led while the Materials
    (-9.1%) sector declined. Of these companies, 48 have issued negative EPS
    guidance and 63 have issued positive EPS guidance.
    The CY 2026 bottom-up EPS estimate increased by 6.1%.
    """
    obs = FactsetEarningsClient.parse_summary_metrics(text, "2026-09-04", "2026Q3", fetched_at="capture")
    assert obs.quarterly_eps_revision_pct == 1.2
    assert obs.annual_eps_revision_pct == 6.1
    assert obs.positive_eps_guidance_count == 63.0
    assert obs.negative_eps_guidance_count == 48.0
    assert obs.eps_guidance_total_count == 111.0
    assert json.loads(obs.sector_revision_json or "{}") == {"Energy": 11.8, "Materials": -9.1}


def test_factset_parser_signed_revision_and_legacy_dates() -> None:
    obs = FactsetEarningsClient.parse_summary_metrics(
        "The Q1 bottom-up EPS estimate fell by 9.6% during the quarter.",
        "2016-04-01",
        "2016Q1",
    )
    assert obs.quarterly_eps_revision_pct == -9.6
    assert FactsetEarningsClient.report_date_from_url(
        "https://insight.factset.com/2015/06/earningsinsight-6-19-15"
    ) == "2015-06-19"


def test_factset_metadata_prefers_publication_stamp_over_historical_body_date() -> None:
    html = """
    <html><body>
      <h1>S&amp;P 500 Forward P/E Ratio Rises Above 20.0</h1>
      <div class="fs--blog--single--meta"><p>By John Butters | April 17, 2020</p></div>
      <div id="hs_cos_wrapper_post_body">
        <p>The forward 12-month P/E ratio was 20.4.</p>
        <p>This was the first time above 20.0 since April 10, 2002.</p>
        <p>Additional context keeps this article body above the source wrapper threshold for extraction.</p>
      </div>
    </body></html>
    """
    metadata = FactsetEarningsClient.extract_article_metadata(html)
    assert metadata["report_date"] == "2020-04-17"


def test_factset_storage_migrates_old_schema_and_removes_empty_topic_rows(tmp_path: Path) -> None:
    storage = FactsetEarningsStorage(tmp_path)
    legacy = pd.DataFrame(
        [
            {
                "report_date": "2026-09-04",
                "reference_quarter": "2026Q3",
                "blended_earnings_growth_yoy": 12.0,
                "source_url": "https://insight.factset.com/good-article",
                "fetched_at": "t",
            },
            {
                "report_date": "2026-09-05",
                "reference_quarter": "2026Q3",
                "source_url": "https://insight.factset.com/topic/earnings/page/2",
                "fetched_at": "t",
            },
        ]
    )
    legacy.to_parquet(storage.normalized_root / "factset_sp500_earnings_regime.parquet", index=False)

    loaded = storage.load_observations()
    assert len(loaded) == 1
    assert loaded.iloc[0]["source_url"] == "https://insight.factset.com/good-article"
    assert "quarterly_eps_revision_pct" in loaded.columns


def test_factset_storage_requires_reference_quarter(tmp_path: Path) -> None:
    storage = FactsetEarningsStorage(tmp_path)
    storage.upsert_observations(
        [
            _fs_obs("2026-09-04", "", 12.0, 21.0, "t1", "https://insight.factset.com/no-quarter"),
            _fs_obs("2026-09-04", "2026Q3", 12.0, 21.0, "t1", "https://insight.factset.com/with-quarter"),
        ]
    )
    loaded = storage.load_observations()
    assert list(loaded["source_url"]) == ["https://insight.factset.com/with-quarter"]


def test_factset_article_catalog_upsert_dedupes_by_article_url(tmp_path: Path) -> None:
    from factset_earnings_data.models import FactsetArticleRecord

    storage = FactsetEarningsStorage(tmp_path)
    first = FactsetArticleRecord(
        article_url="https://insight.factset.com/article",
        title="Old title",
        report_date="2026-09-01",
        reference_quarter="2026Q3",
        article_type="revision",
        raw_run_id="r1",
        ocr_image_count=0,
        body_char_count=100,
        supported_field_count=0,
        extraction_status="no_supported_metrics",
        fetched_at="t1",
    )
    second = FactsetArticleRecord(
        article_url=first.article_url,
        title="New title",
        report_date=first.report_date,
        reference_quarter=first.reference_quarter,
        article_type=first.article_type,
        raw_run_id="r2",
        ocr_image_count=1,
        body_char_count=200,
        supported_field_count=2,
        extraction_status="supported_observation",
        fetched_at="t2",
    )
    catalog = storage.upsert_article_catalog([first, second])
    assert len(catalog) == 1
    assert catalog.iloc[0]["title"] == "New title"
    assert catalog.iloc[0]["supported_field_count"] == 2


def test_factset_storage_keeps_distinct_article_observations_on_same_date(tmp_path: Path) -> None:
    storage = FactsetEarningsStorage(tmp_path)
    records = [
        _fs_obs(
            "2026-09-04",
            "2026Q3",
            10.0,
            20.0,
            "t1",
            "https://insight.factset.com/first-article",
        ),
        FactsetEarningsObservation(
            report_date="2026-09-04",
            reference_quarter="2026Q3",
            blended_earnings_growth_yoy=None,
            blended_revenue_growth_yoy=None,
            eps_beat_rate=None,
            eps_surprise_pct=None,
            revenue_beat_rate=None,
            revenue_surprise_pct=None,
            forward_12m_pe=None,
            forward_12m_pe_10y_avg=None,
            revision_breadth_score=None,
            sector_growth_json=None,
            fetched_at="t1",
            source_url="https://insight.factset.com/second-article",
            quarterly_eps_revision_pct=1.2,
        ),
    ]
    merged = storage.upsert_observations(records)

    assert len(merged) == 2
    assert set(merged["source_url"]) == {
        "https://insight.factset.com/first-article",
        "https://insight.factset.com/second-article",
    }


def test_factset_storage_replacement_drops_rows_absent_from_replay(tmp_path: Path) -> None:
    storage = FactsetEarningsStorage(tmp_path)
    old = _fs_obs(
        "2026-08-28",
        "2026Q3",
        9.0,
        20.0,
        "old",
        "https://insight.factset.com/old-article",
    )
    current = _fs_obs(
        "2026-09-04",
        "2026Q3",
        10.0,
        21.0,
        "current",
        "https://insight.factset.com/current-article",
    )
    storage.upsert_observations([old, current])

    replaced = storage.replace_observations([current])

    assert list(replaced["source_url"]) == ["https://insight.factset.com/current-article"]
