from __future__ import annotations

from pathlib import Path

from minerals_usgs_data.models import MineralMasterRecord, MineralMetricRecord
from minerals_usgs_data.sources.parser import (
    build_application_records,
    build_master_records,
    build_metric_records,
    extract_contents_section_names,
    extract_critical_mineral_names,
    split_mineral_sections,
)
from minerals_usgs_data.sources.pdf_text import extract_pdf_text
from minerals_usgs_data.storage import MineralsStorage

ALLOWED_METRIC_NAMES = frozenset(
    {
        "net_import_reliance",
        "price_change_pct_2024_2025",
    }
)


def validate_master_records(
    master_records: list[MineralMasterRecord], expected_count: int
) -> None:
    if len(master_records) != expected_count:
        raise ValueError(
            f"Parsed mineral count mismatch: expected {expected_count}, got {len(master_records)}"
        )

    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    for record in master_records:
        if record.mineral_id in seen_ids:
            duplicate_ids.add(record.mineral_id)
            continue
        seen_ids.add(record.mineral_id)

    if duplicate_ids:
        duplicates = ", ".join(sorted(duplicate_ids))
        raise ValueError(f"Duplicate mineral_id values found: {duplicates}")


def validate_metric_records(metric_records: list[MineralMetricRecord]) -> None:
    invalid_metric_names = sorted(
        {record.metric_name for record in metric_records if record.metric_name not in ALLOWED_METRIC_NAMES}
    )
    if invalid_metric_names:
        invalid_names = ", ".join(invalid_metric_names)
        raise ValueError(f"Unsupported metric_name values found: {invalid_names}")


class MineralsUSGSPipeline:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def run(
        self,
        pdf_path: Path,
        report_year: int,
        extracted_text: str | None = None,
    ) -> dict[str, Path]:
        resolved_pdf_path = Path(pdf_path)
        report_text = extracted_text if extracted_text is not None else extract_pdf_text(resolved_pdf_path)
        storage = MineralsStorage(self.base_dir, report_year=report_year)

        raw_text_path = storage.write_raw_text(
            file_name=f"mcs{report_year}.txt",
            text=report_text,
        )

        section_names = extract_contents_section_names(report_text)
        sections = split_mineral_sections(report_text, section_names)
        critical_mineral_names = extract_critical_mineral_names(report_text)
        master_records = build_master_records(section_names, critical_mineral_names)
        application_records = build_application_records(sections, report_year)
        metric_records = build_metric_records(sections, report_year)

        validate_master_records(master_records, expected_count=len(section_names))
        validate_metric_records(metric_records)

        outputs = storage.write_all(
            master_records=master_records,
            application_records=application_records,
            metric_records=metric_records,
        )
        return {"raw_text": raw_text_path, **outputs}
