# Research Control Tower Batches 6 & 7 — Genuine Consensus Revisions Design & Implementation Plan

**Date:** 2026-08-19
**Status:** ACCEPT WITH CONDITIONS (Design Challenge & Plan)
**Repo:** `alternative-data` (branch `codex/rtc-batch67-consensus-revisions`)
**Parent scope:** Control Tower data-coverage batch sequence (Batches 6 & 7 of 8)

## 1. Design Risks & Verdict (Design Challenge)

### Context & Architecture
The parallel implementation slice introduces an append-only store at `<output-dir>/store/snapshots_store.parquet` to accumulate daily analyst estimate snapshots. The store is keyed by natural estimate series identity (`provider`, `listing_id`, `metric`, `horizon`, `statistic`, `fiscal_period`, `fiscal_year`, `estimate_period_end`). For each key and UTC calendar date, the store retains at most one snapshot row using same-day last-write-wins replacement, indexed by a deterministic `snapshot_id = hash(natural key + UTC date)`.

From this accumulated store, genuine point-in-time revisions (`pit_class="repository_captured"`) are derived by comparing consecutive snapshot vintages across dates. During cold-start (or when store history is insufficient), retrospective consensus trends (`eps_trend` from yfinance) are retained as cold-start fallbacks labeled `pit_class="reconstructed_sparse"`. All current export contracts (`control_tower_consensus_snapshots.parquet`, `control_tower_consensus_revisions.parquet`, `control_tower_consensus_source_health.parquet`) preserve their exact filenames and schemas.

### Hard Design Review & Risk Analysis

#### Risk 1: Same-Day Last-Write-Wins vs. "Scheduled IMMUTABLE Snapshots" Language
* **Conflict:** The 2026-08-15 Focus Plan specifies Batch 7 as "Scheduled IMMUTABLE snapshots of Batch 6 providers". However, the implementation uses same-day last-write-wins replacement for identical natural keys on the same UTC date.
* **Analysis:** In operational collection, network retries, collector reruns, or intraday script executions on the same UTC day may occur. If every intraday rerun appended a new row, the store would suffer from intraday duplication and non-idempotent reruns. Intraday replacement is a necessary idempotency safeguard.
* **Resolution & Specification Wording:** The plan spec is clarified as **"Day-Granular Immutability"** (or *day-level append-only immutability with same-day idempotent updates*). Once a UTC date closes, that date's vintage is permanently frozen and immutable. Reruns within the same UTC date update the existing same-day record idempotently without breaking point-in-time integrity across calendar days.

#### Risk 2: Natural-Key Fragility with Mapped Fiscal Fields (`fiscal_year`, `estimate_period_end`)
* **Conflict:** The natural key includes `fiscal_year` and `estimate_period_end`, which are resolved dynamically from the sibling `financial-data` repository's `consensus_period_mapping` table.
* **Analysis:** Mapping entries can be added or improved over time. On Day 1, an estimate for `9988.HK` / `eps` / `+1q` might be unmapped (`fiscal_year=Null`, `estimate_period_end=Null`). On Day 2, after a mapping table update, the exact same physical estimate series resolves to `fiscal_year=2027` and `estimate_period_end=2026-06-30`. Under a strict key match including fiscal fields, the Day 1 and Day 2 snapshots land under different natural keys, silently breaking consecutive-vintage pairing and losing genuine revision history!
* **Severity:** HIGH.
* **Mitigation Condition:** For consecutive-vintage revision pairing, vintage matching must be keyed on fixed provider estimate identity `(provider, listing_id, metric, horizon, statistic)` or fall back to horizon-based matching across fiscal mapping transitions, attaching the latest resolved fiscal metadata to the resulting revision record.

#### Risk 3: Akshare Relay Consistency & Initial Ingestion
* **Conflict:** The sibling repository export `FD_CONSENSUS` contains historical snapshots spanning multiple dates, and uses provider naming that must remain strictly aligned.
* **Analysis:** If provider naming differs (e.g. `"financial_data_akshare"` vs. `"akshare"`), store keys split and cross-vintage revision chains break. Furthermore, initial ingestion of `FD_CONSENSUS` must ingest historical snapshot dates into `snapshots_store.parquet` using their native `snapshot_date` vintages rather than stamping them all with `now.date()`.
* **Mitigation Condition:** Standardize provider identifier strictly as `"akshare"` across store, snapshots, revisions, and health schema. Ingest multi-date historical dumps from `financial-data` by preserving each record's native `snapshot_date`.

#### Risk 4: Genuine vs. Reconstructed Revisions Coexistence
* **Conflict:** Both genuine revisions (`repository_captured`) derived from store vintage pairs and reconstructed revisions (`reconstructed_sparse`) derived from `eps_trend` may coexist in `control_tower_consensus_revisions.parquet`.
* **Analysis:** Downstream aggregations (such as catalyst scores or revision breadth) could double-count changes if both genuine and reconstructed rows for the same metric/horizon are summed. Additionally, showing both in a single UI revision panel without clear visual separation could confuse users.
* **Mitigation Condition:** Downstream analytical queries and UI components must enforce strict precedence: prefer `repository_captured` when store vintages exist, using `reconstructed_sparse` strictly as a cold-start fallback. UI badges must clearly distinguish `PIT · captured` (normal badge) from `PIT · reconstructed` (warning badge).

