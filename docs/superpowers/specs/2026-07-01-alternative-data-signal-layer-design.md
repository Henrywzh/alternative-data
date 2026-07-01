# Alternative Data Signal Layer Design

## Objective

Build a simple, explainable signal layer on top of the repository's existing alternative-data pipelines. The first version should turn raw and normalized datasets into meaningful metric-level signals, then map those signals to stock-level and theme-level outputs.

The alert system is intentionally out of scope for this phase. Alerts should come later, after the signal definitions, baselines, mappings, and scoring conventions are stable enough to trust.

## Project Boundaries

Included:
- Define a common schema for metric-level signals.
- Define a mapping registry from metrics to stocks, themes, and exposure types.
- Produce stock-level and theme-level signal outputs by aggregating mapped metric signals.
- Add simple, explainable transforms such as YoY growth, rolling change, percentile, robust z-score, rank change, and momentum.
- Use statistical baselines and surprise measures instead of hand-blended scores with magic-number weights.
- Start with source-specific signal builders that output into a shared schema.
- Keep the design compatible with later email alerts, dashboard views, notebooks, and backtests.

Excluded for this phase:
- Email alerts.
- Real-time alerting.
- Trade execution.
- Portfolio construction.
- Complex machine learning models.
- Full Google Trends seasonality modelling beyond simple baseline support.
- Exhaustive mapping for every possible stock and metric.

## Why This Shape

The repository already has source-specific ingestion and normalized outputs for OpenRouter, Artificial Analysis, provider adoption, semiconductors, Google Trends, and minerals. The missing layer is interpretation.

The signal layer should answer:
- what changed,
- what normal looks like,
- whether the move is directionally meaningful,
- what stocks or themes are exposed,
- how confident the mapping is,
- and what caveats apply.

Metric-level signals should be the source of truth. Stock-level and theme-level signals should be derived outputs built from mappings. This keeps the system auditable: if a stock signal looks bullish or bearish, it can be traced back to the exact metric signals and mapping weights that produced it.

## Recommended Approach

Use a hybrid architecture:
- shared schemas and scoring conventions,
- source-specific signal builders,
- a central mapping registry,
- and shared aggregation logic for stock and theme outputs.

This avoids over-engineering a universal signal engine before the useful features are known. It also avoids inconsistent one-off calculations across datasets. Each data domain can use the transforms that fit its cadence and source quality, while downstream consumers read one consistent signal format.

## Signal Layers

### 1. Metric-Level Signals

Metric-level signals represent the interpreted state of one metric on one date.

Examples:
- Korea memory exports YoY growth.
- OpenRouter provider token-share 28-day change.
- PyPI package download 28-day growth.
- Hugging Face model download acceleration.
- Taiwan semiconductor monthly revenue YoY growth.
- Copper spot-price 13-week momentum.
- Artificial Analysis intelligence rank change.

Metric-level signals should keep raw values, transformed values, baselines, and scoring fields in the same row so they are easy to inspect and debug.

### 2. Asset-Level Signals

Asset-level signals aggregate metric-level signals through a mapping registry.

Examples:
- SK Hynix receives a bullish memory-cycle signal when Korea memory exports and memory PPI improve versus baseline.
- Micron receives a bullish memory-cycle signal from the same memory metrics, with different mapping confidence if desired.
- A copper miner receives a bullish signal from copper price momentum, while a copper-intensive manufacturer may receive a bearish input-cost signal from the same metric.

The same metric can map to different assets with different expected directions.

### 3. Theme-Level Signals

Theme-level signals aggregate metric-level or asset-level signals by investment theme.

Initial themes:
- `ai_model_adoption`
- `ai_infra_demand`
- `ai_capex_cycle`
- `developer_ecosystem`
- `memory_cycle`
- `foundry_cycle`
- `semicap_equipment`
- `consumer_demand`
- `travel_demand`
- `gaming_demand`
- `drug_demand`
- `critical_minerals`
- `industrial_cycle`
- `input_cost_pressure`

