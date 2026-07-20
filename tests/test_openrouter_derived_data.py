from __future__ import annotations

import json
import sys
import tomllib
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from openrouter_derived_data import (
    OpenRouterDerivedPipeline,
    compute_price_metrics,
    compute_workload_intensity_daily,
    compute_workload_intensity_models,
)
from openrouter_derived_data.identity import (
    CapabilityEntry,
    CapabilityMap,
    CapabilityRoute,
    compatible_activity_ids,
    load_capability_map,
    rank_capability_families,
)
from openrouter_derived_data.cli import main


def _write_capability_map(base_dir: Path) -> None:
    config_dir = base_dir / "config"
    config_dir.mkdir()
    (config_dir / "openrouter_capability_map.json").write_text(
        json.dumps(
            {
                "methodology_version": "openrouter-derived-v1",
                "models": [
                    {"aa_model_id": "claude", "family_id": "anthropic/claude-fable-5", "effective_from": "2026-07-01", "openrouter_routes": [{"model_id": "anthropic/claude-fable-5", "effective_from": "2026-07-01"}]},
                    {"aa_model_id": "sol-max", "family_id": "openai/gpt-5.6-sol", "effective_from": "2026-07-01", "openrouter_routes": [{"model_id": "openai/gpt-5.6-sol", "effective_from": "2026-07-01"}, {"model_id": "openai/gpt-5.6-sol-pro", "effective_from": "2026-07-05"}]},
                    {"aa_model_id": "sol-xhigh", "family_id": "openai/gpt-5.6-sol", "effective_from": "2026-07-01", "openrouter_routes": [{"model_id": "openai/gpt-5.6-sol", "effective_from": "2026-07-01"}, {"model_id": "openai/gpt-5.6-sol-pro", "effective_from": "2026-07-05"}]},
                    {"aa_model_id": "kimi", "family_id": "moonshotai/kimi-k3", "effective_from": "2026-07-01", "openrouter_routes": [{"model_id": "moonshotai/kimi-k3", "effective_from": "2026-07-01"}]},
                    {"aa_model_id": "glm", "family_id": "z-ai/glm-5.2", "effective_from": "2026-07-01", "openrouter_routes": [{"model_id": "z-ai/glm-5.2", "effective_from": "2026-07-01"}]},
                    {"aa_model_id": "family-6", "family_id": "provider/family-6", "effective_from": "2026-07-01", "openrouter_routes": []},
                    {"aa_model_id": "family-7", "family_id": "provider/family-7", "effective_from": "2026-07-01", "openrouter_routes": []},
                    {"aa_model_id": "family-8", "family_id": "provider/family-8", "effective_from": "2026-07-01", "openrouter_routes": []},
                    {"aa_model_id": "family-9", "family_id": "provider/family-9", "effective_from": "2026-07-01", "openrouter_routes": []},
                    {"aa_model_id": "family-10", "family_id": "provider/family-10", "effective_from": "2026-07-01", "openrouter_routes": []},
                    {"aa_model_id": "future", "family_id": "future/model", "effective_from": "2026-07-15", "openrouter_routes": []},
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
    assert set(july_18["family_rank"]) == set(range(2, 12))
    assert july_18.loc[july_18["family_rank"].le(5), "capability_tier"].eq("sota").all()
    assert july_18.loc[july_18["family_rank"].between(6, 10), "capability_tier"].eq("frontier_contender").all()
    assert "future/model" not in set(ranked[ranked["usage_date"] == pd.Timestamp("2026-07-10")]["family_id"])
    assert "unmapped/model" not in set(july_18["family_id"])
    assert july_18.iloc[0]["benchmark_snapshot_date"] == pd.Timestamp("2026-07-17")
    assert july_18.iloc[0]["representative_aa_model_id"] == "claude"
    assert july_18.iloc[0]["family_rank"] == 2


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


def test_rank_capability_families_backfills_latest_scores_after_release(tmp_path: Path) -> None:
    _write_capability_map(tmp_path)
    models = _artificial_analysis_rows().loc[lambda frame: frame["as_of_date"].ne("2026-07-19")]

    ranked = rank_capability_families(
        models,
        pd.Series(["2026-07-10", "2026-07-18"]),
        load_capability_map(tmp_path),
        backfill_latest_snapshot=True,
    )

    assert set(ranked["usage_date"].astype(str)) == {"2026-07-10", "2026-07-18"}
    assert ranked["model_match_status"].eq("backfilled_current_score_exact_match").all()
    assert ranked["benchmark_snapshot_date"].astype(str).eq("2026-07-17").all()


def test_backfilled_capability_family_never_precedes_release_date(tmp_path: Path) -> None:
    _write_capability_map(tmp_path)

    ranked = rank_capability_families(
        _artificial_analysis_rows(),
        pd.Series(["2026-06-30"]),
        load_capability_map(tmp_path),
        backfill_latest_snapshot=True,
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
                    {"aa_model_id": "model", "family_id": "provider/model", "effective_from": "2026-01-01", "openrouter_routes": []},
                    {"aa_model_id": "model", "family_id": "provider/model-duplicate", "effective_from": "2026-01-01", "openrouter_routes": []},
                ],
            }
        )
    )

    with pytest.raises(ValueError, match="duplicate aa_model_id"):
        load_capability_map(tmp_path)


def test_capability_map_rejects_route_shared_across_different_families(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "openrouter_capability_map.json").write_text(
        json.dumps(
            {
                "methodology_version": "openrouter-derived-v1",
                "models": [
                    {"aa_model_id": "a", "family_id": "provider/family-a", "effective_from": "2026-01-01", "openrouter_routes": [{"model_id": "provider/shared", "effective_from": "2026-01-01"}]},
                    {"aa_model_id": "b", "family_id": "provider/family-b", "effective_from": "2026-01-01", "openrouter_routes": [{"model_id": "provider/shared", "effective_from": "2026-01-01"}]},
                ],
            }
        )
    )

    with pytest.raises(ValueError, match="assigned to multiple families"):
        load_capability_map(tmp_path)


def test_capability_map_allows_route_shared_within_one_family(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "openrouter_capability_map.json").write_text(
        json.dumps(
            {
                "methodology_version": "openrouter-derived-v1",
                "models": [
                    {"aa_model_id": "a-max", "family_id": "provider/family-a", "effective_from": "2026-01-01", "openrouter_routes": [{"model_id": "provider/shared", "effective_from": "2026-01-01"}]},
                    {"aa_model_id": "a-xhigh", "family_id": "provider/family-a", "effective_from": "2026-01-01", "openrouter_routes": [{"model_id": "provider/shared", "effective_from": "2026-01-01"}]},
                ],
            }
        )
    )

    capability_map = load_capability_map(tmp_path)

    assert len(capability_map.entries) == 2


def test_capability_map_returns_only_exact_compatible_activity_routes(tmp_path: Path) -> None:
    _write_capability_map(tmp_path)
    capability_map = load_capability_map(tmp_path)

    assert compatible_activity_ids(capability_map, "sol-max", pd.Timestamp("2026-07-04")) == frozenset(
        {"openai/gpt-5.6-sol"}
    )
    assert compatible_activity_ids(capability_map, "sol-max", pd.Timestamp("2026-07-05")) == frozenset(
        {"openai/gpt-5.6-sol", "openai/gpt-5.6-sol-pro"}
    )
    assert compatible_activity_ids(capability_map, "not-mapped", pd.Timestamp("2026-07-05")) == frozenset()


def test_future_capability_entry_and_route_do_not_leak_backward(tmp_path: Path) -> None:
    _write_capability_map(tmp_path)
    capability_map = load_capability_map(tmp_path)

    before_entry = rank_capability_families(
        _artificial_analysis_rows(), pd.Series(["2026-07-10"]), capability_map
    )

    assert "future/model" not in set(before_entry["family_id"])
    assert compatible_activity_ids(
        capability_map, "sol-max", pd.Timestamp("2026-07-04")
    ) == frozenset({"openai/gpt-5.6-sol"})


def test_unmapped_benchmark_leaders_leave_explicit_top_five_and_top_ten_rank_gaps() -> None:
    entries = tuple(
        CapabilityEntry(
            aa_model_id=f"mapped-{index}",
            family_id=f"provider/family-{index}",
            effective_from=pd.Timestamp("2026-01-01"),
            openrouter_routes=(
                CapabilityRoute(
                    f"provider/model-{index}", pd.Timestamp("2026-01-01")
                ),
            ),
        )
        for index in range(1, 11)
    )
    capability_map = CapabilityMap("coverage-test-v1", entries)
    model_rows = [
        {
            "as_of_date": "2026-07-17",
            "model_id": f"mapped-{index}",
            "model_name": f"Mapped {index}",
            "release_date": "2026-01-01",
            "intelligence_index": 100 - index,
        }
        for index in range(1, 11)
    ]
    model_rows.extend(
        [
            {
                "as_of_date": "2026-07-17",
                "model_id": "unmapped-top",
                "model_name": "Unmapped top",
                "release_date": "2026-01-01",
                "intelligence_index": 110,
            },
            {
                "as_of_date": "2026-07-17",
                "model_id": "unmapped-middle",
                "model_name": "Unmapped middle",
                "release_date": "2026-01-01",
                "intelligence_index": 94.5,
            },
        ]
    )

    ranked = rank_capability_families(
        pd.DataFrame(model_rows), pd.Series(["2026-07-17"]), capability_map
    )

    ranks = set(ranked["family_rank"])
    assert 1 not in ranks
    assert 7 not in ranks
    assert set(range(1, 6)) - ranks == {1}
    assert set(range(6, 11)) - ranks == {7}

    pricing = pd.DataFrame(
        [
            {
                "model_id": f"provider/model-{index}",
                "snapshot_ts": "2026-07-16T00:00:00Z",
                "pricing_prompt": index / 1_000_000,
                "pricing_completion": index / 1_000_000,
            }
            for index in range(1, 11)
        ]
    )
    price_metrics = compute_price_metrics(
        _economics(),
        pricing,
        ranked,
        capability_map,
        today=date(2026, 7, 18),
    )
    sota = _price_metric(price_metrics, "sota_median_list_price")
    contenders = _price_metric(
        price_metrics, "frontier_contenders_median_list_price"
    )
    assert sota["priced_family_count"] == 4
    assert pd.isna(sota["value"])
    assert contenders["priced_family_count"] == 4
    assert pd.isna(contenders["value"])


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
    assert total_1d.set_index("usage_date").loc["2026-07-16", "excluded_zero_request_rows"] == 0
    assert total_1d.set_index("usage_date").loc["2026-07-17", "excluded_zero_request_rows"] == 1


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


def test_workload_intensity_uses_metric_specific_calendar_windows_and_coverage() -> None:
    activity = pd.DataFrame(
        [
            {"usage_date": "2026-07-01", "model_permaslug": "a/model", "entity_id": "a", "total_tokens": 100, "prompt_tokens": None, "completion_tokens": 10, "request_count": 2},
            {"usage_date": "2026-07-01", "model_permaslug": "invalid/model", "entity_id": "invalid", "total_tokens": 999, "prompt_tokens": 999, "completion_tokens": 999, "request_count": 0},
            {"usage_date": "2026-07-02", "model_permaslug": "b/model", "entity_id": "b", "total_tokens": None, "prompt_tokens": 20, "completion_tokens": None, "request_count": 3},
            {"usage_date": "2026-07-05", "model_permaslug": "b/model", "entity_id": "b", "total_tokens": 40, "prompt_tokens": 30, "completion_tokens": 10, "request_count": 4},
            {"usage_date": "2026-07-05", "model_permaslug": "partial/model", "entity_id": "partial", "total_tokens": None, "prompt_tokens": 5, "completion_tokens": None, "request_count": 100},
            {"usage_date": "2026-07-06", "model_permaslug": "missing/model", "entity_id": "missing", "total_tokens": None, "prompt_tokens": None, "completion_tokens": None, "request_count": 1},
            {"usage_date": "2026-07-08", "model_permaslug": "c/model", "entity_id": "c", "total_tokens": 70, "prompt_tokens": 50, "completion_tokens": 20, "request_count": 7},
            {"usage_date": "2026-07-09", "model_permaslug": "current/model", "entity_id": "current", "total_tokens": 999, "prompt_tokens": 999, "completion_tokens": 999, "request_count": 0},
        ]
    )

    result = compute_workload_intensity_daily(activity, today=date(2026, 7, 9))

    total_1d = result[(result.metric_id == "total_tokens_per_request") & (result.rolling_window_days == 1)].set_index("usage_date")
    prompt_1d = result[(result.metric_id == "prompt_tokens_per_request") & (result.rolling_window_days == 1)].set_index("usage_date")
    completion_1d = result[(result.metric_id == "completion_tokens_per_request") & (result.rolling_window_days == 1)].set_index("usage_date")
    total_7d = result[(result.metric_id == "total_tokens_per_request") & (result.rolling_window_days == 7)].set_index("usage_date")

    assert pd.isna(total_1d.loc["2026-07-02", "value"])
    assert pd.isna(total_1d.loc["2026-07-02", "numerator"])
    assert pd.isna(total_1d.loc["2026-07-02", "denominator"])
    assert total_1d.loc["2026-07-05", "value"] == pytest.approx(10.0)
    assert prompt_1d.loc["2026-07-05", "value"] == pytest.approx(35 / 104)
    assert pd.isna(completion_1d.loc["2026-07-02", "value"])
    assert pd.isna(completion_1d.loc["2026-07-06", "value"])

    assert total_7d.loc["2026-07-07", "value"] == pytest.approx(140 / 6)
    assert total_7d.loc["2026-07-07", "observed_model_count"] == 2
    assert total_7d.loc["2026-07-08", "value"] == pytest.approx(110 / 11)
    assert total_1d.loc["2026-07-01", "excluded_zero_request_rows"] == 1
    assert total_1d.loc["2026-07-07", "excluded_zero_request_rows"] == 0
    assert total_7d.loc["2026-07-07", "excluded_zero_request_rows"] == 1
    assert total_7d.loc["2026-07-08", "excluded_zero_request_rows"] == 0


def _price_capability_map() -> CapabilityMap:
    def entry(aa_model_id: str, family_id: str, *model_ids: str) -> CapabilityEntry:
        return CapabilityEntry(
            aa_model_id=aa_model_id,
            family_id=family_id,
            effective_from=pd.Timestamp("2026-01-01"),
            openrouter_routes=tuple(
                CapabilityRoute(model_id, pd.Timestamp("2026-01-01"))
                for model_id in model_ids
            ),
        )

    entries = [
        entry("aa-a", "family-a", "provider/a", "provider/a:free"),
        entry("aa-a-lower", "family-a", "provider/a-lower-capability"),
        entry("aa-b", "family-b", "provider/b", "provider/b:fast"),
        entry("aa-c", "family-c", "provider/c"),
        entry("aa-d", "family-d", "provider/d"),
        entry("aa-e", "family-e", "provider/e"),
        entry("aa-f", "family-f", "provider/f"),
    ]
    return CapabilityMap(methodology_version="price-test-v1", entries=tuple(entries))


def _price_rankings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "usage_date": "2026-07-17",
                "benchmark_snapshot_date": "2026-07-16",
                "family_id": f"family-{letter}",
                "family_rank": rank,
                "capability_tier": "sota",
                "representative_aa_model_id": f"aa-{letter}",
                "model_match_status": "exact_curated_match",
                "methodology_version": "price-test-v1",
            }
            for rank, letter in enumerate("abcde", start=1)
        ]
    )


