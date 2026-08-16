"""Pure functional helpers for normalizing market bars and quote snapshots.

This module provides contract-compliant normalization, listing identity crosswalk
mapping, quote freshness classification, and future-timestamp / NaN validation.
It operates as a pure data utility and does not touch global models or app UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Literal, Mapping, Sequence

import pandas as pd


MarketDataFreshness = Literal["live", "delayed", "stale", "unavailable"]

MARKET_BARS_COLUMNS = (
    "bar_id",
    "listing_id",
    "canonical_ticker",
    "interval",
    "timestamp_utc",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "source_id",
    "source_url",
    "retrieved_at_utc",
    "pit_class",
    "source_license_class",
    "registry_version",
)

QUOTE_SNAPSHOT_COLUMNS = (
    "quote_id",
    "listing_id",
    "canonical_ticker",
    "provider_symbol",
    "quote_timestamp",
    "retrieved_at_utc",
    "last_price",
    "bid",
    "ask",
    "day_change_pct",
    "volume",
    "currency",
    "market_status",
    "latency_class",
    "source_id",
    "source_url",
    "pit_class",
    "source_license_class",
    "registry_version",
)


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    frame: pd.DataFrame
    valid_count: int
    unmapped_count: int
    future_count: int
    invalid_count: int
    issues: tuple[str, ...] = ()
    dropped_duplicate_count: int = 0


def _text(val: object) -> str:
    if val is None or val is pd.NA:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    return str(val).strip()


def _float_or_none(val: object) -> float | None:
    if val is None or val is pd.NA:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    try:
        res = float(val)
        return None if pd.isna(res) or not math.isfinite(res) else res
    except (TypeError, ValueError, OverflowError):
        return None


def _to_utc_timestamp(val: object) -> pd.Timestamp | None:
    if val is None or val is pd.NaT:
        return None
    try:
        ts = pd.Timestamp(val)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None or ts.utcoffset() is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts


def _first_present(row: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        value = row.get(key)
        if value is None or value is pd.NA or value is pd.NaT:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        try:
            if bool(pd.isna(value)):
                continue
        except (TypeError, ValueError):
            pass
        return value
    return None


def _vendor_symbols(row: Mapping[str, Any]) -> tuple[str, ...]:
    raw = _text(row.get("vendor_tickers"))
    if not raw:
        return ()
    return tuple(
        symbol.strip()
        for token in raw.split(";")
        for _, separator, symbol in [token.partition(":")]
        if separator and symbol.strip()
    )


def _empty_frame(columns: Sequence[str]) -> pd.DataFrame:
    timestamp_columns = {
        "timestamp_utc", "retrieved_at_utc", "quote_timestamp",
    }
    float_columns = {
        "open", "high", "low", "close", "adj_close", "volume",
        "last_price", "bid", "ask", "day_change_pct",
    }
    dtypes = {
        column: (
            "datetime64[ns, UTC]" if column in timestamp_columns
            else "Float64" if column in float_columns
            else "string"
        )
        for column in columns
    }
    return pd.DataFrame({column: pd.Series(dtype=dtype) for column, dtype in dtypes.items()})


def _build_listing_crosswalk_with_conflicts(
    listings: pd.DataFrame,
) -> tuple[dict[str, tuple[str, str]], set[str]]:
    """Build a crosswalk and remove identifiers that map to multiple listings."""
    crosswalk: dict[str, tuple[str, str]] = {}
    conflicted: set[str] = set()
    if listings is None or listings.empty:
        return crosswalk, conflicted

    def add_mapping(key: str, target: tuple[str, str]) -> None:
        if not key or key in conflicted:
            return
        previous = crosswalk.get(key)
        if previous is None:
            crosswalk[key] = target
        elif previous != target:
            # A ticker/security identifier shared by two listings is unsafe to
            # resolve implicitly.  Remove it instead of silently first-winning.
            conflicted.add(key)
            crosswalk.pop(key, None)

    for _, row in listings.iterrows():
        lid = _text(row.get("listing_id"))
        ctick = _text(row.get("canonical_ticker"))
        sec_id = _text(row.get("financial_data_security_id"))
        native = _text(row.get("native_ticker"))

        if lid:
            target = (lid, ctick)
            for key in (lid, sec_id, ctick, native):
                add_mapping(key, target)
    return crosswalk, conflicted


def build_listing_crosswalk(listings: pd.DataFrame) -> dict[str, tuple[str, str]]:
    """Build a mapping dict from identifiers to ``(listing_id, canonical_ticker)``.

    Ambiguous identifiers are omitted so callers cannot accidentally attach a
    row to the wrong exchange listing.
    """
    crosswalk, _ = _build_listing_crosswalk_with_conflicts(listings)
    return crosswalk


def resolve_listing_identity(
    row: Mapping[str, Any] | pd.Series,
    crosswalk: Mapping[str, tuple[str, str]],
) -> tuple[str | None, str]:
    """Resolve listing_id and canonical_ticker for a row using the crosswalk map."""
    lid = _text(row.get("listing_id"))
    if lid:
        # An explicit but unknown listing_id is a hard identity failure.  Do
        # not silently remap it using a ticker/security fallback.
        return crosswalk.get(lid, (None, ""))

    sec_id = _text(row.get("financial_data_security_id")) or _text(row.get("security_id"))
    if sec_id and sec_id in crosswalk:
        return crosswalk[sec_id]

    ticker = _text(row.get("canonical_ticker")) or _text(row.get("provider_symbol")) or _text(row.get("ticker"))
    if ticker and ticker in crosswalk:
        return crosswalk[ticker]

    native = _text(row.get("native_ticker"))
    if native and native in crosswalk:
        return crosswalk[native]

    return None, ""


def classify_quote_freshness(
    quote_timestamp: object,
    as_of_utc: object,
    latency_class: str | None = None,
    max_live_age: pd.Timedelta = pd.Timedelta(minutes=2),
    max_delayed_age: pd.Timedelta = pd.Timedelta(hours=24),
) -> MarketDataFreshness:
    """Determine quote freshness category (live, delayed, stale, or unavailable)."""
    quote_ts = _to_utc_timestamp(quote_timestamp)
    as_of_ts = _to_utc_timestamp(as_of_utc)

    if quote_ts is None or as_of_ts is None:
        return "unavailable"

    if quote_ts > as_of_ts:
        return "unavailable"

    age = as_of_ts - quote_ts
    if age < pd.Timedelta(0):
        return "unavailable"

    latency = _text(latency_class).lower()

    if latency in {"realtime", "live", "real_time"}:
        if age <= max_live_age:
            return "live"
        elif age <= max_delayed_age:
            return "delayed"
        else:
            return "stale"
    elif latency == "delayed":
        if age <= max_delayed_age:
            return "delayed"
        else:
            return "stale"
    else:
        # Without an explicit provider latency declaration, freshness is not
        # safe to label as delayed or live.
        return "unavailable"


def normalize_market_bars(
    input_data: pd.DataFrame | Sequence[Mapping[str, Any]],
    listings: pd.DataFrame,
    *,
    as_of_utc: object,
    source_id: str = "market_bars",
    source_url: str = "",
    pit_class: str = "snapshot_from_live_source",
    license_class: str = "personal_use_terms_unverified",
    registry_version: str = "v1",
) -> NormalizationResult:
    """Normalize input price bars against the listing registry and as_of_utc gate."""
    as_of_ts = _to_utc_timestamp(as_of_utc)
    if as_of_ts is None:
        raise ValueError("as_of_utc must be a valid timestamp")

    if isinstance(input_data, pd.DataFrame):
        rows = input_data.to_dict("records") if not input_data.empty else []
    else:
        rows = list(input_data)

    crosswalk, conflicted_keys = _build_listing_crosswalk_with_conflicts(listings)
    valid_rows: list[dict[str, Any]] = []
    unmapped_count = 0
    future_count = 0
    invalid_count = 0
    missing_retrieved_count = 0
    issues: list[str] = []

    for row in rows:
        lid, ctick = resolve_listing_identity(row, crosswalk)
        if not lid:
            unmapped_count += 1
            continue

        ts_raw = _first_present(row, "timestamp_utc", "timestamp", "date")
        ts = _to_utc_timestamp(ts_raw)
        if ts is None:
            invalid_count += 1
            continue
        if ts > as_of_ts:
            future_count += 1
            continue

        retrieved = _to_utc_timestamp(
            _first_present(row, "retrieved_at_utc", "fetched_at")
        )
        if retrieved is None:
            missing_retrieved_count += 1
            retrieved = pd.NaT
        elif retrieved > as_of_ts:
            future_count += 1
            continue

        close_val = _float_or_none(row.get("close"))
        if close_val is None:
            invalid_count += 1
            continue

        open_val = _float_or_none(row.get("open"))
        high_val = _float_or_none(row.get("high"))
        low_val = _float_or_none(row.get("low"))
        adj_close_val = _float_or_none(_first_present(row, "adj_close"))
        if adj_close_val is None:
            adj_close_val = close_val
        vol_val = _float_or_none(row.get("volume"))

        interval = _text(row.get("interval")) or "1d"
        bar_id = _text(row.get("bar_id")) or (
            f"bar_{lid}_{interval}_{ts.strftime('%Y%m%dT%H%M%S')}"
        )

        valid_rows.append({
            "bar_id": bar_id,
            "listing_id": lid,
            "canonical_ticker": ctick,
            "interval": interval,
            "timestamp_utc": ts,
            "open": open_val,
            "high": high_val,
            "low": low_val,
            "close": close_val,
            "adj_close": adj_close_val,
            "volume": vol_val,
            "source_id": _text(row.get("source_id")) or source_id,
            "source_url": _text(row.get("source_url")) or source_url,
            "retrieved_at_utc": retrieved,
            "pit_class": _text(row.get("pit_class")) or pit_class,
            "source_license_class": _text(row.get("source_license_class")) or license_class,
            "registry_version": _text(row.get("registry_version")) or registry_version,
        })

    if conflicted_keys:
        issues.append(
            f"{len(conflicted_keys)} listing identifier(s) were ambiguous and removed from the crosswalk"
        )
    if unmapped_count > 0:
        issues.append(f"{unmapped_count} bar row(s) failed listing crosswalk resolution")
    if future_count > 0:
        issues.append(f"{future_count} bar row(s) rejected due to timestamp > as_of_utc")
    if invalid_count > 0:
        issues.append(f"{invalid_count} bar row(s) rejected due to missing timestamp or close price")
    if missing_retrieved_count > 0:
        issues.append(
            f"{missing_retrieved_count} bar row(s) have no retrieved timestamp; retained as unknown provenance"
        )

    if not valid_rows:
        return NormalizationResult(
            frame=_empty_frame(MARKET_BARS_COLUMNS),
            valid_count=0,
            unmapped_count=unmapped_count,
            future_count=future_count,
            invalid_count=invalid_count,
            issues=tuple(issues),
        )

    df = pd.DataFrame(valid_rows, columns=MARKET_BARS_COLUMNS)
    before_dedupe = len(df)
    df = df.sort_values(
        [
            "listing_id",
            "interval",
            "timestamp_utc",
            "retrieved_at_utc",
            "source_id",
            "bar_id",
        ],
        ascending=True,
        na_position="first",
        kind="mergesort",
    ).drop_duplicates(
        subset=["listing_id", "interval", "timestamp_utc"], keep="last"
    )
    dropped_duplicate_count = before_dedupe - len(df)
    if dropped_duplicate_count > 0:
        issues.append(f"{dropped_duplicate_count} duplicate bar row(s) dropped")
    df = df.sort_values(["listing_id", "interval", "timestamp_utc"], ascending=True).reset_index(drop=True)

    return NormalizationResult(
        frame=df,
        valid_count=len(df),
        unmapped_count=unmapped_count,
        future_count=future_count,
        invalid_count=invalid_count,
        issues=tuple(issues),
        dropped_duplicate_count=dropped_duplicate_count,
    )


def normalize_quote_snapshots(
    input_data: pd.DataFrame | Sequence[Mapping[str, Any]],
    listings: pd.DataFrame,
    *,
    as_of_utc: object,
    source_id: str = "quote_snapshots",
    source_url: str = "",
    pit_class: str = "snapshot_from_delayed_source",
    license_class: str = "personal_use_terms_unverified",
    registry_version: str = "v1",
) -> NormalizationResult:
    """Normalize latest quote snapshots against the listing registry and as_of_utc gate."""
    as_of_ts = _to_utc_timestamp(as_of_utc)
    if as_of_ts is None:
        raise ValueError("as_of_utc must be a valid timestamp")

    if isinstance(input_data, pd.DataFrame):
        rows = input_data.to_dict("records") if not input_data.empty else []
    else:
        rows = list(input_data)

    crosswalk, conflicted_keys = _build_listing_crosswalk_with_conflicts(listings)
    listing_by_id = listings.set_index("listing_id", drop=False).to_dict("index") if not listings.empty else {}
    valid_rows: list[dict[str, Any]] = []
    unmapped_count = 0
    future_count = 0
    invalid_count = 0
    missing_retrieved_count = 0
    issues: list[str] = []

    for row in rows:
        lid, ctick = resolve_listing_identity(row, crosswalk)
        if not lid:
            unmapped_count += 1
            continue
        listing = listing_by_id.get(lid, {})
        listing_start = _to_utc_timestamp(listing.get("active_from"))
        listing_end = _to_utc_timestamp(listing.get("active_to"))
        if (
            _text(listing.get("listing_status")).lower() not in {"", "active"}
            or (listing_start is not None and listing_start > as_of_ts)
            or (listing_end is not None and listing_end <= as_of_ts)
        ):
            invalid_count += 1
            continue
        supplied_ticker = _text(row.get("canonical_ticker"))
        registry_ticker = _text(listing.get("canonical_ticker"))
        if supplied_ticker and registry_ticker and supplied_ticker != registry_ticker:
            invalid_count += 1
            continue
        supplied_currency = _text(row.get("currency")).upper()
        registry_currency = _text(listing.get("currency")).upper()
        if supplied_currency and registry_currency and supplied_currency != registry_currency:
            invalid_count += 1
            continue
        supplied_provider = _text(row.get("provider_symbol")) or _text(row.get("ticker"))
        registry_symbols = _vendor_symbols(listing)
        if supplied_provider and registry_symbols and supplied_provider not in registry_symbols:
            invalid_count += 1
            continue

        ts_raw = _first_present(row, "quote_timestamp", "timestamp_utc", "timestamp")
        ts = _to_utc_timestamp(ts_raw)
        if ts is None:
            invalid_count += 1
            continue
        if ts > as_of_ts:
            future_count += 1
            continue

        retrieved = _to_utc_timestamp(
            _first_present(row, "retrieved_at_utc", "fetched_at")
        )
        if retrieved is None:
            missing_retrieved_count += 1
            retrieved = pd.NaT
        elif retrieved > as_of_ts:
            future_count += 1
            continue

        last_price = _float_or_none(
            _first_present(row, "last_price", "close", "price")
        )
        if last_price is None:
            invalid_count += 1
            continue

        bid_val = _float_or_none(row.get("bid"))
        ask_val = _float_or_none(row.get("ask"))
        day_change = _float_or_none(
            _first_present(row, "day_change_pct", "change_pct")
        )
        vol_val = _float_or_none(row.get("volume"))

        provider_sym = supplied_provider or (registry_symbols[0] if len(registry_symbols) == 1 else ctick)
        quote_id = _text(row.get("quote_id")) or f"quote_{lid}_{ts.strftime('%Y%m%d%H%M%S')}"

        valid_rows.append({
            "quote_id": quote_id,
            "listing_id": lid,
            "canonical_ticker": ctick,
            "provider_symbol": provider_sym,
            "quote_timestamp": ts,
            "retrieved_at_utc": retrieved,
            "last_price": last_price,
            "bid": bid_val,
            "ask": ask_val,
            "day_change_pct": day_change,
            "volume": vol_val,
            "currency": registry_currency or supplied_currency,
            "market_status": _text(row.get("market_status")) or "unknown",
            "latency_class": "delayed",
            "source_id": _text(row.get("source_id")) or source_id,
            "source_url": _text(row.get("source_url")) or source_url,
            "pit_class": (
                "snapshot_from_delayed_source"
                if (_text(row.get("pit_class")) or pit_class).lower()
                in {"live", "snapshot_from_live_source"}
                else (_text(row.get("pit_class")) or pit_class)
            ),
            "source_license_class": (
                "personal_use_terms_unverified"
                if (_text(row.get("source_license_class")) or license_class).lower()
                in {"public", "public_metadata"}
                else (_text(row.get("source_license_class")) or license_class)
            ),
            "registry_version": _text(row.get("registry_version")) or registry_version,
        })

    if conflicted_keys:
        issues.append(
            f"{len(conflicted_keys)} listing identifier(s) were ambiguous and removed from the crosswalk"
        )
    if unmapped_count > 0:
        issues.append(f"{unmapped_count} quote row(s) failed listing crosswalk resolution")
    if future_count > 0:
        issues.append(f"{future_count} quote row(s) rejected due to quote_timestamp > as_of_utc")
    if invalid_count > 0:
        issues.append(f"{invalid_count} quote row(s) rejected due to missing timestamp or last_price")
    if missing_retrieved_count > 0:
        issues.append(
            f"{missing_retrieved_count} quote row(s) have no retrieved timestamp; retained as unknown provenance"
        )

    if not valid_rows:
        return NormalizationResult(
            frame=_empty_frame(QUOTE_SNAPSHOT_COLUMNS),
            valid_count=0,
            unmapped_count=unmapped_count,
            future_count=future_count,
            invalid_count=invalid_count,
            issues=tuple(issues),
        )

    df = pd.DataFrame(valid_rows, columns=QUOTE_SNAPSHOT_COLUMNS)
    before_dedupe = len(df)
    df = df.sort_values(
        ["listing_id", "quote_timestamp", "retrieved_at_utc", "source_id", "quote_id"],
        ascending=True,
        na_position="first",
        kind="mergesort",
    ).drop_duplicates(subset=["listing_id"], keep="last")
    dropped_duplicate_count = before_dedupe - len(df)
    if dropped_duplicate_count > 0:
        issues.append(f"{dropped_duplicate_count} duplicate quote row(s) dropped")
    df = df.sort_values(["listing_id"], ascending=True).reset_index(drop=True)

    return NormalizationResult(
        frame=df,
        valid_count=len(df),
        unmapped_count=unmapped_count,
        future_count=future_count,
        invalid_count=invalid_count,
        issues=tuple(issues),
        dropped_duplicate_count=dropped_duplicate_count,
    )



def format_quote_age(quote_timestamp: object, as_of_utc: object) -> str:
    """Return a human-readable relative age string for a quote timestamp."""
    quote_ts = _to_utc_timestamp(quote_timestamp)
    as_of_ts = _to_utc_timestamp(as_of_utc)
    if quote_ts is None or as_of_ts is None:
        return "age unavailable"
    if quote_ts > as_of_ts:
        return "future timestamp"
    diff = as_of_ts - quote_ts
    total_seconds = int(diff.total_seconds())
    if total_seconds < 60:
        return "<1m ago"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    rem_minutes = minutes % 60
    if hours < 24:
        return f"{hours}h {rem_minutes}m ago" if rem_minutes else f"{hours}h ago"
    days = hours // 24
    rem_hours = hours % 24
    return f"{days}d {rem_hours}h ago" if rem_hours else f"{days}d ago"

__all__ = [
    "MARKET_BARS_COLUMNS",
    "NormalizationResult",
    "QUOTE_SNAPSHOT_COLUMNS",
    "build_listing_crosswalk",
    "classify_quote_freshness",
    "normalize_market_bars",
    "normalize_quote_snapshots",
    "resolve_listing_identity",
    "format_quote_age",
]
