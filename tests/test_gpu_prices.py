from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import requests

from gpu_prices import pipeline


def _weekly_csv(rows: list[tuple[str, float]]) -> bytes:
    header = "gpu_slug,date,billing_type,reservation_months,min_price,max_price,median_price,provider_median_price,provider_count,offering_count\n"
    return (header + "".join(f"nvidia-h100,{day},ON_DEMAND,,1,6,{price},{price},3,4\n" for day, price in rows)).encode()


def test_weekly_parser_rejects_duplicate_keys_and_keeps_nullable_term() -> None:
    content = _weekly_csv([("2026-10-05", 3.0), ("2026-10-12", 3.2)])
    frame = pipeline.parse_getdeploying(content)
    assert frame.reservation_months.isna().all()
    assert frame.provider_median_price.tolist() == [3.0, 3.2]
    with pytest.raises(ValueError, match="duplicate natural keys"):
        pipeline.parse_getdeploying(_weekly_csv([("2026-10-05", 3.0), ("2026-10-05", 3.2)]))
    with pytest.raises(ValueError, match="Monday"):
        pipeline.parse_getdeploying(_weekly_csv([("2026-10-06", 3.0)]))


def test_screener_null_price_and_original_status_flags_survive() -> None:
    content = json.dumps({"H100": [
        {"d": "2026-10-01", "v": 2.5, "p": 6, "final": True, "w": 1, "restated": True},
        {"d": "2026-10-23", "v": None, "p": 3, "final": False},
    ]}).encode()
    frame = pipeline.parse_screener(content)
    assert frame.weekly.tolist() == [True, False]
    assert frame.final.tolist() == [True, False]
    assert frame.restated.tolist() == [True, None]
    assert pd.isna(frame.iloc[1].price_usd_per_hour)


class _Response:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self, content: bytes | None) -> None:
        self.content = content

    def get(self, url: str, **kwargs):
        if self.content is None:
            raise requests.ConnectionError("source unavailable")
        return _Response(self.content)


def test_refresh_retains_history_and_never_replaces_it_after_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "SOURCES", {"getdeploying": "https://example.test/weekly.csv"})
    monkeypatch.setattr(pipeline, "MIN_ROWS", {"getdeploying": 1})
    target = tmp_path / "data/normalized/gpu_price_history/getdeploying.parquet"
    first = pipeline.refresh(tmp_path, session=_Session(_weekly_csv([("2026-10-05", 3.0), ("2026-10-12", 3.2)])))
    assert first["sources"]["getdeploying"]["status"] == "ok"
    second = pipeline.refresh(tmp_path, session=_Session(_weekly_csv([("2026-10-12", 3.4), ("2026-10-19", 3.6)])))
    frame = pd.read_parquet(target).sort_values("date")
    assert second["sources"]["getdeploying"]["status"] == "ok"
    assert frame.date.tolist() == ["2026-10-05", "2026-10-12", "2026-10-19"]
    assert frame.provider_median_price.tolist() == [3.0, 3.4, 3.6]
    before_failure = target.read_bytes()
    failed = pipeline.refresh(tmp_path, session=_Session(None))
    assert failed["sources"]["getdeploying"]["status"] == "failed"
    assert target.read_bytes() == before_failure
    older = pipeline.refresh(tmp_path, session=_Session(_weekly_csv([("2026-10-05", 9.0)])))
    assert "regressed" in older["sources"]["getdeploying"]["error"]
    assert target.read_bytes() == before_failure
    assert len(list((tmp_path / "data/raw/gpu_price_history").glob("*.bin"))) == 2
