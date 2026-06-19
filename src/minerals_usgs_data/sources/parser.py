from __future__ import annotations

import re

from minerals_usgs_data.sources.config import NON_MINERAL_CONTENTS_HEADINGS

CONTENTS_LINE_RE = re.compile(r"^(?P<name>[A-Za-z0-9 ,()\-—]+)\.{3,}\s+\d+$")
MINERAL_CONTENTS_MARKER = "Mineral Commodities:"


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
