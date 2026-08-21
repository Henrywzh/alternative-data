#!/usr/bin/env python3
"""Collect daily price bars for the Research Control Tower.

``quote_snapshots`` answers "what is it worth now". This answers "what has it
done", which is what a price chart, an event window and any read-through from
a filing date to a market reaction all need.

Bars come from two places, chosen so that neither refetches what already
exists:

* the sibling ``financial-data`` repository's ``market_data_bars`` layer for
  the HK lines, whose ``security_id`` matches the listings registry's
  ``financial_data_security_id`` exactly -- the join the two repositories were
  built for. Nothing is downloaded for these.
* yfinance for the US lines, which are outside that repository's HK-only
  universe.

Both are adjusted-close-bearing daily bars from the same underlying vendor, so
they are labelled identically rather than being given a false distinction; the
``source_id`` records which path each row arrived by.

Usage::

    python scripts/research_control_tower_price_bars.py \
        --basket RESEARCH_STAGE_1_CHINA_INTERNET --years 5
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import glob
import hashlib
from pathlib import Path
import sys

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, REPO_ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from research_control_tower.build import (  # noqa: E402
    PRICE_BARS_ARROW_SCHEMA,
    PRICE_BARS_COLUMNS,
)
from research_control_tower.eligibility import filter_eligible_listings  # noqa: E402

FINANCIAL_DATA_BARS = (
    Path.home() / "Desktop" / "Quant" / "financial-data"
    / "data" / "processed" / "hk_financials" / "market_data_bars"
)
LICENSE_CLASS = "personal_use_terms_unverified"
# A daily bar is the vendor's own end-of-session record, not a vintage this
# repository captured and not a revision-tracked series.
PIT_CLASS = "current_vintage"


def _bar_id(listing_id: str, interval: str, day: object) -> str:
    return hashlib.sha256(f"{listing_id}\x1f{interval}\x1f{day}".encode("utf-8")).hexdigest()


def _active_interval_mask(frame: pd.DataFrame, as_of: datetime) -> pd.Series:
    """Apply the registry's half-open active interval to basket rows."""

    if frame.empty or not {"active_from", "active_to"}.issubset(frame.columns):
        return pd.Series(False, index=frame.index, dtype=bool)
    reference_date = pd.Timestamp(as_of).tz_convert("UTC").tz_localize(None).normalize()
    starts = pd.to_datetime(frame["active_from"], format="%Y-%m-%d", errors="coerce")
    ends = pd.to_datetime(frame["active_to"], format="%Y-%m-%d", errors="coerce")
    return starts.notna() & starts.le(reference_date) & (ends.isna() | (reference_date < ends))


def _rows_from_financial_data(listings: pd.DataFrame, cutoff: pd.Timestamp, now: datetime) -> tuple[list[dict], list[str]]:
    files = sorted(glob.glob(f"{FINANCIAL_DATA_BARS}/**/*.parquet", recursive=True))
    if not files:
        return [], [f"no market_data_bars under {FINANCIAL_DATA_BARS}"]
    frame = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    frame = frame.loc[frame["interval"].astype(str).eq("1d")]
    by_ticker = {str(r["canonical_ticker"]): r for _, r in listings.iterrows()}
    rows: list[dict] = []
    notes: list[str] = []
    for ticker, listing in by_ticker.items():
        subset = frame.loc[frame["ticker"].astype(str).eq(ticker)].copy()
        if subset.empty:
            continue
        subset["day"] = pd.to_datetime(subset["timestamp_utc"], errors="coerce", utc=True)
        subset = subset.loc[subset["day"].notna() & subset["day"].ge(cutoff)]
        # The same session can appear in more than one snapshot file; keep the
        # most recently sourced copy rather than emitting duplicate bars.
        subset = subset.sort_values("day").drop_duplicates(subset=["day"], keep="last")
        for _, bar in subset.iterrows():
            day = bar["day"].date()
            rows.append({
                "bar_id": _bar_id(str(listing["listing_id"]), "1d", day),
                "listing_id": str(listing["listing_id"]),
                "entity_id": str(listing["entity_id"]),
                "canonical_ticker": ticker,
                "provider_symbol": ticker,
                "interval": "1d",
                "bar_date": day,
                "open": _num(bar.get("open")),
                "high": _num(bar.get("high")),
                "low": _num(bar.get("low")),
                "close": _num(bar.get("close")),
                "adj_close": _num(bar.get("adj_close")),
                "volume": _int(bar.get("volume")),
                "currency": str(listing["currency"]),
                "source_id": "financial_data:market_data_bars",
                "source_url": str(bar.get("source_url") or ""),
                "retrieved_at_utc": now,
                "pit_class": PIT_CLASS,
                "source_license_class": LICENSE_CLASS,
                "registry_version": str(listing.get("registry_version") or "v1"),
            })
        notes.append(f"{ticker}: {len(subset)} bars from financial-data")
    return rows, notes


