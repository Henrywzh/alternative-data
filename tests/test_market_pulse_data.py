from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_pulse_data import build_market_pulse, build_overview_signal_series


def _write(base: Path, domain: str, dataset: str, rows: list[dict]) -> None:
    root = base / "data" / "normalized" / domain
    root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(root / f"{dataset}.parquet", index=False)


def test_market_pulse_builds_compact_daily_rows_and_latest_cross_signals(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "openrouter_official",
        "official_model_rankings_daily",
        [
            {"usage_date": "2026-07-16", "model_permaslug": "a/model", "total_tokens": 70, "is_other": False, "source_url": "official://rankings", "as_of": "2026-07-18"},
            {"usage_date": "2026-07-16", "model_permaslug": "other", "total_tokens": 30, "is_other": True, "source_url": "official://rankings", "as_of": "2026-07-18"},
            {"usage_date": "2026-07-17", "model_permaslug": "b/model", "total_tokens": 160, "is_other": False, "source_url": "official://rankings", "as_of": "2026-07-18"},
            {"usage_date": "2026-07-17", "model_permaslug": "other", "total_tokens": 40, "is_other": True, "source_url": "official://rankings", "as_of": "2026-07-18"},
        ],
    )
    _write(
        tmp_path,
        "compute_availability",
        "raw_openrouter_models_current",
        [
            {"model_id": "a/model", "created_at": 1784246400, "snapshot_ts": "2026-07-18T08:00:00Z", "source_url": "official://models"},
            {"model_id": "b/model", "created_at": 1781654400, "snapshot_ts": "2026-07-18T08:00:00Z", "source_url": "official://models"},
        ],
    )
    _write(
        tmp_path,
        "ramp",
        "ramp_ai_adoption_overall",
        [{"date_month": "2026-06-01", "adoption_rate_pct": 55.0, "mom_change_pp": 1.0, "yoy_change_pp": 12.0, "source_url": "ramp://ai"}],
    )

    result = build_market_pulse(
        tmp_path,
        run_id="run-1",
        scraped_at="2026-07-18T12:00:00Z",
    )

    assert len(result) == 2
    latest = result.iloc[-1]
    assert latest["openrouter_total_tokens"] == 200
    assert latest["openrouter_top_model"] == "b/model"
    assert latest["openrouter_other_share_pct"] == 20.0
    assert latest["catalog_model_count"] == 2
    assert latest["ramp_ai_adoption_pct"] == 55.0
    assert (tmp_path / "data" / "normalized" / "overview" / "market_pulse_daily.parquet").exists()


def test_market_pulse_preserves_historical_cross_signals_on_refresh(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "openrouter_official",
        "official_model_rankings_daily",
        [{"usage_date": "2026-07-17", "model_permaslug": "a/model", "total_tokens": 100, "is_other": False, "source_url": "official://rankings", "as_of": "2026-07-18"}],
    )
    first = build_market_pulse(tmp_path, run_id="run-1", scraped_at="2026-07-18T12:00:00Z")
    first.loc[0, "ramp_ai_adoption_pct"] = 42.0
    first.to_parquet(tmp_path / "data" / "normalized" / "overview" / "market_pulse_daily.parquet", index=False)

    _write(
        tmp_path,
        "openrouter_official",
        "official_model_rankings_daily",
        [
            {"usage_date": "2026-07-17", "model_permaslug": "a/model", "total_tokens": 110, "is_other": False, "source_url": "official://rankings", "as_of": "2026-07-19"},
            {"usage_date": "2026-07-18", "model_permaslug": "b/model", "total_tokens": 120, "is_other": False, "source_url": "official://rankings", "as_of": "2026-07-19"},
        ],
    )
    refreshed = build_market_pulse(tmp_path, run_id="run-2", scraped_at="2026-07-19T12:00:00Z")

    old = refreshed[refreshed["pulse_date"] == "2026-07-17"].iloc[0]
    assert old["openrouter_total_tokens"] == 110
    assert old["ramp_ai_adoption_pct"] == 42.0


