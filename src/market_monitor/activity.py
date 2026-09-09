"""Derived ETF scale and estimated creation/redemption activity."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .config import (
    ETF_ACTIVITY_METHOD_SHARE_DELTA_NAV,
    ETF_ACTIVITY_METHOD_SHARE_DELTA_NO_NAV,
    ETF_ACTIVITY_STATUS_INSUFFICIENT_HISTORY,
    ETF_ACTIVITY_STATUS_SHARES_ONLY,
    ETF_ACTIVITY_STATUS_VALIDATED,
)


ACTIVITY_COLUMNS = (
    "observation_date",
    "fund_id",
    "exposure_id",
    "index_id",
    "fund_name",
    "venue",
    "shares_outstanding",
    "shares_change",
    "prior_observation_date",
    "observation_gap_days",
    "nav",
    "aum_nav_estimate_cny",
    "estimated_flow_cny",
    "flow_pct_aum",
    "flow_method",
    "flow_status",
    "source",
    "source_observed_date",
    "retrieved_at_utc",
    "observation_type",
)


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=ACTIVITY_COLUMNS)


def _fund_id(values: pd.Series) -> pd.Series:
    return values.astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)


def _nav_from_premium_history(
    premium_history: pd.DataFrame | None,
    prices: pd.DataFrame | None,
) -> pd.DataFrame:
    if premium_history is None or premium_history.empty or prices is None or prices.empty:
        return pd.DataFrame(columns=["fund_id", "observation_date", "nav"])
    if not {"date", "premium_pct"}.issubset(premium_history.columns):
        return pd.DataFrame(columns=["fund_id", "observation_date", "nav"])
    ph = premium_history.copy()
    if "fund_id" not in ph.columns and "ticker" in ph.columns:
        ph["fund_id"] = ph["ticker"]
    if "fund_id" not in ph.columns:
        return pd.DataFrame(columns=["fund_id", "observation_date", "nav"])
    ph["fund_id"] = _fund_id(ph["fund_id"])
    ph["observation_date"] = pd.to_datetime(ph["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    ph["premium_pct"] = pd.to_numeric(ph["premium_pct"], errors="coerce")
    basis = ph.get("basis", pd.Series("unknown", index=ph.index)).astype(str)
    price = prices.copy()
    if "fund_id" not in price.columns or "date" not in price.columns or "close" not in price.columns:
        return pd.DataFrame(columns=["fund_id", "observation_date", "nav"])
    price["fund_id"] = _fund_id(price["fund_id"])
    price["observation_date"] = pd.to_datetime(price["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    price["close"] = pd.to_numeric(price["close"], errors="coerce")
    joined = ph[["fund_id", "observation_date", "premium_pct"]].copy()
    joined["basis"] = basis
    joined = joined.merge(
        price[["fund_id", "observation_date", "close"]],
        on=["fund_id", "observation_date"],
        how="inner",
    )
    joined = joined[(joined["basis"] == "nav") & (joined["close"] > 0)]
    joined["nav"] = joined["close"] / (1.0 + joined["premium_pct"] / 100.0)
    return joined[["fund_id", "observation_date", "nav"]].dropna(subset=["nav"]).drop_duplicates(
        ["fund_id", "observation_date"], keep="last"
    )


def build_etf_fund_activity(
    shares: pd.DataFrame | None,
    metadata: pd.DataFrame,
    *,
    prices: pd.DataFrame | None = None,
    premium_history: pd.DataFrame | None = None,
    previous: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Merge official shares with prior observations and derive flow metrics.

    A flow is validated only when two observations exist for a fund and a
    same-date published NAV can be reconstructed from the existing NAV-backed
    premium history.  Missing NAV is intentionally retained as a shares-only
    row so the UI can explain why a currency flow is unavailable.
    """
    frames: list[pd.DataFrame] = []
    if previous is not None and not previous.empty:
        keep = [
            column
            for column in (
                "observation_date",
                "fund_id",
                "venue",
                "shares_outstanding",
                "fund_name",
                "source",
                "source_observed_date",
                "retrieved_at_utc",
                "observation_type",
            )
            if column in previous.columns
        ]
        if {"observation_date", "fund_id", "shares_outstanding"}.issubset(keep):
            frames.append(previous[keep].copy())
    if shares is not None and not shares.empty:
        frames.append(shares.copy())
    if not frames or metadata is None or metadata.empty:
        return _empty()

    observed = pd.concat(frames, ignore_index=True)
    observed["fund_id"] = _fund_id(observed["fund_id"])
    observed["observation_date"] = pd.to_datetime(
        observed["observation_date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    observed["shares_outstanding"] = pd.to_numeric(
        observed["shares_outstanding"], errors="coerce"
    )
    observed = observed.dropna(subset=["fund_id", "observation_date", "shares_outstanding"])
    observed = observed.drop_duplicates(["fund_id", "observation_date"], keep="last")
    if "fund_name" not in observed.columns:
        observed["fund_name"] = pd.NA

    meta = metadata.copy()
    meta["fund_id"] = _fund_id(meta["fund_id"])
    meta = meta.drop_duplicates("fund_id")
    observed = observed.merge(
        meta[["fund_id", "exposure_id", "index_id", "fund_name"]],
        on="fund_id",
        how="inner",
        suffixes=("", "_registry"),
    )
    registry_names = observed.get("fund_name_registry")
    if registry_names is not None:
        observed["fund_name"] = observed["fund_name"].fillna(registry_names)
    observed = observed.sort_values(["fund_id", "observation_date"]).reset_index(drop=True)
    grouped = observed.groupby("fund_id", sort=False)
    observed["shares_change"] = grouped["shares_outstanding"].diff()
    observed["prior_observation_date"] = grouped["observation_date"].shift(1)
    current_dates = pd.to_datetime(observed["observation_date"], errors="coerce")
    prior_dates = pd.to_datetime(observed["prior_observation_date"], errors="coerce")
    observed["observation_gap_days"] = (current_dates - prior_dates).dt.days

    nav = _nav_from_premium_history(premium_history, prices)
    observed = observed.merge(nav, on=["fund_id", "observation_date"], how="left")
    observed["aum_nav_estimate_cny"] = observed["shares_outstanding"] * observed["nav"]
    observed["estimated_flow_cny"] = observed["shares_change"] * observed["nav"]
    observed["flow_pct_aum"] = (
        observed["estimated_flow_cny"] / observed["aum_nav_estimate_cny"] * 100.0
    ).where(observed["aum_nav_estimate_cny"] > 0)
    has_change = observed["shares_change"].notna()
    has_nav = observed["nav"].notna() & observed["nav"].gt(0)
    observed["flow_method"] = ETF_ACTIVITY_METHOD_SHARE_DELTA_NO_NAV
    observed.loc[has_nav, "flow_method"] = ETF_ACTIVITY_METHOD_SHARE_DELTA_NAV
    observed["flow_status"] = ETF_ACTIVITY_STATUS_INSUFFICIENT_HISTORY
    observed.loc[has_change, "flow_status"] = ETF_ACTIVITY_STATUS_SHARES_ONLY
    observed.loc[has_change & has_nav, "flow_status"] = ETF_ACTIVITY_STATUS_VALIDATED

    for column in ACTIVITY_COLUMNS:
        if column not in observed.columns:
            observed[column] = pd.NA
    return observed[list(ACTIVITY_COLUMNS)].sort_values(
        ["fund_id", "observation_date"]
    ).reset_index(drop=True)
