# alternative-data

Research repo for gathering and analyzing alternative data.

The first implemented projects are Python ingestion pipelines for OpenRouter rankings, app intelligence data, and GitHub Trending repository stats.
The repository now also includes a provider-adoption pipeline that tracks GitHub, PyPI, npm, and Hugging Face signals for major LLM providers.
The repository also includes an Artificial Analysis pipeline that snapshots the official model API daily and refreshes the public capital-expenditure trend series.
The repository also includes a notebook-friendly research layer that builds analysis-ready marts and starter notebooks on top of the tracked datasets.

Rankings datasets:

- `top_models`: weekly model usage history
- `market_share`: weekly token share by model author
- `categories_programming`: weekly rankings/programming history
- `openrouter_model_activity`: daily model-level activity with request counts and token splits (`prompt`, `completion`, optional `reasoning`)
- `provider_daily_activity`: daily provider-page total-token history by model for the configured major OpenRouter providers

Apps datasets:

- `app_metadata_snapshots`: daily metadata snapshots for monitored apps
- `app_usage_daily`: rolling last-30-days daily usage by app and model
- `app_top_models_daily_snapshot`: daily point-in-time top-model snapshots for monitored apps
- `apps_global_ranking_snapshots`: public `/apps` global rankings by `day`, `week`, and `month`
- `apps_trending_snapshots`: public `/apps` trending leaderboard snapshots
- `github_trending_daily`: cumulative daily point-in-time snapshot history for trending repos
- `github_trending_weekly`: cumulative weekly point-in-time snapshot history for trending repos
- `github_trending_monthly`: cumulative monthly point-in-time snapshot history for trending repos
- `pypi_downloads_daily`: daily PyPI package download history by provider/package/mirror mode
- `npm_downloads_daily`: daily npm package download history by provider/package
- `github_repo_candidates_daily`: public GitHub repositories discovered in each daily date window
- `github_provider_signals_daily`: first-match provider signals by repo/day/type
- `github_repo_rollup_daily`: repo-level provider rollups for manifest/import/env/model detections
- `provider_momentum_daily`: daily blended GitHub + PyPI provider momentum metrics
- `artificial_analysis_models_daily`: daily Artificial Analysis API model snapshots
- `artificial_analysis_leading_models_by_lab_daily`: highest-intelligence model per lab per snapshot date
- `artificial_analysis_context_window_quarter_daily`: release-quarter median context window by proprietary/open-source bucket
- `artificial_analysis_capex_quarterly`: capital expenditure by quarter for major tech companies

Framework adoption tracked inside `provider_adoption`:

- npm: `@langchain/core`, `@langchain/langgraph`
- PyPI: `langchain`, `langgraph`, `pydantic-ai`

## Project Layout

- `src/openrouter_data/`: package, CLI, source extractors, storage, and pipeline logic
- `src/provider_adoption_data/`: package, CLI, source extractors, storage, and pipeline logic for GitHub + PyPI + npm adoption signals
- `src/artificial_analysis_data/`: package, CLI, API extractor, capex scraper, storage, and pipeline logic for Artificial Analysis data
- `src/research_data/`: analysis-facing loaders, marts, notebook helpers, and research CLI
- `tests/fixtures/`: committed parser fixtures
- `data/raw/openrouter/`: timestamped raw snapshots and run manifests
- `data/normalized/openrouter/`: analytics-ready CSV and Parquet outputs tracked in git
- `data/raw/provider_adoption/`: timestamped raw GitHub/PyPI/npm API payloads and run manifests
- `data/normalized/provider_adoption/`: analytics-ready CSV and Parquet outputs for provider adoption signals
- `data/raw/artificial_analysis/`: timestamped raw Artificial Analysis API payloads, trends HTML, JS bundle snapshots, and run manifests
- `data/normalized/artificial_analysis/`: analytics-ready CSV and Parquet outputs for Artificial Analysis datasets
- `data/normalized/marts/`: persisted analysis-ready marts for notebook use
- `notebooks/`: starter Jupyter notebooks for data cataloging and research workflows
- `src/github_trending_data/`: package, CLI, scraper, storage, and pipeline for GitHub data
- `data/normalized/github_trending/`: analytics-ready Parquet outputs for trending repos
- `.github/workflows/github-trending-daily.yml`: daily GitHub Actions job for trending repos
- `.github/workflows/provider-adoption-daily.yml`: daily GitHub Actions job for provider adoption datasets
- `.github/workflows/artificial-analysis-daily.yml`: daily GitHub Actions job for Artificial Analysis API snapshots and capex refreshes
- `.github/workflows/llm-benchmarks-weekly.yml`: weekly GitHub Actions job for ZeroEval benchmark snapshots and the frontier registry mart
- `.github/workflows/provider-adoption-backfill.yml`: manual bounded backfill job for provider adoption datasets
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

