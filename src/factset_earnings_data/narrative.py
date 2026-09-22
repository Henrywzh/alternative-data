"""Parse FactSet Insight article Q&A, typical history, and sector breadth."""

from __future__ import annotations

import json
import re
from typing import Any


_WORD_COUNTS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
}
_YEAR_COUNTS = {
    "five": 5,
    "5": 5,
    "ten": 10,
    "10": 10,
    "fifteen": 15,
    "15": 15,
    "twenty": 20,
    "20": 20,
}
_QUESTION_RE = re.compile(r"([^?]{12,280}\?)")
_ANSWER_RE = re.compile(r"The answer is (yes|no)\.\s*(.*)", re.IGNORECASE | re.DOTALL)
_TYPICAL_RE = re.compile(
    r"past\s+(five|5|ten|10|fifteen|15|twenty|20)\s+years"
    r"[,]?\s*(?:\(\s*\d+\s+quarters\s*\))?[,]?\s+"
    r"the average\s+(decline|increase)\s+in the bottom-up EPS estimate\s+"
    r"during the\s+(first two months|first month)\s+of a quarter has(?: also)? been\s+"
    r"([0-9]+(?:\.[0-9]+)?)%",
    re.IGNORECASE,
)
_WINDOW_RE = re.compile(
    r"from\s+([A-Z][a-z]+\s+\d{1,2})\s+to\s+([A-Z][a-z]+\s+\d{1,2})",
)
_UP_RE = re.compile(
    r"([A-Za-z]+|\d+)\s+of the eleven sectors witnessed an increase"
    r".*?led by the\s+(.+?)\s+sectors?\.",
    re.IGNORECASE | re.DOTALL,
)
_DOWN_RE = re.compile(
    r"([A-Za-z]+|\d+)\s+sectors recorded a decrease"
    r".*?led by the\s+(.+?)\s+sectors?\.",
    re.IGNORECASE | re.DOTALL,
)
_SECTOR_CHUNK_RE = re.compile(
    r"(?:the\s+)?([A-Za-z][A-Za-z ]+?)(?:\s*\([+-]?[0-9.]+%\))?$",
)
_DISCLAIMER = "This blog post is for informational purposes only"


def _clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _article_body(text: str) -> str:
    body = text.split(_DISCLAIMER, 1)[0]
    return _clean_space(body)


def _parse_count(token: str) -> int | None:
    raw = str(token or "").strip().lower()
    if raw.isdigit():
        return int(raw)
    return _WORD_COUNTS.get(raw)


def _parse_leaders(chunk: str) -> list[str]:
    leaders: list[str] = []
    for part in re.split(r"\s+and\s+", str(chunk or ""), flags=re.IGNORECASE):
        match = _SECTOR_CHUNK_RE.search(part.strip().rstrip("."))
        if not match:
            continue
        name = match.group(1).strip()
        if name.lower().startswith("the "):
            name = name[4:].strip()
        if name:
            leaders.append(name)
    return leaders


def parse_article_narrative(text: str) -> dict[str, Any] | None:
    """Extract FactSet's own question, yes/no, typical history and breadth."""
    body = _article_body(text)
    if not body:
        return None
    answer_match = _ANSWER_RE.search(body)
    if not answer_match:
        return None
    prefix = body[: answer_match.start()]
    questions = _QUESTION_RE.findall(prefix)
    if not questions:
        return None
    question_text = _clean_space(questions[-1])
    given = question_text.lower().find("given ")
    if given > 0:
        question_text = question_text[given:]
        question_text = question_text[0].upper() + question_text[1:]
    answer = answer_match.group(1).lower()
    rest = _clean_space(answer_match.group(2) or "")
    first_sentence = rest.split(". ", 1)[0].strip()
    if first_sentence and not first_sentence.endswith("."):
        first_sentence += "."
    answer_sentence = _clean_space(f"The answer is {answer}. {first_sentence}")
    typical: list[dict[str, Any]] = []
    seen_years: set[int] = set()
    for match in _TYPICAL_RE.finditer(body):
        years = _YEAR_COUNTS.get(match.group(1).lower())
        if years is None or years in seen_years:
            continue
        direction = match.group(2).lower()
        window = match.group(3).lower()
        value = abs(float(match.group(4)))
        typical.append(
            {
                "years": years,
                "window": window,
                "value": -value if direction == "decline" else value,
            }
        )
        seen_years.add(years)
    typical.sort(key=lambda item: item["years"])
    window_match = _WINDOW_RE.search(body)
    window = (
        f"{window_match.group(1)} to {window_match.group(2)}"
        if window_match
        else None
    )
    up_match = _UP_RE.search(body)
    down_match = _DOWN_RE.search(body)
    breadth: dict[str, Any] | None = None
    if up_match or down_match:
        breadth = {
            "up_count": _parse_count(up_match.group(1)) if up_match else None,
            "down_count": _parse_count(down_match.group(1)) if down_match else None,
            "led_up": _parse_leaders(up_match.group(2)) if up_match else [],
            "led_down": _parse_leaders(down_match.group(2)) if down_match else [],
        }
    return {
        "question": question_text,
        "answer": answer,
        "answer_sentence": answer_sentence,
        "window": window,
        "typical": typical,
        "breadth": breadth,
    }


def narrative_to_json(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
