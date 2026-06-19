from __future__ import annotations

from pathlib import Path

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

        outputs = storage.write_all(
            master_records=build_master_records(section_names, critical_mineral_names),
            application_records=build_application_records(sections, report_year),
            metric_records=build_metric_records(sections, report_year),
        )
        return {"raw_text": raw_text_path, **outputs}
