from __future__ import annotations

import numpy as np
import pandas as pd


def build_weekly_mineral_signals(
    daily_prices: pd.DataFrame,
    price_universe: pd.DataFrame,
    *,
    week_end: str = "FRI",
) -> pd.DataFrame:
    if daily_prices.empty:
        return pd.DataFrame(
            columns=[
                "normalized_mineral_id",
                "mineral_name",
                "signal_date",
                "source_timestamp",
                "as_of_date",
                "signal_quality",
                "ret_4w",
                "ret_12w",
                "price_vs_12w_avg",
                "trend_score",
                "signal_state",
                "bullish",
                "price",
            ]
        )

    prices = daily_prices.copy()
    prices["date"] = pd.to_datetime(prices["date"], utc=False)
    price_universe_indexed = price_universe.set_index("normalized_mineral_id")
    records: list[pd.DataFrame] = []

    for mineral_id, mineral_prices in prices.groupby("normalized_mineral_id"):
        if mineral_id not in price_universe_indexed.index:
            continue
        meta = price_universe_indexed.loc[mineral_id]
        series = (
            mineral_prices.sort_values("date")
            .set_index("date")["price"]
            .resample(f"W-{week_end}")
            .last()
            .dropna()
        )
        if series.empty:
            continue
        frame = series.to_frame(name="price").reset_index()
        frame["normalized_mineral_id"] = mineral_id
        frame["mineral_name"] = meta["mineral_name"]
        frame["ret_4w"] = frame["price"].pct_change(4)
        frame["ret_12w"] = frame["price"].pct_change(12)
        frame["avg_12w"] = frame["price"].rolling(12, min_periods=4).mean()
        frame["price_vs_12w_avg"] = frame["price"] / frame["avg_12w"] - 1.0
        frame["signal_quality"] = np.where(meta["trackability_grade"] == "direct", "direct", meta["trackability_grade"])
        frame["trend_score"] = (
            frame["ret_4w"].fillna(0.0)
            + frame["ret_12w"].fillna(0.0)
            + frame["price_vs_12w_avg"].fillna(0.0)
        ) / 3.0
        frame["bullish"] = ((frame["ret_4w"] > 0) & (frame["ret_12w"] > 0)).astype(int)
        frame["signal_state"] = np.where(frame["bullish"] == 1, "bullish", "neutral")
        lag_days = int(meta["publish_lag_assumption_days"])
        frame["signal_date"] = frame["date"].dt.normalize()
        frame["source_timestamp"] = frame["signal_date"] + pd.to_timedelta(23, unit="h")
        frame["as_of_date"] = frame["signal_date"] + pd.to_timedelta(lag_days, unit="D")
        if not bool(meta["is_active_for_v1"]) and meta["trackability_grade"] != "proxy":
            frame["signal_state"] = "inactive"
            frame["bullish"] = 0
            frame["trend_score"] = np.nan
        records.append(frame)

    if not records:
        return pd.DataFrame()
    combined = pd.concat(records, ignore_index=True)
    return combined[
        [
            "normalized_mineral_id",
            "mineral_name",
            "signal_date",
            "source_timestamp",
            "as_of_date",
            "signal_quality",
            "ret_4w",
            "ret_12w",
            "price_vs_12w_avg",
            "trend_score",
            "signal_state",
            "bullish",
            "price",
        ]
    ].sort_values(["normalized_mineral_id", "signal_date"]).reset_index(drop=True)


def build_stock_weekly_signals(
    mineral_signals: pd.DataFrame,
    stock_mapping: pd.DataFrame,
) -> pd.DataFrame:
    if mineral_signals.empty or stock_mapping.empty:
        return pd.DataFrame()

    signal_rows = mineral_signals.loc[mineral_signals["signal_state"] != "inactive"].copy()
    if signal_rows.empty:
        return pd.DataFrame()
    signal_rows["mineral_weight"] = np.where(signal_rows["signal_quality"] == "direct", 1.0, 0.5)
    mapping_rows = stock_mapping.copy()
    mapping_rows["exposure_weight"] = np.where(mapping_rows["is_primary_exposure"], 1.0, 0.5)

    merged = mapping_rows.merge(signal_rows, on=["normalized_mineral_id", "mineral_name"], how="inner")
    merged["weighted_score"] = (
        merged["bullish"].astype(float) * merged["mineral_weight"] * merged["exposure_weight"]
    )
    merged["combined_weight"] = merged["mineral_weight"] * merged["exposure_weight"]

    grouped = (
        merged.groupby(["ticker_normalized", "market", "as_of_date"], as_index=False)
        .agg(
            stock_signal_score=("weighted_score", lambda values: float(np.sum(values))),
            total_weight=("combined_weight", lambda values: float(np.sum(values))),
            linked_mineral_count=("normalized_mineral_id", "nunique"),
            direct_signal_count=("signal_quality", lambda values: int((pd.Series(values) == "direct").sum())),
            proxy_signal_count=("signal_quality", lambda values: int((pd.Series(values) == "proxy").sum())),
        )
    )
    grouped["stock_signal_score"] = grouped["stock_signal_score"] / grouped["total_weight"]
    grouped["is_tradeable_signal"] = grouped["stock_signal_score"] > 0
    return grouped.drop(columns=["total_weight"]).sort_values(
        ["as_of_date", "ticker_normalized"]
    ).reset_index(drop=True)
