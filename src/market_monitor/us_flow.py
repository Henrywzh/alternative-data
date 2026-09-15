"""Derived US ETF flow proxies from co-timed market-cap snapshots."""

from __future__ import annotations

from typing import Any

import pandas as pd


FLOW_COLUMNS = (
    "observation_date",
    "ticker",
    "last_price",
    "market_cap",
    "shares_outstanding",
    "shares_change",
    "prior_observation_date",
    "observation_gap_days",
    "estimated_flow",
    "flow_status",
    "shares_basis",
    "size_value",
    "size_basis",
    "currency",
    "source",
    "source_observed_date",
    "retrieved_at_utc",
    "observation_type",
)


def _clean_snapshot(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["observation_date", "ticker", "last_price", "market_cap"])
    out = frame.copy()
    if "date" in out.columns and "observation_date" not in out.columns:
        out["observation_date"] = out["date"]
    required = {"observation_date", "ticker", "last_price", "market_cap"}
    if not required.issubset(out.columns):
        return pd.DataFrame(columns=sorted(required))
    out["observation_date"] = pd.to_datetime(out["observation_date"], errors="coerce")
    out["ticker"] = out["ticker"].astype(str).str.strip().str.upper()
    for col in ("last_price", "market_cap"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["observation_date", "ticker", "last_price", "market_cap"])
    out = out[(out["last_price"] > 0) & (out["market_cap"] > 0)]
    return out.sort_values(["ticker", "observation_date"], kind="mergesort").drop_duplicates(
        ["ticker", "observation_date"], keep="last"
    )


def build_us_proxy_flow(
    current: pd.DataFrame,
    previous: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Estimate ETF flow as share change times the current sampled price.

    This is a market-cap proxy, not an issuer-reported creation/redemption
    series.  The first observation for each ticker remains explicitly
    ``insufficient_history`` and repeated/stale dates are ``unavailable``.
    """
    current_clean = _clean_snapshot(current)
    previous_clean = _clean_snapshot(previous)
    previous_latest = (
        previous_clean.sort_values("observation_date")
        .groupby("ticker", as_index=False, sort=False)
        .tail(1)
        .set_index("ticker")
        if not previous_clean.empty
        else pd.DataFrame()
    )

    rows: list[dict[str, Any]] = []
    for _, row in current_clean.sort_values(["observation_date", "ticker"]).iterrows():
        ticker = str(row["ticker"])
        obs_date = pd.Timestamp(row["observation_date"])
        price = float(row["last_price"])
        market_cap = float(row["market_cap"])
        shares = market_cap / price
        status = "insufficient_history"
        prior_date: pd.Timestamp | None = None
        shares_change: float | None = None
        estimated_flow: float | None = None
        gap_days: int | None = None

        if not previous_latest.empty and ticker in previous_latest.index:
            prior = previous_latest.loc[ticker]
            prior_date = pd.Timestamp(prior["observation_date"])
            prior_price = float(prior["last_price"])
            prior_market_cap = float(prior["market_cap"])
            if obs_date <= prior_date:
                status = "unavailable"
            elif prior_price <= 0 or prior_market_cap <= 0:
                status = "unavailable"
            else:
                prior_shares = prior_market_cap / prior_price
                shares_change = shares - prior_shares
                estimated_flow = shares_change * price
                gap_days = int((obs_date - prior_date).days)
                status = "validated_proxy"

        output: dict[str, Any] = row.to_dict()
        output.update(
            {
                "observation_date": obs_date.strftime("%Y-%m-%d"),
                "ticker": ticker,
                "last_price": price,
                "market_cap": market_cap,
                "shares_outstanding": shares,
                "shares_change": shares_change,
                "prior_observation_date": prior_date.strftime("%Y-%m-%d") if prior_date is not None else None,
                "observation_gap_days": gap_days,
                "estimated_flow": estimated_flow,
                "flow_status": status,
                "shares_basis": "market_cap_proxy",
                "size_value": market_cap,
                "size_basis": "market_cap_proxy",
                "currency": "USD",
            }
        )
        rows.append(output)

    if not rows:
        return pd.DataFrame(columns=FLOW_COLUMNS)
    result = pd.DataFrame(rows)
    for col in FLOW_COLUMNS:
        if col not in result.columns:
            result[col] = pd.NA
    return result[list(FLOW_COLUMNS)]
