"""Stage 1 coverage matrix UI helpers.

Rendering is metadata-only: labels and details come from the artifact bundle
and never imply that Streamlit queries a provider.
"""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from . import ct_dataframe

from ..coverage import (
    COVERAGE_CATEGORY_LABELS,
    COVERAGE_STATUS_DESCRIPTIONS,
    COVERAGE_STATUS_LABELS,
    COVERAGE_STATUS_ORDER,
    CoverageStatusCode,
    Stage1CoverageMatrix,
)

_STATUS_BADGE_CLASSES: dict[CoverageStatusCode, str] = {
    "available": "ct-badge--observed",
    "partial": "ct-badge--warning",
    "stale": "ct-badge--warning",
    "no_records": "",
    "not_applicable": "",
    "unavailable": "",
}


def coverage_badge_class(status_code: str) -> str:
    """CSS class for one coverage status; empty string is the neutral badge."""

    return _STATUS_BADGE_CLASSES.get(status_code, "")


def coverage_status_label(status_code: str) -> str:
    return COVERAGE_STATUS_LABELS.get(
        status_code, status_code.replace("_", " ").title()
    )


def coverage_legend_html() -> str:
    """Six-state legend with human-readable meanings; no query language."""

    items = "".join(
        f'<span class="ct-badge {coverage_badge_class(state)}">'
        f"{escape(COVERAGE_STATUS_LABELS[state])}</span> "
        f'<span style="color: var(--ct-muted); margin-right: 0.9rem;">'
        f"{escape(COVERAGE_STATUS_DESCRIPTIONS[state])}</span>"
        for state in COVERAGE_STATUS_ORDER
    )
    return (
        '<div class="ct-source-line" style="margin-bottom: 0.45rem;">'
        "Coverage states · " + items + "</div>"
    )


def stage1_matrix_to_dataframe(
    matrix: Stage1CoverageMatrix,
) -> pd.DataFrame:
    """Entity-by-category matrix as a display frame with human labels."""

    columns = [
        "entity_id",
        "display_name",
        "entity_type",
        "listing_count",
        "listing_ids",
        *[
            column
            for category in matrix.categories
            for column in (
                f"{category}_status",
                f"{category}_details",
            )
        ],
    ]
    rows: list[dict[str, object]] = []
    for entity in matrix.entity_rows:
        row: dict[str, object] = {
            "entity_id": entity.entity_id,
            "display_name": entity.display_name,
            "entity_type": entity.entity_type,
            "listing_count": entity.listing_count,
            "listing_ids": ", ".join(entity.listing_ids),
        }
        for category, cell in zip(matrix.categories, entity.cells):
            row[f"{category}_status"] = coverage_status_label(cell.status_code)
            row[f"{category}_details"] = cell.details
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def stage1_listings_to_dataframe(
    matrix: Stage1CoverageMatrix,
) -> pd.DataFrame:
    """Active-listing quote coverage as a display frame."""

    columns = (
        "listing_id",
        "entity_id",
        "canonical_ticker",
        "quote_status",
        "details",
    )
    rows = [
        {
            "listing_id": listing.listing_id,
            "entity_id": listing.entity_id,
            "canonical_ticker": listing.canonical_ticker,
            "quote_status": coverage_status_label(listing.status_code),
            "details": listing.details,
        }
        for listing in matrix.listing_rows
    ]
    return pd.DataFrame(rows, columns=columns)


def render_stage1_coverage_matrix(matrix: Stage1CoverageMatrix) -> None:
    """Render entity, listing and macro coverage without any provider access."""

    entity_frame = stage1_matrix_to_dataframe(matrix)
    listing_frame = stage1_listings_to_dataframe(matrix)
    category_columns = [
        f"{category}_status"
        for category in matrix.categories
    ]
    display = entity_frame.loc[
        :,
        [
            "display_name",
            "entity_type",
            "listing_count",
            *category_columns,
        ],
    ].copy()
    display = display.rename(
        columns={
            "display_name": "Entity",
            "entity_type": "Type",
            "listing_count": "Active listings",
            **{
                f"{category}_status": COVERAGE_CATEGORY_LABELS[category]
                for category in matrix.categories
            },
        }
    )
    ct_dataframe(display, width="stretch", hide_index=True)

    if not listing_frame.empty:
        st.caption("Active listings · quote coverage")
        listing_display = listing_frame.loc[
            :,
            ["listing_id", "entity_id", "canonical_ticker", "quote_status"],
        ].rename(
            columns={
                "listing_id": "Listing",
                "entity_id": "Entity",
                "canonical_ticker": "Ticker",
                "quote_status": "Quote status",
            }
        )
        ct_dataframe(listing_display, width="stretch", hide_index=True)

    macro = matrix.global_macro
    st.caption(
        f"Macro observations (global) · {coverage_status_label(macro.status_code)}"
        f" · {macro.details}"
    )
    with st.expander("Coverage details", expanded=False):
        for entity in matrix.entity_rows:
            st.markdown(
                f"**{escape(entity.display_name)}** "
                f"({escape(entity.entity_id)} · {escape(entity.entity_type)} · "
                f"{entity.listing_count} active listing(s))"
            )
            for category, cell in zip(matrix.categories, entity.cells):
                st.caption(
                    f"{COVERAGE_CATEGORY_LABELS[category]} · "
                    f"{coverage_status_label(cell.status_code)} · {cell.details}"
                )


__all__ = [
    "coverage_badge_class",
    "coverage_legend_html",
    "coverage_status_label",
    "render_stage1_coverage_matrix",
    "stage1_listings_to_dataframe",
    "stage1_matrix_to_dataframe",
]
