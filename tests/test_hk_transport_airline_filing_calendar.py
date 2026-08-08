from __future__ import annotations

from pathlib import Path

from hk_transport.sources.airline_filing_calendar import parse_filing_calendar_html


def test_parse_filing_calendar_keeps_schedule_distinct_from_actual_date() -> None:
    payload = '''<table>
      <tr><th>序号</th><th>首次预约时间</th><th>变更时间</th><th>实际披露时间</th></tr>
      <tr><td>1</td><td>2026-08-29</td><td>-</td><td>-</td></tr>
      <tr><td>2</td><td>2025-08-29</td><td>-</td><td>2025-08-29</td></tr>
    </table>'''.encode("gb18030")
    frame = parse_filing_calendar_html(
        payload,
        symbol="600029",
        company="China Southern Airlines",
        snapshot_date="2026-08-06",
        retrieved_at="2026-08-06T00:00:00+00:00",
    )

    row = frame.iloc[0]
    assert row["statement_period"] == "1H2026"
    assert row["first_scheduled_date"] == "2026-08-29"
    assert row["actual_disclosure_date"] is None
    assert row["calendar_status"] == "scheduled"
    assert row["source_quality"] == "public_discovery"


def test_current_local_filing_calendar_has_six_names() -> None:
    path = Path("data/normalized/hk_transport/airline_filing_calendar.csv")
    import pandas as pd

    assert path.exists()
    frame = pd.read_csv(path)
    assert len(frame) == 6
    assert frame["statement_period"].eq("1H2026").all()
    assert frame["first_scheduled_date"].notna().all()
    assert frame["actual_disclosure_date"].isna().all()
