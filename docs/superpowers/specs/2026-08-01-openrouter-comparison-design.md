# OpenRouter Comparison Tab

**Status:** Approved design; implementation not started  
**Date:** 2026-08-01

## Objective

Add a dedicated OpenRouter comparison tab that lets a user compare exactly two
companies or exactly two models using the same usage and economics definitions
already used by the OpenRouter Models and Intelligence tabs.

The feature is intended to answer relative questions such as which company is
gaining usage, whether a model attracts more requests despite lower token
volume, and how realized cost differs between two choices.

## Scope

The tab has two mutually exclusive comparison modes:

- **Companies:** compare two model-origin companies, such as OpenAI and
  Anthropic. A company is not a serving route; Amazon, Google, or Anthropic
  routes are not treated as the model company when they serve another lab's
  model.
- **Models:** compare two canonical model families or model identities.

The user always selects exactly two entities. A mixed company/model comparison
and three- or four-way comparisons are out of scope for the first version.

Each comparison supports three windows:

- **Weekly** (default): longest and most stable history.
- **Daily:** newer granular activity where the underlying source supports it.
- **Monthly:** calendar-month aggregation of the reconciled series.

## Metrics

The comparison surface exposes the following metrics for both selected
entities:

1. Token volume
2. Request volume
3. Estimated revenue
4. Tokens per request
5. Realized price per 1M priced tokens
6. Period-over-period change for the selected window

The latest-period summary shows the value for each entity, absolute delta, and
relative delta. The main chart uses a metric selector so that the page does not
render six visually competing charts at once. The user can switch between
absolute values and a normalized share/index view when entity scale differs
substantially.

For model comparisons, the summary also shows each model's Artificial Analysis
score. Company comparisons do not force a single misleading company score;
scores are not part of the company comparison metric set.

## Historical data reconciliation

The comparison must consume one canonical reconciled series rather than adding
old and new datasets together. It should reuse the source-precedence and alias
normalization logic already used by the Models and Intelligence tabs:

1. Preserve the long legacy weekly history for older periods.
2. Prefer complete model-activity totals once available for a period/entity.
3. Use provider-level totals to fill genuine model-activity gaps, not to create
   a second contribution for the same period.
4. Normalize routing aliases, `~` aliases, and fast/preview/free variants using
   the existing canonical identity rules before aggregation.
5. Keep model-origin companies distinct from serving providers.
6. Do not interpolate missing daily observations or connect a line across a
   known gap.

Weekly values should retain the historical range available in the legacy data.
Daily values may begin later and should display their actual coverage start.
Monthly values are built from the reconciled observations and must not double
count overlapping weekly and daily sources. The newest incomplete week or
month should be visibly marked as partial, consistent with existing dashboard
conventions.

## Economics and quality labels

Estimated revenue and realized price must use the existing OpenRouter pricing
and coverage logic. Realized price is revenue divided by priced tokens; free or
unpriced tokens remain outside the denominator. Each relevant KPI/chart should
show pricing coverage, and low coverage should be flagged rather than presented
as a precise estimate.

The page should expose compact source/coverage notes indicating whether the
selected series is backed by complete model activity, provider totals, or a
reconciled combination. A missing observation means unavailable data, not zero
activity.

## Proposed page layout

1. **Comparison controls:** mode toggle, Entity A, Entity B, window selector,
   and date range.
2. **Latest comparison cards:** paired values for the six metrics, with deltas
   and coverage notes.
3. **Primary time-series chart:** selected metric, two entity lines, and an
   optional normalized share/index toggle.
4. **Model-score row:** shown only in model mode, with the two Artificial
   Analysis scores and score dates/coverage.
5. **Methodology note:** source precedence, company definition, partial-period
   treatment, and pricing coverage.

No latest-most-used-model table or company model-mix breakdown is included in
the initial version.

## Implementation boundaries

The implementation should add a focused renderer and small comparison helpers
to the existing OpenRouter dashboard surface, reusing existing loaded dataset
objects and canonical aggregation functions. It should not introduce a new
scrape or a new high-volume stored dataset. Any new derived frame should be
compact and calculated from already loaded data to respect Streamlit Cloud's
memory limit.

Expected areas of change are the dashboard section registry/navigation, the
OpenRouter section renderer, and narrowly scoped tests for source precedence,
alias normalization, period aggregation, gap handling, and metric formulas.

## Acceptance criteria

- The tab compares exactly two companies or exactly two models.
- Weekly is selected by default and shows the full reconciled history.
- Daily and monthly windows work without silently treating missing values as
  zero or interpolating gaps.
- All five core metrics are available for both entities, with period deltas.
- Model scores appear only for model comparisons.
- Old and new source datasets never double count overlapping periods.
- Realized-price and revenue coverage are visible and low coverage is flagged.
- Existing OpenRouter tabs and their historical charts are unchanged.
- The comparison path remains lightweight enough for the Streamlit Cloud
  memory budget.

## Non-goals

- Mixed company-versus-model comparisons.
- Three-way or four-way comparisons.
- A new OpenRouter scraping endpoint or daily request expansion.
- Replacing existing Models, Intelligence, or Workloads tab charts.
- A company-level capability score presented as if it were a model score.
