from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from openrouter_official_data.storage import DATASET_SPECS


SHARE_COLUMNS = {
    "usage_share",
    "token_share",
    "category_usage_share",
    "category_token_share",
    "tag_usage_share",
    "tag_token_share",
}

MINIMUM_DAILY_RANKING_ROWS = 40


def validate_dataset(dataset_id: str, frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        raise ValueError(f"{dataset_id} is empty")
    keys = DATASET_SPECS[dataset_id]["keys"]
    missing_keys = [column for column in keys if column not in frame.columns]
    if missing_keys:
        raise ValueError(f"{dataset_id} missing natural keys: {', '.join(missing_keys)}")
    duplicate_rows = int(frame.duplicated(subset=keys).sum())
    if duplicate_rows:
        raise ValueError(f"{dataset_id} contains {duplicate_rows} duplicate natural keys")

    for column in ("total_tokens", "total_requests"):
        if column in frame.columns:
            numeric = pd.to_numeric(frame[column], errors="coerce")
            if bool((numeric.dropna() < 0).any()):
                raise ValueError(f"{dataset_id}.{column} contains negative values")
    for column in SHARE_COLUMNS & set(frame.columns):
        numeric = pd.to_numeric(frame[column], errors="coerce").dropna()
        if bool(((numeric < 0) | (numeric > 1)).any()):
            raise ValueError(f"{dataset_id}.{column} contains values outside [0, 1]")

    if dataset_id == "official_model_rankings_daily":
        filter_columns = [
            column
            for column in ("modality", "context_bucket", "category", "language_type")
            if column in frame.columns
        ]
        grouped = frame.groupby(["usage_date", "period", *filter_columns], dropna=False)
        if int(grouped.size().max()) > 51:
            raise ValueError("official_model_rankings_daily has more than top 50 + Other for a date")
        other_counts = grouped["is_other"].sum()
        if bool((other_counts > 1).any()):
            raise ValueError("official_model_rankings_daily has multiple Other rows for a date")

    date_column = next(
        (column for column in ("usage_date", "snapshot_date", "window_end_date") if column in frame.columns),
        None,
    )
    return {
        "dataset_id": dataset_id,
        "row_count": len(frame),
        "first_date": str(frame[date_column].dropna().min()) if date_column and frame[date_column].notna().any() else None,
        "latest_date": str(frame[date_column].dropna().max()) if date_column and frame[date_column].notna().any() else None,
        "duplicate_rows": duplicate_rows,
        "status": "ok",
    }


def validate_rankings_coverage(
    frame: pd.DataFrame,
    *,
    expected_start_date: str,
    expected_end_date: str,
    minimum_rows: int = MINIMUM_DAILY_RANKING_ROWS,
) -> None:
    """Reject successful-but-empty, stale, or partial core ranking payloads."""

    if frame.empty:
        raise ValueError("official_model_rankings_daily core payload is empty")
    dates = pd.to_datetime(frame["usage_date"], errors="coerce").dt.normalize()
    if dates.isna().any():
        raise ValueError("official_model_rankings_daily contains invalid usage dates")
    expected = pd.date_range(expected_start_date, expected_end_date, freq="D")
    observed = pd.DatetimeIndex(sorted(dates.unique()))
    missing = expected.difference(observed)
    if len(missing):
        preview = ", ".join(value.date().isoformat() for value in missing[:5])
        raise ValueError(f"official_model_rankings_daily missing expected dates: {preview}")

    checked = frame.assign(_usage_date=dates)
    grouped = checked.groupby("_usage_date", dropna=False)
    row_counts = grouped.size()
    too_small = row_counts[row_counts < minimum_rows]
    if not too_small.empty:
        details = ", ".join(f"{date.date().isoformat()}={count}" for date, count in too_small.items())
        raise ValueError(f"official_model_rankings_daily has partial date partitions: {details}")
    other_counts = grouped["is_other"].sum()
    invalid_other = other_counts[other_counts != 1]
    if not invalid_other.empty:
        details = ", ".join(f"{date.date().isoformat()}={count}" for date, count in invalid_other.items())
        raise ValueError(f"official_model_rankings_daily requires exactly one Other row per date: {details}")

    named = checked[~checked["is_other"].fillna(False)]
    duplicate_ranks = named.duplicated(["_usage_date", "rank"], keep=False) & named["rank"].notna()
    if bool(duplicate_ranks.any()):
        raise ValueError("official_model_rankings_daily contains duplicate named-model ranks")


def _deduplicated_model_activity(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    working = frame[["usage_date", "model_permaslug", "category_slug", "total_tokens"]].copy()
    working["total_tokens"] = pd.to_numeric(working["total_tokens"], errors="coerce").fillna(0.0)
    all_rows = working[working["category_slug"].astype("string").fillna("all") == "all"]
    detailed = working[~working.index.isin(all_rows.index)]
    detailed = detailed.groupby(["usage_date", "model_permaslug"], as_index=False)["total_tokens"].sum()
    if all_rows.empty:
        return detailed
    all_rows = all_rows.groupby(["usage_date", "model_permaslug"], as_index=False)["total_tokens"].sum()
    detail_keys = set(zip(all_rows["usage_date"].astype(str), all_rows["model_permaslug"].astype(str)))
    detailed = detailed[
        ~pd.Series(
            list(zip(detailed["usage_date"].astype(str), detailed["model_permaslug"].astype(str))),
            index=detailed.index,
        ).isin(detail_keys)
    ]
    return pd.concat([all_rows, detailed], ignore_index=True)


def build_legacy_reconciliation(base_dir: Path, official: pd.DataFrame) -> pd.DataFrame:
    """Measure overlap without treating partial legacy sources as equivalent totals."""
    if official.empty:
        return pd.DataFrame()
    named = official[~official["is_other"].fillna(False)].copy()
    named["total_tokens"] = pd.to_numeric(named["total_tokens"], errors="coerce").fillna(0.0)
    other = official[official["is_other"].fillna(False)].groupby("usage_date")["total_tokens"].sum()
    totals = official.groupby("usage_date")["total_tokens"].sum().rename("official_total_tokens")
    result = pd.concat(
        [
            totals,
            named.groupby("usage_date")["total_tokens"].sum().rename("official_named_tokens"),
            other.rename("official_other_tokens"),
        ],
        axis=1,
    ).fillna(0.0).reset_index()

    legacy_root = base_dir / "data" / "normalized" / "openrouter"
    activity_path = legacy_root / "openrouter_model_activity.parquet"
    provider_path = legacy_root / "provider_daily_activity.parquet"

    if activity_path.exists():
        activity = _deduplicated_model_activity(
            pd.read_parquet(activity_path, columns=["usage_date", "model_permaslug", "category_slug", "total_tokens"])
        )
        activity = activity.rename(columns={"total_tokens": "legacy_model_tokens"})
        matched = named.merge(activity, on=["usage_date", "model_permaslug"], how="left")
        matched["legacy_model_tokens"] = matched["legacy_model_tokens"].fillna(0.0)
        overlap = matched.groupby("usage_date").agg(
            official_models=("model_permaslug", "nunique"),
            matched_activity_models=("legacy_model_tokens", lambda values: int((values > 0).sum())),
            official_tokens_with_activity_match=("total_tokens", lambda values: float(values[matched.loc[values.index, "legacy_model_tokens"] > 0].sum())),
            legacy_activity_tokens_on_official_models=("legacy_model_tokens", "sum"),
        ).reset_index()
        result = result.merge(overlap, on="usage_date", how="left")

    if provider_path.exists():
        provider = pd.read_parquet(provider_path, columns=["usage_date", "model_permaslug", "total_tokens"])
        provider["total_tokens"] = pd.to_numeric(provider["total_tokens"], errors="coerce").fillna(0.0)
        provider = provider.groupby(["usage_date", "model_permaslug"], as_index=False)["total_tokens"].sum()
        provider = provider.rename(columns={"total_tokens": "legacy_provider_tokens"})
        matched = named.merge(provider, on=["usage_date", "model_permaslug"], how="left")
        matched["legacy_provider_tokens"] = matched["legacy_provider_tokens"].fillna(0.0)
        overlap = matched.groupby("usage_date").agg(
            matched_provider_models=("legacy_provider_tokens", lambda values: int((values > 0).sum())),
            official_tokens_with_provider_match=("total_tokens", lambda values: float(values[matched.loc[values.index, "legacy_provider_tokens"] > 0].sum())),
            legacy_provider_tokens_on_official_models=("legacy_provider_tokens", "sum"),
        ).reset_index()
        result = result.merge(overlap, on="usage_date", how="left")

    for column in result.columns:
        if column != "usage_date":
            result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0.0)
    denominator = result["official_named_tokens"].replace(0, pd.NA)
    if "official_tokens_with_activity_match" in result:
        result["activity_official_token_coverage"] = result["official_tokens_with_activity_match"] / denominator
    if "official_tokens_with_provider_match" in result:
        result["provider_official_token_coverage"] = result["official_tokens_with_provider_match"] / denominator
    return result
