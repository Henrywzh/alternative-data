# Research Control Tower — Tencent (0700.HK / TCEHY) T0–T3 Vertical Slice Design Spec

**Date:** 2026-08-21  
**Status:** Approved Design (Architecture boundaries and design principles explicitly approved by user in session discussion)  
**Repository:** `alternative-data`  
**Target Entities:** `TENCENT` (`0700.HK` primary listing; `TCEHY` US OTC depositary receipt — role/ratio/type subject to official verification before activation)  
**Related Entities:** `BYTEDANCE` (private peer/competitor for comparison)  
**Parent Scope:** Research Control Tower Stage 1 Focus Universe + Fundamental/Tactical Thesis Workflow

---

## 1. Product Problem & Scope Boundaries

### 1.1 Core Questions Answered
The Research Control Tower turns fragmented regulatory filings, consensus prints, price actions, and corporate actions into an auditable investment cockpit. For Tencent (`0700.HK` / `TCEHY`), the T0–T3 vertical slice reliably answers:

1. **What changed recently?** Official regulatory announcements, statutory corporate disclosures, and structured consensus changes within the configured lookback window.
2. **What is the market expecting?** Standardized forward consensus estimates across revenue, GAAP net profit, Non-IFRS operating profit, and Non-IFRS net profit, tracking genuine revisions over time.
3. **How are core indicators evolving?** Historical official segment disclosures (VAS, Marketing Services / Online Ads, FinTech & Business Services), margins, deferred revenue, and capital returns (statutory share buyback execution).
4. **What are the next catalysts?** Confirmed board meeting dates, regulatory review windows, and provisional financial reporting windows.
5. **What is the current valuation context?** Clean price/market-cap tracking with explicit currency metadata, Forward P/E (GAAP vs. Non-IFRS), and trailing shareholder cash return yield.
6. **What evidence challenges the current thesis?** Explicit human-authored Watch Questions linked to incoming official filings, corporate actions, and consensus revisions, surfacing evidence conflicts without automated judgment.
7. **Which alternative signals are relevant?** High-signal, verified data streams linked to core thesis questions, separating validated free feeds from unverified/paid candidates.

### 1.2 Explicit Non-Goals
* **No Automated Thesis Decisioning**: The system never updates thesis status, conviction rating, or directional bias automatically. It only attaches evidence items and flags factual divergences against human-authored thesis boundaries.
* **No Live Network/Scraping during UI Navigation**: The Streamlit UI is 100% read-only and loads only local, deterministic Parquet read marts from `.generated/CURRENT/`.
* **No Runtime Database Attaching**: Neither the offline builder nor the Streamlit application attaches to sibling repository DuckDB instances during runtime execution.
* **No Pseudo-Precision or Fake Exact Dates**: Uncertain catalysts and industry milestones must never use quarter-end or year-end dummy dates marked as exact events.
* **No Incompatible Consensus Blending**: RMB forecasts and HKD/USD prices or cross-provider estimates must never be averaged or subtracted without explicit currency vintage, accounting basis, and metric basis alignment.
* **No Lookahead Historical Reconstructions**: Third-party sparse trends (e.g. `yfinance` retrospective `eps_trend`) are typed as `reconstructed_sparse`; they must never be presented as true Point-in-Time (PIT) capture or used to compute headline historical revision breadth.
* **No Strategy Backtesting in Control Tower**: Strategy backtesting, alpha factor ranking, and portfolio construction remain strictly isolated in `quantamental-lab`.

---

## 2. Architecture Trade-Offs & Selected Approach

### 2.1 Evaluated Approaches

