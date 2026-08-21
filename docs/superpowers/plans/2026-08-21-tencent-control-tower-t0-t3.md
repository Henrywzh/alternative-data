# Research Control Tower — Tencent T0–T3 Implementation Plan

**Date:** 2026-08-21
**Status:** ACTIVE — implementation wave 1
**Repo:** \`alternative-data\`（integration branch \`codex/tencent-control-tower-t0-t3\`）
**Design spec (approved):** \`docs/superpowers/specs/2026-08-21-research-control-tower-tencent-t0-t3-design.md\`
**Target:** TENCENT (0700.HK primary; TCEHY US OTC DR — role/ratio/type verified before activation), companion BYTEDANCE (private)

## 0. Objective

Complete the Tencent vertical slice through four gates:
T0 correctness/PIT/identity/metric basis · T1 unified official facts & history
T2 expectations/consensus/valuation · T3 catalysts/thesis/watch-questions/invalidation.
Unified pipeline for structured official sources (HKEX/yfinance/FRED/consensus);
specialised collectors only for company-specific sources (Tencent IR segment
financials, NPPA); every output obeys the unified evidence contract
(pit_class, timestamps, source_url, schema-validated). T3+ items go to TODO.

## 1. Current-state evidence (bundle local-sources-20260819T003448Z, status degraded)

- T0: TENCENT entity + 0700_HK listing verified (2026-08-13, official HKEX source) ✓; TCEHY_US listing MISSING.
- T0: quote 0700.HK delayed yfinance ✓ (SLA bug: 5-min threshold vs delayed data → quote always degraded); price_bars 0700.HK 5y daily 2021-08-20→2026-08-07 ✓ (pit_class=current_vintage, vendor replay).
- T1: official_filings TENCENT=173 HKEX announcements (Next-Day Disclosure buyback daily 2025-08-18→2026-08-18) ✓ all event_class=general (no buyback/dividend classification); earnings_calendar TENCENT 3 observed rows (FY25 2026-03-18, Q1 2026-05-13, 1H26 2026-08-12) ✓; earnings_actuals TENCENT=0 ✗.
- T2: consensus_snapshots TENCENT=11 (akshare relay, provider_asof 2026-07-26 — 24d stale) with fiscal_year=NULL NaN and 10 duplicate snapshot_ids ✗; consensus_revisions 112 rows all pit_class=reconstructed_sparse (cold start) ✓/⚠.
- T3: events=15 rows, ZERO Tencent; event_watch_questions=10 rows none for Tencent; no thesis/evidence marts ✗.
- news_filings: 2045 filing rows, zero news (Batch 5 collector code merged, not wired — no keys).

## 2. Workstreams (non-overlapping write-sets)

| WS | Gate | Scope | Write-set |
|---|---|---|---|
| A | T0+T1 | TCEHY_US listing research+row (role/ratio/type from official depositary/filings before active; else collection_eligible=false); corporate_actions mart (buybacks/dividends) — unified HKEX NDD parser (PDF metadata + numeric fields, price_min/max, total_amount_paid, cancellation), test fixtures; build.py wiring + source_health | config/research_control_tower/listings.csv (+official_source_identity.csv if needed), new scripts/research_control_tower_corporate_actions.py (or extend official_filings collector), src/research_control_tower/build.py (corporate_actions schema+mart), tests/test_research_control_tower_corporate_actions.py, docs updates |
| B | T1+T2 | Tencent earnings_actuals specialised collector: 2021Q1→latest (target ≥12 quarters, both GAAP_REPORTED and NON_IFRS_MANAGEMENT tracks when disclosed): revenue_total, revenue_vas(+subsegments when clean), revenue_online_ads/marketing_services, revenue_fintech_cloud, operating_profit, net_profit_attributable, diluted_eps, deferred_revenue_current; is_restatement handling; from official Tencent IR results PDFs (tencent.com wp-content/static URLs, HKEX x-ref); fix consensus akshare snapshot_id uniqueness + consensus_period_mapping for 0700.HK (+1024/9626/9988/9888) + stale provider_asof semantics; internal_estimates mart (schema + config-research CSV, manual ingestion contract) | new scripts/research_control_tower_tencent_financials.py (or extend earnings_actuals), src/research_control_tower/earnings_actuals.py, scripts/research_control_tower_consensus_collector.py, consensus_period_mapping source (config/research_control_tower/consensus_period_mapping.csv or sibling export), src/research_control_tower/build.py (internal_estimates), tests/* |
| C | T3 data+UI design & seed | Design + draft content (NO canonical-data mutation): Tencent cockpit UI plan (4 tabs), thesis_claims seed (bull/base/bear from existing cockpit research brief §6 Falsifiable Thesis Matrix), event_watch_questions seed, catalyst event taxonomy (hard/provisional/thesis windows: board meetings, NPPA windows, buyback cadence, Xiaowei/H200 milestones), evidence_items+claim_evidence_links modeling; produce design doc + seed CSVs as DRAFT in docs (implementer enriches) | docs/superpowers/plans/2026-08-21-tencent-t3-thesis-ui-design.md, docs draft seed CSVs |
| D | T3/T4 research | Macro upcoming-calendar design for US/CN/HK (release events into events.parquet, unified, no keys), NPPA feasibility probe (robots/anti-bot, cadence, fields) as T4.1 evidence, TCEHY DR ratio/role verification research notes (feeds WS-A), Fx/RMB-HKD-USD valuation protocol note (T2 UI) | docs/research-control-tower/tencent_macro_nppa_probe.md + related notes (research only, no code) |

## 3. Hard constraints (all workstreams)

1. Read AGENTS.md, CLAUDE.md, docs/asia-markets/OPERATING_MANUAL.md, this plan, and the design spec first.
2. Never modify files outside your write-set; never touch \`/Users/henrywzh/Quant/alternative-data/.config\`(secrets), other worktrees, other branches.
3. Builder/UI are network-forbidden; all collection happens in scripts/*.py collectors.
4. PIT grammar: official_filing > repository_captured > dated_broker_report > reconstructed_sparse > not_pit. Never promote reconstructed_sparse/current_vintage to true_pit. yfinance eps_trend stays isolated from headline revision breadth.
5. Currency/accounting: Tencent reports CNY; 0700.HK quotes HKD; TCEHY USD. Valuation conversions log fx_rate_applied/fx_source/fx_snapshot_at_utc. GAAP vs Non-IFRS never blended.
6. No fake exact dates; uncertain windows carry date_precision + starts_at/ends_at.
7. Test-first; run focused tests before finishing; keep existing 14-test RCT suite green.
8. Commit on a NEW branch from main named codex/rct-tencent-<ws>; commit only your write-set; do not merge main; report commit sha + test output.
9. All work max effort; verify with real commands, no fabricated output.

## 4. Acceptance / verification commands

\`\`\`bash
cd /Users/henrywzh/Quant/alternative-data
.venv/bin/pytest -q tests/test_research_control_tower_build.py tests/test_research_control_tower_registries.py \
  tests/test_research_control_tower_events.py tests/test_research_control_tower_official_filings.py \
  tests/test_research_control_tower_earnings_actuals.py tests/test_research_control_tower_consensus_revisions.py \
  tests/test_research_control_tower_repository.py tests/test_research_control_tower_streamlit.py \
  tests/test_research_control_tower_privacy.py tests/test_research_control_tower_coverage_states.py \
  tests/test_research_control_tower_macro_sources.py tests/test_research_control_tower_market_data.py \
  tests/test_research_control_tower_quote_collector.py tests/test_research_control_tower_news_collector.py
.venv/bin/python scripts/build_research_control_tower.py          # staging build
.venv/bin/python scripts/build_research_control_tower.py --publish
.venv/bin/streamlit run apps/research-control-tower/app.py --server.headless true --server.port 8511
# browser QA: Today / Unified Timeline / Tencent Company cockpit tabs / Source Health; light+dark; no console errors
\`\`\`

## 5. Merge sequence

WS branches → GLM-5.2/max code review per WS → fix wave → sequential merge into
codex/tencent-control-tower-t0-t3; then integration tests+bundle+browser; then main.

## 6. TODO — T3 之后（backlog，见 docs/research-control-tower/TODO.md）

T4.1 NPPA automation; T4.2 WeChat ecosystem public signals; T4.3 SOTP listed portfolio tracker;
T4.4 Southbound Stock Connect flows; T4.5 app-intel diligence (SensorTower etc.); Batch 8 alt-data
signals for Tencent; daily scheduling (quote/consensus/filings cron); news provider wiring (keys);
Stage 1.5 (Cathay/MTR/SHKP/Midland) using same pipelines; deployment licensing audit.

