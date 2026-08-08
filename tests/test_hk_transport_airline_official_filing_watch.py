from __future__ import annotations

from pathlib import Path

import pandas as pd

from hk_transport.sources.airline_official_filing_watch import (
    merge_official_filing_watch_history,
    normalize_official_filing_watch,
)


def test_normalize_official_filing_watch_prefers_full_report_and_normalizes_time() -> None:
    announcement_time = int(pd.Timestamp("2026-08-29T10:00:00+08:00").timestamp() * 1000)
    frame = normalize_official_filing_watch(
        [
            (
                "600029",
                "China Southern Airlines",
                [
                    {
                        "announcementId": "abstract-id",
                        "announcementTitle": "南方航空2026年半年度报告摘要",
                        "announcementTime": announcement_time,
                        "adjunctUrl": "finalpage/2026-08-29/abstract.PDF",
                    },
                    {
                        "announcementId": "full-id",
                        "announcementTitle": "南方航空2026年半年度报告",
                        "announcementTime": announcement_time,
                        "adjunctUrl": "finalpage/2026-08-29/full.PDF",
                    },
                ],
            )
        ],
        snapshot_date="2026-08-30",
        scheduled_dates={"600029": "2026-08-29"},
        retrieved_at="2026-08-30T00:00:00+00:00",
    )

    row = frame.iloc[0]
    assert bool(row["official_report_found"]) is True
    assert row["announcement_id"] == "full-id"
    assert row["official_disclosure_date"] == "2026-08-29"
    assert row["scheduled_date"] == "2026-08-29"
    assert row["report_pdf_url"] == "https://static.cninfo.com.cn/finalpage/2026-08-29/full.PDF"
    assert "Asia/Shanghai" not in row["official_disclosure_datetime"]


def test_normalize_official_filing_watch_keeps_query_scoped_no_match_semantics() -> None:
    frame = normalize_official_filing_watch(
        [("601111", "Air China", [{"announcementTitle": "中国国航2025年年度报告"}])],
        snapshot_date="2026-08-07",
        scheduled_dates={"601111": "2026-08-31"},
        retrieved_at="2026-08-07T00:00:00+00:00",
    )

    row = frame.iloc[0]
    assert bool(row["official_report_found"]) is False
    assert pd.isna(row["official_disclosure_date"])
    assert "query-scoped absence" in row["source_note"]
    assert row["scheduled_date"] == "2026-08-31"


def test_official_filing_watch_history_replaces_only_same_company_snapshot() -> None:
    prior = pd.DataFrame(
        [
            {
                "ticker": "01055.HK / 600029.SH",
                "snapshot_date": "2026-08-07",
                "company": "China Southern Airlines",
                "statement_period": "1H2026",
                "official_report_found": False,
            }
        ]
    )
    current = prior.copy()
    current.loc[0, "official_report_found"] = True
    current.loc[0, "announcement_id"] = "new-id"
    result = merge_official_filing_watch_history(prior, current)
    assert len(result) == 1
    assert bool(result.iloc[0]["official_report_found"]) is True
    assert result.iloc[0]["announcement_id"] == "new-id"


def test_current_official_filing_watch_has_six_scheduled_names() -> None:
    path = Path("data/normalized/hk_transport/airline_official_filing_watch.csv")
    frame = pd.read_csv(path)
    assert len(frame) == 6
    assert frame["statement_period"].eq("1H2026").all()
    assert frame["scheduled_date"].notna().all()
    assert frame["official_report_found"].eq(False).all()
    assert frame["source_quality"].eq("cninfo_official_query").all()