| Approach | Description | Pros | Cons | Verdict |
|---|---|---|---|---|
| **Option 1: Monolithic Generic Pipeline** | Treat Tencent identically to US large-cap equities via standard `yfinance` / generic financial APIs. | Zero custom code; quick initial rendering. | Fails on Non-IFRS vs. GAAP reporting, misses HKEX daily buyback disclosure returns, breaks on RMB vs. HKD currency confusion. | **Rejected** |
| **Option 2: Purely Bespoke Single-Stock Silo** | Build isolated `tencent_collector.py`, custom database tables, and a dedicated custom UI page. | Perfectly tailored to Tencent's exact reporting quirks. | Unmaintainable, duplicates code across portfolio holdings, breaks cross-entity filtering and unified timeline. | **Rejected** |
| **Option 3: Hybrid Vertical Slice (Selected)** | Route structured common feeds through a **Unified Pipeline**, use **Specialised Parsers/Collectors** only where necessary, and enforce a **Strict Unified Evidence Contract** at the read mart layer. | High fidelity for entity specifics while preserving universal schemas, clean PIT guarantees, and multi-entity UI composability. | **Approved** |

### 2.2 Component Boundaries

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           1. Ingestion Layer (Network-Entitled)                  │
├─────────────────────────┬───────────────────────────────────────────────────────┤
│        Unified Pipelines│        Specialised Collectors                         │
│ - HKEX title-search     │ - Tencent IR presentation / segment                   │
│   metadata & filings    │   financial statement parser                          │
│ - yfinance OHLCV/quotes │ - Domain-specific alternative data                    │
│ - FRED / Macro vintages │   (verified free feeds only)                          │
│ - Provider consensus    │                                                       │
└─────────────────────────┴───────────────────────────────────────────────────────┘
                                         │
                                         ▼ (Deterministic Transform / Validation)
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    2. Offline Normalization & Read Marts                        │
│ - Day-granular immutable snapshots store (store/snapshots_store.parquet)        │
│ - Unified Evidence & Lineage Registry (pit_class, timestamps, source_url)       │
│ - Materialized Parquet marts in .generated/generations/<gen_id>/                │
└─────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼ (Read-Only Local Query)
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    3. Research Control Tower UI (Streamlit)                     │
│ - Tencent Cockpit Tabs: Overview | Fundamentals | Thesis & Catalysts | Evidence │
│ - Purely local DuckDB/PyArrow reads; Light/Dark theme support; Fail-closed      │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Unified vs. Specialised Source Decision Matrix

| Data Concept | Category | Pipeline Classification | Primary Source & Rationale | Destination Mart |
|---|---|---|---|---|
| **Daily Bars & Quotes** | A | **Unified Pipeline** | `yfinance` / Exchange Market Feeds (OHLCV, quotes, volume) | `price_bars.parquet`, `quote_snapshots.parquet` |
| **Corporate Action: Buybacks** | A | **Unified Pipeline** | HKEX Next Day Disclosure Returns (Statutory form shared across all HK issuers) | `corporate_actions.parquet` |
| **Statutory Filings** | A | **Unified Pipeline** | HKEXnews official title-search metadata adapter / SEC EDGAR | `official_filings.parquet` |
| **Consensus Snapshots** | A | **Unified Pipeline** | Standard providers (Akshare, yfinance); `financial-data` is bridge/calculation_origin | `consensus_snapshots.parquet`, `snapshots_store.parquet` |
| **Analyst Own Estimates** | A | **Manual Ingestion** | Human analyst internal model estimates & management guidance | `internal_estimates.parquet` |
| **Macro / FX Vintages** | A | **Unified Pipeline** | FRED / ECB / HKMA / PBoC reference rates | `macro_observations.parquet` |
| **Segment Financials (VAS, Ads, FBS)** | B | **Specialised Collector** | Tencent IR quarterly financial releases (PDF / HTML tabular extracts) | `earnings_actuals.parquet` |
| **Regulatory Catalysts (NPPA)** | B | **Specialised Collector / Manual** | NPPA official game approval notices (manual/source-backed in T3; automated in T4+) | `events.parquet` |
| **Human Thesis & Watch Questions** | A | **Manual / Static Config** | Human analyst YAML/CSV configurations (read-only in app) | `event_watch_questions.parquet`, `thesis_claims.parquet` |
| **Paid Alt Data (SensorTower, etc.)** | C | **Excluded (T4+ TODO)** | Commercial mobile telemetry (not free, strict licensing) | *Excluded from T0–T3* |

