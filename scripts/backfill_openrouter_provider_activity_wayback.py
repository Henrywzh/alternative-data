#!/usr/bin/env python3
"""Backfill provider_daily_activity history from the Wayback Machine.

Each openrouter.ai/{provider} page embeds a stacked daily-token chart with a
~91-day rolling window in its Next.js RSC payload (same shape the live
scraper already parses via ProviderActivitySource._find_activity_chart). A
handful of well-spaced captures per provider is enough to stitch continuous
daily coverage, since consecutive captures' 91-day windows overlap.

Unlike the pricing dataset, openrouter_data.storage.StorageManager has no
"current catalog" file and no unchanged-row filter for this dataset -- its
natural key already includes usage_date, so upsert_dataset() is safe to
reuse as-is for backfill.

Records are appended provider-by-provider, oldest capture first, so that
when two captures' 91-day windows overlap on the same day the more recent
capture's value wins during drop_duplicates(keep="last").
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

from openrouter_data.models import RunContext, Snapshot  # noqa: E402
from openrouter_data.sources.provider_activity import (  # noqa: E402
    PROVIDER_ACTIVITY_DATASET_ID,
    PROVIDER_SLUGS,
    ProviderActivitySource,
)
from openrouter_data.storage import StorageManager  # noqa: E402
from wayback_backfill import WaybackClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_provider_activity")

BASE_URL = "https://openrouter.ai"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-date", default="20250101")
    parser.add_argument("--to-date", default=datetime.now(timezone.utc).strftime("%Y%m%d"))
    parser.add_argument("--request-delay", type=float, default=1.5)
    parser.add_argument("--providers", nargs="*", default=None, help="Subset of provider slugs (default: all)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit-per-provider", type=int, default=0)
    args = parser.parse_args()

    client = WaybackClient(request_delay_seconds=args.request_delay)
    storage = StorageManager(ROOT)
    source = ProviderActivitySource()

    slugs = {k: v for k, v in PROVIDER_SLUGS.items() if not args.providers or k in args.providers}

    per_provider_summary: dict[str, dict] = {}
    for slug, display_name in slugs.items():
        url = f"{BASE_URL}/{slug}"
        try:
            captures = client.list_snapshots(url, from_date=args.from_date, to_date=args.to_date)
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] could not list captures, skipping provider: %s", slug, exc)
            per_provider_summary[slug] = {"error": str(exc)}
            continue
        captures.sort(key=lambda c: c.timestamp)  # oldest first, so "last wins" on overlaps == freshest capture
        if args.limit_per_provider:
            captures = captures[-args.limit_per_provider :]
        logger.info("[%s] %d captures found", slug, len(captures))

        provider_records = []
        dates_seen: set[str] = set()
        failed = 0
        for capture in captures:
            try:
                body = client.fetch_capture(capture)
                snapshot = Snapshot(name=f"provider_{slug}", source_url=capture.original, body=body)
                context = RunContext(
                    run_id=f"wayback-{slug}-{capture.timestamp}-{uuid4().hex[:8]}",
                    scraped_at=datetime.strptime(capture.timestamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc),
                )
                extracted = source.extract([snapshot], context)
                records = extracted.get(PROVIDER_ACTIVITY_DATASET_ID, [])
                if not records:
                    logger.warning("[%s] capture %s: no activity chart found", slug, capture.timestamp)
                    failed += 1
                    continue
                provider_records.extend(records)
                dates_seen.update(r.usage_date for r in records if r.usage_date)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] capture %s failed: %s", slug, capture.timestamp, exc)
                failed += 1

        per_provider_summary[slug] = {
            "captures": len(captures),
            "failed": failed,
            "records": len(provider_records),
            "distinct_days": len(dates_seen),
            "min_date": min(dates_seen) if dates_seen else None,
            "max_date": max(dates_seen) if dates_seen else None,
        }
        logger.info("[%s] -> %d records, %d distinct days (%s -> %s)", slug, len(provider_records), len(dates_seen),
                    per_provider_summary[slug]["min_date"], per_provider_summary[slug]["max_date"])

        if not provider_records:
            continue
        if args.dry_run:
            logger.info("[%s] dry run: not writing %d records", slug, len(provider_records))
            continue

        # Write after each provider, not once at the end -- a later provider's
        # transient Wayback failure must not lose an earlier provider's data.
        merged = storage.upsert_dataset("provider_daily_activity", provider_records)
        logger.info("[%s] wrote to disk; provider_daily_activity now has %d total rows", slug, len(merged))

    logger.info("Summary: %s", per_provider_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
