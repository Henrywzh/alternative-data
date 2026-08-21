"""Drift guard: alert on capability-resolution gaps before users see them.

The published SOTA metric degrades quietly. A frontier model nobody has
mapped, or a stripped key that matches two families, shows up as a slightly
smaller cohort -- not as an error -- and stays that way until someone
happens to look at the chart. This runs off the two committed input parquets
and reports those conditions with an actionable message.

Design: docs/openrouter-capability-self-healing-design.md section 6, adapted
to the shipped ranking design (unmapped leaders stay in the ranking under a
sentinel id and surface as partial cohort coverage) rather than to the
rank-continuity refactor that proposal also assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import pandas as pd

from .identity import load_capability_map
from .resolver import (
    RESOLVER_EXACT,
    RESOLVER_STRIPPED,
    UNRESOLVED_AMBIGUOUS,
    resolve_capability_map,
)


SOTA_METRIC_ID = "sota_volume_weighted_atp"
PARTIAL_COVERAGE_PREFIX = "partial_true_sota_route_coverage"
CONSECUTIVE_PARTIAL_DAYS_ALLOWED = 2

_AA_INPUT = "data/normalized/artificial_analysis/artificial_analysis_models_daily.parquet"
_CATALOG_INPUT = "data/normalized/compute_availability/raw_openrouter_models.parquet"
_MART = "data/normalized/marts/openrouter_usage_economics_daily.parquet"


@dataclass
class Finding:
    check: str
    severity: str  # "error" | "warning"
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class GuardReport:
    top_n: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [item for item in self.findings if item.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [item for item in self.findings if item.severity == "warning"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "top_n": self.top_n,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "findings": [asdict(item) for item in self.findings],
        }


def _latest_released_models(aa_models: pd.DataFrame, top_n: int) -> pd.DataFrame:
    if aa_models.empty:
        return aa_models
    as_of = pd.to_datetime(aa_models["as_of_date"], errors="coerce")
    latest = aa_models.loc[as_of == as_of.max()].drop_duplicates("model_id", keep="last")
    latest = latest.loc[pd.to_datetime(latest["release_date"], errors="coerce").notna()]
    latest = latest.assign(
        _score=pd.to_numeric(latest["intelligence_index"], errors="coerce")
    ).dropna(subset=["_score"])
    return latest.sort_values("_score", ascending=False).head(top_n)


def _check_resolution(report: GuardReport, base_dir: Path, top_n: int) -> None:
    aa_models = pd.read_parquet(base_dir / _AA_INPUT)
    catalog = pd.read_parquet(base_dir / _CATALOG_INPUT)
    curated = load_capability_map(base_dir)
    _, resolutions = resolve_capability_map(curated, aa_models, catalog)
    by_model = {resolution.aa_model_id: resolution for resolution in resolutions}

    top = _latest_released_models(aa_models, top_n)
    curated_ids = set(curated.by_aa_model_id)

    for rank, (_, model) in enumerate(top.iterrows(), start=1):
        model_id = str(model["model_id"])
        name = str(model.get("model_name") or model_id)
        if model_id in curated_ids:
            continue
        resolution = by_model.get(model_id)
        if resolution is None:
            continue
        common = {
            "rank": rank,
            "model_name": name,
            "aa_model_id": model_id,
            "model_slug": str(model.get("model_slug") or ""),
            "creator_slug": str(model.get("creator_slug") or ""),
        }
        if resolution.status == UNRESOLVED_AMBIGUOUS:
            report.findings.append(
                Finding(
                    check="ambiguous",
                    severity="error",
                    message=f"rank {rank} '{name}': {resolution.detail}",
                    detail=common,
                )
            )
        elif not resolution.resolved:
            report.findings.append(
                Finding(
                    check="drift",
                    severity="error",
                    message=(
                        f"rank {rank} '{name}' resolves to no OpenRouter family: "
                        f"{resolution.detail}"
                    ),
                    detail=common,
                )
            )
        elif resolution.status in {RESOLVER_EXACT, RESOLVER_STRIPPED}:
            report.findings.append(
                Finding(
                    check="fuzzy",
                    severity="warning",
                    message=(
                        f"rank {rank} '{name}' is running on an automatic match "
                        f"({resolution.status} -> {resolution.family_id}); promote it "
                        "to config/openrouter_capability_map.json once confirmed"
                    ),
                    detail={**common, "family_id": resolution.family_id},
                )
            )


def _check_coverage(report: GuardReport, base_dir: Path) -> None:
    """Catch silent degradation the resolution checks missed.

    A cohort can be short for reasons the resolver cannot see -- a route with
    no usage, a price that will not join -- so the published metric is checked
    directly. One partial day is normal at the edge of the data; a run of them
    is a problem nobody has noticed.
    """
    path = base_dir / _MART
    if not path.exists():
        return
    mart = pd.read_parquet(path)
    if mart.empty or "metric_id" not in mart.columns:
        return
    sota = mart.loc[mart["metric_id"] == SOTA_METRIC_ID].copy()
    if sota.empty:
        return
    sota["usage_date"] = pd.to_datetime(sota["usage_date"], errors="coerce")
    sota = sota.dropna(subset=["usage_date"]).sort_values("usage_date")
    partial = (
        sota["pricing_join_status"].astype("string").fillna("").str.startswith(PARTIAL_COVERAGE_PREFIX)
    )
    streak = 0
    for flag in reversed(partial.tolist()):
        if not flag:
            break
        streak += 1
    if streak > CONSECUTIVE_PARTIAL_DAYS_ALLOWED:
        last = sota.iloc[-1]
        report.findings.append(
            Finding(
                check="coverage",
                severity="error",
                message=(
                    f"{SOTA_METRIC_ID} has reported partial cohort coverage for "
                    f"{streak} consecutive days through "
                    f"{last['usage_date'].date()} "
                    f"({int(last.get('observed_family_count') or 0)}/"
                    f"{int(last.get('expected_family_count') or 0)} families)"
                ),
                detail={
                    "consecutive_days": streak,
                    "through": str(last["usage_date"].date()),
                },
            )
        )


def run_guard(base_dir: Path, *, top_n: int = 10, fail_on: str = "error") -> GuardReport:
    """Report capability-resolution drift. Reads committed inputs, no network."""
    report = GuardReport(top_n=top_n)
    _check_resolution(report, base_dir, top_n)
    _check_coverage(report, base_dir)
    return report


def report_exit_code(report: GuardReport, *, fail_on: str = "error") -> int:
    if report.errors:
        return 1
    if fail_on == "fuzzy" and report.warnings:
        return 1
    return 0
