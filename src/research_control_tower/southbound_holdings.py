"""Per-listing southbound Stock Connect holdings for Control Tower.

This is not the 2014-onward market-wide southbound flow. It is the Eastmoney
individual ownership series via akshare ``stock_hsgt_individual_em``. HKEX
listings derive their 5-digit security code from ``native_ticker``; no
company-specific profile is required.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.market_monitor.sources.eastmoney_hsgt import fetch_southbound_individual

SOUTHBOUND_COLUMNS = [
    "hold_date",
    "close",
    "day_change_pct",
    "holding_shares",
    "holding_market_value",
    "holding_share_pct",
    "holding_mv_change_1d",
    "holding_mv_change_5d",
    "holding_mv_change_10d",
    "entity_id",
    "listing_id",
    "canonical_ticker",
    "security_code",
    "source_id",
    "source_url",
    "retrieved_at_utc",
]


@dataclass(frozen=True)
class SouthboundCollectResult:
    frame: pd.DataFrame
    status: str
    detail: str
    security_code: str
    path: Path | None = None


def hkex_security_code(native_ticker: object, canonical_ticker: object = "") -> str:
    raw = str(native_ticker or "").strip()
    if not raw:
        raw = str(canonical_ticker or "").replace(".HK", "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    return digits.zfill(5)


def southbound_mart_path(repo_root: Path, listing_id: str) -> Path:
    return repo_root / "data" / "normalized" / "marts" / f"{str(listing_id).lower()}_southbound_holdings.parquet"


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=SOUTHBOUND_COLUMNS)


def collect_listing_southbound(
    listing: pd.Series | dict[str, Any],
    *,
    fetch_fn=fetch_southbound_individual,
) -> SouthboundCollectResult:
    entity_id = str(listing.get("entity_id") or "").strip()
    listing_id = str(listing.get("listing_id") or "").strip()
    canonical = str(listing.get("canonical_ticker") or "").strip()
    code = hkex_security_code(listing.get("native_ticker"), canonical)
    if not listing_id or not code:
        return SouthboundCollectResult(_empty(), "unavailable", "listing is missing an HKEX security code", code)
    try:
        raw = fetch_fn(code)
    except Exception as exc:  # network/provider failures stay listing-scoped
        return SouthboundCollectResult(_empty(), "error", f"{type(exc).__name__}: {exc}", code)
    if raw is None or raw.empty:
        return SouthboundCollectResult(_empty(), "unavailable", f"no southbound individual rows for {code}", code)
    frame = raw.copy()
    frame["entity_id"] = entity_id
    frame["listing_id"] = listing_id
    frame["canonical_ticker"] = canonical or f"{code[1:]}.HK"
    frame["security_code"] = code
    for column in SOUTHBOUND_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame = frame.loc[:, SOUTHBOUND_COLUMNS]
    frame["hold_date"] = pd.to_datetime(frame["hold_date"], errors="coerce")
    frame = frame.dropna(subset=["hold_date"]).sort_values("hold_date").reset_index(drop=True)
    return SouthboundCollectResult(frame, "available", f"{len(frame)} daily rows for {code}", code)


def write_listing_southbound(
    result: SouthboundCollectResult,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    result.frame.to_parquet(path, index=False)
    return path


def collect_stage1_southbound(
    listings: pd.DataFrame,
    *,
    repo_root: Path,
    fetch_fn=fetch_southbound_individual,
) -> list[SouthboundCollectResult]:
    results: list[SouthboundCollectResult] = []
    hk = listings.copy()
    if "exchange" in hk.columns:
        hk = hk.loc[hk["exchange"].astype("string").str.upper().eq("HKEX")]
    for _, listing in hk.iterrows():
        result = collect_listing_southbound(listing, fetch_fn=fetch_fn)
        if result.status == "available" and not result.frame.empty:
            path = southbound_mart_path(repo_root, str(listing["listing_id"]))
            write_listing_southbound(result, path)
            result = SouthboundCollectResult(result.frame, result.status, result.detail, result.security_code, path)
        results.append(result)
    return results
