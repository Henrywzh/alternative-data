# Research Control Tower — Tencent (0700.HK / TCEHY) T3 Thesis, Catalyst & Evidence Cockpit Design

**Date:** 2026-08-21  
**Status:** IMPLEMENTATION READY (Seed layer, schemas, loader/validator, and unit tests implemented; integration ready)  
**Target Entity:** `TENCENT` (`0700.HK` primary; `TCEHY` US OTC DR gated)  
**Companion Entity:** `BYTEDANCE` (private competitor/peer benchmark)  
**Parent Plan:** `docs/superpowers/plans/2026-08-21-tencent-control-tower-t0-t3.md`  
**Design Spec:** `docs/superpowers/specs/2026-08-21-research-control-tower-tencent-t0-t3-design.md`  

---

## 1. Executive Summary & Core Philosophy

The Research Control Tower transforms fragmented market observations, regulatory filings, consensus prints, corporate actions, and alternative signals into an auditable fundamental+tactical cockpit.

### 1.1 Human-in-the-Loop Thesis Governance
* **Human Owns Thesis State**: The system never updates thesis status (`active`, `falsified`, `confirmed`, `archived`), conviction ratings, or directional bias automatically.
* **Deterministic Evidence Linking & Conflict Detection**: Automation links incoming factual evidence (`evidence_items`) against human-authored invalidation rules in `thesis_claims`, flagging `conflict_hint=True` when observed metrics violate predefined thresholds.
* **Auditability & Lineage**: Every claim, watch question, and evidence item is backed by source URLs, exact publication timestamps, and point-in-time classification.

---

## 2. Seven Core Questions Answered in the Tencent Cockpit

| Core Question | Cockpit Answer & Data Flow | Source & Provenance |
|---|---|---|
| **1. What changed recently?** | Official 2Q2026 financial report (RMB204.8B rev, +11% YoY; Non-IFRS Op Profit RMB75.6B, +9% YoY; FCF -RMB13.8B due to AI compute prepayments); statutory HKEX Next-Day Disclosure buybacks resumed post-blackout at ~HKD1.2B/day. | Tencent IR / HKEX Next-Day Disclosure Returns |
| **2. What is the market expecting?** | FY2026E Revenue consensus at RMB826.6B (+10.0% YoY); Non-IFRS EPS at RMB29.08 (+4.3% YoY), reflecting market conservatism regarding 2H26 AI compute depreciation. | Standard Provider Consensus (`consensus_snapshots_store`) |
| **3. How are core drivers evolving?** | Segments: VAS (Evergreen games), Marketing Services / Ads (+22% YoY on AIM+ & Video Accounts), FinTech & Cloud; Capital returns: statutory buybacks tracking ~HKD20B-30B half-year pace. | Specialized Tencent Financials Parser / HKEX NDD Returns |
| **4. What are the next catalysts?** | Confirmed 2Q26 earnings observation (`observed` / `hard`); 3Q26 results window (`thesis_checkpoint`, Nov 2026); NPPA monthly game license approval cadence; 2H26 AI CapEx and FCF inflection research window. | Event Ledger (`events.csv` / `tencent_events.csv`) |
| **5. What is the current valuation context?** | 0700.HK at HK$457 trading at ~13.2x forward Non-GAAP P/E (bottom 10th percentile of 10-year historical range); SOTP fair value estimated at HK$485-510/share; currency conversion explicitly tracked (CNY reports vs HKD price). | Valuation Snapshots Mart (`valuation_snapshots.parquet`) |
| **6. What evidence challenges the thesis?** | Negative quarterly FCF (-RMB13.8B in 2Q26) flags an active conflict hint against the Bull Case; CapEx surging 176% YoY to RMB52.8B approaches the Bear Case monitoring ceiling (RMB65B/quarter). | Thesis Claims & Claim-Evidence Links |
| **7. Which alternative signals are relevant?** | Tier 1: Daily HKEX share repurchases, monthly NPPA game publishing approvals; Tier 2: OpenRouter Hy3/Hunyuan LLM token consumption rankings; Rejected: raw keyword search trends, macro clearing volumes. | Alternative Signal Registry |

---

## 3. Data Schema & Seed Layer Contracts

