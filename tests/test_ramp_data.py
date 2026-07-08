"""Tests for the Ramp vendor-intelligence pipeline.

These focus on the failure modes of the original ``scripts/run_ramp_scraper.py``
that this package replaces: broken RSC unescaping, brace-in-string extraction,
key-order sensitivity, and history-erasing silent writes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ramp_data.models import RunContext, Snapshot
from ramp_data.pipeline import RampPipeline, ValidationError
from ramp_data.schemas import JOBS_IMPACT_DATASET
from ramp_data.sources import rsc
from ramp_data.sources.ai_index import RampAiIndexSource
from ramp_data.sources.jobs_impact import RampJobsImpactSource, _figure_from_caption
from ramp_data.sources.vendors import RampVendorsSource
from ramp_data.storage import StorageManager


def _push(chunk_body: str) -> str:
    """Wrap a raw RSC chunk body the way Ramp's HTML does."""
    return f'<script>self.__next_f.push([1,{json.dumps(chunk_body)}])</script>'


def _context() -> RunContext:
    return RunContext(run_id="test", scraped_at=datetime(2026, 7, 1, tzinfo=timezone.utc))


# ---------------------------------------------------------------- RSC decoding


def test_decode_payload_handles_unicode_escape():
    # The old scraper left literal & in category names; the proper decode
    # turns it back into an ampersand.
    html = _push(r'{"name":"Image & Video AI","pathname":"/vendors/categories/image-video-ai"}')
    payload = rsc.decode_payload(html)
    assert "Image & Video AI" in payload
    assert "u0026" not in payload


def test_objects_containing_is_key_order_independent():
    # cleanDomain appears AFTER a nested object — the old rfind('{') heuristic
    # would have grabbed the nested object and dropped the vendor.
    payload = (
        '{"logo":{"asset":"x"},"keyStats":{"adoptionRateValue":0.5},'
        '"cleanDomain":"cursor.com","name":"Cursor","pathname":"/vendors/cursor"}'
    )
    found = rsc.objects_containing(payload, '"cleanDomain":', {"cleanDomain", "name", "pathname"})
    assert len(found) == 1
    assert found[0]["name"] == "Cursor"
    assert found[0]["keyStats"]["adoptionRateValue"] == 0.5


def test_objects_containing_survives_brace_in_string():
    # A brace inside a string value used to unbalance the manual brace counter.
    payload = '{"cleanDomain":"x.com","name":"Weird } Vendor {","pathname":"/vendors/weird"}'
    found = rsc.objects_containing(payload, '"cleanDomain":', {"cleanDomain", "name", "pathname"})
    assert len(found) == 1
    assert found[0]["name"] == "Weird } Vendor {"


def test_extract_array_after_key():
    payload = '...{"historicalData":[{"spendMonth":"2026-06-01","adoptionRate":{"value":0.5}}],"x":1}'
    arr = rsc.extract_array_after_key(payload, "historicalData")
    assert len(arr) == 1
    assert arr[0]["spendMonth"] == "2026-06-01"


# ------------------------------------------------------------------- extract


def _sample_snapshots() -> list[Snapshot]:
    index = json.dumps([{"name": "Code AI", "pathname": "/vendors/categories/code-ai"}])
    category = json.dumps(
        [
            {
                "cleanDomain": "cursor.com",
                "name": "Cursor",
                "pathname": "/vendors/cursor",
                "keyStats": {"adoptionRateValue": 0.95, "adoptionRateYoyChange": -0.01},
            }
        ]
    )
    vendor = json.dumps(
        [
            {
                "spendMonth": "2026-06-01",
                "adoptionRank": {"value": 1, "momChange": 0},
                "adoptionRate": {"value": 0.95, "yoyChange": -0.01},
                "competitorSwitchRate": 0.4,
                "newAdopterShare": 0.85,
                "dominantFteSegment": "Mid-Market",
                "dominantFteSegmentPct": 0.44,
            }
        ]
    )
    return [
        Snapshot("index", "https://ramp.com/vendors", index),
        Snapshot("category__code-ai", "https://ramp.com/vendors/categories/code-ai", category),
        Snapshot("vendor__cursor", "https://ramp.com/vendors/cursor", vendor),
    ]


