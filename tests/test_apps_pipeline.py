from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from openrouter_data.exceptions import ExtractionError
from openrouter_data.models import RunContext, Snapshot
from openrouter_data.pipeline import AppsPipeline
from openrouter_data.sources.apps import AppsSource


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "apps_payloads.json"


def _load_payloads() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _make_next_f_script(label: str, payload: list) -> str:
    encoded = json.dumps(f"{label}:{json.dumps(payload, separators=(',', ':'))}")
    return f"<script>self.__next_f.push([1,{encoded}])</script>"


def build_app_detail_fixture_html(
    *,
    metadata: dict | None = None,
    usage: dict | None = None,
    top_models: dict | None = None,
) -> str:
    payloads = _load_payloads()
    metadata = payloads["openclaw_metadata"] if metadata is None else metadata
    usage = payloads["openclaw_usage"] if usage is None else usage
    top_models = payloads["openclaw_top_models"] if top_models is None else top_models

    return (
        "<html><body>"
        f"{_make_next_f_script('50', ['$', '$L50', None, metadata])}"
        f"{_make_next_f_script('51', ['$', '$L51', None, usage])}"
        f"{_make_next_f_script('52', ['$', '$L52', None, top_models])}"
        "</body></html>"
    )


def build_hermes_detail_fixture_html(
    *,
    metadata: dict | None = None,
    usage: dict | None = None,
    top_models: dict | None = None,
) -> str:
    payloads = _load_payloads()
    metadata = payloads["hermes_metadata"] if metadata is None else metadata
    usage = payloads["hermes_usage"] if usage is None else usage
    top_models = payloads["hermes_top_models"] if top_models is None else top_models

    return (
        "<html><body>"
        f"{_make_next_f_script('60', ['$', '$L60', None, metadata])}"
        f"{_make_next_f_script('61', ['$', '$L61', None, usage])}"
        f"{_make_next_f_script('62', ['$', '$L62', None, top_models])}"
        "</body></html>"
    )


def build_apps_directory_fixture_html(
    *,
    ranking_map: dict | None = None,
    trending: list[dict] | None = None,
) -> str:
    payloads = _load_payloads()
    ranking_map = payloads["ranking_map"] if ranking_map is None else ranking_map
    trending = payloads["trending"] if trending is None else trending

    ranking_payload = ["$", "$L3e", None, {"rankingMap": ranking_map}]
    trending_payload = ["$", "$L32", None, {"trendingApps": trending}]
    return (
        "<html><body>"
        f"{_make_next_f_script('36', ranking_payload)}"
        f"{_make_next_f_script('37', trending_payload)}"
        "</body></html>"
    )


def make_snapshots(
    directory_html: str,
    app_html: str,
    hermes_html: str | None = None,
) -> list[Snapshot]:
    return [
        Snapshot(name="apps_directory", source_url="fixture://apps", body=directory_html),
        Snapshot(name="app_openclaw", source_url="fixture://apps?url=openclaw", body=app_html),
        Snapshot(
            name="app_hermes-agent",
            source_url="fixture://apps/hermes-agent",
            body=hermes_html or build_hermes_detail_fixture_html(),
        ),
    ]


def make_multi_app_snapshots(directory_html: str, app_snapshots: dict[str, str]) -> list[Snapshot]:
    snapshots = [Snapshot(name="apps_directory", source_url="fixture://apps", body=directory_html)]
    for slug, body in app_snapshots.items():
        snapshots.append(Snapshot(name=f"app_{slug}", source_url=f"fixture://apps/{slug}", body=body))
    return snapshots


def test_parse_fixture_snapshots_for_app_and_directory_datasets() -> None:
    source = AppsSource()
    context = RunContext(run_id="test-apps", scraped_at=pd.Timestamp("2026-04-05T01:10:00Z").to_pydatetime())

    extracted = source.extract(
        make_snapshots(build_apps_directory_fixture_html(), build_app_detail_fixture_html()),
        context,
    )

    assert set(extracted) == {
        "app_metadata_snapshots",
        "app_usage_daily",
        "app_top_models_daily_snapshot",
        "apps_global_ranking_snapshots",
        "apps_trending_snapshots",
    }
    assert len(extracted["app_metadata_snapshots"]) == 2
    assert len(extracted["app_usage_daily"]) == 12
    assert len(extracted["app_top_models_daily_snapshot"]) == 4
    assert len(extracted["apps_global_ranking_snapshots"]) == 6
    assert len(extracted["apps_trending_snapshots"]) == 2
    assert extracted["apps_global_ranking_snapshots"][0].period == "day"
    assert extracted["apps_trending_snapshots"][0].growth_percent == 20.0
    assert extracted["apps_trending_snapshots"][0].tokens == 5651018332581.0


def test_missing_required_payload_raises_clear_error() -> None:
    source = AppsSource()
    context = RunContext(run_id="broken-apps", scraped_at=pd.Timestamp("2026-04-05T01:10:00Z").to_pydatetime())
    broken_directory = build_apps_directory_fixture_html(trending=[])

    with pytest.raises(ExtractionError, match="trending"):
        source.extract(make_snapshots(broken_directory, build_app_detail_fixture_html()), context)


