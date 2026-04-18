from __future__ import annotations

import numpy as np
import pandas as pd

from .clean import clean_model_id, to_datetime


def latest_pricing_snapshot(models: pd.DataFrame) -> pd.DataFrame:
    if models.empty:
        return pd.DataFrame(
            columns=["model_id", "pricing_snapshot_ts", "pricing_prompt", "pricing_completion", "context_length"]
        )

    pricing = models.copy()
    pricing["model_id"] = clean_model_id(pricing["model_id"])
    pricing["snapshot_ts"] = to_datetime(pricing["snapshot_ts"], utc=True)
    pricing = pricing.dropna(subset=["model_id", "snapshot_ts"]).sort_values(["model_id", "snapshot_ts"])
    latest = pricing.groupby("model_id", as_index=False).tail(1).copy()
    latest = latest.rename(columns={"snapshot_ts": "pricing_snapshot_ts"})
    latest = latest.rename(columns={"context_length": "openrouter_context_length"})
    return latest[
        ["model_id", "pricing_snapshot_ts", "pricing_prompt", "pricing_completion", "openrouter_context_length"]
    ].reset_index(drop=True)


def latest_huggingface_snapshot(models: pd.DataFrame) -> pd.DataFrame:
    if models.empty:
        return pd.DataFrame(
            columns=[
                "model_id",
                "hf_download_date",
                "hf_downloads_daily_est_latest",
                "hf_downloads_all_time_latest",
            ]
        )

    enriched = models.copy()
    enriched["model_id"] = clean_model_id(enriched["model_id"])
    enriched["download_date"] = to_datetime(enriched["download_date"])
    enriched = enriched.dropna(subset=["model_id", "download_date"]).sort_values(["model_id", "download_date"])
    latest = enriched.groupby("model_id", as_index=False).tail(1).copy()
    latest = latest.rename(
        columns={
            "download_date": "hf_download_date",
            "hf_downloads_daily_est": "hf_downloads_daily_est_latest",
            "hf_downloads_all_time": "hf_downloads_all_time_latest",
        }
    )
    return latest[
        [
            "model_id",
            "hf_download_date",
            "hf_downloads_daily_est_latest",
            "hf_downloads_all_time_latest",
        ]
    ].reset_index(drop=True)


def attach_asof_pricing(activity: pd.DataFrame, pricing: pd.DataFrame) -> pd.DataFrame:
    if activity.empty:
        return pd.DataFrame()

    usage = activity.copy()
    usage["model_permaslug"] = clean_model_id(usage["model_permaslug"])
    usage["usage_date_dt"] = to_datetime(usage["usage_date"])
    usage = usage.sort_values(["model_permaslug", "usage_date_dt"]).reset_index(drop=True)

    pricing_df = pricing.copy()
    pricing_df["model_id"] = clean_model_id(pricing_df["model_id"])
    pricing_df["snapshot_ts"] = to_datetime(pricing_df["snapshot_ts"], utc=True)
    pricing_df["pricing_effective_date"] = pricing_df["snapshot_ts"].dt.tz_convert(None).dt.normalize()
    pricing_df = pricing_df.dropna(subset=["model_id", "pricing_effective_date"]).sort_values(
        ["model_id", "pricing_effective_date", "snapshot_ts"]
    )
    pricing_df = pricing_df[
        ["model_id", "snapshot_ts", "pricing_effective_date", "pricing_prompt", "pricing_completion", "context_length"]
    ].copy()

    merged_groups: list[pd.DataFrame] = []
    empty_price_columns = [
        "pricing_effective_date",
        "pricing_snapshot_ts",
        "pricing_prompt",
        "pricing_completion",
        "pricing_context_length",
    ]
    for model_id, usage_group in usage.groupby("model_permaslug", dropna=False):
        model_prices = pricing_df[pricing_df["model_id"] == model_id].copy()
        if model_prices.empty:
            missing = usage_group.copy()
            for column in empty_price_columns:
                missing[column] = pd.NA
            merged_groups.append(missing)
            continue

        joined = pd.merge_asof(
            usage_group.sort_values("usage_date_dt"),
            model_prices.rename(
                columns={
                    "snapshot_ts": "pricing_snapshot_ts",
                    "context_length": "openrouter_context_length",
                }
            ).sort_values("pricing_effective_date"),
            left_on="usage_date_dt",
            right_on="pricing_effective_date",
            direction="backward",
        )
        merged_groups.append(joined)

    merged = pd.concat(merged_groups, ignore_index=True) if merged_groups else usage
    merged["pricing_join_status"] = np.where(
        merged["pricing_snapshot_ts"].isna(),
        "missing_snapshot",
        np.where(
            merged[["pricing_prompt", "pricing_completion"]].isna().all(axis=1),
            "missing_prices",
            "matched",
        ),
    )
    return merged


def attach_latest_pricing(activity: pd.DataFrame, pricing: pd.DataFrame) -> pd.DataFrame:
    if activity.empty:
        return pd.DataFrame()

    latest = latest_pricing_snapshot(pricing)
    merged = activity.copy()
    merged["model_permaslug"] = clean_model_id(merged["model_permaslug"])
    merged = merged.merge(
        latest.rename(columns={"model_id": "model_permaslug"}),
        on="model_permaslug",
        how="left",
    )
    merged["pricing_join_status"] = np.where(
        merged["pricing_snapshot_ts"].isna(),
        "missing_snapshot",
        np.where(
            merged[["pricing_prompt", "pricing_completion"]].isna().all(axis=1),
            "missing_prices",
            "matched",
        ),
    )
    return merged
