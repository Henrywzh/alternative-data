# Research Control Tower V1

Research Control Tower is a local/private, read-only Streamlit research
surface for evidence-first review of registered entities, listings, baskets,
events, macro observations and permitted provider metadata. It is independent
of the Asia Markets production dashboard: it has its own manifest-bound local
artifact bundle and does not run Asia Markets collectors, attach a sibling
DuckDB, or write canonical research data. An explicit local export may provide
provider-specific consensus metadata; that does not make the Control Tower a
cross-market collection service.

## Build the local bundle

Run from the repository root with every build input explicit:

```bash
python -m src.research_control_tower.cli build \
  --registry-root config/research_control_tower \
  --event-root config/research_control_tower \
  --output-dir apps/research-control-tower/.generated \
  --as-of-utc 2026-08-13T12:00:00Z \
  --build-id task8-local-20260813
```

The build is local and network-forbidden. The required inputs are the
registry CSVs and event CSVs named by the registry/event roots. Macro,
consensus, news and filing inputs are optional local inputs. Missing or
unavailable optional inputs produce a `degraded` publication, a typed-empty
artifact where the schema requires one, and a visible source-health reason;
they are not represented as successful live coverage. Required artifact or
manifest failures stop the build.

The output is a publication, not a loose directory of interchangeable files:

```text
apps/research-control-tower/.generated/
├── CURRENT                         # one relative target, newline terminated
└── generations/
    └── <generation-id>/             # 15 Parquet marts + build_manifest.json
```

`CURRENT` must point to `generations/<generation-id>`. The generation manifest
must agree with that pointer, its generation ID, artifact names, schemas,
hashes, row counts and status. The app reads the generation selected by
`CURRENT`; it does not discover the newest directory or merge generations.

## Run locally

After a successful or explicitly degraded build:

```bash
streamlit run apps/research-control-tower/app.py \
  --server.headless true \
  --server.address 127.0.0.1 \
  --server.port 8511 \
  --server.fileWatcherType none
```

Open `http://127.0.0.1:8511`. Navigation reads only the selected local
bundle. It does not fetch source links, run collectors, refresh providers, or
write the bundle/canonical inputs. Source links are metadata for a researcher
to inspect separately; the app does not open them during navigation.

## Optional quote refresh

The external collector is separate from Streamlit. It uses the free yfinance
minute-bar endpoint and labels the result `delayed`; it does not claim exchange
real-time entitlement or bid/ask coverage:

```bash
python scripts/research_control_tower_quote_collector.py \
  --listings config/research_control_tower/listings.csv \
  --output /tmp/control-tower-quotes.parquet

python -m src.research_control_tower.cli build \
  --registry-root config/research_control_tower \
  --event-root config/research_control_tower \
  --output-dir apps/research-control-tower/.generated \
  --as-of-utc 2026-08-13T12:00:00Z \
  --build-id quote-refresh-20260813T1200Z \
  --quote-input 'market:yfinance|/tmp/control-tower-quotes.parquet|parquet|quote_snapshots_v1'
```

The collector can be scheduled every 30–60 seconds, but displayed freshness
remains `delayed` unless a provider adapter with explicit real-time entitlement
is used. The Streamlit app itself never calls the provider.

## Privacy and licensing boundary

Portable artifacts are metadata/value marts, not raw-source archives. News and
filings are metadata-only: headline, publisher, timestamps, identifiers,
source URL, language, classification, PIT/licence labels and permitted hash or
derived-summary fields. Full article/filing bodies, HTML, response envelopes,
request headers, cookies, credentials and raw provider payloads are excluded.

Provider-specific consensus rows are allowed only when an explicit local
export records the provider, metric/statistic, period, timestamps, PIT class,
license class and coverage reason. Futu, IBKR, Finnhub, Marketaux, FMP,
Alpha Vantage and FnGuide may be unavailable or entitlement-required; their
absence is not silently rendered as a successful empty feed. A source URL is
link metadata, not permission to copy linked content.

## Hosting-readiness checklist

Before hosting or sharing a deployment, confirm:

- the build is reproducible from explicit local inputs and the `CURRENT` /
  `generations/` contract is stable;
- the complete generated bundle passes the format-aware privacy scan and the
  relevant source-license audit;
- no credential, secret URL, request header, raw body or licensed payload is
  present in the portable files;
- the app has no collector, network-fetch or canonical-write dependency and
  does not require the sibling `financial-data` runtime database;
- resource limits, artifact size, process lifecycle, loopback/proxy policy and
  any authentication boundary have been reviewed for the intended host; and
- browser QA has separately checked the hosted environment for console,
  network, responsive-layout and link-target behavior.

Hosting is a follow-on review. Local/private operation and passing automated
tests do not by themselves establish redistribution rights or deployment
readiness.
