"""Provider adapters for writing local quote snapshot inputs.

The Streamlit app never imports this module. A scheduled process may call
collect_yfinance_quotes and write the resulting standardized parquet; the
normal Control Tower builder then consumes that local file with networking
disabled.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import datetime
import json
import math
from pathlib import Path
from typing import Any, Callable, Literal, Sequence
import uuid
from zoneinfo import ZoneInfo

import pandas as pd

from .build import QUOTE_SNAPSHOT_COLUMNS
from .registries import REQUIRED_COLUMNS


DownloadFunction = Callable[..., pd.DataFrame]

STAGE1_BASKET_ID = "RESEARCH_STAGE_1_CHINA_INTERNET"
CURRENT_RUN_TOLERANCE = pd.Timedelta(hours=72)
QUOTE_STATUS_SCHEMA = "quote_collection_status_v1"
STATUS_SIDECAR_SUFFIX = ".status.json"

_EXCHANGE_TIMEZONES = {
    "HKEX": "Asia/Hong_Kong",
    "SEHK": "Asia/Hong_Kong",
    "HKSE": "Asia/Hong_Kong",
    "NYSE": "America/New_York",
    "NASDAQ": "America/New_York",
    "AMEX": "America/New_York",
    "ARCA": "America/New_York",
    "LSE": "Europe/London",
}

# Regular-session open used to attribute a pre-open quote to the prior local
# session.  All Stage 1 exchanges (SEHK, NYSE, NASDAQ) open at 09:30 local.
_REGULAR_SESSION_OPEN = datetime.time(9, 30)


@dataclass(frozen=True, slots=True)
class QuoteDiagnostic:
    symbol: str
    listing_id: str
    entity_id: str
    status: Literal[
        "available",
        "no_records",
        "ambiguous_symbol",
        "invalid_listing",
        "excluded_private",
        "failed",
        "inactive",
    ]
    reason: str


@dataclass(frozen=True, slots=True)
class QuoteCollectionResult:
    frame: pd.DataFrame
    aggregate_status: Literal["available", "partial", "no_records", "unavailable"]
    symbol_diagnostics: tuple[QuoteDiagnostic, ...]
    issues: tuple[str, ...] = ()
    expected_listing_count: int = 0


def _empty_quote_frame() -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in QUOTE_SNAPSHOT_COLUMNS})


def _vendor_symbol(row: Any, provider: str) -> str:
    raw = row.get("vendor_tickers", "")
    if raw is None or pd.isna(raw):
        return ""
    for token in str(raw).split(";"):
        name, separator, symbol = token.partition(":")
        if separator and name.strip().casefold() == provider.casefold() and symbol.strip():
            return symbol.strip()
    return ""


def _quote_timestamp(value: object) -> pd.Timestamp | None:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.tz_localize("UTC")
    else:
        parsed = parsed.tz_convert("UTC")
    return parsed


def quote_status_path(output_path: Path) -> Path:
    """Return the adjacent status/diagnostic sidecar path for a quote input."""

    output = Path(output_path)
    return output.with_name(f"{output.stem}{STATUS_SIDECAR_SUFFIX}")


def _date(value: object) -> pd.Timestamp | None:
    ts = _quote_timestamp(value)
    if ts is not None:
        return ts.tz_localize(None).normalize()
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return None if pd.isna(parsed) else parsed.normalize()


def _blank(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    try:
        missing = pd.isna(value)
        if not hasattr(missing, "__len__") and bool(missing):
            return True
    except (TypeError, ValueError):
        pass
    return not str(value).strip()


def _text(value: object) -> str:
    return "" if _blank(value) else str(value).strip()


def _truthy(value: object) -> bool:
    if _blank(value):
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _exchange_timezone(exchange: object) -> ZoneInfo:
    name = _EXCHANGE_TIMEZONES.get(_text(exchange).upper(), "UTC")
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError):
        return ZoneInfo("UTC")


def _interval_errors(
    frame: pd.DataFrame,
    registry_name: str,
    *,
    required_columns: Sequence[str],
) -> list[str]:
    errors: list[str] = []
    missing = sorted(set(required_columns) - set(frame.columns))
    if missing:
        return [f"{registry_name} registry missing required columns: {', '.join(missing)}"]
    for row_index, row in frame.iterrows():
        start = _date(row.get("active_from"))
        end = _date(row.get("active_to"))
        if start is None:
            errors.append(f"{registry_name} row {row_index} has invalid or missing active_from")
        if not _blank(row.get("active_to")) and end is None:
            errors.append(f"{registry_name} row {row_index} has invalid active_to")
        if start is not None and end is not None and end <= start:
            errors.append(f"{registry_name} row {row_index} has active_to <= active_from")
    return errors


def _validate_stage1_registry(
    listings: pd.DataFrame | None,
    entities: pd.DataFrame | None,
    baskets: pd.DataFrame | None,
    basket_memberships: pd.DataFrame | None,
) -> tuple[str, ...]:
    """Validate the complete Stage 1 registry gate before any provider call."""

    frames = {
        "entities": entities,
        "baskets": baskets,
        "basket_memberships": basket_memberships,
        "listings": listings,
    }
    errors: list[str] = []
    for name, frame in frames.items():
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            errors.append(f"{name} registry is missing or empty")
            continue
        required_columns = tuple(REQUIRED_COLUMNS[name])
        if name == "listings":
            # ``listing_status`` is part of the published listing mart even
            # though older registry loaders did not include it in their
            # minimum CSV column set.
            required_columns = (*required_columns, "listing_status")
        errors.extend(
            _interval_errors(
                frame,
                name,
                required_columns=required_columns,
            )
        )

    if errors:
        return tuple(errors)

    assert listings is not None
    assert entities is not None
    assert baskets is not None
    assert basket_memberships is not None

    for name, frame, key in (
        ("entities", entities, "entity_id"),
        ("listings", listings, "listing_id"),
        ("baskets", baskets, "basket_id"),
    ):
        if frame[key].map(_blank).any():
            errors.append(f"{name} registry has blank {key}")
    if basket_memberships[["entity_id", "basket_id"]].map(_blank).any().any():
        errors.append("basket_memberships registry has blank entity_id or basket_id")

    if entities["entity_id"].duplicated().any():
        errors.append("entities registry contains duplicate entity_id")
    if listings["listing_id"].duplicated().any():
        errors.append("listings registry contains duplicate listing_id")
    if baskets["basket_id"].duplicated().any():
        errors.append("baskets registry contains duplicate basket_id")

    entity_types = entities["entity_type"].astype("string").str.strip().str.lower()
    if (~entity_types.isin({"public", "private"})).any():
        errors.append("entities registry has invalid or missing entity_type")
    active_status = entities["active_status"].astype("string").str.strip().str.lower()
    if (~active_status.isin({"active", "archived", "inactive"})).any():
        errors.append("entities registry has invalid active_status")

    listing_status = listings["listing_status"].astype("string").str.strip().str.lower()
    if (~listing_status.isin({"active", "archived", "inactive"})).any():
        errors.append("listings registry has invalid listing_status")
    mapping_status = listings["mapping_status"].astype("string").str.strip().str.lower()
    if (~mapping_status.isin({"verified", "unresolved"})).any():
        errors.append("listings registry has invalid mapping_status")

    entity_ids = set(entities["entity_id"].astype("string"))
    basket_ids = set(baskets["basket_id"].astype("string"))
    if STAGE1_BASKET_ID not in basket_ids:
        errors.append(f"baskets registry is missing {STAGE1_BASKET_ID}")
    if not set(listings["entity_id"].astype("string")).issubset(entity_ids):
        errors.append("listings registry contains an unknown entity_id")
    if not set(basket_memberships["entity_id"].astype("string")).issubset(entity_ids):
        errors.append("basket_memberships registry contains an unknown entity_id")
    if not set(basket_memberships["basket_id"].astype("string")).issubset(basket_ids):
        errors.append("basket_memberships registry contains an unknown basket_id")

    stage1_members = basket_memberships.loc[
        basket_memberships["basket_id"].astype("string").eq(STAGE1_BASKET_ID)
    ]
    if stage1_members.empty:
        errors.append(f"basket_memberships registry has no {STAGE1_BASKET_ID} members")

    return tuple(sorted(set(errors)))


def _frame_with_market_time_index(
    frame: pd.DataFrame,
    timezone: ZoneInfo,
    *,
    daily: bool,
) -> pd.DataFrame:
    """Normalize and sort provider frames while retaining local session labels."""

    if frame is None or frame.empty:
        return pd.DataFrame()
    output = frame.copy()
    utc_index: list[pd.Timestamp | None] = []
    local_dates: list[object] = []
    for raw in output.index:
        try:
            parsed = pd.Timestamp(raw)
        except (TypeError, ValueError, OverflowError):
            parsed = pd.NaT
        if pd.isna(parsed):
            utc_index.append(None)
            local_dates.append(pd.NaT)
            continue
        if daily and (parsed.tzinfo is None or parsed.utcoffset() is None):
            # yfinance daily labels are exchange-local session dates when naive.
            local_dates.append(parsed.date())
            utc_index.append(parsed.tz_localize("UTC"))
        else:
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                parsed = parsed.tz_localize(timezone)
            parsed = parsed.tz_convert("UTC")
            utc_index.append(parsed)
            local_dates.append(parsed.tz_convert(timezone).date())
    keep = [index is not None for index in utc_index]
    if not any(keep):
        return pd.DataFrame()
    output = output.loc[keep].copy()
    output.index = pd.DatetimeIndex([index for index in utc_index if index is not None])
    output["__local_session_date"] = [date for date, valid in zip(local_dates, keep) if valid]
    return output.sort_values(
        ["__local_session_date"],
        kind="mergesort",
    ).sort_index(kind="mergesort")


def _session_date(value: object, timezone: ZoneInfo, *, daily: bool = False):
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed):
        return None
    if daily and (parsed.tzinfo is None or parsed.utcoffset() is None):
        return parsed.date()
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.tz_localize(timezone)
    return parsed.tz_convert(timezone).date()


def _symbol_frame(downloaded: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Extract one ticker from either yfinance MultiIndex orientation."""

    if downloaded is None or downloaded.empty:
        return pd.DataFrame()
    frame = downloaded
    columns = frame.columns
    if isinstance(columns, pd.MultiIndex):
        matched_symbol = False
        for level in range(columns.nlevels):
            values = {str(value) for value in columns.get_level_values(level)}
            if symbol in values:
                matched_symbol = True
                frame = frame.xs(symbol, axis=1, level=level, drop_level=True)
                break
        if not matched_symbol:
            return pd.DataFrame()
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = [str(value[-1]) for value in frame.columns]
    frame = frame.copy()
    frame.columns = [str(column).strip().title() for column in frame.columns]
    return frame


