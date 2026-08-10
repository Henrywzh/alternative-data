"""Wikipedia airline fleet-table snapshots for the fleet/utilization bridge.

The free, stable Wikipedia airline pages carry a fleet table with aircraft
type, in-service and on-order counts and seat configuration.  The table is a
dated snapshot (Wikipedia revision ID is retained and mapped to a revision
timestamp through the MediaWiki API when available), which makes the layer
point-in-time-usable as long as every row keeps its snapshot date.  It is a
complement to the official-report fleet disclosures, not a replacement:

* The official drivers layer carries issuer-disclosed fleet totals (e.g.
  Air China FY2025 fleet_total); this layer adds the composition by type.
* Cathay's Wikipedia fleet table is an image with no parseable rows, so
  Cathay is intentionally excluded and stays on official disclosures.
* Hainan Airlines Holdings is a group consolidation; the page covers the
  Hainan Airlines operating carrier and the row scope is labelled as such.

Wikipedia content is community-maintained and can lag or disagree with
issuer filings; the layer is labelled ``secondary_aggregator`` and is never
used to override an official fleet total.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    NORMALIZED_DIR,
    WIKIPEDIA_AIRLINE_FLEET_PAGES,
    WIKIPEDIA_API_URL,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_fleet_wikipedia_snapshot.csv"
DATASET_ID = "airline_fleet_wikipedia_snapshot"

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "aircraft_type",
    "in_service",
    "on_order",
    "total",
    "seats_capacity",
    "fleet_scope",
    "snapshot_date",
    "revision_id",
    "revision_timestamp",
    "revision_timestamp_status",
    "source_url",
    "point_in_time_status",
    "source_quality",
    "source_note",
    "raw_snapshot_path",
    "retrieved_at",
]

# Aircraft-type patterns that identify fleet-table rows; the first cell is
# the type (possibly with a linking title), the following cells carry counts.
AIRCRAFT_PATTERN = re.compile(
    r"(?:Airbus\s+A3\d{2}(?:-?\d{3})?|Boeing\s+B\d{3}(?:-\d{3,4})?|"
    r"Comac\s+C9\d{2}|Comac\s+ARJ21|C919|C909|ARJ21|"
    r"A320|A321|A330|A350|B737|B747|B777|B787)",
    re.IGNORECASE,
)


def _get(url: str) -> requests.Response:
    response = requests.get(
        url,
        headers=DEFAULT_HEADERS,
        timeout=max(DEFAULT_TIMEOUT, 30),
    )
    response.raise_for_status()
    return response


def _revision_timestamp(revision_id: str) -> tuple[str | None, str]:
    """Map a Wikipedia revision ID to its timestamp via the MediaWiki API."""
    try:
        response = requests.get(
            WIKIPEDIA_API_URL,
            params={
                "action": "query",
                "prop": "revisions",
                "revids": revision_id,
                "rvprop": "timestamp",
                "format": "json",
                "formatversion": "2",
            },
            headers=DEFAULT_HEADERS,
            timeout=max(DEFAULT_TIMEOUT, 30),
        )
        response.raise_for_status()
        payload = response.json()
        pages = payload.get("query", {}).get("pages", [])
        if pages and pages[0].get("revisions"):
            timestamp = pages[0]["revisions"][0].get("timestamp")
            if timestamp:
                return timestamp, "mediawiki_revision_timestamp"
    except Exception as exc:
        logger.warning("Wikipedia revision lookup failed for %s: %s", revision_id, exc)
    return None, "revision_timestamp_unavailable"


def _parse_fleet_table(html: str, company: str) -> list[dict[str, Any]]:
    """Parse the aircraft fleet table from a Wikipedia airline page."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    for table in soup.find_all("table"):
        caption = table.find("caption")
        caption_text = caption.get_text(" ", strip=True) if caption else ""
        header_text = table.get_text(" ", strip=True)[:200]
        is_fleet_table = (
            "fleet" in caption_text.lower()
            or "fleet" in header_text.lower()
            or any(
                cell.get_text(" ", strip=True).lower() in ("in service", "orders")
                for cell in table.find_all(["th", "td"])[:20]
            )
        )
        if not is_fleet_table:
            continue
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            if not cells:
                continue
            type_match = AIRCRAFT_PATTERN.search(cells[0])
            if not type_match:
                continue
            aircraft_type = re.sub(r"\s+", " ", cells[0])
            # Fleet tables typically order: type | in service | on order |
            # seats (+ optional notes).  Column positions vary, so capture by
            # header hint first, then fall back to position.
            headers = [
                th.get_text(" ", strip=True).lower()
                for th in tr.find_all("th")
            ] or [
                th.get_text(" ", strip=True).lower()
                for th in table.find("tr").find_all(["th", "td"])
            ]
            in_service = on_order = None
            seats = None
            if "in service" in headers and "orders" in headers:
                h = {name: i for i, name in enumerate(headers)}
                if "in service" in h and len(cells) > h["in service"]:
                    in_service = _count(cells[h["in service"]])
                if "orders" in h and len(cells) > h["orders"]:
                    on_order = _count(cells[h["orders"]])
            else:
                numeric = [_count(c) for c in cells[1:]]
                numeric = [v for v in numeric if v is not None]
                if len(numeric) >= 1:
                    in_service = numeric[0]
                if len(numeric) >= 2:
                    on_order = numeric[1]
                if len(numeric) >= 4:
                    seats = f"{numeric[2]}-{numeric[3]}"
                elif len(numeric) >= 3:
                    seats = str(numeric[2])
            # Retired-fleet rows: the "orders" cell carries the introduction
            # year (e.g. A340-300 with in-service 6 / orders 1997), and the
            # seats/notes cells carry the retirement year.  A 4-digit year in
            # a count position marks a historical row, not an on-order count.
            if _is_year(on_order) or (in_service is None and _seats_are_year(seats)):
                continue
            total = None
            if in_service is not None and on_order is not None:
                total = in_service + on_order
            rows.append(
                {
                    "aircraft_type": aircraft_type,
                    "in_service": in_service,
                    "on_order": on_order,
                    "total": total,
                    "seats_capacity": seats,
                }
            )
    return rows


