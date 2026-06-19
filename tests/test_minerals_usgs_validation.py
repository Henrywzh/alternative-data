from __future__ import annotations

from pathlib import Path

import pytest

import minerals_usgs_data.pipeline as pipeline_module
from minerals_usgs_data.models import MineralMasterRecord, MineralMetricRecord
from minerals_usgs_data.pipeline import (
    MineralsUSGSPipeline,
    validate_master_records,
    validate_metric_records,
)


SAMPLE_REPORT_TEXT = """
CONTENTS
Table 1—U.S. Mineral Industry Trends .......................... 10

Mineral Commodities:
Copper ......................................................................... 72
Rare Earths .................................................................... 152
\f
MINERAL COMMODITY SUMMARIES 2026

Copper
Events, Trends, and Issues
Copper is used in electrical wiring, construction, and renewable energy systems.
Net import reliance as a percentage of apparent consumption was 45% in 2025.
The annual average U.S. producer price increased by 12% from 2024 to 2025.

Rare Earths
Events, Trends, and Issues
Rare earths were used principally in magnets, catalysts, and polishing compounds.
The annual average price increased by 8% from 2024 to 2025.

Table 6—The U.S. Final 2025 Critical Minerals List
Copper
Rare Earths

Table 7—Salient Critical Minerals Statistics in 2025
"""


def test_validate_master_records_rejects_duplicate_mineral_ids() -> None:
    master_records = [
        MineralMasterRecord(
            mineral_id="copper",
            mineral_name="Copper",
            usgs_section_name="Copper",
            category="metal",
            is_critical_mineral_2025=True,
            notes=None,
        ),
        MineralMasterRecord(
            mineral_id="copper",
            mineral_name="Copper (Duplicate)",
            usgs_section_name="Copper Duplicate",
            category="metal",
            is_critical_mineral_2025=True,
            notes=None,
        ),
    ]

    with pytest.raises(ValueError, match="Duplicate mineral_id values found: copper"):
        validate_master_records(master_records, expected_count=2)


def test_validate_master_records_rejects_parsed_mineral_count_mismatch() -> None:
    master_records = [
        MineralMasterRecord(
            mineral_id="copper",
            mineral_name="Copper",
            usgs_section_name="Copper",
            category="metal",
            is_critical_mineral_2025=True,
            notes=None,
        )
    ]

    with pytest.raises(ValueError, match="Parsed mineral count mismatch: expected 2, got 1"):
        validate_master_records(master_records, expected_count=2)


def test_validate_metric_records_rejects_unknown_metric_names() -> None:
    metric_records = [
        MineralMetricRecord(
            mineral_id="copper",
            metric_name="unexpected_metric",
            metric_value=1.0,
            metric_unit="pct",
            metric_period="annual",
            metric_year=2025,
            comparison_year=None,
            source_year=2026,
            source_type="usgs_mcs",
            source_section_name="Copper",
            source_page_hint=None,
            notes=None,
        )
    ]

    with pytest.raises(ValueError, match="Unsupported metric_name values found: unexpected_metric"):
        validate_metric_records(metric_records)


def test_pipeline_run_validates_before_writing_processed_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline = MineralsUSGSPipeline(base_dir=tmp_path)

    def duplicate_master_records(
        section_names: list[str], critical_mineral_names: set[str]
    ) -> list[MineralMasterRecord]:
        return [
            MineralMasterRecord(
                mineral_id="copper",
                mineral_name="Copper",
                usgs_section_name="Copper",
                category="metal",
                is_critical_mineral_2025=True,
                notes=None,
            ),
            MineralMasterRecord(
                mineral_id="copper",
                mineral_name="Rare Earths",
                usgs_section_name="Rare Earths",
                category="rare_earth",
                is_critical_mineral_2025=True,
                notes=None,
            ),
        ]

    monkeypatch.setattr(pipeline_module, "build_master_records", duplicate_master_records)

    with pytest.raises(ValueError, match="Duplicate mineral_id values found: copper"):
        pipeline.run(
            pdf_path=tmp_path / "mcs2026.pdf",
            report_year=2026,
            extracted_text=SAMPLE_REPORT_TEXT,
        )

    assert (tmp_path / "data" / "raw" / "minerals_usgs" / "2026" / "mcs2026.txt").exists()
    assert not (
        tmp_path / "data" / "processed" / "minerals_usgs" / "2026" / "minerals_master.csv"
    ).exists()
    assert not (
        tmp_path / "data" / "processed" / "minerals_usgs" / "2026" / "mineral_applications.csv"
    ).exists()
    assert not (
        tmp_path / "data" / "processed" / "minerals_usgs" / "2026" / "mineral_metrics.csv"
    ).exists()
