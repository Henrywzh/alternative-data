"""Archive non-focus Control Tower rows without deleting registry lineage."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import tempfile


DEFAULT_FOCUS_ENTITIES = frozenset(
    {"ALIBABA", "TENCENT", "BAIDU", "KUAISHOU", "BILIBILI", "BYTEDANCE"}
)
DEFAULT_ARCHIVE_DATE = "2026-08-15"


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path} has no CSV header")
        return list(reader.fieldnames), list(reader)


def _write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def archive_to_focus(
    registry_root: Path,
    event_root: Path,
    *,
    archive_date: str = DEFAULT_ARCHIVE_DATE,
    focus_entities: frozenset[str] = DEFAULT_FOCUS_ENTITIES,
) -> dict[str, int]:
    """Mark non-focus rows archived while preserving every source row and interval.

    ``active_to`` is intentionally preserved: future thesis observations can
    still reference an archived entity, while ``active_status`` and the app's
    Stage 1 focus control determine default visibility.
    """

    if not archive_date.strip():
        raise ValueError("archive_date must not be blank")

    entity_path = registry_root / "entities.csv"
    listing_path = registry_root / "listings.csv"
    membership_path = registry_root / "basket_memberships.csv"
    event_link_path = event_root / "event_links.csv"

    entity_fields, entities = _read_rows(entity_path)
    for row in entities:
        entity_id = row["entity_id"].strip()
        if entity_id in focus_entities:
            row["active_status"] = "active"
            row["active_to"] = ""
        else:
            row["active_status"] = "archived"
    _write_rows(entity_path, entity_fields, entities)

    listing_fields, listings = _read_rows(listing_path)
    for row in listings:
        if row["entity_id"].strip() in focus_entities:
            row["listing_status"] = "active"
        else:
            row["listing_status"] = "archived"
    _write_rows(listing_path, listing_fields, listings)

    membership_fields, memberships = _read_rows(membership_path)
    # Membership lineage remains available for deliberate legacy views.
    _write_rows(membership_path, membership_fields, memberships)

    event_fields, event_links = _read_rows(event_link_path)
    # Event lineage remains available even when its entity is archived.
    _write_rows(event_link_path, event_fields, event_links)

    return {
        "entities_archived": sum(row["active_status"] == "archived" for row in entities),
        "listings_archived": sum(row["listing_status"] == "archived" for row in listings),
        "memberships_preserved": len(memberships),
        "event_links_preserved": len(event_links),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-root", type=Path, required=True)
    parser.add_argument("--event-root", type=Path, required=True)
    parser.add_argument("--archive-date", default=DEFAULT_ARCHIVE_DATE)
    args = parser.parse_args()
    summary = archive_to_focus(
        args.registry_root,
        args.event_root,
        archive_date=args.archive_date,
    )
    for key, value in summary.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
