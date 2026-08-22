"""The guard that keeps a continue-on-error producer from failing silently."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_dataset_contract import check_dataset  # noqa: E402

from dashboard.data import DATASET_REGISTRY  # noqa: E402


DATASET_ID = "cloud_infra_daily_activity"


def _valid_frame() -> pd.DataFrame:
    spec = DATASET_REGISTRY[DATASET_ID]
    columns = {str(column): ["a", "b"] for column in spec["required_columns"]}
    # Two rows that differ on the natural key, so uniqueness holds.
    for index, key in enumerate(spec["natural_keys"]):
        columns[str(key)] = ["k0", f"k1-{index}"]
    return pd.DataFrame(columns)


def _write(frame: pd.DataFrame, tmp_path: Path) -> Path:
    path = tmp_path / f"{DATASET_ID}.parquet"
    frame.to_parquet(path, index=False)
    return path


def test_a_conforming_dataset_reports_no_failures(tmp_path: Path) -> None:
    assert check_dataset(DATASET_ID, _write(_valid_frame(), tmp_path)) == []


def test_the_pre_serving_provider_schema_is_rejected(tmp_path: Path) -> None:
    """The exact shape that sat on main while the job reported success.

    The old builder wrote provider_slug where the contract now expects
    serving_provider, so the readers' natural key collapsed and the dataset
    looked duplicated.  A green workflow must never coexist with this file.
    """

    legacy = pd.DataFrame(
        {
            "dataset_id": [DATASET_ID] * 2,
            "usage_date": ["2026-08-20", "2026-08-20"],
            "provider_slug": ["together", "fireworks"],
            "provider_name": ["Together", "Fireworks"],
            "model_permaslug": ["deepseek/deepseek-v4", "deepseek/deepseek-v4"],
            "total_tokens": [1, 2],
            "headquarters": ["US", "US"],
            "datacenters": ["US", "US"],
        }
    )
    failures = check_dataset(DATASET_ID, _write(legacy, tmp_path))

    assert any("missing required columns" in failure for failure in failures)
    assert any("serving_provider" in failure for failure in failures)
    assert any("uniqueness cannot be established" in failure for failure in failures)


def test_duplicate_natural_keys_are_reported_with_a_count(tmp_path: Path) -> None:
    frame = _valid_frame()
    duplicated = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    failures = check_dataset(DATASET_ID, _write(duplicated, tmp_path))

    assert any("1 duplicate rows on the natural key" in failure for failure in failures)


def test_an_empty_or_absent_dataset_is_a_failure(tmp_path: Path) -> None:
    empty = check_dataset(DATASET_ID, _write(_valid_frame().iloc[:0], tmp_path))
    assert any("empty" in failure for failure in empty)

    absent = check_dataset(DATASET_ID, tmp_path / "nope.parquet")
    assert any("does not exist" in failure for failure in absent)


def test_an_unregistered_dataset_is_a_failure_not_a_pass(tmp_path: Path) -> None:
    """A typo in the workflow must not read as a healthy dataset."""

    failures = check_dataset("not_a_dataset", _write(_valid_frame(), tmp_path))
    assert any("not registered" in failure for failure in failures)


@pytest.mark.parametrize("dataset_id", [DATASET_ID])
def test_the_guard_reads_its_contract_from_the_dashboard_registry(
    dataset_id: str,
) -> None:
    """No duplicated column list: the readers' contract is the only source."""

    spec = DATASET_REGISTRY[dataset_id]
    assert spec["natural_keys"] and spec["required_columns"]