def collect_yfinance_quotes(
    listings: pd.DataFrame,
    *,
    as_of_utc: object | None = None,
    download_fn: DownloadFunction | None = None,
    daily_download_fn: DownloadFunction | None = None,
    source_id: str = "market:yfinance",
    latency_class: str = "delayed",
    entities: pd.DataFrame | None = None,
    baskets: pd.DataFrame | None = None,
    basket_memberships: pd.DataFrame | None = None,
    stage1_only: bool = True,
    timeout_seconds: float = 10.0,
) -> QuoteCollectionResult:
    """Collect one latest quote snapshot per eligible registry listing.

    yfinance is intentionally imported lazily and its output is labelled
    delayed with source_license_class="personal_use_terms_unverified".
    """

    retrieved_at_wall_utc = pd.Timestamp.now(tz="UTC")
    as_of = _quote_timestamp(as_of_utc) if as_of_utc is not None else retrieved_at_wall_utc
    if as_of is None:
        raise ValueError("as_of_utc must be a valid timestamp")

    requested_latency = str(latency_class or "").strip().lower()
    if requested_latency in {"realtime", "live", "real_time"}:
        raise ValueError("latency_class cannot be 'realtime' or 'live' without entitlement evidence; use 'delayed'")

    if as_of < retrieved_at_wall_utc - CURRENT_RUN_TOLERANCE:
        return QuoteCollectionResult(
            frame=_empty_quote_frame(),
            aggregate_status="unavailable",
            symbol_diagnostics=(),
            issues=(
                "Historical as_of_utc is outside the current quote snapshot tolerance; "
                "use a bounded historical-bars collector for backfill",
            ),
        )
    if as_of > retrieved_at_wall_utc + pd.Timedelta(minutes=5):
        return QuoteCollectionResult(
            frame=_empty_quote_frame(),
            aggregate_status="unavailable",
            symbol_diagnostics=(),
            issues=("as_of_utc is in the future relative to collection time",),
        )

    if stage1_only:
        registry_errors = _validate_stage1_registry(
            listings,
            entities,
            baskets,
            basket_memberships,
        )
        if registry_errors:
            registry_diagnostics = [
                QuoteDiagnostic(
                    symbol="",
                    listing_id=_text(row.get("listing_id")),
                    entity_id=_text(row.get("entity_id")),
                    status="invalid_listing",
                    reason=error,
                )
                for error in registry_errors
                for row in (
                    listings.to_dict("records")
                    if isinstance(listings, pd.DataFrame) and not listings.empty
                    else [{}]
                )
            ]
            if not registry_diagnostics:
                registry_diagnostics = [
                    QuoteDiagnostic(
                        symbol="",
                        listing_id="",
                        entity_id="",
                        status="invalid_listing",
                        reason=error,
                    )
                    for error in registry_errors
                ]
            return QuoteCollectionResult(
                frame=_empty_quote_frame(),
                aggregate_status="unavailable",
                symbol_diagnostics=tuple(registry_diagnostics),
                issues=registry_errors,
            )

    # Required listing identity columns check
    required_cols = {
        "listing_id",
        "entity_id",
        "collection_eligible",
        "mapping_status",
        "listing_status",
        "active_from",
        "active_to",
        "canonical_ticker",
        "currency",
        "vendor_tickers",
    }
    if listings is None or listings.empty or not required_cols.issubset(listings.columns):
        return QuoteCollectionResult(
            frame=_empty_quote_frame(),
            aggregate_status="unavailable",
            symbol_diagnostics=(),
            issues=("Listings input is missing required identity or interval columns",),
        )

    as_of_date = as_of.tz_localize(None).normalize()
    diagnostics: list[QuoteDiagnostic] = []

    # 1. Filter listings by active status, mapping status, collection eligibility, and active interval.
    eligible = listings.copy()

    def _interval_active(row: Any) -> bool:
        start = _date(row.get("active_from"))
        end = _date(row.get("active_to"))
        return (start is None or as_of_date >= start) and (end is None or as_of_date < end)

    entity_by_id = (
        entities.set_index("entity_id", drop=False).to_dict("index")
        if isinstance(entities, pd.DataFrame) and not entities.empty and "entity_id" in entities.columns
        else {}
    )
    stage1_entity_ids: set[str] | None = None
    if stage1_only:
        assert baskets is not None
        assert basket_memberships is not None
        basket_rows = baskets.loc[
            baskets["basket_id"].astype("string").eq(STAGE1_BASKET_ID)
            & baskets.apply(_interval_active, axis=1)
        ]
        membership_rows = basket_memberships.loc[
            basket_memberships["basket_id"].astype("string").eq(STAGE1_BASKET_ID)
            & basket_memberships.apply(_interval_active, axis=1)
        ]
        stage1_entity_ids = set(membership_rows["entity_id"].astype("string")) if not basket_rows.empty else set()

    eligible_rows: list[dict[str, Any]] = []
    for _, row in listings.iterrows():
        listing_id = _text(row.get("listing_id"))
        entity_id = _text(row.get("entity_id"))
        if stage1_only and entity_id not in (stage1_entity_ids or set()):
            continue
        entity = entity_by_id.get(entity_id)
        if entity is not None:
            entity_type = _text(entity.get("entity_type")).lower()
            if entity_type == "private":
                diagnostics.append(
                    QuoteDiagnostic(
                        symbol="",
                        listing_id=listing_id,
                        entity_id=entity_id,
                        status="excluded_private",
                        reason="Private entity is not public-market collection eligible",
                    )
                )
                continue
            if (
                _text(entity.get("active_status")).lower() != "active"
                or not _interval_active(entity)
            ):
                diagnostics.append(
                    QuoteDiagnostic(
                        symbol="",
                        listing_id=listing_id,
                        entity_id=entity_id,
                        status="inactive",
                        reason="Entity is archived, inactive, or outside its active interval",
                    )
                )
                continue
        if _text(row.get("listing_status")).lower() != "active" or not _interval_active(row):
            diagnostics.append(
                QuoteDiagnostic(
                    symbol="",
                    listing_id=listing_id,
                    entity_id=entity_id,
                    status="inactive",
                    reason="Listing is archived, inactive, or outside its active interval",
                )
            )
            continue
        if (
            not _truthy(row.get("collection_eligible"))
            or _text(row.get("mapping_status")).lower() != "verified"
            or _blank(row.get("canonical_ticker"))
            or _blank(row.get("currency"))
        ):
            diagnostics.append(
                QuoteDiagnostic(
                    symbol="",
                    listing_id=listing_id,
                    entity_id=entity_id,
                    status="invalid_listing",
                    reason="Listing fails verified public collection identity requirements",
                )
            )
            continue
        eligible_rows.append(row.to_dict())

    eligible = pd.DataFrame(eligible_rows, columns=listings.columns)

    if eligible.empty:
        return QuoteCollectionResult(
            frame=_empty_quote_frame(),
            aggregate_status="no_records",
            symbol_diagnostics=tuple(diagnostics),
            issues=("No Stage 1 public listings resolved for collection",),
            expected_listing_count=0,
        )

    expected_listing_count = len(eligible)

    # 2. Resolve yfinance vendor symbols and check duplicate mappings.
    symbol_to_listings: dict[str, list[dict[str, Any]]] = {}
    for _, row in eligible.iterrows():
        symbol = _vendor_symbol(row, "yfinance")
        listing_id = _text(row.get("listing_id"))
        entity_id = _text(row.get("entity_id"))
        if not symbol:
            diagnostics.append(
                QuoteDiagnostic(
                    symbol="",
                    listing_id=listing_id,
                    entity_id=entity_id,
                    status="no_records",
                    reason="Missing yfinance provider symbol in listing registry",
                )
            )
            continue
        symbol_to_listings.setdefault(symbol, []).append(row.to_dict())

    valid_symbols: list[str] = []
    for symbol, l_rows in symbol_to_listings.items():
        if len(l_rows) > 1:
            for l_row in l_rows:
                diagnostics.append(
                    QuoteDiagnostic(
                        symbol=symbol,
                        listing_id=_text(l_row.get("listing_id")),
                        entity_id=_text(l_row.get("entity_id")),
                        status="ambiguous_symbol",
                        reason=f"Vendor symbol {symbol} maps to multiple active listings",
                    )
                )
        else:
            valid_symbols.append(symbol)
    valid_symbols.sort()

    if not valid_symbols:
        return QuoteCollectionResult(
            frame=_empty_quote_frame(),
            aggregate_status="partial" if diagnostics else "no_records",
            symbol_diagnostics=tuple(diagnostics),
            issues=("No unambiguous vendor symbols available for query",),
            expected_listing_count=expected_listing_count,
        )

    # 3. Fetch market data using download_fn or lazy yfinance import.
    download_fn_was_none = download_fn is None
    if download_fn is None:
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover
            return QuoteCollectionResult(
                frame=_empty_quote_frame(),
                aggregate_status="unavailable",
                symbol_diagnostics=tuple(diagnostics),
                issues=("yfinance module is required for live quote collection",),
            )
        def _default_download(symbols, **kwargs):
            return yf.download(symbols, timeout=timeout_seconds, **kwargs)
        download_fn = _default_download

    try:
        downloaded = download_fn(
            valid_symbols,
            period="1d",
            interval="1m",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        for symbol in valid_symbols:
            listing = symbol_to_listings[symbol][0]
            diagnostics.append(
                QuoteDiagnostic(
                    symbol=symbol,
                    listing_id=_text(listing.get("listing_id")),
                    entity_id=_text(listing.get("entity_id")),
                    status="failed",
                    reason=f"Provider download failed: {exc}",
                )
            )
        return QuoteCollectionResult(
            frame=_empty_quote_frame(),
            aggregate_status="unavailable",
            symbol_diagnostics=tuple(diagnostics),
            issues=(f"yfinance download failed: {exc}",),
            expected_listing_count=expected_listing_count,
        )

    # 4. Fetch prior daily session bars through a separate injectable function.
    daily_downloaded: pd.DataFrame | None = None
    if daily_download_fn is None and download_fn_was_none:
        daily_download_fn = download_fn
    if daily_download_fn is not None:
        try:
            daily_downloaded = daily_download_fn(
                valid_symbols,
                period="5d",
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=False,
            )
        except Exception as exc:
            daily_downloaded = None
            diagnostics.append(
                QuoteDiagnostic(
                    symbol=";".join(valid_symbols),
                    listing_id="",
                    entity_id="",
                    status="failed",
                    reason=f"Daily session download failed: {exc}",
                )
            )

    rows: list[dict[str, Any]] = []

    for symbol in valid_symbols:
        listing = symbol_to_listings[symbol][0]
        listing_id = _text(listing.get("listing_id"))
        entity_id = _text(listing.get("entity_id"))
        canonical_ticker = _text(listing.get("canonical_ticker"))
        exchange_timezone = _exchange_timezone(listing.get("exchange"))

        frame = _frame_with_market_time_index(
            _symbol_frame(downloaded, symbol),
            exchange_timezone,
            daily=False,
        )
        if frame.empty or "Close" not in frame.columns:
            diagnostics.append(
                QuoteDiagnostic(
                    symbol=symbol,
                    listing_id=listing_id,
                    entity_id=entity_id,
                    status="no_records",
                    reason="Provider returned empty or incomplete bar frame",
                )
            )
            continue

        close = pd.to_numeric(frame["Close"], errors="coerce").dropna().sort_index(kind="mergesort")
        if close.empty:
            diagnostics.append(
                QuoteDiagnostic(
                    symbol=symbol,
                    listing_id=listing_id,
                    entity_id=entity_id,
                    status="no_records",
                    reason="Provider returned no valid close prices",
                )
            )
            continue

        # Restrict to intraday bars <= wall clock retrieval AND <= reference as_of.
        valid_close = close.loc[
            close.index.map(lambda idx: bool(_quote_timestamp(idx) is not None and _quote_timestamp(idx) <= retrieved_at_wall_utc and _quote_timestamp(idx) <= as_of))
        ]
        if valid_close.empty:
            diagnostics.append(
                QuoteDiagnostic(
                    symbol=symbol,
                    listing_id=listing_id,
                    entity_id=entity_id,
                    status="no_records",
                    reason="No bar timestamp <= collection time",
                )
            )
            continue

        last_index = valid_close.index[-1]
        quote_timestamp = _quote_timestamp(last_index)
        last_price = float(valid_close.iloc[-1])

        if quote_timestamp is None or not pd.notna(last_price) or not math.isfinite(last_price):
            diagnostics.append(
                QuoteDiagnostic(
                    symbol=symbol,
                    listing_id=listing_id,
                    entity_id=entity_id,
                    status="no_records",
                    reason="Invalid timestamp or last price",
                )
            )
            continue

        volume = pd.NA
        if "Volume" in frame.columns:
            candidate = pd.to_numeric(frame.loc[last_index, "Volume"], errors="coerce")
            if pd.notna(candidate) and math.isfinite(float(candidate)):
                volume = float(candidate)

        # Produce defensible day change from explicit prior daily session close
        day_change_pct: float | object = pd.NA
        prev_close_val: float | None = None
        # Check daily bars fetched from the separate daily provider.
        daily_frame = (
            _frame_with_market_time_index(
                _symbol_frame(daily_downloaded, symbol),
                exchange_timezone,
                daily=True,
            )
            if daily_downloaded is not None
            else pd.DataFrame()
        )
        if daily_frame.empty and "Close" in frame.columns:
            # Check if frame itself contains daily bars or explicit Previous Close column
            for col in ("Previous Close", "Prev Close", "Previous_Close"):
                if col in frame.columns:
                    parsed_prev = pd.to_numeric(frame[col], errors="coerce").dropna()
                    if not parsed_prev.empty and float(parsed_prev.iloc[-1]) > 0:
                        prev_close_val = float(parsed_prev.iloc[-1])
                        break

        if prev_close_val is None and not daily_frame.empty and "Close" in daily_frame.columns:
            daily_close = pd.to_numeric(daily_frame["Close"], errors="coerce").dropna()
            quote_session_date = _session_date(quote_timestamp, exchange_timezone)
            # A quote observed before the exchange's regular session open
            # belongs to the prior local session: the current session has not
            # started, so the day-change reference is the previous calendar
            # day's close rather than a same-day bar.
            if quote_session_date is not None:
                local_time = quote_timestamp.tz_convert(exchange_timezone).time()
                if local_time < _REGULAR_SESSION_OPEN:
                    quote_session_date = quote_session_date - pd.Timedelta(days=1)
            daily_dates = daily_frame.loc[daily_close.index, "__local_session_date"]
            prior_positions = [
                position
                for position, value in enumerate(daily_dates.tolist())
                if quote_session_date is not None and value < quote_session_date
            ]
            if prior_positions:
                val = float(daily_close.iloc[prior_positions[-1]])
                if val > 0 and math.isfinite(val):
                    prev_close_val = val

        if prev_close_val is not None and prev_close_val > 0:
            day_change_pct = float(round((last_price - prev_close_val) / prev_close_val * 100.0, 4))

        # No separate unbounded provider-metadata request: unknown is safer
        # than an unbound market-state lookup and does not imply exchange
        # entitlement.
        market_status = "unknown"

        rows.append({
            "quote_id": f"quote_{listing_id}_{quote_timestamp.strftime('%Y%m%dT%H%M%S')}_yfinance",
            "listing_id": listing_id,
            "canonical_ticker": canonical_ticker,
            "provider_symbol": symbol,
            "quote_timestamp": quote_timestamp,
            "retrieved_at_utc": retrieved_at_wall_utc,
            "last_price": last_price,
            "bid": pd.NA,
            "ask": pd.NA,
            "day_change_pct": day_change_pct,
            "volume": volume,
            "currency": _text(listing.get("currency")),
            "market_status": market_status,
            "latency_class": "delayed",
            "source_id": source_id,
            "source_url": f"https://finance.yahoo.com/quote/{symbol}",
            "pit_class": "snapshot_from_delayed_source",
            "source_license_class": "personal_use_terms_unverified",
            "registry_version": _text(listing.get("registry_version")) or "v1",
        })
        diagnostics.append(
            QuoteDiagnostic(
                symbol=symbol,
                listing_id=listing_id,
                entity_id=entity_id,
                status="available",
                reason="Successfully collected latest quote snapshot",
            )
        )

    out_df = pd.DataFrame(rows, columns=QUOTE_SNAPSHOT_COLUMNS) if rows else _empty_quote_frame()

    success_count = len(rows)
    total_valid = len(valid_symbols)

    if success_count == total_valid and success_count > 0:
        agg_status: Literal["available", "partial", "no_records", "unavailable"] = (
            "available" if success_count == expected_listing_count else "partial"
        )
    elif success_count > 0:
        agg_status = "partial"
    elif total_valid > 0:
        agg_status = "no_records"
    else:
        agg_status = "unavailable"

    return QuoteCollectionResult(
        frame=out_df,
        aggregate_status=agg_status,
        symbol_diagnostics=tuple(diagnostics),
        expected_listing_count=expected_listing_count,
    )


def write_quote_snapshot(
    frame: pd.DataFrame,
    output_path: Path,
    *,
    result: QuoteCollectionResult | None = None,
) -> Path:
    """Write quote data and collection status atomically as adjacent files."""

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    prepared = frame.reindex(columns=QUOTE_SNAPSHOT_COLUMNS)
    temp_filename = f".{output.name}.{uuid.uuid4().hex}.tmp"
    temporary = output.with_name(temp_filename)
    prepared.to_parquet(temporary, index=False)
    temporary.replace(output)

    if result is None:
        result = QuoteCollectionResult(
            frame=prepared,
            aggregate_status="available" if not prepared.empty else "no_records",
            symbol_diagnostics=(),
            expected_listing_count=len(prepared),
        )
    sidecar_payload = {
        "schema": QUOTE_STATUS_SCHEMA,
        "aggregate_status": result.aggregate_status,
        "row_count": int(len(prepared)),
        "expected_listing_count": int(result.expected_listing_count),
        "diagnostic_count": int(len(result.symbol_diagnostics)),
        "diagnostics": [asdict(item) for item in result.symbol_diagnostics],
        "issues": list(result.issues),
    }
    sidecar = quote_status_path(output)
    sidecar_temp = sidecar.with_name(f".{sidecar.name}.{uuid.uuid4().hex}.tmp")
    sidecar_temp.write_text(
        json.dumps(sidecar_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    sidecar_temp.replace(sidecar)
    return output


__all__ = [
    "QuoteCollectionResult",
    "QuoteDiagnostic",
    "CURRENT_RUN_TOLERANCE",
    "collect_yfinance_quotes",
    "quote_status_path",
    "write_quote_snapshot",
]
