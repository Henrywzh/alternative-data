from minerals_usgs_data.models import (
    MineralApplicationRecord,
    MineralMasterRecord,
    MineralMetricRecord,
)
from minerals_usgs_data.sources.parser import (
    build_application_records,
    build_master_records,
    build_metric_records,
    extract_critical_mineral_names,
)


SAMPLE_SECTION_NAMES = [
    "Copper",
    "Rare Earths",
    "Stone (Crushed)",
]

SAMPLE_CRITICAL_MINERAL_NAMES = {"Rare Earths", "Copper"}

SAMPLE_SECTIONS = {
    "Copper": """Copper
Events, Trends, and Issues
Copper is used in electrical wiring, construction, and renewable energy systems.
Net import reliance as a percentage of apparent consumption was 45% in 2025.
The annual average U.S. producer price increased by 12% from 2024 to 2025.
""",
    "Rare Earths": """Rare Earths
Events, Trends, and Issues
Rare earths were used principally in magnets, catalysts, and polishing compounds.
The annual average price increased by 8% from 2024 to 2025.
""",
    "Stone (Crushed)": """Stone (Crushed)
Events, Trends, and Issues
Crushed stone was used as construction aggregate and road base material.
""",
}


def test_extract_critical_mineral_names_reads_table_entries() -> None:
    report_text = """
Table 6—The U.S. Final 2025 Critical Minerals List
Copper
Rare Earths
Zinc

Table 7—Salient Critical Minerals Statistics in 2025
"""

    names = extract_critical_mineral_names(report_text)

    assert names == {"Copper", "Rare Earths", "Zinc"}


def test_extract_critical_mineral_names_preserves_comma_bearing_section_names() -> None:
    report_text = """
Table 6—The U.S. Final 2025 Critical Minerals List
Titanium mineral concentrates, ilmenite and rutile
Zinc

Table 7—Salient Critical Minerals Statistics in 2025
"""

    names = extract_critical_mineral_names(report_text)

    assert names == {
        "Titanium mineral concentrates, ilmenite and rutile",
        "Zinc",
    }


def test_build_master_records_creates_deterministic_categories() -> None:
    records = build_master_records(SAMPLE_SECTION_NAMES, SAMPLE_CRITICAL_MINERAL_NAMES)

    assert records == [
        MineralMasterRecord(
            mineral_id="copper",
            mineral_name="Copper",
            usgs_section_name="Copper",
            category="metal",
            is_critical_mineral_2025=True,
            notes=None,
        ),
        MineralMasterRecord(
            mineral_id="rare_earths",
            mineral_name="Rare Earths",
            usgs_section_name="Rare Earths",
            category="rare_earth",
            is_critical_mineral_2025=True,
            notes=None,
        ),
        MineralMasterRecord(
            mineral_id="stone_crushed",
            mineral_name="Stone (Crushed)",
            usgs_section_name="Stone (Crushed)",
            category="industrial_mineral",
            is_critical_mineral_2025=False,
            notes=None,
        ),
    ]


def test_build_application_records_extracts_usage_sentences() -> None:
    records = build_application_records(SAMPLE_SECTIONS, report_year=2026)

    assert records == [
        MineralApplicationRecord(
            mineral_id="copper",
            application_text="Copper is used in electrical wiring, construction, and renewable energy systems.",
            source_year=2026,
            source_type="usgs_mcs",
            source_section_name="Copper",
            source_page_hint=None,
            extraction_confidence="medium",
        ),
        MineralApplicationRecord(
            mineral_id="rare_earths",
            application_text="Rare earths were used principally in magnets, catalysts, and polishing compounds.",
            source_year=2026,
            source_type="usgs_mcs",
            source_section_name="Rare Earths",
            source_page_hint=None,
            extraction_confidence="medium",
        ),
        MineralApplicationRecord(
            mineral_id="stone_crushed",
            application_text="Crushed stone was used as construction aggregate and road base material.",
            source_year=2026,
            source_type="usgs_mcs",
            source_section_name="Stone (Crushed)",
            source_page_hint=None,
            extraction_confidence="medium",
        ),
    ]


