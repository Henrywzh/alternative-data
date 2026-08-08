"""Free Yahoo Finance analyst-estimate and rating-trend discovery layer.

Yahoo exposes useful current aggregates and short-horizon revision counts for
some airline shares.  This module keeps them separate from dated broker-PDF
revisions: the fields are a vendor snapshot, not a complete institutional
consensus-vintage history.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR
from .airline_revenue_consensus import REVENUE_ESTIMATE_UNIVERSE


OUTPUT_PATH = NORMALIZED_DIR / "airline_yahoo_analyst_snapshot.csv"

OUTPUT_COLUMNS = [
    "dataset_id", "ticker", "company", "market", "source_ticker", "snapshot_date",
    "metric", "period", "forecast_year", "metric_unit", "native_currency",
    "value_avg_native", "value_low_native", "value_high_native", "year_ago_value_native",
    "analyst_count", "growth_pct", "up_last_7_days", "up_last_30_days",
    "down_last_30_days", "down_last_7_days", "strong_buy", "buy", "hold", "sell",
    "strong_sell", "rating_total", "buy_add_pct", "stock_trend", "index_trend",
    "source_quality", "revision_signal_available", "revision_history_available",
    "source_url", "source_note", "retrieved_at",
]

ESTIMATE_PERIODS = ("0y", "+1y")


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _retrieved_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_row(
    *,
    item: dict[str, str],
    snapshot_date: str,
    metric: str,
    period: str,
    retrieved_at: str,
    metric_unit: str,
) -> dict[str, Any]:
    forecast_year = None
    if period in ESTIMATE_PERIODS:
        forecast_year = int(snapshot_date[:4]) + (1 if period == "+1y" else 0)
    return {
        "dataset_id": "airline_yahoo_analyst_snapshot",
        "ticker": item["ticker"],
        "company": item["company"],
        "market": item["market"],
        "source_ticker": item["source_ticker"],
        "snapshot_date": snapshot_date,
        "metric": metric,
        "period": period,
        "forecast_year": forecast_year,
        "metric_unit": metric_unit,
        "native_currency": item["currency"],
        "source_quality": "yfinance_discovery",
        "revision_signal_available": False,
        "revision_history_available": False,
        "source_url": f"https://finance.yahoo.com/quote/{item['source_ticker']}/analysis/",
        "source_note": (
            "Yahoo Finance/yfinance current analyst snapshot. Estimate averages, ranges, "
            "recommendation counts and short-horizon EPS revision counts are retained, "
            "but this provider does not expose a complete broker-vintage history or exact "
            "institutional update timestamps."
        ),
        "retrieved_at": retrieved_at,
    }


def _normalize_estimate(
    frame: pd.DataFrame,
    *,
    item: dict[str, str],
    metric: str,
    snapshot_date: str,
    retrieved_at: str,
) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for period in ESTIMATE_PERIODS:
        if period not in frame.index:
            continue
        source = frame.loc[period]
        average = _number(source.get("avg"))
        if average is None:
            continue
        row = _base_row(
            item=item,
            snapshot_date=snapshot_date,
            metric=metric,
            period=period,
            retrieved_at=retrieved_at,
            metric_unit=("native_currency_mn" if metric == "revenue_estimate" else "native_currency_per_share"),
        )
        row.update({
            "value_avg_native": average / 1_000_000.0 if metric == "revenue_estimate" else average,
            "value_low_native": _number(source.get("low")),
            "value_high_native": _number(source.get("high")),
            "year_ago_value_native": _number(source.get("yearAgoRevenue" if metric == "revenue_estimate" else "yearAgoEps")),
            "analyst_count": _number(source.get("numberOfAnalysts")),
            "growth_pct": _number(source.get("growth")),
        })
        if metric == "revenue_estimate":
            for column in ("value_low_native", "value_high_native", "year_ago_value_native"):
                if row[column] is not None:
                    row[column] = row[column] / 1_000_000.0
        rows.append(row)
    return rows


def _normalize_eps_revisions(
    frame: pd.DataFrame,
    *,
    item: dict[str, str],
    snapshot_date: str,
    retrieved_at: str,
) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for period in ESTIMATE_PERIODS:
        if period not in frame.index:
            continue
        source = frame.loc[period]
        fields = {
            "up_last_7_days": _number(source.get("upLast7days")),
            "up_last_30_days": _number(source.get("upLast30days")),
            "down_last_30_days": _number(source.get("downLast30days")),
            "down_last_7_days": _number(source.get("downLast7Days")),
        }
        if all(value is None for value in fields.values()):
            continue
        row = _base_row(
            item=item,
            snapshot_date=snapshot_date,
            metric="eps_revision_signal",
            period=period,
            retrieved_at=retrieved_at,
            metric_unit="analyst_count",
        )
        row.update(fields)
        row["revision_signal_available"] = True
        rows.append(row)
    return rows


def _normalize_recommendations(
    frame: pd.DataFrame,
    *,
    item: dict[str, str],
    snapshot_date: str,
    retrieved_at: str,
) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    if "period" in frame.columns:
        records = ((source.get("period"), source) for _, source in frame.iterrows())
    else:
        records = frame.iterrows()
    for period, source in records:
        counts = {
            "strong_buy": _number(source.get("strongBuy")),
            "buy": _number(source.get("buy")),
            "hold": _number(source.get("hold")),
            "sell": _number(source.get("sell")),
            "strong_sell": _number(source.get("strongSell")),
        }
        total = sum(value or 0 for value in counts.values())
        row = _base_row(
            item=item,
            snapshot_date=snapshot_date,
            metric="recommendation_trend",
            period=str(period),
            retrieved_at=retrieved_at,
            metric_unit="analyst_count",
        )
        row.update(counts)
        row["rating_total"] = total
        row["buy_add_pct"] = 100.0 * ((counts["strong_buy"] or 0) + (counts["buy"] or 0)) / total if total else None
        rows.append(row)
    return rows


def _normalize_growth(
    frame: pd.DataFrame,
    *,
    item: dict[str, str],
    snapshot_date: str,
    retrieved_at: str,
) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for period, source in frame.iterrows():
        stock = _number(source.get("stockTrend"))
        index = _number(source.get("indexTrend"))
        if stock is None and index is None:
            continue
        row = _base_row(
            item=item,
            snapshot_date=snapshot_date,
            metric="growth_estimate",
            period=str(period),
            retrieved_at=retrieved_at,
            metric_unit="percent",
        )
        row["stock_trend"] = stock * 100.0 if stock is not None else None
        row["index_trend"] = index * 100.0 if index is not None else None
        rows.append(row)
    return rows


def normalize_yahoo_analyst_frames(
    *,
    item: dict[str, str],
    earnings_estimate: pd.DataFrame | None,
    revenue_estimate: pd.DataFrame | None,
    eps_revisions: pd.DataFrame | None,
    recommendations: pd.DataFrame | None,
    growth_estimates: pd.DataFrame | None,
    snapshot_date: str,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    retrieved = retrieved_at or _retrieved_at()
    rows = []
    rows.extend(_normalize_estimate(
        revenue_estimate, item=item, metric="revenue_estimate",
        snapshot_date=snapshot_date, retrieved_at=retrieved,
    ))
    rows.extend(_normalize_estimate(
        earnings_estimate, item=item, metric="eps_estimate",
        snapshot_date=snapshot_date, retrieved_at=retrieved,
    ))
    rows.extend(_normalize_eps_revisions(
        eps_revisions, item=item, snapshot_date=snapshot_date, retrieved_at=retrieved,
    ))
    rows.extend(_normalize_recommendations(
        recommendations, item=item, snapshot_date=snapshot_date, retrieved_at=retrieved,
    ))
    rows.extend(_normalize_growth(
        growth_estimates, item=item, snapshot_date=snapshot_date, retrieved_at=retrieved,
    ))
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def merge_yahoo_analyst_history(prior: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    """Append provider snapshots while replacing only the same PIT key."""
    result = pd.concat([prior, current], ignore_index=True)
    if result.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    for column in OUTPUT_COLUMNS:
        if column not in result.columns:
            result[column] = None
    key = ["ticker", "snapshot_date", "metric", "period"]
    result = result.drop_duplicates(key, keep="last")
    return result.sort_values(["ticker", "snapshot_date", "metric", "period"])[OUTPUT_COLUMNS].reset_index(drop=True)


def fetch_airline_yahoo_analyst_snapshot(*, snapshot_date: str | None = None) -> pd.DataFrame:
    """Fetch free Yahoo analyst estimates, revision signals and ratings."""
    import yfinance as yf

    snapshot = snapshot_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    retrieved = _retrieved_at()
    frames: list[pd.DataFrame] = []
    for item in REVENUE_ESTIMATE_UNIVERSE:
        try:
            ticker = yf.Ticker(item["source_ticker"])
            frames.append(normalize_yahoo_analyst_frames(
                item=item,
                earnings_estimate=ticker.get_earnings_estimate(),
                revenue_estimate=ticker.get_revenue_estimate(),
                eps_revisions=ticker.get_eps_revisions(),
                recommendations=ticker.get_recommendations(),
                growth_estimates=ticker.get_growth_estimates(),
                snapshot_date=snapshot,
                retrieved_at=retrieved,
            ))
        except Exception:
            continue
    current = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True) if frames else pd.DataFrame(columns=OUTPUT_COLUMNS)
    result = merge_yahoo_analyst_history(pd.read_csv(OUTPUT_PATH), current) if OUTPUT_PATH.exists() else current
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
