from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from openrouter_derived_data import (
    compute_price_metrics,
    compute_workload_intensity_daily,
    compute_workload_intensity_models,
)
from openrouter_derived_data.identity import (
    CapabilityEntry,
    CapabilityMap,
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
    entries = [
        CapabilityEntry("aa-a", "family-a", frozenset({"provider/a", "provider/a:free"})),
        CapabilityEntry(
            "aa-a-lower",
            "family-a",
            frozenset({"provider/a-lower-capability"}),
        ),
        CapabilityEntry("aa-b", "family-b", frozenset({"provider/b", "provider/b:fast"})),
        CapabilityEntry("aa-c", "family-c", frozenset({"provider/c"})),
        CapabilityEntry("aa-d", "family-d", frozenset({"provider/d"})),
        CapabilityEntry("aa-e", "family-e", frozenset({"provider/e"})),
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
