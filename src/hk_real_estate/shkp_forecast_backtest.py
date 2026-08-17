"""Bounded SHKP scenario and release-event research outputs.

This module is deliberately downstream of the first-stage financial-model
inputs.  It does not manufacture a historical earnings-vintage tape from
current data.  Instead it provides two auditable, distinct surfaces:

* current broker/consensus scenario ranges for FY2026 onward; and
* an event study around the eight SHKP releases whose HKEX publication times
  are currently curated, using the daily price contract without same-day
  post-release leakage.

Both outputs are research-only.  The event study is not a causal estimate or
an investable strategy backtest, and the current scenario ranges are not
point-in-time historical forecasts.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from .shkp_financial_model import SHKP_TICKER
from .storage import load_latest_normalized, save_normalized_dataset


FORECAST_SCENARIO_COLUMNS = [
    "scenario_id",
    "ticker",
    "forecast_year",
    "metric",
    "scenario",
    "value",
    "unit",
    "currency",
    "source_layer",
    "source",
    "source_rows",
    "forecast_date_min",
    "forecast_date_max",
    "snapshot_date",
    "estimate_period_end",
    "availability_quality",
    "model_use",
    "research_only",
    "caveat",
]


RELEASE_EVENT_STUDY_COLUMNS = [
    "event_id",
    "ticker",
    "event_type",
    "title",
    "reporting_period_end",
    "release_at_hkt",
    "release_date_hkt",
    "event_price_date",
    "event_price_adj_close",
    "pre_return_5d",
    "pre_return_20d",
    "forward_return_1d",
    "forward_return_5d",
    "forward_return_20d",
    "forward_price_date_1d",
    "forward_price_date_5d",
    "forward_price_date_20d",
    "event_window_status",
    "same_day_inclusion_policy",
    "price_source",
    "price_source_url",
    "release_source_url",
    "availability_quality",
    "model_use",
    "research_only",
    "caveat",
]


FORECAST_BACKTEST_COVERAGE_COLUMNS = [
    "run_id",
    "ticker",
    "model_input_run_id",
    "scenario_rows",
    "event_rows",
    "event_rows_with_20d_forward_window",
    "release_events_with_exact_hkex_time",
    "price_history_first_date",
    "price_history_last_date",
    "scenario_model_use",
    "backtest_model_use",
    "research_only",
    "status",
    "caveat",
    "created_at",
]


_BROKER_METRIC_MAP: tuple[tuple[str, str, str, str], ...] = (
    ("eps", "eps", "currency_per_share", "eps_currency"),
    # The sibling broker table stores net profit as an absolute currency value
    # (for example ~2.3e10 HKD), not HKD millions.  Keep the unit generic and
    # preserve the raw provider magnitude rather than relabelling it.
    ("net_profit", "net_profit", "currency", "net_profit_currency"),
    ("dividend", "dividend", "currency_per_share", "dividend_currency"),
    ("target_price", "target_price", "currency_per_share", "target_price_currency"),
)


def _as_date(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).strftime("%Y-%m-%d")


def _as_hkt_timestamp(value: Any) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    timestamp = pd.Timestamp(parsed)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("Asia/Hong_Kong")
    return timestamp.tz_convert("Asia/Hong_Kong")


def _scenario_id(year: Any, metric: str, scenario: str, source_layer: str) -> str:
    year_label = "unspecified" if pd.isna(year) else str(int(year))
    return f"shkp:scenario:{source_layer}:{year_label}:{metric}:{scenario}"


def _scenario_row(
    *,
    year: int,
    metric: str,
    scenario: str,
    value: float,
    unit: str,
    currency: str | None,
    source_layer: str,
    source: str,
    source_rows: int,
    forecast_date_min: str | None,
    forecast_date_max: str | None,
    snapshot_date: str | None,
    estimate_period_end: str | None,
    caveat: str,
) -> dict[str, Any]:
    return {
        "scenario_id": _scenario_id(year, metric, scenario, source_layer),
        "ticker": SHKP_TICKER,
        "forecast_year": int(year),
        "metric": metric,
        "scenario": scenario,
        "value": float(value),
        "unit": unit,
        "currency": currency,
        "source_layer": source_layer,
        "source": source,
        "source_rows": int(source_rows),
        "forecast_date_min": forecast_date_min,
        "forecast_date_max": forecast_date_max,
        "snapshot_date": snapshot_date,
        "estimate_period_end": estimate_period_end,
        "availability_quality": "current_batch_snapshot",
        "model_use": "current_snapshot_scenario_only",
        "research_only": True,
        "caveat": caveat,
    }


def build_shkp_forecast_scenarios(
    broker_forecasts: pd.DataFrame,
    consensus: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build transparent low/base/high current-snapshot scenarios.

    Broker rows use min/median/max within each fiscal year.  Consensus rows
    use the provider's low/mean/high statistics.  The two layers are kept
    separate rather than averaged together, because they have different
    aggregation and provenance semantics.
    """
    if broker_forecasts is None or broker_forecasts.empty:
        raise ValueError("broker_forecasts is required for the current scenario baseline")
    rows: list[dict[str, Any]] = []
    broker = broker_forecasts.copy()
    if "ticker" in broker.columns and broker["ticker"].astype(str).ne(SHKP_TICKER).any():
        raise ValueError("broker_forecasts contains a non-SHKP ticker")
    for metric, value_column, unit, currency_column in _BROKER_METRIC_MAP:
        if value_column not in broker.columns:
            continue
        broker[value_column] = pd.to_numeric(broker[value_column], errors="coerce")
        for year, group in broker.groupby("fiscal_year", dropna=True):
            values = group[value_column].dropna()
            if values.empty:
                continue
            parsed_forecast_dates = pd.to_datetime(group.get("forecast_date"), errors="coerce")
            parsed_fetched_dates = pd.to_datetime(group.get("fetched_at"), errors="coerce", utc=True)
            currency = None
            if currency_column in group.columns:
                currency_values = group[currency_column].dropna().astype(str).str.strip()
                if not currency_values.empty:
                    currency = currency_values.mode().iloc[0]
            values_by_scenario = {
                "low": float(values.min()),
                "base": float(values.median()),
                "high": float(values.max()),
            }
            for scenario, value in values_by_scenario.items():
                rows.append(_scenario_row(
                    year=int(year),
                    metric=metric,
                    scenario=scenario,
                    value=value,
                    unit=unit,
                    currency=currency,
                    source_layer="broker_forecasts",
                    source="financial-data.broker_forecasts",
                    source_rows=len(values),
                    forecast_date_min=_as_date(parsed_forecast_dates.min()),
                    forecast_date_max=_as_date(parsed_forecast_dates.max()),
                    snapshot_date=_as_date(parsed_fetched_dates.max()),
                    estimate_period_end=None,
                    caveat=(
                        "Aggregated from the current broker batch by fiscal year; "
                        "forecast_date is preserved but this is not a historical estimate-vintage series."
                    ),
                ))

    if consensus is not None and not consensus.empty:
        consensus_frame = consensus.copy()
        if "ticker" in consensus_frame.columns and consensus_frame["ticker"].astype(str).ne(SHKP_TICKER).any():
            raise ValueError("consensus contains a non-SHKP ticker")
        statistic_to_scenario = {"low": "low", "mean": "base", "high": "high"}
        for row in consensus_frame.to_dict("records"):
            statistic = str(row.get("statistic") or "").lower()
            if statistic not in statistic_to_scenario or pd.isna(row.get("fiscal_year")):
                continue
            value = pd.to_numeric(pd.Series([row.get("value")]), errors="coerce").iloc[0]
            if pd.isna(value):
                continue
            metric = str(row.get("metric") or "").strip()
            if not metric:
                continue
            unit = str(row.get("unit") or "unknown")
            currency = str(row.get("currency") or "").strip() or None
            rows.append(_scenario_row(
                year=int(row["fiscal_year"]),
                metric=metric,
                scenario=statistic_to_scenario[statistic],
                value=float(value),
                unit=unit,
                currency=currency,
                source_layer="consensus_statistics",
                source=str(row.get("source") or "financial-data.consensus_statistics_history"),
                source_rows=int(row.get("contributor_count") or 0),
                forecast_date_min=None,
                forecast_date_max=None,
                snapshot_date=_as_date(row.get("snapshot_date")),
                estimate_period_end=_as_date(row.get("estimate_period_end")),
                caveat=(
                    "Provider low/mean/high statistic from one current snapshot; "
                    "estimate_period_end is missing in the available consensus rows."
                ),
            ))
    frame = pd.DataFrame(rows, columns=FORECAST_SCENARIO_COLUMNS)
    if frame.empty:
        raise ValueError("No usable current forecast scenario rows were produced")
    if frame.duplicated("scenario_id").any():
        # A provider can expose multiple rows with the same fiscal year and
        # statistic.  Keep the source layer in the key and fail loudly only if
        # the normalized scenario identity itself collides.
        raise ValueError("forecast scenario IDs are not unique")
    return frame