def test_repeated_runs_keep_metadata_and_usage_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = AppsPipeline(tmp_path)
    directory_html = build_apps_directory_fixture_html()
    app_html = build_app_detail_fixture_html()
    monkeypatch.setattr(pipeline.source, "fetch_snapshots", lambda: make_snapshots(directory_html, app_html))

    pipeline.run_initial_backfill()
    pipeline.run_daily_update()

    metadata = pd.read_csv(tmp_path / "data" / "normalized" / "openrouter" / "app_metadata_snapshots.csv")
    usage = pd.read_csv(tmp_path / "data" / "normalized" / "openrouter" / "app_usage_daily.csv")
    assert len(metadata) == 2
    assert usage[["app_id", "usage_date", "model_permaslug"]].duplicated().sum() == 0


def test_daily_update_appends_new_usage_day_and_preserves_older_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payloads = _load_payloads()
    initial_usage = dict(payloads["openclaw_usage"])
    initial_usage["data"] = payloads["openclaw_usage"]["data"][:1]
    updated_usage = dict(payloads["openclaw_usage"])
    updated_usage["data"] = payloads["openclaw_usage"]["data"] + [
        {
            "x": "2026-03-08 00:00:00",
            "ys": {
                "stepfun/step-3.5-flash": 80423763540,
                "moonshotai/kimi-k2.5-0127": 21496321256,
                "Others": 62090175269,
            },
        }
    ]

    pipeline = AppsPipeline(tmp_path)
    monkeypatch.setattr(
        pipeline.source,
        "fetch_snapshots",
        lambda: make_snapshots(
            build_apps_directory_fixture_html(),
            build_app_detail_fixture_html(usage=initial_usage),
        ),
    )
    pipeline.run_initial_backfill()

    monkeypatch.setattr(
        pipeline.source,
        "fetch_snapshots",
        lambda: make_snapshots(
            build_apps_directory_fixture_html(),
            build_app_detail_fixture_html(usage=updated_usage),
        ),
    )
    pipeline.run_daily_update()

    usage = pd.read_csv(tmp_path / "data" / "normalized" / "openrouter" / "app_usage_daily.csv")
    assert sorted(usage["usage_date"].unique().tolist()) == ["2026-03-06", "2026-03-07", "2026-03-08"]


def test_daily_update_with_no_new_usage_reports_no_new_rows_and_skips_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline = AppsPipeline(tmp_path)
    directory_html = build_apps_directory_fixture_html()
    app_html = build_app_detail_fixture_html()
    monkeypatch.setattr(pipeline.source, "fetch_snapshots", lambda: make_snapshots(directory_html, app_html))

    pipeline.run_initial_backfill()
    usage_path = tmp_path / "data" / "normalized" / "openrouter" / "app_usage_daily.csv"
    rows_after_backfill = len(pd.read_csv(usage_path))

    result = pipeline.run_daily_update()

    manifest = json.loads((result.raw_run_dir / "manifest.json").read_text(encoding="utf-8"))
    usage_entry = next(item for item in manifest["datasets"] if item["dataset_id"] == "app_usage_daily")
    assert usage_entry["status"] == "no_new_rows"
    assert usage_entry["rows"] == 0
    assert result.datasets_written["app_usage_daily"] == rows_after_backfill
    assert len(pd.read_csv(usage_path)) == rows_after_backfill


def test_top_models_snapshots_append_across_multiple_scrape_dates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = AppsPipeline(tmp_path)
    first_top_models = {
        "appName": "OpenClaw",
        "appModelAnalytics": [
            {
                "date": "2026-04-05",
                "model_permaslug": "stepfun/step-3.5-flash",
                "total_tokens": 3571671369928,
            }
        ],
    }
    second_top_models = {
        "appName": "OpenClaw",
        "appModelAnalytics": [
            {
                "date": "2026-04-06",
                "model_permaslug": "stepfun/step-3.5-flash",
                "total_tokens": 3671671369928,
            }
        ],
    }
    monkeypatch.setattr(
        pipeline.source,
        "fetch_snapshots",
        lambda: make_snapshots(
            build_apps_directory_fixture_html(),
            build_app_detail_fixture_html(top_models=first_top_models),
        ),
    )
    pipeline.run_initial_backfill()
    monkeypatch.setattr(
        pipeline.source,
        "fetch_snapshots",
        lambda: make_snapshots(
            build_apps_directory_fixture_html(),
            build_app_detail_fixture_html(top_models=second_top_models),
        ),
    )
    pipeline.run_daily_update()

    top_models = pd.read_csv(tmp_path / "data" / "normalized" / "openrouter" / "app_top_models_daily_snapshot.csv")
    assert sorted(top_models["snapshot_date"].unique().tolist()) == ["2026-04-05", "2026-04-06"]


def test_global_ranking_snapshots_store_all_three_periods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = AppsPipeline(tmp_path)
    monkeypatch.setattr(
        pipeline.source,
        "fetch_snapshots",
        lambda: make_snapshots(build_apps_directory_fixture_html(), build_app_detail_fixture_html()),
    )
    pipeline.run_initial_backfill()

    ranking = pd.read_csv(tmp_path / "data" / "normalized" / "openrouter" / "apps_global_ranking_snapshots.csv")
    assert sorted(ranking["period"].unique().tolist()) == ["day", "month", "week"]


