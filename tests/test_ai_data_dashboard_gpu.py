from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pandas as pd
import pytest

_spec = importlib.util.spec_from_file_location("ai_dashboard_gpu", Path(__file__).resolve().parents[1] / "apps/ai-data-dashboard/gpu.py")
gpu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gpu)


def _panel(rows: list[tuple[str, str, float, int]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["period", "model", "price", "providers"])


def test_chain_index_is_provider_weighted_geometric_mean_of_matched_relatives() -> None:
    panel = _panel([
        ("w1", "a", 2.0, 2), ("w1", "b", 4.0, 6),
        ("w2", "a", 2.2, 2), ("w2", "b", 3.6, 6),
    ])
    idx = gpu.chain_index(panel, {"a", "b"})
    expected = 100 * math.exp(0.25 * math.log(1.1) + 0.75 * math.log(0.9))
    assert idx["level"][0] == 100.0
    assert idx["level"][1] == pytest.approx(expected, abs=1e-3)
    assert idx["models"] == [None, 2]
    assert sum(idx["contrib"][0].values()) == pytest.approx(math.log(expected / 100), abs=1e-6)


def test_entering_model_and_thin_listing_do_not_move_the_level() -> None:
    panel = _panel([
        ("w1", "a", 2.0, 3),
        ("w2", "a", 2.0, 3), ("w2", "new", 9.0, 5),
        ("w3", "a", 2.0, 3), ("w3", "new", 4.5, 1),
    ])
    idx = gpu.chain_index(panel, {"a", "new"})
    # w2 adds a model priced only in w2; w3 halves it but with one provider.
    assert idx["level"] == [100.0, 100.0, 100.0]
    assert idx["models"] == [None, 1, 1]


def test_link_with_no_matched_model_is_a_gap() -> None:
    panel = _panel([("w1", "a", 2.0, 3), ("w2", "b", 2.0, 3)])
    idx = gpu.chain_index(panel, {"a", "b"})
    assert idx["level"] == [100.0, None]
    assert idx["models"] == [None, 0]
