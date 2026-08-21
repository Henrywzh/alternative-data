#!/usr/bin/env python3
"""Stage and optionally upsert serving-provider history from Wayback.

Provider pages expose a rolling activity window.  This command inventories
captures, selects a minimal overlapping set, writes an auditable staging
parquet/manifest, and only touches the normalized dataset when ``--write`` is
explicitly supplied.  Coverage gaps block writes unless ``--allow-gaps`` is
also explicit.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openrouter_data.models import RunContext, Snapshot  # noqa: E402
from openrouter_data.sources.serving_provider_activity import (  # noqa: E402
    CLOUD_INFRA_ACTIVITY_DATASET_ID,
    ServingProviderActivitySource,
)
from openrouter_data.storage import (  # noqa: E402
    SERVING_PROVIDER_DATASET_COLUMNS,
    StorageManager,
)
from wayback_backfill import WaybackClient, plan_rolling_window_captures  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_serving_provider_wayback")


def _parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", default=str(ROOT))
    parser.add_argument("--from-date", default="20260101")
    parser.add_argument(
        "--to-date",
        default=datetime.now(timezone.utc).strftime("%Y%m%d"),
    )
    parser.add_argument("--providers", nargs="*", default=None)
    parser.add_argument("--request-delay", type=float, default=1.5)
    parser.add_argument("--window-days", type=int, default=91)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--allow-gaps", action="store_true")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).expanduser().resolve()
    start = _parse_day(args.from_date)
    end = _parse_day(args.to_date)
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid4().hex[:8]
    )
    source = ServingProviderActivitySource(max_workers=1)
    client = WaybackClient(request_delay_seconds=args.request_delay)
    catalog = source.fetch_provider_catalog()
    if args.providers:
        requested = {value.strip().casefold() for value in args.providers}
        catalog = [provider for provider in catalog if provider["slug"] in requested]
        missing = sorted(requested - {provider["slug"] for provider in catalog})
        if missing:
            raise SystemExit(f"Unknown provider slugs: {', '.join(missing)}")

    records_with_capture: list[tuple[str, object]] = []
    provider_manifest: dict[str, object] = {}
    for provider in catalog:
        slug = provider["slug"]
        source.provider_metadata[slug] = provider
        url = f"https://openrouter.ai/provider/{slug}"
        captures = client.list_snapshots(
            url,
            from_date=args.from_date,
            to_date=args.to_date,
        )
        plan = plan_rolling_window_captures(
            captures,
            start_date=start,
            end_date=end,
            window_days=args.window_days,
        )
        extracted_count = 0
        failed_captures: list[dict[str, str]] = []
        for capture in plan.selected:
            try:
                body = client.fetch_capture(capture)
                context = RunContext(
                    run_id=f"wayback-serving-{slug}-{capture.timestamp}",
                    scraped_at=datetime.strptime(
                        capture.timestamp, "%Y%m%d%H%M%S"
                    ).replace(tzinfo=timezone.utc),
                )
                extracted = source.extract(
                    [
                        Snapshot(
                            name=f"serving_provider_{slug}",
                            source_url=(
                                f"https://web.archive.org/web/"
                                f"{capture.timestamp}id_/{capture.original}"
                            ),
                            body=body,
                        )
                    ],
                    context,
                )[CLOUD_INFRA_ACTIVITY_DATASET_ID]
                if not extracted:
                    failed_captures.append(
                        {
                            "timestamp": capture.timestamp,
                            "error": "capture parsed successfully but yielded zero activity rows",
                        }
                    )
                    continue
                extracted_count += len(extracted)
                records_with_capture.extend(
                    (capture.timestamp, record) for record in extracted
                )
            except Exception as exc:  # noqa: BLE001
                failed_captures.append(
                    {"timestamp": capture.timestamp, "error": str(exc)}
                )
        provider_manifest[slug] = {
            "capture_inventory_count": len(captures),
            "selected_captures": [
                capture.timestamp for capture in plan.selected
            ],
            "uncovered_ranges": list(plan.uncovered_ranges),
            "extracted_rows": extracted_count,
            "failed_captures": failed_captures,
        }
        logger.info(
            "%s: %d inventory, %d selected, %d rows, %d gaps",
            slug,
            len(captures),
            len(plan.selected),
            extracted_count,
            len(plan.uncovered_ranges),
        )

    records_with_capture.sort(key=lambda item: item[0])
    records = [record for _, record in records_with_capture]
    staging_root = (
        base_dir / "data" / "staging" / "openrouter_wayback" / run_id
    )
    staging_root.mkdir(parents=True, exist_ok=True)
    staged = pd.DataFrame(
        [record.to_dict() for record in records],
        columns=SERVING_PROVIDER_DATASET_COLUMNS,
    )
    if not staged.empty:
        staged = staged.drop_duplicates(
            subset=["usage_date", "serving_provider", "model_permaslug"],
            keep="last",
        ).sort_values(
            ["usage_date", "serving_provider", "model_permaslug"]
        )
    staged.to_parquet(
        staging_root / f"{CLOUD_INFRA_ACTIVITY_DATASET_ID}.parquet",
        index=False,
    )
    has_gaps = any(
        details.get("uncovered_ranges") or details.get("failed_captures")
        for details in provider_manifest.values()
        if isinstance(details, dict)
    )
    manifest = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "from_date": args.from_date,
        "to_date": args.to_date,
        "window_days": args.window_days,
        "write_requested": bool(args.write),
        "allow_gaps": bool(args.allow_gaps),
        "staged_rows": int(len(staged)),
        "has_coverage_gaps": bool(has_gaps),
        "providers": provider_manifest,
    }
    (staging_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    logger.info("Staged %d rows at %s", len(staged), staging_root)

    if not args.write:
        return 0
    if staged.empty:
        raise SystemExit("Refusing to write an empty staged backfill")
    if has_gaps and not args.allow_gaps:
        raise SystemExit(
            "Coverage gaps or failed captures detected; inspect the staging manifest or rerun "
            "with --allow-gaps to accept them explicitly"
        )
    merged = StorageManager(base_dir).upsert_dataset(
        CLOUD_INFRA_ACTIVITY_DATASET_ID,
        records,
    )
    logger.info("Normalized serving-provider activity now has %d rows", len(merged))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
