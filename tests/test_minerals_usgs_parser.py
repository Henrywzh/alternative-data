from minerals_usgs_data.sources.parser import (
    extract_contents_section_names,
    normalize_mineral_id,
    split_mineral_sections,
)


SAMPLE_REPORT_TEXT = """
CONTENTS
Table 1—U.S. Mineral Industry Trends .......................... 10
Table 2—U.S. Mineral-Related Economic Trends ......... 10
Figure 2—2025 U.S. Net Import Reliance ...................... 11
Appendix A—Abbreviations and Units of Measure ...... 216

Mineral Commodities:
Abrasives (Manufactured) ............................................ 38
Aluminum ..................................................................... 40
Copper ......................................................................... 72
Rare Earths .................................................................... 152
Zinc ........................................................................... 212
\f
MINERAL COMMODITY SUMMARIES 2026
Abrasives
Aluminum
Copper
Rare Earths
Zinc

Copper
Events, Trends, and Issues
Copper is used in electrical applications and renewable energy systems.

Rare Earths
Events, Trends, and Issues
Rare earths were used in magnets and catalysts.
"""


def test_extract_contents_section_names_reads_minerals_only() -> None:
    names = extract_contents_section_names(SAMPLE_REPORT_TEXT)
    assert names == [
        "Abrasives (Manufactured)",
        "Aluminum",
        "Copper",
        "Rare Earths",
        "Zinc",
    ]


def test_normalize_mineral_id_handles_multiword_titles() -> None:
    assert normalize_mineral_id("Rare Earths") == "rare_earths"
    assert normalize_mineral_id("Bauxite and Alumina") == "bauxite_and_alumina"


def test_split_mineral_sections_maps_text_by_heading() -> None:
    sections = split_mineral_sections(SAMPLE_REPORT_TEXT, ["Copper", "Rare Earths"])
    assert "electrical applications" in sections["Copper"]
    assert "magnets and catalysts" in sections["Rare Earths"]
    assert sections["Copper"].startswith("Copper\nEvents, Trends, and Issues")
    assert not sections["Copper"].startswith("MINERAL COMMODITY SUMMARIES 2026")
