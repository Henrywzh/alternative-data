from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opencode_data.extract import (
    extract_benchmarks,
    extract_country_usage,
    extract_leaderboard,
    extract_market_share,
    extract_model_catalog,
    extract_model_deepdive,
    extract_usage_daily,
    extract_users_daily,
)
from opencode_data.source import (
    extract_home_payload,
    extract_model_payload,
    fetch_html,
)
from opencode_data.storage import (
    save_normalized_dataset,
    save_raw_snapshot,
)


def run_opencode_scrape(base_dir: Path, top_models_count: int = 15) -> dict[str, Any]:
    """Execute complete OpenCode data scrape and normalization pipeline."""
    scraped_at = datetime.now(timezone.utc).isoformat()
    home_url = "https://opencode.ai/data/"
    print(f"[{scraped_at}] Fetching home page: {home_url}")
    html = fetch_html(home_url)

    stats_home, catalog = extract_home_payload(html)
    if catalog is None:
        print(
            "Warning: model catalog payload (models+labs metadata) was not found in the "
            "home page hydration state -- opencode_model_catalog/opencode_benchmarks will "
            "not be updated this run. stats_home-derived datasets are unaffected."
        )

    # Save raw snapshots
    save_raw_snapshot(base_dir, "stats_home", stats_home, scraped_at)
    if catalog is not None:
        save_raw_snapshot(base_dir, "model_catalog", catalog, scraped_at)

    # Extract primary datasets
    market_rows = extract_market_share(stats_home, scraped_at)
    usage_rows = extract_usage_daily(stats_home, scraped_at)
    users_rows = extract_users_daily(stats_home, scraped_at)
    leaderboard_rows = extract_leaderboard(stats_home, scraped_at)
    country_rows = extract_country_usage(stats_home, scraped_at)
    catalog_rows = extract_model_catalog(catalog, scraped_at) if catalog is not None else []
    benchmark_rows = extract_benchmarks(catalog, scraped_at) if catalog is not None else []

    # A malformed/partial payload can still pass extract_home_payload's shape
    # check (it only requires the top-level keys to exist) while yielding
    # empty core datasets. Fail loudly here instead of upserting near-empty
    # rows into the workflow's history. model_catalog is excluded: it's
    # legitimately allowed to be empty right now (see extract_home_payload).
    empty_core_datasets = [
        dataset_name
        for dataset_name, dataset_rows in (
            ("market_share", market_rows),
            ("usage_daily", usage_rows),
            ("leaderboard", leaderboard_rows),
        )
        if not dataset_rows
    ]
    if empty_core_datasets:
        raise ValueError(
            f"Scrape produced no rows for core dataset(s): {', '.join(empty_core_datasets)}. "
            "Aborting before saving to avoid upserting a malformed/partial snapshot."
        )

    # Select top models for deepdives based on active leaderboard entries
    models_to_fetch = []
    seen = set()
    for row in leaderboard_rows:
        if len(models_to_fetch) >= top_models_count:
            break
        provider = row.get("provider")
        slug = row.get("model_slug")
        if provider and slug and slug != "Other" and (provider, slug) not in seen:
            seen.add((provider, slug))
            models_to_fetch.append((provider, slug))

    deepdive_rows = []
    raw_deepdives = {}
    for provider, slug in models_to_fetch:
        model_url = f"https://opencode.ai/data/{provider}/{slug}"
        print(f"Fetching model deepdive: {model_url}")
        try:
            m_html = fetch_html(model_url)
            m_payload = extract_model_payload(m_html)
            raw_deepdives[f"{provider}_{slug}"] = m_payload
            deepdive_row = extract_model_deepdive(m_payload, scraped_at)
            deepdive_rows.append(deepdive_row)
        except Exception as e:
            print(f"Notice: Model page {provider}/{slug} may not have a dedicated deepdive page: {e}")

    if raw_deepdives:
        save_raw_snapshot(base_dir, "model_deepdives", raw_deepdives, scraped_at)

    # Save normalized CSV & optional Parquet datasets
    save_normalized_dataset(base_dir, "opencode_market_share", market_rows)
    save_normalized_dataset(base_dir, "opencode_usage_daily", usage_rows)
    save_normalized_dataset(base_dir, "opencode_users_daily", users_rows)
    save_normalized_dataset(base_dir, "opencode_leaderboard", leaderboard_rows)
    save_normalized_dataset(base_dir, "opencode_country_usage", country_rows)
    save_normalized_dataset(base_dir, "opencode_model_catalog", catalog_rows)
    save_normalized_dataset(base_dir, "opencode_benchmarks", benchmark_rows)
    save_normalized_dataset(base_dir, "opencode_model_deepdives", deepdive_rows)

    summary = {
        "scraped_at": scraped_at,
        "market_share_records": len(market_rows),
        "usage_daily_records": len(usage_rows),
        "users_daily_records": len(users_rows),
        "leaderboard_records": len(leaderboard_rows),
        "country_usage_records": len(country_rows),
        "catalog_models_count": len(catalog_rows),
        "benchmark_records": len(benchmark_rows),
        "model_deepdives_count": len(deepdive_rows),
    }
    return summary