### 3.1 `thesis_claims.csv` (Human-Authored Thesis Boundaries)
```csv
claim_id,entity_id,thesis_title,claim_text,invalidation_rule,status,last_reviewed_at_utc,reviewed_by,registry_version
TENCENT_THESIS_BULL_AI_ADS,TENCENT,Bull Case: AI Ad Efficiencies (AIM+) & Agentic Workflows,AI advertising algorithm upgrades (AIM+) and agentic workflow integration (Xiaowei and WorkBuddy) sustain mid-teens profit growth and re-expand forward P/E toward >18x.,Gross Margin falls below 55.0% for 2 consecutive quarters; OR Marketing Services YoY revenue growth slows below 12.0%; OR 2H2026 Free Cash Flow remains negative without offsetting gross receipts.,active,2026-08-21T00:00:00Z,research_analyst,v1
TENCENT_THESIS_BASE_COMPOUNDER,TENCENT,Base Case: Core Gaming & Advertising Compounder with P/E Floor,Evergreen gaming franchise and high-margin ad network compound operating earnings at 8-11% YoY; CapEx stabilizes near RMB130B-150B/yr; statutory buybacks + rising dividend payouts establish a 12-15x P/E floor.,Non-IFRS operating profit growth turns flat or negative (<0% YoY); OR Quarterly CapEx exceeds RMB65.0B without incremental Cloud/AI enterprise revenue; OR Buyback execution halts for >30 consecutive trading days without statutory blackout justification.,active,2026-08-21T00:00:00Z,research_analyst,v1
TENCENT_THESIS_BEAR_CAPEX_TRAP,TENCENT,Bear Case: AI CapEx Dilution & Agentic Monetization Hurdle,AI CapEx represents a value-diluting hardware arms race; WeChat agent monetization stalls behind privacy and latency hurdles; domestic gaming gross receipts peak.,Domestic Games gross receipts return to >15.0% YoY sustainable growth; OR WeChat Xiaowei achieves daily token monetization >RMB50.0M; OR Free Cash Flow rebounds to >RMB45.0B/quarter.,active,2026-08-21T00:00:00Z,research_analyst,v1
```

### 3.2 `thesis_watch_questions.csv` (Operational Falsification & Support Questions)
```csv
question_id,claim_id,entity_id,question,question_type,priority,registry_version
TENCENT_TWQ_AIM_GROWTH,TENCENT_THESIS_BULL_AI_ADS,TENCENT,Does Marketing Services / Online Advertising maintain YoY revenue growth >= 15% with expanding gross margins?,support,1,v1
TENCENT_TWQ_FCF_INFLECTION,TENCENT_THESIS_BULL_AI_ADS,TENCENT,Does quarterly Free Cash Flow inflect back to positive territory in 2H2026 as initial compute hardware prepayments settle?,falsification,1,v1
TENCENT_TWQ_NON_IFRS_OP_FLOOR,TENCENT_THESIS_BASE_COMPOUNDER,TENCENT,Does Non-IFRS operating profit maintain positive YoY growth (>= 8%) despite new AI product operating drag?,falsification,1,v1
TENCENT_TWQ_BUYBACK_CADENCE,TENCENT_THESIS_BASE_COMPOUNDER,TENCENT,Do statutory HKEX Next-Day Disclosure returns demonstrate continuous daily share repurchases within the targeted HKD20B-30B half-year pace?,support,2,v1
TENCENT_TWQ_CAPEX_CEILING,TENCENT_THESIS_BEAR_CAPEX_TRAP,TENCENT,Does quarterly capital expenditure exceed RMB65.0B without corresponding acceleration in enterprise cloud or AI revenue?,support,1,v1
TENCENT_TWQ_GAME_PIPELINE_RECEIPTS,TENCENT_THESIS_BEAR_CAPEX_TRAP,TENCENT,Are domestic evergreen game gross receipts decelerating below 5% YoY or losing market share to competing domestic releases?,support,2,v1
```

