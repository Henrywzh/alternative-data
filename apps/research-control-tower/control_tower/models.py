"""Immutable public data contracts for the Control Tower read surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping

import pandas as pd


RepositoryStatus = Literal["success", "degraded"]
Horizon = Literal["all", "7d", "30d", "90d", "long_range"]

_HORIZONS = {"all", "7d", "30d", "90d", "long_range"}
_SCOPES = {"company", "basket", "macro", "policy", "index"}
_CERTAINTY = {"hard", "provisional", "thesis_checkpoint", "observed"}
_STATUSES = {
    "scheduled", "confirmed", "observed", "active", "watch", "completed",
    "cancelled", "unavailable",
}
_IMPORTANCE = {"high", "medium", "low"}


def _normalise_values(
    values: tuple[str, ...] | list[str] | str | float | int | None,
    *,
    upper: bool = False,
    lower: bool = False,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, float, int)):
        values = (values,)
    cleaned = {str(value).strip() for value in values if str(value).strip()}
    if upper:
        cleaned = {value.upper() for value in cleaned}
    if lower:
        cleaned = {value.lower() for value in cleaned}
    return tuple(sorted(cleaned))


def _timestamp_or_none(value: object) -> pd.Timestamp | None:
    if value is None or value is pd.NaT:
        return None
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    return parsed.tz_convert("UTC")


@dataclass(frozen=True, slots=True)
class ControlTowerSnapshot:
    entities: pd.DataFrame
    listings: pd.DataFrame
    baskets: pd.DataFrame
    basket_memberships: pd.DataFrame
    indices: pd.DataFrame
    events: pd.DataFrame
    event_entity_links: pd.DataFrame
    event_basket_links: pd.DataFrame
    event_watch_questions: pd.DataFrame
    macro_observations: pd.DataFrame
    consensus_snapshots: pd.DataFrame
    consensus_revisions: pd.DataFrame
    quote_snapshots: pd.DataFrame
    news_filings: pd.DataFrame
    official_filings: pd.DataFrame
    earnings_calendar: pd.DataFrame
    earnings_actuals: pd.DataFrame
    source_health: pd.DataFrame
    manifest: Mapping[str, Any]
    status: RepositoryStatus
    missing_optional: tuple[str, ...]
    degraded_reasons: Mapping[str, str]
    build_id: str
    built_at_utc: pd.Timestamp
    as_of_utc: pd.Timestamp
    previous_build_at: pd.Timestamp | None
    # Optional artifact, defaulted so that adding it to the contract does not
    # force every existing construction site to supply one. An empty frame is
    # the honest value when a bundle predates the price-bar mart.
    price_bars: pd.DataFrame = field(default_factory=pd.DataFrame)
    corporate_actions: pd.DataFrame = field(default_factory=pd.DataFrame)
    valuation_snapshots: pd.DataFrame = field(default_factory=pd.DataFrame)
    internal_estimates: pd.DataFrame = field(default_factory=pd.DataFrame)
    thesis_claims: pd.DataFrame = field(default_factory=pd.DataFrame)
    thesis_watch_questions: pd.DataFrame = field(default_factory=pd.DataFrame)
    evidence_items: pd.DataFrame = field(default_factory=pd.DataFrame)
    claim_evidence_links: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def now_utc(self) -> pd.Timestamp:
        """Return the manifest reference time; never the wall clock."""

        return self.as_of_utc


@dataclass(frozen=True, slots=True)
class EventFilters:
    horizon: Horizon = "all"
    basket_id: tuple[str, ...] = ()
    country: tuple[str, ...] = ()
    scope: tuple[str, ...] = ()
    certainty_class: tuple[str, ...] = ()
    status: tuple[str, ...] = ()
    membership_tier: tuple[str, ...] = ()
    importance: tuple[str, ...] = ()
    confidence: tuple[str, ...] = ()
    confidence_min: float | None = None
    now_utc: pd.Timestamp | str | datetime | None = None
    catalyst_eligible: bool | None = None

    def __post_init__(self) -> None:
        horizon = str(self.horizon).strip().lower()
        if horizon not in _HORIZONS:
            raise ValueError(f"unsupported horizon: {self.horizon!r}")
        object.__setattr__(self, "horizon", horizon)

        scope = _normalise_values(self.scope, lower=True)
        invalid_scope = sorted(set(scope) - _SCOPES)
        if invalid_scope:
            raise ValueError(f"unsupported scope: {invalid_scope[0]!r}")
        certainty = _normalise_values(self.certainty_class, lower=True)
        invalid_certainty = sorted(set(certainty) - _CERTAINTY)
        if invalid_certainty:
            raise ValueError(f"unsupported certainty_class: {invalid_certainty[0]!r}")
        status = _normalise_values(self.status, lower=True)
        invalid_status = sorted(set(status) - _STATUSES)
        if invalid_status:
            raise ValueError(f"unsupported status: {invalid_status[0]!r}")
        importance = _normalise_values(self.importance, lower=True)
        invalid_importance = sorted(set(importance) - _IMPORTANCE)
        if invalid_importance:
            raise ValueError(f"unsupported importance: {invalid_importance[0]!r}")

        object.__setattr__(self, "basket_id", _normalise_values(self.basket_id, upper=True))
        object.__setattr__(self, "country", _normalise_values(self.country, upper=True))
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "certainty_class", certainty)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "membership_tier", _normalise_values(self.membership_tier, lower=True))
        object.__setattr__(self, "importance", importance)
        object.__setattr__(self, "confidence", _normalise_values(self.confidence, lower=True))

        if self.confidence_min is not None:
            value = float(self.confidence_min)
            if not 0 <= value <= 1:
                raise ValueError("confidence_min must be between 0 and 1")
            object.__setattr__(self, "confidence_min", value)

        reference = _timestamp_or_none(self.now_utc)
        if horizon != "all" and reference is None:
            raise ValueError("now_utc is required for bounded horizons")
        object.__setattr__(self, "now_utc", reference)


__all__ = [
    "ControlTowerSnapshot",
    "EventFilters",
    "Horizon",
    "RepositoryStatus",
]
