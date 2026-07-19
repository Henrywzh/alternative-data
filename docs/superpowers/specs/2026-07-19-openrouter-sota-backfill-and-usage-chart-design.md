# OpenRouter SOTA Backfill and Simplified Usage Charts

## Goal

Make the OpenRouter Usage & Economics section easy to read while adding a useful historical SOTA price signal. The usage view should show total demand at weekly cadence by default; Average Price should show the existing price-index family plus one clearly labeled SOTA line.

## Scope

### Usage chart

- Keep one chart with a Tokens / Requests metric toggle.
- Default window: Weekly.
- Optional window: Daily.
- Tokens: total OpenRouter token volume.
- Requests: total OpenRouter request volume from the weekly provider request feed when weekly is selected; do not show provider/model stacked breakdowns.
- Remove the Workload Intensity Component selector from this view.

### Average Price chart

Always show the original five price-index lines:

1. Spend-Weighted TEI
2. CPI Workload Basket Index (50/40/10)
3. Original Volume-Weighted TEI
4. Frontier
5. Value

Add one new line:

- **SOTA Volume-Weighted ATP (AA score backfilled from Jul 18, 2026)**

Remove the Price diagnostics expander and its opt-in behavior. The new SOTA line is not a zero-filled fallback: if there is insufficient paid SOTA traffic, it remains a gap and the chart explains why.

## SOTA methodology

The current Artificial Analysis normalized dataset contains 576 model rows and 563 non-null intelligence scores, with one score snapshot dated July 18, 2026. The implementation will use that snapshot as a historical proxy:

1. Collapse Artificial Analysis configurations into distinct model families.
2. Carry the July 18 score backward only to each model family's release date; never show a family before release.
3. Restrict the historical cohort to the top five distinct families by the backfilled score.
4. Map each family to exact OpenRouter routes, while keeping dated, preview, fast, pro, and free variants separate for pricing. Variants collapse only for SOTA membership.
5. Calculate SOTA Volume-Weighted ATP as paid SOTA revenue divided by paid SOTA tokens.
6. Require a minimum observed/priced-family guard; otherwise emit a missing value, never zero.
7. Carry explicit provenance in the output and visibly label the series as a backfilled AA-score proxy rather than a historical AA ranking.

## Data quality and limitations

- Backfilled scores are current-score historical proxies, not point-in-time Artificial Analysis measurements.
- Historical SOTA ATP begins only where matching OpenRouter activity and pricing are available.
- A model with no observed traffic contributes no denominator and does not imply zero cost.
- Route matching must remain exact and fail closed; no fuzzy matching is permitted for pricing.
- The compact marts remain the dashboard source to preserve Streamlit memory limits.

## Acceptance criteria

- Weekly total-token and total-request views render without provider/model stacks.
- Daily is available as an explicit alternate window.
- No Component selector or Price diagnostics expander remains.
- All five original price-index lines are visible by default.
- The new SOTA line is visibly labeled as backfilled and uses volume-weighted ATP.
- SOTA gaps are explained and never rendered as zero.
- Existing dashboard style, data-size limits, and workflow reliability remain intact.
