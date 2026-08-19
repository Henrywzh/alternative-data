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
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sys
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
    return pd.concat(
        [genuine[REVISION_COLUMNS], reconstructed[REVISION_COLUMNS]],
        ignore_index=True,
    )


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


# ---------------------------------------------------------------------------
# Batch 6/7: day-granular immutable snapshot store + genuine revisions
# ---------------------------------------------------------------------------

# Storage dedupe key (includes fiscal fields so different mappings coexist).
NATURAL_KEY_COLUMNS = (
    "provider",
    "listing_id",
    "metric",
    "horizon",
    "statistic",
    "fiscal_period",
    "fiscal_year",
    "estimate_period_end",
)

# Revision chaining key (fixed provider estimate identity).  Deliberately
# EXCLUDES fiscal_year/estimate_period_end: the sibling financial-data
# mapping can improve over time, and chaining on mapped fields would split a
# continuous estimate series into two buckets (null-keyed then mapped) and
# silently break the revision chain (design-review condition 2).
SERIES_IDENTITY_COLUMNS = (
    "provider",
    "listing_id",
    "metric",
    "horizon",
    "statistic",
)

SNAPSHOT_STORE_COLUMNS = (
    "snapshot_id",
    "provider",
    "entity_id",
    "listing_id",
    "financial_data_security_id",
    "canonical_ticker",
    "metric",
    "fiscal_period",
    "fiscal_year",
    "estimate_period_end",
    "horizon",
    "snapshot_at",
    "value",
    "statistic",
    "low_value",
    "high_value",
    "analyst_count",
    "provider_contributor_count",
    "currency",
    "unit",
    "accounting_basis",
    "provider_asof",
    "retrieved_at_utc",
    "source_url",
    "raw_hash",
    "pit_class",
    "source_run_id",
    "calculation_origin",
    "coverage_reason",
)


def _nk(value: object) -> str:
    """Null-safe string form of a key component."""

    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def _natural_key(row: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(_nk(row.get(column)) for column in NATURAL_KEY_COLUMNS)


def _series_identity(row: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(_nk(row.get(column)) for column in SERIES_IDENTITY_COLUMNS)


def _utc_day(value: object) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC").strftime("%Y-%m-%d")


def _store_snapshot_id(key: tuple[str, ...], utc_day: str) -> str:
    """Deterministic vintage id: stable across same-day re-runs, joinable."""

    return _hash("vintage", *key, utc_day)


def _empty_store_frame() -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in dict.fromkeys(SNAPSHOT_STORE_COLUMNS)})


def load_store(store_path: Path) -> pd.DataFrame:
    if not store_path.is_file():
        return _empty_store_frame()
    try:
        frame = pd.read_parquet(store_path)
    except Exception:
        return _empty_store_frame()
    columns = list(dict.fromkeys(SNAPSHOT_STORE_COLUMNS))
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        return _empty_store_frame()
    return frame.loc[:, columns]


