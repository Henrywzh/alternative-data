# Streamlit Parity Protocol

This is the shared playbook for deciding whether a change to the public
Cloudflare Asia Markets dashboard should also affect the private Streamlit
research terminal.

All agents working on Asia Markets should read this file when a Cloudflare
artifact, chart, dataset, source contract or dashboard package changes. The
repository GitHub Action also checks for structural Cloudflare changes and
posts a reminder automatically; no user memory or manual trigger phrase is
required.

## The two surfaces have different jobs

- Cloudflare is the public, source-status and long-history monitoring surface.
- Streamlit is the private research surface for richer interaction, high-
  frequency analysis and derived signals.
- A Cloudflare change must not be copied into Streamlit automatically.
- Streamlit should receive a change only when it improves research use:
  high-frequency data, a useful derived signal, an interactive comparison, or
  a clearly useful drill-down.

## What counts as a parity event

The reminder is important when a Cloudflare change:

- adds or removes a chart, card, table or dataset;
- changes a chart's dataset, series, encoding, unit, cadence or definition;
- changes a source contract, sector roster or artifact builder;
- adds a genuinely new historical or high-frequency data family;
- changes a caveat that affects how the metric should be interpreted.

The reminder is intentionally quiet for:

- a routine refresh of existing snapshot values;
- a new dataAsOf, row count or freshness value with the same artifact
  structure;
- generated HTML or status-file value changes that do not change the data
  contract.

The GitHub Action compares artifact structure rather than raw rows so the daily
Cloudflare refresh does not create a noisy Streamlit task every day.

## Decision tree

For every parity reminder:

1. Identify the affected sector, chart/dataset and source cadence.
2. Decide whether the change is:
   - Streamlit now;
   - Streamlit later, after more history or quality checks;
   - Cloudflare only;
   - blocked or not suitable for Streamlit.
3. If it belongs in Streamlit, choose the destination:
   - sector page;
   - Data Explorer;
   - Source Health;
   - Overview pulse;
   - a future derived-signal module.
4. Preserve the source grain and observation date. Do not make a snapshot look
   like a trend.
5. Run the focused Streamlit tests and a browser check before calling it done.

## Current Streamlit scope

The current Streamlit app connects:

- `market_monitor` (Index & ETF Allocation Monitor; Streamlit-native in V1);
- hk-labour-market;
- hk-population-migration;
- hk-transport (Airlines + MTR only in V1).
- hk-stablecoin-crypto (global market context only in V1).

All other Cloudflare sectors are currently Cloudflare-only or future scope
unless an explicit implementation adds them to the Streamlit artifact loader
and sidebar.

`market_monitor` is the explicit exception to the parity workflow: it is
already a Streamlit product surface and is intentionally not wired into the
Cloudflare sector roster or portable package. Its JSON artifact is a shared
read contract, not a request to publish the feature publicly.

Current Overview rules:

- each connected sector may contribute at most three compact pulse metrics;
- a pulse sparkline must show its title, latest value, plotted observation
  count, cadence and plotted date range;
- the 精选走势 / Featured Trends section remains blank until higher-frequency
  inputs and validated derived signals are available;
- future sectors enter the compact sector pulse by default, not as a full set
  of Overview charts;
- Overview has a maximum of two featured chart slots when they are eventually
  enabled.

## Required validation

For a Streamlit parity implementation, run:

    python -m py_compile apps/asia-markets-streamlit/app.py
    pytest -q tests/test_asia_markets_streamlit_overview.py

Then run the Streamlit AppTest smoke flow for Overview, Labour, Population,
Transport, Crypto, Data Explorer and Source Health, followed by a browser check at
http://127.0.0.1:8501.

## Automatic reminder behavior

.github/workflows/streamlit-parity-reminder.yml runs on relevant pull
requests and pushes. It:

1. compares the Cloudflare artifact contracts between the base and head
   revisions;
2. ignores value-only refreshes;
3. writes a workflow summary for every relevant change;
4. updates one non-blocking pull-request comment when a Streamlit decision is
   needed;
5. updates one open reminder issue for a direct push that needs a decision, so
   a main-branch workflow does not silently disappear into the Actions log.

The workflow is intentionally advisory first. It does not block Cloudflare
deployment, because “Cloudflare only” is a valid decision and Streamlit should
not be forced to mirror every public monitor.

## Decision record template

When a reminder results in a meaningful decision, record it in the PR
description, commit notes or the relevant project status document:

    Cloudflare change:
    Affected sector/dataset:
    Streamlit decision: now / later / Cloudflare only / blocked
    Destination:
    Reason:
    Validation:
