from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_operating_freshness import build_airline_operating_freshness


def test_operating_freshness_distinguishes_found_and_query_scoped_absence() -> None:
    kpi = pd.DataFrame(
        [
            {"airline_code": "601111", "month": "2026-06", "metric": "ask", "value": 1},
            {"airline_code": "600029", "month": "2026-06", "metric": "ask", "value": 1},
        ]
    )
    registry = pd.DataFrame(
        [
            {
                "airline_code": "601111",
                "month": "2026-06",
                "announcement_date": "2026-07-15",
                "announcement_id": "june-id",
            }
        ]
    )
    result = build_airline_operating_freshness(
        kpi=kpi,
        registry=registry,
        announcements_by_company=[
            (
                "Air China",
                [
                    {
                        "announcementTitle": "中国国航2026年7月主要运营数据公告",
                        "announcementTime": int(pd.Timestamp("2026-08-15T10:00:00+08:00").timestamp() * 1000),
                        "announcementId": "july-id",
                        "adjunctUrl": "finalpage/2026-08-15/july.PDF",
                    }
                ],
            ),
            ("China Southern Airlines", []),
        ],
        snapshot_date="2026-08-20",
        retrieved_at="2026-08-20T00:00:00+00:00",
    )

    assert len(result) == 6
    air_china = result.loc[result["company"].eq("Air China")].iloc[0]
    assert air_china["target_release_status"] == "announcement_found"
    assert air_china["target_announcement_id"] == "july-id"
    assert air_china["target_source_pdf_url"].endswith("july.PDF")

    southern = result.loc[result["company"].eq("China Southern Airlines")].iloc[0]
    assert southern["target_release_status"] == "not_found_in_cninfo_window"
    assert "query-scoped absence" in southern["source_note"]


def test_operating_freshness_uses_prior_month_as_target() -> None:
    result = build_airline_operating_freshness(
        kpi=pd.DataFrame(),
        registry=pd.DataFrame(),
        announcements_by_company=[],
        snapshot_date="2026-08-07",
        retrieved_at="2026-08-07T00:00:00+00:00",
    )
    assert result["target_month"].eq("2026-07").all()
    assert result["target_window_start"].eq("2026-07-01").all()
    assert result["target_window_end"].eq("2026-08-07").all()