Theme signals are useful for dashboards and later alert digests because they summarize broad shifts without forcing every signal into a single stock call.

## Core Data Model

### `signal_metric_registry`

Purpose:
- Define each metric that can produce a signal.

Initial fields:
- `metric_id`
- `source`
- `dataset_id`
- `date_column`
- `value_column`
- `entity_columns`
- `cadence`
- `transform`
- `baseline_method`
- `baseline_window`
- `seasonality_mode`
- `higher_is_better`
- `default_metric_direction`
- `description`
- `caveats`

Rules:
- `metric_id` must be stable and human-readable.
- Registry rows should describe the metric, not a particular computed observation.
- `higher_is_better` and `default_metric_direction` are defaults only; asset mappings can override direction.

### `signal_asset_mapping`

Purpose:
- Map metrics to stocks and themes.

Initial fields:
- `metric_id`
- `ticker`
- `company_name`
- `asset_type`
- `theme`
- `exposure_type`
- `expected_direction`
- `weight`
- `lag_days`
- `confidence`
- `notes`

Expected exposure types:
- `direct_revenue_proxy`
- `supplier_proxy`
- `customer_demand_proxy`
- `input_cost_proxy`
- `competitive_threat`
- `ecosystem_adoption`
- `macro_cycle_proxy`
- `valuation_context`

Rules:
- A single metric can map to multiple assets.
- A single metric can be bullish for one asset and bearish for another.
- Confidence should be explicit, using simple labels such as `high`, `medium`, and `low`.
- Mapping notes should explain why the metric matters for the asset.

### `metric_signals`

Purpose:
- Store computed metric-level signals.

Initial fields:
- `metric_id`
- `source`
- `as_of_date`
- `entity_key`
- `entity_name`
- `latest_value`
- `comparison_value`
- `raw_change`
- `pct_change`
- `yoy_change`
- `rolling_change`
- `z_score`
- `robust_z_score`
- `percentile`
- `rank`
- `rank_change`
- `baseline_value`
- `baseline_method`
- `baseline_window`
- `baseline_observation_count`
- `empirical_percentile`
- `tail_probability`
- `effect_size`
- `signed_stat`
- `metric_direction`
- `signal_state`
- `confidence`
- `source_updated_at`
- `quality_state`
- `quality_issues`
- `caveats`

Rules:
- Not every field applies to every metric. Unused transform fields can be null.
- Statistical fields should be traceable to the configured baseline window.
- `tail_probability` should represent how unusual the observation is versus its baseline, not a model-implied investment probability.
- `signed_stat` should preserve direction using the metric's configured interpretation, so positive means directionally positive for the metric and negative means directionally negative.
- `metric_direction` should describe the metric itself: `positive`, `negative`, or `ambiguous`.
- `signal_state` should use simple labels: `bullish`, `bearish`, `neutral`, or `watch`.
- `quality_state` should make the data eligibility result explicit before anyone interprets the signal.

Expected `quality_state` values:
- `valid`
- `insufficient_history`
- `stale`
- `duplicate_grain`
- `low_coverage`
- `invalid_values`
- `partial_period`
- `unvalidated_source`

### `asset_signals`

Purpose:
- Store stock-level signals derived from `metric_signals` and `signal_asset_mapping`.

Initial fields:
- `ticker`
- `company_name`
- `asset_type`
- `as_of_date`
- `theme`
- `combined_signed_stat`
- `combined_tail_probability`
- `median_signed_stat`
- `positive_evidence_count`
- `negative_evidence_count`
- `bullish_metric_count`
- `bearish_metric_count`
- `neutral_metric_count`
- `top_metric_id`
- `top_metric_description`
- `driver_count`
- `signal_state`
- `confidence`
- `summary`

