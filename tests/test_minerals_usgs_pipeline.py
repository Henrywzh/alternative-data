from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from minerals_usgs_data.pipeline import MineralsUSGSPipeline


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


def test_pipeline_runs_with_fixture_text(tmp_path: Path) -> None:
    pipeline = MineralsUSGSPipeline(base_dir=tmp_path)

    outputs = pipeline.run(
        pdf_path=tmp_path / "mcs2026.pdf",
        report_year=2026,
        extracted_text=SAMPLE_REPORT_TEXT,
    )

    expected_raw = tmp_path / "data" / "raw" / "minerals_usgs" / "2026" / "mcs2026.txt"
    expected_master = tmp_path / "data" / "processed" / "minerals_usgs" / "2026" / "minerals_master.csv"
    expected_applications = (
        tmp_path / "data" / "processed" / "minerals_usgs" / "2026" / "mineral_applications.csv"
    )
    expected_metrics = tmp_path / "data" / "processed" / "minerals_usgs" / "2026" / "mineral_metrics.csv"

    assert outputs == {
        "raw_text": expected_raw,
        "minerals_master_csv": expected_master,
        "mineral_applications_csv": expected_applications,
        "mineral_metrics_csv": expected_metrics,
    }

    assert expected_raw.read_text(encoding="utf-8") == SAMPLE_REPORT_TEXT

    master_df = pd.read_csv(expected_master)
    applications_df = pd.read_csv(expected_applications)
    metrics_df = pd.read_csv(expected_metrics)

    assert master_df["mineral_id"].tolist() == ["copper", "rare_earths"]
    assert master_df["is_critical_mineral_2025"].tolist() == [True, True]
    assert applications_df["mineral_id"].tolist() == ["copper", "rare_earths"]
    assert applications_df["source_year"].tolist() == [2026, 2026]
    assert metrics_df["metric_name"].tolist() == [
        "net_import_reliance",
        "price_change_pct_2024_2025",
        "price_change_pct_2024_2025",
    ]


def test_pipeline_missing_pdf_does_not_create_output_directories(tmp_path: Path) -> None:
    pipeline = MineralsUSGSPipeline(base_dir=tmp_path)
    missing_pdf = tmp_path / "missing.pdf"
    raw_partition = tmp_path / "data" / "raw" / "minerals_usgs" / "2026"
    processed_partition = tmp_path / "data" / "processed" / "minerals_usgs" / "2026"

    with pytest.raises(FileNotFoundError, match="Missing PDF"):
        pipeline.run(pdf_path=missing_pdf, report_year=2026)

    assert not raw_partition.exists()
    assert not processed_partition.exists()
