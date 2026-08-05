#!/usr/bin/env python3
"""Backfill top_models/market_share history from the Wayback Machine.

openrouter.ai/rankings has captures back to January 2024. This reuses
RankingsSource's static-HTML RSC extraction path directly (the same
fallback the live scraper uses when OpenRouter's ranking APIs are
unavailable) -- Wayback only has the archived page HTML, not the live
JSON APIs, so the HTML path is the only usable one here.

Scoped to top_models + market_share only (per the agreed backfill scope).
categories_programming/context_length/modality_rankings come from
different endpoints (a separate /rankings/programming page and JSON-only
API routes) that weren't verified against Wayback and are out of scope.

Both target datasets key on (week_start_date, entity_id) with no
forward-only assumptions in openrouter_data.storage, so upsert_dataset()
is safe to reuse as-is for backfill.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openrouter_data.exceptions import ValidationError  # noqa: E402
from openrouter_data.models import RunContext, Snapshot  # noqa: E402
from openrouter_data.sources.rankings import MARKET_SHARE_SPEC, TOP_MODELS_SPEC, RankingsSource  # noqa: E402
from openrouter_data.storage import StorageManager  # noqa: E402
from wayback_backfill import WaybackClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_rankings")

RANKINGS_URL = "https://openrouter.ai/rankings"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-date", default="20250101")
    parser.add_argument("--to-date", default=datetime.now(timezone.utc).strftime("%Y%m%d"))
    parser.add_argument("--request-delay", type=float, default=1.5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    client = WaybackClient(request_delay_seconds=args.request_delay)
    storage = StorageManager(ROOT)
    source = RankingsSource()

    captures = client.list_snapshots(RANKINGS_URL, from_date=args.from_date, to_date=args.to_date)
    captures.sort(key=lambda c: c.timestamp)
    if args.limit:
        captures = captures[-args.limit :]
    logger.info("Found %d captures of %s", len(captures), RANKINGS_URL)

    top_models_records, market_share_records = [], []
    weeks_seen: dict[str, set[str]] = {"top_models": set(), "market_share": set()}
    failed = 0
    for index, capture in enumerate(captures, start=1):
        try:
            html = client.fetch_capture(capture)
            context = RunContext(
                run_id=f"wayback-rankings-{capture.timestamp}-{uuid4().hex[:8]}",
                scraped_at=datetime.strptime(capture.timestamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc),
            )

            top_chart = source._find_chart(html, predicate=lambda c: c.get("forecast") == "forecast-1w", label="top_models")
            market_chart = source._find_chart(html, predicate=source._looks_like_market_share_chart, label="market_share")

            if top_chart is not None:
                try:
                    records = source._records_from_chart(top_chart, TOP_MODELS_SPEC, context)
                    top_models_records.extend(records)
                    weeks_seen["top_models"].update(r.week_start_date for r in records if r.week_start_date)
                except ValidationError as exc:
                    logger.debug("[%s] top_models: %s", capture.timestamp, exc)
            if market_chart is not None:
                try:
                    records = source._records_from_chart(market_chart, MARKET_SHARE_SPEC, context)
                    market_share_records.extend(records)
                    weeks_seen["market_share"].update(r.week_start_date for r in records if r.week_start_date)
                except ValidationError as exc:
                    logger.debug("[%s] market_share: %s", capture.timestamp, exc)

            if top_chart is None and market_chart is None:
                logger.warning("[%d/%d] capture %s: neither chart found", index, len(captures), capture.timestamp)
                failed += 1
            else:
                logger.info("[%d/%d] capture %s ok (top=%s market=%s)", index, len(captures), capture.timestamp,
                            top_chart is not None, market_chart is not None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%d/%d] capture %s failed: %s", index, len(captures), capture.timestamp, exc)
            failed += 1

    logger.info(
        "top_models: %d records, %d distinct weeks; market_share: %d records, %d distinct weeks; %d/%d captures unusable",
        len(top_models_records), len(weeks_seen["top_models"]),
        len(market_share_records), len(weeks_seen["market_share"]),
        failed, len(captures),
    )

    if args.dry_run:
        logger.info("Dry run: not writing.")
        return 0

    if top_models_records:
        merged = storage.upsert_dataset("top_models", top_models_records)
        logger.info("Wrote top_models: %d total rows now on disk", len(merged))
    if market_share_records:
        merged = storage.upsert_dataset("market_share", market_share_records)
        logger.info("Wrote market_share: %d total rows now on disk", len(merged))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