Rules:
- Asset-level outputs should be traceable back to contributing metric IDs.
- `top_metric_id` should identify the strongest contributor by absolute statistical surprise.
- `summary` should be generated from deterministic templates at first, not an LLM.

### `theme_signals`

Purpose:
- Store theme-level summaries for dashboard and digest use.

Initial fields:
- `theme`
- `as_of_date`
- `combined_signed_stat`
- `combined_tail_probability`
- `median_signed_stat`
- `positive_evidence_count`
- `negative_evidence_count`
- `active_metric_count`
- `active_asset_count`
- `top_metric_id`
- `top_ticker`
- `signal_state`
- `confidence`
- `summary`

## Metric Transforms

V1 should support a small set of reusable transforms:

- `latest_value`: latest observed value.
- `period_change`: absolute change versus previous period.
- `pct_change`: percent change versus previous period.
- `yoy_growth`: year-over-year growth for seasonal or monthly series.
- `rolling_growth`: change versus a rolling average, such as 7-day, 28-day, 4-week, or 3-month.
- `acceleration`: current growth minus previous growth.
- `percentile`: latest value or growth rate versus a trailing baseline window.
- `z_score`: standard z-score versus a trailing baseline.
- `robust_z_score`: median/MAD-based z-score for noisy data.
- `rank_change`: current rank minus prior rank.
- `share_change`: change in market share or token share.
- `breadth`: number of related series confirming the same direction.

Baseline windows should be configured per metric. Suggested defaults:
- high-frequency data: trailing 90 days or trailing 52 weeks,
- monthly macro and semiconductor data: trailing 24 to 36 months,
- adoption data: trailing 28 days and trailing 90 days,
- rank data: previous observation and trailing 30 to 90 days,
- commodity prices: trailing 52 weeks and trailing 3 years where available.

## Metric Eligibility Gates

Before a row can become an interpreted metric signal, the builder should run a data eligibility gate. The gate should produce `quality_state` and `quality_issues` fields and should prevent weak data from becoming a confident bullish or bearish signal.

Minimum gates:
- valid grain: the source table must be unique at the declared metric grain after canonicalization,
- freshness: the latest source observation must be within the source's expected lag window,
- baseline size: the metric must meet its configured minimum baseline observation count,
- value validity: values must pass source-specific range and sign checks,
- period completeness: partial periods must either be excluded or explicitly labelled,
- coverage: metrics based on joins or pricing coverage must meet configured coverage thresholds,
- source validation: known parser or extraction issues must block signal interpretation until resolved.

Default behavior:
- `valid` rows may receive bullish, bearish, watch, or neutral states based on statistical evidence.
- `insufficient_history`, `stale`, `duplicate_grain`, `low_coverage`, `invalid_values`, `partial_period`, and `unvalidated_source` rows should default to `watch` or `neutral`.
- Invalid rows should remain visible in outputs with caveats rather than being silently dropped.

## Source-Specific V1 Scope

### OpenRouter

Initial signals:
- provider token share change,
- provider token volume growth,
- model rank change,
- 7-day and 28-day request/token growth,
- task-level spend growth only after multiple comparable task-spend snapshots exist,
- estimated revenue growth only where pricing coverage is sufficient,
- usage concentration or fragmentation.

Data-side notes:
- token volume and share signals are safer v1 metrics than revenue signals,
- provider/model history is uneven, so baseline observation counts must be checked per provider/model pair,
- task-spend data currently may be snapshot-only for some windows and should be labelled `insufficient_history` until a time series exists,
- estimated revenue metrics require pricing coverage checks by row count and token share before interpretation.

Useful mappings:
- AI labs and their public backers where applicable,
- cloud and AI infrastructure providers,
- semiconductor and compute supply-chain beneficiaries,
- software names exposed to coding-agent adoption.

### Provider Adoption

