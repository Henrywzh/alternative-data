from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "audit_hkex_event_study_outputs.py"
SPEC = importlib.util.spec_from_file_location("audit_hkex_event_study_outputs", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_post_write_audit_reports_missing_artifacts(tmp_path: Path):
    result = MODULE.audit_output(tmp_path)

    assert result["status"] == "failed"
    assert "missing_artifacts" in result["errors"][0]


def test_comparison_audit_reconciles_same_cutoff_pair(tmp_path: Path):
    path = tmp_path / "comparison.json"
    path.write_text(
        json.dumps(
            {
                "replays": [
                    {"capture_id": "a", "status": "ok", "market_cutoff_5m": "2026-08-07T08:05:00Z", "market_cutoff_1h": "2026-08-07T07:30:00Z"},
                    {"capture_id": "b", "status": "ok", "market_cutoff_5m": "2026-08-07T08:05:00+00:00", "market_cutoff_1h": "2026-08-07T07:30:00+00:00"},
                ],
                "pairs": [
                    {
                        "left_capture_id": "a",
                        "right_capture_id": "b",
                        "market_cutoff_status": "same",
                        "left_market_cutoff_5m": "2026-08-07T08:05:00Z",
                        "right_market_cutoff_5m": "2026-08-07T08:05:00+00:00",
                        "left_market_cutoff_1h": "2026-08-07T07:30:00Z",
                        "right_market_cutoff_1h": "2026-08-07T07:30:00+00:00",
                        "exact_replay_consistent": True,
                    }
                ],
                "pair_count": 1,
                "distinct_market_cutoff_pair_count": 0,
                "partial_market_cutoff_pair_count": 0,
                "robustness_status": "insufficient_distinct_market_cutoffs",
                "production_database_modified": False,
            },
            indent=2,
        )
    )

    result = MODULE.audit_comparison(path)

    assert result["status"] == "ok"
    assert result["pair_count"] == 1
