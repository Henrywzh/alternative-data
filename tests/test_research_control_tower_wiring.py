"""Focused offline tests for the Control Tower producer and CLI wiring."""

from __future__ import annotations

from pathlib import Path
import shutil
from types import SimpleNamespace

import pandas as pd

from scripts import build_research_control_tower as wiring
from src.research_control_tower import cli
from src.research_control_tower.build import (
    LEGACY_GENERATION_ARTIFACT_NAMES,
    LocalInput,
    _validated_current_lineage,
)


def _input(source_id: str, schema: str) -> LocalInput:
    return LocalInput(
        source_id=source_id,
        path=f"/tmp/{source_id}.parquet",
        format="parquet",
        expected_schema=schema,
    )


def test_collector_catalog_has_unique_ids_and_exact_new_contracts():
    rows = (*wiring.REPO_SOURCES, *wiring.COLLECTOR_SOURCES)
    source_ids = [row[1] for row in rows]

    assert len(source_ids) == len(set(source_ids))
    by_id = {row[1]: row for row in rows}

    assert by_id["corporate_actions"][0:4] == (
        "corporate_actions",
        "corporate_actions",
        "data/normalized/research_control_tower/corporate_actions_v1.parquet",
        "corporate_actions_v1",
    )
    assert by_id["corporate_actions_state"][3] == "source_state_v1"
    assert by_id["tencent_earnings_actuals"][0:4] == (
        "earnings",
        "tencent_earnings_actuals",
        "data/normalized/research_control_tower/tencent_earnings_actuals_v1.parquet",
        "earnings_actuals_v1",
    )
    assert by_id["tencent_earnings_actuals_state"][3] == "source_state_v1"
    assert by_id["valuation_snapshots"][0:4] == (
        "valuation",
        "valuation_snapshots",
        "data/normalized/research_control_tower/valuation_snapshots.parquet",
        "valuation_snapshots_v2",
    )
    assert by_id["internal_estimates"][0:4] == (
        "valuation",
        "internal_estimates",
        "data/normalized/research_control_tower/internal_estimates.parquet",
        "internal_estimates_v1",
    )
    assert by_id["price_bars"][0] == "price_bar"

    assert "--max-rows-per-query" not in wiring.COLLECTOR_COMMANDS["corporate_actions"]
    assert "research_control_tower_tencent_financials.py" in wiring.COLLECTOR_COMMANDS[
        "tencent_earnings_actuals"
    ]
    assert "--quotes" in wiring.COLLECTOR_COMMANDS["valuation_snapshots"]
    assert "--consensus-health" in wiring.COLLECTOR_COMMANDS["valuation_snapshots"]
    assert "--earnings-actuals" in wiring.COLLECTOR_COMMANDS["valuation_snapshots"]


def test_repository_build_script_routes_new_input_kinds(monkeypatch, tmp_path):
    by_kind = {
        "macro": [],
        "news": [],
        "filing": [],
        "official_filing": [],
        "earnings": [_input("generic_earnings", "earnings_actuals_v1")],
        "market": [_input("quotes", "quote_snapshots_v1")],
        "price_bar": [_input("bars", "price_bars_v1")],
        "corporate_actions": [_input("actions", "corporate_actions_v1")],
        "valuation": [
            _input("valuations", "valuation_snapshots_v2"),
            _input("estimates", "internal_estimates_v1"),
        ],
    }
    captured: dict[str, object] = {}

    def fake_build(config):
        captured["config"] = config
        return SimpleNamespace(status="success", artifacts={})

    monkeypatch.setattr(wiring, "_collect_inputs", lambda verbose=True: (by_kind, []))
    monkeypatch.setattr(wiring, "build_control_tower_marts", fake_build)

    result = wiring.main(
        [
            "--output-dir",
            str(tmp_path / "output"),
            "--as-of-utc",
            "2026-08-22T00:00:00Z",
            "--build-id",
            "wiring-test",
        ]
    )

    assert result == 0
    config = captured["config"]
    assert [item.source_id for item in config.earnings_inputs] == ["generic_earnings"]
    assert [item.source_id for item in config.quote_inputs] == ["quotes"]
    assert [item.source_id for item in config.price_bar_inputs] == ["bars"]
    assert [item.source_id for item in config.corporate_actions_inputs] == ["actions"]
    assert [item.source_id for item in config.valuation_inputs] == [
        "valuations",
        "estimates",
    ]


def test_cli_wires_repeatable_price_bar_corporate_action_and_valuation_inputs(
    monkeypatch, tmp_path
):
    captured: dict[str, object] = {}

    def fake_build(config):
        captured["config"] = config
        return SimpleNamespace(status="success")

    monkeypatch.setattr(cli, "build_control_tower_marts", fake_build)
    result = cli.main(
        [
            "build",
            "--registry-root",
            str(tmp_path / "registry"),
            "--event-root",
            str(tmp_path / "events"),
            "--output-dir",
            str(tmp_path / "output"),
            "--as-of-utc",
            "2026-08-22T00:00:00Z",
            "--build-id",
            "cli-wiring-test",
            "--earnings-input",
            "generic|/tmp/generic.parquet|parquet|earnings_actuals_v1",
            "--quote-input",
            "quote|/tmp/quote.parquet|parquet|quote_snapshots_v1",
            "--price-bar-input",
            "bars-a|/tmp/bars-a.parquet|parquet|price_bars_v1",
            "--price-bar-input",
            "bars-b|/tmp/bars-b.parquet|parquet|price_bars_v1",
            "--corporate-actions-input",
            "actions|/tmp/actions.parquet|parquet|corporate_actions_v1",
            "--valuation-input",
            "valuations|/tmp/valuations.parquet|parquet|valuation_snapshots_v2",
            "--valuation-input",
            "estimates|/tmp/estimates.parquet|parquet|internal_estimates_v1",
        ]
    )

    assert result == 0
    config = captured["config"]
    assert [item.source_id for item in config.earnings_inputs] == ["generic"]
    assert [item.source_id for item in config.quote_inputs] == ["quote"]
    assert [item.source_id for item in config.price_bar_inputs] == [
        "bars-a",
        "bars-b",
    ]
    assert [item.source_id for item in config.corporate_actions_inputs] == ["actions"]
    assert [item.source_id for item in config.valuation_inputs] == [
        "valuations",
        "estimates",
    ]
    assert pd.Timestamp(config.as_of_utc) == pd.Timestamp("2026-08-22T00:00:00Z")


def test_publisher_accepts_the_known_legacy_current_for_lineage(tmp_path):
    publication = Path(__file__).resolve().parents[1] / "apps" / "research-control-tower" / ".generated"
    current_target = "generations/local-sources-20260819T003448Z-b844a17b439cfae6"
    source_generation = publication / current_target
    legacy_root = tmp_path / "publication"
    legacy_generation = legacy_root / current_target
    legacy_generation.parent.mkdir(parents=True)
    shutil.copytree(source_generation, legacy_generation)
    (legacy_root / "CURRENT").write_text(current_target + "\n", encoding="utf-8")

    assert set(path.name for path in source_generation.iterdir()) == set(
        LEGACY_GENERATION_ARTIFACT_NAMES
    )
    built_at, generation_id = _validated_current_lineage(
        legacy_root,
        as_of_utc=pd.Timestamp("2026-08-22T00:05:00Z"),
    )
    assert built_at == "2026-08-19T00:34:48.375609Z"
    assert generation_id == Path(current_target).name