Initial signals:
- PyPI package download growth,
- npm package download growth,
- GitHub provider signal repo-count growth,
- GitHub matched-signal breadth by signal type,
- Hugging Face model download acceleration,
- provider momentum change,
- cross-source provider breadth count.

Data-side notes:
- PyPI and npm package downloads have enough daily history for simple baselines, but npm rows need canonicalization because older uncategorized rows can coexist with newer categorized rows,
- Hugging Face model-level history is uneven and many models have short or zero-heavy histories, so model-level signals need per-model baseline gates,
- GitHub adoption counts are useful as provider-level breadth metrics but should not be treated as complete market adoption,
- source breadth is more robust than any single adoption source.

Useful mappings:
- public AI platforms,
- cloud providers,
- developer tooling ecosystems,
- AI application and infrastructure themes.

### Semiconductor

Initial signals:
- Korea export YoY and MoM growth,
- memory PPI YoY and MoM growth,
- Taiwan monthly revenue YoY and MoM growth,
- 3-month moving-average growth,
- export/revenue acceleration,
- memory-cycle and foundry-cycle regime classification.

Data-side notes:
- monthly semiconductor and Taiwan revenue series have enough history for YoY, rolling, and regime baselines,
- release lag and preliminary/revised flags should be preserved because stale or revised monthly data can otherwise look like a new signal,
- category, region, unit, and currency must be part of the metric grain to avoid mixing incompatible trade series,
- FRED memory PPI is statistically usable but should stay separated from narrative/vision-extracted ADATA fields unless those fields pass source validation.

Useful mappings:
- SK Hynix,
- Samsung Electronics,
- Micron,
- TSMC,
- UMC,
- VIS,
- ASML,
- Applied Materials,
- Lam Research,
- KLA,
- other semicap names as mapping confidence allows.

### Minerals

Initial signals:
- spot-price weekly and monthly change,
- 13-week momentum,
- percentile versus trailing 1-year and 3-year windows,
- drawdown from peak,
- direct and proxy mineral signal state from the existing minerals pipeline,
- stock exposure evidence from the existing mineral-stock mapping.

Data-side notes:
- live mineral price series and the existing mineral-stock mapping are better v1 candidates than USGS extracted metrics,
- USGS `net_import_reliance` extraction must be validated before use because parser contamination can turn years such as `2021` or `2025` into percentage values,
- input-cost mappings should be tested carefully because a mineral price increase can be bullish for producers and bearish for consumers,
- mapping purity and primary-exposure flags should remain visible in stock-level outputs.

Useful mappings:
- miners and producers as positive exposure,
- industrial consumers as input-cost exposure,
- defense, EV, battery, and electrification themes.

### Artificial Analysis

Initial signals after the first four domains are stable:
- intelligence rank change,
- price/performance percentile,
- latency percentile,
- context-window expansion,
- frontier gap versus peers,
- model release cadence,
- capex YoY and QoQ growth.

### Google Trends

Initial signals after watchlist quality is reviewed:
- search-interest YoY growth,
- rolling 4-week growth,
- percentile versus prior 52 weeks,
- breakout above a seasonal baseline,
- keyword-stock lead/lag correlation where enough history exists.

Google Trends should be handled carefully because seasonality, geography, and keyword ambiguity can produce false positives.

## Statistical Signal Measurement

V1 should avoid blended scores with arbitrary component weights. The first version should report statistically interpretable surprise measures and keep any economic mapping confidence as separate metadata.

Metric-level measurement:
- compute the configured transform, such as YoY growth, rolling growth, share change, or rank change,
- compare the transformed value with the metric's configured historical baseline,
- report the baseline observation count,
- report an empirical percentile within the baseline window,
- report a robust z-score where enough history exists,
- report a tail probability based on the empirical distribution,
- report an effect size, such as latest transformed value minus baseline median divided by baseline MAD or standard deviation,
- report a signed statistic where the sign follows the configured metric direction.