def _rows_from_yfinance(listings: pd.DataFrame, cutoff: pd.Timestamp, now: datetime) -> tuple[list[dict], list[str]]:
    import yfinance as yf

    rows: list[dict] = []
    notes: list[str] = []
    for _, listing in listings.iterrows():
        symbol = str(listing["canonical_ticker"]).removesuffix(".US")
        try:
            history = yf.Ticker(symbol).history(
                start=cutoff.date().isoformat(), interval="1d", auto_adjust=False
            )
        except Exception as exc:  # noqa: BLE001 - provider failures are reported
            notes.append(f"{symbol}: {type(exc).__name__}: {exc}")
            continue
        if history is None or history.empty:
            notes.append(f"{symbol}: no bars returned")
            continue
        for index, bar in history.iterrows():
            day = pd.Timestamp(index).date()
            rows.append({
                "bar_id": _bar_id(str(listing["listing_id"]), "1d", day),
                "listing_id": str(listing["listing_id"]),
                "entity_id": str(listing["entity_id"]),
                "canonical_ticker": str(listing["canonical_ticker"]),
                "provider_symbol": symbol,
                "interval": "1d",
                "bar_date": day,
                "open": _num(bar.get("Open")),
                "high": _num(bar.get("High")),
                "low": _num(bar.get("Low")),
                "close": _num(bar.get("Close")),
                "adj_close": _num(bar.get("Adj Close", bar.get("Close"))),
                "volume": _int(bar.get("Volume")),
                "currency": str(listing["currency"]),
                "source_id": "yfinance:history",
                "source_url": f"https://finance.yahoo.com/quote/{symbol}/history",
                "retrieved_at_utc": now,
                "pit_class": PIT_CLASS,
                "source_license_class": LICENSE_CLASS,
                "registry_version": str(listing.get("registry_version") or "v1"),
            })
        notes.append(f"{symbol}: {len(history)} bars from yfinance")
    return rows, notes


def _num(value: object) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(out) else out


def _int(value: object) -> int | None:
    out = _num(value)
    return None if out is None else int(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--listings", type=Path, default=REPO_ROOT / "config/research_control_tower/listings.csv")
    parser.add_argument(
        "--output", type=Path,
        default=REPO_ROOT / "data/normalized/research_control_tower/price_bars_v1.parquet",
    )
    parser.add_argument("--basket", default=None)
    parser.add_argument("--years", type=int, default=5)
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    cutoff = pd.Timestamp(now) - pd.DateOffset(years=args.years)

    listings = pd.read_csv(args.listings, keep_default_na=False)
    listings, rejected = filter_eligible_listings(listings, now)
    eligibility_notes = [
        "listing rejected by shared eligibility gate: "
        f"listing_id={item.get('listing_id') or '<blank>'} "
        f"entity_id={item.get('entity_id') or '<blank>'} "
        f"reason={item.get('reason')}"
        for item in rejected
    ]
    if args.basket:
        memberships = pd.read_csv(args.listings.parent / "basket_memberships.csv", keep_default_na=False)
        baskets_path = args.listings.parent / "baskets.csv"
        baskets = pd.read_csv(baskets_path, keep_default_na=False) if baskets_path.is_file() else pd.DataFrame()
        active_basket = baskets.loc[
            baskets.get("basket_id", pd.Series(dtype="object")).eq(args.basket)
            & _active_interval_mask(baskets, now)
        ]
        active_memberships = memberships.loc[
            memberships.get("basket_id", pd.Series(dtype="object")).eq(args.basket)
            & _active_interval_mask(memberships, now)
        ]
        if active_basket.empty:
            eligibility_notes.append(
                f"basket rejected by shared active interval gate: basket_id={args.basket}"
            )
        members = set(active_memberships.get("entity_id", pd.Series(dtype="object"))) if not active_basket.empty else set()
        listings = listings.loc[listings["entity_id"].isin(members)]

    hk = listings.loc[listings["canonical_ticker"].astype(str).str.endswith(".HK")]
    other = listings.loc[~listings["canonical_ticker"].astype(str).str.endswith(".HK")]
    print(f"listings: {len(hk)} HK (from financial-data), {len(other)} other (from yfinance)")

    fd_rows, fd_notes = _rows_from_financial_data(hk, cutoff, now)
    yf_rows, yf_notes = _rows_from_yfinance(other, cutoff, now)

    frame = pd.DataFrame(fd_rows + yf_rows, columns=PRICE_BARS_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(["listing_id", "bar_date"]).reset_index(drop=True)
    table = pa.Table.from_pandas(frame, schema=PRICE_BARS_ARROW_SCHEMA, preserve_index=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, args.output)

    print(f"\nbars written: {len(frame):,}")
    if not frame.empty:
        span = frame.groupby("canonical_ticker")["bar_date"].agg(["size", "min", "max"])
        print(span.to_string())
    for note in eligibility_notes + fd_notes + yf_notes:
        print(f"  {note}")
    print(f"\noutput: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
