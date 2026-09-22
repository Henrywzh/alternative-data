from __future__ import annotations

import pytest
from pathlib import Path

from common.free_data_artifacts import RawSnapshotRun
from factset_earnings_data.replay import latest_raw_run_id, replay_raw_run


def test_factset_replay_reuses_html_and_ocr_without_network(tmp_path: Path) -> None:
    raw_root = tmp_path / "data" / "raw" / "factset_earnings"
    run = RawSnapshotRun(raw_root, "20260917T000000Z-test", "factset_earnings")
    article_url = "https://insight.factset.com/q3-eps-estimates-increase"
    html = """
    <html><body>
      <h1>Analysts Increasing EPS Estimates for S&amp;P 500 Companies</h1>
      <div class="fs--blog--single--meta"><p>By John Butters | September 4, 2026</p></div>
      <div id="hs_cos_wrapper_post_body">
        <p>The Q3 bottom-up EPS estimate increased by 1.2% during the first two months of the quarter.</p>
        <p>The CY 2026 bottom-up EPS estimate increased by 6.1% during the same period.</p>
        <p>At the sector level, the Energy (+11.8%) sector led the increase.</p>
      </div>
    </body></html>
    """.encode()
    run.write_bytes(
        "articles/0001_q3-eps-estimates-increase.html",
        html,
        source_url=article_url,
        metadata={"article_url": article_url},
        gzip_payload=True,
    )
    run.write_bytes(
        "ocr/0001_panel.txt",
        b"48 have issued negative EPS guidance and 63 have issued positive EPS guidance",
        metadata={"article_url": article_url, "derived_from": "tesseract"},
    )
    run.finalize(status="ok", coverage={"relevant_articles": 1})

    result = replay_raw_run(tmp_path, "20260917T000000Z-test")

    assert result.stats["relevant_articles"] == 1
    assert len(result.observations) == 1
    assert result.observations[0].quarterly_eps_revision_pct == 1.2
    assert result.observations[0].positive_eps_guidance_count == 63.0
    assert result.catalog[0].ocr_image_count == 1
    assert result.catalog[0].extraction_status == "supported_observation"


def test_latest_raw_run_ignores_partial_article_fetches(tmp_path: Path) -> None:
    raw_root = tmp_path / "data" / "raw" / "factset_earnings"
    complete_boundary = RawSnapshotRun(raw_root, "20260917T000001Z-boundary", "factset_earnings")
    complete_boundary.write_bytes(
        "articles/0001_article.html",
        b"<html><body><h1>EPS estimates for S&amp;P 500</h1></body></html>",
        metadata={"article_url": "https://insight.factset.com/article"},
        gzip_payload=True,
    )
    complete_boundary.finalize(
        status="partial",
        errors={"topic_page_84": "HTTPError: 404 Client Error for https://insight.factset.com/topic/earnings/page/84"},
    )

    failed = RawSnapshotRun(raw_root, "20260917T000002Z-failed", "factset_earnings")
    failed.write_bytes(
        "articles/0001_article.html",
        b"<html><body><h1>EPS estimates for S&amp;P 500</h1></body></html>",
        metadata={"article_url": "https://insight.factset.com/article"},
        gzip_payload=True,
    )
    failed.finalize(status="partial", errors={"article_1": "ReadTimeout"})

    assert latest_raw_run_id(tmp_path) == "20260917T000001Z-boundary"
    with pytest.raises(ValueError, match="partial or invalid"):
        replay_raw_run(tmp_path, "20260917T000002Z-failed")
    replayed = replay_raw_run(tmp_path, "20260917T000002Z-failed", allow_partial=True)
    assert replayed.raw_run_id == "20260917T000002Z-failed"
