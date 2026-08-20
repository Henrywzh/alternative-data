"""Wrapper-layer premium / relative-premium / spread aggregation."""

from __future__ import annotations

import pandas as pd


def merge_premium(
    spot: pd.DataFrame,
    metadata: pd.DataFrame,
) -> pd.DataFrame:
    """Join Eastmoney ETF spot premium (premium_pct) to the metadata registry.

    Rows whose premium is missing stay present with NaNs (dashboard renders
    them as unavailable rather than fabricating a premium). Cross-border QDII
    premium should be interpreted with the caveat rendered by the builder.
    """
    if spot is None or spot.empty:
        spot = pd.DataFrame()
    if "ticker" not in spot.columns or spot.empty:
        spot_rows = pd.DataFrame(columns=["ticker", "premium_pct", "spread_bp"])
    else:
        # Copy before touching anything: this used to normalise spot["ticker"]
        # in place, mutating the caller's frame -- the same object the pipeline
        # had already written to the raw snapshot.
        spot_rows = spot.copy()
        if "markcap" in spot_rows.columns and "aum" not in spot_rows.columns:
            spot_rows["aum"] = spot_rows["markcap"]

    meta = metadata.copy()
    # Normalize ticker keys to bare 6-digit code on both sides.
    meta["ticker"] = meta["ticker"].astype(str).str.split(".").str[0].str.zfill(6)
    # markcap is deliberately not carried through: aum is derived from it just
    # above, so shipping both put two identical columns in the artifact under
    # different names, which is how "AUM" came to label a market-cap proxy.
    spot_cols = [c for c in ("ticker", "premium_pct", "market_price", "iopv", "turnover", "aum", "units", "bid", "ask", "spread_bp") if c in spot_rows.columns]
    if "ticker" in spot_rows.columns:
        spot_rows["ticker"] = spot_rows["ticker"].astype(str).str.zfill(6)
    merged = meta.merge(spot_rows[spot_cols], on="ticker", how="left")

    # The spot snapshot's size wins; the registry column is a manual override
    # slot that is None for every fund today. Written as .where rather than
    # .combine_first because combine_first concatenates internally, and against
    # an all-None registry column that raises the pandas empty-entry
    # concatenation FutureWarning on every single run.
    spot_aum = pd.to_numeric(merged["aum_y"], errors="coerce") if "aum_y" in merged.columns else None
    meta_aum = pd.to_numeric(merged["aum_x"], errors="coerce") if "aum_x" in merged.columns else None
    if spot_aum is not None and meta_aum is not None:
        resolved = spot_aum.where(spot_aum.notna(), meta_aum)
    else:
        resolved = spot_aum if spot_aum is not None else meta_aum
    if resolved is None and "aum" in merged.columns:
        resolved = pd.to_numeric(merged["aum"], errors="coerce")
    if resolved is not None:
        merged["aum"] = resolved
        merged["aum_proxy"] = resolved
    merged.drop(columns=[c for c in ("aum_x", "aum_y") if c in merged.columns], inplace=True)
    if "premium_pct" not in merged.columns:
        merged["premium_pct"] = float("nan")

    # Relative premium: premium vs same-index median. The notna guard is not
    # cosmetic -- an unquoted cohort makes .median() call nanmean on an all-NaN
    # slice, which emits a RuntimeWarning on every ordinary run and produces
    # the same all-NaN result either way.
    merged["relative_premium_pct"] = merged.groupby("exposure_id")["premium_pct"].transform(
        lambda s: s - s.median() if s.notna().any() else s
    )
    return merged.sort_values(["exposure_id", "fund_id"]).reset_index(drop=True)


def fill_premium_from_last_close(merged: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Price a wrapper the live feed forgot to refresh, using its last close.

    Eastmoney stamps every spot row with its own update time, and a fund the
    feed has not touched since before the open comes back with an IOPV but no
    last price -- 513100 国泰纳斯达克100ETF sat at 08:30 while its peers were
    at 10:02. Premium then cannot be computed, the row reads UNAVAILABLE, and
    a fund with 20.8bn under management drops to rank 99 over a stale quote.

    The premium definition does not change: it is still market price against
    IOPV. Only the price changes, from a live quote to the last one the market
    actually printed, and ``premium_basis`` says which was used.
    """
    out = merged.copy()
    if "premium_basis" not in out.columns:
        out["premium_basis"] = pd.Series(
            ["live" if pd.notna(value) else None for value in out.get("premium_pct", pd.Series(dtype=float))],
            index=out.index,
        )
    if prices is None or prices.empty or "fund_id" not in prices.columns or "iopv" not in out.columns:
        return out

    latest_close = (
        prices.sort_values("date")
        .groupby(prices["fund_id"].astype(str).str.zfill(6))["close"]
        .last()
    )
    keys = out["ticker"].astype(str).str.zfill(6) if "ticker" in out.columns else out["fund_id"].astype(str).str.zfill(6)
    fallback_price = keys.map(latest_close)

    iopv = pd.to_numeric(out["iopv"], errors="coerce")
    premium = pd.to_numeric(out["premium_pct"], errors="coerce")
    # Only rows the feed left unpriced, and only where there is something to
    # price against. A missing IOPV is a genuine absence, not a stale quote.
    recoverable = premium.isna() & iopv.gt(0) & fallback_price.notna()
    if not recoverable.any():
        return out

    out.loc[recoverable, "market_price"] = fallback_price[recoverable]
    out.loc[recoverable, "premium_pct"] = (
        (fallback_price[recoverable] / iopv[recoverable] - 1.0) * 100.0
    ).round(2)
    out.loc[recoverable, "premium_basis"] = "last_close"
    out["relative_premium_pct"] = out.groupby("exposure_id")["premium_pct"].transform(
        lambda s: s - s.median() if s.notna().any() else s
    )
    return out
