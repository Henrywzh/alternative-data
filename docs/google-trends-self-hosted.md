# Google Trends Self-Hosted Workflow

This repo’s automated Google Trends refresh first attempts one Google Trends CSV export on a `self-hosted` GitHub Actions runner, then falls back to SerpApi if that export fails. The older `trendspyg` flow remains available for ad hoc local single-keyword work.

Current active Google Trends program covers eight high-priority HK consumer companies. Pop Mart (`9992.HK`) refreshes weekly; the other seven refresh monthly. Booking Holdings (`BKNG`) and Action (`III.L`) are excluded, and other names remain disabled.

## SerpApi Verification and Request Budget

One SerpApi `google_trends` / `TIMESERIES` request was tested against the prior validation target: `Pop Mart`, worldwide, `today 5-y`. The response returned 262 weekly points, including one partial latest week through `2026-07-26`, with no missing values, monotonic weekly timestamps, and values in the expected 1–100 range.

Compared with `data/raw/google_trends/pop_mart_worldwide_trends.parquet`, the 261-week overlap had 170 exact matches, Pearson correlation `0.9992`, mean absolute difference `1.6`, and maximum difference `5`. The data is structurally valid and highly comparable, but historical values are not byte-for-byte identical; this is consistent with rolling-window normalization or historical revisions. Do not silently overwrite the existing series during a provider migration.

SerpApi allows up to five queries per request, but `geo` applies to the whole request and batching can change Google Trends’ relative normalization. Until migration is complete, budget one request per keyword/geo pair:

| Scope | Weekly schedule | Approx. monthly requests |
|---|---:|---:|
| Pop Mart weekly scope (5 pairs) | 5 × 52 ÷ 12 | ~22 |
| Seven other high-priority companies monthly (14 pairs) | 14 | 14 |
| Data refreshes only | ~22 + 14 | **~36** |
| Validation calls (weekly + monthly) | 52 ÷ 12 + 1 | ~5 |
| Current program including validation | ~36 + ~5 | **~41** |

The Free Plan provides 250 searches/month, so the current program uses about 36 data-refresh searches/month, or about 41 including validation calls, and fits comfortably. See the [SerpApi Google Trends documentation](https://serpapi.com/google-trends-api) and the detailed [SerpApi deep dive](serpapi-deep-dive.md).

The exporter waits between outbound search attempts (`--search-delay`, default 2 seconds). Each keyword/geo pair gets one CSV attempt; only a failed pair invokes the SerpApi fallback.

## Current CSV Failure Diagnosis

The observed failure is an upstream Google Trends rate-limit/block, not primarily a selector change. The Explore page loaded and returned HTTP 200 for the configuration request, but the Interest-over-time widget request returned HTTP 429. Google then rendered “Oops! Something went wrong” and omitted the Interest-over-time widget; the remaining CSV buttons belonged to other widgets, so the exporter correctly rejected them.

This is why CSV can succeed for one pair and fall back to SerpApi for later pairs in the same run: the browser session can hit Google’s widget rate limit progressively.

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
python -m google_trends_data.batch_cli validate --base-dir . --headful --search-delay 2
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

Refresh the weekly Pop Mart scope:

```bash
python -m google_trends_data.batch_cli refresh-enabled --base-dir . --frequency weekly --search-delay 2
```

Refresh the monthly high-priority scope:

```bash
python -m google_trends_data.batch_cli refresh-enabled --base-dir . --frequency monthly --search-delay 2
```

## Workflow Behavior

- Scheduled weekly runs should execute `refresh-enabled --frequency weekly` on `runs-on: self-hosted`.
- A separate monthly run should execute `refresh-enabled --frequency monthly`.
- Manual runs support `refresh-enabled`, `refresh-ticker`, and `validate`.
- Manual runs can enable visible-browser debugging with the `headful` workflow input.
- Only parquet outputs under `data/raw/google_trends` and `data/processed/google_trends` are committed.
- Downloaded CSVs are kept under `output/google_trends_downloads/` and uploaded as workflow artifacts.

## Recovery Notes

If the workflow starts failing:

1. Trigger a manual `validate` run with `headful=true`.
2. Check whether the Interest-over-time widget request is returning HTTP 429; if so, the SerpApi fallback should handle the pair.
3. If the profile state looks stale, delete or archive the profile directory and reseed it with a fresh headful `validate` run.
4. If selectors drifted, inspect the page manually and update the Playwright exporter selector list.

## Data Source Policy

- Automated watchlist refreshes: one-attempt Google Trends CSV export/import, then SerpApi fallback
- Manual/local fallback: `google-trends-data` single-keyword CLI using `trendspyg`
- SerpApi: implemented as the per-pair fallback; API key is read from `SERP_API_KEY` or repository `.config`