def _price_at_index(prices: pd.DataFrame, index: int) -> float | None:
    if index < 0 or index >= len(prices):
        return None
    value = pd.to_numeric(pd.Series([prices.iloc[index]["adj_close"]]), errors="coerce").iloc[0]
    return float(value) if pd.notna(value) else None


def _return_from_indices(prices: pd.DataFrame, start_index: int, end_index: int) -> float | None:
    start = _price_at_index(prices, start_index)
    end = _price_at_index(prices, end_index)
    if start is None or end is None or start == 0:
        return None
    return float(end / start - 1.0)


def build_shkp_release_event_study(
    corporate_documents: pd.DataFrame,
    price_history: pd.DataFrame,
    *,
    horizons: Iterable[int] = (1, 5, 20),
) -> pd.DataFrame:
    """Measure forward adjusted-close returns after exact HKEX release times.

    The curated release records are timestamped at 16:30–16:36 HKT, after the
    regular Hong Kong close.  The event close therefore includes the trading
    date's close and the first forward observation is the next trading
    session.  If a future release is before the close, the generic policy uses
    the prior trading close instead; this avoids accidentally using a price
    that was not available when the event was published.
    """
    if corporate_documents is None or corporate_documents.empty:
        raise ValueError("corporate_documents is required for the release event study")
    if price_history is None or price_history.empty:
        raise ValueError("price_history is required for the release event study")
    prices = price_history.copy()
    if prices["ticker"].astype(str).ne(SHKP_TICKER).any():
        raise ValueError("price_history contains a non-SHKP ticker")
    prices["_trading_date"] = pd.to_datetime(prices["trading_date"], errors="coerce").dt.normalize()
    prices = prices.dropna(subset=["_trading_date"]).sort_values("_trading_date").reset_index(drop=True)
    price_dates = pd.DatetimeIndex(prices["_trading_date"])
    horizon_values = tuple(sorted({int(h) for h in horizons if int(h) > 0}))
    if not horizon_values:
        raise ValueError("horizons must contain at least one positive trading-day horizon")
    docs = corporate_documents.copy()
    docs["_release_ts_hkt"] = docs.get("hkex_release_at", pd.Series(dtype="string")).map(_as_hkt_timestamp)
    docs = docs.dropna(subset=["_release_ts_hkt"]).copy()
    if docs.empty:
        raise ValueError("corporate_documents has no exact hkex_release_at rows")
    rows: list[dict[str, Any]] = []
    for ordinal, document in enumerate(docs.sort_values("_release_ts_hkt").to_dict("records"), start=1):
        release_ts = document["_release_ts_hkt"]
        release_date = release_ts.normalize().tz_localize(None)
        # Publication after 16:00 HKT is safely after the market close.  For a
        # future before-close timestamp, use the prior close instead.
        after_close = release_ts.hour >= 16
        if after_close:
            event_index = int(price_dates.searchsorted(release_date, side="right") - 1)
        else:
            event_index = int(price_dates.searchsorted(release_date, side="left") - 1)
        if event_index < 0:
            continue
        event_price = _price_at_index(prices, event_index)
        if event_price is None:
            continue
        event_id = f"shkp:event:{_as_date(release_ts)}:{ordinal}"
        row: dict[str, Any] = {
            "event_id": event_id,
            "ticker": SHKP_TICKER,
            "event_type": document.get("document_semantics") or document.get("document_type"),
            "title": document.get("title"),
            "reporting_period_end": _as_date(document.get("reporting_period_end")),
            "release_at_hkt": release_ts.isoformat(),
            "release_date_hkt": release_ts.strftime("%Y-%m-%d"),
            "event_price_date": _as_date(prices.iloc[event_index]["_trading_date"]),
            "event_price_adj_close": event_price,
            "pre_return_5d": _return_from_indices(prices, event_index - 5, event_index),
            "pre_return_20d": _return_from_indices(prices, event_index - 20, event_index),
            "event_window_status": "complete",
            "same_day_inclusion_policy": "after_close_release_uses_same_day_close_then_next_session",
            "price_source": str(prices.iloc[event_index].get("source") or "yfinance"),
            "price_source_url": str(prices.iloc[event_index].get("source_url") or ""),
            "release_source_url": document.get("release_source_url") or document.get("document_url"),
            "availability_quality": "exact_curated_hkex_release_time_plus_vendor_price_replay",
            "model_use": "release_event_study_only",
            "research_only": True,
            "caveat": (
                "Event-window return is descriptive, not causal or investable. "
                "The release time is exact for the curated HKEX record; Yahoo adjusted-close history is a vendor replay, not a full PIT price tape."
            ),
        }
        for horizon in horizon_values:
            future_index = event_index + horizon
            future_return = _return_from_indices(prices, event_index, future_index)
            row[f"forward_return_{horizon}d"] = future_return
            row[f"forward_price_date_{horizon}d"] = (
                _as_date(prices.iloc[future_index]["_trading_date"])
                if 0 <= future_index < len(prices)
                else None
            )
            if future_return is None:
                row["event_window_status"] = "partial_history"
        rows.append(row)
    frame = pd.DataFrame(rows)
    # Keep the fixed contract for the standard horizons.  Additional horizons
    # are intentionally not silently dropped; callers should use the standard
    # event study for the persisted research artifact.
    required_columns = set(RELEASE_EVENT_STUDY_COLUMNS)
    missing = sorted(required_columns - set(frame.columns))
    if missing:
        raise ValueError("event study missing contract columns: " + ", ".join(missing))
    return frame.reindex(columns=RELEASE_EVENT_STUDY_COLUMNS)