Run the OpenRouter model-activity update for the configured major-provider set:

```bash
openrouter-data --base-dir . activity-daily-update
```

Validate the live app extractor:

```bash
openrouter-data --base-dir . apps-validate
```

Run the GitHub Trending extraction:

```bash
github-trending-data --period all --data-dir data
```

Run the provider-adoption PyPI update:

```bash
provider-adoption-data --base-dir . pypi-daily-update
```

Run the framework-adoption PyPI update only:

```bash
provider-adoption-data --base-dir . --date 2026-04-24 --providers langchain,pydantic_ai pypi-daily-update
```

Run the provider-adoption npm update:

```bash
provider-adoption-data --base-dir . --date 2026-04-08 npm-daily-update
```

Run the framework-adoption npm update only:

```bash
provider-adoption-data --base-dir . --date 2026-04-24 --providers langchain npm-daily-update
```

Run the provider-adoption GitHub update for a specific date:

```bash
provider-adoption-data --base-dir . --date 2026-04-08 github-daily-update
```

Run the provider-adoption Hugging Face update for a specific date:

```bash
provider-adoption-data --base-dir . --date 2026-04-08 huggingface-daily-update
```

Run the ZeroEval benchmark update:

```bash
llm-benchmark-data --base-dir . update
```

Run the Artificial Analysis daily update:

```bash
artificial-analysis-data --base-dir . daily-update
```

Refresh only the Artificial Analysis capex history:

```bash
artificial-analysis-data --base-dir . capex-update
```

Validate Artificial Analysis API auth and capex parsing:

```bash
artificial-analysis-data --base-dir . validate
```

Show the source and mart catalog:

```bash
research-data --base-dir . catalog
```

Build all research marts:

```bash
research-data --base-dir . build-marts --refresh
```

Build a single research mart:

```bash
research-data --base-dir . build-mart weekly_openrouter_usage --refresh
```

Compute the provider momentum snapshot for a specific date:

```bash
provider-adoption-data --base-dir . --date 2026-04-08 derived-daily-update
```

Run a bounded provider-adoption backfill:

```bash
provider-adoption-data --base-dir . backfill --start-date 2026-04-01 --end-date 2026-04-08
```

Set `HF_TOKEN` to reduce Hugging Face API rate limiting during model snapshot collection. The token is optional for public data but recommended in CI and long-running local syncs.

Set `ARTIFICIAL_ANALYSIS_API_KEY` to enable the Artificial Analysis API collector. If the environment variable is unset, the pipeline falls back to the repository-root `.config` file. API-backed history starts on the first real collection date; the pipeline does not synthesize historical API snapshots.

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
The provider-adoption pipeline now defaults to tracking OpenAI, Anthropic, Google, DeepSeek, Meta, Mistral, Qwen, Moonshot, Minimax, and ZAI. PyPI and npm coverage remain selective, while Hugging Face coverage tracks all models under each configured organization.
Framework ecosystems are also tracked inside the provider-adoption domain, with package-level daily raw series for LangChain and PydanticAI.
The OpenRouter activity pipeline now prefers the latest local OpenRouter catalog to discover model activity pages for the configured major-provider set, and stores request counts plus prompt/completion token splits with optional reasoning-token capture when the source exposes it.
The bounded backfill command does not fabricate historical Hugging Face rows; HF snapshots begin from the first real collection date onward.
The Artificial Analysis pipeline uses the official API for model data and only scrapes the public site for the capital expenditure series; any downstream use should preserve Artificial Analysis attribution and API terms.
The research layer keeps scraping outputs as the source of truth and writes derived marts under `data/normalized/marts/` for fast, deterministic Jupyter analysis.