def _pricing_history() -> pd.DataFrame:
    rows = [
        ("provider/a", "2026-07-16T12:00:00Z", 1.0),
        ("provider/a:free", "2026-07-16T12:00:00Z", 0.0),
        ("provider/b", "2026-07-16T12:00:00Z", 2.0),
        ("provider/b:fast", "2026-07-16T12:00:00Z", 4.0),
        ("provider/c", "2026-07-16T12:00:00Z", 3.0),
        ("provider/c", "2026-07-18T00:00:00Z", 99.0),
        ("provider/d", "2026-07-16T12:00:00Z", 4.0),
        ("provider/e", "2026-07-16T12:00:00Z", 5.0),
        ("provider/a-lower-capability", "2026-07-16T12:00:00Z", 50.0),
    ]
    return pd.DataFrame(
        [
            {
                "model_id": model_id,
                "snapshot_ts": snapshot_ts,
                "pricing_prompt": price / 1_000_000,
                "pricing_completion": price / 1_000_000,
            }
            for model_id, snapshot_ts, price in rows
        ]
    )


def _economics() -> pd.DataFrame:
    rows = [
        ("provider/a", 100.0, 0.0001, "matched_asof", 1.0),
        ("provider/a:free", 50.0, 0.0, "free_model_zero_revenue", 0.0),
        ("provider/b", 100.0, 0.0002, "matched_asof", 2.0),
        ("provider/b:fast", 100.0, 0.0004, "matched_asof", 4.0),
        ("provider/c", 100.0, 0.0003, "matched_asof", 3.0),
        ("provider/d", 100.0, 0.0004, "matched_asof", 4.0),
        ("provider/e", 100.0, 0.0005, "matched_asof", 5.0),
        ("provider/a-lower-capability", 1_000.0, 0.05, "matched_asof", 50.0),
        ("provider/unpriced", 70.0, None, "unresolved_missing_pricing", None),
        ("provider/legacy", 100.0, 0.0001, "backcast_earliest_pricing", 1.0),
    ]
    return pd.DataFrame(
        [
            {
                "usage_date": "2026-07-17",
                "model_permaslug": model_id,
                "total_tokens": tokens,
                "prompt_tokens": tokens,
                "completion_tokens": 0.0,
                "estimated_revenue": revenue,
                "pricing_snapshot_ts": "2026-07-16T12:00:00Z" if price is not None else None,
                "pricing_prompt": None if price is None else price / 1_000_000,
                "pricing_completion": None if price is None else price / 1_000_000,
                "pricing_join_status": status,
            }
            for model_id, tokens, revenue, status, price in rows
        ]
    )