Default statistical approach:
- use median and MAD-based robust z-scores for noisy adoption, search, and commodity series,
- use standard z-scores only when the baseline distribution is reasonably stable,
- use empirical percentiles when sample sizes are small or distributions are non-normal,
- require a minimum baseline observation count before emitting a strong interpretation,
- keep insufficient-history rows as `watch` or `neutral` rather than forcing a bullish or bearish label.

Asset-level aggregation should be statistical, not a hand-weighted blend. The default aggregation is a signed Stouffer-style statistic over mapped metric surprises:

```text
combined_signed_stat =
  sum(signed_stat_i * sqrt(exposure_weight_i))
  / sqrt(sum(exposure_weight_i))
```

Where:
- `signed_stat_i` is the metric surprise after applying the asset mapping's expected direction,
- `exposure_weight_i` is a registry field that represents economic exposure, not a tuning weight,
- mapping confidence is reported separately and should not be multiplied into the statistic in v1.

Because alternative-data metrics are often correlated, the combined statistic should be treated as descriptive evidence rather than a formal independent p-value. The output should therefore include:
- `combined_signed_stat`,
- `combined_tail_probability`,
- `median_signed_stat`,
- positive and negative evidence counts,
- contributing source count,
- strongest single metric driver.

Signal states should be derived from statistical evidence rules, not arbitrary blend-score thresholds. Initial rules:
- `bullish`: enough baseline history exists and the signed evidence is materially positive by robust z-score or empirical tail probability,
- `bearish`: enough baseline history exists and the signed evidence is materially negative by robust z-score or empirical tail probability,
- `watch`: the move is unusual but history is thin, sources conflict, or mapping confidence is low,
- `neutral`: evidence is not statistically unusual versus baseline.

The exact thresholds for "materially positive" and "materially negative" should be named configuration values tied to statistical conventions, such as two-sided 10%, 5%, and 1% empirical tail levels or robust z-score bands. They should not be hidden inside blended formulas.

## Output Artifacts

Proposed output layout:
- `data/reference/signal_layer/signal_metric_registry.csv`
- `data/reference/signal_layer/signal_asset_mapping.csv`
- `data/processed/signals/metric_signals.csv`
- `data/processed/signals/metric_signals.parquet`
- `data/processed/signals/asset_signals.csv`
- `data/processed/signals/asset_signals.parquet`
- `data/processed/signals/theme_signals.csv`
- `data/processed/signals/theme_signals.parquet`
- `data/processed/signals/latest_signal_run.json`

CSV outputs are for inspection and review. Parquet outputs are for downstream analysis, dashboard loading, notebooks, and future alert jobs.

## Pipeline Design

### Registry Loading

Load metric definitions and asset mappings from reference CSV files.

Responsibilities:
- validate required columns,
- validate metric IDs are unique in the metric registry,
- validate mapped metric IDs exist,
- normalize confidence and direction labels,
- reject invalid weights or missing tickers for asset mappings.

### Metric Signal Builders

Each source domain should have a small builder that reads the existing normalized datasets and emits `metric_signals` rows.

Initial builders:
- OpenRouter signal builder,
- provider adoption signal builder,
- semiconductor signal builder,
- minerals signal builder.

Later builders:
- Artificial Analysis signal builder,
- Google Trends signal builder.

Builders can be source-specific internally, but they must output the common schema.

Builder responsibilities:
- canonicalize each input to the declared metric grain before transformation,
- resolve duplicate source rows using source-specific rules, such as latest run wins or prefer enriched/categorized rows,
- compute and attach metric eligibility gates,
- preserve source freshness and coverage fields needed for caveats,
- emit invalid or immature metric rows with explicit quality states rather than hiding them.

### Aggregation

Shared aggregation logic should:
- join `metric_signals` to `signal_asset_mapping`,
- apply mapping direction, lag, weight, and confidence,
- compute asset-level statistical evidence,
- identify top drivers,
- aggregate theme-level outputs,
- generate deterministic summaries.

