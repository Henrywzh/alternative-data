from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from openrouter_derived_data import (
    compute_workload_intensity_daily,
    compute_workload_intensity_models,
)
from openrouter_derived_data.identity import (
    compatible_activity_ids,
    load_capability_map,
    rank_capability_families,
)


def _write_capability_map(base_dir: Path) -> None:
    config_dir = base_dir / "config"
    config_dir.mkdir()
    (config_dir / "openrouter_capability_map.json").write_text(
        json.dumps(
            {
                "methodology_version": "openrouter-derived-v1",
                "models": [
                    {"aa_model_id": "claude", "family_id": "anthropic/claude-fable-5", "openrouter_model_ids": ["anthropic/claude-fable-5"]},
                    {"aa_model_id": "sol-max", "family_id": "openai/gpt-5.6-sol", "openrouter_model_ids": ["openai/gpt-5.6-sol", "openai/gpt-5.6-sol-pro"]},
                    {"aa_model_id": "sol-xhigh", "family_id": "openai/gpt-5.6-sol", "openrouter_model_ids": ["openai/gpt-5.6-sol", "openai/gpt-5.6-sol-pro"]},
                    {"aa_model_id": "kimi", "family_id": "moonshotai/kimi-k3", "openrouter_model_ids": ["moonshotai/kimi-k3"]},
                    {"aa_model_id": "glm", "family_id": "z-ai/glm-5.2", "openrouter_model_ids": ["z-ai/glm-5.2"]},
                    {"aa_model_id": "family-6", "family_id": "provider/family-6", "openrouter_model_ids": []},
                    {"aa_model_id": "family-7", "family_id": "provider/family-7", "openrouter_model_ids": []},
                    {"aa_model_id": "family-8", "family_id": "provider/family-8", "openrouter_model_ids": []},
                    {"aa_model_id": "family-9", "family_id": "provider/family-9", "openrouter_model_ids": []},
                    {"aa_model_id": "family-10", "family_id": "provider/family-10", "openrouter_model_ids": []},
                    {"aa_model_id": "future", "family_id": "future/model", "openrouter_model_ids": []},
                ],
            }
        )
    )


def _artificial_analysis_rows() -> pd.DataFrame:
    current = [
        ("claude", "Claude Fable 5", 100),
        ("sol-max", "GPT-5.6 Sol (max)", 99),
        ("sol-xhigh", "GPT-5.6 Sol (xhigh)", 98),
        ("kimi", "Kimi K3", 97),
        ("glm", "GLM-5.2", 96),
        ("family-6", "Family 6", 95),
        ("family-7", "Family 7", 94),
        ("family-8", "Family 8", 93),
        ("family-9", "Family 9", 92),
        ("family-10", "Family 10", 91),
        ("future", "Future model", 90),
        ("unmapped", "Unmapped model", 120),
    ]
    rows = [
        {
            "as_of_date": "2026-07-17",
            "model_id": model_id,
            "model_name": name,
            "release_date": "2026-07-01" if model_id != "future" else "2026-07-15",
            "intelligence_index": intelligence_index,
        }
        for model_id, name, intelligence_index in current
    ]
    rows.extend(
        [
            {
                "as_of_date": "2026-07-09",
                "model_id": "family-10",
                "model_name": "Family 10 old",
                "release_date": "2026-07-01",
                "intelligence_index": 80,
            },
            {
                "as_of_date": "2026-07-19",
                "model_id": "family-10",
                "model_name": "Family 10 future snapshot",
                "release_date": "2026-07-01",
                "intelligence_index": 200,
            },
        ]
    )
    return pd.DataFrame(rows)


def test_rank_capability_families_collapses_configurations_and_uses_asof_snapshot(tmp_path: Path) -> None:
    _write_capability_map(tmp_path)
    models = _artificial_analysis_rows()
    ranked = rank_capability_families(
        models,
        pd.Series(["2026-07-10", "2026-07-18"]),
        load_capability_map(tmp_path),
    )

    july_18 = ranked[ranked["usage_date"] == pd.Timestamp("2026-07-18")]
    assert len(july_18[july_18["family_id"] == "openai/gpt-5.6-sol"]) == 1
    assert july_18.iloc[:5]["capability_tier"].eq("sota").all()
    assert july_18.iloc[5:10]["capability_tier"].eq("frontier_contender").all()
    assert "future/model" not in set(ranked[ranked["usage_date"] == pd.Timestamp("2026-07-10")]["family_id"])
    assert "unmapped/model" not in set(july_18["family_id"])
    assert july_18.iloc[0]["benchmark_snapshot_date"] == pd.Timestamp("2026-07-17")
    assert july_18.iloc[0]["representative_aa_model_id"] == "claude"


