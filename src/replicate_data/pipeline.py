import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any
from replicate_data.source import (
    fetch_collections_list,
    fetch_collection_models,
    fetch_model_detail,
)
from replicate_data.extract import (
    extract_models_catalog,
    extract_collections_summary,
)
from replicate_data.storage import (
    save_raw_snapshot,
    save_normalized_dataset,
)

# Matches the pacing convention used elsewhere in this repo (e.g.
# provider_incident_data/backfill_historical_incidents.py) to avoid tripping
# rate limits / bot protection across the ~dozens of collection pages and
# hundreds of deduplicated model-detail pages fetched per run.
REQUEST_DELAY_SECONDS = 0.3

def run_replicate_scrape(base_dir: Path, top_models_per_col: int = 10) -> Dict[str, Any]:
    """Execute the full Replicate AI collection and model scrape pipeline."""
    scraped_at = datetime.now(timezone.utc).isoformat()
    date_str = scraped_at.split("T", 1)[0]
    print(f"[replicate_data] Starting Replicate scrape pipeline for {date_str}...")

    # 1. Fetch Collections
    collection_slugs = fetch_collections_list()
    print(f"[replicate_data] Found {len(collection_slugs)} collections.")

    collections_raw = []
    model_details = {}

    for col in collection_slugs:
        try:
            col_data = fetch_collection_models(col)
            collections_raw.append(col_data)
            print(f"[replicate_data] Collection '{col}': {col_data['total_models']} models found.")
        except Exception as e:
            print(f"[replicate_data] Warning fetching collection {col}: {e}")
            continue
        finally:
            time.sleep(REQUEST_DELAY_SECONDS)

        # Fetch details for top models in collection
        for m in col_data.get("models", [])[:top_models_per_col]:
            slug = m["slug"]
            if slug in model_details:
                continue
            try:
                owner, name = m["owner"], m["name"]
                detail = fetch_model_detail(owner, name)
                model_details[slug] = detail
            except Exception as e:
                print(f"[replicate_data] Warning fetching model detail for {slug}: {e}")
            finally:
                time.sleep(REQUEST_DELAY_SECONDS)

    # 2. Save Raw Snapshots
    save_raw_snapshot(base_dir, {"collections": collections_raw}, date_str, "collections_raw.json")
    save_raw_snapshot(base_dir, {"details": model_details}, date_str, "model_details_raw.json")

    # 3. Extract & Normalize Datasets
    df_catalog = extract_models_catalog(collections_raw, model_details, scraped_at)
    df_collections = extract_collections_summary(collections_raw, scraped_at)

    # A malformed/partial run (e.g. every request blocked and caught by the
    # warn-and-continue handlers above) can still reach this point with
    # empty or near-empty results. Fail loudly instead of upserting a
    # degraded snapshot over previously-good history.
    if df_catalog.empty or df_collections.empty:
        raise ValueError(
            "Scrape produced an empty catalog or collections summary "
            f"(catalog={len(df_catalog)} rows, collections={len(df_collections)} rows). "
            "Aborting before saving to avoid upserting a malformed/partial snapshot."
        )

    save_normalized_dataset(base_dir, df_catalog, "replicate_model_catalog")
    save_normalized_dataset(base_dir, df_collections, "replicate_collections_summary")

    print(f"[replicate_data] Pipeline completed cleanly! Catalog: {len(df_catalog)} models, Collections: {len(df_collections)}.")
    return {
        "date": date_str,
        "total_collections": len(df_collections),
        "total_models": len(df_catalog),
    }