def _latest_model_run_id() -> str | None:
    coverage = load_latest_normalized("shkp_financial_model_coverage")
    if coverage.empty or "model_run_id" not in coverage.columns:
        return None
    value = coverage.iloc[0].get("model_run_id")
    return str(value) if pd.notna(value) and str(value).strip() else None


def run_shkp_forecast_backtest(*, run_id: str | None = None) -> dict[str, Any]:
    """Persist the bounded SHKP scenario/event-study research artifacts."""
    research_run_id = run_id or f"shkp-forecast-backtest-{uuid.uuid4()}"
    model_run_id = _latest_model_run_id()
    broker = load_latest_normalized("shkp_financial_model_broker_forecasts")
    consensus = load_latest_normalized("shkp_financial_model_consensus")
    corporate_documents = load_latest_normalized("shkp_corporate_documents")
    prices = load_latest_normalized("shkp_financial_model_price_history")
    scenarios = build_shkp_forecast_scenarios(broker, consensus)
    event_study = build_shkp_release_event_study(corporate_documents, prices)
    scenarios["run_id"] = research_run_id
    event_study["run_id"] = research_run_id
    price_dates = pd.to_datetime(prices["trading_date"], errors="coerce")
    coverage = pd.DataFrame([{
        "run_id": research_run_id,
        "ticker": SHKP_TICKER,
        "model_input_run_id": model_run_id,
        "scenario_rows": int(len(scenarios)),
        "event_rows": int(len(event_study)),
        "event_rows_with_20d_forward_window": int(event_study["forward_return_20d"].notna().sum()),
        "release_events_with_exact_hkex_time": int(len(event_study)),
        "price_history_first_date": _as_date(price_dates.min()),
        "price_history_last_date": _as_date(price_dates.max()),
        "scenario_model_use": "current_snapshot_scenario_only",
        "backtest_model_use": "release_event_study_only",
        "research_only": True,
        "status": "valid_research_only_event_study_and_current_scenarios",
        "caveat": (
            "This run does not claim historical earnings-vintage backtesting: sibling actuals lack original announcement dates, "
            "consensus has one snapshot, and Yahoo prices are a vendor replay. Ownership-gated project activity is not used as attributable sales."
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }])
    release_source_urls = sorted({
        str(value).strip()
        for value in corporate_documents.get("release_source_url", pd.Series(dtype="string")).dropna().tolist()
        if str(value).strip()
    })
    price_source_urls = ["https://finance.yahoo.com/quote/0016.HK/history"]
    frames = {
        "shkp_forecast_scenarios": scenarios,
        "shkp_release_event_study": event_study,
        "shkp_forecast_backtest_coverage": coverage,
    }
    normalized: dict[str, Any] = {}
    for dataset_name, frame in frames.items():
        dataset_source_urls = (
            []
            if dataset_name == "shkp_forecast_scenarios"
            else price_source_urls + release_source_urls
        )
        normalized[dataset_name] = save_normalized_dataset(
            dataset_name,
            frame,
            run_id=research_run_id,
            source_urls=sorted(set(dataset_source_urls)),
            lineage_metadata={
                "lineage_type": "shkp_research_forecast_backtest",
                "research_run_id": research_run_id,
                "model_input_run_id": model_run_id,
                "research_only": True,
                "point_in_time_policy": "exact_curated_hkex_release_time_for_event_study; current_snapshot_only_for_scenarios",
                "ownership_policy": "project_activity_not_used_as_attributable_sales_without_approved_phase_interval",
            },
        )
    return {
        "mode": "shkp_forecast_backtest_research_only",
        "run_id": research_run_id,
        "model_input_run_id": model_run_id,
        "dataset_counts": {name: int(len(frame)) for name, frame in frames.items()},
        "normalized": normalized,
        "status": coverage.iloc[0]["status"],
        "research_only": True,
    }
