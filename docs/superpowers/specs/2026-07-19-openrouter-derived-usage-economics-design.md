# OpenRouter Derived Usage and Economics Design

## Purpose

Improve the existing OpenRouter usage section with derived measures that distinguish workload demand, token intensity, market pricing, and frontier-model pricing without weakening the quality or granularity of the underlying datasets.

The work adds no new external scraping or API traffic. It derives compact analytical marts from data already collected by the repository.

## Product Questions

The feature must answer four different questions without conflating them:

1. How much token volume is OpenRouter processing?
2. How many requests are models and providers handling as a proxy for workload demand?
3. How many tokens does the observed workload consume per request?
4. What is the realized price of OpenRouter usage, and how does it compare with the price of genuinely state-of-the-art models?

Requests are a workload-demand proxy, not a count of completed user tasks. Agent loops, retries, batching, and multi-call workflows can cause one user task to generate several requests. Tokens per request is a workload-intensity measure, not a pure efficiency score, because long-context and reasoning workloads may legitimately consume more tokens.

## Scope

### Included

- Add `Workload Intensity` to the current OpenRouter usage metric selector.
- Improve `Average Price` with capability-aware SOTA pricing measures.
- Preserve the existing token, request, realized-price, price-band, and fixed-basket calculations where they remain valid.
- Rename price-defined cohorts so they are not presented as capability classifications.
- Precompute compact derived datasets for low Streamlit memory and CPU use.
- Surface coverage, provenance, and methodology guards in the dashboard.

### Excluded

- New OpenRouter, Artificial Analysis, or third-party collection routes.
- A single composite model score combining capability, price, context, and speed.
- Claims that requests equal completed tasks or that tokens per request alone measures model efficiency.
- Fuzzy matching as sufficient evidence for capability classification.
- Rewriting or reducing the granularity of existing raw and normalized datasets.

## Dashboard Information Architecture

Rename `Weekly OpenRouter Usage` to **OpenRouter Usage & Economics** because the section contains both weekly and daily measures.

The primary segmented selector contains:

1. `Tokens`
2. `Requests`
3. `Workload Intensity`
4. `Average Price`

Each view states its own frequency, source coverage, and most recent complete observation. The current day is excluded from all daily derived metrics because it may be incomplete.

## Workload Intensity

### Source boundary

Workload Intensity is calculated only from `openrouter_model_activity`. Its token numerator and request denominator must come from the same rows. Broad weekly token rankings and provider-level request rankings must never be divided by one another because their coverage differs.

### Daily calculations

For each complete usage day:

```text
total_tokens_per_request = sum(total_tokens) / sum(request_count)
prompt_tokens_per_request = sum(prompt_tokens) / sum(request_count)
completion_tokens_per_request = sum(completion_tokens) / sum(request_count)
```

The aggregate is a ratio of sums, not an unweighted mean of model-level ratios. Rows with missing or non-positive request counts are excluded from ratio calculations and counted in a quality field. Missing values are never converted to zero.

The chart defaults to a seven-day rolling ratio calculated from seven-day rolling numerators and denominators. It must not take the arithmetic mean of seven daily ratios. A raw-daily option remains available.

The view offers `Total`, `Prompt`, and `Completion` controls. Total uses the source-reported `total_tokens`; prompt and completion use their respective source columns. Any material mismatch between reported total tokens and component tokens is retained and monitored rather than silently reconciled.

### KPIs

- Total tokens per request
- Prompt tokens per request
- Completion tokens per request
- Seven-day percentage change in total tokens per request

The KPI date and observed model count are shown alongside the values.

### Model comparison

A compact table aggregates the latest 30 complete days by canonical model identity and shows:

- Model
- Company
- Requests
- Request share
- Tokens
- Token share
- Tokens per request
- Intensity ratio
- Window start and end dates

```text
intensity_ratio = token_share / request_share
```

An intensity ratio above 1 means the model is more token-intensive than the observed tracked-model market. A ratio below 1 means it is more request-heavy. The UI must not label either result as inherently better.

## Average Price

### Existing realized market measure

Preserve the existing usage-weighted realized market price calculation, including its explicitly labelled earliest-price backcast for dates before usable pricing history. It continues to represent estimated revenue divided by priced token volume for the observed paid-model activity. Free routes remain excluded from the paid price index and are reported separately in coverage.

This legacy backcast applies only to the existing market-average series and retains its `backcast_earliest_pricing` provenance. The new SOTA and Frontier Contender measures use strict as-of prices and never inherit the legacy backcast. This preserves the useful early market history without presenting future prices as point-in-time SOTA evidence.

