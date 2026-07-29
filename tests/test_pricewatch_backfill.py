import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture()
def backfill_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "backfill_consumer_council_pricewatch.py"
    spec = importlib.util.spec_from_file_location("pricewatch_backfill", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_archive_versions_choose_latest_timestamp_per_date(backfill_module, monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "timestamps": [
                    "20200530090000",
                    "20200530170000",
                    "20200531120000",
                    "bad-timestamp",
                ]
            }

    monkeypatch.setattr(backfill_module.requests, "get", lambda *args, **kwargs: Response())
    dates = backfill_module.get_daily_timestamps(now=datetime(2026, 7, 29, tzinfo=timezone.utc))
    assert dates == {"2020-05-30": "20200530170000", "2020-05-31": "20200531120000"}


def test_pricewatch_parser_rejects_non_contract_csv(backfill_module, tmp_path):
    raw_path = tmp_path / "bad.csv"
    raw_path.write_text("Category 1,Price\nFood,10\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        backfill_module.parse_raw_csv(raw_path, "2020-05-30")


def test_pricewatch_manifest_marks_missing_parses_incomplete(backfill_module):
    manifest = backfill_module._build_manifest(
        {"2020-05-30": "20200530120000", "2020-05-31": "20200531120000"},
        {"2020-05-30": "cached", "2020-05-31": "downloaded"},
        {"2020-05-30"},
        {"2020-05-31": "invalid header"},
        [],
    )
    assert manifest["status"] == "incomplete"


def test_pricewatch_manifest_marks_full_parse_complete(backfill_module):
    dates = {"2020-05-30": "20200530120000"}
    manifest = backfill_module._build_manifest(
        dates,
        {"2020-05-30": "cached"},
        set(dates),
        {},
        [{"path": "2020-05/pricewatch_2020-05.parquet"}],
    )
    assert manifest["status"] == "complete"
