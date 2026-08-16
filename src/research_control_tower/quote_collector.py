"""Provider adapters for writing local quote snapshot inputs.

The Streamlit app never imports this module.  A scheduled process may call
collect_yfinance_quotes and write the resulting standardized parquet; the
normal Control Tower builder then consumes that local file with networking
disabled.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .build import QUOTE_SNAPSHOT_COLUMNS


DownloadFunction = Callable[..., pd.DataFrame]

STAGE1_PUBLIC_ENTITY_IDS = {
    "ALIBABA",
    "TENCENT",
    "BAIDU",
    "KUAISHOU",
    "BILIBILI",
}


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
    stage1_only: bool = True,
) -> pd.DataFrame:
    """Collect one latest minute-bar quote per eligible registry listing.

    yfinance is intentionally imported lazily and its output is labelled
    delayed by default.  The function does not claim bid/ask or exchange
    real-time entitlement when the free endpoint does not provide them.
    """

    if listings is None or listings.empty:
        return _empty_quote_frame()
    as_of = _quote_timestamp(as_of_utc) if as_of_utc is not None else pd.Timestamp.now(tz="UTC")
    if as_of is None:
        raise ValueError("as_of_utc must be a valid timestamp")

    eligible = listings.copy()
    for column, expected in (
        ("collection_eligible", True),
        ("mapping_status", "verified"),
        ("listing_status", "active"),
    ):
        if column not in eligible.columns:
            return _empty_quote_frame()
        if column == "collection_eligible":
            eligible = eligible.loc[eligible[column].fillna(False).astype(bool)]
        else:
            eligible = eligible.loc[eligible[column].astype("string").str.casefold().eq(expected)]
    if eligible.empty:
        return _empty_quote_frame()

    # Exclude private entities (e.g. ByteDance) if entity information is provided
    if entities is not None and not entities.empty and "entity_id" in entities.columns:
        private_entity_ids = set(
            entities.loc[
                entities.get("entity_type", pd.Series(dtype="string")).astype("string").str.casefold().eq("private"),
                "entity_id",
            ].astype("string")
        )
        if private_entity_ids:
            eligible = eligible.loc[~eligible["entity_id"].astype("string").isin(private_entity_ids)]

    if stage1_only and "entity_id" in eligible.columns:
        eligible = eligible.loc[eligible["entity_id"].astype("string").isin(STAGE1_PUBLIC_ENTITY_IDS)]

    if eligible.empty:
        return _empty_quote_frame()

    symbol_to_listings: dict[str, list[dict[str, Any]]] = {}
    for _, row in eligible.iterrows():
        symbol = _vendor_symbol(row, "yfinance")
        if not symbol:
            continue
        entity_type = str(row.get("entity_type") or "").strip().lower()
        if entity_type == "private":
            continue
        entity_id = str(row.get("entity_id") or "").strip()
        if entity_id == "BYTEDANCE":
            continue
        symbol_to_listings.setdefault(symbol, []).append(row.to_dict())

    # Exclude duplicate vendor symbols mapping to multiple listings
    symbols = sorted(symbol for symbol, rows in symbol_to_listings.items() if len(rows) == 1)
    if not symbols:
        return _empty_quote_frame()

    download_fn_was_none = download_fn is None
    if download_fn is None:
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover - depends on runtime extras
            raise RuntimeError("yfinance is required by the quote collector") from exc
        download_fn = yf.download

    downloaded = download_fn(
        symbols,
        period="1d",
        interval="1m",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        frame = _symbol_frame(downloaded, symbol)
        if frame.empty or "Close" not in frame.columns:
            continue
        close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
        if close.empty:
            continue
        last_index = close.index[-1]
        quote_timestamp = _quote_timestamp(last_index)
        last_price = float(close.iloc[-1])
        if quote_timestamp is None or quote_timestamp > as_of or not pd.notna(last_price):
            continue
        volume = pd.NA
        if "Volume" in frame.columns:
            candidate = pd.to_numeric(frame.loc[last_index, "Volume"], errors="coerce")
            if pd.notna(candidate):
                volume = float(candidate)

        # Produce defensible day change (do not use first intraday bar as previous close without explicit label)
        day_change_pct: float | object = pd.NA
        prev_close_val: float | None = None

        # Check for explicit Previous Close column in frame
        for col in ("Previous Close", "Prev Close", "Previous_Close"):
            if col in frame.columns:
                parsed_prev = pd.to_numeric(frame[col], errors="coerce").dropna()
                if not parsed_prev.empty and float(parsed_prev.iloc[-1]) > 0:
                    prev_close_val = float(parsed_prev.iloc[-1])
                    break

        # If live yfinance (download_fn was None), attempt ticker fast_info lookup for previousClose
        if prev_close_val is None and download_fn_was_none:
            try:
                import yfinance as yf
                t = yf.Ticker(symbol)
                fast_prev = getattr(t.fast_info, "previous_close", None)
                if fast_prev is not None and pd.notna(fast_prev) and float(fast_prev) > 0:
                    prev_close_val = float(fast_prev)
            except Exception:
                pass

        if prev_close_val is not None and prev_close_val > 0:
            day_change_pct = float(round((last_price - prev_close_val) / prev_close_val * 100.0, 4))

        # Determine market status
        market_status = "unknown"
        if download_fn_was_none:
            try:
                import yfinance as yf
                t = yf.Ticker(symbol)
                state = str(t.info.get("marketState") or "").upper()
                state_map = {"REGULAR": "open", "CLOSED": "closed", "PRE": "pre_market", "POST": "post_market"}
                market_status = state_map.get(state, "closed")
            except Exception:
                market_status = "closed"

        listing = symbol_to_listings[symbol][0]
        listing_id = str(listing.get("listing_id") or "").strip()
        canonical_ticker = str(listing.get("canonical_ticker") or "").strip()
        rows.append({
            "quote_id": f"quote_{listing_id}_{quote_timestamp.strftime('%Y%m%dT%H%M%S')}_yfinance",
            "listing_id": listing_id,
            "canonical_ticker": canonical_ticker,
            "provider_symbol": symbol,
            "quote_timestamp": quote_timestamp,
            "retrieved_at_utc": as_of,
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
            "source_license_class": "public_metadata",
            "registry_version": str(listing.get("registry_version") or "v1").strip(),
        })
    return pd.DataFrame(rows, columns=QUOTE_SNAPSHOT_COLUMNS) if rows else _empty_quote_frame()


def write_quote_snapshot(frame: pd.DataFrame, output_path: Path) -> Path:
    """Write a standardized quote input atomically for the local builder."""

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    prepared = frame.reindex(columns=QUOTE_SNAPSHOT_COLUMNS)
    temporary = output.with_name(f".{output.name}.tmp")
    prepared.to_parquet(temporary, index=False)
    temporary.replace(output)
    return output


__all__ = [
    "collect_yfinance_quotes",
    "write_quote_snapshot",
]
