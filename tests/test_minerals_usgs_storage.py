from __future__ import annotations

from pathlib import Path

import pandas as pd

from minerals_usgs_data.models import (
    MineralApplicationRecord,
    MineralMasterRecord,
    MineralMetricRecord,
)
from minerals_usgs_data.storage import MineralsStorage


def test_storage_writes_csv_and_parquet(tmp_path: Path) -> None:
    storage = MineralsStorage(tmp_path, report_year=2026)
    storage.write_all(
        master_records=[
            MineralMasterRecord(
                mineral_id="copper",
                mineral_name="Copper",
                usgs_section_name="Copper",
                category="metal",
                is_critical_mineral_2025=True,
                notes=None,
            )
        ],
        application_records=[
            MineralApplicationRecord(
                mineral_id="copper",
                application_text="Electrical wiring and motors.",
                source_year=2026,
                source_type="usgs_mcs",
                source_section_name="Copper",
                source_page_hint="72-73",
                extraction_confidence="high",
            )
        ],
        metric_records=[
            MineralMetricRecord(
                mineral_id="copper",
                metric_name="price_change_pct_2024_2025",
                metric_value=12.5,
                metric_unit="percent",
                metric_period="2024_2025",
                metric_year=2025,
                comparison_year=2024,
                source_year=2026,
                source_type="usgs_mcs",
                source_section_name="Copper",
                source_page_hint="72-73",
                notes=None,
            ),
            MineralMetricRecord(
                mineral_id="copper",
                metric_name="notes",
                metric_value="stable supply outlook",
                metric_unit=None,
                metric_period="2024_2025",
                metric_year=2025,
                comparison_year=None,
                source_year=2026,
                source_type="usgs_mcs",
                source_section_name="Copper",
                source_page_hint="72-73",
                notes="qualitative",
            ),
        ],
    )

    master_csv = tmp_path / "data" / "processed" / "minerals_usgs" / "2026" / "minerals_master.csv"
    master_parquet = tmp_path / "data" / "processed" / "minerals_usgs" / "2026" / "minerals_master.parquet"
    applications_csv = tmp_path / "data" / "processed" / "minerals_usgs" / "2026" / "mineral_applications.csv"
    applications_parquet = tmp_path / "data" / "processed" / "minerals_usgs" / "2026" / "mineral_applications.parquet"
    metrics_csv = tmp_path / "data" / "processed" / "minerals_usgs" / "2026" / "mineral_metrics.csv"
    metrics_parquet = tmp_path / "data" / "processed" / "minerals_usgs" / "2026" / "mineral_metrics.parquet"

    assert master_csv.exists()
    assert master_parquet.exists()
    assert applications_csv.exists()
    assert applications_parquet.exists()
    assert metrics_csv.exists()
    assert metrics_parquet.exists()

    master_df = pd.read_csv(master_csv)
    master_parquet_df = pd.read_parquet(master_parquet)
    applications_df = pd.read_parquet(applications_parquet)
    metric_df = pd.read_csv(metrics_csv)
    metric_parquet_df = pd.read_parquet(metrics_parquet)

    assert master_df.loc[0, "mineral_id"] == "copper"
    assert bool(master_df.loc[0, "is_critical_mineral_2025"]) is True
    assert master_parquet_df.loc[0, "mineral_name"] == "Copper"
    assert applications_df.loc[0, "application_text"] == "Electrical wiring and motors."
    assert metric_df.loc[0, "metric_name"] == "price_change_pct_2024_2025"
    assert metric_parquet_df.loc[0, "metric_unit"] == "percent"
    assert metric_parquet_df.loc[0, "metric_value"] == "12.5"
    assert metric_parquet_df.loc[1, "metric_name"] == "notes"
    assert metric_parquet_df.loc[1, "metric_value"] == "stable supply outlook"
