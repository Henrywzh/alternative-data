from __future__ import annotations

import re

from minerals_usgs_data.models import (
    MineralApplicationRecord,
    MineralMasterRecord,
    MineralMetricRecord,
)
from minerals_usgs_data.sources.config import NON_MINERAL_CONTENTS_HEADINGS

CONTENTS_LINE_RE = re.compile(r"^(?P<name>[A-Za-z0-9 ,()\-—]+)\.{3,}\s+\d+$")
MINERAL_CONTENTS_MARKER = "Mineral Commodities:"
CRITICAL_MINERALS_MARKER_RE = re.compile(r"Table 6—The U\.S\. Final \d{4} Critical Minerals List")
APPLICATION_SENTENCE_RE = re.compile(
    r"\b(?:is|are|was|were)\s+used\b|\bused\s+principally\b",
    re.IGNORECASE,
)
NET_IMPORT_RELIANCE_RE = re.compile(
    r"net import reliance\d*.*?(?:was|estimated to be|was estimated to be)?\s*(\d+(?:\.\d+)?)%?\b(?:.*?\b(?:in|for)\s+(\d{4}))?",
    re.IGNORECASE,
)
PRICE_CHANGE_RE = re.compile(
    r"(?:price|producer price).*?(increased|decreased)\s+by\s+(\d+(?:\.\d+)?)%\s+from\s+(\d{4})\s+to\s+(\d{4})",
    re.IGNORECASE | re.DOTALL,
)
RARE_EARTH_CATEGORY_TOKENS = ("rare earth",)
INDUSTRIAL_MINERAL_CATEGORY_TOKENS = (
    "abrasive",
    "boron",
    "cement",
    "clay",
    "feldspar",
    "fluorspar",
    "gemstone",
    "gypsum",
    "helium",
    "lime",
    "mica",
    "peat",
    "perlite",
    "phosphate",
    "potash",
    "pumice",
    "salt",
    "sand",
    "silica",
    "soda ash",
    "stone",
    "sulfur",
    "talc",
    "vermiculite",
    "zeolite",
)


def extract_contents_section_names(report_text: str) -> list[str]:
    names: list[str] = []
    marker_index = report_text.find(MINERAL_CONTENTS_MARKER)
    if marker_index == -1:
        return names

    mineral_contents_text = report_text[marker_index + len(MINERAL_CONTENTS_MARKER) :]
    mineral_contents_text = mineral_contents_text.split("\f", 1)[0]
    for raw_line in mineral_contents_text.splitlines():
        line = raw_line.strip()
        match = CONTENTS_LINE_RE.match(line)
        if match:
            name = match.group("name").strip()
            if name not in NON_MINERAL_CONTENTS_HEADINGS:
                names.append(name)
    return names


def normalize_mineral_id(section_name: str) -> str:
    normalized = section_name.lower().replace("&", "and")
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")


def split_mineral_sections(report_text: str, section_names: list[str]) -> dict[str, str]:
    sections: dict[str, str] = {}
    lines = report_text.splitlines()
    line_offsets: list[int] = []
    offset = 0
    for line in lines:
        line_offsets.append(offset)
        offset += len(line) + 1

    section_names_set = set(section_names)
    chosen_positions: dict[str, tuple[int, int]] = {}
    for line_index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if line not in section_names_set:
            continue

        next_section_line = len(lines)
        for next_line_index in range(line_index + 1, len(lines)):
            if lines[next_line_index].strip() in section_names_set:
                next_section_line = next_line_index
                break

        start_offset = line_offsets[line_index]
        current = chosen_positions.get(line)
        if current is None or (next_section_line - line_index) > current[1]:
            chosen_positions[line] = (start_offset, next_section_line - line_index)

    heading_positions = {name: position for name, (position, _) in chosen_positions.items()}
    ordered_names = [name for name in section_names if name in heading_positions]
    for index, section_name in enumerate(ordered_names):
        start = heading_positions[section_name]
        end = len(report_text)
        for next_name in ordered_names[index + 1 :]:
            next_start = heading_positions[next_name]
            if next_start > start:
                end = next_start
                break
        sections[section_name] = report_text[start:end].strip()
    return sections


def extract_critical_mineral_names(report_text: str) -> set[str]:
    marker_match = CRITICAL_MINERALS_MARKER_RE.search(report_text)
    if marker_match is None:
        return set()

    critical_names: set[str] = set()
    for raw_line in report_text[marker_match.end() :].splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if critical_names and re.match(r"^(Table|Figure|Appendix)\b", line):
            break
        if not _looks_like_mineral_name(line):
            continue
        critical_names.update(_split_mineral_name_line(line))
    return critical_names