---

## 4. T0–T3 Additive Schema & Data Contracts

All schemas preserve existing column names and conventions without breaking existing generation readers.

### 4.1 T0: Entity, Listing & Crosswalk Contracts

#### `entities.parquet` (Preserves Existing Schema)
* `entity_id` (string, PK): Canonical entity key (e.g. `"TENCENT"`, `"BYTEDANCE"`).
* `legal_name` (string): Legal name.
* `display_name` (string): Display label.
* `country` (string): ISO country code (`"CN"`, `"US"`, `"HK"`).
* `sector` (string): Sector classification.
* `industry` (string): Industry classification.
* `active_status` (string): `"active"` or `"archived"`.
* `active_from` (string), `active_to` (string, nullable).
* `registry_version` (string): Version tag.
* `source_or_research_note` (string).
* `entity_type` (string): `"public"` or `"private"`.

#### `listings.parquet` (Preserves Existing Schema)
* `listing_id` (string, PK): `"0700_HK"`, `"TCEHY_US"`.
* `entity_id` (string, FK): Reference to `entities.entity_id`.
* `exchange` (string): `"HKEX"`, `"OTC"`.
* `native_ticker` (string): `"0700"`, `"TCEHY"`.
* `canonical_ticker` (string): Standardized dot-notation ticker (`"0700.HK"`, `"TCEHY.US"`).
* `financial_data_security_id` (string, nullable).
* `financial_data_issuer_group_id` (string, nullable).
* `mapping_status` (string): `"verified"` or `"unverified"`.
* `mapping_verified_at` (string).
* `mapping_source_url` (string).
* `collection_eligible` (bool).
* `listing_role` (string): `"primary"` for `0700_HK`; for `TCEHY_US`, role/ratio/type must be verified from depositary/official filings prior to active trading enablement.
* `vendor_tickers` (string): Semicolon-delimited mappings.
* `currency` (string): `"HKD"`, `"USD"`.
* `primary_listing` (bool): True for `0700_HK`, False for `TCEHY_US`.
* `active_from` (string), `active_to` (string, nullable).
* `listing_status` (string): `"active"` or `"archived"`.
* `registry_version` (string), `source_url` (string), `source_or_research_note` (string).

---

### 4.2 T1: Official Historical Fundamentals & Corporate Actions

#### `earnings_actuals.parquet` (Additive Extension)
Covers at least 12 quarters (target: 2021Q1 to latest verifiable quarter), with documented handling for historical reporting format shifts.
* `actual_id` (string, PK): `hash(entity_id + period_label + metric + accounting_basis + vintage_type + source_document_id + observed_at)`.
* `version` (string): Schema version.
* `supersedes_actual_id` (string, nullable).
* `entity_id` (string, FK): `"TENCENT"`.
* `listing_id` (string, nullable): `"0700_HK"`.
* `canonical_ticker` (string): `"0700.HK"`.
* `metric` (string): Canonical metric (e.g. `"revenue_total"`, `"revenue_vas"`, `"revenue_online_ads"`, `"revenue_marketing_services"`, `"revenue_fintech_cloud"`, `"operating_profit"`, `"net_profit_attributable"`, `"diluted_eps"`, `"deferred_revenue_current"`).
* `source_metric_label` (string): Literal label in the source report (e.g. *"Online Advertising"* vs *"Marketing Services"*).
* `period_label` (string): `"2025Q1"`, `"2025Q2"`, `"2025H1"`, `"2025FY"`.
* `period_start` (string), `period_end` (string).
* `reported_value` (float64): Raw value as reported.
* `normalized_value` (float64): Normalized value in base units.
* `normalization_note` (string, nullable).
* `currency` (string): Reporting currency (`"CNY"`).
* `unit` (string): Value scale (`"CNY"`, `"ratio"`, `"shares"`).
* `accounting_basis` (string): `"GAAP_REPORTED"` or `"NON_IFRS_MANAGEMENT"`.
* `filing_at` (string): Statutory filing timestamp.
* `published_at` (string): Public release timestamp.
* `retrieved_at_utc` (timestamp): Ingestion timestamp.
* `source_url` (string), `accession_no` (string, nullable), `form` (string, nullable).
* `is_restatement` (bool): True if from a subsequent comparative period table.
* `source_id` (string), `source_quality` (string), `pit_class` (string), `source_license_class` (string), `registry_version` (string).