def test_csv_and_parquet_outputs_stay_schema_consistent_for_app_datasets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = AppsPipeline(tmp_path)
    monkeypatch.setattr(
        pipeline.source,
        "fetch_snapshots",
        lambda: make_snapshots(build_apps_directory_fixture_html(), build_app_detail_fixture_html()),
    )
    pipeline.run_initial_backfill()

    csv_df = pd.read_csv(tmp_path / "data" / "normalized" / "openrouter" / "apps_trending_snapshots.csv")
    parquet_df = pd.read_parquet(tmp_path / "data" / "normalized" / "openrouter" / "apps_trending_snapshots.parquet")
    assert list(csv_df.columns) == list(parquet_df.columns)


def test_multi_app_monitored_extraction_returns_openclaw_and_hermes() -> None:
    source = AppsSource()
    context = RunContext(run_id="test-multi-apps", scraped_at=pd.Timestamp("2026-04-05T01:10:00Z").to_pydatetime())

    extracted = source.extract(
        make_multi_app_snapshots(
            build_apps_directory_fixture_html(),
            {
                "openclaw": build_app_detail_fixture_html(),
                "hermes-agent": build_hermes_detail_fixture_html(),
            },
        ),
        context,
    )

    metadata_apps = {record.app_name for record in extracted["app_metadata_snapshots"]}
    usage_apps = {record.app_name for record in extracted["app_usage_daily"]}
    top_model_apps = {record.app_name for record in extracted["app_top_models_daily_snapshot"]}

    assert {"OpenClaw", "Hermes Agent"}.issubset(metadata_apps)
    assert {"OpenClaw", "Hermes Agent"}.issubset(usage_apps)
    assert {"OpenClaw", "Hermes Agent"}.issubset(top_model_apps)


def test_live_card_text_parsers_handle_current_apps_page_format() -> None:
    source = AppsSource()

    ranking_row = source._parse_live_marketplace_row(
        {
            "href": "/apps/hermes-agent",
            "text": (
                "1.\nHermes Agent\n\n"
                "Hermes Agent is an open-source, self-improving AI agent.\n\n"
                "Personal Agents\nCLI Agents\n644Btokens"
            ),
        }
    )
    trending_row = source._parse_live_trending_card(
        {
            "href": "/apps/codex",
            "text": "Codex\n54B\n+421%",
        }
    )

    assert ranking_row["app_id"] == "/apps/hermes-agent"
    assert ranking_row["rank"] == 1
    assert ranking_row["app"]["title"] == "Hermes Agent"
    assert ranking_row["app"]["description"] == "Hermes Agent is an open-source, self-improving AI agent."
    assert ranking_row["app"]["categories"] == ["Personal Agents", "CLI Agents"]
    assert ranking_row["total_tokens"] == 644_000_000_000.0

    assert trending_row["growthPercent"] == 421.0
    assert trending_row["appAnalytics"]["app_id"] == "/apps/codex"
    assert trending_row["appAnalytics"]["app"]["title"] == "Codex"
    assert trending_row["appAnalytics"]["total_tokens"] == 54_000_000_000.0


def test_click_visible_option_ignores_hidden_duplicate_options() -> None:
    class FakeOption:
        def __init__(self, *, visible: bool) -> None:
            self.visible = visible
            self.clicked = False

        def is_visible(self) -> bool:
            return self.visible

        def click(self, timeout: int) -> None:
            self.clicked = True

    class FakeOptions:
        def __init__(self, options: list[FakeOption]) -> None:
            self.options = options

        def count(self) -> int:
            return len(self.options)

        def nth(self, index: int) -> FakeOption:
            return self.options[index]

    class FakePage:
        def __init__(self, options: list[FakeOption]) -> None:
            self.options = FakeOptions(options)
            self.locator_calls: list[tuple[str, str | None]] = []

        def locator(self, selector: str, *, has_text: str | None = None) -> FakeOptions:
            self.locator_calls.append((selector, has_text))
            return self.options

    hidden = FakeOption(visible=False)
    visible = FakeOption(visible=True)

    AppsSource._click_visible_option(FakePage([hidden, visible]), "This Month")

    assert not hidden.clicked
    assert visible.clicked


def test_extract_uses_playwright_directory_fallback_when_html_payload_is_missing() -> None:
    source = AppsSource()
    context = RunContext(run_id="live-fallback", scraped_at=pd.Timestamp("2026-04-05T01:10:00Z").to_pydatetime())
    payloads = _load_payloads()

    source._extract_directory_payload_with_playwright = lambda: (payloads["ranking_map"], payloads["trending"])  # type: ignore[method-assign]

    extracted = source.extract(
        make_snapshots("<html><body><div>No ranking payload here</div></body></html>", build_app_detail_fixture_html()),
        context,
    )

    assert len(extracted["apps_global_ranking_snapshots"]) == 6
    assert len(extracted["apps_trending_snapshots"]) == 2
