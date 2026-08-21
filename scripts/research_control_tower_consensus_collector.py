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
* The natural key / revision chaining key is
  ``(provider_series_id, listing_id, metric, horizon, statistic)``, keyed
  null-safely. Derived fiscal-period mapping labels (``fiscal_period``,
  ``fiscal_year``, ``estimate_period_end``) NEVER enter the key, so a
  corrected period mapping cannot break a revision chain (design spec:
  mapping labels never enter the chaining key). ``provider_series_id``
  is a stable per-provider series identity: ``yfinance:<ticker>:<metric>``
  for live estimates and ``akshare:<ticker>:<metric>:fiscal_year:<FY>``
  for the sibling relay, whose export carries one row per source fiscal
  year and no relative horizon — the source-reported fiscal year is the
  only stable series discriminator there.
* One vintage per natural key per UTC calendar day. A same-day rerun for
  the same key REPLACES that day's row (last-write-wins within the day),
  which makes scheduled daily collection idempotent; different days
  always append. Intra-day value changes are intentionally not retained —
  the cadence is daily, and ``snapshot_id`` is a deterministic hash of
  the natural key plus the UTC date so re-runs produce stable, joinable
  ids.
* Genuine revisions are derived from consecutive store vintages per
  natural key and carry ``pit_class="repository_captured"``.
  Reconstructed eps_trend rows remain as a labelled cold-start fallback;
  strict precedence applies — a chain with captured history suppresses
  its reconstructed rows — and the two classes are never blended or
  deduped against each other.
* Provider health is honest about freshness: a provider whose latest
  captured ``provider_asof`` falls outside its freshness window is
  reported ``stale`` (never ``available``), and an empty provider is
  ``unavailable``.


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

# Provider freshness windows (calendar days) for the health sidecar. The
# akshare relay is a delayed sibling-repository snapshot; 14 days matches
# the repository-wide ``task3_consensus_export_v1`` freshness threshold in
# ``src/research_control_tower/build.py``. yfinance estimates are collected
# live each run, so a 2-day window keeps health honest across weekends.
PROVIDER_FRESHNESS_SLA_DAYS = {"yfinance": 2, "akshare": 14}

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


def _as_utc(value: object) -> pd.Timestamp | None:
    """Coerce a provider timestamp to UTC, or None when missing/invalid."""

    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


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


def _provider_series_id(row: Mapping[str, object]) -> str:
    """Stable per-provider series identity, never a derived mapping label.

    yfinance: ``yfinance:<ticker>:<metric>`` (symbol + field). akshare:
    ``akshare:<ticker>:<metric>:fiscal_year:<FY>`` — the sibling export
    carries one row per source-reported fiscal year and no relative
    horizon, so the source fiscal year is the only stable discriminator
    between the rows. A corrected period mapping therefore never changes
    the identity of an existing series.
    """

    provider = _key_part(row.get("provider"))
    ticker = _key_part(row.get("canonical_ticker"))
    metric = _key_part(row.get("metric"))
    if provider == "akshare":
        return "\x1f".join((provider, ticker, metric, "fiscal_year", _key_part(row.get("fiscal_year"))))
    return "\x1f".join((provider, ticker, metric))