#### `corporate_actions.parquet` (Statutory Buybacks & Dividends)
Captures verifiable fields from official statutory filings; unverified or derived fields remain nullable with documented coverage reasons.
* `action_id` (string, PK): `hash(listing_id + filing_date + execution_date + action_type)`.
* `listing_id` (string, FK): `"0700_HK"`.
* `action_type` (string): `"buyback_execution"`, `"cash_dividend"`, `"distribution_in_specie"`.
* `filing_date` (string): Statutory disclosure date (ISO).
* `execution_date` (string): Execution date (ISO).
* `shares_affected` (int64): Repurchased or distributed share count.
* `price_min` (float64, nullable): Lowest price paid (source-extractable).
* `price_max` (float64, nullable): Highest price paid (source-extractable).
* `price_avg` (float64, nullable): Nullable unless explicitly provided in official filing.
* `total_amount_paid` (float64): Total consideration paid excluding commissions.
* `currency` (string): `"HKD"`.
* `cancellation_status` (string, nullable): Nullable unless explicitly reported as cancelled.
* `coverage_reason` (string, nullable): Documents why optional fields are null.
* `source_url` (string): Official HKEX Next Day Disclosure Return link.
* `retrieved_at_utc` (timestamp): Collection timestamp.

---

### 4.3 T2: Consensus Snapshots, Own Estimates & Revisions

#### `consensus_snapshots.parquet` & `store/snapshots_store.parquet`
* `snapshot_id` (string, PK): `hash(provider + listing_id + metric + horizon + statistic + accounting_basis + snapshot_at)`.
* `provider` (string): Standard provider identifier (`"akshare"`, `"yfinance"`).
* `calculation_origin` (string, nullable): System origin if bridged (e.g. `"financial_data_bridge"`).
* `observation_type` (string): `"provider_consensus"`, `"management_guidance"`, `"internal_estimate"`.
* `listing_id` (string, FK): `"0700_HK"`.
* `metric` (string): Target metric (`"revenue"`, `"eps"`, `"operating_profit"`, `"net_profit"`).
* `accounting_basis` (string): `"GAAP_REPORTED"` or `"NON_IFRS_MANAGEMENT"`.
* `fiscal_period` (string), `fiscal_year` (int32, nullable), `estimate_period_end` (string, nullable).
* `horizon` (string): `"current_quarter"`, `"next_quarter"`, `"FY1"`, `"FY2"`.
* `snapshot_at` (string): Snapshot calendar date/time.
* `value` (float64): Estimate figure.
* `statistic` (string): `"mean"`, `"median"`, `"high"`, `"low"`, `"count"`.
* `currency` (string), `unit` (string).
* `provider_asof` (string, nullable), `retrieved_at_utc` (timestamp), `source_url` (string), `pit_class` (string).

#### `internal_estimates.parquet` (Own Estimates & Management Guidance Mart)
Maintains full isolation from third-party consensus.
* `estimate_id` (string, PK): Unique estimate identifier.
* `entity_id` (string, FK), `listing_id` (string, FK).
* `observation_type` (string): `"management_guidance"` or `"internal_estimate"`.
* `author` (string): Analyst name or `"company_management"`.
* `metric` (string), `accounting_basis` (string), `fiscal_period` (string), `fiscal_year` (int32).
* `value_low` (float64, nullable), `value_high` (float64, nullable), `value_mid` (float64).
* `currency` (string), `unit` (string).
* `effective_asof` (string), `recorded_at_utc` (timestamp), `rationale_notes` (string).