Aggregation rules:
- only `valid` metric rows should contribute to combined statistical evidence by default,
- non-valid rows should be counted and surfaced as caveats,
- asset and theme summaries should include evidence counts by quality state,
- combined tail probabilities should be labelled descriptive because mapped metrics are often correlated.

### Storage

Write metric, asset, and theme signals as CSV and parquet.

The storage layer should preserve stable schemas and avoid rewriting unrelated reference files.

### Validation

Minimum checks:
- metric registry has unique `metric_id` values,
- asset mapping references valid metric IDs,
- metric signals use registered metric IDs,
- statistical fields are within expected ranges,
- signal states are from the allowed set,
- quality states are from the allowed set,
- source tables are unique at declared metric grain after canonicalization,
- baseline observation counts meet metric-specific requirements before strong interpretation,
- pricing or join coverage metrics meet declared thresholds before revenue-like signals are interpreted,
- at least one metric signal is produced for each enabled source,
- asset signals can be traced back to contributing metric IDs,
- output files are written successfully.

## Repo Integration

The existing repo uses source-oriented packages with `models`, `pipeline`, `storage`, `cli`, and tests. The signal layer should follow that pattern.

Proposed package:
- `src/signal_layer/`

Expected modules:
- `src/signal_layer/__init__.py`
- `src/signal_layer/models.py`
- `src/signal_layer/registry.py`
- `src/signal_layer/transforms.py`
- `src/signal_layer/builders/openrouter.py`
- `src/signal_layer/builders/provider_adoption.py`
- `src/signal_layer/builders/semiconductor.py`
- `src/signal_layer/builders/minerals.py`
- `src/signal_layer/aggregation.py`
- `src/signal_layer/storage.py`
- `src/signal_layer/pipeline.py`
- `src/signal_layer/cli.py`

Potential CLI:

```bash
signal-layer --base-dir . build
signal-layer --base-dir . validate-registry
signal-layer --base-dir . build --sources openrouter,provider_adoption
```

## Testing Strategy

Unit tests:
- registry validation,
- source canonicalization and duplicate-grain handling,
- metric eligibility gates,
- transform calculations,
- confidence and direction normalization,
- metric-level statistical baseline calculations,
- asset-level aggregation,
- theme-level aggregation,
- deterministic summary generation.

Fixture tests:
- small OpenRouter dataset,
- small provider adoption dataset,
- small semiconductor monthly dataset,
- small minerals signal dataset,
- minimal mapping registry.

Integration tests:
- run the signal pipeline against fixture normalized inputs,
- assert expected metric and asset signals,
- assert output schemas,
- assert validation failures are clear for invalid mappings.

## Implementation Sequence

1. Add reference schema files with a small initial mapping set.
2. Add registry models and validation.
3. Add quality-state enums, canonicalization helpers, and metric eligibility gates.
4. Add reusable transform and statistical baseline helpers.
5. Add the first source builders for OpenRouter, provider adoption, semiconductors, and minerals.
6. Add asset and theme aggregation.
7. Add storage and CLI.
8. Add tests.
9. Inspect generated outputs and calibrate statistical evidence bands before adding alerts.

## Open Decisions

These decisions can be made during implementation without changing the overall design:
- exact first set of mapped tickers,
- exact statistical evidence bands after initial output inspection,
- exact first metric set inside each of the four v1 domains,
- whether Google Trends requires a separate watchlist-cleanup step before signal generation in a later phase.

## Success Criteria

The phase is successful when:
- metric-level signals are generated from at least four source domains,
- the four v1 source domains are OpenRouter, provider adoption, semiconductors, and minerals,
- stock-level signals are generated from metric mappings,
- theme-level signals summarize major domains,
- outputs are explainable and traceable to source metrics,
- tests cover registry validation, transforms, and aggregation,
- the design can support future alerts without reworking the signal model.
