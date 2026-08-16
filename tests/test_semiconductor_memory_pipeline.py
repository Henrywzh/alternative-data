from __future__ import annotations

from pathlib import Path

import pandas as pd

from semiconductor_memory_data.models import DatasetRecord
from semiconductor_memory_data.pipeline import SemiconductorMemoryPipeline
from semiconductor_memory_data.storage import StorageManager


def _adata_record(month: str) -> DatasetRecord:
    return DatasetRecord(
        dataset_id="adata_marketwatch_monthly",
        source_url="https://example.test/adata",
        source_run_id="run-adata",
        scraped_at="2026-04-17T00:00:00Z",
        month=month,
        nand_regime_label="stable",
        dram_regime_label="stable",
    )


def _fred_record(series_id: str, date: str, value: float) -> DatasetRecord:
    return DatasetRecord(
        dataset_id="fred_semiconductor_ppi",
        source_url=f"https://fred.test/{series_id}",
        source_run_id="run-fred",
        scraped_at="2026-04-17T00:00:00Z",
        date=date,
        series_id=series_id,
        series_name=series_id,
        value=value,
    )


def test_run_derive_builds_weighted_ai_ppi_and_rebased_components(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    storage.upsert_dataset(
        "adata_marketwatch_monthly",
        [_adata_record("2026-01"), _adata_record("2026-02"), _adata_record("2026-03")],
    )
    storage.upsert_dataset(
        "fred_semiconductor_ppi",
        [
            _fred_record("PCU33443344", "2026-01-01", 50.0),
            _fred_record("PCU33423342", "2026-01-01", 100.0),
            _fred_record("PCU335313335313", "2026-01-01", 200.0),
            _fred_record("PCU334111334111", "2026-01-01", 80.0),
            _fred_record("PCU3341123341121", "2026-01-01", 40.0),
            _fred_record("PCU33443344", "2026-02-01", 55.0),
            _fred_record("PCU33423342", "2026-02-01", 110.0),
            _fred_record("PCU335313335313", "2026-02-01", 210.0),
            _fred_record("PCU334111334111", "2026-02-01", 88.0),
            _fred_record("PCU3341123341121", "2026-02-01", 44.0),
            _fred_record("PCU33443344", "2026-03-01", 60.0),
            _fred_record("PCU33423342", "2026-03-01", 120.0),
            _fred_record("PCU335313335313", "2026-03-01", 220.0),
            _fred_record("PCU334111334111", "2026-03-01", 96.0),
        ],
    )

    pipeline = SemiconductorMemoryPipeline(tmp_path)
    pipeline.run_derive()

    derived = pd.read_csv(
        tmp_path / "data" / "normalized" / "semiconductor_memory" / "semiconductor_memory_regime_monthly.csv"
    )
    jan = derived.loc[derived["month"] == "2026-01"].iloc[0]
    feb = derived.loc[derived["month"] == "2026-02"].iloc[0]
    mar = derived.loc[derived["month"] == "2026-03"].iloc[0]

    assert jan["fred_ppi_value"] == 100.0
    assert round(feb["fred_ppi_value"], 6) == round((102.5 / 95.0) * 100.0, 6)
    # March is 4/5 (storage devices missing): it is emitted as a partial point
    # using renormalized weights over the four available components.
    # raw = 0.4210526*60 + 0.2631579*120 + 0.2105263*220 + 0.1052632*96 = 113.263158
    assert round(mar["fred_ppi_value"], 6) == round((113.263158 / 95.0) * 100.0, 6)
    assert mar["component_coverage"] == "4/5"
    assert mar["missing_components"] == "PCU3341123341121"
    assert feb["ppi_component_pcu33443344_rebased"] == 110.0
    assert feb["ppi_component_pcu33423342_rebased"] == 110.0
    assert feb["ppi_component_pcu335313335313_rebased"] == 105.0
    assert pd.isna(mar["ppi_component_pcu3341123341121_rebased"])
    assert round(feb["fred_ppi_mom_pct"], 6) == round((((102.5 / 95.0) * 100.0) / 100.0 - 1.0) * 100.0, 6)


def test_run_derive_emits_and_flags_partial_month_when_component_lags(tmp_path: Path) -> None:
    """A month missing one basket component must still produce a PPI value,
    explicitly flagged, so the dashboard can show July without a silent gap."""
    storage = StorageManager(tmp_path)
    storage.upsert_dataset("adata_marketwatch_monthly", [_adata_record("2026-02")])
    storage.upsert_dataset(
        "fred_semiconductor_ppi",
        _full_fred_month("2026-01", 50.0)
        + _full_fred_month("2026-02", 55.0)
        # March is complete except storage devices (the 5th basket component).
        + [
            _fred_record("PCU33443344", "2026-03-01", 60.0),
            _fred_record("PCU33423342", "2026-03-01", 120.0),
            _fred_record("PCU335313335313", "2026-03-01", 220.0),
            _fred_record("PCU334111334111", "2026-03-01", 96.0),
        ],
    )

    SemiconductorMemoryPipeline(tmp_path).run_derive()

    ppi = storage.load_dataset("fred_semiconductor_ppi_monthly")
    assert sorted(ppi["month"].tolist()) == ["2026-01", "2026-02", "2026-03"]
    mar = ppi.loc[ppi["month"] == "2026-03"].iloc[0]
    assert mar["component_coverage"] == "4/5"
    assert mar["missing_components"] == "PCU3341123341121"
    assert pd.notna(mar["fred_ppi_value"])
    # Full months carry the complete-basket label and no missing components.
    jan = ppi.loc[ppi["month"] == "2026-01"].iloc[0]
    assert jan["component_coverage"] == "5/5"
    missing_jan = jan["missing_components"]
    assert missing_jan is None or pd.isna(missing_jan) or missing_jan in ("", "nan")


def _full_fred_month(month: str, base: float) -> list[DatasetRecord]:
    return [
        _fred_record("PCU33443344", f"{month}-01", base),
        _fred_record("PCU33423342", f"{month}-01", base * 2),
        _fred_record("PCU335313335313", f"{month}-01", base * 4),
        _fred_record("PCU334111334111", f"{month}-01", base * 1.6),
        _fred_record("PCU3341123341121", f"{month}-01", base * 0.8),
    ]


def test_run_derive_persists_standalone_fred_ppi_monthly_table(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    storage.upsert_dataset(
        "fred_semiconductor_ppi",
        _full_fred_month("2026-01", 50.0) + _full_fred_month("2026-02", 55.0),
    )
    # ADATA covers only one month, mimicking a stale/collapsed scraper.
    storage.upsert_dataset("adata_marketwatch_monthly", [_adata_record("2026-02")])

    SemiconductorMemoryPipeline(tmp_path).run_derive()

    ppi = storage.load_dataset("fred_semiconductor_ppi_monthly")
    # PPI table carries the full FRED history regardless of ADATA coverage.
    assert sorted(ppi["month"].tolist()) == ["2026-01", "2026-02"]
    jan = ppi.loc[ppi["month"] == "2026-01"].iloc[0]
    feb = ppi.loc[ppi["month"] == "2026-02"].iloc[0]
    assert jan["fred_ppi_value"] == 100.0
    assert round(feb["fred_ppi_value"], 6) == round((55.0 / 50.0) * 100.0, 6)
    assert round(feb["ppi_component_pcu33443344_rebased"], 6) == 110.0


def test_run_derive_ppi_monthly_unaffected_by_collapsed_adata(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    storage.upsert_dataset(
        "fred_semiconductor_ppi",
        _full_fred_month("2026-01", 50.0) + _full_fred_month("2026-02", 55.0),
    )
    # No ADATA at all: the shared regime table would go blank, but the dedicated
    # PPI table must still hold the full FRED-derived series.
    SemiconductorMemoryPipeline(tmp_path).run_derive()

    ppi = storage.load_dataset("fred_semiconductor_ppi_monthly")
    assert len(ppi) == 2
    assert ppi["fred_ppi_value"].notna().all()


def test_run_derive_uses_fred_only_when_adata_is_missing(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    storage.upsert_dataset(
        "fred_semiconductor_ppi",
        [
            _fred_record("PCU33443344", "2026-01-01", 50.0),
            _fred_record("PCU33423342", "2026-01-01", 100.0),
            _fred_record("PCU335313335313", "2026-01-01", 200.0),
            _fred_record("PCU334111334111", "2026-01-01", 80.0),
            _fred_record("PCU3341123341121", "2026-01-01", 40.0),
        ],
    )

    pipeline = SemiconductorMemoryPipeline(tmp_path)
    pipeline.run_derive()

    derived = pd.read_csv(
        tmp_path / "data" / "normalized" / "semiconductor_memory" / "semiconductor_memory_regime_monthly.csv"
    )
    jan = derived.loc[derived["month"] == "2026-01"].iloc[0]

    assert jan["data_completeness"] == "fred_only"
    assert jan["fred_ppi_value"] == 100.0
