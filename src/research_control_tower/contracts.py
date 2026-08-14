"""Typed data contracts for the Research Control Tower registries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd


ValidationSeverity = Literal["error", "warning", "info"]
SUPPORTED_SEVERITIES = frozenset({"error", "warning", "info"})


@dataclass(frozen=True)
class RegistryBundle:
    """Frozen wrapper for the five registry frames.

    The wrapper prevents replacing a frame through the dataclass API. Pandas
    frames themselves remain mutable objects; callers should treat a loaded
    bundle as a read-only snapshot by convention.
    """

    entities: pd.DataFrame
    listings: pd.DataFrame
    baskets: pd.DataFrame
    basket_memberships: pd.DataFrame
    indices: pd.DataFrame


@dataclass(frozen=True)
class ValidationIssue:
    """A deterministic registry validation result."""

    severity: ValidationSeverity
    code: str
    message: str
    registry: str | None = None
    row_index: int | None = None

    def __post_init__(self) -> None:
        if self.severity not in SUPPORTED_SEVERITIES:
            raise ValueError(f"unsupported validation severity: {self.severity!r}")