def _atomic_write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def accumulate_snapshots(
    store: pd.DataFrame,
    new_rows: Sequence[Mapping[str, object]],
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Merge captured snapshots into the day-granular immutable store.

    Storage dedupe: one vintage per FULL natural key per UTC day (same-day
    rerun replaces that key's row for the day; different days append).  Past
    dates are never touched when the collector runs on a later date.
    ``snapshot_id`` becomes the deterministic hash(natural key + UTC date).
    """

    working = _empty_store_frame() if store is None or store.empty else store.copy()
    id_remap: dict[str, str] = {}
    index: dict[tuple[tuple[str, ...], str], int] = {}
    for position in range(len(working)):
        row = working.iloc[position]
        index[(_natural_key(row), _utc_day(row.get("snapshot_at")))] = position

    for raw in new_rows:
        row = {column: raw.get(column) for column in dict.fromkeys(SNAPSHOT_STORE_COLUMNS)}
        key = _natural_key(row)
        day = _utc_day(row.get("snapshot_at"))
        new_id = _store_snapshot_id(key, day)
        old_id = _nk(row.get("snapshot_id"))
        if old_id and old_id != new_id:
            id_remap[old_id] = new_id
        row["snapshot_id"] = new_id
        position = index.get((key, day))
        if position is None:
            index[(key, day)] = len(working)
            if working.empty:
                working = pd.DataFrame([row], columns=list(dict.fromkeys(SNAPSHOT_STORE_COLUMNS)))
            else:
                working = pd.concat(
                    [working, pd.DataFrame([row], columns=list(working.columns))],
                    ignore_index=True,
                )
        else:
            for column in working.columns:
                working.iat[position, working.columns.get_loc(column)] = row.get(column)

    if working.empty:
        return _empty_store_frame(), id_remap
    working = working.sort_values(
        ["listing_id", "provider", "metric", "horizon", "statistic", "snapshot_at"],
        kind="mergesort",
    ).reset_index(drop=True)
    return working, id_remap


def derive_genuine_revisions(store: pd.DataFrame) -> list[dict]:
    """Derive PIT revisions from consecutive CAPTURED store vintages.

    Chaining groups by the fixed 5-field series identity (provider, listing,
    metric, horizon, statistic) -- NOT the mapped fiscal fields -- so a
    mapping improvement never splits a revision chain.  Fiscal metadata on
    each revision row comes from the newer (current) vintage.
    """

    revisions: list[dict] = []
    if store is None or store.empty:
        return revisions
    working = store.copy()
    working["_series"] = working.apply(lambda row: _series_identity(row), axis=1)
    for _, group in working.groupby("_series", sort=False):
        ordered = group.sort_values("snapshot_at", kind="mergesort")
        rows = list(ordered.to_dict("records"))
        for prior, current in zip(rows, rows[1:]):
            prior_value = _f(prior.get("value"))
            current_value = _f(current.get("value"))
            if prior_value is None or current_value is None:
                continue
            current_at = pd.Timestamp(current["snapshot_at"])
            prior_at = pd.Timestamp(prior["snapshot_at"])
            prior_count = _i(prior.get("analyst_count"))
            current_count = _i(current.get("analyst_count"))
            revisions.append({
                "revision_id": _hash(str(current["snapshot_id"]), str(prior["snapshot_id"])),
                "snapshot_id": str(current["snapshot_id"]),
                "provider": str(current["provider"]),
                "prior_provider": str(prior["provider"]),
                "entity_id": str(current.get("entity_id") or ""),
                "listing_id": str(current.get("listing_id") or ""),
                "financial_data_security_id": str(current.get("financial_data_security_id") or ""),
                "canonical_ticker": str(current.get("canonical_ticker") or ""),
                "metric": str(current["metric"]),
                "fiscal_period": _nk(current.get("fiscal_period")),
                "fiscal_year": current.get("fiscal_year"),
                "estimate_period_end": current.get("estimate_period_end"),
                "horizon": str(current["horizon"]),
                "statistic": str(current.get("statistic") or "mean"),
                "current_snapshot_at": current_at.to_pydatetime(),
                "current_value": current_value,
                "current_analyst_count": current_count,
                "current_dispersion": None,
                "lookback_days": int((current_at.normalize() - prior_at.normalize()).days),
                "cutoff_at": prior_at.to_pydatetime(),
                "prior_snapshot_id": str(prior["snapshot_id"]),
                "prior_snapshot_at": prior_at.to_pydatetime(),
                "prior_value": prior_value,
                "prior_provider_asof": prior.get("provider_asof"),
                "provider_asof": current.get("provider_asof"),
                "retrieved_at_utc": current.get("retrieved_at_utc"),
                "source_url": str(current.get("source_url") or ""),
                "pit_class": "repository_captured",
                "source_run_id": str(current.get("source_run_id") or ""),
                "prior_analyst_count": prior_count,
                "revision_value": current_value - prior_value,
                "revision_pct": (
                    (current_value - prior_value) / abs(prior_value) * 100.0
                    if prior_value
                    else None
                ),
                "analyst_count_change": (
                    current_count - prior_count
                    if current_count is not None and prior_count is not None
                    else None
                ),
                "dispersion": None,
                "alignment_status": "",
            })
    revisions.sort(
        key=lambda row: (
            str(row["listing_id"]),
            str(row["provider"]),
            str(row["metric"]),
            str(row["horizon"]),
            -pd.Timestamp(row["current_snapshot_at"]).value,
        )
    )
    return revisions


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
    store_path = args.output_dir / "store" / "snapshots_store.parquet"
    store = load_store(store_path)
    store, _id_remap = accumulate_snapshots(store, yf_snapshots + fd_snapshots)
    _atomic_write_parquet(store, store_path)
    genuine_revisions = derive_genuine_revisions(store)

    snapshots = store.to_dict("records")
    revisions = genuine_revisions + yf_revisions
    health = [
        {
            "provider": "yfinance",
            "status": "available" if yf_snapshots else "unavailable",
            "reason": (
                "; ".join(yf_notes)
                or f"live analyst estimates collected; genuine_revisions={len(genuine_revisions)}; "
                f"reconstructed={len(yf_revisions)}; store_vintages={len(store)}"
            ),
            "row_count": len(snapshots) + len(revisions),
            "mapped_row_count": sum(1 for row in yf_snapshots if row["fiscal_year"] is not None),
            "latest_snapshot_at": now,
            "as_of": now,
            "network_calls": calls,
            "source_license_class": YF_LICENSE,
            "entitlement_status": "terms_unverified",
            "entitlement_evidence": "Yahoo Finance analyst estimates via yfinance; personal research use, no redistribution asserted",
            "entitlement_ref": "task3-provider-policy:sidecar-required-v1",
        },
        {
            "provider": "akshare",
            "status": "available" if fd_snapshots else "unavailable",
            "reason": (
                "; ".join(fd_notes)
                or f"akshare consensus export read from {FINANCIAL_DATA_ROOT.name}; "
                f"store_vintages={len(store)}"
            ),
            "row_count": len(fd_snapshots),
            "mapped_row_count": sum(1 for row in fd_snapshots if row["fiscal_year"] is not None),
            "latest_snapshot_at": max((row["snapshot_at"] for row in fd_snapshots), default=now),
            "as_of": now,
            "network_calls": 0,
            "source_license_class": FD_LICENSE,
            "entitlement_status": "terms_unverified",
            "entitlement_evidence": "Sibling-repository export; collected by financial-data, not re-fetched here",
            "entitlement_ref": "task3-provider-policy:sidecar-required-v1",
        },
    ]

    out = args.output_dir
    n_snap = _write(snapshots, TASK3_SNAPSHOT_ARROW_SCHEMA, out / "control_tower_consensus_snapshots.parquet")
    n_rev = _write(revisions, TASK3_REVISION_ARROW_SCHEMA, out / "control_tower_consensus_revisions.parquet")
    n_health = _write(health, TASK3_HEALTH_ARROW_SCHEMA, out / "control_tower_consensus_source_health.parquet")

    print(f"\nstore     : {len(store)} vintages -> {store_path}")
    print(f"snapshots : {n_snap:>4d}  (full accumulated history)")
    print(f"revisions : {n_rev:>4d}  (genuine {len(genuine_revisions)} repository_captured + {len(yf_revisions)} reconstructed)")
    print(f"health    : {n_health:>4d}")
    aligned = sum(1 for row in snapshots if row["fiscal_year"] is not None)
    print(f"fiscal-period aligned: {aligned}/{len(snapshots)}")
    for note in yf_notes + fd_notes:
        print(f"  note: {note}")
    print(f"\noutput: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
