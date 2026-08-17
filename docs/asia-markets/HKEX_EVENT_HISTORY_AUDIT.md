# HKEX event-history expansion audit

Status: research-only audit; the sibling financial-data catalog was refreshed
through its append-only HKEX collection path, but no trading signal or
production dashboard registration was opened.

## Finding

The current canonical event layer is not a short slice of a larger historical
event tape hidden in the migrated tables. After the targeted 2026-08-08 HKEX
metadata re-fetch:

| Layer | Rows | Distinct event IDs / filings | Announcement range | PIT caveat |
|---|---:|---:|---|---|
| `hkex_announcement_events` | 223 | 223 event IDs | 2026-07-07 to 2026-08-07 | 16 observed-collection rows, 207 source-timestamp proxies |
| `_hkex_announcement_events_migrated` | 660 | 223 event IDs | same range | 216 event IDs repeat 3 times and one repeats 6 times; all IDs overlap canonical |
| `hkex_filings` | 934 | 934 filings | 2026-06-29 to 2026-08-07 | 0 rows missing `available_at`; 907 source-timestamp proxies and 27 observed-collection rows |
| `_hkex_filings_migrated` | 1,911 | 934 filings | same range | 948 rows still lack PIT fields in legacy migrated duplicates; migrated layer is not a PIT source |

The migrated announcement table therefore cannot be used as a sample
expansion by row-count. Its repeated rows have the same event ID, URL and
content hash, with collection/availability replay differences. Deduplicating
to event ID returns the same 223-event universe.

## Inclusion rule

The event study continues to read only the canonical
`hkex_announcement_events` table. The broader `hkex_filings` table is a
discovery queue for future event-family expansion, not a PIT backtest input:
ordinary dividends, director changes, capital actions and miscellaneous
announcements require explicit event definitions and availability validation
before inclusion.

Historical sample expansion must come from additional dated HKEX collection
runs or a separately verified historical source. The 162 legacy rows were
recovered by querying the official HKEX title-search endpoint, matching
`FILE_LINK` to `document_url`, parsing `DATE_TIME` as HKT, and deriving a
10-minute `source_timestamp_proxy`. They are not observed live collections.
The migrated duplicates remain excluded from PIT research.

The current candidate inventory is written by
`scripts/audit_hkex_filing_candidates.py`: 949 filing rows resolve to 223
canonical rows, 162 PIT-recovery-sidecar rows explicitly blocked from event
study, 488 discovery candidates, and 76 composite-category rows. There are no
remaining missing-PIT rows in the canonical filing catalog. Discovery
candidates are not trading signals; their `pit_status` still distinguishes
observed collection from a historical source-timestamp proxy.

An isolated exploratory mode is now available with
`--candidate-inventory outputs/hkex_filing_candidate_inventory/hkex_filing_candidate_inventory.csv`.
It admits only PIT-complete, non-composite, named families (`business_update`,
`capital_action`, `director_change`, `dividend`, `governance`,
`inside_information`, `results`, `trading_update`), excludes `other` and
`transaction`, and limits candidates to the inventory's eligible tickers. The
exploratory replay explicitly excludes the 162 sidecar filing IDs, then adds
174 candidate event rows to the 223 canonical rows (397 source events total,
268 eligible-entry clusters). The targeted yfinance archive expands the
candidate ticker set to 21 tickers; interval coverage is audited separately,
so `7688.HK` remains in the event sample as an explicit
`missing_5m_bars_in_snapshot` gap rather than disappearing from coverage. A
direct raw/prefixed-ID audit finds zero sidecar overlap in both candidate
outputs. The candidate outputs are written separately under
`outputs/hkex_event_study_candidates/` and
`outputs/hkex_event_study_candidates_pit_recovered/` and remain globally
blocked. All covered candidate rows are still source-timestamp proxies.

