from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from opencode_data.extract import (
    extract_benchmarks,
    extract_country_usage,
    extract_leaderboard,
    extract_market_share,
    extract_model_catalog,
    extract_model_deepdive,
    extract_usage_daily,
    extract_users_daily,
)
from opencode_data.source import parse_solid_hydration
from opencode_data.storage import save_normalized_dataset, save_raw_snapshot


def test_opencode_extraction():
    scraped_at = "2026-08-04T12:00:00+00:00"

    mock_stats_home = {
        "updatedAt": "2026-08-04T11:52:17.000Z",
        "market": {
            "3M": [
                {
                    "date": "AUG 4",
                    "total": 3.5,
                    "authors": [
                        {"author": "DeepSeek", "share": 90.0, "tokens": 3.15},
                        {"author": "OpenAI", "share": 2.5, "tokens": 0.088},
                    ],
                }
            ]
        },
        "usage": {
            "All Users": {
                "1D": [
                    {
                        "date": "AUG 4",
                        "segments": [{"model": "deepseek-v4-pro", "value": 18607}],
                    }
                ]
            }
        },
        "users": {
            "All Users": {
                "1D": [
                    {
                        "date": "AUG 4",
                        "segments": [{"model": "deepseek-v4-pro", "value": 18607}],
                    }
                ]
            }
        },
        "leaderboard": {
            "All Users": {
                "1D": [
                    {
                        "model": "deepseek-v4-pro",
                        "provider": "deepseek",
                        "author": "DeepSeek",
                        "tokens": 20233,
                        "change": 0,
                        "rank": 1,
                    }
                ]
            }
        },
        "country": {
            "1D": [
                {
                    "country": "CN",
                    "continent": "AS",
                    "tokens": 1.08,
                    "share": 31.1,
                    "rank": 1,
                }
            ]
        },
    }

    mock_catalog = {
        "models": [
            {
                "id": "deepseek/deepseek-v4-pro",
                "lab": "deepseek",
                "slug": "deepseek-v4-pro",
                "name": "DeepSeek V4 Pro",
                "limit": {"context": 128000, "output": 8192},
                "cost": {"input": 0.14, "output": 0.28, "cacheRead": 0.014},
                "openWeights": False,
                "benchmarks": [{"name": "SWE-Bench Verified", "score": 92.5}],
            }
        ]
    }

    market_rows = extract_market_share(mock_stats_home, scraped_at)
    assert len(market_rows) == 2
    assert market_rows[0]["author"] == "DeepSeek"

    usage_rows = extract_usage_daily(mock_stats_home, scraped_at)
    assert len(usage_rows) == 1
    assert usage_rows[0]["model_slug"] == "deepseek-v4-pro"

    users_rows = extract_users_daily(mock_stats_home, scraped_at)
    assert len(users_rows) == 1

    lb_rows = extract_leaderboard(mock_stats_home, scraped_at)
    assert len(lb_rows) == 1
    assert lb_rows[0]["provider"] == "deepseek"

    country_rows = extract_country_usage(mock_stats_home, scraped_at)
    assert len(country_rows) == 1
    assert country_rows[0]["country_code"] == "CN"

    catalog_rows = extract_model_catalog(mock_catalog, scraped_at)
    assert len(catalog_rows) == 1
    assert catalog_rows[0]["slug"] == "deepseek-v4-pro"

    bench_rows = extract_benchmarks(mock_catalog, scraped_at)
    assert len(bench_rows) == 1
    assert bench_rows[0]["benchmark_name"] == "SWE-Bench Verified"


def test_opencode_storage():
    scraped_at = "2026-08-04T12:00:00+00:00"
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)

        # Save raw snapshot
        raw_file = save_raw_snapshot(base_dir, "test_snap", {"key": "val"}, scraped_at)
        assert raw_file.exists()

        # Save normalized dataset
        rows = [{"a": 1, "b": "hello"}]
        p_file, c_file = save_normalized_dataset(base_dir, "test_norm", rows)
        assert c_file.exists()


def test_save_normalized_dataset_preserves_prior_days_on_upsert():
    """A second day's scrape must not wipe out the first day's rows.

    Regression test for the original blind-overwrite bug: save_normalized_dataset
    used to df.to_csv() only the current run's rows, discarding all history.
    """
    import pandas as pd

    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)

        day1_rows = [
            {
                "snapshot_date": "2026-08-03",
                "user_tier": "All Users",
                "timeframe": "1D",
                "rank": 1,
                "model_slug": "deepseek-v4-pro",
                "provider": "deepseek",
                "author": "DeepSeek",
                "tokens": 100,
                "rank_change": 0,
                "scraped_at": "2026-08-03T04:15:00+00:00",
            }
        ]
        save_normalized_dataset(base_dir, "opencode_leaderboard", day1_rows)

        day2_rows = [
            {
                "snapshot_date": "2026-08-04",
                "user_tier": "All Users",
                "timeframe": "1D",
                "rank": 1,
                "model_slug": "deepseek-v4-pro",
                "provider": "deepseek",
                "author": "DeepSeek",
                "tokens": 150,
                "rank_change": 0,
                "scraped_at": "2026-08-04T04:15:00+00:00",
            }
        ]
        save_normalized_dataset(base_dir, "opencode_leaderboard", day2_rows)

        stored = pd.read_csv(base_dir / "data" / "normalized" / "opencode" / "opencode_leaderboard.csv")
        assert sorted(stored["snapshot_date"].tolist()) == ["2026-08-03", "2026-08-04"]

        # Re-running the *same* day with an updated value should refresh that
        # row in place, not append a duplicate.
        day1_rerun_rows = [{**day1_rows[0], "tokens": 999}]
        save_normalized_dataset(base_dir, "opencode_leaderboard", day1_rerun_rows)
        stored = pd.read_csv(base_dir / "data" / "normalized" / "opencode" / "opencode_leaderboard.csv")
        assert len(stored) == 2
        day1_row = stored[stored["snapshot_date"] == "2026-08-03"].iloc[0]
        assert day1_row["tokens"] == 999


def test_save_normalized_dataset_empty_rows_keeps_existing_history():
    """An empty scrape result (e.g. no deepdives fetched) must not erase history."""
    import pandas as pd

    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        rows = [{"snapshot_date": "2026-08-03", "model_slug": "deepseek-v4-pro"}]
        save_normalized_dataset(base_dir, "opencode_model_deepdives", rows)

        save_normalized_dataset(base_dir, "opencode_model_deepdives", [])

        stored = pd.read_csv(base_dir / "data" / "normalized" / "opencode" / "opencode_model_deepdives.csv")
        assert len(stored) == 1
        assert stored.iloc[0]["model_slug"] == "deepseek-v4-pro"


_HYDRATION_TEST_HTML = """
<html><body>
<script>var preference = "system";</script>
<script>window._$HY_setup = 1;</script>
<script>
self.$R = self.$R || [];
_$HY_data = self.$R[0] = { p: { v: { hello: "world" } } };
</script>
</body></html>
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="requires a node binary on PATH")
def test_parse_solid_hydration_selects_scripts_by_content_marker():
    extracted = parse_solid_hydration(_HYDRATION_TEST_HTML)
    assert extracted == [{"idx": 0, "value": {"hello": "world"}}]


def test_parse_solid_hydration_raises_clearly_when_page_structure_changes():
    html_without_hydration_scripts = "<html><body><script>var x = 1;</script></body></html>"
    with pytest.raises(ValueError, match="hydration-related script tags"):
        parse_solid_hydration(html_without_hydration_scripts)