### Rename price cohorts

The current price-defined labels are renamed:

- `Frontier` becomes `Premium-priced`
- `Mid-Tier` becomes `Mid-priced`
- `Value` becomes `Low-priced`

The current thresholds remain unchanged initially so the historical series remains comparable:

- Premium-priced: blended price at least $2.00 per million tokens
- Mid-priced: blended price from $0.50 to below $2.00 per million tokens
- Low-priced: blended price below $0.50 per million tokens

These cohorts are pricing diagnostics and make no claim about model capability.

### Capability tiers

Capability tiers use Artificial Analysis intelligence rankings and distinct model families:

- `SOTA`: ranks 1 through 5
- `Frontier Contenders`: ranks 6 through 10
- `Broader Scored Market`: rank 11 and below
- `Unscored`: no defensible Artificial Analysis match

One family may occupy only one rank. Within a family, the representative configuration is selected by:

1. Highest valid intelligence index
2. Most recent release date when scores tie
3. Stable model identifier as the final deterministic tie-breaker

Families are then sorted by representative intelligence index, representative release date, and stable family identifier to produce exactly five SOTA families and five Frontier Contenders when at least ten eligible families exist.

Family membership must come from exact canonical identifiers or an explicitly curated alias map. Fuzzy similarity may generate a review candidate but may not assign a tier automatically.

### Point-in-time eligibility

For every usage date, ranking uses the latest successful Artificial Analysis snapshot on or before that date. A model is eligible only when its release date is on or before the usage date. Pricing uses the latest valid OpenRouter price snapshot on or before the usage date.

The pipeline does not reconstruct SOTA history before adequate point-in-time Artificial Analysis snapshots exist. A missing historical benchmark or price remains missing. Future benchmark snapshots, releases, aliases, and prices cannot leak backward.

### SOTA Median List Price

The **SOTA Median List Price** is the median blended list price of the five representative SOTA configurations. It is not usage-weighted.

The initial blended-price method preserves the dashboard's existing fixed workload mix for comparability:

```text
blended_price = 97.7% * input_price + 2.3% * output_price
```

The input price, output price, blend weights, and methodology version are stored with or recoverable from the derived record. The median is emitted only when at least three of the five representative configurations have valid as-of prices.

### Realized SOTA Price

The **Realized SOTA Price** is calculated from actual observed paid activity belonging to compatible serving variants of the five SOTA representative configurations:

```text
realized_sota_price = sum(estimated_revenue) / sum(total_tokens)
```

It uses actual prompt and completion splits where available, following the repository's existing revenue methodology. It is token-weighted and smoothed using the same seven-day rolling ratio-of-sums rule as the realized market average.

Compatible serving variants may include provider routes, `fast`, or `preview` routes only when they map to the same benchmarked model configuration. Lower-capability siblings in the same broad family are excluded. Every route retains its own as-of price. `fast`, `preview`, free, reasoning, and non-reasoning variants are never assigned another variant's price.

Free usage is excluded from the paid Realized SOTA Price and disclosed separately. An unobserved SOTA family is not treated as zero usage or zero price.

The Realized SOTA Price is emitted only when at least three of the five SOTA families have both valid as-of pricing and observed activity for the rolling window.

### Default and diagnostic lines

The Average Price chart defaults to:

- Realized Market Average
- SOTA Median List Price
- Realized SOTA Price

Optional price diagnostics contain:

- Frontier Contenders median list price
- Premium-priced realized price
- Mid-priced realized price
- Low-priced realized price
- Existing fixed workload basket

This keeps the default chart readable while preserving the existing analytical series.

## Coverage and Provenance

Every capability-derived record includes:

- Usage date or rolling-window end date
- Artificial Analysis snapshot date
- Latest contributing pricing snapshot date
- Methodology version
- Expected family count
- Families with valid benchmark matches
- Families with valid prices
- Families with observed activity
- Paid tokens included
- Free tokens excluded
- Unpriced tokens excluded
- Model-identity match status

The dashboard displays concise coverage such as `Observed 4/5 SOTA families; priced 5/5`. A details expander explains excluded free, unpriced, unmatched, and incompatible-variant activity.

No metric is silently zero-filled when its guard fails. The chart shows a gap and a specific coverage message.

## Derived Storage

Create two compact long-format marts under `data/normalized/marts/`:

### `openrouter_usage_economics_daily.parquet`

One row per date, metric, and cohort. Proposed fields:

- `usage_date`
- `metric_id`
- `cohort_id`
- `value`
- `numerator`
- `denominator`
- `rolling_window_days`
- `benchmark_snapshot_date`
- `pricing_snapshot_date`
- `expected_family_count`
- `priced_family_count`
- `observed_family_count`
- `observed_model_count`
- `included_tokens`
- `excluded_free_tokens`
- `excluded_unpriced_tokens`
- `methodology_version`

### `openrouter_workload_intensity_models.parquet`

One row per canonical model for the latest comparison window. Proposed fields:

- `window_start_date`
- `window_end_date`
- `model_id`
- `company_id`
- `total_tokens`
- `prompt_tokens`
- `completion_tokens`
- `request_count`
- `token_share`
- `request_share`
- `tokens_per_request`
- `intensity_ratio`
- `model_match_status`
- `methodology_version`

Long-form storage avoids another wide schema and keeps the Streamlit memory footprint small. These marts duplicate only compact derived aggregates, not raw activity history.

## Pipeline and Scheduling

Add a derived-metrics pipeline that reads:

- `openrouter_model_activity`
- `daily_provider_economics`
- `artificial_analysis_models_daily`
- Existing OpenRouter catalog/model identity fields where required
- A version-controlled curated family and alias map

Run it in a short, isolated daily GitHub Action after the OpenRouter and Artificial Analysis source workflows normally finish. The action performs no external data requests. It has an explicit timeout, concurrency cancellation, workflow dispatch support, quality tests, and commits only changed derived files.

If one source is stale but valid, the mart records that source date. If required source data is absent or structurally invalid, the derived action fails without rewriting the last valid mart.

## Streamlit Behaviour

The dashboard loads only the two compact marts for the new views. It does not perform the full activity-pricing-benchmark join during each session. Existing data-loading and chart-style conventions are reused.

If a derived mart is missing or stale:

- Existing Tokens and Requests views remain available.
- Existing price views remain available when their current source is valid.
- Workload Intensity or capability-price lines show a scoped unavailable/stale message.
- The page does not crash and does not substitute zeros.

## Testing and Quality Gates

### Capability and identity tests

- Several configurations from one family occupy only one family rank.
- Family representative selection and top-five tie-breaking are deterministic.
- Ranks 1–5, 6–10, and 11+ are assigned correctly.
- Fuzzy-only matches remain unscored.
- Lower-capability family siblings do not enter representative-config activity.
- `fast`, `preview`, free, reasoning, and non-reasoning prices remain separate.

### Point-in-time tests

- Future model releases cannot enter an earlier SOTA tier.
- Future benchmark snapshots cannot rank an earlier day.
- Future pricing cannot price earlier SOTA or Frontier Contender activity.
- The existing market-average backcast remains isolated and explicitly labelled.
- Missing historical coverage produces a gap rather than a backfill or zero.

### Price tests

- SOTA median list price uses one representative per family and the median of valid blended prices.
- The list-price series requires at least three priced SOTA families.
- Realized SOTA price is a ratio of summed revenue to summed tokens.
- The realized series requires at least three observed and priced SOTA families.
- Free and unpriced tokens are excluded and counted in coverage.
- Existing realized market and fixed-basket outputs remain backward compatible apart from clearer cohort labels.

### Workload tests

- Daily tokens per request is a ratio of aggregate sums.
- Seven-day values are rolling ratios of sums, not averages of daily ratios.
- Zero-request and incomplete-current-day rows are excluded and counted.
- Prompt, completion, and total calculations use the documented columns.
- Model token shares and request shares each sum to approximately 100% over the same eligible row set.
- Intensity ratio equals token share divided by request share.

### Dashboard tests

- The four metric states render without loading unrelated large datasets.
- Coverage labels match mart counts.
- Missing or guarded metrics show explanatory gaps rather than zeros.
- Default Average Price lines and optional diagnostics are correctly separated.
- Existing visual style, date formatting, and navigation state remain consistent.

## Acceptance Criteria

The design is complete when:

1. The section exposes Tokens, Requests, Workload Intensity, and Average Price without changing raw source data.
2. Workload Intensity uses matched token/request coverage and clearly identifies its tracked-model boundary.
3. SOTA contains exactly five distinct eligible model families when coverage permits.
4. The dashboard shows both SOTA median list price and usage-weighted Realized SOTA Price.
5. Price-defined cohorts use price terminology rather than capability terminology.
6. All point-in-time, identity, variant, minimum-coverage, and missing-data guards are enforced.
7. The new marts are compact, long-format, and safe for the Streamlit Cloud memory constraint.
8. No new external API or scraping traffic is introduced.
9. Existing OpenRouter token, request, revenue, and price history remains available at its current granularity.