def test_overview_signal_series_builds_compact_cross_dashboard_histories(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "openrouter_official",
        "official_model_rankings_daily",
        [
            {"usage_date": "2026-07-17", "model_permaslug": "a/model", "total_tokens": 80, "is_other": False, "source_url": "official://rankings"},
            {"usage_date": "2026-07-17", "model_permaslug": "other", "total_tokens": 20, "is_other": True, "source_url": "official://rankings"},
        ],
    )
    _write(
        tmp_path,
        "semiconductor_memory",
        "fred_semiconductor_ppi_monthly",
        [
            {"month": "2026-05", "fred_ppi_value": 148.0, "fred_ppi_3m_trend": 147.0, "source_url": "fred://ppi"},
            {"month": "2026-06", "fred_ppi_value": 149.0, "fred_ppi_3m_trend": 148.0, "source_url": "fred://ppi"},
        ],
    )
    _write(
        tmp_path,
        "ramp",
        "ramp_ai_adoption_overall",
        [
            {"date_month": "2026-05-01", "adoption_rate_pct": 54.0, "source_url": "ramp://adoption"},
            {"date_month": "2026-06-01", "adoption_rate_pct": 55.0, "source_url": "ramp://adoption"},
        ],
    )
    _write(
        tmp_path,
        "provider_incidents",
        "provider_incidents",
        [
            {"provider_id": "openai", "source_incident_id": "one", "started_at": "2026-06-10T00:00:00Z", "published_at": None, "source_url": "status://openai"},
            {"provider_id": "anthropic", "source_incident_id": "two", "started_at": None, "published_at": "2026-07-10T00:00:00Z", "source_url": "status://anthropic"},
        ],
    )
    _write(
        tmp_path,
        "artificial_analysis",
        "artificial_analysis_models_daily",
        [
            {
                "model_id": "us-one",
                "model_name": "US One",
                "creator_name": "OpenAI",
                "creator_slug": "openai",
                "creator_country": None,
                "release_date": "2026-01-01",
                "intelligence_index": 50.0,
                "source_url": "aa://models",
            },
            {
                "model_id": "cn-one",
                "model_name": "CN One",
                "creator_name": "DeepSeek",
                "creator_slug": "deepseek",
                "creator_country": None,
                "release_date": "2026-02-01",
                "intelligence_index": 48.0,
                "source_url": "aa://models",
            },
        ],
    )
    _write(
        tmp_path,
        "openrouter",
        "provider_daily_activity",
        [
            {"usage_date": "2026-01-16", "entity_id": "openai", "entity_name": "OpenAI", "model_permaslug": "openai/test", "total_tokens": 100, "prompt_tokens": 80, "completion_tokens": 20, "reasoning_tokens": 0},
            {"usage_date": "2026-04-15", "entity_id": "openai", "entity_name": "OpenAI", "model_permaslug": "openai/test", "total_tokens": 200, "prompt_tokens": 160, "completion_tokens": 40, "reasoning_tokens": 0},
        ],
    )
    _write(
        tmp_path,
        "compute_availability",
        "raw_openrouter_models",
        [
            {"model_id": "openai/test", "canonical_slug": "openai/test", "provider_prefix": "openai", "snapshot_ts": "2026-04-15T22:53:52Z", "pricing_prompt": 0.000001, "pricing_completion": 0.000002},
        ],
    )

    result = build_overview_signal_series(
        tmp_path,
        run_id="run-overview",
        scraped_at="2026-07-18T12:00:00Z",
    )

    assert {
        "openrouter_full_market_tokens",
        "ai_demand_ppi",
        "ai_demand_ppi_3m_trend",
        "ramp_ai_adoption",
        "provider_incidents",
        "frontier_intelligence_us",
        "frontier_intelligence_china",
    }.issubset(set(result["signal_id"]))
    official = result[result["signal_id"] == "openrouter_full_market_tokens"].iloc[-1]
    assert official["value"] == 100
    revenue = result[result["signal_id"] == "openrouter_estimated_revenue"].sort_values("signal_date")
    assert revenue["value"].tolist() == pytest.approx([0.00012, 0.00024])
    assert revenue["detail_label"].tolist() == ["backcast_earliest_pricing", "as_of_pricing"]
    current_incidents = result[
        (result["signal_id"] == "provider_incidents") & (result["signal_date"] == "2026-07-01")
    ].iloc[0]
    assert bool(current_incidents["is_complete"]) is False
    assert (tmp_path / "data" / "normalized" / "overview" / "overview_signal_series.parquet").exists()
