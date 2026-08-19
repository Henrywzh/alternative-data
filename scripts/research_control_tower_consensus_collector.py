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

Usage::

    python scripts/research_control_tower_consensus_collector.py \
        --listings config/research_control_tower/listings.csv \
        --output-dir data/normalized/research_control_tower/consensus
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys
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


def _write(rows: list[dict], schema: pa.Schema, path: Path) -> int:
    frame = pd.DataFrame(rows, columns=[field.name for field in schema])
    table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
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

    snapshots = yf_snapshots + fd_snapshots
    health = [
        {
            "provider": "yfinance",
            "status": "available" if yf_snapshots else "unavailable",
            "reason": "; ".join(yf_notes) or "live analyst estimates collected",
            "row_count": len(yf_snapshots) + len(yf_revisions),
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
            "reason": "; ".join(fd_notes) or f"akshare consensus export read from {FINANCIAL_DATA_ROOT.name}",
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
    n_rev = _write(yf_revisions, TASK3_REVISION_ARROW_SCHEMA, out / "control_tower_consensus_revisions.parquet")
    n_health = _write(health, TASK3_HEALTH_ARROW_SCHEMA, out / "control_tower_consensus_source_health.parquet")

    print(f"\nsnapshots : {n_snap:>4d}  (yfinance {len(yf_snapshots)}, akshare {len(fd_snapshots)})")
    print(f"revisions : {n_rev:>4d}  (reconstructed from eps_trend at 7/30/60/90 days)")
    print(f"health    : {n_health:>4d}")
    aligned = sum(1 for row in snapshots if row["fiscal_year"] is not None)
    print(f"fiscal-period aligned: {aligned}/{len(snapshots)}")
    for note in yf_notes + fd_notes:
        print(f"  note: {note}")
    print(f"\noutput: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