def _price_metric(result: pd.DataFrame, metric_id: str) -> pd.Series:
    matches = result[
        result["usage_date"].eq("2026-07-17")
        & result["metric_id"].eq(metric_id)
    ]
    assert len(matches) == 1
    return matches.iloc[0]


def test_sota_prices_use_distinct_families_strict_asof_and_minimum_coverage() -> None:
    result = compute_price_metrics(
        _economics(), _pricing_history(), _price_rankings(), _price_capability_map()
    )

    list_price = _price_metric(result, "sota_median_list_price")
    assert list_price["value"] == pytest.approx(3.0)
    assert list_price["priced_family_count"] == 5
    assert pd.Timestamp(list_price["pricing_snapshot_date"]) <= pd.Timestamp("2026-07-17")

    realized = _price_metric(result, "realized_sota_price")
    assert realized["value"] == pytest.approx(
        realized["numerator"] / realized["denominator"] * 1_000_000
    )
    assert realized["numerator"] == pytest.approx(0.0019)
    assert realized["denominator"] == pytest.approx(600.0)
    assert realized["observed_family_count"] == 5
    assert realized["excluded_free_tokens"] == pytest.approx(50.0)
    assert realized["excluded_unpriced_tokens"] == pytest.approx(0.0)
    assert realized["pricing_join_status"] != "backcast_earliest_pricing"