def build_master_records(
    section_names: list[str], critical_mineral_names: set[str]
) -> list[MineralMasterRecord]:
    return [
        MineralMasterRecord(
            mineral_id=normalize_mineral_id(section_name),
            mineral_name=section_name,
            usgs_section_name=section_name,
            category=_infer_category(section_name),
            is_critical_mineral_2025=section_name in critical_mineral_names,
            notes=None,
        )
        for section_name in section_names
    ]


def build_application_records(
    sections: dict[str, str], report_year: int
) -> list[MineralApplicationRecord]:
    records: list[MineralApplicationRecord] = []
    for section_name, section_text in sections.items():
        application_sentence = _extract_application_sentence(section_text)
        if application_sentence is None:
            continue
        records.append(
            MineralApplicationRecord(
                mineral_id=normalize_mineral_id(section_name),
                application_text=application_sentence,
                source_year=report_year,
                source_type="usgs_mcs",
                source_section_name=section_name,
                source_page_hint=None,
                extraction_confidence="medium",
            )
        )
    return records


def build_metric_records(sections: dict[str, str], report_year: int) -> list[MineralMetricRecord]:
    records: list[MineralMetricRecord] = []
    default_metric_year = report_year - 1
    for section_name, section_text in sections.items():
        mineral_id = normalize_mineral_id(section_name)
        for sentence in _split_sentences(_strip_section_heading(section_text)):
            net_import_match = NET_IMPORT_RELIANCE_RE.search(sentence)
            if net_import_match is not None:
                metric_year = int(net_import_match.group(2) or default_metric_year)
                records.append(
                    MineralMetricRecord(
                        mineral_id=mineral_id,
                        metric_name="net_import_reliance",
                        metric_value=float(net_import_match.group(1)),
                        metric_unit="pct",
                        metric_period="annual",
                        metric_year=metric_year,
                        comparison_year=None,
                        source_year=report_year,
                        source_type="usgs_mcs",
                        source_section_name=section_name,
                        source_page_hint=None,
                        notes=None,
                    )
                )
                break

        price_change_match = PRICE_CHANGE_RE.search(section_text)
        if price_change_match is not None:
            comparison_year = int(price_change_match.group(3))
            metric_year = int(price_change_match.group(4))
            if comparison_year == 2024 and metric_year == 2025:
                direction = price_change_match.group(1).lower()
                metric_value = float(price_change_match.group(2))
                if direction == "decreased":
                    metric_value *= -1.0
                records.append(
                    MineralMetricRecord(
                        mineral_id=mineral_id,
                        metric_name="price_change_pct_2024_2025",
                        metric_value=metric_value,
                        metric_unit="pct",
                        metric_period="annual",
                        metric_year=metric_year,
                        comparison_year=comparison_year,
                        source_year=report_year,
                        source_type="usgs_mcs",
                        source_section_name=section_name,
                        source_page_hint=None,
                        notes=None,
                    )
                )
    return records


def _infer_category(section_name: str) -> str:
    normalized_name = section_name.lower()
    if any(token in normalized_name for token in RARE_EARTH_CATEGORY_TOKENS):
        return "rare_earth"
    if any(token in normalized_name for token in INDUSTRIAL_MINERAL_CATEGORY_TOKENS):
        return "industrial_mineral"
    return "metal"


def _extract_application_sentence(section_text: str) -> str | None:
    body_text = _strip_section_heading(section_text)
    for sentence in _split_sentences(body_text):
        normalized_sentence = sentence.strip()
        if not normalized_sentence:
            continue
        if APPLICATION_SENTENCE_RE.search(normalized_sentence):
            return normalized_sentence
    return None


def _strip_section_heading(section_text: str) -> str:
    lines = [line.strip() for line in section_text.splitlines() if line.strip()]
    if not lines:
        return ""
    if len(lines) >= 2 and lines[1] == "Events, Trends, and Issues":
        return "\n".join(lines[2:])
    return "\n".join(lines[1:])


def _looks_like_mineral_name(line: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z ,()&\-]+", line))


def _split_mineral_name_line(line: str) -> list[str]:
    return [line]


def _split_sentences(text: str) -> list[str]:
    normalized_text = text.replace("\n", " ").strip()
    if not normalized_text:
        return []

    protected_text = normalized_text.replace("U.S.", "U<DOT>S<DOT>")
    sentences = re.split(r"(?<=[.?!])\s+", protected_text)
    return [sentence.replace("U<DOT>S<DOT>", "U.S.") for sentence in sentences]
