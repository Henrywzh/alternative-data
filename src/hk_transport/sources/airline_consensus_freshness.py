"""Point-in-time freshness and coverage contract for airline expectations."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


OUTPUT_PATH = NORMALIZED_DIR / "airline_consensus_freshness.csv"

INPUTS = {
    "ashare_profit_consensus": NORMALIZED_DIR / "airline_consensus_ashare_snapshot.csv",
    "ashare_em_profit_consensus": NORMALIZED_DIR / "airline_consensus_em_snapshot.csv",
    "ashare_detailed_consensus": NORMALIZED_DIR / "airline_consensus_ashare_detailed.csv",
    "hk_broker_profit_consensus": NORMALIZED_DIR / "airline_hk_sell_side_forecasts.csv",
    "mainland_revenue_sell_side_pdf": NORMALIZED_DIR / "airline_sell_side_revenue_forecasts.csv",
    "vendor_revenue_consensus": NORMALIZED_DIR / "airline_revenue_consensus_yfinance.csv",
    "public_report_evidence": NORMALIZED_DIR / "airline_public_report_evidence.csv",
    "mainland_eps_sell_side_revision_proxy": NORMALIZED_DIR / "airline_sell_side_forecast_revisions.csv",
}

REVISION_INPUTS = {
    "hk_broker_profit_consensus": NORMALIZED_DIR / "airline_hk_forecast_revisions.csv",
    "mainland_revenue_sell_side_pdf": NORMALIZED_DIR / "airline_sell_side_revenue_revisions.csv",
    "mainland_eps_sell_side_revision_proxy": NORMALIZED_DIR / "airline_sell_side_forecast_revisions.csv",
}

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "market", "source_layer", "metric_scope",
    "as_of_date", "latest_observation_date", "latest_snapshot_date", "age_days",
    "freshness_band", "observation_count", "prior_comparison_count",
    "forecast_year_min", "forecast_year_max", "revision_history_available",
    "source_quality", "source_url", "source_note", "retrieved_at",
]


def _date_series(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_datetime(frame[column], errors="coerce") if column in frame else pd.Series(dtype="datetime64[ns]")


def _first_non_null(frame: pd.DataFrame, column: str) -> Any:
    if column not in frame:
        return None
    values = frame[column].dropna()
    return values.iloc[0] if not values.empty else None


def _freshness_band(age_days: int | None) -> str:
    if age_days is None:
        return "unknown"
    if age_days <= 14:
        return "fresh"
    if age_days <= 45:
        return "recent"
    if age_days <= 90:
        return "aging"
    return "stale"


def _layer_contract(
    frame: pd.DataFrame,
    *,
    source_layer: str,
    market: str,
    latest_observation_column: str,
    as_of_column: str | None,
    revision_frame: pd.DataFrame | None = None,
    metric_scope: str | None = None,
    retrieved_at: str,
) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    revision_frame = revision_frame if revision_frame is not None else pd.DataFrame()
    group_columns = [column for column in ("company", "ticker") if column in frame.columns]
    for group_key, group in frame.groupby(group_columns, dropna=False):
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        company = str(group_key[group_columns.index("company")]) if "company" in group_columns else None
        ticker = str(group_key[group_columns.index("ticker")]) if "ticker" in group_columns else None

        observations = _date_series(group, latest_observation_column).dropna()
        latest_observation = observations.max() if not observations.empty else pd.NaT
        if as_of_column and as_of_column in group:
            as_of_values = _date_series(group, as_of_column).dropna()
            as_of = as_of_values.max() if not as_of_values.empty else latest_observation
        else:
            # Report-feed layers have no explicit snapshot date. Use the
            # retrieval date as the information cutoff, so older last reports
            # are visibly stale rather than receiving an artificial age of
            # zero merely because they are the latest row in that feed.
            retrieval_date = pd.to_datetime(retrieved_at, errors="coerce")
            if not pd.isna(retrieval_date) and getattr(retrieval_date, "tzinfo", None) is not None:
                retrieval_date = retrieval_date.tz_localize(None)
            as_of = retrieval_date if not pd.isna(retrieval_date) else latest_observation
        if pd.isna(as_of):
            age_days = None
            as_of_date = None
            latest_observation_date = None
        else:
            age_days = int((as_of.normalize() - latest_observation.normalize()).days)
            as_of_date = as_of.strftime("%Y-%m-%d")
            latest_observation_date = latest_observation.strftime("%Y-%m-%d")

        prior_comparisons = 0
        if not revision_frame.empty:
            revision_subset = revision_frame.copy()
            for column, value in (("company", company), ("ticker", ticker)):
                if column in revision_subset.columns and value is not None:
                    revision_subset = revision_subset.loc[revision_subset[column].astype(str).eq(value)]
            if "prior_report_date" in revision_subset:
                prior_comparisons = int(revision_subset["prior_report_date"].notna().sum())

        years = pd.to_numeric(group.get("fiscal_year"), errors="coerce").dropna()
        source_quality = "+".join(sorted({str(value) for value in group.get("source_quality", pd.Series()).dropna()}))
        source_url = _first_non_null(group, "source_url") or _first_non_null(group, "report_url")
        latest_snapshot = _first_non_null(group, "snapshot_date")
        if latest_snapshot is None and "retrieved_at" in group:
            retrieved_dates = pd.to_datetime(group["retrieved_at"], errors="coerce").dropna()
            latest_snapshot = retrieved_dates.max().strftime("%Y-%m-%d") if not retrieved_dates.empty else None

        rows.append(
            {
                "dataset_id": "airline_consensus_freshness",
                "company": company,
                "ticker": ticker,
                "market": market,
                "source_layer": source_layer,
                "metric_scope": metric_scope or ("profit/EPS" if "profit" in source_layer else "revenue"),
                "as_of_date": as_of_date,
                "latest_observation_date": latest_observation_date,
                "latest_snapshot_date": latest_snapshot,
                "age_days": age_days,
                "freshness_band": _freshness_band(age_days),
                "observation_count": len(group),
                "prior_comparison_count": prior_comparisons,
                "forecast_year_min": int(years.min()) if not years.empty else None,
                "forecast_year_max": int(years.max()) if not years.empty else None,
                "revision_history_available": prior_comparisons > 0,
                "source_quality": source_quality or None,
                "source_url": source_url,
                "source_note": (
                    "Freshness is measured from the layer as-of date to the latest dated forecast observation. "
                    "A provider snapshot date is not the same as a broker estimate-vintage date; prior comparisons "
                    "are sparse and must not be read as a complete institutional revision history."
                    if source_layer != "public_report_evidence" else
                    "10jqka public report evidence uses visible institution report dates for EPS/net profit; "
                    "revenue rows are page-snapshot-only and revision markers do not establish a complete numeric "
                    "broker-vintage history."
                ),
                "retrieved_at": retrieved_at,
            }
        )
    return rows


def build_airline_consensus_freshness(
    *,
    frames: dict[str, pd.DataFrame] | None = None,
    revision_frames: dict[str, pd.DataFrame] | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build one comparable freshness row per company/share-class/source layer."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    if frames is None:
        frames = {name: pd.read_csv(path) for name, path in INPUTS.items() if path.exists()}
    if revision_frames is None:
        revision_frames = {
            name: pd.read_csv(path)
            for name, path in REVISION_INPUTS.items()
            if path.exists()
        }

    rows: list[dict[str, Any]] = []
    rows.extend(_layer_contract(
        frames.get("ashare_profit_consensus", pd.DataFrame()),
        source_layer="ashare_profit_consensus", market="CN_A",
        latest_observation_column="forecast_date_max", as_of_column="snapshot_date",
        retrieved_at=retrieved,
    ))
    rows.extend(_layer_contract(
        frames.get("ashare_em_profit_consensus", pd.DataFrame()),
        source_layer="ashare_em_profit_consensus", market="CN_A",
        latest_observation_column="snapshot_date", as_of_column="snapshot_date",
        retrieved_at=retrieved,
    ))
    rows.extend(_layer_contract(
        frames.get("ashare_detailed_consensus", pd.DataFrame()),
        source_layer="ashare_detailed_consensus", market="CN_A",
        latest_observation_column="forecast_date_max", as_of_column="snapshot_date",
        retrieved_at=retrieved,
    ))
    rows.extend(_layer_contract(
        frames.get("hk_broker_profit_consensus", pd.DataFrame()),
        source_layer="hk_broker_profit_consensus", market="HK",
        latest_observation_column="report_date", as_of_column=None,
        revision_frame=revision_frames.get("hk_broker_profit_consensus"),
        retrieved_at=retrieved,
    ))
    rows.extend(_layer_contract(
        frames.get("mainland_revenue_sell_side_pdf", pd.DataFrame()),
        source_layer="mainland_revenue_sell_side_pdf", market="CN_A",
        latest_observation_column="report_date", as_of_column=None,
        revision_frame=revision_frames.get("mainland_revenue_sell_side_pdf"),
        retrieved_at=retrieved,
    ))
    rows.extend(_layer_contract(
        frames.get("vendor_revenue_consensus", pd.DataFrame()),
        source_layer="vendor_revenue_consensus", market="mixed",
        latest_observation_column="snapshot_date", as_of_column="snapshot_date",
        retrieved_at=retrieved,
    ))
    rows.extend(_layer_contract(
        frames.get("public_report_evidence", pd.DataFrame()),
        source_layer="public_report_evidence", market="CN_A",
        latest_observation_column="report_date", as_of_column="snapshot_date",
        metric_scope="public EPS/net profit/revenue evidence",
        retrieved_at=retrieved,
    ))
    rows.extend(_layer_contract(
        frames.get("mainland_eps_sell_side_revision_proxy", pd.DataFrame()),
        source_layer="mainland_eps_sell_side_revision_proxy", market="CN_A",
        latest_observation_column="report_date", as_of_column=None,
        revision_frame=revision_frames.get("mainland_eps_sell_side_revision_proxy"),
        metric_scope="EPS revision proxy",
        retrieved_at=retrieved,
    ))
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if result.empty:
        return result
    return result.sort_values(["company", "source_layer"]).reset_index(drop=True)


def fetch_airline_consensus_freshness() -> pd.DataFrame:
    result = build_airline_consensus_freshness()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
