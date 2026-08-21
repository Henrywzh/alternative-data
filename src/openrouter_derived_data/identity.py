"""Curated capability-family identity and point-in-time benchmark rankings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


RANKING_COLUMNS = [
    "usage_date",
    "benchmark_snapshot_date",
    "family_id",
    "family_rank",
    "capability_tier",
    "representative_aa_model_id",
    "representative_model_name",
    "intelligence_index",
    "release_date",
    "model_match_status",
    "methodology_version",
]
_ENTRY_KEYS = {"aa_model_id", "family_id", "effective_from", "openrouter_routes"}
_ROUTE_KEYS = {"model_id", "effective_from"}
_ROOT_KEYS = {"methodology_version", "models"}


@dataclass(frozen=True)
class CapabilityRoute:
    model_id: str
    effective_from: pd.Timestamp


@dataclass(frozen=True)
class CapabilityEntry:
    aa_model_id: str
    family_id: str
    effective_from: pd.Timestamp
    openrouter_routes: tuple[CapabilityRoute, ...]


@dataclass(frozen=True)
class CapabilityMap:
    methodology_version: str
    entries: tuple[CapabilityEntry, ...]

    @property
    def by_aa_model_id(self) -> dict[str, CapabilityEntry]:
        return {entry.aa_model_id: entry for entry in self.entries}


def load_capability_map(base_dir: Path) -> CapabilityMap:
    """Load and validate the versioned, exact Artificial Analysis capability map."""
    path = Path(base_dir) / "config" / "openrouter_capability_map.json"
    try:
        payload: Any = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid capability map JSON: {path}") from exc

    if not isinstance(payload, dict) or set(payload) != _ROOT_KEYS:
        raise ValueError("capability map must contain only methodology_version and models")
    methodology_version = payload["methodology_version"]
    rows = payload["models"]
    if not isinstance(methodology_version, str) or not methodology_version:
        raise ValueError("capability map methodology_version must be a non-empty string")
    if not isinstance(rows, list) or not rows:
        raise ValueError("capability map models must be a non-empty list")

    entries: list[CapabilityEntry] = []
    seen_aa_model_ids: set[str] = set()
    activity_id_families: dict[str, str] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != _ENTRY_KEYS:
            raise ValueError(f"capability map entry {index} has an invalid schema")
        aa_model_id = row["aa_model_id"]
        family_id = row["family_id"]
        effective_from = _parse_effective_date(
            row["effective_from"], f"capability map entry {index} effective_from"
        )
        route_rows = row["openrouter_routes"]
        if not isinstance(aa_model_id, str) or not aa_model_id:
            raise ValueError(f"capability map entry {index} aa_model_id must be a non-empty string")
        if aa_model_id in seen_aa_model_ids:
            raise ValueError(f"duplicate aa_model_id: {aa_model_id}")
        if not isinstance(family_id, str) or not family_id:
            raise ValueError(f"capability map entry {index} family_id must be a non-empty string")
        if not isinstance(route_rows, list):
            raise ValueError(f"capability map entry {index} openrouter_routes must be a list")
        routes: list[CapabilityRoute] = []
        seen_route_ids: set[str] = set()
        for route_index, route_row in enumerate(route_rows):
            if not isinstance(route_row, dict) or set(route_row) != _ROUTE_KEYS:
                raise ValueError(
                    f"capability map entry {index} route {route_index} has an invalid schema"
                )
            model_id = route_row["model_id"]
            if not isinstance(model_id, str) or not model_id:
                raise ValueError(
                    f"capability map entry {index} route {route_index} model_id must be a non-empty string"
                )
            if model_id in seen_route_ids:
                raise ValueError(
                    f"capability map entry {index} openrouter routes must have unique model_ids"
                )
            route_effective_from = _parse_effective_date(
                route_row["effective_from"],
                f"capability map entry {index} route {route_index} effective_from",
            )
            if route_effective_from < effective_from:
                raise ValueError(
                    f"capability map entry {index} route {route_index} predates its entry"
                )
            existing_family = activity_id_families.get(model_id)
            if existing_family is not None and existing_family != family_id:
                raise ValueError(
                    f"openrouter_model_id {model_id} is assigned to multiple families: "
                    f"{existing_family}, {family_id}"
                )
            activity_id_families[model_id] = family_id
            seen_route_ids.add(model_id)
            routes.append(CapabilityRoute(model_id, route_effective_from))
        seen_aa_model_ids.add(aa_model_id)
        entries.append(
            CapabilityEntry(
                aa_model_id=aa_model_id,
                family_id=family_id,
                effective_from=effective_from,
                openrouter_routes=tuple(routes),
            )
        )
    return CapabilityMap(methodology_version=methodology_version, entries=tuple(entries))


def compatible_activity_ids(
    capability_map: CapabilityMap,
    aa_model_id: str,
    usage_date: pd.Timestamp,
) -> frozenset[str]:
    """Return exact curated routes effective for an AA configuration on a date."""
    entry = capability_map.by_aa_model_id.get(aa_model_id)
    normalized_usage_date = pd.Timestamp(usage_date).normalize()
    if entry is None or entry.effective_from > normalized_usage_date:
        return frozenset()
    return frozenset(
        route.model_id
        for route in entry.openrouter_routes
        if route.effective_from <= normalized_usage_date
    )


def rank_capability_families(
    models: pd.DataFrame,
    usage_dates: pd.Series,
    capability_map: CapabilityMap,
    *,
    backfill_latest_snapshot: bool = False,
    resolution_status: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Rank model families using strict or explicitly backfilled benchmark scores.

    Strict mode uses the latest Artificial Analysis snapshot available on or
    before each usage date. Backfill mode uses the latest available snapshot
    for every usage date, while still enforcing each model's release date. The
    latter is a deliberately labeled current-score historical proxy.

    ``resolution_status`` labels families the resolver supplied rather than a
    human, keyed by aa_model_id. A curated assignment and a resolved one are
    both exact, but only the curated one has been reviewed, so the published
    rows keep them distinguishable and the drift guard can report which
    top-N families are still running on an automatic match.
    """
    required_columns = {"as_of_date", "model_id", "model_name", "release_date", "intelligence_index"}
    missing_columns = required_columns - set(models.columns)
    if missing_columns:
        raise ValueError(f"models is missing required columns: {sorted(missing_columns)}")

    prepared = models.loc[:, list(required_columns)].copy()
    prepared["as_of_date"] = _normalize_days(prepared["as_of_date"])
    prepared["release_date"] = _normalize_days(prepared["release_date"])
    prepared["intelligence_index"] = pd.to_numeric(prepared["intelligence_index"], errors="coerce")
    prepared = prepared.dropna(subset=["as_of_date", "release_date", "model_id", "intelligence_index"])
    normalized_usage_dates = _normalize_days(pd.Series(usage_dates)).dropna().drop_duplicates().sort_values()
    ranked_days: list[pd.DataFrame] = []
    for usage_date in normalized_usage_dates:
        if backfill_latest_snapshot:
            benchmark_snapshot_date = prepared["as_of_date"].max()
            snapshots_as_of_usage = prepared.loc[prepared["as_of_date"].eq(benchmark_snapshot_date)]
        else:
            snapshots_as_of_usage = prepared.loc[prepared["as_of_date"] <= usage_date]
            if snapshots_as_of_usage.empty:
                continue
            benchmark_snapshot_date = snapshots_as_of_usage["as_of_date"].max()
        if snapshots_as_of_usage.empty:
            continue
        eligible = snapshots_as_of_usage.loc[
            (snapshots_as_of_usage["as_of_date"] == benchmark_snapshot_date)
            & (snapshots_as_of_usage["release_date"] <= usage_date)
        ].copy()
        if eligible.empty:
            continue
        effective_entries = {
            entry.aa_model_id: entry
            for entry in capability_map.entries
            if entry.effective_from <= usage_date
        }
        eligible["family_id"] = eligible["model_id"].map(
            lambda model_id: (
                effective_entries[model_id].family_id
                if model_id in effective_entries
                else f"__unmapped__:{model_id}"
            )
        )
        eligible["_mapped"] = eligible["model_id"].isin(effective_entries)
        # Preserve the benchmark's true point-in-time ordering.  An unmapped
        # leader is a coverage gap, not permission to promote a lower-ranked
        # curated family into the SOTA cohort.  Unmapped rows intentionally
        # remain in the ranking with a sentinel family id; downstream route
        # joins cannot match them and therefore expose partial coverage.
        eligible = eligible.sort_values(
            ["family_id", "intelligence_index", "release_date", "model_id"],
            ascending=[True, False, False, True],
        ).drop_duplicates("family_id", keep="first")
        eligible = eligible.sort_values(
            ["intelligence_index", "release_date", "family_id"],
            ascending=[False, False, True],
        ).reset_index(drop=True)
        eligible["family_rank"] = range(1, len(eligible) + 1)
        eligible["capability_tier"] = eligible["family_rank"].map(_tier)
        eligible["usage_date"] = usage_date
        eligible["benchmark_snapshot_date"] = benchmark_snapshot_date
        eligible["representative_aa_model_id"] = eligible["model_id"]
        eligible["representative_model_name"] = eligible["model_name"]
        exact_status = (
            "backfilled_current_score_exact_match"
            if backfill_latest_snapshot
            else "exact_curated_match"
        )
        eligible["model_match_status"] = eligible["_mapped"].map(
            {True: exact_status, False: "unmapped_no_activity_route"}
        )
        if resolution_status:
            resolved = eligible["model_id"].map(resolution_status)
            eligible["model_match_status"] = eligible["model_match_status"].where(
                ~(eligible["_mapped"] & resolved.notna()), resolved
            )
        eligible["methodology_version"] = capability_map.methodology_version
        ranked_days.append(eligible[RANKING_COLUMNS])
    if not ranked_days:
        return pd.DataFrame(columns=RANKING_COLUMNS)
    return pd.concat(ranked_days, ignore_index=True)


def _normalize_days(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()


def _parse_effective_date(value: object, label: str) -> pd.Timestamp:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be an ISO date string")
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed) or parsed.strftime("%Y-%m-%d") != value:
        raise ValueError(f"{label} must be an ISO date string")
    return parsed.tz_localize(None).normalize()


def _tier(rank: int) -> str:
    if rank <= 5:
        return "sota"
    if rank <= 10:
        return "frontier_contender"
    return "broader_scored_market"
