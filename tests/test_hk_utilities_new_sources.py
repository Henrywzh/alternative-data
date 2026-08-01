"""Focused parser tests for the CSDI-catalogued HK utilities additions."""

from __future__ import annotations

import pandas as pd

from src.hk_utilities.sources.dsd_sewage_flow_lab import parse_dsd_sewage_flow_lab_csv
from src.hk_utilities.sources.wsd_water_suspension import parse_wsd_water_suspension_csv


def test_parse_dsd_sewage_flow_lab_utf16_tab_csv() -> None:
    header = [
        "Sampling Date",
        "Sewage Treatment Works",
        "Daily Flow (CuM/d)",
        "BOD_SYMBOL",
        "BOD (mgO2/L)",
        "TSS_SYMBOL",
        "TSS (mg/L)",
        "NH3-N_SYMBOL",
        "NH3-N (mg/L)",
        "NOx-N_SYMBOL",
        "NOx-N (mg/L)",
        "OG_SYMBOL",
        "OG (mg/L)",
        "TN_SYMBOL",
        "TN (mg/L)",
        "pH",
        "E.coli (cfu/100ml)",
    ]
    rows = [
        ["2026/06/30", "Shatin STW", "293170", "", "5", "", "20", "", "", "", "", "", "", "", "", "", "96"],
        ["2026/06/30", "Tai Po STW", "133652", "<", "5", "", "9", "", "", "", "", "", "", "", "", "", "82"],
    ]
    payload = ("\t".join(header) + "\n" + "\n".join("\t".join(row) for row in rows)).encode("utf-16")

    frame = parse_dsd_sewage_flow_lab_csv(payload)

    assert list(frame["plant"]) == ["Shatin STW", "Tai Po STW"]
    assert frame["date"].tolist() == [pd.Timestamp("2026-06-30"), pd.Timestamp("2026-06-30")]
    assert frame.loc[0, "daily_flow_cum_d"] == 293170
    assert frame.loc[1, "e_coli_cfu_100ml"] == 82
    assert frame.loc[1, "bod_symbol"] == "<"
    assert not frame.duplicated(["date", "plant"]).any()


def test_parse_wsd_water_suspension_repairs_known_missing_separator() -> None:
    header = "|".join(
        [
            "SUSPENSION_ID",
            "WATER_TYPE_DESCRIPTION",
            "WATER_TYPE_DESCRIPTION_ZHT",
            "DISTRICT_ENG",
            "DISTRICT_ZHT",
            "NATURE_DESCRIPTION",
            "NATURE_DESCRIPTION_ZHT",
            "SUSPENSION_DATE_TIME",
            "ACTUAL_RESUMPTION_DATE_TIME",
            "LONG_ADDRESS",
            "LONG_ADDRESS_ZHT",
            "CAUSE",
            "CAUSE_ZHT",
            "STATUS",
            "STATUS_ZHT",
        ]
    )
    correct = "|".join(
        [
            "2026073111456",
            "Fresh Water",
            "食水",
            "Wan Chai",
            "灣仔區",
            "Emergency",
            "緊急停水",
            "31-07-2026 21:22",
            "01-08-2026 00:35",
            "68 Sing Woo Road",
            "成和道68號",
            "Emergency repairing of water main/installation",
            "緊急維修水管工程",
            "Supply resumed",
            "供水已恢復",
        ]
    )
    malformed = "|".join(
        [
            "2026072811317",
            "Fresh Water",
            "食水",
            "Sham Shui Po",
            "深水埗區Planned",
            "計劃停水",
            "30-07-2026 09:30",
            "30-07-2026 17:28",
            "Tai Hang Tung Estate",
            "大坑東邨",
            "Improvement work of water main/installation",
            "水管改善工程",
            "Supply resumed",
            "供水已恢復",
        ]
    )
    malformed_cause = "|".join(
        [
            "2026073111439",
            "Salt Water",
            "鹹水",
            "Tai Po",
            "大埔區",
            "Emergency",
            "緊急停水",
            "31-07-2026 11:00",
            "31-07-2026 21:03",
            "HA WONG YI AU TSUEN",
            "下黃宜坳村Emergency repairing of water main/installation",
            "緊急維修水管工程",
            "Supply resumed",
            "供水已恢復",
        ]
    )
    payload = (header + "\n" + correct + "\n" + malformed + "\n" + malformed_cause).encode("big5", errors="replace")

    frame = parse_wsd_water_suspension_csv(payload)

    assert len(frame) == 3
    assert frame["suspension_id"].is_unique
    assert set(frame["nature"]) == {"Emergency", "Planned"}
    assert frame["suspension_start"].notna().all()
    assert frame["actual_resumption"].notna().all()
    assert frame["is_active"].eq(False).all()
    assert frame.loc[frame["suspension_id"] == "2026072811317", "district"].item() == "Sham Shui Po"
    assert frame.loc[frame["suspension_id"] == "2026073111439", "cause"].item() == "Emergency repairing of water main/installation"
