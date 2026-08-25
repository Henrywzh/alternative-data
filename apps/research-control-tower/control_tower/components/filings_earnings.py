"""Batch 2/3 filings, earnings-calendar and earnings-actuals rendering.

Read-only helper for the Company page.  It renders the official-source
metadata marts (``official_filings``, ``earnings_calendar``, ``earnings_actuals``)
with honest empty/partial/no_records/not_applicable states sourced from the
``source_health`` rows; it never queries a provider and never renders document
bodies.  The Company page calls ``render_filings_earnings_sections`` once.
"""

from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from ..models import ControlTowerSnapshot
from . import ct_dataframe


OFFICIAL_FILING_COLUMNS = (
    "document_type", "event_class", "headline", "published_at", "accepted_at",
    "source_url", "reporting_period_label", "date_precision", "source_timezone",
    "source_quality",
)
CALENDAR_COLUMNS = (
    "event_date", "event_type", "period_label", "date_basis", "status",
    "source_url", "headline",
)
ACTUALS_COLUMNS = (
    "period_label", "metric", "reported_value", "normalized_value", "currency",
    "unit", "accounting_basis", "filing_at", "version", "is_restatement",
    "revision_reason", "source_url",
)


def _text(value: object) -> str:
    if value is None or value is pd.NaT:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _friendly(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    output = frame.copy()
    keep = [column for column in columns if column in output.columns]
    for column in output.columns:
        if column not in keep and column not in {"entity_id", "listing_id", "canonical_ticker"}:
            output.drop(columns=[column], inplace=True)
    for column in output.columns:
        output[column] = output[column].map(_text)
    return output.loc[:, [column for column in keep if column in output.columns]]


def _source_status(snapshot: ControlTowerSnapshot, source_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Return explicit per-source status labels for the honest coverage states."""

    if snapshot.source_health.empty:
        return ("no source-health rows in the snapshot",)
    health = snapshot.source_health
    labels: list[str] = []
    for source_id in source_ids:
        rows = health.loc[health["source_id"].astype("string").eq(source_id)]
        if rows.empty:
            continue
        row = rows.iloc[0]
        status = _text(row.get("status")) or "unavailable"
        detail = _text(row.get("detail"))
        suffix = f" · {detail}" if detail else ""
        labels.append(f"{status}{suffix}")
    return tuple(labels)


def render_official_filings(
    snapshot: ControlTowerSnapshot,
    *,
    entity_id: str,
    listing_id: str | None,
    viewer_timezone: str,
) -> None:
    st.markdown("#### Official filings and announcements metadata")
    if snapshot.official_filings.empty:
        st.info("No official filing/announcement metadata rows in the current snapshot.")
        return
    frame = snapshot.official_filings.loc[
        snapshot.official_filings["entity_id"].astype("string").eq(entity_id)
    ].copy()
    if listing_id:
        frame = frame.loc[frame["listing_id"].astype("string").eq(listing_id)]
    if frame.empty:
        st.info("No official filing/announcement metadata rows for this entity/listing.")
        return
    ct_dataframe(_friendly(frame, OFFICIAL_FILING_COLUMNS), width="stretch", hide_index=True)


def render_earnings_calendar(
    snapshot: ControlTowerSnapshot,
    *,
    entity_id: str,
    listing_id: str | None,
) -> None:
    st.markdown("#### Official earnings calendar")
    if snapshot.earnings_calendar.empty:
        st.info(
            "No official earnings-calendar rows in the current snapshot; "
            "scheduled dates are only shown when an official source states them."
        )
        return
    frame = snapshot.earnings_calendar.loc[
        snapshot.earnings_calendar["entity_id"].astype("string").eq(entity_id)
    ].copy()
    if listing_id:
        frame = frame.loc[frame["listing_id"].astype("string").eq(listing_id)]
    if frame.empty:
        st.info("No official earnings-calendar rows for this entity/listing.")
        return
    ct_dataframe(_friendly(frame, CALENDAR_COLUMNS), width="stretch", hide_index=True)


def render_earnings_actuals(
    snapshot: ControlTowerSnapshot,
    *,
    entity_id: str,
    listing_id: str | None,
    viewer_timezone: str,
) -> None:
    st.markdown("#### Earnings actuals history")
    if snapshot.earnings_actuals.empty:
        st.info(
            "No earnings-actuals rows in the current snapshot; "
            "values are only shown from official issuer disclosure metadata."
        )
        return
    frame = snapshot.earnings_actuals.loc[
        snapshot.earnings_actuals["entity_id"].astype("string").eq(entity_id)
    ].copy()
    if listing_id:
        frame = frame.loc[frame["listing_id"].astype("string").eq(listing_id)]
    if frame.empty:
        st.info("No earnings-actuals rows for this entity/listing.")
        return
    frame = frame.sort_values(["period_end", "metric", "version"], ascending=False)
    ct_dataframe(_friendly(frame, ACTUALS_COLUMNS), width="stretch", hide_index=True)
    latest = frame["period_end"].dropna()
    if not latest.empty:
        latest_label = _text(frame.loc[frame["period_end"].eq(latest.max()), "period_label"].iloc[0])
        st.caption(f"Latest reported period in snapshot: {escape(latest_label) if latest_label else latest.max().strftime('%Y-%m-%d')} · reported values preserved per filing; restatements are versioned, not overwritten.")


def render_filings_earnings_sections(
    snapshot: ControlTowerSnapshot,
    *,
    entity_id: str,
    listing_id: str | None,
    viewer_timezone: str,
) -> None:
    """Single Company-page integration point for the Batch 2/3 sections."""

    render_official_filings(
        snapshot, entity_id=entity_id, listing_id=listing_id, viewer_timezone=viewer_timezone
    )
    render_earnings_calendar(snapshot, entity_id=entity_id, listing_id=listing_id)
    render_earnings_actuals(
        snapshot, entity_id=entity_id, listing_id=listing_id, viewer_timezone=viewer_timezone
    )
    statuses = _source_status(
        snapshot,
        ("filings:sec_edgar_submissions", "filings:hkexnews", "filings:issuer_ir", "filings:bytedance"),
    )
    if statuses:
        st.caption("Source states · " + " · ".join(escape(status) for status in statuses))


__all__ = ["render_filings_earnings_sections"]
