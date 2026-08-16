"""Provider adapters for writing local quote snapshot inputs.

The Streamlit app never imports this module. A scheduled process may call
collect_yfinance_quotes and write the resulting standardized parquet; the
normal Control Tower builder then consumes that local file with networking
disabled.
"""

from __future__ import annotations

import math

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal
import uuid

import pandas as pd

from .build import QUOTE_SNAPSHOT_COLUMNS


DownloadFunction = Callable[..., pd.DataFrame]


@dataclass(frozen=True, slots=True)
class QuoteDiagnostic:
    symbol: str
    listing_id: str
    entity_id: str
    status: Literal["available", "no_records", "ambiguous_symbol", "excluded_private", "failed", "inactive"]
    reason: str


@dataclass(frozen=True, slots=True)
class QuoteCollectionResult:
    frame: pd.DataFrame
    aggregate_status: Literal["available", "partial", "no_records", "unavailable"]
    symbol_diagnostics: tuple[QuoteDiagnostic, ...]
    issues: tuple[str, ...] = ()


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


def _date(value: object) -> pd.Timestamp | None:
    ts = _quote_timestamp(value)
    if ts is not None:
        return ts.tz_localize(None).normalize()
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return None if pd.isna(parsed) else parsed.normalize()


def _symbol_frame(downloaded: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Extract one ticker from either yfinance MultiIndex orientation."""

    if downloaded is None or downloaded.empty:
        return pd.DataFrame()
    frame = downloaded
    columns = frame.columns
    if isinstance(columns, pd.MultiIndex):
        for level in range(columns.nlevels):
            values = {str(value) for value in columns.get_level_values(level)}
            if symbol in values:
                frame = frame.xs(symbol, axis=1, level=level, drop_level=True)
                break
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

    if latency_class.strip().lower() in {"realtime", "live", "real_time"}:
        raise ValueError("latency_class cannot be 'realtime' or 'live' without entitlement evidence; use 'delayed'")

    # Required listing identity columns check
    required_cols = {"listing_id", "entity_id", "collection_eligible", "mapping_status", "listing_status", "active_from"}
    if listings is None or listings.empty or not required_cols.issubset(listings.columns):
        return QuoteCollectionResult(
            frame=_empty_quote_frame(),
            aggregate_status="unavailable",
            symbol_diagnostics=(),
            issues=("Listings input is missing required identity or interval columns",),
        )

    as_of_date = as_of.tz_localize(None).normalize()
    diagnostics: list[QuoteDiagnostic] = []

    # 1. Filter listings by active status, mapping status, collection eligibility, and active interval
    eligible = listings.copy()
    eligible = eligible.loc[
        eligible["collection_eligible"].fillna(False).astype(bool)
        & eligible["mapping_status"].astype("string").str.casefold().eq("verified")
        & eligible["listing_status"].astype("string").str.casefold().eq("active")
    ].copy()

    def _interval_active(row: Any) -> bool:
        start = _date(row.get("active_from"))
        end = _date(row.get("active_to"))
        return (start is None or as_of_date >= start) and (end is None or as_of_date < end)

    eligible = eligible.loc[eligible.apply(_interval_active, axis=1)].copy()

    if eligible.empty:
        return QuoteCollectionResult(
            frame=_empty_quote_frame(),
            aggregate_status="unavailable",
            symbol_diagnostics=(),
            issues=("No verified active collection-eligible listings in registry as of reference date",),
        )

    # 2. Entity validation (exclude private entities like ByteDance or inactive entities)
    if entities is not None and not entities.empty and {"entity_id", "active_status", "entity_type"}.issubset(entities.columns):
        active_public_entities = set(
            entities.loc[
                entities["active_status"].astype("string").str.casefold().eq("active")
                & ~entities["entity_type"].astype("string").str.casefold().eq("private")
                & entities.apply(_interval_active, axis=1),
                "entity_id",
            ].astype("string")
        )
        private_entities = set(
            entities.loc[
                entities["entity_type"].astype("string").str.casefold().eq("private"),
                "entity_id",
            ].astype("string")
        )
        for _, prow in entities.loc[entities["entity_id"].astype("string").isin(private_entities)].iterrows():
            diagnostics.append(
                QuoteDiagnostic(
                    symbol="",
                    listing_id="",
                    entity_id=str(prow.get("entity_id")),
                    status="excluded_private",
                    reason="Private entity is not public-market collection eligible",
                )
            )
        eligible = eligible.loc[eligible["entity_id"].astype("string").isin(active_public_entities)].copy()

    # 3. Dynamic Stage 1 focus resolution
    if stage1_only:
        stage1_basket_id = "RESEARCH_STAGE_1_CHINA_INTERNET"
        if basket_memberships is not None and not basket_memberships.empty and {"basket_id", "entity_id"}.issubset(basket_memberships.columns):
            m_rows = basket_memberships.loc[
                basket_memberships["basket_id"].astype("string").eq(stage1_basket_id)
                & basket_memberships.apply(_interval_active, axis=1)
            ]
            stage1_entity_ids = set(m_rows["entity_id"].astype("string"))
            eligible = eligible.loc[eligible["entity_id"].astype("string").isin(stage1_entity_ids)].copy()
        elif baskets is not None and not baskets.empty and "basket_id" in baskets.columns:
            b_rows = baskets.loc[baskets["basket_id"].astype("string").eq(stage1_basket_id)]
            if b_rows.empty:
                eligible = eligible.iloc[0:0].copy()

    if eligible.empty:
        return QuoteCollectionResult(
            frame=_empty_quote_frame(),
            aggregate_status="no_records",
            symbol_diagnostics=tuple(diagnostics),
            issues=("No Stage 1 public listings resolved for collection",),
        )

    # 4. Resolve yfinance vendor symbols and check duplicate mappings
    symbol_to_listings: dict[str, list[dict[str, Any]]] = {}
    for _, row in eligible.iterrows():
        symbol = _vendor_symbol(row, "yfinance")
        listing_id = str(row.get("listing_id") or "").strip()
        entity_id = str(row.get("entity_id") or "").strip()
        if not symbol:
            diagnostics.append(
                QuoteDiagnostic(
                    symbol="",
                    listing_id=listing_id,
                    entity_id=entity_id,
                    status="no_records",
                    reason="No yfinance vendor ticker defined in registry",
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
                        listing_id=str(l_row.get("listing_id")),
                        entity_id=str(l_row.get("entity_id")),
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
        )

    # 5. Fetch market data using download_fn or lazy yfinance import
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
                    listing_id=str(listing.get("listing_id")),
                    entity_id=str(listing.get("entity_id")),
                    status="failed",
                    reason=f"Provider download failed: {exc}",
                )
            )
        return QuoteCollectionResult(
            frame=_empty_quote_frame(),
            aggregate_status="unavailable",
            symbol_diagnostics=tuple(diagnostics),
            issues=(f"yfinance download failed: {exc}",),
        )

    # Attempt to fetch prior daily session bars for defensible day change calculation
    daily_downloaded: pd.DataFrame | None = None
    if download_fn_was_none:
        try:
            import yfinance as yf
            daily_downloaded = yf.download(
                valid_symbols,
                period="5d",
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=False,
                timeout=timeout_seconds,
            )
        except Exception:
            daily_downloaded = None

    rows: list[dict[str, Any]] = []

    for symbol in valid_symbols:
        listing = symbol_to_listings[symbol][0]
        listing_id = str(listing.get("listing_id") or "").strip()
        entity_id = str(listing.get("entity_id") or "").strip()
        canonical_ticker = str(listing.get("canonical_ticker") or "").strip()

        frame = _symbol_frame(downloaded, symbol)
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

        close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
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

        # Restrict to intraday bars <= wall clock retrieval AND <= reference as_of
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
        quote_date = quote_timestamp.tz_localize(None).normalize()

        # Check daily bars fetched from provider or passed frame
        daily_frame = _symbol_frame(daily_downloaded, symbol) if daily_downloaded is not None else pd.DataFrame()
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
            prior_daily = daily_close.loc[
                daily_close.index.map(lambda idx: bool(_quote_timestamp(idx) is not None and _quote_timestamp(idx).tz_localize(None).normalize() < quote_date))
            ]
            if not prior_daily.empty:
                val = float(prior_daily.iloc[-1])
                if val > 0 and math.isfinite(val):
                    prev_close_val = val

        if prev_close_val is not None and prev_close_val > 0:
            day_change_pct = float(round((last_price - prev_close_val) / prev_close_val * 100.0, 4))

        # Defensible market status resolution: preserve unknown on failure or missing provider state
        market_status = "unknown"
        if download_fn_was_none:
            try:
                import yfinance as yf
                t = yf.Ticker(symbol)
                state_raw = str(t.info.get("marketState") or "").upper().strip()
                state_map = {
                    "REGULAR": "open",
                    "OPEN": "open",
                    "CLOSED": "closed",
                    "PRE": "pre_market",
                    "PREMARKET": "pre_market",
                    "POST": "post_market",
                    "POSTMARKET": "post_market",
                    "HOLIDAY": "holiday",
                }
                market_status = state_map.get(state_raw, "unknown")
            except Exception:
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
            "currency": str(listing.get("currency") or "").strip(),
            "market_status": market_status,
            "latency_class": latency_class,
            "source_id": source_id,
            "source_url": f"https://finance.yahoo.com/quote/{symbol}",
            "pit_class": "snapshot_from_delayed_source",
            "source_license_class": "personal_use_terms_unverified",
            "registry_version": str(listing.get("registry_version") or "v1").strip(),
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
        agg_status: Literal["available", "partial", "no_records", "unavailable"] = "available"
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
    )


def write_quote_snapshot(frame: pd.DataFrame, output_path: Path) -> Path:
    """Write a standardized quote input atomically for the local builder using a unique temp file."""

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    prepared = frame.reindex(columns=QUOTE_SNAPSHOT_COLUMNS)
    temp_filename = f".{output.name}.{uuid.uuid4().hex}.tmp"
    temporary = output.with_name(temp_filename)
    prepared.to_parquet(temporary, index=False)
    temporary.replace(output)
    return output


__all__ = [
    "QuoteCollectionResult",
    "QuoteDiagnostic",
    "collect_yfinance_quotes",
    "write_quote_snapshot",
]
