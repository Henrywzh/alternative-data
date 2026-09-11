from __future__ import annotations

from pathlib import Path

from msci_index_review_data.models import MsciReviewEvent
from msci_index_review_data.storage import MsciIndexReviewStorage


def _msci_evt(cycle: str, ann: str, eff: str, action: str, idx: str, tkr: str, name: str, fetched_at: str) -> MsciReviewEvent:
    return MsciReviewEvent(
        review_cycle=cycle,
        announcement_date=ann,
        effective_date=eff,
        action=action,
        index_name=idx,
        country="CN",
        ticker=tkr,
        security_name=name,
        size_segment="STANDARD",
        fetched_at=fetched_at,
    )


def test_msci_upsert_events_dedupes(tmp_path: Path) -> None:
    storage = MsciIndexReviewStorage(tmp_path)
    storage.upsert_events([
        _msci_evt("2026-08-QIR", "2026-08-12", "2026-08-31", "ADD", "MSCI_CHINA_A", "600000.SH", "SPD Bank", "t1"),
        _msci_evt("2026-08-QIR", "2026-08-12", "2026-08-31", "DELETE", "MSCI_CHINA_A", "000001.SZ", "Ping An Bank", "t1"),
    ])
    merged = storage.upsert_events([
        _msci_evt("2026-08-QIR", "2026-08-12", "2026-08-31", "ADD", "MSCI_CHINA_A", "600000.SH", "SPD Bank Updated", "t2"),
        _msci_evt("2026-11-SAIR", "2026-11-10", "2026-11-30", "ADD", "MSCI_CHINA_A", "600519.SH", "Moutai", "t2"),
    ])
    assert len(merged) == 3
    spd = merged[(merged["review_cycle"] == "2026-08-QIR") & (merged["ticker"] == "600000.SH")]
    assert len(spd) == 1
    assert spd.iloc[0]["security_name"] == "SPD Bank Updated"