def test_sota_list_price_is_missing_below_three_priced_families() -> None:
    pricing = _pricing_history().loc[lambda frame: frame.model_id.isin(["provider/a", "provider/b"])]

    result = compute_price_metrics(
        _economics(), pricing, _price_rankings(), _price_capability_map()
    )

    metric = _price_metric(result, "sota_median_list_price")
    assert metric["priced_family_count"] == 2
    assert pd.isna(metric["value"])


def test_realized_sota_price_is_missing_below_three_observed_families() -> None:
    economics = _economics().loc[
        lambda frame: ~frame.model_permaslug.isin(["provider/c", "provider/d", "provider/e"])
    ]

    result = compute_price_metrics(
        economics, _pricing_history(), _price_rankings(), _price_capability_map()
    )

    metric = _price_metric(result, "realized_sota_price")
    assert metric["observed_family_count"] == 2
    assert pd.isna(metric["value"])


def test_price_metrics_reject_future_prices_and_keep_exact_route_prices() -> None:
    result = compute_price_metrics(
        _economics(), _pricing_history(), _price_rankings(), _price_capability_map()
    )

    list_price = _price_metric(result, "sota_median_list_price")
    realized = _price_metric(result, "realized_sota_price")
    assert list_price["value"] == pytest.approx(3.0), "future $99 price must not leak backward"
    assert realized["numerator"] == pytest.approx(0.0019), "fast must retain its $4 route price"
    assert realized["included_tokens"] == pytest.approx(600.0), "lower-capability sibling is excluded"


def test_price_metrics_isolate_legacy_market_backcast_provenance() -> None:
    result = compute_price_metrics(
        _economics(), _pricing_history(), _price_rankings(), _price_capability_map()
    )

    market = _price_metric(result, "realized_market_average")
    sota = _price_metric(result, "realized_sota_price")
    assert "backcast_earliest_pricing" in market["pricing_join_status"]
    assert "backcast_earliest_pricing" not in sota["pricing_join_status"]


def test_fixed_workload_basket_is_missing_when_a_price_cohort_is_unsupported() -> None:
    economics = _economics().loc[lambda frame: frame.pricing_prompt.ge(0.5e-6) | frame.pricing_prompt.isna()]

    result = compute_price_metrics(
        economics, _pricing_history(), _price_rankings(), _price_capability_map()
    )

    assert pd.isna(_price_metric(result, "low_priced_realized")["value"])
    assert pd.isna(_price_metric(result, "fixed_workload_basket")["value"])