#### Risk 5: Deterministic `snapshot_id` Implications
* **Analysis:** Computing `snapshot_id = hash(natural_key + UTC date)` guarantees complete deterministic rerun stability across collector executions. However, if provider data updates intra-day, the second run overwrites the first run's intra-day value under the same `snapshot_id`.
* **Verdict:** Acceptable. Daily cadence is the explicit SLA of the Research Control Tower; intra-day estimate tracking is out of scope.

#### Risk 6: `lookback_days` Semantics Under Irregular Runs
* **Analysis:** If collection runs miss calendar days (e.g., weekends, holidays, or pipeline downtime), consecutive store vintages may be separated by multiple days ($N > 1$).
* **Mitigation Condition:** `lookback_days` must be computed dynamically as `(current_snapshot_at.date() - prior_snapshot_at.date()).days` rather than hardcoding `lookback_days = 1`.

### Design Verdict & Concrete Conditions

**Verdict:** **ACCEPT WITH CONDITIONS**

**Required Conditions:**
1. **Day-Granular Immutability:** Define store immutability as day-granular. Within-day reruns update same-day records idempotently; past dates (`snapshot_date < current_date`) remain strictly immutable.
2. **Keying & Chaining Resilience:** Pair consecutive store vintages using provider estimate series identity `(provider, listing_id, metric, horizon, statistic)` to prevent fiscal mapping updates from splitting revision chains.
3. **Canonical Provider Naming & Multi-Vintage Ingestion:** Enforce `"akshare"` provider string across all schema outputs and ingest historical akshare snapshots preserving native `snapshot_date`.
4. **PIT Precedence & Downstream Hygiene:** Downstream summary metrics must filter on `pit_class == 'repository_captured'` when genuine revisions exist, falling back to `reconstructed_sparse` only when store history is absent.
5. **Dynamic `lookback_days` Calculation:** Derive `lookback_days` directly from calendar date deltas between matched store vintages.

---

## 2. Batch 6 & 7 Plan Alignment & Requirement Matrix

Mapping to the consensus roadmap defined in `docs/superpowers/plans/2026-08-15-research-control-tower-focus-and-theme.md`:

| Batch / Requirement | Scope & Description | Status / Delivery |
|---|---|---|
| **Batch 6 — Consensus Snapshots** | Live analyst estimate snapshots (`yfinance` live US/HK + `akshare` sibling relay for HK), period alignment mapping (`consensus_period_mapping`), and provider health sidecar (`control_tower_consensus_source_health.parquet`). | **DELIVERED** (Commit `427fff47` & `scripts/research_control_tower_consensus_collector.py`). |
| **Batch 7 — Store Accumulation** | Append-only store at `<output-dir>/store/snapshots_store.parquet` retaining daily estimate vintages per natural key with day-granular immutability. | **DELIVERED IN BRANCH** (`codex/rtc-batch67-consensus-revisions`). |
| **Batch 7 — Genuine Revisions** | Compute point-in-time consensus revisions (`control_tower_consensus_revisions.parquet`) by pairing consecutive store vintages (`pit_class="repository_captured"`). | **DELIVERED IN BRANCH** (`codex/rtc-batch67-consensus-revisions`). |
| **Batch 7 — Cold-Start Fallback** | Retain `eps_trend` restatements (`pit_class="reconstructed_sparse"`) as initial cold-start fallback until store accumulates sufficient daily vintages. | **DELIVERED IN BRANCH** (`codex/rtc-batch67-consensus-revisions`). |
| **Batch 7 — UI PIT Grammar** | Add `repository_captured` -> `PIT · captured` badge to `control_tower/components/source_badges.py`, rendering as normal (non-warning) badge. | **DELIVERED IN BRANCH** (`codex/rtc-batch67-consensus-revisions`). |
| **Batch 7 — Daily Scheduling / Automation** | Daily automated cron / runner execution of the consensus collector script. | **OPEN (OPS SCOPE)** — Automated scheduling is an operational infrastructure setup outside code repository scope. Collector code provides idempotent daily execution contract. |

---

## 3. Delivered Slice & Verification

### Files Modified / Created in This Slice
* `docs/superpowers/plans/2026-08-19-research-control-tower-batch67-consensus-revisions.md` (Design challenge, plan doc, verdict)
* `apps/research-control-tower/control_tower/components/source_badges.py` (Added `repository_captured` label and badge rendering logic)

### Verification Output
Ran verification command for UI badge mapping:
```bash
PYTHONPATH=src:apps/research-control-tower python3 -c "from control_tower.components.source_badges import _PIT_LABELS; print(_PIT_LABELS['repository_captured'])"
```
**Result:** `PIT · captured` (Passes import and dictionary lookup check cleanly).
