import pandas as pd

from src.hk_real_estate.sources.hse28 import parse_28hse_new_projects_html
from src.hk_real_estate.shkp_28hse_reconciliation import (
    build_shkp_28hse_reconciliation,
    build_shkp_ownership_review_priority,
)


def test_parse_28hse_new_projects_keeps_unit_states_and_status_separate():
    html = """
    <div class="content">
      <a class="header" href="https://www.28hse.com/new-properties/test">TEST PHASE</a>
      <div class="meta">TAI PO<span class="separation"></span>1 TEST ROAD</div>
      <div class="description">
        <div class="ui grid"><div class="middle aligned row">
          <div class="column width_28p">開售中</div>
          <div class="column width_18p"><div class="ui mini statistic"><div class="value">1,000</div><div class="label">總伙數</div></div></div>
          <div class="column width_18p"><div class="ui mini statistic"><div class="value">700</div><div class="label">餘貨</div></div></div>
          <div class="column width_18p"><div class="ui mini statistic"><div class="value">100</div><div class="label">在售</div></div></div>
          <div class="column width_18p"><div class="ui mini statistic"><div class="value">300</div><div class="label">已售</div></div></div>
        </div></div>
      </div>
      <div class="extra"><label class="ui label">2028年入伙</label></div>
    </div>
    """
    frame = parse_28hse_new_projects_html(html)
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["project_url"].endswith("/test")
    assert row["status"] == "開售中"
    assert row["estimated_total_units"] == 1000
    assert row["remaining_units"] == 700
    assert row["on_sale_units"] == 100
    assert row["sold_units"] == 300
    assert row["estimated_move_in_year"] == 2028


def test_shkp_28hse_reconciliation_keeps_one_sided_coverage_explicit():
    hse = pd.DataFrame([
        {
            "project_name": "PORTAL PHASE",
            "status": "開售中",
            "estimated_total_units": 100,
            "remaining_units": 40,
            "sold_units": 60,
        }
    ])
    candidates = pd.DataFrame([
        {
            "srpe_development_id": "1234",
            "development_name_en": "OTHER DEVELOPMENT",
            "phase_name_en": "PHASE 1",
            "candidate_status": "ambiguous",
        }
    ])
    recon, summary = build_shkp_28hse_reconciliation(hse, candidates)
    assert len(recon) == 2
    assert set(recon["match_status"]) == {
        "not_matched_current_28hse_listing",
        "srpe_phase_not_in_current_28hse_listing",
    }
    assert summary.loc[0, "exact_unique_matches"] == 0
    assert summary.loc[0, "unit_comparable_rows"] == 0
    assert all(recon["status_comparison"] == "not_comparable")


def test_shkp_ownership_priority_is_review_order_only():
    queue = pd.DataFrame([
        {
            "srpe_development_id": "1234",
            "review_priority": "P0",
            "evidence_count": 2,
            "ownership_attribution_ready": False,
        },
        {
            "srpe_development_id": "5678",
            "review_priority": "P1",
            "evidence_count": 5,
            "ownership_attribution_ready": False,
        },
    ])
    priority = build_shkp_ownership_review_priority(queue)
    assert priority.iloc[0]["srpe_development_id"] == "1234"
    assert set(priority["ownership_review_status"]) == {"blocked_interval_missing"}
    assert list(priority["review_queue_rank"]) == [1, 2]
