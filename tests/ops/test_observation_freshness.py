"""Age-checking a lane that feeds no dashboard.

The free institutional lanes are absent from dashboard.data.DATASET_REGISTRY,
so dataset_contract cannot resolve their date column. Before this validator the
only option was `file`, which reports existence -- and a lane whose source
stopped answering keeps a complete, structurally valid, frozen file that passes
an existence check forever.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from ops_control.health import evaluate_output
from ops_control.registry import OutputSpec, RegistryError


def _spec(**overrides) -> OutputSpec:
    payload = dict(
        output_id="lane",
        path="data/normalized/lane/lane.parquet",
        required=True,
        validator="observation_freshness",
        date_column="trade_date",
        freshness={"mode": "max_age_days", "max_age_days": 7},
    )
    payload.update(overrides)
    return OutputSpec(**payload)


def _write(root: Path, values: list[str], column: str = "trade_date") -> None:
    target = root / "data" / "normalized" / "lane"
    target.mkdir(parents=True)
    pd.DataFrame({column: values}).to_parquet(target / "lane.parquet", index=False)


def test_a_recent_observation_is_healthy(tmp_path: Path) -> None:
    _write(tmp_path, ["2026-09-10", "2026-09-11"])

    checks, observation = evaluate_output(
        spec=_spec(), repo_root=tmp_path, as_of=date(2026, 9, 12)
    )

    assert [c.status for c in checks] == ["healthy"]
    assert observation.latest_observation == "2026-09-11"


def test_a_lane_that_stopped_publishing_goes_stale(tmp_path: Path) -> None:
    _write(tmp_path, ["2026-08-01"])

    checks, _ = evaluate_output(
        spec=_spec(), repo_root=tmp_path, as_of=date(2026, 9, 12)
    )

    assert [c.status for c in checks] == ["stale"]
    assert "past the 7-day contract" in checks[0].message


def test_the_boundary_day_is_not_yet_stale(tmp_path: Path) -> None:
    _write(tmp_path, ["2026-09-05"])

    checks, _ = evaluate_output(
        spec=_spec(), repo_root=tmp_path, as_of=date(2026, 9, 12)
    )

    assert [c.status for c in checks] == ["healthy"]


def test_a_month_granularity_column_is_measured_from_its_first_day(tmp_path: Path) -> None:
    # sp_pmi stores "2026-08", which is already a month behind on the day it
    # publishes -- the contract has to be set against that, not against a day.
    _write(tmp_path, ["2026-08"], column="period")

    checks, _ = evaluate_output(
        spec=_spec(date_column="period", freshness={"mode": "max_age_days", "max_age_days": 75}),
        repo_root=tmp_path,
        as_of=date(2026, 9, 12),
    )

    assert [c.status for c in checks] == ["healthy"]


def test_an_unparseable_date_is_unknown_not_healthy(tmp_path: Path) -> None:
    # Refusing to judge beats silently passing: "unknown" is visible in the
    # report, "healthy" would not be.
    _write(tmp_path, ["not-a-date"], column="period")

    checks, _ = evaluate_output(
        spec=_spec(date_column="period"), repo_root=tmp_path, as_of=date(2026, 9, 12)
    )

    assert [c.status for c in checks] == ["unknown"]


def test_a_quarter_label_is_aged_from_the_quarter_start(tmp_path: Path) -> None:
    # Why bis_observations stays on the `file` validator: "2025-Q4" parses, but
    # to 2025-10-01, and BIS publishes roughly two quarters in arrears -- so a
    # threshold loose enough to be quiet would let the lane die unnoticed.
    _write(tmp_path, ["2025-Q4"], column="period")

    checks, observation = evaluate_output(
        spec=_spec(date_column="period"), repo_root=tmp_path, as_of=date(2026, 9, 12)
    )

    assert observation.latest_observation == "2025-Q4"
    assert [c.status for c in checks] == ["stale"]


def test_a_missing_date_column_is_unknown_not_healthy(tmp_path: Path) -> None:
    _write(tmp_path, ["2026-09-11"], column="some_other_column")

    checks, _ = evaluate_output(
        spec=_spec(), repo_root=tmp_path, as_of=date(2026, 9, 12)
    )

    assert [c.status for c in checks] == ["unknown"]


def test_an_absent_dataset_is_still_missing(tmp_path: Path) -> None:
    checks, observation = evaluate_output(
        spec=_spec(), repo_root=tmp_path, as_of=date(2026, 9, 12)
    )

    assert [c.status for c in checks] == ["missing"]
    assert observation.exists is False


def test_a_partitioned_lane_is_aged_across_its_partitions(tmp_path: Path) -> None:
    target = tmp_path / "data" / "normalized" / "lane" / "lane"
    target.mkdir(parents=True)
    for day in ("2026-09-09", "2026-09-11"):
        pd.DataFrame({"trade_date": [day]}).to_parquet(target / f"{day}.parquet", index=False)

    checks, observation = evaluate_output(
        spec=_spec(path="data/normalized/lane/lane"), repo_root=tmp_path, as_of=date(2026, 9, 12)
    )

    assert [c.status for c in checks] == ["healthy"]
    assert observation.latest_observation == "2026-09-11"
