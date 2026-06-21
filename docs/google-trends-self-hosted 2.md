# Google Trends Self-Hosted Workflow

This repo’s automated Google Trends refresh now uses Google Trends CSV export/import on a `self-hosted` GitHub Actions runner. The older `trendspyg` flow remains available for ad hoc local single-keyword work, but scheduled watchlist refreshes should use the self-hosted workflow.

## Runner Setup

1. Register your Mac as a self-hosted runner for this repo.
2. Make sure the runner user has Chrome/Chromium-compatible desktop access.
3. Set a repo or org Actions variable named `GOOGLE_TRENDS_PROFILE_DIR` if you want a fixed browser-profile path.
4. If you do not set that variable, the workflow falls back to `$HOME/.cache/google-trends-playwright`.

## One-Time Browser Profile Bootstrap

Before enabling the schedule, seed the persistent Playwright profile once on the self-hosted machine.

```bash
python -m pip install -e .[dev]
python -m playwright install chromium
python -m google_trends_data.batch_cli validate --base-dir . --headful
```

During that run:
- let the browser window open
- clear any consent screens
- confirm Google Trends loads normally
- let the validation export finish once

This creates a reusable profile with any required consent state already stored.

## Manual Smoke Tests

Validate a single export without writing datasets:

```bash
python -m google_trends_data.batch_cli validate --base-dir . --headful
```

Refresh one ticker only:

```bash
python -m google_trends_data.batch_cli refresh-ticker --base-dir . --ticker TSLA --headful
```

Refresh the full enabled watchlist:

```bash
python -m google_trends_data.batch_cli refresh-enabled --base-dir .
```

## Workflow Behavior

- Scheduled runs execute `refresh-enabled` weekly on `runs-on: self-hosted`.
- Manual runs support `refresh-enabled`, `refresh-ticker`, and `validate`.
- Manual runs can enable visible-browser debugging with the `headful` workflow input.
- Only parquet outputs under `data/raw/google_trends` and `data/processed/google_trends` are committed.
- Downloaded CSVs are kept under `output/google_trends_downloads/` and uploaded as workflow artifacts.

## Recovery Notes

If the workflow starts failing:

1. Trigger a manual `validate` run with `headful=true`.
2. Check whether Google Trends is showing a consent prompt, login interruption, or changed download UI.
3. If the profile state looks stale, delete or archive the profile directory and reseed it with a fresh headful `validate` run.
4. If selectors drifted, inspect the page manually and update the Playwright exporter selector list.

## Data Source Policy

- Automated watchlist refreshes: Google Trends CSV export/import on self-hosted runner
- Manual/local fallback: `google-trends-data` single-keyword CLI using `trendspyg`
