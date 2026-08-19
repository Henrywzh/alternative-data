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
        spot["ticker"] = spot["ticker"].astype(str).str.zfill(6)
        spot_rows = spot.copy()

    meta = metadata.copy()
    # Normalize ticker keys to bare 6-digit code on both sides.
    meta["ticker"] = meta["ticker"].astype(str).str.split(".").str[0].str.zfill(6)
    spot_cols = [c for c in ("ticker", "premium_pct", "market_price", "iopv", "turnover", "aum", "units", "markcap") if c in spot_rows.columns]
    if "ticker" in spot_rows.columns:
        spot_rows["ticker"] = spot_rows["ticker"].astype(str).str.zfill(6)
    merged = meta.merge(spot_rows[spot_cols], on="ticker", how="left")
    if "premium_pct" not in merged.columns:
        merged["premium_pct"] = float("nan")

    # Relative premium: premium vs same-index median.
    merged["relative_premium_pct"] = merged.groupby("exposure_id")["premium_pct"].transform(
        lambda s: s - s.median()
    )
    return merged.sort_values(["exposure_id", "fund_id"]).reset_index(drop=True)