def test_price_metrics_emit_calendar_day_rolling_rows_for_sparse_activity() -> None:
    economics = _economics().iloc[[0, 2]].copy()
    economics.loc[economics.index[0], "usage_date"] = "2026-07-11"
    economics.loc[economics.index[1], "usage_date"] = "2026-07-17"

    result = compute_price_metrics(
        economics,
        pd.DataFrame(),
        pd.DataFrame(),
        _price_capability_map(),
    )

    market_dates = set(
        result.loc[result.metric_id.eq("realized_market_average"), "usage_date"]
    )
    assert "2026-07-12" in market_dates


def _ranked_families(
    usage_date: str,
    letters: str,
    *,
    first_rank: int = 1,
) -> pd.DataFrame:
    tier = "sota" if first_rank == 1 else "frontier_contender"
    return pd.DataFrame(
        [
            {
                "usage_date": usage_date,
                "benchmark_snapshot_date": usage_date,
                "family_id": f"family-{letter}",
                "family_rank": rank,
                "capability_tier": tier,
                "representative_aa_model_id": f"aa-{letter}",
                "model_match_status": "exact_curated_match",
                "methodology_version": "price-test-v1",
            }
            for rank, letter in enumerate(letters, start=first_rank)
        ]
    )


def test_realized_sota_price_uses_each_activity_days_point_in_time_membership() -> None:
    economics = _economics().loc[
        lambda frame: frame.model_permaslug.isin(
            ["provider/a", "provider/b", "provider/c"]
        )
    ].copy()
    economics.loc[
        economics.model_permaslug.eq("provider/a"), "usage_date"
    ] = "2026-07-11"
    economics.loc[
        economics.model_permaslug.eq("provider/a"), "pricing_snapshot_ts"
    ] = "2026-07-10T12:00:00Z"
    earlier_future_member = economics.loc[
        economics.model_permaslug.eq("provider/a")
    ].copy()
    earlier_future_member["model_permaslug"] = "provider/f"
    earlier_future_member["total_tokens"] = 1_000.0
    earlier_future_member["estimated_revenue"] = 0.01
    earlier_future_member["pricing_prompt"] = 10e-6
    earlier_future_member["pricing_completion"] = 10e-6
    economics = pd.concat([economics, earlier_future_member], ignore_index=True)
    pricing = pd.concat(
        [
            _pricing_history(),
            pd.DataFrame(
                [
                    {
                        "model_id": "provider/a",
                        "snapshot_ts": "2026-07-10T12:00:00Z",
                        "pricing_prompt": 1e-6,
                        "pricing_completion": 1e-6,
                    },
                    {
                        "model_id": "provider/f",
                        "snapshot_ts": "2026-07-10T12:00:00Z",
                        "pricing_prompt": 10e-6,
                        "pricing_completion": 10e-6,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    rankings = pd.concat(
        [
            _ranked_families("2026-07-11", "abcde"),
            _ranked_families("2026-07-17", "bcdef"),
        ],
        ignore_index=True,
    )

    result = compute_price_metrics(
        economics, pricing, rankings, _price_capability_map()
    )

    realized = _price_metric(result, "realized_sota_price")
    assert realized["numerator"] == pytest.approx(0.0006)
    assert realized["denominator"] == pytest.approx(300.0)
    assert realized["observed_family_count"] == 3


def test_sota_price_metrics_require_the_complete_rank_one_to_five_cohort() -> None:
    partial_rankings = _price_rankings().loc[lambda frame: frame.family_rank.le(3)]

    result = compute_price_metrics(
        _economics(),
        _pricing_history(),
        partial_rankings,
        _price_capability_map(),
    )

    list_price = _price_metric(result, "sota_median_list_price")
    realized = _price_metric(result, "realized_sota_price")
    assert list_price["expected_family_count"] == 5
    assert list_price["priced_family_count"] == 3
    assert pd.isna(list_price["value"])
    assert realized["expected_family_count"] == 5
    assert pd.isna(realized["value"])


def test_frontier_contender_price_requires_complete_ranks_six_to_ten() -> None:
    complete = _ranked_families("2026-07-17", "abcde", first_rank=6)

    complete_result = compute_price_metrics(
        _economics(), _pricing_history(), complete, _price_capability_map()
    )
    complete_metric = _price_metric(
        complete_result, "frontier_contenders_median_list_price"
    )
    assert complete_metric["expected_family_count"] == 5
    assert complete_metric["priced_family_count"] == 5
    assert complete_metric["value"] == pytest.approx(3.0)

    partial_result = compute_price_metrics(
        _economics(),
        _pricing_history(),
        complete.loc[lambda frame: frame.family_rank.le(8)],
        _price_capability_map(),
    )
    partial_metric = _price_metric(
        partial_result, "frontier_contenders_median_list_price"
    )
    assert partial_metric["expected_family_count"] == 5
    assert partial_metric["priced_family_count"] == 3
    assert pd.isna(partial_metric["value"])


def test_missing_price_component_stays_unpriced_and_cannot_support_basket() -> None:
    economics = pd.DataFrame(
        [
            {
                "usage_date": "2026-07-17",
                "model_permaslug": "provider/premium",
                "total_tokens": 100.0,
                "estimated_revenue": 0.0005,
                "pricing_snapshot_ts": "2026-07-16T12:00:00Z",
                "pricing_prompt": 5e-6,
                "pricing_completion": 5e-6,
                "pricing_join_status": "matched_asof",
            },
            {
                "usage_date": "2026-07-17",
                "model_permaslug": "provider/low",
                "total_tokens": 100.0,
                "estimated_revenue": 0.00001,
                "pricing_snapshot_ts": "2026-07-16T12:00:00Z",
                "pricing_prompt": 0.1e-6,
                "pricing_completion": 0.1e-6,
                "pricing_join_status": "matched_asof",
            },
            {
                "usage_date": "2026-07-17",
                "model_permaslug": "provider/missing-completion",
                "total_tokens": 1_000.0,
                "estimated_revenue": 0.001,
                "pricing_snapshot_ts": "2026-07-16T12:00:00Z",
                "pricing_prompt": 1e-6,
                "pricing_completion": None,
                "pricing_join_status": "matched_asof",
            },
        ]
    )

    result = compute_price_metrics(
        economics, pd.DataFrame(), pd.DataFrame(), _price_capability_map()
    )

    market = _price_metric(result, "realized_market_average")
    assert market["denominator"] == pytest.approx(200.0)
    assert market["excluded_unpriced_tokens"] == pytest.approx(1_000.0)
    mid = _price_metric(result, "mid_priced_realized")
    basket = _price_metric(result, "fixed_workload_basket")
    assert pd.isna(mid["value"])
    assert mid["excluded_unpriced_tokens"] == pytest.approx(1_000.0)
    assert pd.isna(basket["value"])
    assert basket["excluded_unpriced_tokens"] == pytest.approx(1_000.0)


def test_price_metrics_emit_original_indices_and_volume_weighted_sota_atp() -> None:
    result = compute_price_metrics(
        _economics(),
        _pricing_history(),
        _price_rankings(),
        _price_capability_map(),
    )

    assert {
        "original_spend_weighted_tei",
        "original_cpi_workload_basket",
        "original_volume_weighted_tei",
        "original_frontier_tei",
        "original_value_tei",
        "sota_volume_weighted_atp",
    } <= set(result["metric_id"])
    sota = result.loc[result["metric_id"].eq("sota_volume_weighted_atp")].iloc[-1]
    assert sota["value"] == pytest.approx(
        sota["numerator"] / sota["denominator"] * 1_000_000
    )


def test_sota_atp_accepts_dated_activity_route_with_canonical_snapshot_price() -> None:
    economics = _economics().copy()
    economics.loc[economics["model_permaslug"].eq("provider/a"), "model_permaslug"] = "provider/a-20260709"
    capability = _price_capability_map()
    first = capability.entries[0]
    dated_first = CapabilityEntry(
        aa_model_id=first.aa_model_id,
        family_id=first.family_id,
        effective_from=first.effective_from,
        openrouter_routes=first.openrouter_routes
        + (CapabilityRoute("provider/a-20260709", first.effective_from),),
    )
    capability = CapabilityMap(
        methodology_version=capability.methodology_version,
        entries=(dated_first, *capability.entries[1:]),
    )

    result = compute_price_metrics(
        economics, _pricing_history(), _price_rankings(), capability
    )

    sota = _price_metric(result, "sota_volume_weighted_atp")
    assert sota["observed_family_count"] == 5
    assert pd.notna(sota["value"])


def test_price_metrics_exclude_current_day_and_preserve_prior_values() -> None:
    economics = _economics()
    prior = compute_price_metrics(
        economics,
        _pricing_history(),
        _price_rankings(),
        _price_capability_map(),
        today=date(2026, 7, 18),
    )
    current_day = economics.iloc[[0]].copy()
    current_day["usage_date"] = "2026-07-18"
    current_day["total_tokens"] = 10**15
    current_day["estimated_revenue"] = 10**12
    current_day_pricing = _pricing_history().iloc[[0]].copy()
    current_day_pricing["snapshot_ts"] = "2026-07-18T12:00:00Z"
    current_day_pricing[["pricing_prompt", "pricing_completion"]] = 999.0

    result = compute_price_metrics(
        pd.concat([economics, current_day], ignore_index=True),
        pd.concat([_pricing_history(), current_day_pricing], ignore_index=True),
        _price_rankings(),
        _price_capability_map(),
        today=date(2026, 7, 18),
    )

    assert pd.to_datetime(result["usage_date"]).max() == pd.Timestamp("2026-07-17")
    pd.testing.assert_frame_equal(result.reset_index(drop=True), prior.reset_index(drop=True))


def test_price_metrics_choose_one_latest_complete_provenance_tuple() -> None:
    economics = _economics()
    old_run = economics.iloc[:5].assign(
        source_url="https://old.example",
        source_run_id="old-run",
        scraped_at="2026-07-17T00:00:00Z",
    )
    new_run = economics.iloc[5:].assign(
        source_url="https://new.example",
        source_run_id="new-run",
        scraped_at="2026-07-18T00:00:00Z",
    )
    economics = pd.concat([new_run, old_run], ignore_index=True)

    result = compute_price_metrics(
        economics,
        _pricing_history(),
        _price_rankings(),
        _price_capability_map(),
        today=date(2026, 7, 18),
    )

    assert set(result["source_url"]) == {"https://new.example"}
    assert set(result["source_run_id"]) == {"new-run"}
    assert set(result["scraped_at"]) == {"2026-07-18T00:00:00Z"}


def test_price_metrics_fail_closed_when_economics_provenance_is_missing() -> None:
    result = compute_price_metrics(
        _economics(),
        _pricing_history(),
        _price_rankings(),
        _price_capability_map(),
        today=date(2026, 7, 18),
    )

    assert set(result["source_url"]) == {"derived://openrouter-price-metrics"}
    assert set(result["source_run_id"]) == {"derived-unattributed"}
    assert result["scraped_at"].isna().all()


_DAILY_MART_COLUMNS = [
    "dataset_id",
    "source_url",
    "source_run_id",
    "scraped_at",
    "usage_date",
    "metric_id",
    "cohort_id",
    "value",
    "numerator",
    "denominator",
    "rolling_window_days",
    "benchmark_snapshot_date",
    "pricing_snapshot_date",
    "expected_family_count",
    "priced_family_count",
    "observed_family_count",
    "observed_model_count",
    "included_tokens",
    "excluded_free_tokens",
    "excluded_unpriced_tokens",
    "excluded_zero_request_rows",
    "pricing_join_status",
    "methodology_version",
]
_MODEL_MART_COLUMNS = [
    "window_start_date",
    "window_end_date",
    "model_id",
    "company_id",
    "total_tokens",
    "prompt_tokens",
    "completion_tokens",
    "request_count",
    "token_share",
    "request_share",
    "tokens_per_request",
    "intensity_ratio",
    "model_match_status",
    "methodology_version",
]


def _seed_pipeline_inputs(base_dir: Path) -> dict[str, Path]:
    _write_capability_map(base_dir)
    activity_path = base_dir / "data/normalized/openrouter/openrouter_model_activity.parquet"
    economics_path = base_dir / "data/normalized/marts/daily_provider_economics.parquet"
    pricing_path = base_dir / "data/normalized/compute_availability/raw_openrouter_models.parquet"
    models_path = base_dir / "data/normalized/artificial_analysis/artificial_analysis_models_daily.parquet"
    for path in (activity_path, economics_path, pricing_path, models_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    activity = pd.DataFrame(
        [
            {
                "usage_date": "2026-07-16",
                "model_permaslug": "provider/a",
                "entity_id": "provider-a",
                "total_tokens": 200.0,
                "prompt_tokens": 150.0,
                "completion_tokens": 50.0,
                "request_count": 2.0,
                "source_url": "https://openrouter.ai/activity",
                "source_run_id": "activity-run",
                "scraped_at": "2026-07-19T00:00:00Z",
            },
            {
                "usage_date": "2026-07-17",
                "model_permaslug": "provider/b",
                "entity_id": "provider-b",
                "total_tokens": 800.0,
                "prompt_tokens": 600.0,
                "completion_tokens": 200.0,
                "request_count": 4.0,
                "source_url": "https://openrouter.ai/activity",
                "source_run_id": "activity-run",
                "scraped_at": "2026-07-19T00:00:00Z",
            },
        ]
    )
    economics = _economics().assign(
        source_url="https://openrouter.ai/economics",
        source_run_id="economics-run",
        scraped_at="2026-07-19T00:00:00Z",
    )
    activity.to_parquet(activity_path, index=False)
    economics.to_parquet(economics_path, index=False)
    _pricing_history().to_parquet(pricing_path, index=False)
    _artificial_analysis_rows().to_parquet(models_path, index=False)
    return {
        "activity": activity_path,
        "economics": economics_path,
        "pricing": pricing_path,
        "models": models_path,
    }


def test_pipeline_builds_both_marts_and_preserves_last_valid_files_on_failure(tmp_path: Path) -> None:
    paths = _seed_pipeline_inputs(tmp_path)

    result = OpenRouterDerivedPipeline(tmp_path).build(today=date(2026, 7, 19))

    assert result["openrouter_usage_economics_daily"] > 0
    assert result["openrouter_workload_intensity_models"] > 0
    economics_path = tmp_path / "data/normalized/marts/openrouter_usage_economics_daily.parquet"
    models_path = tmp_path / "data/normalized/marts/openrouter_workload_intensity_models.parquet"
    assert list(pd.read_parquet(economics_path).columns) == _DAILY_MART_COLUMNS
    assert list(pd.read_parquet(models_path).columns) == _MODEL_MART_COLUMNS
    previous_economics = economics_path.read_bytes()
    previous_models = models_path.read_bytes()

    paths["activity"].unlink()

    with pytest.raises(FileNotFoundError):
        OpenRouterDerivedPipeline(tmp_path).build(today=date(2026, 7, 19))

    assert economics_path.read_bytes() == previous_economics
    assert models_path.read_bytes() == previous_models
    assert not list(economics_path.parent.glob("*.parquet.tmp"))


def test_pipeline_accepts_current_day_benchmark_when_economics_lag_one_day(tmp_path: Path) -> None:
    paths = _seed_pipeline_inputs(tmp_path)
    models = pd.read_parquet(paths["models"])
    models["as_of_date"] = "2026-07-19"
    models = models.drop_duplicates("model_id", keep="last")
    models.to_parquet(paths["models"], index=False)

    result = OpenRouterDerivedPipeline(tmp_path).build(today=date(2026, 7, 19))

    assert result["openrouter_usage_economics_daily"] > 0


@pytest.mark.parametrize(
    ("invalid_input", "error_type"),
    [
        ("missing_required_column", ValueError),
        ("duplicate_natural_key", ValueError),
        ("no_complete_activity", ValueError),
        ("no_artificial_analysis_snapshot", ValueError),
        ("all_output_values_missing", ValueError),
    ],
)
def test_pipeline_rejects_invalid_inputs_before_writing_marts(
    tmp_path: Path, invalid_input: str, error_type: type[Exception]
) -> None:
    paths = _seed_pipeline_inputs(tmp_path)
    activity = pd.read_parquet(paths["activity"])
    economics = pd.read_parquet(paths["economics"])
    models = pd.read_parquet(paths["models"])
    if invalid_input == "missing_required_column":
        activity = activity.drop(columns="request_count")
        activity.to_parquet(paths["activity"], index=False)
    elif invalid_input == "duplicate_natural_key":
        pd.concat([activity, activity.iloc[[0]]], ignore_index=True).to_parquet(
            paths["activity"], index=False
        )
    elif invalid_input == "no_complete_activity":
        activity["usage_date"] = "2026-07-19"
        activity.to_parquet(paths["activity"], index=False)
    elif invalid_input == "no_artificial_analysis_snapshot":
        models["as_of_date"] = "2026-07-20"
        models.to_parquet(paths["models"], index=False)
    else:
        activity[["total_tokens", "prompt_tokens", "completion_tokens"]] = pd.NA
        activity.to_parquet(paths["activity"], index=False)
        economics[["estimated_revenue", "pricing_prompt", "pricing_completion"]] = pd.NA
        economics.to_parquet(paths["economics"], index=False)

    with pytest.raises(error_type):
        OpenRouterDerivedPipeline(tmp_path).build(today=date(2026, 7, 19))

    mart_dir = tmp_path / "data/normalized/marts"
    assert not (mart_dir / "openrouter_usage_economics_daily.parquet").exists()
    assert not (mart_dir / "openrouter_workload_intensity_models.parquet").exists()


def test_pipeline_allows_guarded_sota_gaps_when_workload_and_market_outputs_are_valid(tmp_path: Path) -> None:
    paths = _seed_pipeline_inputs(tmp_path)
    models = pd.read_parquet(paths["models"])
    models.loc[~models["model_id"].isin(["claude", "sol-max"]), "release_date"] = "2026-07-20"
    models.to_parquet(paths["models"], index=False)

    result = OpenRouterDerivedPipeline(tmp_path).build(today=date(2026, 7, 19))
    daily = pd.read_parquet(
        tmp_path / "data/normalized/marts/openrouter_usage_economics_daily.parquet"
    )

    assert result["openrouter_usage_economics_daily"] == len(daily)
    assert daily.loc[
        daily["metric_id"].eq("total_tokens_per_request"), "value"
    ].notna().any()
    assert daily.loc[
        daily["metric_id"].eq("realized_market_average"), "value"
    ].notna().any()
    assert daily.loc[
        daily["metric_id"].eq("sota_median_list_price"), "value"
    ].isna().all()


def test_pipeline_builds_from_category_keyed_activity_with_null_entity_ids(tmp_path: Path) -> None:
    paths = _seed_pipeline_inputs(tmp_path)
    activity = pd.read_parquet(paths["activity"])
    activity["category_slug"] = ["chat", "programming"]
    activity["entity_id"] = pd.NA
    activity.to_parquet(paths["activity"], index=False)

    result = OpenRouterDerivedPipeline(tmp_path).build(today=date(2026, 7, 19))
    models = pd.read_parquet(
        tmp_path / "data/normalized/marts/openrouter_workload_intensity_models.parquet"
    )

    assert result["openrouter_workload_intensity_models"] == len(models)
    assert models["company_id"].isna().all()


def test_pipeline_rejects_duplicate_natural_dates_after_normalization(tmp_path: Path) -> None:
    paths = _seed_pipeline_inputs(tmp_path)
    activity = pd.read_parquet(paths["activity"])
    activity["category_slug"] = ["chat", "chat"]
    activity.loc[1, "usage_date"] = "2026-07-16T00:00:00Z"
    activity.loc[1, "model_permaslug"] = activity.loc[0, "model_permaslug"]
    activity.to_parquet(paths["activity"], index=False)

    with pytest.raises(ValueError, match="duplicate natural keys"):
        OpenRouterDerivedPipeline(tmp_path).build(today=date(2026, 7, 19))


def test_pipeline_rolls_back_both_marts_when_second_final_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_pipeline_inputs(tmp_path)
    pipeline = OpenRouterDerivedPipeline(tmp_path)
    pipeline.build(today=date(2026, 7, 19))
    mart_dir = tmp_path / "data/normalized/marts"
    economics_path = mart_dir / "openrouter_usage_economics_daily.parquet"
    models_path = mart_dir / "openrouter_workload_intensity_models.parquet"
    previous_economics = economics_path.read_bytes()
    previous_models = models_path.read_bytes()
    original_replace = Path.replace
    failed_temporary = models_path.with_suffix(".parquet.tmp")

    def fail_models_replace(source: Path, target: str | Path) -> Path:
        if source == failed_temporary:
            raise OSError("simulated replacement failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_models_replace)

    with pytest.raises(OSError, match="simulated replacement failure"):
        pipeline.build(today=date(2026, 7, 19))

    assert economics_path.read_bytes() == previous_economics
    assert models_path.read_bytes() == previous_models
    assert not list(mart_dir.glob("*.tmp"))
    assert not list(mart_dir.glob("*.backup"))


def test_cli_builds_marts_with_deterministic_row_count_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_pipeline_inputs(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "openrouter-derived-data",
            "--base-dir",
            str(tmp_path),
            "build",
            "--today",
            "2026-07-19",
        ],
    )

    main()

    assert capsys.readouterr().out.splitlines() == [
        "openrouter_usage_economics_daily: 26 rows",
        "openrouter_workload_intensity_models: 2 rows",
    ]


def test_project_registers_openrouter_derived_data_cli() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text())

    assert project["project"]["scripts"]["openrouter-derived-data"] == (
        "openrouter_derived_data.cli:main"
    )
