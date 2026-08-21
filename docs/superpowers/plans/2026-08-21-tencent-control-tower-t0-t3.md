# Research Control Tower — Tencent T0–T3 Implementation Plan

**Date:** 2026-08-21
**Status:** DESIGN REVIEW GATE — 等待用户对 design spec 的书面审查（written spec review）；gate 通过前不实施任何代码
**Repo:** `alternative-data`（integration branch `codex/tencent-control-tower-t0-t3`）
**Worktree:** 本计划与 spec/TODO 的契约收尾在专用 worktree `/private/tmp/rct-tencent-t0-t3-20260821` 完成（未提交、未推送）；不触碰 root shared worktree 工作副本
**Design spec:** `docs/superpowers/specs/2026-08-21-research-control-tower-tencent-t0-t3-design.md`
**Target:** TENCENT (0700.HK primary; TCEHY US OTC DR — 仅 gated identity research，官方验证前 collection_eligible=false，不阻塞 0700 vertical slice)，companion BYTEDANCE (private)

## 0. Objective

Complete the Tencent vertical slice through four gates:
**T0** correctness/PIT/identity/metric basis · **T1** unified official facts & corporate actions + specialised Tencent IR parser · **T2** provider consensus / own estimates / management guidance / valuation · **T3** source-backed catalysts / manual thesis / watch questions / evidence.
Unified pipeline for structured official sources (HKEX/yfinance/FRED/consensus); specialised collectors only for company-specific sources (Tencent IR segment financials, NPPA); every output obeys the unified evidence contract (pit_class, timestamps, source_url, schema-validated). T4+ items go to TODO.

**Scope exclusions (deferred to TODO, not part of T0–T3):** Kuaishou; global macro upcoming-calendar wiring; news (news_filings) network wiring; unverified Xiaowei/H200 milestones.

## 1. Current-state evidence (bundle local-sources-20260819T003448Z, status degraded)

- T0: TENCENT entity + 0700_HK listing verified (2026-08-13, official HKEX source) OK; TCEHY_US listing MISSING (gated research only).
- T0: quote 0700.HK delayed yfinance OK (SLA bug: 5-min threshold vs delayed data → quote always degraded); price_bars 0700.HK 5y daily 2021-08-20→2026-08-07 OK (pit_class=current_vintage, vendor replay).
- T1: official_filings TENCENT=173 HKEX announcements covering 2025-08-18→2026-08-18, including recurring Next-Day Disclosure rows (not all 173 are buybacks) OK all event_class=general (no buyback/dividend classification); earnings_calendar TENCENT 3 observed rows (FY25 2026-03-18, Q1 2026-05-13, 1H26 2026-08-12) OK; earnings_actuals TENCENT=0 MISSING.
- T2: consensus_snapshots TENCENT=11 — yfinance 8 × `snapshot_from_live_source` + akshare 3 × `snapshot_from_delayed_source`; 3 duplicate snapshot_id rows (3 akshare rows share one id) MISSING; akshare stale-health bug 保留 (provider_asof 2026-07-26 — 24d stale yet flagged available); consensus_revisions TENCENT=16 all yfinance `reconstructed_sparse` (cold start) OK/warn (bundle-wide 112 rows cover multiple entities, not only Tencent).
- T3: events=15 rows, ZERO Tencent; event_watch_questions=10 rows none for Tencent; no thesis/evidence marts MISSING.
- news_filings: 2045 filing rows, zero news (news wiring out of scope; Batch 5 collector code merged, not wired — no keys).

## 2. Workstreams (non-overlapping write-sets)