def test_extract_produces_both_datasets():
    extracted = RampVendorsSource().extract(_sample_snapshots(), _context())

    cats = extracted["ramp_category_vendors"]
    assert len(cats) == 1
    assert cats[0].category_name == "Code AI"
    assert cats[0].vendor_slug == "cursor"
    assert cats[0].adoption_rate == pytest.approx(0.95)

    monthly = extracted["ramp_vendor_adoption_monthly"]
    assert len(monthly) == 1
    row = monthly[0]
    assert row.vendor_slug == "cursor"
    # Vendor identity is joined in from the category card.
    assert row.vendor_name == "Cursor"
    assert row.spend_month == "2026-06-01"
    assert row.adoption_rank == 1
    assert row.competitor_switch_rate == pytest.approx(0.4)


# ------------------------------------------------------------------- storage


def test_upsert_accumulates_history_and_is_idempotent(tmp_path: Path):
    storage = StorageManager(tmp_path)
    source = RampVendorsSource()

    first = source.extract(_sample_snapshots(), _context())
    storage.upsert_dataset("ramp_vendor_adoption_monthly", first["ramp_vendor_adoption_monthly"])

    parquet = tmp_path / "data" / "normalized" / "ramp" / "ramp_vendor_adoption_monthly.parquet"
    before = parquet.read_bytes()

    # Re-running with identical data must not churn the parquet (provenance preserved).
    storage.upsert_dataset("ramp_vendor_adoption_monthly", first["ramp_vendor_adoption_monthly"])
    assert parquet.read_bytes() == before

    # A new month accumulates rather than replacing.
    vendor2 = json.dumps(
        [{"spendMonth": "2026-07-01", "adoptionRate": {"value": 0.96}, "adoptionRank": {"value": 1}}]
    )
    snaps = _sample_snapshots()[:2] + [Snapshot("vendor__cursor", "https://ramp.com/vendors/cursor", vendor2)]
    second = RampVendorsSource().extract(snaps, _context())
    merged = storage.upsert_dataset("ramp_vendor_adoption_monthly", second["ramp_vendor_adoption_monthly"])
    assert set(merged["spend_month"]) == {"2026-06-01", "2026-07-01"}


def test_category_vendors_snapshot_prunes_delisted(tmp_path: Path):
    storage = StorageManager(tmp_path)
    source = RampVendorsSource()
    storage.upsert_dataset("ramp_category_vendors", source.extract(_sample_snapshots(), _context())["ramp_category_vendors"])

    # Next crawl: the category now lists a different vendor. The old one is pruned
    # (REPLACE dataset semantics), not left to linger.
    index = json.dumps([{"name": "Code AI", "pathname": "/vendors/categories/code-ai"}])
    category = json.dumps(
        [{"cleanDomain": "windsurf.com", "name": "Windsurf", "pathname": "/vendors/windsurf",
          "keyStats": {"adoptionRateValue": 0.3}}]
    )
    snaps = [
        Snapshot("index", "https://ramp.com/vendors", index),
        Snapshot("category__code-ai", "https://ramp.com/vendors/categories/code-ai", category),
    ]
    merged = storage.upsert_dataset("ramp_category_vendors", RampVendorsSource().extract(snaps, _context())["ramp_category_vendors"])
    assert set(merged["vendor_slug"]) == {"windsurf"}


# ------------------------------------------------------------------ pipeline


def test_quality_gate_rejects_empty_extraction():
    pipeline = RampPipeline(Path("."))
    # No category pages + no rows -> ValidationError, so a blocked crawl can never
    # be upserted over committed history.
    with pytest.raises(ValidationError):
        pipeline._assert_quality([], {"ramp_category_vendors": [], "ramp_vendor_adoption_monthly": []})


# ------------------------------------------------------------------ AI Index


