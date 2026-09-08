from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops_control.health import classify_regression, derive_dimensions
from ops_control.models import CheckResult


FIXTURES = Path(__file__).parent / "fixtures"
CASES = json.loads((FIXTURES / "health_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_known_failure_shapes_derive_expected_health(case: dict) -> None:
    checks = [CheckResult.from_dict(item) for item in case["checks"]]

    dimensions = derive_dimensions(execution=case["execution"], checks=checks)

    assert dimensions.to_dict() == case["expected"]


def test_latest_observation_regression_is_explicit() -> None:
    assert classify_regression("2026-06", "2026-07") is True
    assert classify_regression("2026-07", "2026-07") is False
    assert classify_regression("2026-08", "2026-07") is False
    assert classify_regression(None, "2026-07") is False


def test_tolerated_producer_failure_is_degraded_even_with_fresh_output() -> None:
    checks = [
        CheckResult(
            check_id="output.contract",
            status="healthy",
            required=True,
            message="Retained output is still fresh.",
        )
    ]

    dimensions = derive_dimensions(
        execution="success",
        checks=checks,
        producer_failures=True,
    )

    assert dimensions.collection == "partial"
    assert dimensions.data_health == "fresh"
    assert dimensions.publication == "retained_previous"
    assert dimensions.derived_state == "DEGRADED_RETAINED"
