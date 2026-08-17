from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "audit_hkex_pit_recovery_sidecar.py"
SPEC = importlib.util.spec_from_file_location("audit_hkex_pit_recovery_sidecar", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    legacy = pd.DataFrame(
        [
            {
                "filing_id": "legacy-1",
                "ticker": "2899.HK",
                "announcement_date": "2026-07-10",
                "document_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0710/a.pdf",
            }
        ]
    )
    recovered = pd.DataFrame(
        [
            {
                "filing_id": "legacy-1",
                "ticker": "2899.HK",
                "announcement_date": "2026-07-10",
                "document_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0710/a.pdf",
                "announcement_at": pd.Timestamp("2026-07-10 11:43", tz="UTC"),
                "available_at": pd.Timestamp("2026-07-10 11:53", tz="UTC"),
                "collected_at": pd.Timestamp("2026-08-08 11:43", tz="UTC"),
                "availability_basis": "source_timestamp_proxy",
                "source_item_json": json.dumps(
                    {
                        "DATE_TIME": "10/07/2026 19:43",
                        "FILE_LINK": "/listedco/listconews/sehk/2026/0710/a.pdf",
                        "NEWS_ID": "123",
                        "STOCK_CODE": "02899",
                        "TITLE": "Test filing",
                    }
                ),
            }
        ]
    )
    return legacy, recovered


def test_build_sidecar_proves_official_proxy_and_isolation():
    legacy, recovered = _frames()
    sidecar = MODULE.build_sidecar(legacy, recovered)
    row = sidecar.iloc[0]
    assert len(sidecar) == 1
    assert row["pit_recovery_status"] == "official_datetime_verified"
    assert bool(row["url_continuity_ok"]) is True
    assert bool(row["official_timestamp_ok"]) is True
    assert float(row["availability_delta_minutes"]) == 10.0
    assert row["availability_basis"] == "source_timestamp_proxy"
    assert bool(row["event_study_eligible"]) is False


def test_build_sidecar_rejects_wrong_basis():
    legacy, recovered = _frames()
    recovered.loc[0, "availability_basis"] = "observed_collection"
    sidecar = MODULE.build_sidecar(legacy, recovered)
    assert sidecar.loc[0, "pit_recovery_status"] == "verification_failed"
    assert bool(sidecar.loc[0, "availability_basis_ok"]) is False