def test_rank_capability_families_does_not_rewind_when_latest_snapshot_is_future_only(tmp_path: Path) -> None:
    _write_capability_map(tmp_path)
    models = pd.DataFrame(
        [
            {
                "as_of_date": "2026-07-09",
                "model_id": "claude",
                "model_name": "Claude Fable 5",
                "release_date": "2026-07-01",
                "intelligence_index": 100,
            },
            {
                "as_of_date": "2026-07-17",
                "model_id": "future",
                "model_name": "Future model",
                "release_date": "2026-07-19",
                "intelligence_index": 110,
            },
        ]
    )

    ranked = rank_capability_families(
        models,
        pd.Series(["2026-07-18"]),
        load_capability_map(tmp_path),
    )

    assert ranked.empty


def test_load_capability_map_rejects_duplicate_or_malformed_entries(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "openrouter_capability_map.json").write_text(
        json.dumps(
            {
                "methodology_version": "openrouter-derived-v1",
                "models": [
                    {"aa_model_id": "model", "family_id": "provider/model", "openrouter_model_ids": []},
                    {"aa_model_id": "model", "family_id": "provider/model-duplicate", "openrouter_model_ids": []},
                ],
            }
        )
    )

    with pytest.raises(ValueError, match="duplicate aa_model_id"):
        load_capability_map(tmp_path)


def test_capability_map_returns_only_exact_compatible_activity_routes(tmp_path: Path) -> None:
    _write_capability_map(tmp_path)
    capability_map = load_capability_map(tmp_path)

    assert compatible_activity_ids(capability_map, "sol-max") == frozenset(
        {"openai/gpt-5.6-sol", "openai/gpt-5.6-sol-pro"}
    )
    assert compatible_activity_ids(capability_map, "not-mapped") == frozenset()


def test_workload_intensity_uses_matching_rows_and_rolling_ratio_of_sums() -> None:
    activity = pd.DataFrame(
        [
            {"usage_date": "2026-07-16", "model_permaslug": "a/model", "entity_id": "a", "total_tokens": 1000, "prompt_tokens": 800, "completion_tokens": 200, "request_count": 10},
            {"usage_date": "2026-07-16", "model_permaslug": "b/model", "entity_id": "b", "total_tokens": 9000, "prompt_tokens": 6000, "completion_tokens": 3000, "request_count": 90},
            {"usage_date": "2026-07-17", "model_permaslug": "a/model", "entity_id": "a", "total_tokens": 4000, "prompt_tokens": 3000, "completion_tokens": 1000, "request_count": 20},
            {"usage_date": "2026-07-17", "model_permaslug": "zero/model", "entity_id": "zero", "total_tokens": 999999, "prompt_tokens": 1, "completion_tokens": 1, "request_count": 0},
            {"usage_date": "2026-07-18", "model_permaslug": "a/model", "entity_id": "a", "total_tokens": 999999, "prompt_tokens": 1, "completion_tokens": 1, "request_count": 1},
        ]
    )

    result = compute_workload_intensity_daily(activity, today=date(2026, 7, 18))

    total_1d = result[
        (result.metric_id == "total_tokens_per_request")
        & (result.rolling_window_days == 1)
    ]
    assert total_1d.set_index("usage_date").loc["2026-07-16", "value"] == pytest.approx(100.0)
    total_7d = result[
        (result.metric_id == "total_tokens_per_request")
        & (result.rolling_window_days == 7)
    ]
    assert total_7d.iloc[-1]["value"] == pytest.approx(14000 / 120)
    assert "2026-07-18" not in set(result["usage_date"])
    assert result["excluded_zero_request_rows"].eq(1).all()


def test_workload_intensity_models_uses_one_eligible_row_set_for_shares() -> None:
    activity = pd.DataFrame(
        [
            {"usage_date": "2026-06-17", "model_permaslug": "outside/window", "entity_id": "outside", "total_tokens": 100000, "prompt_tokens": 90000, "completion_tokens": 10000, "request_count": 1},
            {"usage_date": "2026-06-18", "model_permaslug": "a/model", "entity_id": "a", "total_tokens": 1000, "prompt_tokens": 700, "completion_tokens": 300, "request_count": 10},
            {"usage_date": "2026-07-17", "model_permaslug": "b/model", "entity_id": "b", "total_tokens": 9000, "prompt_tokens": 6000, "completion_tokens": 3000, "request_count": 90},
            {"usage_date": "2026-07-17", "model_permaslug": "zero/model", "entity_id": "zero", "total_tokens": 999999, "prompt_tokens": 1, "completion_tokens": 1, "request_count": 0},
            {"usage_date": "2026-07-18", "model_permaslug": "current/model", "entity_id": "current", "total_tokens": 999999, "prompt_tokens": 1, "completion_tokens": 1, "request_count": 1},
        ]
    )

    result = compute_workload_intensity_models(activity, today=date(2026, 7, 18))

    assert set(result["model_id"]) == {"a/model", "b/model"}
    assert result["window_start_date"].eq("2026-06-18").all()
    assert result["window_end_date"].eq("2026-07-17").all()
    assert result["token_share"].sum() == pytest.approx(1.0)
    assert result["request_share"].sum() == pytest.approx(1.0)
    assert (result["intensity_ratio"] == result["token_share"] / result["request_share"]).all()