def test_build_application_records_handles_u_s_abbreviations_in_usage_sentence() -> None:
    sections = {
        "Gallium": """Gallium
Events, Trends, and Issues
In the U.S., gallium was used in integrated circuits, optoelectronic components, and photovoltaics.
""",
    }

    records = build_application_records(sections, report_year=2026)

    assert records == [
        MineralApplicationRecord(
            mineral_id="gallium",
            application_text="In the U.S., gallium was used in integrated circuits, optoelectronic components, and photovoltaics.",
            source_year=2026,
            source_type="usgs_mcs",
            source_section_name="Gallium",
            source_page_hint=None,
            extraction_confidence="medium",
        )
    ]


def test_build_application_records_ignores_heading_noise_before_usage_sentence() -> None:
    sections = {
        "Gallium": """Gallium
Uses
Applications
Gallium is used in integrated circuits, optoelectronic components, and photovoltaics.
""",
    }

    records = build_application_records(sections, report_year=2026)

    assert records == [
        MineralApplicationRecord(
            mineral_id="gallium",
            application_text="Gallium is used in integrated circuits, optoelectronic components, and photovoltaics.",
            source_year=2026,
            source_type="usgs_mcs",
            source_section_name="Gallium",
            source_page_hint=None,
            extraction_confidence="medium",
        )
    ]


def test_build_metric_records_extracts_supported_numeric_metrics_only() -> None:
    records = build_metric_records(SAMPLE_SECTIONS, report_year=2026)

    assert records == [
        MineralMetricRecord(
            mineral_id="copper",
            metric_name="net_import_reliance",
            metric_value=45.0,
            metric_unit="pct",
            metric_period="annual",
            metric_year=2025,
            comparison_year=None,
            source_year=2026,
            source_type="usgs_mcs",
            source_section_name="Copper",
            source_page_hint=None,
            notes=None,
        ),
        MineralMetricRecord(
            mineral_id="copper",
            metric_name="price_change_pct_2024_2025",
            metric_value=12.0,
            metric_unit="pct",
            metric_period="annual",
            metric_year=2025,
            comparison_year=2024,
            source_year=2026,
            source_type="usgs_mcs",
            source_section_name="Copper",
            source_page_hint=None,
            notes=None,
        ),
        MineralMetricRecord(
            mineral_id="rare_earths",
            metric_name="price_change_pct_2024_2025",
            metric_value=8.0,
            metric_unit="pct",
            metric_period="annual",
            metric_year=2025,
            comparison_year=2024,
            source_year=2026,
            source_type="usgs_mcs",
            source_section_name="Rare Earths",
            source_page_hint=None,
            notes=None,
        ),
    ]


def test_build_metric_records_handles_percentless_footnoted_net_import_reliance() -> None:
    sections = {
        "Nickel": """Nickel
Events, Trends, and Issues
Net import reliance5 as a percentage of apparent consumption was 45.
""",
    }

    records = build_metric_records(sections, report_year=2026)

    assert records == [
        MineralMetricRecord(
            mineral_id="nickel",
            metric_name="net_import_reliance",
            metric_value=45.0,
            metric_unit="pct",
            metric_period="annual",
            metric_year=2025,
            comparison_year=None,
            source_year=2026,
            source_type="usgs_mcs",
            source_section_name="Nickel",
            source_page_hint=None,
            notes=None,
        )
    ]


def test_build_metric_records_keeps_net_import_year_local_to_sentence() -> None:
    sections = {
        "Graphite": """Graphite
Events, Trends, and Issues
Net import reliance as a percentage of apparent consumption was 45.
In 2023, mine output increased.
""",
    }

    records = build_metric_records(sections, report_year=2026)

    assert records == [
        MineralMetricRecord(
            mineral_id="graphite",
            metric_name="net_import_reliance",
            metric_value=45.0,
            metric_unit="pct",
            metric_period="annual",
            metric_year=2025,
            comparison_year=None,
            source_year=2026,
            source_type="usgs_mcs",
            source_section_name="Graphite",
            source_page_hint=None,
            notes=None,
        )
    ]


def test_build_metric_records_skips_price_change_when_years_are_not_2024_to_2025() -> None:
    sections = {
        "Nickel": """Nickel
Events, Trends, and Issues
The annual average price increased by 12% from 2023 to 2024.
""",
    }

    records = build_metric_records(sections, report_year=2026)

    assert records == []