The recovery run used `financial-data`'s existing parser and availability
contract. A live verification found that the HKEX servlet silently ignores
generic `from`/`to` query names; `fetch_announcements()` now uses the official
`fromDate`/`toDate` names and has a regression test. The first pre-fix run was
not used as a PIT recovery input; the corrected run succeeded for all 81
target tickers and wrote 320 changed/new filing rows.

The recovery proof is persisted separately under
`outputs/hkex_pit_recovery_sidecar/`: 162 legacy rows are matched to official
HKEX `DATE_TIME`/`FILE_LINK` metadata, all use the exact 10-minute proxy
delta, and all remain `event_study_eligible=false`. This sidecar is evidence
of timestamp recovery, not an event-study inclusion list. Each dashboard
artifact surfaces the same proof under `pit_recovery_summary`, separate from
active-event PIT coverage.
Each artifact's top-level `manifest.metadata` also records the contributing
`archive_capture_ids`, whether the replay used one capture or the merged
manifest archive, the distinct 5m/1h cutoff lists and counts, the canonical
symbol count, and the candidate expansion count. This makes the provenance
boundary inspectable without parsing nested coverage rows.

The registry retains the legacy `status` label for compatibility but now also
publishes `statistical_gates_passed`, `sample_tier`, and
`trading_execution_eligible`. The latter is false unless explicit registration,
all statistical gates, and the global market/PIT gate all pass. With the
current 30-cluster minimum, small samples remain `blocked`; rows with enough
clusters but failed statistics remain `exploratory`, not tradable.

The candidate-specific coverage audit keeps 35 covered event rows with
unexpected same-session bar holes visible rather than interpolating them: 12
reject only the 1h derived horizon, 11 reject 30m and 1h, and 12 reject
5m/30m/1h. Thirty are overnight/opening-session cases and five cross the lunch
boundary. The 5m-derived 1h path remains the primary event-aligned result;
native 1h is retained as a separate clock-bar sensitivity and is not used as a
silent fallback because its entry alignment is different. In the candidate
scope, 5m/30m/1h event-row return coverage is 362/351/339, while native 1h
coverage is 376 rows. Dashboard event detail exposes both paths, the rejected
horizons and the market-data gap reason.

The inventory contains 349 `candidate_family=other` rows (294 discovery,
50 sidecar-blocked and 5 composite-blocked), dominated by routine monthly
returns, overseas or miscellaneous administrative notices, share-buyback
disclosure returns and company-information forms. The current audit keeps
those `other` rows excluded. One eligible `7688.HK` voluntary announcement
with an explicit on-market share-repurchase intention is narrowly promoted to
`capital_action` using
`candidate_family_basis=title_material_repurchase_override`. The three
comparable sidecar-blocked material disclosures remain isolated, and routine
next-day buyback returns remain excluded. The
`1647.HK` and `2477.HK` rows are ordinary monthly equity-movement returns and
are not reclassified. The new classification was replayed and coverage
reviewed; it adds one event but does not unlock signal registration because
the market archive still has only one distinct cutoff and one missing 5m
candidate ticker.

The canonical event-study output now preserves the raw parser direction and
confidence beside the title-derived direction. In the full 223-event snapshot,
raw labels are `unknown=206`, `positive=7`, `negative=5`, `mixed=5`; four raw
versus title conflicts are recorded, including `negative->positive` for a
positive-profit-alert title. All four are the narrow generic
`EARNINGS_WARNING`/high-precision-title case and are reconciled with explicit
`category_generic_title_override` provenance; unresolved review rows are now
zero. A valid raw label with no high-precision title match is not treated as a
conflict. Raw labels remain audit evidence, not truth. Any future unresolved
queue is written to
`outputs/hkex_event_study_yfinance/event_direction_conflicts.csv`.

The persisted event detail makes the return decomposition explicit:
`opening_gap_return` plus post-entry `*_drift_return` compound into
`total_*_return`; the corresponding HSI gap and drift components are retained
so `total_*_abnormal_return` can be independently reconciled. Direction-signed
drift and total abnormal returns are populated only for resolved positive or
negative rows; unknown, mixed and `review_required` rows remain null for this
efficacy view.