def _is_year(value: int | None) -> bool:
    """1950-2035 covers introduction/retirement years in Wikipedia retired
    fleet rows; real on-order counts never fall in that range for these
    carriers' current narrowbody/widebody fleets."""
    return value is not None and 1950 <= value <= 2035


def _seats_are_year(seats: str | None) -> bool:
    if not seats:
        return False
    digits = re.sub(r"[^\d]", "", seats)
    if not digits:
        return False
    value = int(digits[:4])
    return 1950 <= value <= 2035


def _count(cell: str) -> int | None:
    if not cell or cell in ("—", "–", "-", "", "TBA", "TBD"):
        return None
    match = re.search(r"(\d[\d,]*)(?:\[[\d\s]+\])?", cell)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def fetch_airline_fleet_wikipedia() -> pd.DataFrame:
    """Fetch Wikipedia fleet snapshots for the mainland carriers and persist."""
    retrieved = datetime.now(timezone.utc).isoformat()
    snapshot_date = datetime.now(timezone.utc).date().isoformat()
    all_rows: list[dict[str, Any]] = []
    for company, url in WIKIPEDIA_AIRLINE_FLEET_PAGES.items():
        try:
            response = _get(url)
        except Exception as exc:
            logger.warning("Wikipedia fleet fetch failed for %s: %s", company, exc)
            continue
        raw_path = save_raw_snapshot(
            f"airline_fleet_wikipedia_{company.lower().replace(' ', '_')}",
            response.content,
            file_ext="html",
            source_url=url,
        )
        html = response.content.decode("utf-8", errors="ignore")
        revision_match = re.search(r'"wgRevisionId":(\d+)', html)
        revision_id = revision_match.group(1) if revision_match else None
        revision_ts, revision_ts_status = (
            _revision_timestamp(revision_id) if revision_id else (None, "no_revision_id")
        )
        fleet_rows = _parse_fleet_table(html, company)
        for row in fleet_rows:
            all_rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "company": company,
                    "aircraft_type": row["aircraft_type"],
                    "in_service": row["in_service"],
                    "on_order": row["on_order"],
                    "total": row["total"],
                    "seats_capacity": row["seats_capacity"],
                    "fleet_scope": (
                        "operating_carrier"
                        if company == "Hainan Airlines"
                        else "group_operating_carriers"
                    ),
                    "snapshot_date": snapshot_date,
                    "revision_id": revision_id,
                    "revision_timestamp": revision_ts,
                    "revision_timestamp_status": revision_ts_status,
                    "source_url": url,
                    "point_in_time_status": "snapshot_observation",
                    "source_quality": "wikipedia_secondary_aggregator",
                    "source_note": (
                        "Wikipedia airline fleet table snapshot; community-"
                        "maintained and may lag issuer filings.  Composition "
                        "layer only - never overrides an official fleet "
                        "total.  Hainan row is the operating carrier, not "
                        "the group consolidation."
                    ),
                    "raw_snapshot_path": str(raw_path),
                    "retrieved_at": retrieved,
                }
            )
    if not all_rows:
        raise ValueError("No Wikipedia fleet rows parsed for any airline")
    result = pd.DataFrame(all_rows, columns=OUTPUT_COLUMNS)
    result = result.drop_duplicates(
        subset=["company", "aircraft_type", "snapshot_date"], keep="last"
    ).sort_values(["company", "aircraft_type"]).reset_index(drop=True)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "fetch_airline_fleet_wikipedia",
    "source_path",
]