#### `consensus_revisions.parquet`
* `revision_id` (string, PK): `hash(current_snapshot_id + prior_snapshot_id)`.
* `snapshot_id` (string, FK), `prior_snapshot_id` (string, FK).
* `provider` (string): Standard provider identifier.
* `listing_id` (string, FK), `metric` (string), `accounting_basis` (string), `fiscal_period` (string), `fiscal_year` (int32).
* `current_value` (float64), `prior_value` (float64), `revision_value` (float64), `revision_pct` (float64).
* `lookback_days` (int32): Dynamic calendar day delta between snapshot dates.
* `pit_class` (string): `"repository_captured"` (valid for momentum signals) or `"reconstructed_sparse"` (cold-start display only).

---

### 4.4 T3: Catalysts, Thesis Structure, Watch Questions & Evidence

#### `events.parquet` (Catalyst Timeline)
* `event_id` (string, PK): Stable event key.
* `event_type` (string): `"earnings_release"`, `"board_meeting"`, `"regulatory_review"`, `"corporate_action"`.
* `title` (string), `description` (string).
* `certainty_class` (string): `"hard"` (statutory confirmed) or `"provisional"` (historical estimate).
* `date_precision` (string): `"exact_date"`, `"month"`, `"quarter"`, `"range"`.
* `starts_at` (string), `ends_at` (string).
* `source_id` (string), `source_url` (string, nullable), `source_published_at` (string, nullable).
* `last_verified_at` (string).

#### `thesis_claims.parquet` & `event_watch_questions.parquet`
Separates thesis declarations, watch questions, and evidence links across normalized relational tables:
* **`thesis_claims.parquet`**:
  * `claim_id` (string, PK), `entity_id` (string, FK), `thesis_title` (string), `claim_text` (string).
  * `invalidation_rule` (string): Explicit deterministic rule authored by human analyst.
  * `status` (string): `"active"`, `"falsified"`, `"confirmed"`, `"archived"` (Updated by human analyst only).
  * `last_reviewed_at_utc` (timestamp), `reviewed_by` (string).
* **`event_watch_questions.parquet`**:
  * `question_id` (string, PK), `event_id` (string, FK/nullable), `entity_id` (string, FK).
  * `question` (string), `question_type` (string), `priority` (string).
* **`evidence_items.parquet`**:
  * `evidence_id` (string, PK), `source_type` (string: `"filing"`, `"consensus_revision"`, `"corporate_action"`).
  * `source_id_ref` (string), `published_at` (string), `summary_text` (string), `observed_at_utc` (timestamp).
* **`claim_evidence_links.parquet`**:
  * `link_id` (string, PK), `claim_id` (string, FK), `evidence_id` (string, FK).
  * `conflict_hint` (bool): True if recent evidence crosses human-defined invalidation thresholds.
  * `review_state` (string): `"pending_review"`, `"acknowledged"`, `"dismissed"`.
  * `analyst_note` (string, nullable).

---

