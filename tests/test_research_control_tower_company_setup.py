"""Deterministic tests for company setup labels and official change cards."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research_control_tower.company_setup import (
    build_official_change_cards,
    classify_company_setup,
    official_fact_line,
)


def _bars_from_closes(closes: list[float], start: str = "2026-01-02") -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=len(closes))
    return pd.DataFrame(
        {
            "bar_date": dates,
            "close": closes,
            "adj_close": closes,
        }
    )


def test_setup_unavailable_without_enough_history() -> None:
    bars = _bars_from_closes([100.0, 101.0, 102.0])
    setup = classify_company_setup(bars, now_utc=pd.Timestamp("2026-01-10", tz="UTC"))
    assert setup.state == "unavailable"
    assert "25 daily closes" in setup.reason


def test_setup_extended_when_rsi_and_ma_stretch() -> None:
    closes = [100.0] * 40 + list(np.linspace(100.0, 140.0, 20))
    bars = _bars_from_closes(closes)
    setup = classify_company_setup(bars, now_utc=pd.Timestamp("2026-04-01", tz="UTC"))
    assert setup.state == "extended"
    assert setup.rsi is not None and setup.rsi >= 70
    assert setup.ma20_pct is not None and setup.ma20_pct >= 5
    assert "buy" not in setup.reason.lower()
    assert "sell" not in setup.reason.lower()


def test_setup_washout_when_drawdown_and_low_rsi() -> None:
    closes = list(np.linspace(80.0, 120.0, 40)) + list(np.linspace(120.0, 80.0, 25))
    bars = _bars_from_closes(closes)
    setup = classify_company_setup(bars, now_utc=pd.Timestamp("2026-04-01", tz="UTC"))
    assert setup.state == "washout"
    assert setup.drawdown_60d is not None and setup.drawdown_60d <= -12


def test_event_window_overlays_technicals() -> None:
    closes = [100.0 + i * 0.1 for i in range(60)]
    bars = _bars_from_closes(closes)
    events = pd.DataFrame(
        {
            "title": ["Q2 2026 results"],
            "starts_at": [pd.Timestamp("2026-04-08T00:00:00Z")],
        }
    )
    setup = classify_company_setup(
        bars,
        events=events,
        now_utc=pd.Timestamp("2026-04-01T00:00:00Z"),
    )
    assert setup.state == "event_window"
    assert setup.event_window is True
    assert "Q2 2026 results" in setup.next_event_title
    assert setup.rsi is not None


def test_buyback_fact_line_is_official_only() -> None:
    line = official_fact_line(
        {
            "action_type": "buyback_execution",
            "shares_affected": 667_000,
            "total_amount_paid": 300_279_998.3,
            "currency": "HKD",
            "filing_date": "2026-08-21",
            "headline": "Next Day Disclosure Return",
        }
    )
    assert line.startswith("2026-08-21 · Buyback 667,000 shares")
    assert "HKD 300.3m" in line
    assert "thesis" not in line.lower()


def test_change_cards_put_results_before_routine_buybacks() -> None:
    filings = pd.DataFrame(
        [
            {
                "headline": "ANNOUNCEMENT OF THE RESULTS FOR THE THREE AND SIX MONTHS ENDED 30 JUNE 2026",
                "event_class": "earnings_results",
                "published_at": "2026-08-12T08:31:00Z",
                "source_url": "https://example.test/results",
            },
            {
                "headline": "Next Day Disclosure Return - Changes in issued shares and share buybacks",
                "event_class": "share_buyback",
                "published_at": "2026-08-21T09:55:00Z",
                "source_url": "https://example.test/buyback",
                "shares_affected": 667000,
                "total_amount_paid": 300279998.3,
                "currency": "HKD",
            },
        ]
    )
    cards = build_official_change_cards(filings=filings, limit=8)
    assert [card.bucket for card in cards] == ["priority", "routine"]
    assert cards[0].needs_review is True
    assert cards[1].needs_review is False
    assert "Buyback" in cards[1].fact