Clusters carry `cluster_document_count`, `cluster_co_occurring_types`,
`is_multi_document_cluster` and `is_pure_event_type`. In the current full
replay, 11 of 176 eligible-entry clusters contain multiple documents, 170 are
single-primary-type clusters, and 12 type-representative rows are in mixed-type
clusters. Robustness, stratified, gap/drift, native-1h sensitivity and registry
artifacts use the conservative `resolved_impact_direction` grain; raw/title-
derived labels stay in the event detail for audit.

Among non-canonical, non-composite rows, the largest strict observed buckets
are director changes (3 rows), dividends (3), capital actions (2), governance
(2) and generic inside-information announcements (2). None has enough strict
observed observations to support a standalone event-study signal; the next
step is to accumulate these categories across dated collection runs and keep
proxy-only rows as a separate exploratory stratum.

## Current consequence

The yfinance event-study archive currently covers one market cutoff. As of the
2026-08-08 refresh, it contains four captures: three canonical-universe
captures, including `20260808T100430Z`, plus one candidate-only capture. The
latest captures were collected on Saturday and yfinance returned the same
2026-08-07 market bars. The three canonical captures are useful for exact
replay consistency, but not independent market observations. Signal registration remains blocked until the archive has
clean coverage and multiple distinct market cutoffs, followed by event-level
and cluster-level robustness checks.

The capture comparison now compares the native-1h returns and coverage fields
in addition to the 5m/30m/1h returns. A pair is considered an independent
cutoff pair only when both the 5m and 1h market cutoffs differ; a difference in
only one interval is reported as partial and does not unlock robustness.

The event-study output also includes
`event_native_1h_sensitivity.csv`. The primary 1h result remains a 12×5m
open-to-open drift; the native-1h view is a separate next-native-bar
sensitivity. It currently covers 205/223 full-universe rows, and its differences
from the 5m-derived result can be material for interim-results and small-sample
groups, so it is not used for signal registration.
The current full replay has 182 comparable native-vs-derived 1h rows, a global
directional agreement rate of 92.86%, and a mean absolute abnormal-return
difference of 0.405 percentage points. These are sensitivity diagnostics, not
an attempt to choose the more favorable granularity.

The native-1h sensitivity is stratified by `session` because lunch-break and
overnight/pre-open events do not have the same execution delay as intraday
events. Both the 5m-derived and native-1h paths require the first bar to be
strictly later than `available_at`, and exact benchmark labels are required;
there is no interpolation. The event detail also records `bar_hole_horizons`.
In the current full-universe replay, 23 event rows have at least one rejected
horizon because an unexpected same-session bar gap would otherwise make a
positional offset silently lengthen the holding period. Those horizons are
missing rather than repaired. No native-1h row currently has a bar-hole.

The CLI now treats `--top-tickers 0` as the full event universe and uses that
as the default; use `--top-tickers 30` only for the smaller top-30 sensitivity.

For the next trading-day refresh, the collector can resolve the current event
universe without a hand-maintained ticker list:

```bash
python scripts/capture_yfinance_intraday.py \
  --from-event-universe --audit-after \
  --output-root data/raw/market_data/yfinance
```

This reads `hkex_announcement_events` read-only, adds `^HSI`, writes an
append-only capture, and refreshes the manifest-fingerprinted audit.

Before downloading, a no-network readiness check is available:

```bash
python scripts/capture_yfinance_intraday.py \
  --readiness \
  --output-root data/raw/market_data/yfinance
```

The next trading-day runbook is intentionally split by scope. First capture
the canonical 122-symbol universe and refresh the canonical audit:

```bash
python scripts/capture_yfinance_intraday.py \
  --from-event-universe \
  --output-root data/raw/market_data/yfinance \
  --audit-after
```

Then, if candidate coverage is being refreshed, capture the 21 eligible
candidate tickers separately without `--audit-after`; this keeps the canonical
`archive_audit.json` contract independent of candidate-only gaps. Replay both
candidate output directories with the immutable archive, and compare only
canonical capture IDs (not the partial candidate capture):