### 3.3 `evidence_items.csv` (Source-Backed Evidence Ledger)
```csv
evidence_id,source_type,source_id_ref,published_at,summary_text,observed_at_utc,registry_version
EVID_TENCENT_2Q2026_RESULTS_FILING,filing,https://www.tencent.com/wp-content/uploads/2026/08/Tencent-Announces-2026-Second-Quarter-Results.pdf,2026-08-12T20:00:00+08:00,"Tencent 2Q2026 Results: Total revenue RMB204.8B (+11% YoY), Non-IFRS Op Profit RMB75.6B (+9% YoY, or +19% YoY ex-New AI drag). CapEx surged 176% YoY to RMB52.8B driving negative quarterly FCF of -RMB13.8B due to AI compute prepayments.",2026-08-12T12:00:00Z,v1
EVID_TENCENT_1Q2026_RESULTS_FILING,filing,https://static.www.tencent.com/uploads/2026/05/13/47382ae415a209fd161bc19a1f9b3704.pdf,2026-05-13T20:00:00+08:00,"Tencent 1Q2026 Results: Revenue RMB196.4B (+10% YoY), Non-IFRS Op Profit RMB71.2B (+12% YoY), Free Cash Flow +RMB56.7B.",2026-05-13T12:00:00Z,v1
EVID_TENCENT_FY2025_ANNUAL_RESULTS,filing,https://static.www.tencent.com/uploads/2026/03/18/e6a646796d0d869acc76271c9ee1a6a5.pdf,2026-03-18T20:00:00+08:00,"Tencent FY2025 Annual Results: Management guided moderation of share buybacks from HKD80B peak to fund AI capex; raised dividend 18% to HKD5.30/share.",2026-03-18T12:00:00Z,v1
EVID_TENCENT_NDD_BUYBACKS_AUG2026,corporate_action,hkex:next_day_disclosure_returns_20260818,2026-08-18T18:30:00+08:00,"HKEX Statutory Next Day Disclosure: Tencent repurchased ~2.6M shares at average HK$455-460 for ~HKD1.2B aggregate daily spend following 2Q26 earnings blackout window.",2026-08-18T10:30:00Z,v1
EVID_TENCENT_CONSENSUS_FY26E_REVISION,consensus_revision,consensus_snapshots_store:0700_HK_20260815,2026-08-15T00:00:00Z,"Sell-side consensus updated post-2Q26 results: FY26E revenue trimmed to RMB826.6B (+10.0% YoY); Non-IFRS EPS estimate revised to RMB29.08 (+4.3% YoY) incorporating 2H26 AI compute depreciation.",2026-08-15T04:00:00Z,v1
```

### 3.4 `claim_evidence_links.csv` (Conflict Flagging Matrix)
```csv
link_id,claim_id,evidence_id,conflict_hint,review_state,analyst_note,registry_version
LINK_TENCENT_BULL_2Q26_FCF,TENCENT_THESIS_BULL_AI_ADS,EVID_TENCENT_2Q2026_RESULTS_FILING,true,acknowledged,"2Q26 FCF of -RMB13.8B touches bull invalidation condition; normalized FCF was RMB37.6B ex-prepayments. Monitor 2H26 inflection.",v1
LINK_TENCENT_BASE_2Q26_OP,TENCENT_THESIS_BASE_COMPOUNDER,EVID_TENCENT_2Q2026_RESULTS_FILING,false,acknowledged,"Non-IFRS operating profit grew 9% YoY (+19% ex-AI), supporting compounder base case above 0% floor.",v1
LINK_TENCENT_BEAR_2Q26_CAPEX,TENCENT_THESIS_BEAR_CAPEX_TRAP,EVID_TENCENT_2Q2026_RESULTS_FILING,false,acknowledged,"CapEx surged 176% YoY to RMB52.8B, providing initial confirmation of elevated capex drag; monitor whether 2H26 exceeds RMB65B/quarter ceiling.",v1
LINK_TENCENT_BASE_BUYBACKS,TENCENT_THESIS_BASE_COMPOUNDER,EVID_TENCENT_NDD_BUYBACKS_AUG2026,false,acknowledged,"Statutory buybacks resumed immediately post-earnings blackout at ~HKD1.2B/day.",v1
LINK_TENCENT_BULL_CONSENSUS_REVISION,TENCENT_THESIS_BULL_AI_ADS,EVID_TENCENT_CONSENSUS_FY26E_REVISION,true,pending_review,"Consensus expects moderate 4.3% Non-GAAP EPS growth for FY26E, reflecting market conservatism on AI margins.",v1
```

---

