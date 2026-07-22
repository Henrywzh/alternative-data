# OpenRouter Workload-Intensity History Design

## Goal

Extend weekly workload intensity back to August 4, 2025 without treating
partial model-activity weeks as complete request totals.

## Source semantics

- `provider_weekly_requests` is the historical weekly request-count series.
- `openrouter_model_activity` rows with `category_slug = all` are the newer
  daily request-count series.
- The weekly token numerator remains the same total displayed by the weekly
  Tokens chart, preserving the existing `tokens / requests` definition.
- Daily workload intensity is unchanged and continues to use daily model
  activity only.

## Weekly request splice

1. Aggregate historical provider requests across companies for each week.
2. Aggregate `all` model-activity requests by Monday-starting week and count
   distinct observed dates.
3. Use model activity when all seven dates are present and a later observation
   confirms that the week has closed.
4. Otherwise retain the historical weekly request value when one exists.
5. Omit an incomplete model-activity week when no completed historical value
   exists. Do not extrapolate or annualize partial observations.
6. Join tokens and selected requests on completed common weeks before
   calculating workload intensity.

This makes the five-day week starting June 15, 2026 use the historical weekly
total, while complete model-activity weeks starting June 22 use the newer
series. The currently incomplete week starting July 20 is omitted from the
workload-intensity chart but remains unchanged in the separate source charts.

## Presentation

The methodology note will identify the coverage-aware splice and state that
incomplete unmatched weeks are omitted. The latest KPI and change calculation
will therefore use the latest completed common week.

## Verification

Regression tests will cover:

- historical weeks appearing before model activity begins;
- historical requests winning an incomplete overlap;
- model activity winning a complete overlap;
- an unmatched partial latest week being omitted;
- daily workload behavior remaining unchanged.