## 5. Point-in-Time, Currency, Accounting & Vintage Protocol

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      Strict Point-in-Time (PIT) Class Hierarchy                  │
├─────────────────────────┬───────────────────────────────────────────────────────┤
│ 1. official_filing      │ Direct exchange/regulator filing with published time  │
│ 2. repository_captured  │ Daily immutable snapshot captured by our pipeline     │
│ 3. dated_broker_report  │ Explicitly dated broker report/estimate publication   │
│ 4. reconstructed_sparse │ Retrospective trend from third-party API (cold-start) │
│ 5. not_pit / unverified │ Unversioned live web scrapings or ambiguous snapshots │
└─────────────────────────┴───────────────────────────────────────────────────────┘
```

### 5.1 Rules for PIT Integrity & Cold-Start Precedence
1. **Isolation of Reconstructed Trends**: `reconstructed_sparse` records from `yfinance` are kept for historical context during cold start but are **strictly excluded** from calculating headline consensus revision breadth or triggering quantitative momentum alerts.
2. **Day-Granular Store Immutability**: Within a UTC calendar day, reruns update same-day snapshot records idempotently. Once a calendar day closes (`snapshot_date < current_utc_date`), past snapshots remain permanently immutable.
3. **Resilient Key Pairing**: Consecutive vintage pairing is keyed on `(provider, listing_id, metric, horizon, statistic, accounting_basis)`. Dynamic updates to fiscal period mappings attach updated labels without breaking historical delta links.

### 5.2 Multi-Currency & Accounting Alignment Protocol
* **Reporting vs. Quoting Currency**: Tencent reports in **RMB (CNY)**. `0700.HK` trades in **HKD**; `TCEHY` trades in **USD**.
* **Valuation Ratio Computation**: Market capitalization converted at contemporaneous FX rates must match the denominator currency, explicitly logging `fx_rate_applied`, `fx_source`, and `fx_snapshot_at_utc`.
* **GAAP vs. Non-IFRS Segregation**: GAAP Net Profit includes volatile mark-to-market fluctuations on investee companies. Non-IFRS Operating/Net Profit reflects normalized core operations. The UI provides side-by-side dual tracks to prevent bogus beat/miss calculations.

### 5.3 As-Reported vs. Restated Vintage Integrity
* **As-Reported**: Preserves original numbers and HKEX publication timestamps.
* **Restated**: Captures subsequent segment reclassifications (e.g. Online Ads reclassified to Marketing Services) as distinct records with `is_restatement=True` linked to the later filing accession. Historical point-in-time queries selecting past dates retrieve only the `as_reported` state available at that date.

---

## 6. Streamlit UI Information Architecture: Tencent Cockpit

The Control Tower operates strictly offline from `.generated/CURRENT/` with full Light (default) and Dark theme consistency. The Tencent Cockpit on the Company Page organizes into four focused tabs:

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│              Tencent Holdings (0700.HK / TCEHY) Research Cockpit                │
│ [Primary: HKEX 0700.HK]  [Reporting: RMB / IFRS]  [Status: Active Stage 1 Focus]│
├─────────────────────────────────────────────────────────────────────────────────┤
│ [ Tab 1: Overview ]                                                             │
│ - Security Identity: Primary HKD listing, OTC DR status, FX conversion rates    │
│ - Latest Market Quotes: Close, day change, volume, verified quote freshness SLA │
│ - Flight Deck: Active catalysts within 7d/30d/90d, open watch question count    │
├─────────────────────────────────────────────────────────────────────────────────┤
│ [ Tab 2: Fundamentals ]                                                         │
│ - Segment Disclosures: VAS, Marketing Services/Online Ads, FinTech & Cloud      │
│ - Profitability & Cash: GAAP vs. Non-IFRS Operating Profit, Deferred Revenue    │
│ - Capital Returns: Statutory HKEX share buyback ledger, spend, price bands      │
├─────────────────────────────────────────────────────────────────────────────────┤
│ [ Tab 3: Thesis & Catalysts ]                                                   │
│ - Active Thesis Claims: Human-authored core investment theses & invalidation    │
│ - Upcoming Catalysts: Confirmed Hard board meetings vs Provisional windows     │
│ - Watch Questions: Targeted operational questions with conflict alert badges   │
├─────────────────────────────────────────────────────────────────────────────────┤
│ [ Tab 4: Evidence ]                                                             │
│ - Lineage Feed: HKEX statutory announcements, filing hashes, published times    │
│ - Consensus Revisions: Forward estimate trajectories & revision histories       │
│ - Claim-Evidence Matrix: Evidence items mapped to thesis boundaries             │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Error Handling, Degradation & Fail-Closed Guards

1. **Required vs. Optional Mart Failure Handling**:
   * If a **required** core registry or catalog mart (`entities.parquet`, `listings.parquet`, `events.parquet`) is missing or has an invalid schema, the builder and UI fail closed immediately with a fatal diagnostic error.
   * If an **optional** mart (`corporate_actions.parquet`, `internal_estimates.parquet`) is missing, the application does not crash; it renders typed `unavailable` state badges in the affected panels.
2. **Stale Data Bundle Behavior**: If the newest observation in the active generation predates the previous build timestamp, the app banners **"Data bundle is stale"** prominently but keeps interactive UI filters operable.
3. **Strict Network Isolation**: All UI components load strictly from local files; any background socket or HTTP request raises an immediate exception.

---

## 8. Stage Gates & Verification Matrix (T0–T3)

```text
[ Gate 0: T0 Foundation & Identity ]
  ├── 0700.HK & TCEHY mapped; TCEHY role marked for official verification
  ├── Core Parquet files conform strictly to typed schemas
  └── Currency and metric_basis validators pass