## 4. Cockpit User Experience & Tab Navigation

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        Tencent Holdings (0700.HK / TCEHY) Cockpit                      │
│ Primary Listing: HKEX 0700.HK  │  Reporting: RMB / IFRS  │  Status: Active Stage 1     │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ [ Tab 1: Overview ]                                                                    │
│   • Quote Banner: HK$457.00 (+1.2%), Volume 18.4M shares, Quote Freshness SLA Verified │
│   • Flight Deck: 1 Confirmed Hard result, 3 Active Thesis Checkpoints, 1 Pending Alert │
│   • Peer Matrix: Side-by-side valuation comparison with ByteDance & Alibaba            │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ [ Tab 2: Fundamentals & Capital Returns ]                                              │
│   • Segment Revenue & Margin Trends: VAS, Marketing Services, FinTech & Cloud          │
│   • Profitability & Prepayment Bridge: Core Non-IFRS Op Profit vs. New AI Product Drag │
│   • Free Cash Flow Trajectory: Reported FCF (-RMB13.8B) vs Normalized FCF (RMB37.6B)  │
│   • Statutory Buyback Pacing: Daily HKEX NDD repurchase bars & cumulative HKD spend    │
│   • Valuation Multiples: Forward Non-GAAP P/E (13.2x), FCF yield, Cash return yield    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ [ Tab 3: Thesis & Catalysts ]                                                          │
│   • Active Thesis Cards: Bull (AI Ads & Agents), Base (Compounder), Bear (Capex Trap)  │
│   • Invalidation Rule Box: Explicit thresholds for margin, revenue deceleration & FCF  │
│   • Catalyst Roadmap: 3Q26 Window (Nov 2026), FCF Inflection Checkpoint, NPPA Cadence  │
│   • Operational Watch Questions: Priority badges & support/falsification tagging       │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ [ Tab 4: Evidence & Lineage ]                                                          │
│   • Lineage Table: Source URLs, statutory filing accession IDs, published timestamps   │
│   • Consensus Revision History: Trajectory of sell-side forward estimates              │
│   • Claim-Evidence Matrix: Evidence cards with Conflict Alert status badges            │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Alternative Data Triage & Quality Evaluation

| Data Feed | Mechanism & Cadence | Reliability & Licensing | Cockpit Verdict |
|---|---|---|---|
| **HKEX Next-Day Share Repurchase Returns** | Daily disclosure (T+0, ~18:00 HKT) of shares repurchased, price band, and consideration paid. | **Free & Official**. Highest legal reliability. | **TIER 1 (Must Include)** |
| **NPPA Game Publishing License Releases** | Monthly official notices of domestic and imported game approval ISBNs. | **Free & High Reliability**. Direct regulatory source. | **TIER 1 (Must Include)** |
| **OpenRouter LLM Token API Consumption** | Daily tracking of Hy3 and Hunyuan enterprise token volume and rank. | **Free & High Signal**. High relevance for AI enterprise adoption. | **TIER 2 (High Signal)** |
| **Grossing Rank Deltas (iOS / Android)** | Daily App Store grossing rank movements for *Delta Force*, *HoK*, *Peacekeeper Elite*. | **Freemium / Sensitive**. Must not be used without download/revenue weighting. | **TIER 2 (Use with Caution)** |
| *WeChat Index / Baidu Search Trends* | Daily search query volume for brand keywords. | **Free / High Noise**. Vanity metrics with negligible revenue correlation. | **REJECTED (Do Not Include)** |
| *PBOC Payment Clearing Statistics* | Monthly aggregate transaction volume. | **Free / Diluted**. Too macro-aggregated to isolate WeChat Pay market share. | **REJECTED (Do Not Include)** |
| *CCASS Broker Custodial Transfers* | Daily clearing participant movements. | **Free / Misleading**. High attribution error; confuses ADR conversions with buying. | **REJECTED (Misleading)** |

---

## 6. Integration Contract & Next Steps

1. **Loader & Validator Module**: `src/research_control_tower/thesis_seed.py` exposes:
   * `load_thesis_seed_bundle(config_root: Path) -> ThesisSeedBundle`
   * `validate_thesis_seed_bundle(thesis, registries, events, now_utc) -> list[ValidationIssue]`
   * `load_tencent_event_seed_bundle(config_root: Path) -> EventBundle`
   * `merge_event_bundles(base: EventBundle, addition: EventBundle) -> EventBundle`
   * Helper query functions: `get_entity_thesis_claims`, `get_claim_watch_questions`, `get_claim_evidence`, `count_active_conflicts`.
2. **Deterministic Test Suite**: `tests/test_research_control_tower_thesis_seed.py` runs 11 focused unit tests covering loading, validation, edge cases, foreign key integrity, and event seed merging.
3. **Downstream Integration**: The dedicated Integration Worker will incorporate the additive read-marts (`thesis_claims.parquet`, `thesis_watch_questions.parquet`, `evidence_items.parquet`, `claim_evidence_links.parquet`) into `build.py` and render the 4-tab cockpit in `apps/research-control-tower/`.

