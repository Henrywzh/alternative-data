"""Track-exclusivity guards for the unified KPI backtest engine.

H1 and FY are independently reported by the issuer, but H2 is derived
arithmetically as FY minus H1.  In level terms this makes H1 error + H2 error
identically equal to FY error, so pooling ``fiscal_year`` with
``half_year_non_overlapping`` observations into one aggregate double-counts
the same underlying information and understates the true variance of the
estimate.  A valid aggregate may use ``{H1, H2}`` (via
``half_year_non_overlapping``) OR ``{FY}`` (via ``fiscal_year``), never both.

``ytd_current`` (an incomplete current-period forecast) and ``monthly_sparse``
(SHKP monthly contract activity) are independent measurement processes with
no arithmetic relationship to the half-year/full-year tracks or to each
other, so each is isolated in its own exclusion group.

This module is intentionally dependency-light (``pandas`` + ``typing`` only)
and does not import ``metrics.py``, to avoid a circular import: a later
change wires these guards into the metrics pipeline, not the other way
around.
"""

from __future__ import annotations

from typing import Final

import pandas as pd

from .vocabulary import TRACK_IDS

TRACK_EXCLUSION_GROUPS: Final[tuple[frozenset[str], ...]] = (
    frozenset({"fiscal_year", "half_year_non_overlapping"}),
    frozenset({"ytd_current"}),
    frozenset({"monthly_sparse"}),
)
"""Groups of track_ids that are mutually exclusive within one aggregate.

Members of the same group must never appear together in a single aggregate.
``fiscal_year`` and ``half_year_non_overlapping`` share a group because they
are two competing, overlapping ways of covering the same annual information
(H2 = FY - H1, so picking both double-counts). A group with a single member
is *isolated*: that track_id conflicts with every other track_id in the
closed set, not merely with itself, so ``ytd_current`` and ``monthly_sparse``
can never be pooled with anything else, including each other.
"""

_TRACK_PERIOD_TYPES: Final[dict[str, tuple[str, ...]]] = {
    "fiscal_year": ("FY",),
    "half_year_non_overlapping": ("H1", "H2"),
    "ytd_current": ("H1",),
    "monthly_sparse": ("month",),
}
"""The period types that legitimately belong to each track.

``ytd_current`` is an in-progress observation reported against the H1
period type (a current, incomplete half-year read), but it is its own track
and is never pooled with ``half_year_non_overlapping``'s completed H1 rows.
"""


def _group_for_track(track_id: str) -> frozenset[str]:
    for group in TRACK_EXCLUSION_GROUPS:
        if track_id in group:
            return group
    raise ValueError(
        f"Unknown track_id {track_id!r}; no exclusion group is declared for it. "
        f"Known tracks: {sorted(TRACK_IDS)}"
    )


def _tracks_conflict(track_a: str, track_b: str) -> bool:
    """Return True if ``track_a`` and ``track_b`` may never be pooled together."""
    group_a, group_b = _group_for_track(track_a), _group_for_track(track_b)
    if group_a == group_b:
        return True
    return len(group_a) == 1 or len(group_b) == 1


def period_types_for_track(track_id: str) -> tuple[str, ...]:
    """Return the period types that legitimately belong to ``track_id``.

    Raises ``ValueError`` naming the offending value if ``track_id`` is not a
    member of ``vocabulary.TRACK_IDS``.
    """
    if track_id not in _TRACK_PERIOD_TYPES:
        raise ValueError(
            f"Unknown track_id {track_id!r}; expected one of {sorted(TRACK_IDS)}"
        )
    return _TRACK_PERIOD_TYPES[track_id]


