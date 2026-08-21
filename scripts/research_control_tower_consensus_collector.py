#!/usr/bin/env python3
"""Collect analyst consensus for the Research Control Tower.

Consensus is the keystone the Control Tower was missing. Surprise, revision
breadth, "what changed" and catalyst scoring all need an expectation to
compare against, and with `consensus_snapshots` and `consensus_revisions`
empty none of them could work at all.

Two providers are collected and deliberately kept **unblended** -- the company
page renders provider rows side by side and states that they are not blended,
so mixing them here would destroy the only thing that panel is for:

* ``yfinance``            live analyst estimates; covers the US and HK lines.
* ``financial_data_akshare``  the akshare consensus snapshot already collected
                          by the sibling repository at
                          ``~/Desktop/Quant/financial-data``; HK lines only.

Fiscal-period alignment is not invented here. yfinance labels estimates only
by relative horizon (``0q``/``+1q``/``0y``/``+1y``) and carries no fiscal year,
which matters because several of these issuers do not close on 31 December --
Alibaba's fiscal year ends in March, so deriving a year from the calendar
would silently mislabel every estimate. The sibling repository already solved
this: its ``consensus_period_mapping`` table maps (ticker, metric, horizon) to
a fiscal year and period end with an explicit alignment quality and
confidence. Where it has no row, fiscal_year and estimate_period_end are left
null and ``coverage_reason`` says so rather than guessing.

Revisions are reconstructed from yfinance's ``eps_trend``, which reports the
consensus as it stood 7, 30, 60 and 90 days ago. That is the provider's own
retrospective statement, not a vintage this repository captured, so those rows
are labelled ``reconstructed_sparse`` and the UI badges them as such. From the
first run onward the snapshots accumulate into genuine point-in-time history;
the reconstruction only exists to give the panel a cold start.

Batch 7 accumulation semantics (day-granular immutability):

* Every run appends its captured snapshots to an append-only store at
  ``<output-dir>/store/snapshots_store.parquet``.
* The natural key is (provider, listing_id, metric, horizon, statistic,
  fiscal_period, fiscal_year, estimate_period_end), keyed null-safely.
* One vintage per natural key per UTC calendar day. A same-day rerun for the
  same key REPLACES that day's row (last-write-wins within the day), which
  makes scheduled daily collection idempotent; different days always append.
  Intra-day value changes are intentionally not retained — the cadence is
  daily, and ``snapshot_id`` is a deterministic hash of the natural key plus
  the UTC date so re-runs produce stable, joinable ids.
* Genuine revisions are derived from consecutive store vintages per natural
  key and carry ``pit_class="repository_captured"``. Reconstructed
  eps_trend rows remain as a labelled cold-start fallback; the two coexist
  and are never blended or deduped against each other.

Usage::

    python scripts/research_control_tower_consensus_collector.py \
        --listings config/research_control_tower/listings.csv \
        --output-dir data/normalized/research_control_tower/consensus
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from typing import Mapping, Sequence
import uuid

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_control_tower.build import (  # noqa: E402
    TASK3_HEALTH_ARROW_SCHEMA,
    TASK3_REVISION_ARROW_SCHEMA,
    TASK3_SNAPSHOT_ARROW_SCHEMA,
)

FINANCIAL_DATA_ROOT = Path.home() / "Desktop" / "Quant" / "financial-data"
FD_DUCKDB = FINANCIAL_DATA_ROOT / "data" / "databases" / "hk_financials.duckdb"
FD_CONSENSUS = FINANCIAL_DATA_ROOT / "data" / "processed" / "hk_financials" / "consensus_snapshots"

YF_SOURCE_URL = "https://finance.yahoo.com/quote/{symbol}/analysis"
# The Task 3 provider policy admits populated consensus rows only under a
# local/private research licence with evidence and a policy reference. Both
# labels below are the accurate description of the use, not a way around the
# gate: nothing here is redistributed, and the akshare rows are relayed from
# the sibling repository rather than re-fetched (recorded in
# calculation_origin).
YF_LICENSE = "research_use_only"
FD_LICENSE = "local_private_research"

# yfinance reports estimates by relative horizon only.
HORIZONS = ("0q", "+1q", "0y", "+1y")
LOOKBACKS = {"7daysAgo": 7, "30daysAgo": 30, "60daysAgo": 60, "90daysAgo": 90}

STORE_DIRNAME = "store"
STORE_FILENAME = "snapshots_store.parquet"


def _hash(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def _f(value: object) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(out) else out


def _i(value: object) -> int | None:
    out = _f(value)
    return None if out is None else int(out)


STORE_COLUMNS = list(TASK3_SNAPSHOT_ARROW_SCHEMA.names)
REVISION_COLUMNS = list(TASK3_REVISION_ARROW_SCHEMA.names)


def _key_part(value: object) -> str:
    """NULL-safe natural-key part: None/NaN/NaT all key as the empty string."""

    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):  # pd.isna is not total over scalar types
        pass
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def snapshot_natural_key(row: Mapping[str, object]) -> tuple[str, ...]:
    """The store's natural key for a snapshot row or mapping.

    ``(provider, listing_id, metric, horizon, statistic, fiscal_period,
    fiscal_year, estimate_period_end)`` with NULL-safe parts (see
    :func:`_key_part`). Unaligned rows (null fiscal year / estimate period end)
    therefore key consistently with empty strings rather than NaN.
    """

    return (
        _key_part(row.get("provider")),
        _key_part(row.get("listing_id")),
        _key_part(row.get("metric")),
        _key_part(row.get("horizon")),
        _key_part(row.get("statistic")),
        _key_part(row.get("fiscal_period")),
        _key_part(row.get("fiscal_year")),
        _key_part(row.get("estimate_period_end")),
    )


def _snapshot_day(value: object, fallback: date) -> date:
    """UTC calendar day of ``snapshot_at``; ``fallback`` when null/NaT."""

    if value is None:
        return fallback
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return fallback
    if pd.isna(ts):
        return fallback
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.date()


def stable_snapshot_id(row: Mapping[str, object], fallback: date) -> str:
    """Deterministic stable id: hash of natural key + ``snapshot_at`` UTC date.

    Deliberately independent of ``run_id`` and of the within-day collection
    timestamp, so a same-day rerun keeps the same id and genuine revisions
    reference ids that stay stable across runs and across files.
    """

    return _hash(
        *snapshot_natural_key(row),
        str(_snapshot_day(row.get("snapshot_at"), fallback)),
    )


def accumulate_snapshots(
    store: pd.DataFrame,
    new_rows: Sequence[Mapping[str, object]],
    run_date: date,
) -> pd.DataFrame:
    """Merge a collection batch into the append-only snapshot store.

    Returns the merged store as a DataFrame with exactly
    ``TASK3_SNAPSHOT_ARROW_SCHEMA`` columns. Dedupe policy: one row per natural
    key per UTC calendar day of ``snapshot_at``; within a day the newest row
    wins (last-write-wins), so same-day reruns are idempotent while different
    days append. ``snapshot_id`` is recomputed as the deterministic stable
    hash (natural key + ``snapshot_at`` UTC date) on every row, replacing any
    run-scoped id the collector originally assigned. ``run_date`` is the
    fallback UTC day only when a row's ``snapshot_at`` is null/NaT.
    """

    if store is None or store.empty:
        existing = pd.DataFrame({column: pd.Series(dtype="object") for column in STORE_COLUMNS})
    else:
        existing = store[STORE_COLUMNS].copy()
    existing = existing.drop_duplicates(subset=STORE_COLUMNS)
    new = pd.DataFrame(list(new_rows), columns=STORE_COLUMNS)
    new = new.assign(
        __stable_id=[stable_snapshot_id(row, run_date) for _, row in new.iterrows()],
        __key=["\x1f".join(snapshot_natural_key(row)) for _, row in new.iterrows()],
        __day=[str(_snapshot_day(row.get("snapshot_at"), run_date)) for _, row in new.iterrows()],
    )
    new["snapshot_id"] = new["__stable_id"]
    new = new.drop(columns=["__stable_id"])

    existing["__key"] = ["\x1f".join(snapshot_natural_key(row)) for _, row in existing.iterrows()]
    existing["__day"] = [str(_snapshot_day(row.get("snapshot_at"), run_date)) for _, row in existing.iterrows()]
    if existing.empty:
        merged = new
    elif new.empty:
        merged = existing
    else:
        # Only concat when both sides carry data: pandas deprecates concat of
        # empty/all-NA frames and the store is routinely empty on first run.
        merged = pd.concat([existing, new], ignore_index=True)
    # Last-write-wins within (natural key, UTC day): after the concat the new
    # batch rows come last, so keep="last" replaces the same-day store row and
    # preserves every other vintage.
    merged = merged.drop_duplicates(subset=["__key", "__day"], keep="last")
    merged = merged.drop(columns=["__key", "__day"])
    merged = merged.sort_values(
        ["snapshot_at", "provider", "listing_id", "metric", "horizon", "statistic"],
        kind="mergesort",
        ignore_index=True,
    )
    return merged[STORE_COLUMNS]


def _genuine_revision_row(prior: pd.Series, current: pd.Series) -> dict[str, object]:
    """One genuine revision from a consecutive (prior -> current) snapshot pair."""

    prior_value = _f(prior.get("value"))
    current_value = _f(current.get("value"))
    revision_value: float | None = (
        None
        if prior_value is None or current_value is None
        else current_value - prior_value
    )
    revision_pct: float | None = (
        revision_value / abs(prior_value)
        if revision_value is not None and prior_value not in (None, 0)
        else None
    )
    prior_ac = _i(prior.get("analyst_count"))
    current_ac = _i(current.get("analyst_count"))
    analyst_count_change: int | None = (
        None if prior_ac is None or current_ac is None else current_ac - prior_ac
    )
    prior_at = pd.Timestamp(prior.get("snapshot_at"))
    current_at = pd.Timestamp(current.get("snapshot_at"))
    lookback_days: int | None = (
        (current_at - prior_at).days
        if not pd.isna(prior_at) and not pd.isna(current_at)
        else None
    )
    return {
        "revision_id": _hash(prior.get("snapshot_id"), current.get("snapshot_id")),
        "snapshot_id": str(current.get("snapshot_id")),
        "provider": str(current.get("provider")),
        "prior_provider": str(prior.get("provider")),
        "entity_id": str(current.get("entity_id")),
        "listing_id": str(current.get("listing_id")),
        "financial_data_security_id": str(current.get("financial_data_security_id") or ""),
        "canonical_ticker": str(current.get("canonical_ticker")),
        "metric": str(current.get("metric")),
        "fiscal_period": str(current.get("fiscal_period")),
        "fiscal_year": _i(current.get("fiscal_year")),
        "estimate_period_end": current.get("estimate_period_end"),
        "horizon": str(current.get("horizon")),
        "statistic": str(current.get("statistic")),
        "current_snapshot_at": current.get("snapshot_at"),
        "current_value": current_value,
        "current_analyst_count": current_ac,
        # The snapshot schema carries no dispersion or alignment-status fields,
        # so the store cannot persist them and genuine rows report them as
        # null rather than inventing values (see module docstring).
        "current_dispersion": None,
        "lookback_days": lookback_days,
        "cutoff_at": prior.get("snapshot_at"),
        "prior_snapshot_id": str(prior.get("snapshot_id")),
        "prior_snapshot_at": prior.get("snapshot_at"),
        "prior_value": prior_value,
        "prior_provider_asof": prior.get("provider_asof"),
        "provider_asof": current.get("provider_asof"),
        "retrieved_at_utc": current.get("retrieved_at_utc"),
        "source_url": str(current.get("source_url")),
        "pit_class": "repository_captured",
        "source_run_id": str(current.get("source_run_id")),
        "prior_analyst_count": prior_ac,
        "revision_value": revision_value,
        "revision_pct": revision_pct,
        "analyst_count_change": analyst_count_change,
        "dispersion": None,
        "alignment_status": None,
    }


def derive_genuine_revisions(store: pd.DataFrame) -> pd.DataFrame:
    """Genuine revisions from consecutive store vintages per natural key.

    Rows of the same natural key are ordered by ``snapshot_at`` and each
    consecutive pair yields one revision row (older ``prior_*`` fields, newer
    ``current_*`` fields) labelled ``pit_class="repository_captured"``. The
    derivation is deterministic: ordering, revision ids and pairwise values
    depend only on the store contents, never on run metadata.
    """

    if store is None or store.empty:
        return pd.DataFrame({column: pd.Series(dtype="object") for column in REVISION_COLUMNS})
    frame = store[STORE_COLUMNS].copy()
    frame["__key"] = ["\x1f".join(snapshot_natural_key(row)) for _, row in frame.iterrows()]
    frame["__ord"] = range(len(frame))
    frame = frame.sort_values(["__key", "snapshot_at", "__ord"], kind="mergesort")
    prior_key = frame["__key"].shift(1)
    paired = frame["__key"].eq(prior_key)
    priors = frame.shift(1).loc[paired]
    currents = frame.loc[paired]
    rows = [
        _genuine_revision_row(prior_row, current_row)
        for prior_row, current_row in zip(
            (priors.loc[index] for index in priors.index),
            (currents.loc[index] for index in currents.index),
        )
    ]
    if not rows:
        return pd.DataFrame({column: pd.Series(dtype="object") for column in REVISION_COLUMNS})
    return pd.DataFrame(rows, columns=REVISION_COLUMNS)


def combine_revision_export(
    genuine: pd.DataFrame,
    reconstructed: pd.DataFrame,
) -> pd.DataFrame:
    """Combine genuine and reconstructed revisions for export.

    Ordering: genuine first (most recent ``current_snapshot_at`` first), then
    the reconstructed rows in their original order. The two classes are never
    blended or deduped against each other -- they coexist, distinctly labelled
    by ``pit_class``.
    """

    genuine = genuine.sort_values("current_snapshot_at", ascending=False, kind="mergesort")
    parts = []
    if not genuine.empty:
        parts.append(genuine[REVISION_COLUMNS])
    if not reconstructed.empty:
        parts.append(reconstructed[REVISION_COLUMNS])
    if not parts:
        return pd.DataFrame({column: pd.Series(dtype="object") for column in REVISION_COLUMNS})
    return pd.concat(parts, ignore_index=True)


def snapshot_export_frame(store: pd.DataFrame) -> pd.DataFrame:
    """Full store history sorted for the snapshots export."""

    return store.sort_values(
        ["listing_id", "provider", "metric", "horizon", "statistic", "snapshot_at"],
        kind="mergesort",
        ignore_index=True,
    )[STORE_COLUMNS]


def _read_store(path: Path) -> pd.DataFrame:
    if path.is_file():
        frame = pd.read_parquet(path)
    else:
        frame = pd.DataFrame({column: pd.Series(dtype="object") for column in STORE_COLUMNS})
    return frame[STORE_COLUMNS]


def load_period_mapping() -> pd.DataFrame:
    """(ticker, metric, horizon) -> fiscal year / period end, from financial-data."""
    if not FD_DUCKDB.is_file():
        return pd.DataFrame()
    try:
        import duckdb
    except ImportError:
        return pd.DataFrame()
    try:
        con = duckdb.connect(str(FD_DUCKDB), read_only=True)
        frame = con.execute(
            """
            select ticker, metric, source_horizon, mapped_fiscal_year, mapped_period_end,
                   alignment_quality, confidence
            from consensus_period_mapping
            """
        ).df()
        con.close()
        return frame
    except Exception:
        return pd.DataFrame()


def _alignment(
    mapping: pd.DataFrame,
    ticker: str,
    metric: str,
    horizon: str,
    sibling_tickers: tuple[str, ...] = (),
) -> dict[str, object]:
    if mapping.empty:
        return {
            "fiscal_year": None, "estimate_period_end": None,
            "alignment_status": "unaligned_no_mapping_source",
            "coverage_reason": "financial-data consensus_period_mapping unavailable; horizon not resolved to a fiscal period",
        }
    row = mapping.loc[
        mapping["ticker"].eq(ticker)
        & mapping["metric"].eq(metric)
        & mapping["source_horizon"].eq(horizon)
    ]
    borrowed_from = ""
    if row.empty:
        # A fiscal calendar belongs to the issuer, not to one of its listings:
        # BABA.US and 9988.HK close the same March year end. financial-data
        # keys its mapping by HK ticker, so a US line would otherwise go
        # unaligned purely because the sibling repository's universe is
        # HK-only. Borrow from another listing of the same entity and say so.
        for sibling in sibling_tickers:
            if sibling == ticker:
                continue
            candidate = mapping.loc[
                mapping["ticker"].eq(sibling)
                & mapping["metric"].eq(metric)
                & mapping["source_horizon"].eq(horizon)
            ]
            if not candidate.empty:
                row = candidate
                borrowed_from = sibling
                break
    if row.empty:
        return {
            "fiscal_year": None, "estimate_period_end": None,
            "alignment_status": "unaligned_horizon_not_mapped",
            "coverage_reason": f"no consensus_period_mapping row for {ticker}/{metric}/{horizon}",
        }
    first = row.iloc[0]
    end = first.get("mapped_period_end")
    end = None if pd.isna(end) else pd.Timestamp(end).date()
    quality = str(first.get("alignment_quality") or "unknown")
    confidence = str(first.get("confidence") or "unknown")
    status = f"{quality}_confidence_{confidence}"
    if borrowed_from:
        status = f"{status}_via_{borrowed_from}"
    return {
        "fiscal_year": _i(first.get("mapped_fiscal_year")),
        "estimate_period_end": end,
        "alignment_status": status,
        "coverage_reason": (
            f"fiscal period borrowed from same-issuer listing {borrowed_from}" if borrowed_from else ""
        ),
    }


def _sibling_tickers(listings: pd.DataFrame) -> dict[str, tuple[str, ...]]:
    """entity_id -> every canonical ticker that issuer lists under."""
    out: dict[str, tuple[str, ...]] = {}
    for entity, group in listings.groupby("entity_id"):
        out[str(entity)] = tuple(str(t) for t in group["canonical_ticker"])
    return out


def collect_yfinance(
    listings: pd.DataFrame,
    mapping: pd.DataFrame,
    *,
    run_id: str,
    now: datetime,
) -> tuple[list[dict], list[dict], int, list[str]]:
    import yfinance as yf

    siblings = _sibling_tickers(listings)
    snapshots: list[dict] = []
    revisions: list[dict] = []
    calls = 0
    notes: list[str] = []

    for _, listing in listings.iterrows():
        symbol = str(listing["provider_symbol"])
        try:
            ticker = yf.Ticker(symbol)
            estimates = {"eps": ticker.earnings_estimate, "revenue": ticker.revenue_estimate}
            trend = ticker.eps_trend
            calls += 3
        except Exception as exc:  # noqa: BLE001 - provider errors are reported, not raised
            notes.append(f"{symbol}: {type(exc).__name__}: {exc}")
            continue

        for metric, frame in estimates.items():
            if frame is None or frame.empty:
                notes.append(f"{symbol}: no {metric} estimates returned")
                continue
            unit = "currency_per_share" if metric == "eps" else "currency"
            for horizon in HORIZONS:
                if horizon not in frame.index:
                    continue
                row = frame.loc[horizon]
                value = _f(row.get("avg"))
                if value is None:
                    continue
                align = _alignment(mapping, str(listing["canonical_ticker"]), metric, horizon, siblings.get(str(listing["entity_id"]), ()))
                snapshot_id = _hash(run_id, "yfinance", listing["listing_id"], metric, horizon)
                snapshots.append({
                    "snapshot_id": snapshot_id,
                    "provider": "yfinance",
                    "entity_id": str(listing["entity_id"]),
                    "listing_id": str(listing["listing_id"]),
                    "financial_data_security_id": str(listing["financial_data_security_id"] or ""),
                    "canonical_ticker": str(listing["canonical_ticker"]),
                    "metric": metric,
                    "fiscal_period": "quarterly" if horizon.endswith("q") else "annual",
                    "fiscal_year": align["fiscal_year"],
                    "estimate_period_end": align["estimate_period_end"],
                    "horizon": horizon,
                    "snapshot_at": now,
                    "value": value,
                    "statistic": "mean",
                    "low_value": _f(row.get("low")),
                    "high_value": _f(row.get("high")),
                    "analyst_count": _i(row.get("numberOfAnalysts")),
                    "provider_contributor_count": _i(row.get("numberOfAnalysts")),
                    "currency": str(listing["currency"]),
                    "unit": unit,
                    "accounting_basis": "provider_reported_non_gaap_unverified",
                    "provider_asof": now,
                    "retrieved_at_utc": now,
                    "source_url": YF_SOURCE_URL.format(symbol=symbol),
                    "raw_hash": _hash(value, row.get("low"), row.get("high"), row.get("numberOfAnalysts")),
                    "pit_class": "snapshot_from_live_source",
                    "source_run_id": run_id,
                    "calculation_origin": "provider_published_consensus",
                    "coverage_reason": str(align["coverage_reason"]),
                })

                # Revisions only exist for EPS: eps_trend is the one table that
                # restates the consensus at earlier dates.
                if metric != "eps" or trend is None or trend.empty or horizon not in trend.index:
                    continue
                trend_row = trend.loc[horizon]
                current = _f(trend_row.get("current"))
                if current is None:
                    continue
                for column, lookback in LOOKBACKS.items():
                    prior = _f(trend_row.get(column))
                    if prior is None:
                        continue
                    cutoff = (pd.Timestamp(now) - pd.Timedelta(days=lookback)).to_pydatetime()
                    revisions.append({
                        "revision_id": _hash(snapshot_id, lookback),
                        "snapshot_id": snapshot_id,
                        "provider": "yfinance",
                        "prior_provider": "yfinance",
                        "entity_id": str(listing["entity_id"]),
                        "listing_id": str(listing["listing_id"]),
                        "financial_data_security_id": str(listing["financial_data_security_id"] or ""),
                        "canonical_ticker": str(listing["canonical_ticker"]),
                        "metric": "eps",
                        "fiscal_period": "quarterly" if horizon.endswith("q") else "annual",
                        "fiscal_year": align["fiscal_year"],
                        "estimate_period_end": align["estimate_period_end"],
                        "horizon": horizon,
                        "statistic": "mean",
                        "current_snapshot_at": now,
                        "current_value": current,
                        "current_analyst_count": _i(frame.loc[horizon].get("numberOfAnalysts")),
                        "current_dispersion": None,
                        "lookback_days": lookback,
                        "cutoff_at": cutoff,
                        "prior_snapshot_id": "",
                        "prior_snapshot_at": cutoff,
                        "prior_value": prior,
                        "prior_provider_asof": cutoff,
                        "provider_asof": now,
                        "retrieved_at_utc": now,
                        "source_url": YF_SOURCE_URL.format(symbol=symbol),
                        # The prior value is the provider restating history, not
                        # a vintage captured at the time. Never call it PIT.
                        "pit_class": "reconstructed_sparse",
                        "source_run_id": run_id,
                        "prior_analyst_count": None,
                        "revision_value": current - prior,
                        "revision_pct": ((current - prior) / abs(prior) * 100.0) if prior else None,
                        "analyst_count_change": None,
                        "dispersion": None,
                        "alignment_status": str(align["alignment_status"]),
                    })
    return snapshots, revisions, calls, notes


def collect_financial_data(
    listings: pd.DataFrame,
    mapping: pd.DataFrame,
    *,
    run_id: str,
    now: datetime,
) -> tuple[list[dict], list[str]]:
    """Read the akshare consensus already collected by the sibling repository."""
    files = sorted(FD_CONSENSUS.glob("source=akshare/**/*.parquet")) if FD_CONSENSUS.is_dir() else []
    if not files:
        return [], [f"no akshare consensus snapshot under {FD_CONSENSUS}"]
    frame = pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)
    siblings = _sibling_tickers(listings)
    by_ticker = {str(row["canonical_ticker"]): row for _, row in listings.iterrows()}
    snapshots: list[dict] = []
    notes: list[str] = []
    for _, row in frame.iterrows():
        listing = by_ticker.get(str(row.get("ticker")))
        if listing is None:
            continue
        snapshot_at = pd.Timestamp(row.get("snapshot_date"))
        if snapshot_at.tzinfo is None:
            snapshot_at = snapshot_at.tz_localize("UTC")
        for metric, column in (("eps", "eps_avg"), ("revenue", "revenue_avg")):
            value = _f(row.get(column))
            if value is None:
                continue
            horizon = str(row.get("horizon") or "")
            align = _alignment(mapping, str(listing["canonical_ticker"]), metric, horizon, siblings.get(str(listing["entity_id"]), ()))
            snapshots.append({
                "snapshot_id": _hash(run_id, "akshare", listing["listing_id"], metric, horizon, snapshot_at),
                "provider": "akshare",
                "entity_id": str(listing["entity_id"]),
                "listing_id": str(listing["listing_id"]),
                "financial_data_security_id": str(row.get("security_id") or ""),
                "canonical_ticker": str(listing["canonical_ticker"]),
                "metric": metric,
                "fiscal_period": "quarterly" if horizon.endswith("q") else "annual",
                "fiscal_year": align["fiscal_year"],
                "estimate_period_end": align["estimate_period_end"],
                "horizon": horizon,
                "snapshot_at": snapshot_at.to_pydatetime(),
                "value": value,
                "statistic": "mean",
                "low_value": _f(row.get("eps_low")) if metric == "eps" else None,
                "high_value": _f(row.get("eps_high")) if metric == "eps" else None,
                "analyst_count": None,
                "provider_contributor_count": None,
                "currency": str(row.get(f"{metric}_currency") or listing["currency"]),
                "unit": "currency_per_share" if metric == "eps" else "currency",
                "accounting_basis": "provider_reported_non_gaap_unverified",
                "provider_asof": snapshot_at.to_pydatetime(),
                "retrieved_at_utc": now,
                "source_url": "https://www.akshare.xyz/",
                "raw_hash": _hash(row.get("consensus_id"), value),
                "pit_class": "snapshot_from_delayed_source",
                "source_run_id": run_id,
                "calculation_origin": "sibling_repository_export",
                "coverage_reason": str(align["coverage_reason"]),
            })
    if not snapshots:
        notes.append("akshare consensus export held no rows for the configured listings")
    return snapshots, notes


def _as_frame(frame: pd.DataFrame | Sequence[Mapping[str, object]], schema: pa.Schema) -> pd.DataFrame:
    if isinstance(frame, pd.DataFrame):
        return frame[[field.name for field in schema]]
    return pd.DataFrame(list(frame), columns=[field.name for field in schema])


def _write(frame: pd.DataFrame | Sequence[Mapping[str, object]], schema: pa.Schema, path: Path) -> int:
    frame = _as_frame(frame, schema)
    path = Path(path)
    table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return len(frame)


def _write_atomic(
    frame: pd.DataFrame | Sequence[Mapping[str, object]],
    schema: pa.Schema,
    path: Path,
) -> int:
    """Write a parquet file atomically (temp file + ``os.replace``).

    The store is append-only lineage, so a torn write must never be observable
    at the final path -- the temp file is written to the same directory and
    atomically moved into place only once it is complete.
    """

    frame = _as_frame(frame, schema)
    path = Path(path)
    table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    os.close(descriptor)
    try:
        pq.write_table(table, tmp_path)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return len(frame)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--listings", type=Path, default=REPO_ROOT / "config/research_control_tower/listings.csv")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "data/normalized/research_control_tower/consensus")
    parser.add_argument("--basket", default=None, help="restrict to one basket_id from basket_memberships.csv")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    run_id = f"consensus-{uuid.uuid4()}"

    listings = pd.read_csv(args.listings, keep_default_na=False)
    listings = listings.loc[listings["listing_status"].astype(str).str.strip().eq("active")]
    if args.basket:
        memberships = pd.read_csv(args.listings.parent / "basket_memberships.csv", keep_default_na=False)
        members = set(memberships.loc[memberships["basket_id"].eq(args.basket), "entity_id"])
        listings = listings.loc[listings["entity_id"].isin(members)]
    listings = listings.assign(
        provider_symbol=listings["canonical_ticker"].astype(str).str.replace(r"\.US$", "", regex=True)
    )
    print(f"listings in scope: {len(listings)}  ({', '.join(listings['canonical_ticker'])})")

    mapping = load_period_mapping()
    print(f"period mapping rows from financial-data: {len(mapping)}")

    yf_snapshots, yf_revisions, calls, yf_notes = collect_yfinance(listings, mapping, run_id=run_id, now=now)
    fd_snapshots, fd_notes = collect_financial_data(listings, mapping, run_id=run_id, now=now)

    # Batch 7: merge the captured snapshots into the day-granular immutable
    # store, derive genuine revisions from consecutive captured vintages, and
    # export the FULL accumulated history (not just this run's rows).
    snapshots = yf_snapshots + fd_snapshots
    out = args.output_dir
    store_path = out / STORE_DIRNAME / STORE_FILENAME
    store = accumulate_snapshots(_read_store(store_path), snapshots, run_date=now.date())
    n_store = len(store)
    _write_atomic(store, TASK3_SNAPSHOT_ARROW_SCHEMA, store_path)

    genuine_revisions = derive_genuine_revisions(store)
    n_genuine = len(genuine_revisions)
    n_recon = len(yf_revisions)
    revisions = combine_revision_export(
        genuine_revisions,
        pd.DataFrame(yf_revisions, columns=REVISION_COLUMNS),
    )
    n_rev = len(revisions)

    def _store_rows(provider: str) -> pd.DataFrame:
        return store.loc[store["provider"].eq(provider)]

    def _latest_at(provider: str) -> pd.Timestamp:
        rows = _store_rows(provider)
        if rows.empty:
            return pd.Timestamp(now)
        return pd.Timestamp(rows["snapshot_at"].max())

    yf_store = _store_rows("yfinance")
    ak_store = _store_rows("akshare")
    n_yf_rev = int(revisions["provider"].eq("yfinance").sum())
    n_ak_rev = int(revisions["provider"].eq("akshare").sum())
    health = [
        {
            "provider": "yfinance",
            "status": "available" if not yf_store.empty else "unavailable",
            "reason": (
                ("; ".join(yf_notes) or "live analyst estimates collected")
                + f"; genuine_revisions={n_genuine}; reconstructed={n_recon}; store_vintages={n_store}"
            ),
            "row_count": len(yf_store) + n_yf_rev,
            "mapped_row_count": int(yf_store["fiscal_year"].notna().sum()),
            "latest_snapshot_at": _latest_at("yfinance"),
            "as_of": now,
            "network_calls": calls,
            "source_license_class": YF_LICENSE,
            "entitlement_status": "terms_unverified",
            "entitlement_evidence": "Yahoo Finance analyst estimates via yfinance; personal research use, no redistribution asserted",
            "entitlement_ref": "task3-provider-policy:sidecar-required-v1",
        },
        {
            "provider": "akshare",
            "status": "available" if not ak_store.empty else "unavailable",
            "reason": "; ".join(fd_notes) or f"akshare consensus export read from {FINANCIAL_DATA_ROOT.name}",
            "row_count": len(ak_store) + n_ak_rev,
            "mapped_row_count": int(ak_store["fiscal_year"].notna().sum()),
            "latest_snapshot_at": _latest_at("akshare"),
            "as_of": now,
            "network_calls": 0,
            "source_license_class": FD_LICENSE,
            "entitlement_status": "terms_unverified",
            "entitlement_evidence": "Sibling-repository export; collected by financial-data, not re-fetched here",
            "entitlement_ref": "task3-provider-policy:sidecar-required-v1",
        },
    ]

    n_snap = _write(
        snapshot_export_frame(store),
        TASK3_SNAPSHOT_ARROW_SCHEMA,
        out / "control_tower_consensus_snapshots.parquet",
    )
    _write(revisions, TASK3_REVISION_ARROW_SCHEMA, out / "control_tower_consensus_revisions.parquet")
    n_health = _write(health, TASK3_HEALTH_ARROW_SCHEMA, out / "control_tower_consensus_source_health.parquet")

    print(f"\nstore     : {n_store:>4d} vintages -> {store_path}")
    print(f"snapshots : {n_snap:>4d}  (full accumulated store history)")
    print(f"revisions : {n_rev:>4d}  (genuine {n_genuine} repository_captured, reconstructed {n_recon})")
    print(f"health    : {n_health:>4d}")
    aligned = sum(1 for row in snapshots if row["fiscal_year"] is not None)
    print(f"fiscal-period aligned: {aligned}/{len(snapshots)}")
    for note in yf_notes + fd_notes:
        print(f"  note: {note}")
    print(f"\noutput: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