def test_ai_index_extract_and_upsert(tmp_path: Path):
    # A minimal RSC-style payload: named keys each holding a JSON array. The
    # extractor keys off these names and passes fields through.
    payload = (
        'prefix...'
        '"adoptionOverall":[{"date_month":"2024-01-01","adoption_rate_pct":10.5,"mom_change_pp":0.3,"yoy_change_pp":2.1},'
        '{"date_month":"2024-02-01","adoption_rate_pct":11.0,"mom_change_pp":0.5,"yoy_change_pp":2.4}],'
        '"adoptionVendor":[{"date_month":"2024-01-01","vendor":"OpenAI","adoption_rate_pct":3.2,"mom_change_pp":0.1}],'
        '...suffix'
    )
    snap = [Snapshot("ai_index", "https://ramp.com/data/ai-index", payload)]
    extracted = RampAiIndexSource().extract(snap, _context())

    overall = extracted["ramp_ai_adoption_overall"]
    assert len(overall) == 2
    assert overall[0].payload["adoption_rate_pct"] == 10.5
    assert extracted["ramp_ai_adoption_by_vendor"][0].payload["vendor"] == "OpenAI"

    storage = StorageManager(tmp_path)
    merged = storage.upsert_dataset("ramp_ai_adoption_overall", overall)
    assert list(merged["date_month"]) == ["2024-01-01", "2024-02-01"]
    assert set(merged.columns) >= {"date_month", "adoption_rate_pct", "mom_change_pp", "yoy_change_pp"}

    # Idempotent re-upsert: unchanged payload -> identical parquet.
    parquet = tmp_path / "data" / "normalized" / "ramp" / "ramp_ai_adoption_overall.parquet"
    before = parquet.read_bytes()
    storage.upsert_dataset("ramp_ai_adoption_overall", overall)
    assert parquet.read_bytes() == before


def test_ai_index_gate_rejects_thin_extraction():
    pipeline = RampPipeline(Path("."))
    with pytest.raises(ValidationError):
        pipeline._assert_ai_index_quality([], {dsid: [] for dsid in ("ramp_ai_adoption_overall",)})


# --------------------------------------------------------------- Jobs Impact


_JOBS_HEADERS = [
    "Month Relative to Adoption",
    "Effect on High-Intensity Firms (log points × 100)",
    "Low-End Confidence Interval on High-Intensity Firms (log points × 100)",
    "High-End Confidence Interval on High-Intensity Firms (log points × 100)",
    "Effect on Low-Intensity Firms (log points × 100)",
    "Low-End Confidence Interval on Low-Intensity Firms (log points × 100)",
    "High-End Confidence Interval on Low-Intensity Firms (log points × 100)",
]


def test_figure_from_caption():
    cap = "Change in headcount after AI adoption: Total Headcount: estimates and 95% confidence intervals"
    assert _figure_from_caption(cap) == "total_headcount"


def test_jobs_impact_extract_normalizes_table():
    tables = [{
        "caption": "Change in headcount after AI adoption: Total Headcount: estimates and 95% CIs",
        "headers": _JOBS_HEADERS,
        "rows": [
            ["-12", "-2.74", "-7.11", "1.64", "-0.39", "-3.40", "2.63"],
            ["0", "0.00", "-1.00", "1.00", "0.10", "-0.50", "0.70"],
        ],
    }]
    snap = [Snapshot("jobs_impact_tables", "https://ramp.com/data/ai-jobs-impact", json.dumps(tables))]
    records = RampJobsImpactSource().extract(snap, _context())[JOBS_IMPACT_DATASET]
    assert len(records) == 2
    row = records[0].payload
    assert row["figure"] == "total_headcount"
    assert row["month_relative_to_adoption"] == -12
    assert row["high_intensity_effect"] == -2.74
    assert row["high_intensity_ci_low"] == -7.11
    assert row["low_intensity_ci_high"] == 2.63
    assert row["units"] == "log points x 100"


def test_jobs_impact_skips_unrelated_table():
    # A table that isn't the 7-column event study must be ignored, not mis-parsed.
    tables = [{"caption": "Something else", "headers": ["a", "b"], "rows": [["1", "2"]]}]
    snap = [Snapshot("jobs_impact_tables", "https://ramp.com/data/ai-jobs-impact", json.dumps(tables))]
    records = RampJobsImpactSource().extract(snap, _context())[JOBS_IMPACT_DATASET]
    assert records == []
