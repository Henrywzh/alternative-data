"""Resuming the ranged institutional lanes instead of refetching from 2019.

The backfill defaults are right for a one-shot backfill and wrong for a
schedule: --hkex-start 2019-01-01 is ~1,750 trading days of fetches per run and
--eia-start 2019-01-01T00 re-merges 2,800 partitions. Without a resume path the
lanes could not be scheduled at all, which is why they sat unrefreshed.
"""

from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from eia_energy_data.models import EiaGridHourlyObservation
from eia_energy_data.storage import EiaEnergyStorage
from hkex_market_flow_data.storage import HkexMarketFlowStorage


REPO_ROOT = Path(__file__).resolve().parents[1]


def _runner():
    spec = importlib.util.spec_from_file_location(
        "backfill_free_institutional_data_under_test",
        REPO_ROOT / "scripts" / "backfill_free_institutional_data.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = _runner()


def _store_eia_hours(base: Path, days: list[str]) -> None:
    storage = EiaEnergyStorage(base)
    storage.upsert_grid_hourly(
        [
            EiaGridHourlyObservation(
                timestamp_utc=f"{day}T{hour:02d}",
                respondent="CISO",
                fuel_type="NG",
                generation_mwh=1.0,
                fetched_at="2026-09-12T00:00:00Z",
            )
            for day in days
            for hour in (0, 1)
        ]
    )


def test_eia_resumes_behind_the_newest_stored_day(tmp_path: Path) -> None:
    _store_eia_hours(tmp_path, ["2026-09-08", "2026-09-09", "2026-09-10"])

    start = RUNNER.resume_start_eia(tmp_path, lookback_days=3)

    # Behind the newest day, not after it: EIA revises recent hours, and a
    # start at the next hour would make any missed publication a permanent hole.
    assert start == "2026-09-07T00"


def test_eia_falls_back_to_the_backfill_origin_when_nothing_is_stored(tmp_path: Path) -> None:
    assert RUNNER.resume_start_eia(tmp_path) == RUNNER.EIA_BACKFILL_START


def test_eia_resume_does_not_read_the_rows(tmp_path: Path, monkeypatch) -> None:
    # 2.5M rows across 2,800 partitions in production: the newest day is in the
    # last filename, and paying a full read to find it would make the resume
    # cost what it was meant to save.
    _store_eia_hours(tmp_path, ["2026-09-10"])
    monkeypatch.setattr(
        EiaEnergyStorage,
        "load_grid_hourly",
        lambda self: pytest.fail("resume must not read the dataset"),
    )

    assert RUNNER.resume_start_eia(tmp_path, lookback_days=1) == "2026-09-09T00"


def test_a_null_observation_bucket_is_not_a_resume_point(tmp_path: Path) -> None:
    # Rows with no observation date land in an "__unpartitioned__" partition,
    # whose name sorts after every digit. Taking the last filename blindly
    # would resume from a stem that is not a date at all.
    _store_eia_hours(tmp_path, ["2026-09-10"])
    store = EiaEnergyStorage(tmp_path).partition_store()
    (store.directory / "__unpartitioned__.parquet").write_bytes(
        (store.directory / "2026-09-10.parquet").read_bytes()
    )

    assert RUNNER.resume_start_eia(tmp_path, lookback_days=1) == "2026-09-09T00"


def _store_hkex_days(base: Path, days: list[str]) -> None:
    storage = HkexMarketFlowStorage(base)
    frame = pd.DataFrame({"trade_date": days})
    storage.normalized_root.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(storage.normalized_root / "hkex_market_flow_daily.parquet", index=False)


def test_hkex_resumes_behind_the_newest_stored_trade_date(tmp_path: Path) -> None:
    _store_hkex_days(tmp_path, ["2026-09-09", "2026-09-10", "2026-09-11"])

    assert RUNNER.resume_start_hkex(tmp_path, lookback_days=7) == "2026-09-04"


def test_hkex_falls_back_to_the_backfill_origin_when_nothing_is_stored(tmp_path: Path) -> None:
    assert RUNNER.resume_start_hkex(tmp_path) == RUNNER.HKEX_BACKFILL_START


def test_resume_shrinks_the_hkex_fetch_from_years_to_days(tmp_path: Path) -> None:
    # The point of the whole exercise, asserted rather than asserted-in-prose.
    _store_hkex_days(tmp_path, ["2026-09-11"])
    today = "2026-09-12"

    backfill_days = RUNNER._date_range(RUNNER.HKEX_BACKFILL_START, today)
    resumed_days = RUNNER._date_range(RUNNER.resume_start_hkex(tmp_path), today)

    assert len(backfill_days) > 1_700
    assert len(resumed_days) <= 10


# --- what main() actually passes to the lanes -----------------------------


def _run_main(monkeypatch, tmp_path: Path, argv: list[str]) -> dict:
    seen: dict = {}

    def fake_eia(base_dir, run_id, start, end):
        seen["eia"] = (start, end)
        return {"status": "ok", "rows_fetched": 0}

    def fake_hkex(base_dir, run_id, start, end, workers):
        seen["hkex"] = (start, end)
        return {"status": "ok", "rows_fetched": 0}

    monkeypatch.setattr(RUNNER, "backfill_eia", fake_eia)
    monkeypatch.setattr(RUNNER, "backfill_hkex", fake_hkex)
    monkeypatch.setattr(
        "sys.argv",
        ["backfill", "--base-dir", str(tmp_path), "--source", "eia", "--source", "hkex", *argv],
    )
    RUNNER.main()
    return seen


def test_main_defaults_to_the_full_backfill_range(monkeypatch, tmp_path: Path) -> None:
    _store_eia_hours(tmp_path, ["2026-09-10"])
    _store_hkex_days(tmp_path, ["2026-09-11"])

    seen = _run_main(monkeypatch, tmp_path, [])

    assert seen["eia"][0] == RUNNER.EIA_BACKFILL_START
    assert seen["hkex"][0] == RUNNER.HKEX_BACKFILL_START


def test_main_resumes_from_stored_coverage(monkeypatch, tmp_path: Path) -> None:
    _store_eia_hours(tmp_path, ["2026-09-10"])
    _store_hkex_days(tmp_path, ["2026-09-11"])

    seen = _run_main(monkeypatch, tmp_path, ["--resume"])

    assert seen["eia"][0] == "2026-09-07T00"
    assert seen["hkex"][0] == "2026-09-04"


def test_an_explicit_range_overrides_resume(monkeypatch, tmp_path: Path) -> None:
    # An operator repairing a hole must be able to say so without the stored
    # coverage quietly overriding them.
    _store_eia_hours(tmp_path, ["2026-09-10"])
    _store_hkex_days(tmp_path, ["2026-09-11"])

    seen = _run_main(
        monkeypatch, tmp_path, ["--resume", "--eia-start", "2020-01-01T00", "--hkex-start", "2020-01-01"]
    )

    assert seen["eia"][0] == "2020-01-01T00"
    assert seen["hkex"][0] == "2020-01-01"


def test_a_stored_date_ahead_of_the_end_date_does_not_crash(monkeypatch, tmp_path: Path) -> None:
    # _date_range raises when start > end. A clock skew, or an --end-date
    # pinned to the past, would otherwise take the whole run down.
    _store_eia_hours(tmp_path, ["2026-09-10"])
    _store_hkex_days(tmp_path, ["2026-09-11"])

    seen = _run_main(
        monkeypatch, tmp_path, ["--resume", "--end-date", "2026-09-01", "--eia-end", "2026-09-01T23"]
    )

    assert seen["hkex"][0] <= seen["hkex"][1]
    assert seen["eia"][0] <= seen["eia"][1]


def test_the_manifest_records_the_range_actually_fetched(monkeypatch, tmp_path: Path) -> None:
    # Under --resume the argparse attributes are None; a manifest that recorded
    # those would be provenance pointing at nothing.
    import json

    _store_eia_hours(tmp_path, ["2026-09-10"])
    _store_hkex_days(tmp_path, ["2026-09-11"])
    _run_main(monkeypatch, tmp_path, ["--resume"])

    manifests = list((tmp_path / "data" / "raw" / "free_institutional_backfill").glob("*/manifest.json"))
    scope = json.loads(manifests[0].read_text())["scope"]

    assert scope["eia_start"] == "2026-09-07T00"
    assert scope["hkex_start"] == "2026-09-04"
    assert scope["resumed"] is True
