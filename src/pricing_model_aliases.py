from __future__ import annotations

import re


SUPPORTED_TAG_SUFFIX_RE = re.compile(r":(free|beta|alpha|online|chat|search)$")
DATE_SUFFIX_RE = re.compile(
    r"-(\d{8}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}|(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))$"
)
ANTHROPIC_VERSION_RE = re.compile(r"(anthropic/claude-)(\d)-(\d)(?=[-/]|$)")
ANTHROPIC_ORDER_RE = re.compile(r"anthropic/claude-([\d.]+)-(opus|sonnet|haiku)(?=$|[-/])")


def clean_slug(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "<na>"}:
        return None
    return text


def derive_provider_prefix(value: object) -> str | None:
    slug = clean_slug(value)
    if slug is None or "/" not in slug:
        return None
    return slug.split("/", 1)[0]


def strip_supported_tag(value: object) -> str | None:
    slug = clean_slug(value)
    if slug is None:
        return None
    return SUPPORTED_TAG_SUFFIX_RE.sub("", slug)


def strip_date_suffix(value: object) -> str | None:
    slug = clean_slug(value)
    if slug is None:
        return None
    return DATE_SUFFIX_RE.sub("", slug)


def normalize_anthropic_punctuation(value: object) -> str | None:
    slug = clean_slug(value)
    if slug is None or not slug.startswith("anthropic/"):
        return slug
    return ANTHROPIC_VERSION_RE.sub(r"\1\2.\3", slug)


def reorder_anthropic_variant(value: object) -> str | None:
    slug = clean_slug(value)
    if slug is None or not slug.startswith("anthropic/"):
        return None
    match = ANTHROPIC_ORDER_RE.match(slug)
    if not match:
        return None
    return f"anthropic/claude-{match.group(2)}-{match.group(1)}"


def generate_candidate_aliases(value: object) -> list[str]:
    slug = clean_slug(value)
    if slug is None:
        return []

    aliases: list[str] = []

    def add(candidate: str | None) -> None:
        if candidate and candidate not in aliases:
            aliases.append(candidate)

    stripped_tag = strip_supported_tag(slug)
    stripped_date = strip_date_suffix(stripped_tag)
    anthropic_punct = normalize_anthropic_punctuation(stripped_date)
    anthropic_reordered = reorder_anthropic_variant(anthropic_punct)

    add(slug)
    add(stripped_tag)
    add(stripped_date)
    add(anthropic_punct)
    add(anthropic_reordered)

    if anthropic_punct and anthropic_punct.startswith("qwen/qwen"):
        if "plus" in anthropic_punct:
            add("qwen/qwen-plus")
        if "max" in anthropic_punct:
            add("qwen/qwen-max")

    return aliases
