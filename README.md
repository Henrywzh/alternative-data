# alternative-data

Research repo for gathering and analyzing alternative data.

The first implemented projects are Python ingestion pipelines for OpenRouter rankings and app intelligence data.

Rankings datasets:

- `top_models`: weekly model usage history
- `market_share`: weekly token share by model author
- `categories_programming`: weekly rankings/programming history

Apps datasets:

- `app_metadata_snapshots`: daily metadata snapshots for monitored apps
- `app_usage_daily`: rolling last-30-days daily usage by app and model
- `app_top_models_daily_snapshot`: daily point-in-time top-model snapshots for monitored apps
- `apps_global_ranking_snapshots`: public `/apps` global rankings by `day`, `week`, and `month`
- `apps_trending_snapshots`: public `/apps` trending leaderboard snapshots

## Project Layout

- `src/openrouter_data/`: package, CLI, source extractors, storage, and pipeline logic
- `tests/fixtures/`: committed parser fixtures
- `data/raw/openrouter/`: timestamped raw snapshots and run manifests
- `data/normalized/openrouter/`: analytics-ready CSV and Parquet outputs tracked in git
- `.github/workflows/openrouter-rankings-weekly.yml`: weekly GitHub Actions job
- `.github/workflows/openrouter-apps-daily.yml`: daily GitHub Actions job for app monitoring and public app rankings
- `.github/workflows/repo-keepalive.yml`: scheduled keepalive commit to avoid GitHub disabling scheduled workflows after long inactivity

## Commands

Install locally:

```bash
python3 -m pip install -e .[dev]
```

Run the rankings initial backfill:

```bash
openrouter-data --base-dir . initial-backfill
```

Run the rankings weekly update:

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

Run the apps initial backfill:

```bash
openrouter-data --base-dir . apps-initial-backfill
```

Run the apps daily update:

```bash
openrouter-data --base-dir . apps-daily-update
```

Validate the live app extractor:

```bash
openrouter-data --base-dir . apps-validate
```

Run the internal QA dashboard locally:

```bash
python3 -m pip install -r requirements-dashboard.txt
streamlit run dashboard/app.py
```

Deploy the QA dashboard on Render:

```bash
render blueprint apply
```

## Notes

This repository is intended as a home for small, practical alternative data projects that can expand over time. The OpenRouter pipeline now supports both rankings and app sources with the same raw snapshot storage and normalized dataset workflow.
