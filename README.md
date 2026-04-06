# alternative-data

Research repo for gathering and analyzing alternative data.

The first implemented projects are Python ingestion pipelines for OpenRouter rankings, app intelligence data, and GitHub Trending repository stats.

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
- `github_trending_daily`: daily points-in-time snapshots for trending repos
- `github_trending_weekly`: weekly points-in-time snapshots for trending repos
- `github_trending_monthly`: monthly points-in-time snapshots for trending repos

## Project Layout

- `src/openrouter_data/`: package, CLI, source extractors, storage, and pipeline logic
- `tests/fixtures/`: committed parser fixtures
- `data/raw/openrouter/`: timestamped raw snapshots and run manifests
- `data/normalized/openrouter/`: analytics-ready CSV and Parquet outputs tracked in git
- `src/github_trending_data/`: package, CLI, scraper, storage, and pipeline for GitHub data
- `data/normalized/github_trending/`: analytics-ready Parquet outputs for trending repos
- `.github/workflows/github-trending-daily.yml`: daily GitHub Actions job for trending repos
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

Run the GitHub Trending extraction:

```bash
github-trending-data --period all --data-dir data
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