def validate_track_exclusivity(frame: pd.DataFrame, *, track_column: str = "track_id") -> None:
    """Raise if ``frame`` mixes mutually exclusive track_ids.

    Passes silently when ``frame`` is empty, when ``track_column`` is absent,
    or when at most one distinct track_id is present. Given the current
    closed set of tracks (see ``TRACK_EXCLUSION_GROUPS``), every pair of
    distinct track_ids conflicts -- ``fiscal_year``/``half_year_non_overlapping``
    because they cover the same annual information twice, and
    ``ytd_current``/``monthly_sparse`` because each is declared isolated --
    so in practice this currently rejects any frame with more than one
    track_id. The group structure exists so a future, genuinely compatible
    track pairing can be declared without changing this function. An empty
    frame or a missing column carries no track information to conflict, so
    both are treated as trivially valid rather than errors -- callers that
    require the column to be present should check for it separately.

    Note on overlap with ``assert_single_track``: with today's closed track
    set this function is functionally equivalent to "raise if more than one
    distinct track_id is present" -- the same thing ``assert_single_track``
    checks -- because no two tracks are declared compatible yet. It is kept
    as a separate, group-aware function (rather than collapsed into
    ``assert_single_track``) so that a future track pairing which *is*
    genuinely compatible (both members of the same multi-member exclusion
    group, like ``{fiscal_year, half_year_non_overlapping}`` would be if that
    group were ever widened) can be declared once in
    ``TRACK_EXCLUSION_GROUPS`` and take effect here without callers of
    ``assert_single_track`` -- which must always see exactly one track and
    should never loosen -- changing behavior.
    """
    if frame.empty or track_column not in frame.columns:
        return
    tracks_present = sorted(set(frame[track_column].dropna().astype(str)))
    if len(tracks_present) <= 1:
        return
    conflicts = [
        (tracks_present[i], tracks_present[j])
        for i in range(len(tracks_present))
        for j in range(i + 1, len(tracks_present))
        if _tracks_conflict(tracks_present[i], tracks_present[j])
    ]
    if conflicts:
        pair_text = ", ".join(f"{a!r} vs {b!r}" for a, b in conflicts)
        raise ValueError(
            "Frame mixes mutually exclusive track_ids: "
            f"{sorted(tracks_present)}. Conflicting pairs: {pair_text}. "
            "H1/H2 (half_year_non_overlapping) and FY (fiscal_year) cover the "
            "same underlying information -- H2 is derived as FY minus H1 -- "
            "so an aggregate must use one or the other, never both. "
            "ytd_current and monthly_sparse may never be pooled with any "
            "other track."
        )


def assert_single_track(frame: pd.DataFrame, *, context: str = "") -> str:
    """Raise unless ``frame`` contains exactly one track_id; return it.

    This is the strict guard for call sites (a chart, a per-track aggregate)
    that must not silently pool tracks at all. An empty frame or a frame
    missing ``track_id`` raises, since there is no single track_id to
    return. ``context`` is included verbatim in the error message so the
    caller site can be identified from the traceback alone.
    """
    label = f" ({context})" if context else ""
    if frame.empty:
        raise ValueError(f"Cannot determine a single track_id{label}: frame is empty")
    if "track_id" not in frame.columns:
        raise ValueError(f"Cannot determine a single track_id{label}: frame is missing 'track_id'")
    tracks_present = sorted(set(frame["track_id"].dropna().astype(str)))
    if len(tracks_present) != 1:
        raise ValueError(
            f"Expected exactly one track_id{label}, found {len(tracks_present)}: {tracks_present}"
        )
    return tracks_present[0]


def check_period_type_consistency(
    frame: pd.DataFrame,
    *,
    track_column: str = "track_id",
    period_column: str = "target_period_type",
) -> None:
    """Raise if any row's period type does not belong to its own track.

    For example an "FY" row sitting on the ``half_year_non_overlapping``
    track is invalid: that period type only ever belongs to ``fiscal_year``.
    Passes silently when ``frame`` is empty or either column is absent,
    matching ``validate_track_exclusivity``'s handling of missing structure.
    """
    if frame.empty or track_column not in frame.columns or period_column not in frame.columns:
        return
    violations: list[tuple[str, str]] = []
    for track_id, period_type in frame[[track_column, period_column]].dropna().drop_duplicates().itertuples(index=False):
        allowed = period_types_for_track(str(track_id))
        if str(period_type) not in allowed:
            violations.append((str(track_id), str(period_type)))
    if violations:
        detail = ", ".join(f"{track!r} row has period_type {period!r}" for track, period in sorted(violations))
        raise ValueError(
            f"Frame contains period types inconsistent with their track_id: {detail}"
        )
