# alternative-data

Research repo for gathering and analyzing alternative data.

The first implemented project is a Python ingestion pipeline for OpenRouter rankings data:

- `top_models`: weekly model usage history
- `market_share`: weekly token share by model author
- `categories_programming`: weekly rankings/programming history

## Project Layout

- `src/openrouter_data/`: package, CLI, source extractors, storage, and pipeline logic
- `tests/fixtures/`: committed parser fixtures
- `data/raw/openrouter/`: timestamped raw snapshots and run manifests
- `data/normalized/openrouter/`: analytics-ready CSV and Parquet outputs
- `.github/workflows/openrouter-rankings-weekly.yml`: weekly GitHub Actions job

## Commands

Install locally:

```bash
python3 -m pip install -e .[dev]
```

Run the initial backfill:

```bash
openrouter-data --base-dir . initial-backfill
```

Run the weekly update:

```bash
openrouter-data --base-dir . weekly-update
```

Backfill any missing completed weeks:

```bash
openrouter-data --base-dir . backfill-missing
```

Validate the live extractor:

```bash
openrouter-data --base-dir . validate
```

## Notes

This repository is intended as a home for small, practical alternative data projects that can expand over time. The OpenRouter pipeline keeps a shared source interface so app and trending-app scraping can slot into the same framework later.
