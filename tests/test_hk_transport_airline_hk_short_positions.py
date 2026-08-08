from __future__ import annotations

from pathlib import Path

import pandas as pd

from hk_transport.sources.airline_hk_short_positions import (
    parse_sfc_csv,
    parse_sfc_csv_links,
)


def test_parse_sfc_csv_links_respects_pit_window() -> None:
    html = """
    <a href="/x/Short_Position_Reporting_Aggregated_Data_20260814.csv">future</a>
    <a href="/x/Short_Position_Reporting_Aggregated_Data_20260731.csv">latest</a>
    <a href="/x/Short_Position_Reporting_Aggregated_Data_20260102.csv">start</a>
    <a href="/x/Short_Position_Reporting_Aggregated_Data_20251231.csv">old</a>
    """
    result = parse_sfc_csv_links(
        html,
        cutoff_date="2026-08-07",
        start_date="2026-01-01",
    )
    assert result == [
        ("2026-01-02", "https://hksfc.org/x/Short_Position_Reporting_Aggregated_Data_20260102.csv"),
        ("2026-07-31", "https://hksfc.org/x/Short_Position_Reporting_Aggregated_Data_20260731.csv"),
    ]


def test_parse_sfc_csv_keeps_reportable_position_separate_from_borrow() -> None:
    content = (
        "Date,Stock Code,Stock Name,Aggregated Reportable Short Positions (Shares),"
        "Aggregated Reportable Short Positions (HK$)\n"
        "31/07/2026,293,CATHAY PAC AIR,1234567,89012345\n"
        "31/07/2026,753,AIR CHINA,2345678,90123456\n"
        "31/07/2026,66,OTHER,999,111\n"
    ).encode("utf-8")
    result = parse_sfc_csv(
        content,
        source_url="https://hksfc.org/example.csv",
        snapshot_date="2026-08-07",
        retrieved_at="2026-08-07T00:00:00+00:00",
    )
    assert len(result) == 2
    cathay = result.loc[result["ticker"].eq("0293.HK")].iloc[0]
    assert cathay["reporting_date"] == "2026-07-31"
    assert cathay["short_position_shares"] == 1234567
    assert cathay["short_position_value_hkd"] == 89012345
    assert bool(cathay["borrow_data_available"]) is False


def test_current_sfc_short_position_history_covers_four_hk_airlines() -> None:
    frame = pd.read_csv(Path("data/normalized/hk_transport/airline_hk_short_positions.csv"))
    assert len(frame) >= 4
    assert frame["company"].nunique() == 4
    assert frame["reporting_date"].notna().all()
    assert frame["short_position_shares"].ge(0).all()
    assert frame["short_position_value_hkd"].ge(0).all()
    assert frame["borrow_data_available"].eq(False).all()