[ Gate 1: T1 Fundamentals & Corporate Actions ]
  ├── HKEX official filings parsed (>=12 quarters, target 2021Q1–latest)
  ├── Dual-track GAAP vs Non-IFRS actuals extracted and verified
  └── HKEX Next Day Disclosure buybacks match source-extractable fields

[ Gate 2: T2 Consensus, Guidance & Own Estimates ]
  ├── snapshots_store.parquet records immutable day-level vintages
  ├── Genuine revisions paired across mappings; yfinance trend isolated
  └── Management guidance & own estimates stored in dedicated mart

[ Gate 3: T3 Catalysts & Thesis Workbench ]
  ├── Hard vs Provisional event dates properly classified
  ├── Thesis claims, watch questions & evidence links stored in normalized marts
  └── Conflict alerts flag divergences without automated thesis state mutation
```

| Stage Gate | Target Artifacts | Verification Command / Suite | Exit Criteria |
|---|---|---|---|
| **Gate 0: T0 Foundation** | `entities.parquet`, `listings.parquet` | `pytest tests/test_research_control_tower_registries.py` | 100% pass, zero unmapped listings |
| **Gate 1: T1 Fundamentals** | `earnings_actuals.parquet`, `corporate_actions.parquet` | `pytest tests/test_research_control_tower_earnings_actuals.py tests/test_research_control_tower_official_filings.py` | Source-extractable fields exact match with documented coverage |
| **Gate 2: T2 Expectations** | `consensus_snapshots.parquet`, `consensus_revisions.parquet` | `pytest tests/test_research_control_tower_consensus_revisions.py` | Provider consensus isolated from own estimates; revision pairing valid |
| **Gate 3: T3 Thesis & UI** | `events.parquet`, `thesis_claims.parquet`, `event_watch_questions.parquet` | `pytest tests/test_research_control_tower_events.py tests/test_research_control_tower_streamlit.py` | AppTest passes; Light/Dark theme rendering clean; zero console errors |

---

## 9. T4+ Candidates & Backlog (TODO Only)

The following items are deferred to T4+ and do not block T0–T3 completion:

* **[TODO T4.1] Automated NPPA Game Approval Ingestion**: Direct pipeline for National Press and Publication Administration game license releases once web crawler stability is verified (T3 supports manual/source-backed events).
* **[TODO T4.2] WeChat Ecosystem Public Signals**: Ingestion of verified public data (e.g. WeChat search index, mini-programs directory).
* **[TODO T4.3] Listed SOTP Portfolio Value Tracker**: Automated market-cap tracker for Tencent's publicly listed equity holdings (Meituan, Kuaishou, Sea, etc.).
* **[TODO T4.4] Southbound Stock Connect Inflows**: Net daily inflow tracking for `0700.HK` via HKEX Stock Connect.
* **[TODO T4.5] Commercial App Intelligence Diligence**: Formal diligence on commercial app store revenue estimation feeds (SensorTower, Data.ai) if budget and data distribution rights are authorized.

---

## 10. Test & Migration Strategy

1. **Deterministic Test-First Execution**: Ingestion parsers and transform builders must be covered by unit tests using static mock fixtures (offline HKEX Next Day Disclosure HTML/XML samples, mock consensus exports).
2. **Additive Migration Safety**: New read marts are additive. Existing Control Tower generations without these tables fall back gracefully to typed `unavailable` state badges without application failure.
3. **Automated Bundle Integrity Verification**: `src/research_control_tower/build.py` executes an automated post-build check ensuring primary key uniqueness, non-null mandatory timestamps, and schema conformity before updating `.generated/CURRENT`.