```bash
python scripts/run_hkex_event_study_yfinance.py \
  --snapshot-root data/raw/market_data/yfinance \
  --candidate-inventory outputs/hkex_filing_candidate_inventory/hkex_filing_candidate_inventory.csv \
  --output-dir outputs/hkex_event_study_candidates

python scripts/run_hkex_event_study_yfinance.py \
  --snapshot-root data/raw/market_data/yfinance \
  --candidate-inventory outputs/hkex_filing_candidate_inventory/hkex_filing_candidate_inventory.csv \
  --output-dir outputs/hkex_event_study_candidates_pit_recovered

python scripts/compare_hkex_event_study_captures.py \
  --snapshot-root data/raw/market_data/yfinance \
  --output-dir outputs/hkex_event_study_capture_comparison \
  --top-tickers 30 \
  --capture-ids <previous-canonical-capture-id> <new-canonical-capture-id>
```

Only after the comparison reports `distinct_both_intervals` should the
canonical and candidate bundles be re-exported and their post-write audits
rerun. A new cutoff is evidence for robustness testing, not permission to
register a signal automatically.

The current readiness result is `needs_capture` only because `1788.HK` is
stale in both intervals; universe coverage is 100% and no archive integrity
error is reported. The full replay has 18 uncovered events: 16 are explicitly
`awaiting_next_market_cutoff` because their observed PIT time is after the
latest archived `^HSI` bar, while `0736.HK` has a late symbol history start and
`1788.HK` remains the stale-history boundary.

The registration gate is deliberately stricter than the descriptive
robustness table. In the current full replay it blocks on four independent
conditions: degraded archive quality (`1788.HK` stale), only one market cutoff,
the covered sample being entirely source-timestamp proxies (205/205), and 23
rows with rejected bar-hole horizons. The four raw-versus-derived conflicts
are retained as reconciled audit evidence, with zero unresolved review rows.
These are evidence-review reasons, not claims that the underlying announcement
effects are false. They must be resolved or explicitly reviewed before any row
can become a dashboard trading signal.

After each replay, the persisted CSV/JSON bundle can be independently checked
with:

```bash
python scripts/audit_hkex_event_study_outputs.py \
  outputs/hkex_event_study_yfinance \
  --comparison-json outputs/hkex_event_study_capture_comparison/comparison.json \
  --write-audit
```

The post-write audit rechecks row counts, cluster representatives, availability
basis, resolved-direction enums and counts, strict PIT entries, horizon
monotonicity, native-1h coverage, direction conflicts, bar holes,
candidate-family isolation, registry gate alignment and the
no-production-database-write invariant.
When a comparison JSON is supplied, it also verifies successful-replay pair
combinations, cutoff provenance, same/partial/distinct classification,
aggregate pair counts and the final robustness status.

For dashboard consumption without changing the production sector roster, the
research bundle can be exported to the shared JSON artifact contract:

```bash
python scripts/export_hkex_event_study_dashboard_artifact.py \
  outputs/hkex_event_study_yfinance \
  --comparison-json outputs/hkex_event_study_capture_comparison/comparison.json \
  --output outputs/hkex_event_study_dashboard/full_universe_artifact.json
```

The exporter creates a research-only `manifest` + `snapshot.datasets` artifact
with per-ticker evidence, coverage/cluster cards, direction-signed efficacy,
return-decomposition tables, conflict review and the blocked signal registry.
It refuses bundles that fail the independent audit, contain a registered
signal, or do not confirm that the production database was unmodified. Top-30
and candidate explorations are exported separately and must not be merged into
the canonical full-universe view without an explicit scope filter.
The artifact also exposes a PIT availability table and a stale-symbol table.
The current yfinance check confirms that `1788.HK` returns no newer 5m or 1h
bar after 2026-07-22; this is recorded as an unresolved yfinance-history
boundary, not silently labelled a suspension and not filled with another
provider.
