"""Free Yahoo Finance revenue-estimate discovery layer for airline shares."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


REVENUE_ESTIMATE_UNIVERSE: tuple[dict[str, str], ...] = (
    {"ticker": "0293.HK", "source_ticker": "0293.HK", "company": "Cathay Pacific", "market": "HK", "currency": "HKD"},
    {"ticker": "0753.HK", "source_ticker": "0753.HK", "company": "Air China", "market": "HK", "currency": "RMB"},
    {"ticker": "01055.HK", "source_ticker": "1055.HK", "company": "China Southern Airlines", "market": "HK", "currency": "RMB"},
    {"ticker": "0670.HK", "source_ticker": "0670.HK", "company": "China Eastern Airlines", "market": "HK", "currency": "RMB"},
    {"ticker": "601021.SH", "source_ticker": "601021.SS", "company": "Spring Airlines", "market": "CN_A", "currency": "RMB"},
    {"ticker": "603885.SH", "source_ticker": "603885.SS", "company": "Juneyao Airlines", "market": "CN_A", "currency": "RMB"},
    {"ticker": "600221.SH", "source_ticker": "600221.SS", "company": "Hainan Airlines Holdings", "market": "CN_A", "currency": "RMB"},
    {"ticker": "601111.SH", "source_ticker": "601111.SS", "company": "Air China", "market": "CN_A", "currency": "RMB"},
    {"ticker": "600029.SH", "source_ticker": "600029.SS", "company": "China Southern Airlines", "market": "CN_A", "currency": "RMB"},
    {"ticker": "600115.SH", "source_ticker": "600115.SS", "company": "China Eastern Airlines", "market": "CN_A", "currency": "RMB"},
)

REVENUE_CONSENSUS_COLUMNS = [
    "dataset_id", "ticker", "company", "market", "source_ticker", "snapshot_date",
    "forecast_period", "fiscal_year", "revenue_avg_native_mn", "revenue_low_native_mn",
    "revenue_high_native_mn", "native_currency", "analyst_count",
    "year_ago_revenue_native_mn", "growth_pct", "source_quality",
    "revision_history_available", "source_url", "source_note", "retrieved_at",
]


def normalize_revenue_estimate_frame(
    frame: pd.DataFrame,
    *,
    ticker: str,
    source_ticker: str,
    company: str,
    market: str,
    currency: str,
    snapshot_date: str,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Normalize yfinance's ``revenue_estimate`` period-indexed frame."""
    required = {"avg", "low", "high", "numberOfAnalysts", "yearAgoRevenue", "growth"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"revenue estimate is missing columns: {sorted(missing)}")
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for period, year_offset in (("0y", 0), ("+1y", 1)):
        if period not in frame.index:
            continue
        source_row = frame.loc[period]
        average = pd.to_numeric(source_row.get("avg"), errors="coerce")
        if pd.isna(average) or float(average) <= 0:
            continue
        def million(value: Any) -> float | None:
            parsed = pd.to_numeric(value, errors="coerce")
            return None if pd.isna(parsed) else float(parsed) / 1_000_000.0

        rows.append({
            "dataset_id": "airline_revenue_consensus_yfinance",
            "ticker": ticker,
            "company": company,
            "market": market,
            "source_ticker": source_ticker,
            "snapshot_date": snapshot_date,
            "forecast_period": period,
            "fiscal_year": int(snapshot_date[:4]) + year_offset,
            "revenue_avg_native_mn": million(source_row.get("avg")),
            "revenue_low_native_mn": million(source_row.get("low")),
            "revenue_high_native_mn": million(source_row.get("high")),
            "native_currency": currency,
            "analyst_count": pd.to_numeric(source_row.get("numberOfAnalysts"), errors="coerce"),
            "year_ago_revenue_native_mn": million(source_row.get("yearAgoRevenue")),
            "growth_pct": pd.to_numeric(source_row.get("growth"), errors="coerce") * 100.0,
            "source_quality": "yfinance_discovery",
            "revision_history_available": False,
            "source_url": f"https://finance.yahoo.com/quote/{source_ticker}/analysis/",
            "source_note": (
                "Yahoo Finance/yfinance revenue-estimate snapshot. The provider exposes "
                "average/low/high/analyst count and growth but not a complete estimate-vintage "
                "history or exact broker update timestamps; forecast period is the provider's "
                f"{period} label as retrieved on {snapshot_date}."
            ),
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=REVENUE_CONSENSUS_COLUMNS)


def merge_revenue_consensus_history(
    prior: pd.DataFrame,
    current: pd.DataFrame,
) -> pd.DataFrame:
    """Append provider snapshots while replacing only the same PIT key."""
    result = pd.concat([prior, current], ignore_index=True)
    if result.empty:
        return pd.DataFrame(columns=REVENUE_CONSENSUS_COLUMNS)
    result = result.drop_duplicates(
        subset=["ticker", "snapshot_date", "forecast_period"],
        keep="last",
    )
    return result.sort_values(
        ["ticker", "snapshot_date", "fiscal_year"]
    ).reset_index(drop=True)


def fetch_airline_revenue_consensus(
    *,
    snapshot_date: str | None = None,
) -> pd.DataFrame:
    """Fetch and persist free revenue estimates for the airline universe."""
    import yfinance as yf

    snapshot = snapshot_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    retrieved = datetime.now(timezone.utc).isoformat()
    frames: list[pd.DataFrame] = []
    for item in REVENUE_ESTIMATE_UNIVERSE:
        try:
            raw = yf.Ticker(item["source_ticker"]).revenue_estimate
            normalized = normalize_revenue_estimate_frame(
                raw,
                ticker=item["ticker"],
                source_ticker=item["source_ticker"],
                company=item["company"],
                market=item["market"],
                currency=item["currency"],
                snapshot_date=snapshot,
                retrieved_at=retrieved,
            )
            if not normalized.empty:
                frames.append(normalized)
        except Exception:
            continue
    current = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=REVENUE_CONSENSUS_COLUMNS)
    )
    output_path = NORMALIZED_DIR / "airline_revenue_consensus_yfinance.csv"
    if output_path.exists():
        prior = pd.read_csv(output_path)
        result = merge_revenue_consensus_history(prior, current)
    else:
        result = current
    if not result.empty:
        result = result.sort_values(
            ["ticker", "snapshot_date", "fiscal_year"]
        ).reset_index(drop=True)
    result.to_csv(output_path, index=False)
    return result


def source_path() -> Path:
    return NORMALIZED_DIR / "airline_revenue_consensus_yfinance.csv"