def snapshot_natural_key(row: Mapping[str, object]) -> tuple[str, ...]:
    """The store natural key / revision chaining key for a snapshot row.

    ``(provider_series_id, listing_id, metric, horizon, statistic)`` with
    NULL-safe parts (see :func:`_key_part`). Derived fiscal-period mapping
    labels (``fiscal_period`` / ``fiscal_year`` / ``estimate_period_end``)
    are deliberately excluded: the design spec keys vintage pairing on the
    stable series identity, and mapping changes must never split a chain.
    """

    return (
        _provider_series_id(row),
        _key_part(row.get("listing_id")),
        _key_part(row.get("metric")),
        _key_part(row.get("horizon")),
        _key_part(row.get("statistic")),
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
    # Last-write-wins within (natural key, UTC day): sort by provider_asof/retrieved_at_utc/snapshot_at
    # so newest timestamp deterministically wins regardless of ingestion order.
    merged = merged.sort_values(
        ["provider_asof", "retrieved_at_utc", "snapshot_at"],
        kind="mergesort",
        na_position="first",
    )
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


def _revision_chain_key(row: Mapping[str, object]) -> tuple[str, ...]:
    """The series chain a revision row belongs to.

    Matches the snapshot natural key: ``(provider_series_id, listing_id,
    metric, horizon, statistic)`` with NULL-safe parts, so a reconstructed
    row can be checked against the same chain a genuine revision covers.
    """

    return (
        _provider_series_id(row),
        _key_part(row.get("listing_id")),
        _key_part(row.get("metric")),
        _key_part(row.get("horizon")),
        _key_part(row.get("statistic")),
    )


def _reconstructed_revision_row(
    snapshot: Mapping[str, object],
    *,
    prior_value: object,
    lookback_days: int,
    now: datetime,
    alignment_status: str,
) -> dict[str, object]:
    """One yfinance eps_trend reconstructed revision, consistent with its snapshot.

    The snapshots mart and the revisions mart must agree on the current
    figure: ``current_value`` is the snapshot's own ``value`` (the mean the
    snapshots export shows) and ``snapshot_id`` is the snapshot's stable id,
    so a rerun can never desynchronize the two marts. The prior side comes
    from the provider's retrospective restatement and stays
    ``reconstructed_sparse`` -- cold-start context only, never PIT.
    """

    current_value = _f(snapshot.get("value"))
    prior = _f(prior_value)
    revision_value: float | None = (
        None if current_value is None or prior is None else current_value - prior
    )
    revision_pct: float | None = (
        revision_value / abs(prior)
        if revision_value is not None and prior not in (None, 0)
        else None
    )
    cutoff = (pd.Timestamp(now) - pd.Timedelta(days=lookback_days)).to_pydatetime()
    return {
        "revision_id": _hash(snapshot.get("snapshot_id"), lookback_days),
        "snapshot_id": str(snapshot.get("snapshot_id")),
        "provider": "yfinance",
        "prior_provider": "yfinance",
        "entity_id": str(snapshot.get("entity_id")),
        "listing_id": str(snapshot.get("listing_id")),
        "financial_data_security_id": str(snapshot.get("financial_data_security_id") or ""),
        "canonical_ticker": str(snapshot.get("canonical_ticker")),
        "metric": "eps",
        "fiscal_period": _key_part(snapshot.get("fiscal_period")),
        "fiscal_year": _i(snapshot.get("fiscal_year")),
        "estimate_period_end": snapshot.get("estimate_period_end"),
        "horizon": _key_part(snapshot.get("horizon")),
        "statistic": _key_part(snapshot.get("statistic")),
        "current_snapshot_at": snapshot.get("snapshot_at"),
        "current_value": current_value,
        "current_analyst_count": _i(snapshot.get("analyst_count")),
        "current_dispersion": None,
        "lookback_days": lookback_days,
        "cutoff_at": cutoff,
        "prior_snapshot_id": "",
        "prior_snapshot_at": cutoff,
        "prior_value": prior,
        "prior_provider_asof": cutoff,
        "provider_asof": snapshot.get("provider_asof"),
        "retrieved_at_utc": snapshot.get("retrieved_at_utc"),
        "source_url": str(snapshot.get("source_url")),
        "pit_class": "reconstructed_sparse",
        "source_run_id": str(snapshot.get("source_run_id")),
        "prior_analyst_count": None,
        "revision_value": revision_value,
        "revision_pct": revision_pct,
        "analyst_count_change": None,
        "dispersion": None,
        "alignment_status": str(alignment_status),
    }


def combine_revision_export(
    genuine: pd.DataFrame,
    reconstructed: pd.DataFrame,
) -> pd.DataFrame:
    """Combine genuine and reconstructed revisions for export.

    Strict precedence: reconstructed rows for a chain that already carries
    genuine ``repository_captured`` history are suppressed (cold-start
    display only), while rows for uncovered chains survive to give the
    panel a cold start. Remaining ordering: genuine first (most recent
    ``current_snapshot_at`` first), then the surviving reconstructed rows in
    their original order. The two classes are never blended or deduped
    against each other -- suppressed rows are removed, surviving rows keep
    their labels and order.
    """

    genuine = genuine.sort_values("current_snapshot_at", ascending=False, kind="mergesort")
    if not reconstructed.empty and not genuine.empty:
        covered = {
            "\x1f".join(_revision_chain_key(row))
            for _, row in genuine.iterrows()
        }
        keys = [
            "\x1f".join(_revision_chain_key(row))
            for _, row in reconstructed.iterrows()
        ]
        reconstructed = reconstructed.loc[
            [key not in covered for key in keys]
        ].copy()
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
                   alignment_quality, confidence, period_kind
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


def _fiscal_year_end_anchor(
    mapping: pd.DataFrame,
    ticker: str,
    sibling_tickers: tuple[str, ...] = (),
) -> dict[str, object]:
    """Issuer fiscal year-end (month, day) from the mapping's annual anchors.

    The mapping keys yfinance horizons, but the fiscal calendar belongs to
    the issuer: the most common (month, day) among ``period_kind="annual"``
    mapped period ends (e.g. 0700.HK -> 12-31, 9988.HK -> 03-31) is the
    calendar used to turn an akshare source fiscal year into a period end.
    Returns ``{}`` when the mapping carries no usable annual anchor.
    """

    if mapping is None or mapping.empty or "period_kind" not in mapping.columns:
        return {}
    counts: dict[tuple[int, int], int] = {}
    confidences: dict[tuple[int, int], list[str]] = {}
    borrowed_from = ""
    for candidate in (ticker, *[other for other in sibling_tickers if other != ticker]):
        rows = mapping.loc[mapping["ticker"].eq(candidate)]
        annual = rows.loc[rows["period_kind"].eq("annual")]
        for _, row in annual.iterrows():
            end = row.get("mapped_period_end")
            if end is None or pd.isna(end):
                continue
            ts = pd.Timestamp(end)
            if pd.isna(ts):
                continue
            key = (ts.month, ts.day)
            counts[key] = counts.get(key, 0) + 1
            confidences.setdefault(key, []).append(str(row.get("confidence") or "unknown"))
            if candidate != ticker:
                borrowed_from = candidate
    if not counts:
        return {}
    (month, day), _ = max(counts.items(), key=lambda item: item[1])
    order = {"high": 2, "medium": 1, "low": 0}
    confidence = max(confidences[(month, day)], key=lambda c: order.get(c, -1))
    return {"month": month, "day": day, "confidence": confidence, "borrowed_from": borrowed_from}


def _align_akshare(
    mapping: pd.DataFrame,
    ticker: str,
    metric: str,
    source_fiscal_year: int | None,
    sibling_tickers: tuple[str, ...] = (),
) -> dict[str, object]:
    """Period alignment for an akshare relay row.

    The sibling export reports one row per source fiscal year with no
    relative horizon, so the source-reported ``fiscal_year`` is the period
    identity. When the issuer's annual calendar is derivable, a period end
    is derived from it; otherwise the fiscal year is kept and the period
    end stays null (never guessed).
    """

    if source_fiscal_year is None:
        return {
            "fiscal_year": None,
            "estimate_period_end": None,
            "alignment_status": "unaligned_no_source_fiscal_year",
            "coverage_reason": "akshare export row carries no fiscal year",
        }
    anchor = _fiscal_year_end_anchor(mapping, ticker, sibling_tickers)
    if not anchor:
        return {
            "fiscal_year": source_fiscal_year,
            "estimate_period_end": None,
            "alignment_status": "source_fiscal_year_no_calendar",
            "coverage_reason": "fiscal year from akshare export; no issuer annual calendar in consensus_period_mapping to derive a period end",
        }
    try:
        period_end = date(source_fiscal_year, int(anchor["month"]), int(anchor["day"]))
    except ValueError:
        period_end = None
    status = "source_fiscal_year_calendared_confidence_" + str(anchor["confidence"])
    borrowed = str(anchor.get("borrowed_from") or "")
    if borrowed:
        status = status + "_via_" + borrowed
    return {
        "fiscal_year": source_fiscal_year,
        "estimate_period_end": period_end,
        "alignment_status": status,
        "coverage_reason": (
            "fiscal year from akshare export; period end derived from issuer annual calendar"
            + (" via same-issuer listing " + borrowed if borrowed else "")
            + (": " + period_end.isoformat() if period_end is not None else ": unavailable")
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
                analyst_count = _i(row.get("numberOfAnalysts"))
                snapshot = {
                    "snapshot_id": "",  # stable id computed below
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
                    "analyst_count": analyst_count,
                    "provider_contributor_count": analyst_count,
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
                }
                snapshot["snapshot_id"] = stable_snapshot_id(snapshot, now.date())
                snapshots.append(snapshot)

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
                    revisions.append(
                        _reconstructed_revision_row(
                            snapshot,
                            prior_value=prior,
                            lookback_days=lookback,
                            now=now,
                            alignment_status=str(align["alignment_status"]),
                        )
                    )
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
        snapshot_at = _as_utc(row.get("snapshot_date"))
        if snapshot_at is None:
            continue
        # The sibling's fetch timestamp is the true provider-as-of; the
        # snapshot date alone would understate freshness by a day.
        provider_asof = _as_utc(row.get("fetched_at")) or snapshot_at
        now_utc = _as_utc(now) or pd.Timestamp.now(tz="UTC")
        if snapshot_at > now_utc or provider_asof > now_utc:
            notes.append(
                f"excluded future-dated sibling row for {listing['canonical_ticker']} "
                f"(snapshot_at={snapshot_at.isoformat()}, provider_asof={provider_asof.isoformat()}, as_of={now_utc.isoformat()})"
            )
            continue
        for metric, column in (("eps", "eps_avg"), ("revenue", "revenue_avg")):
            value = _f(row.get(column))
            if value is None:
                continue
            horizon = str(row.get("horizon") or "")
            align = _align_akshare(
                mapping,
                str(listing["canonical_ticker"]),
                metric,
                _i(row.get("fiscal_year")),
                siblings.get(str(listing["entity_id"]), ()),
            )
            snapshot = {
                "snapshot_id": "",  # stable id computed below
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
                "provider_asof": provider_asof.to_pydatetime(),
                "retrieved_at_utc": now,
                "source_url": "https://www.akshare.xyz/",
                "raw_hash": _hash(row.get("consensus_id"), value),
                "pit_class": "snapshot_from_delayed_source",
                "source_run_id": run_id,
                "calculation_origin": "sibling_repository_export",
                "coverage_reason": str(align["coverage_reason"]),
            }
            snapshot["snapshot_id"] = stable_snapshot_id(snapshot, snapshot_at.date())
            snapshots.append(snapshot)
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


def _provider_freshness_status(
    provider_rows: pd.DataFrame,
    sla_days: int,
    now: datetime,
) -> tuple[str, str]:
    """Honest freshness status for one provider's store rows.

    ``available`` while the newest captured ``provider_asof`` sits inside
    the provider's freshness window; ``stale`` when it falls outside (the
    rows are still exported, but health must never call them available);
    ``unavailable`` for an empty input (callers handle the empty-store
    branch, this helper keeps the wording consistent).
    """

    if provider_rows is None or provider_rows.empty:
        return ("unavailable", "no vintages in store")
    asof_values = provider_rows["provider_asof"].dropna()
    if asof_values.empty:
        latest = provider_rows["snapshot_at"].dropna().max()
    else:
        latest = asof_values.max()
    latest_ts = pd.Timestamp(latest)
    if pd.isna(latest_ts):
        return ("stale", "latest provider_asof unavailable; freshness cannot be established")
    now_ts = pd.Timestamp(now)
    if now_ts.tzinfo is None and latest_ts.tzinfo is not None:
        now_ts = now_ts.tz_localize("UTC")
    elif now_ts.tzinfo is not None and latest_ts.tzinfo is None:
        latest_ts = latest_ts.tz_localize("UTC")
    if latest_ts > now_ts:
        return (
            "fail_closed_future_dated",
            f"provider_asof {latest_ts.isoformat()} is in the future relative to as_of {now_ts.isoformat()}",
        )
    age_days = (now_ts - latest_ts).days
    if age_days > sla_days:
        return (
            "stale",
            f"provider_asof {latest_ts.isoformat()} is {age_days}d older than as_of (freshness window {sla_days}d)",
        )
    return ("available", "")


def build_provider_health_rows(
    store: pd.DataFrame,
    revisions: pd.DataFrame,
    *,
    now: datetime,
    yf_notes: Sequence[str],
    fd_notes: Sequence[str],
    calls: int,
) -> list[dict[str, object]]:
    """Health sidecar rows with availability AND freshness semantics.

    A provider whose latest captured ``provider_asof`` is outside its
    freshness window is reported ``stale`` (never ``available``); an empty
    provider is ``unavailable``. Run counters are appended to every reason
    so the source page can explain both the data and the derivation.
    """

    defaults = {
        "yfinance": "live analyst estimates collected",
        "akshare": f"akshare consensus export read from {FINANCIAL_DATA_ROOT.name}",
    }
    notes = {"yfinance": yf_notes, "akshare": fd_notes}
    licenses = {"yfinance": YF_LICENSE, "akshare": FD_LICENSE}
    evidence = {
        "yfinance": "Yahoo Finance analyst estimates via yfinance; personal research use, no redistribution asserted",
        "akshare": "Sibling-repository export; collected by financial-data, not re-fetched here",
    }
    rows: list[dict[str, object]] = []
    for provider in ("yfinance", "akshare"):
        provider_store = store.loc[store["provider"].eq(provider)] if not store.empty else store.iloc[0:0]
        provider_revisions = revisions.loc[revisions["provider"].eq(provider)] if not revisions.empty else revisions.iloc[0:0]
        provider_notes = [str(note) for note in (notes[provider] or ())]
        base = (
            "; ".join(provider_notes)
            if provider_notes
            else "no vintages in store" if provider_store.empty else defaults[provider]
        )
        status, freshness = _provider_freshness_status(provider_store, PROVIDER_FRESHNESS_SLA_DAYS[provider], now)
        reason_parts = [base]
        if not provider_store.empty and freshness:
            reason_parts.append(freshness)
        reason = "; ".join(reason_parts)
        prov_genuine = int((provider_revisions["pit_class"].eq("repository_captured")).sum()) if not provider_revisions.empty else 0
        prov_recon = int((provider_revisions["pit_class"].eq("reconstructed_sparse")).sum()) if not provider_revisions.empty else 0
        reason += f"; genuine_revisions={prov_genuine}; reconstructed={prov_recon}; store_vintages={len(provider_store)}"
        latest_snapshot_at = (
            pd.Timestamp(provider_store["snapshot_at"].max())
            if not provider_store.empty
            else (_as_utc(now) or pd.Timestamp.now(tz="UTC"))
        )
        rows.append({
            "provider": provider,
            "status": status,
            "reason": reason,
            "row_count": len(provider_store) + len(provider_revisions),
            "mapped_row_count": int(provider_store["fiscal_year"].notna().sum()) if not provider_store.empty else 0,
            "latest_snapshot_at": latest_snapshot_at,
            "as_of": now,
            "network_calls": calls if provider == "yfinance" else 0,
            "source_license_class": licenses[provider],
            "entitlement_status": "terms_unverified",
            "entitlement_evidence": evidence[provider],
            "entitlement_ref": "task3-provider-policy:sidecar-required-v1",
        })
    return rows


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

    health = build_provider_health_rows(
        store,
        revisions,
        now=now,
        yf_notes=yf_notes,
        fd_notes=fd_notes,
        calls=calls,
    )

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