| WS | Gate | Scope | Write-set |
|---|---|---|---|
| A | T0+T1 | TCEHY_US listing gated research (official depositary/filings verification only; collection_eligible=false until verified); corporate_actions mart (buybacks/dividends) — **unified HKEX corporate-actions pipeline** (NDD parser: PDF metadata + numeric fields, price_min/max, total_amount_paid, cancellation), test fixtures | config/research_control_tower/listings.csv (+official_source_identity.csv if needed), new scripts/research_control_tower_corporate_actions.py (or extend official_filings collector), tests/test_research_control_tower_corporate_actions.py, docs updates. **build.py wiring handled sequentially by integration worker (WS order A→B→C→E), never in parallel.** |
| B | T1+T2 | Tencent earnings_actuals specialised collector: 2021Q1→latest; **≥12 quarters is the TARGET for core metrics (revenue_total, operating_profit, net_profit_attributable, diluted_eps)** — non-core source-specific metrics (deferred_revenue_current, subsegments) allow documented coverage gaps and are never a per-quarter-per-metric hard failure; both GAAP_REPORTED and NON_IFRS_MANAGEMENT tracks when disclosed; is_restatement handling; from official Tencent IR results PDFs (tencent.com wp-content/static URLs, HKEX x-ref); fix consensus akshare snapshot_id uniqueness + consensus_period_mapping for **0700.HK only** + stale provider_asof semantics | new scripts/research_control_tower_tencent_financials.py (or extend earnings_actuals), src/research_control_tower/earnings_actuals.py, scripts/research_control_tower_consensus_collector.py, consensus_period_mapping source (config/research_control_tower/consensus_period_mapping.csv or sibling export), tests/*. **build.py wiring sequentially by integration worker.** |
| C | T2+T3 | valuation_snapshots mart (forward_pe / ev_ebitda / fcf_yield / shareholder_cash_return_yield with numerator/denominator vintages + fx logs; percentile unavailable without denominator vintages); internal_estimates mart (schema + config-research CSV, manual ingestion contract: management_guidance / internal_estimate) | config/research_control_tower/internal_estimates.csv, new scripts/research_control_tower_valuation.py, tests/*. **build.py wiring sequentially by integration worker.** |
| D | T3 | Tencent cockpit UI plan + seed content (NO canonical-data mutation): 4 tabs (Overview / Fundamentals / Thesis & Catalysts / Evidence), thesis_claims seed (bull/base/bear from existing cockpit research brief), event_watch_questions seed, catalyst event taxonomy (hard/provisional/thesis_checkpoint: board meetings, NPPA windows, buyback cadence), evidence_items+claim_evidence_links modeling; design doc + seed CSVs as DRAFT in docs (implementer enriches) | docs/superpowers/plans/2026-08-21-tencent-t3-thesis-ui-design.md, docs draft seed CSVs |
| E | T3 | Thesis & evidence read marts: thesis_claims / thesis_watch_questions / evidence_items / claim_evidence_links schemas as additive optional marts (preserve existing events & event_watch_questions contract unchanged); app rendering via repository/coverage states | apps/research-control-tower/control_tower/... , tests/* **（本 WS 不直接改 build.py；schema+wiring 由 integration worker 串行应用其 diff）** |
| F | research only | TCEHY DR ratio/role verification research notes (feeds WS-A gated row); FX/RMB-HKD-USD valuation protocol note (feeds WS-C); NPPA feasibility probe (robots/anti-bot, cadence, fields) as T4.1 evidence | docs/research-control-tower/tencent_tcehy_dr_research.md, docs/research-control-tower/tencent_valuation_fx_protocol.md, docs/research-control-tower/nppa_feasibility_probe.md (research only, no code) |

**Integration worker (dedicated DeepSeek v4 Flash subagent, ultra):** the only role that touches shared files (build.py / repository / registries). It applies each reviewed WS diff sequentially in order A→B→C→E, resolves conflicts, and merges into the integration branch. Main session never edits shared files; it orchestrates, reviews, and runs the final verification (build + tests + bundle + browser QA).

## 3. Hard constraints (all workstreams)

1. Read AGENTS.md, CLAUDE.md, docs/asia-markets/OPERATING_MANUAL.md, this plan, and the design spec first.
2. Never modify files outside your write-set; never touch `/Users/henrywzh/Quant/alternative-data/.config` (secrets), other worktrees, other branches. Each WS writes in its own child worktree; only the integration worker writes shared files, in the integration worktree.
3. Builder/UI are network-forbidden; all collection happens in scripts/*.py collectors.
4. PIT vocabulary (verbatim, from src/research_control_tower build + source_badges; a flat vocabulary, not an ordered hierarchy): `snapshot_from_live_source` / `snapshot_from_delayed_source` / `repository_captured` / `true_pit` / `dated_public_broker_report` / `reconstructed_sparse` / `current_vintage` / `not_pit`. `official_filing` is NOT a pit_class. `official_external` / `source_observation` / `internal_research` are event **evidence_class**, never pit_class. Never promote reconstructed_sparse/current_vintage to true_pit; reconstructed_sparse is cold-start context only and never drives headline revision breadth. yfinance eps_trend stays isolated.
5. Currency/accounting: Tencent reports CNY; 0700.HK quotes HKD; TCEHY USD. Valuation conversions log fx_rate_applied/fx_source/fx_snapshot_at_utc. accounting_basis keeps source raw label; metric_basis is the canonical enum (GAAP_REPORTED / NON_IFRS_MANAGEMENT / PROVIDER_UNVERIFIED). GAAP vs Non-IFRS never blended.
6. No fake exact dates; uncertain windows carry date_precision + starts_at/ends_at. events.parquet certainty_class/date_precision and event_watch_questions columns stay exactly on the existing contract.
7. Test-first; run focused tests before finishing; keep existing 14-test RCT suite green.
8. Each implementation WS works in its own child branch + worktree (e.g. `codex/rct-tencent-a`) created from the integration branch tip; commit only your write-set; never push directly to the integration branch. The integration worker merges child branches sequentially in WS order A→B→C→E into `codex/tencent-control-tower-t0-t3`; no two agents ever write the integration branch or shared files concurrently. Report commit sha + test output per WS.
9. All work max effort; verify with real commands, no fabricated output.

## 4. Model orchestration (main session = orchestrator/reviewer only)

- **T3 seed + UI implementation (WS D/E):** Gemini 3.7 Flash (ultra) — thesis/evidence seed, event taxonomy, cockpit UI, read-mart schemas
- **T0/T1/T2 implementation (WS A/B/C):** OpenCode Go DeepSeek v4 Flash (ultra), non-overlapping write-sets
- **Integration worker (shared build.py/repository changes):** dedicated DeepSeek v4 Flash (ultra) subagent, serial A→B→C→E application
- **Exploration / UX / design critique:** Gemini 3.7 Flash (ultra)
- **Final code review:** Z.ai GLM 5.3 (ultra); if unavailable, fall back to Luna (max effort)
- Main session never implements and never edits shared files; it plans, reviews, audits, and runs final verification (build + tests + browser QA).

## 5. Acceptance / verification commands

```bash
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
```

## 6. Merge sequence

WS branches → GLM 5.3 (ultra) code review per WS → fix wave → sequential merge into
codex/tencent-control-tower-t0-t3 (dedicated DeepSeek integration worker applies shared
build.py/repository changes in WS order A→B→C→E, one WS at a time, no concurrent writes)
→ integration tests+bundle+browser → main (main session reviews final state).

## 7. TODO — T4+（backlog，见 docs/research-control-tower/TODO.md）

T4.1 NPPA automation; T4.2 WeChat ecosystem public signals; T4.3 SOTP listed portfolio tracker;
T4.4 Southbound Stock Connect flows; T4.5 app-intel diligence (SensorTower etc.); Batch 8 alt-data
signals for Tencent (OpenRouter Hy3/Hunyuan usage, validated share-float/positioning feeds only — App-store
rankings never used unconditionally as a signal); daily scheduling (quote/consensus/filings cron);
news provider wiring (keys); global macro upcoming-calendar wiring; Stage 1.5 (Cathay/MTR/SHKP/Midland)
using same pipelines; deployment licensing audit.
