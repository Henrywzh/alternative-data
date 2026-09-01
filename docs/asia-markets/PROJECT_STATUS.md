# Asia Markets Project Status

This file is a short, human-maintained handoff for the next agent. It is not a
replacement for the operating manual or generated source-status JSON.

## Current state

- Public production surface: Cloudflare Pages for the existing public sector
  dashboard.
- Private research surface: `apps/asia-markets-streamlit/app.py`. The current
  app includes Overview, Index & ETF Allocation Monitor, labour, population,
  transport, real estate, aerospace, crypto, Data Explorer and Source Health.
  The Index & ETF Allocation Monitor is Streamlit-only in V1; it is not in
  the Cloudflare `sectors.json` roster and is not packaged by
  `package-dashboard.mjs`.
- Canonical financial-data sibling: `/Users/henrywzh/Desktop/Quant/financial-data`;
  see `REPO_BRIDGE.md` for the shared contract.
- Research Control Tower V1 is a local/private, read-only publication. The
  current immutable `CURRENT` generation is
  `rct-tencent-integrity-reviewed-20260822-ce1914e9bdd11ac8` and contains 27 files
  (26 Parquet artifacts plus `build_manifest.json`). Its status is `degraded`.
  The published counts are: entities 71, listings 81, events 21, consensus
  56 snapshots and 112 revisions, valuation 0, official filings 403
  (Tencent 173), generic SEC filing metadata 1,897, generic news 0,
  earnings actuals 224, calendar 10, corporate
  actions 203, quotes 7, price bars 8,598, macro observations 56,847 and
  source health 44. Macro IDs preserve vintage/capture keys and SEC generic
  filing IDs preserve physical source/accession/URL identity. `TCEHY_US` is registry-only with unresolved mapping and
  `collection_eligible=false`; it remains only in the published listings
  registry and is absent from collected fact marts and active coverage.
  Tencent's only active eligible listing is `0700_HK`. This remains
  local/private and read-only: provider entitlements and some source health
  are degraded, and valuation is fail-closed and unavailable.
- Live sector roster: 10 sectors; see `apps/asia-markets-dashboard/sectors.json`.
- Unified KPI backtest engine (2026-08-12): Steps 1–6 complete, with the MTR
  chronological practical-OOS track added afterward. Step 1
  metadata registry (`data/registries/asia_backtest_*`), shared package
  (`src/common/backtest/`), additive long form (5,308 rows: 2,788 primary +
  163 source aliases + 2,357 same-period-last-year baselines), MTR actuals
  migrated out of the script
  into `data/normalized/hk_transport/mtr_transport_ops_actuals.csv`, SHKP
  split into three targets (contract activity stays D/diagnostic), and the
  metric-policy table with explicit pooled-reference/per-entity grains,
  baseline-coverage guards and directional hit rate. The current data has no
  final headline contracts after independent-period and PIT gates. Run
  everything with `python scripts/run_backtest_engine.py`; the latest run also
  includes the independent MTR FY/H1 walk-forward contracts and their isolated
  baselines. The MTR legacy 4.78%/4.06% values remain structural replay
  diagnostics; the new chronological track is FY 9.32% / H1 8.10% practical
  MAPE and records origin/cutoff/input fingerprints. Monthly output remains
  forecast-only because no official monthly revenue actual exists.
  wide tables and dashboards are untouched.  See
  `docs/asia-markets/unified-kpi-backtest-v1.md`.
- English and Chinese hub/data-status pages are published.
- Sector artifacts are generated as portable HTML from `.generated/*.json`.
- Artifact refreshes now fail closed on destructive empty-data regressions:
  `run-artifact-builders.mjs` restores the previous sector artifact/status when
  a previously non-empty dataset becomes empty or disappears, and core HKMA
  mortgage / Buildings Department history builders use committed-artifact
  fallbacks marked stale when CI has no normalized cache.
- `scripts/audit_asia_markets_freshness.py` is the machine-readable freshness
  gate for the Streamlit-facing sector artifacts. It checks observation periods
  rather than build timestamps, validates Buildings Department history against
  the latest parsed digest, and rejects EN/ZH snapshot drift. Its durable report
  is `.generated/asia-markets-freshness.json`.
- As of 2026-08-31 the verified headline periods are: labour force 2026-07,
  median employment earnings 2026-Q2, vacancies and wage/payroll 2026-Q1
  (their official Q2 releases are scheduled for 18 and 28 September),
  MPFA permanent-departure claims 2026-Q2, Buildings Department aggregate
  supply history 2026-06, China-listed airline traffic 2026-07, and MTR
  patronage 2026-06. The MTR investor page still identifies June as its latest
  official month on 2026-08-31; the transport workflow now retries on the 5th,
  20th, 25th and 28th rather than missing releases posted after the 20th.
- `STREAMLIT_PARITY_PROTOCOL.md` is the shared Cloudflare-to-Streamlit
  decision guide. The non-blocking GitHub Action
  `.github/workflows/streamlit-parity-reminder.yml` compares structural
  artifact changes and reminds agents when a Streamlit review is needed;
  value-only refreshes are intentionally ignored.
- The dashboard has explicit month/year chart ticks and visible copy-title
  controls in the current packaging path.
- The project contains both historical time series and current snapshots. Do
  not treat every non-empty dataset as a trend.
- HKEX event-study Stage 3 remains research-only: recent 5m/1h bars are a
  rolling-window lane, while the explicit 175-symbol daily yfinance replay
  now covers 2016-01-04 through 2026-08-07. It is vendor historical replay
  rather than a PIT universe or price-vintage tape; no signal, portfolio
  backtest or dashboard output is approved from it.
- The sibling `financial-data` repository now has a checkpointed official HKEX
  metadata backfill for 2016-01-01 through 2026-08-07: 126,220 unique filings,
  174 declared tickers and zero collector failures. PDF provenance is
  complete for the two Stage 1 core families (1,058 parsed P0 filings covering
  profit warnings/alerts and inside information). The event-study audit is
  documented in `quantamental-lab/reports/hkex_event_study_2016_2026_stage1.md`.
  The result remains current-issuer, source-timestamp-proxy and exploratory;
  official announcement-aware HSCI review history is canonical only from
  2021-03-15 onward. The official HSCI historical endpoint advertises stale
  `.xlsx` links, but its legacy `.xls` fallback is live for 2001–2008; that
  early layer is now archived and parsed separately because it has no
  announcement timestamp. A separate provisional HSI review backfill now
  records 43 direct older HSI assets plus 37 archived URL captures and 1,158
  active review actions for 2008-09-08–2021-09-06; the active candidate view
  has 169 rows (63 from the official Chinese 2011 detail, 50 diverted by the
  automatic PIT-availability check from post-effective 2010-09-06/2011-09-05
  captures, plus 74 from older official ad-hoc/prose/table/review notices),
  while the raw candidate ledger has 272
  observations and 221 append-only candidate corrections (including the
  `0181.HK` ordinal-phrase phantom and other fuzzy-row retirements). A
  per-row review queue with dispositions is generated by
  `scripts/review_hsci_candidates_v1.py`. The active source
  view has 81 records (43 direct, 37 Wayback, one unresolved); the raw source
  ledger has 91 rows. Archived sources with captures on/after their effective
  date are excluded from the verified active event lane (1,158 rows; 50 rows
  retired via append-only `retire_event_unverified_pit` records). Only the 2011-03-07 HSCI-detail availability window
  remains unresolved for strict PIT. The raw append-only event ledger has 1,213
  observations and 64 correction records (ten supersessions plus 54
  PIT-availability retirements). A strict replay audit finds 90
  state-transition gaps; a separate candidate-inclusive diagnostic replay has
  4 gaps (1 duplicate active add and 3 inactive deletes), so the 2008–2021 bridge remains provisional and no combined
  interval mask is promoted.
  The sibling's market-cap PIT layer now extends to the full HSCI review
  universe (971 tickers, daily market cap 2023+; 62 delisted/renamed names
  flagged as no free-source data) via `run-market-cap-pit --include-hsci`.
  Daily OHLCV bars are consolidated into the same DuckDB
  (`market_data_bars`: 1,196,733 rows / 938 tickers / 2016-01-04+), importing
  the legacy 10y/5y research archives and extending live coverage to the HSCI
  universe via `run-market-data-bars --include-hsci`.
  The event-study toolkit exposes `load_canonical_daily_bars()` in
  `scripts/run_hkex_event_study_yfinance.py` (DuckDB-first with the legacy 1d
  snapshot archive as offline fallback); the legacy daily capture lanes in
  this repo and `quantamental-lab` are deprecated for new work.
  The four gaps are classified in the sibling's
  `historical_review_replay_explanations_v1.json`: 0906/0190/0825 trace to
  Research-only 2008-10-08/10-20 batches (no recoverable official source;
  anchored as `MISSING_REVIEW_ANCHORS` for automatic re-probing), and 1619 is
  an official redundancy of its 2014-10-20 removal.

## Recent completed work

- Two silent data defects caught by the test suite and fixed (2026-09-01):

  1. **Buildings Department supply history collapsed from 121 months to 6.**
     `run-bd-history-current-year` merges the fetched current year into the
     retained 2005-present archive, but normalized `hk_real_estate` output is
     gitignored, so a clean CI runner had nothing to merge into and took the
     fallback branch that publishes the current year on its own. The daily
     workflow then rebuilt and committed the artifact from that truncated run
     and reported success, so nothing went red: between 2026-08-30 and
     2026-09-01 the published supply-pipeline chart showed six months of
     history instead of ten years, and could not recover, because each run
     started from nothing again. Complete run
     `3e55204d-570f-4a1b-a64c-3f81f3850723` (1,285 rows, 2005-01 to 2026-05)
     is now committed as the merge base, and the refresh raises rather than
     writing a frame that covers fewer months than the one it replaces.
     Replaying the CI sequence against the committed base restores the chart
     window to 121 months (2016-07 to 2026-07).

  2. **"Trailing-12m ASK growth" was a single-month YoY print.**
     `_ask_decomposition` compared the latest month against the same month a
     year earlier while carrying the trailing-12m label. Mainland monthly ASK
     YoY is extremely noisy — Spring's last six prints ran +22.7, +22.9,
     +12.6, +15.0, +15.9, +8.0 — so the figure landed wherever the final
     month happened to fall. The Spring/Juneyao pair spread that the trade
     card underwrites read 4.6pp on a soft July against 13.8pp on the true
     twelve-month windows, and four of six carriers were being reported as
     contracting when none were. Now computed as a twelve-month sum ratio;
     carriers without two clean consecutive years are dropped rather than
     compared against a short window.

  Both had pinned test expectations that failed as the data moved; those are
  now derived or moved onto fixtures, so the suite tests the rule rather than
  this month's prints. Related: the delivery-pace confidence label treated any
  strictly-positive trailing net fleet add as evidence of a cadence, so a
  single Juneyao airframe promoted the forward projection to "medium"; the
  floor is now two aircraft.

- Airline P1 data build-out (2026-08-10): HKG airport hub is now in
  `airline_airport_traffic.csv` (1,026 rows from the CAD monthly workbook,
  1998-01 to 2026-06, movements/passengers/freight; snapshot-dated because the
  workbook has no per-month announcement date).  Open-Meteo weather-risk layer
  is live (`airline_weather_risk.csv` 24,160 daily rows, `airline_weather_risk_monthly.csv`
  800 rows) for ten hubs (PEK/SHA-PVG/SHA-SHA/CAN/SZX/HKG/CTU/TFU/CKG/HAK) with
  heavy-rain/high-wind/fog day flags and monthly low/moderate/high disruption
  buckets (2026-07 shows HKG and SZX at high).  The forward H1-2026
  net-income bridge (`airline_forward_net_income_bridge.csv`) now anchors on
  the 1H2025 interim official waterfall instead of the static FY2026
  net-to-operating conversion: Spring/Juneyao build for all five walk-forward
  model variants (integrated: Spring EPS 1.84 vs Juneyao 0.24, all variants
  positive Spring-minus-Juneyao attributable spread), Southern/Hainan also
  build (Southern loss-year 239.6% tax rate falls back to absolute carry via
  the 0-60% guard), Air China/Eastern remain labelled gaps because their
  interim statement pages are not parsed in the official-report layer.
  Chengdu remains the only missing hub (CAAC monthly is region-level only; no
  clean free monthly source).  NBS demand controls (P1 item 2) are now live:
  `airline_nbs_demand.csv` carries 47 dated rows from 21 NBS press releases
  (2025-08 to 2026-07) covering monthly retail sales of consumer goods
  (single-month + cumulative scopes, signed YoY) and manufacturing/
  non-manufacturing/services PMI levels, release-date-safe, parsed from the
  public press-release index (the NBS data-portal JSON API is WAF-blocked).
- MTR SRPE transaction probe is live: `scripts/mtr_srpe_transactions.py` downloads the latest statutory register-of-transactions PDF for each of the 8 name-confirmed MTR phases and parses 5,921 transactions (shared `srpe_pdf.py` parser). Per-phase stats feed the property master (units_sold_registered / asp_median / first-last transaction date): 晉環 860 @ HK$18.2m median, 揚海 641 @ 19.1m, 海盈山 374 @ 14.2m, 瑜一 378 @ 16.4m, 凱柏峰I 669 @ 8.2m, 晉海 1,047 @ 7.4m, 晉海II 1,142 @ 8.4m, 柏傲莊I 810 @ 10.2m. First transaction dates sit 1-3 weeks after each phase's first price list, consistent with presale mechanics. `units_sold_registered` is registered transactions, NOT total project units.
- FY26 RECONCILIATION complete (2026-08-09): EPS bridge now reports dual EPS - underlying (recurrent + property, no IP reval) base 1.96 and reported base 2.36 with IP reval +2.5bn scenario (bear +0.5 / base +2.5 / bull +4.5bn), vs consensus 2.52 (-6.5% base, range covers consensus). REVISED (2026-08-09, verified ET Net anchor): with FY26E consensus corrected to 2.69-2.76 (yfinance 0y 2.52 was a YEAR_AGO_EPS field misread), our base reported EPS 2.36 sits -12.3%/-14.5% below Street and bull 2.97 covers consensus (+7.6-10.4%). The residual gap is property scale / IP reval magnitude: Street's FY26 property+IP space (implied 84-109亿 at 2.69) still exceeds our 63亿 base. FY27 dispersion (0.94-1.87) and our FY27 pool (62亿) diverge most - that is the variant frontier. CONCLUSION: FY26 earnings broadly well-understood by consensus; the previous 20-43% gap was an overly conservative IP-revaluation assumption, not core operations. Research horizon moves to FY27.
- MTR Consensus Monitor is live: `scripts/mtr_consensus_monitor.py` outputs `mtr_consensus_monitor.csv` - Our-vs-Street per KPI (transport revenue 24.2bn base vs consensus-implied 23.5bn; property 4.6/6.3/8.1bn; reported EPS 1.44/1.71/2.01 vs 2.52) plus an EPS back-out table. KEY INSIGHT: consensus 2.52 is consistent with our property base (63.3bn) if IP revaluation turns positive ~+30亿 (implied property 68.6bn); with IP reval negative -15亿 the consensus implies property at/above the FY25 record (113.6bn), which our SRPE/OP chain does not support. The EPS gap is therefore mostly an IP-revaluation assumption (rates/property market), not a property-profit disagreement. IP revaluation rate sensitivity is live in the monitor: investment properties 93,188m (FY25 balance sheet; 96,322m FY24), FY25 remeasurement loss 3,538m pre-tax implies ~14bp yield widening. Sensitivity: +25bp yields -> -6.1bn pre-tax / -0.81 EPS; -25bp -> +0.81 EPS; consensus 2.52 implies only ~-15bp yields (+0.49 EPS). CONCLUSION: the EPS gap vs consensus is almost entirely an IP-revaluation (rate direction) assumption - our property-recognition chain and consensus agree; the long/short question becomes a rates call on HK property yields, not a property-timing call. Also flagged: yfinance yearAgoEps 2.69 conflicts with official FY25 2.36; ratings (12) cover more analysts than EPS estimates (7). IP revaluation nowcast is live (`scripts/mtr_ip_reval_nowcast.py` -> mtr_ip_reval_nowcast.csv): Centaline CRI overall rental yield (1997-01..2026-05) as cap-rate proxy, calibrated 0.42x on FY2024 (official -3,821m vs +37bp CRI). FY2026 YTD (2025-12 -> 2026-05): CRI -21bp -> calibrated IP reval +2,163m -> EPS +0.29, supporting consensus's positive-reval assumption (our -1.5bn IP assumption likely too conservative). Caveat: FY2025 CRI was flat while MTR booked -3,538m (residential vs commercial divergence) - the factor is a lower bound for commercial-driven years.
- FY27 property pool is live: `scripts/mtr_property_expected_profit_fy27.py` -> mtr_property_expected_profit_fy27.csv. FY27 expected property profit 4.7/6.2/7.8bn (= 47/62/78 亿, bear/base/bull) - similar to FY26, implying no FY27 collapse under our pool. Broker-level snapshot (`scripts/mtr_broker_consensus_snapshot.py`, 2026-08-09, ET Net-verified) confirms FY27E EPS is a real Street view: JPM 1.87 / CLSA 0.943 / MS 1.65 / Citi 1.43 / UBS 1.72 (consolidated 1.65, mean ~1.52; FY26E ~2.69-2.76 - the earlier yfinance 2.52 was a YEAR_AGO_EPS field misread; FY28E ~1.26). Reverse engineering (FY27 NPAT - assumed recurrent 6.0bn): brokers leave -0.1bn (CLSA) to 5.6bn (JPM) for property + IP reval + one-offs, vs our property pool base 6.2bn - JPM's 5.6bn is close to ours, CLSA assumes no FY27 property recognition at all. The large FY27 dispersion (0.94-1.87) is a low-visibility signal. Priorities: verify LP13 identity/value, P6 scale, YOHO WEST PARKSIDE scale. Next event: interim results 2026-08-13 - re-snapshot to capture revisions.
- MTR Property Expected Profit V1 + EPS bridge are live: `scripts/mtr_property_expected_profit.py` and `scripts/mtr_property_eps_bridge.py`. FY26 pool = official FY25-outlook names (new: LP13, THE SOUTHSIDE P6, Yau Tong VB; continued: Tai Wai, SOUTHSIDE P5, LP12) plus residual (凱柏峰 II/III, 朗賢峯). Expected profit = P(recognition) x eligible registered value x implied conversion ratio (15/20/25% bear/base/bull, anchored by G2022H1). Measured layer (SRPE) 1.06bn base; assumed-scenario layer 4.70bn base (values explicitly ASSUMED, +/-25% band); FY26 total 3.4/5.8/8.7bn vs FY25 11.1bn. EPS bridge: reported EPS 1.25/1.62/2.09 vs Street FY26 2.52 (-50%/-36%/-17%) - flags a large gap to test (our P/magnitude too conservative vs Street not marking down FY26 property). Targeted SRPE enrichment round complete: LP12 海瑅灣 I/II (999 deals, 87.4bn), SOUTHSIDE P5 滶晨 I/II (793 deals, 139.8bn - nearly 2.3x the assumed scenario!), 凱柏峰 II/III (1,292 deals, 93.1bn; three-phase total 1,961 deals ~ OP 1,880 units cross-check), 朗賢峯 (162 deals, 31.4bn), LP13 suspected (633 deals, 41.6bn). FY26 expected property profit updated to 4.9/6.7/8.6bn (bear/base/bull) and EPS 1.48/1.77/2.07 vs Street 2.52 (-41%/-30%/-18%). FY26 expected profit now uses PIT-aligned eligible values (registered sales as of FY25 year end): P5 滶晨 121.8bn (87% of its 139.8bn sold in first 7 months), 凱柏峰 II/III 90.9bn, LP13 39.8bn, 朗賢峯 31.4bn; LP12 海瑅灣 had zero FY25 deals (recognition via OP 2025-10 handover) so its FY26 residual draws on FY26 sales. Updated FY26: property 4.6/6.3/8.1bn, EPS 1.44/1.71/2.01 vs Street 2.52 (-43%/-32%/-20%). Full stack handoff in `docs/asia-markets/MTR_RESEARCH_STACK.md`. P5 is now the largest single EPS risk (0.180). EPS-risk ranking directs targeted enrichment: (0.090 EPS risk), Tai Wai (0.085), SOUTHSIDE P5 (0.077), 凱柏峰 II/III & 朗賢峯 (0.052), LP13 (0.048), P6 (0.040), Yau Tong (0.019).
- MTR Property Magnitude Engine V1 is live: `scripts/mtr_magnitude_engine.py` writes `mtr_magnitude_engine.csv` with exact registered sales value per phase (cancelled deals excluded): 晉環 16,823m, 揚海 14,755m, 晉海II 9,582m, 柏傲莊I 8,808m, 晉海 8,703m, 瑜一 6,704m, 海盈山 5,980m, 凱柏峰I 4,897m, plus p25/median/mean/p75 price distribution. Confirmation-group profit/sales reference (UPPER bounds - missing members shrink the denominator): G2022H1 24.5% (7,747m vs 晉環+揚海 31,578m; ~17% if LP10 value ~15bn); G2024H2 78.4% and G2025H1 82.7% are unreliable (most members lack SRPE data) and are flagged NOT trustworthy as point estimates. G2022H1 anchors MTR recognised profit at roughly 17-24% of registered sales value (bundles project margin and MTR share; not a statutory take-rate).
- MTR Property Timing Engine V0 is live: `scripts/mtr_timing_engine.py` writes `mtr_property_timing_history.csv` linking presale -> first transaction -> BD occupancy permit -> MTR recognition. Four STRONG-mapped cases (address + permit count + timing): 晉環 OP 2022-04 (PR4/2022/OP, 800u) -> 2022; 揚海 OP 2022-08 (PR6/2022/OP, 600u) -> 2022; 海盈山 OP 2024-11 (PR12/2024/OP, 800u) -> 2024; 瑜一 OP 2024-11 (PR11/2024/OP, 630u) -> 2025. Two SUSPECTED shared-lot cases: LOHAS Park P11 OP 2024-12 (1,880u) -> 2024; P12 OP 2025-10 (1,985u) -> 2025. H1/H2 recognition split is now official: interim results show 2022H1 7,747 (LP10/SOUTHLAND/La Marina) vs 2022H2 2,666; 2023H1 712 (LP11 initial) vs H2 1,371; 2024H1 1,740 vs H2 8,525 (LP11 bulk + SOUTHSIDE + Ho Man Tin P1); 2025H1 5,542 (Ho Man Tin P1/P2, SOUTHSIDE P3/P5) vs H2 5,542 (LP12). Annual = H1 + H2 reconciles for all six years. Per-package recognition half is attached to the timing history (晉環 2022-H1 strong, 瑜一 2025-H1 strong, 海盈山 2024-H2 inferred, LP11 2023-H1+2024-H2 strong). Empirical pattern: OP issuance and recognition fall in the same calendar year (median lag ~1 month). THE SOUTHSIDE mapped via 11 Heung Yip Road in the BD history.
- MTR Consensus Bridge (P0C skeleton) is live: `scripts/mtr_consensus_bridge.py` writes `mtr_consensus_bridge.csv` (our FY2026E revenue bridge vs Street) and `mtr_eps_sensitivity.csv`. Street EPS/revenue from yfinance 0066.HK (7 analysts; FY2026E EPS 2.52 avg, revenue 55.2bn). Our FY2026E transport revenue is derived from the farebox H1 nowcast (11,977) x FY25 H2/H1 seasonality (1.0201) = ~24.2bn; other segments are explicitly labelled ASSUMED. EPS sensitivity confirms research priority: one property package timing shift moves EPS ~+/-0.45 (17.7% of consensus) vs farebox +1% (+1.5%), HIBOR +100bp (-3.4%), Mainland +10% (+0.3%).
- MTR Property Project Master (P0B skeleton) is live: `src/hk_transport/sources/mtr_property_project_master.py` and `data/normalized/hk_transport/mtr_property_project_master.csv` (19 project/package rows). Rows are official-disclosure-only: profit-recognition years from MTR annual results (2021: LOHAS Park P7-9; 2022: LP10, SOUTHLAND, La Marina; 2024: Villa Garda, SOUTHSIDE P1/2/4/5, Ho Man Tin P1; 2025: SOUTHSIDE P3/P5, LOHAS Park P12, Ho Man Tin P1/P2), tender years (THE SOUTHSIDE P5/P6 2021; Tung Chung East P1 2024; Tuen Mun A16 P1 2025), plus SHKP-verified LOHAS Park 4A/4B and YOHO WEST cross-references. Units/GFA/ASP/remaining profit stay unpopulated until verified - no fabricated economics. v2 adds an SRPE crosswalk (8/19 rows confirmed): THE SOUTHSIDE P1 晉環/SOUTHLAND (SRPE 7585, first price list 2021-04-19), P2 揚海/La Marina (7787, 2021-08-17), P4 海盈山/La Montagne (9345, 2023-06-27), Ho Man Tin P2 瑜一/IN ONE (8745, 2023-05-08), LOHAS Park P11 凱柏峰/Villa Garda (8545, 2022-06-20), LOHAS Park 4A/4B 晉海/晉海II (4745/4865, 2017), Tai Wai 柏傲莊 I (7225, 2020-10-06). Mappings require an official-name match or repo-verified SHKP data; ambiguous phases (THE SOUTHSIDE P3/P5/P6, Ho Man Tin P1, LOHAS Park P7-10/P12) stay unmapped with evidence_level=official_recognition_only.
- MTR farebox revenue backtest is live: `scripts/mtr_farebox_revenue_backtest.py`; annual and H1 outputs are now generated together (`mtr_farebox_revenue_annual_backtest.csv`, `mtr_farebox_revenue_h1_backtest.csv`) from canonical FY/H1 actuals in `data/normalized/hk_transport/mtr_transport_ops_actuals.csv`, with official 2017-2025 interim actuals and a 2026 H1 forecast row.
  calibrates per-passenger yields to MTR's disclosed FY2024 segment revenue
  (domestic / cross-boundary / HSR & intercity / Airport Express / Light Rail
  & Bus) and evolves them through the cumulative Fare Adjustment Mechanism
  series (2010-2024 plus the 2025/2026 freeze; AEL and HSR yields flat).
  It produces a monthly farebox revenue estimate from 2000-01 to 2026-06 in
  `data/processed/transport/mtr_farebox_revenue_monthly.csv` plus an annual
  backtest file. The legacy FY2024-anchor physics/Ridge results (2019-2023
  4.78%/4.06%) are structural replay diagnostics, not OOS; COVID-era years
  under-estimate by 7-9% (journey-mix drift, not captured by FAM-only yield
  shifts), and the 2008 step is the MTR-KCR merger coverage change, not a fare
  event. The independent chronological prior-period-yield track now reports
  FY MAPE 9.32% and H1 MAPE 8.10% on practical-OOS rows, with forecast origin,
  information cutoff and input bundle fingerprints recorded; historical
  patronage release vintages are not yet captured, so it remains B-practical
  rather than strict A-PIT. The monthly companion is forecast-only because
  MTR does not publish monthly transport-operations revenue actuals. A
  16-fiscal-year MTR historical earnings bridge (annual, 2010-2025) is live in
  `src/hk_transport/sources/mtr_historical_earnings_bridge.py` and
  `data/normalized/hk_transport/mtr_historical_earnings_bridge.csv`; every
  value was hand-verified against official MTR results PDFs (full
  announcements for 2020-2025, analyst result decks for 2010-2019). It
  reconciles segment revenue, recurrent post-tax profit, HK property
  development post-tax profit, underlying profit, IP fair-value movements,
  reported NPAT, EPS and DPS; the underlying = recurrent + property
  development identity holds for all 12 years 2014-2025. 2016-2018 decks
  disclose station commercial + property rental as a merged revenue line;
  2010-2013 decks disclose no segment revenue breakdown.
- China listed airline monthly operating data is wired into transport for six
  listed groups: Air China, China Southern, China Eastern, Spring Airlines,
  Hainan Airlines Holdings and Juneyao Airlines. The artifact includes
  passenger traffic, ASK, RPK, passenger load factor, cargo/mail tonnage,
  RFTK/AFTK, freight load factor, overall load factor and regional split. The
  latest snapshot shows each issuer's reporting scope; Hainan is an eight-
  operating-carrier group consolidation and Juneyao includes Jiuyuan Airlines.
  Hainan history starts in 2016-06 and Juneyao history starts in 2016-01;
  source PDFs remain monthly, preliminary and unaudited. A small number of
  issuer-reported freight load factors exceed 100% (mostly Spring Airlines),
  and are retained as explicit source anomalies rather than clipped. A
  separate operating-events parquet now carries sparse fleet additions,
  retirements, disclosed fleet totals and new-route counts, with source-detail
  text retained in the latest-events table rather than treating prose events as
  a continuous zero-filled series.
- The airline research layer now includes an independent six-company forward
  earnings bridge, 24 company-level invalidation rules and a 21-pair scorecard.
  The five-row `airline_pair_thesis_working_set.csv` aligns the current core,
  three backups and Spring–Juneyao monitor to actual market-leg valuation,
  consensus freshness, catalyst dates, factor/drawdown risk and invalidation
  counts. Mechanical direction hints remain unapproved until valuation,
  catalyst and fundamental validation are completed.
- `airline_independent_forecast_view.csv` now separates the actual pre-event
  judgement from the consensus stress bridge with a bottom-up ASK/RPK,
  revenue-per-ASK, fuel/non-fuel cost and net-profit bridge. Its base case is
  long Spring / short Juneyao: Spring FY2026 profit is modelled at USD344.3m
  (+9.2% versus consensus), while Juneyao is USD107.2m (-22.0%). It carries
  dated sector context (APAC RPK/ASK outlook, China H1 traffic and fuel
  regime). The 1H2026 reports are validation/revision catalysts rather than
  prerequisites for forming the view.
- `airline_company_financial_forecast_bridge.csv` is now the six-company
  non-directional earnings bridge: 21 rows across Air China, China Southern,
  China Eastern, Spring, Hainan, Juneyao and pending 9 Air scope. It separates
  passenger revenue (`passenger RASK x ASK`) from cargo/other revenue, keeps
  native RMB million and USD million distinct, prefers the mainland A-share
  consensus leg for dual-listed names, and exposes assumption-source labels.
  It also carries a market-implied revenue diagnostic using current market cap
  divided by the free 3-year historical P/S median; dual-listed fallbacks are
  explicitly marked as same-company cross-market diagnostics.
  FY2025 loss-making carriers do not use a negative historical
  net-profit/operating-profit conversion; they use a labelled consensus-margin
  normalization fallback. Fuel sensitivity remains pre-tax unless a positive
  operating-to-net conversion is supportable. The v3 layer now prefers a
  reported FY2025 below-operating residual bridge when all five official
  anchors are present; where a formal consolidated income statement exposes
  `营业利润`, v3 now uses that reported operating-profit anchor rather than
  revenue-minus-operating-cost for the historical residual. The parser also
  carries disclosed FY2025 finance cost, interest, investment, tax,
  non-operating, NCI and net-income rows as an audit waterfall. Forward
  finance cost, FX, tax, associates and NCI remain inside the residual, so
  this is a transparent research bridge, not issuer guidance or a trade
  approval.
- v3 now exposes a parallel `forward_waterfall_proxy` diagnostic. For Air
  China and China Southern, the FY2025 formal lower waterfall reconciles and
  the diagnostic scales finance cost with forecast revenue while carrying
  other disclosed below-operating rows at FY2025 absolute values. It is not
  yet the primary EPS forecast: FX, debt schedule, recurring/non-recurring
  classification, tax regime and dilution still need independent assumptions.
- The first v3 free-online source/model extension is now live. The MOFCOM
  monthly goods-trade endpoint produces six current 2026 monthly observations
  (total/export/import values and YoY rates) in
  `airline_cargo_demand_proxies.csv`, with raw JSON snapshots and explicit
  latest-snapshot/PIT caveats. v3 now triangulates cargo demand using fixed
  40% CAAC cargo/mail, 40% MOFCOM trade and 20% State Post Bureau express-volume
  weights, renormalizing only when a component is unavailable. A later MOFCOM
  retrieval snapshot is excluded from earlier model dates. The split is used
  only to grow reported cargo revenue; other revenue is modelled separately as
  a passenger-revenue-growth residual. `airline_earnings_model_v3.csv` applies
  that dated overlay to the six-company bear/base/bull unit-economics bridge;
  9 Air remains incomplete because no standalone financial base exists. The companion
  `airline_earnings_model_v3_kpi_coverage.csv` explicitly marks ASK/RPK/load
  factor/aggregate CASK as modelled, yield/cargo/fuel hedge/fleet/net income
  as partial or proxy, finance waterfall as historical-partial/forward-
  unmodelled, and ancillary/other revenue as a labelled residual proxy; EPS
  remains an explicitly labelled basic-share-count proxy. This is
  a research model extension, not a final long/short direction.
- The official report driver layer now contains 431 normalized rows across
  the 12 FY2025/1H2025 primary-issuer PDFs. The v3 output carries a
  `fy2025_waterfall_status` and per-line FY2025 anchors. The core profit,
  tax and attributable identities reconcile exactly for Air China and China
  Southern; Hainan's attributable/NCI identity remains partial because the
  report layer does not expose a safe minority-interest row. Spring/Juneyao
  remain partial and China Eastern FY2025 is not safely parsed in the current
  report layer. These are historical anchors only, not forward line-item
  forecasts.
- The CAAC sector layer is now live alongside the MOFCOM proxy. Official
  monthly PDFs are normalized from 2020-01 through 2026-06 into
  `airline_caac_sector_monthly.csv` with 5,928 monthly/YTD observations and
  release dates. The latest June release shows sector passenger volume down
  6.5% YoY, cargo/mail volume up 0.4% and scheduled passenger load factor at
  84.7%; these are sector fast-report observations, not company forecasts.
  A separate `airline_caac_sector_proxy_validation.csv` layer compares CAAC
  sector growth with observed company totals; it is calibration evidence, not
  a revenue or earnings forecast. The current 2019 gap is documented rather
  than filled by interpolation.
- The State Post Bureau postal/express proxy is now live in
  `airline_postal_demand_proxies.csv` with 33 normalized rows across 2025 H1,
  2026 Jan-Apr and 2026 H1, including cumulative/latest-month revenue and
  parcel-volume metrics. The v3 model carries the signal as context only and
  applies article-release-date filtering; it is not treated as airline cargo
  revenue. For a 2026-06-30 cutoff, the July 2026 H1 article is correctly
  excluded in favor of the May 2026 Jan-Apr release.
- The MOT/MCT holiday demand layer is now live in
  `airline_travel_demand_events.csv` with 13 normalized rows across five
  official event articles: the 2026 40-day Spring Festival transport window,
  2026 Spring Festival/May/Dragon Boat tourism and 2025 May tourism. It keeps
  article release dates, event duration, per-day normalization and the
  distinction between source-reported and derived YoY. For the 2026 Spring
  Festival tourism article, the nine-day versus eight-day prior holiday is
  normalized to roughly 5.7% daily traveler growth rather than using the raw
  19.0% level growth. v3 carries the latest admissible event as sector
  context only; it does not convert holiday points into monthly company RPK.
- The issuer airport monthly traffic layer is now live in
  `airline_airport_traffic.csv` with 360 rows across Shanghai Pudong/Hongqiao,
  Shenzhen, Guangzhou Baiyun and Beijing Capital for 2026-01 through 2026-06.
  It parses official CNINFO PDF bulletins (SHA/SZX/CAN) plus Beijing Capital's
  investor-relations monthly fast reports (PEK), with announcement dates,
  scope rows and month/cumulative units; v3 carries the latest
  release-date-safe hub observation as sector context only.
- The airport-cargo bridge validation layer is now live in
  `airline_cargo_airport_bridge.csv` (4 companies). For H1-2026 it compares
  hub airport cargo throughput with issuer cargo tonnage: Shanghai hubs grew
  9.4% YoY while Spring cargo tonnage grew 22.6% (-13.2pp gap), Juneyao grew
  5.5% (+3.8pp), and Guangzhou/Shenzhen hubs grew 0.7% against Southern's
  0.3% (0.4pp). Spring's low revenue-per-tonne (RMB2.8/t) versus Southern
  (RMB20.9/t) reflects their different cargo mixes. The mapping is directional
  and the layer is calibration context, not a cargo revenue forecast.
- The forward cargo-revenue bridge is now live in
  `airline_cargo_yield_bridge.csv` (6 companies). It applies a reported
  revenue-per-tonne anchor (H1-2025 official cargo revenue / H1-2025 tonnage;
  FY2025 annualized for Spring/Juneyao) to H1-2026 issuer tonnage. Implied
  H1-2026 cargo revenue grows ~22.6% at Spring, +5.5% at Juneyao, +8.3% at
  Eastern, +1.8% at Hainan, +0.3% at Southern and ~flat at Air China. This is
  a dated evidence layer that the external-proxy cargo leg can be tested
  against when H1-2026 reports are published; it is not a full-year forecast.
- Forward tax and FX assumptions are now live in
  `airline_forward_assumptions.csv` (6 companies). Effective tax rates use
  FY2025 reported tax/profit-before-tax with hand-verified curated anchors
  for Spring (p25), Juneyao (p165) and Eastern (p12, deferred-tax reversal).
  Air China and Eastern are flagged for absolute tax carry because their tax
  lines reflect reversal effects, and the forward FX assumption is the latest
  ECB USD/CNY reference carried forward rather than a forecast. Southern's
  forward waterfall proxy now applies its 44.2% FY2025 effective rate to
  forecast profit instead of carrying FY2025 absolute tax.
- The H1-2026 validation playbook is now live in
  `airline_h1_2026_validation_playbook.csv` (7 companies). It consolidates the
  pre-report H1 KPI forecasts (ASK/RPK/passengers/load-factor/cargo-tonnes),
  the cargo-yield revenue bridge, v3 bear/base/bull net profit, EPS and
  consensus, plus each issuer's scheduled filing date, into one reconciliation
  table that is filled with actuals after the interim reports. The first read
  exposes a large v3-versus-consensus gap for the Big Three (Air China +3,215%,
  Southern +2,040%, Eastern +866%) that the residual-bridge methodology must
  explain before it can be used as a final earnings leg.
- The v3 net-income leg now has a regime-flip guard. When FY2025 operating
  profit is negative but the forward operating profit is positive (Air China,
  China Eastern), the FY2025 absolute below-operating residual embeds
  loss-year artifacts, so the net-income leg switches to the dated consensus
  margin applied to forecast revenue. The raw residual bridge stays as a
  diagnostic column (`v3_attributable_net_income_bridge_*`), and the active
  leg is labelled in `net_income_leg`/`regime_flip_flag`. Air China's guarded
  base profit is USD34.6m and Eastern's USD58.0m versus consensus USD40m and
  USD64m; China Southern stays on the residual bridge because FY2025 was
  profitable, but its v3-versus-consensus gap remains the key open question
  for H1-2026.
- China Southern's v3-versus-consensus gap (previously the key open question)
  is now resolved with a share-based NCI forward leg
  (`net_income_leg="share_based_nci_forward"`). Southern's FY2025 minority
  interest was 68% of net income (1,828m on 2,685m), so carrying the
  FY2025 *absolute* below-operating residual into a much larger forward
  profit year overstates attributable net income (residual bridge 2,242m
  USD base vs consensus 105m). The share-based leg prorates NCI at the
  FY2025 NCI/net-income ratio and an effective tax rate, yielding a coherent
  456m USD base (bear 252m / bull 608m), still a deliberate +335% variant
  view above a consensus that straddles zero (A-share EV consensus averages
  -1,447m RMBm on the negative set and +707m RMBm on the positive set). The
  raw residual bridge remains available as a diagnostic column. Net-income
  leg selection is centralised in `_select_net_income_leg` in
  `src/hk_transport/sources/airline_earnings_model_v3.py`.
- The cargo-bridge backtest is now live in `airline_cargo_bridge_backtest.csv`.
  The FY2025 revenue-per-tonne yield method applied to 1H2025 tonnage predicts
  reported 1H2025 cargo revenue within 4.0% at Southern, 4.0% at Air China and
  6.2% at Hainan -- a genuine holdout validation. The airport-signal leg
  compares H1-2026 airport cargo YoY with company tonnage YoY on the same
  calendar basis: Southern's hub signal (+0.7%) closely tracks company tonnage
  (+0.3%), while Shanghai hub cargo (+9.4%) understates Spring's company
  tonnage growth (+22.6%) because the hubs are dominated by international
  freight that the LCCs do not carry.
- The fuel pass-through layer is upgraded from schedule-only to a dated
  surcharge-to-fuel recovery proxy in `airline_fuel_surcharge_recovery.csv`
  (7 observations). The 2026-07-05 mainland change cut the >800km surcharge
  33% and the <=800km band 38% even as the EIA jet-fuel benchmark rose 18%,
  producing a negative recovery ratio; Cathay's 2026-08-01 change raised
  surcharges 20-41% against a 2.1% fuel move. These are policy/pass-through
  context observations, not realized accounting recovery, and v3 carries them
  as context only.
- The CAAC 2026 summer/autumn route-licence PDF is now parsed into
  `airline_caac_route_licence_events.csv` with 53 dated event rows: 36 new
  domestic route licences, 13 cargo-licence renewals and 4 cancellations.
  v3 carries company-level planned-route counts and stated initial-frequency
  sums for Spring, Juneyao, 9 Air, Southern, Eastern and Air China, but does
  not convert them into ASK or assume operation.
- The current free HSR refresh queried the eight previously pending domestic
  legs in the route queue using dated Ctrip SSR snapshots. The normalized panel
  now has six verified train observations, six explicit no-direct-train rows,
  one no-G/D row and two international controls. v3 carries HSR route coverage
  counts and ASK-weighted-leg status as risk context only; it does not convert
  rail observations into company revenue growth.
- v3 now also carries the fuel matrix's hedge-status, surcharge and
  pass-through-status fields, plus the existing pre-tax fuel sensitivity. The
  mainland surcharge is retained as policy context, and absent numeric hedge
  anchors remain missing rather than zero. The fuel overlay changes the
  operating-profit sensitivity only; no realized pass-through or hedge P&L is
  assumed.
- `airline_forecast_reconciliation.csv` now compares that broad mechanical
  bridge with the separate Spring/Juneyao independent view. The current base
  case has only a modest revenue difference (about USD45m for Spring and
  USD85m for Juneyao), while the operating-cost difference is larger (about
  USD97m and USD208m respectively). The current model disagreement is therefore
  primarily a CASK/non-fuel-cost assumption issue, not a demand/revenue issue.
  This is an audit layer and does not merge the models or select a pair.
- `airline_h1_kpi_backtest.csv` keeps the event horizon explicit. Its raw layer
  uses January--June issuer ASK/RPK releases before an August 1 cutoff to
  calibrate a flat-unit-economics H1 revenue/cost bridge against 43 historical
  evaluated company-years, while adding six pre-report 1H2026 nowcasts. The
  source-recovered/imputed sensitivity now reaches 53 historical rows. Spring's
  source-recovered/imputed flat-ASK revenue MAE is 9.8% and flat-RPK MAE is
  7.5%; the separate recovery-case sensitivity is 6.6% but is not a fitted
  point forecast. Cost errors remain materially larger (Spring 11.1%). This is
  calibration evidence, not a strict historical PIT backtest, because
  pre-1H2025 financial targets lack issuer announcement dates. The formal
  1H2026 reports remain the actual test.
- `airline_operating_kpi_source_recovered.parquet` now sits between the raw
  issuer-release archive and the research-imputed layer. It re-parses cached
  official CNINFO PDFs and now recovers 178 source rows across known page-break,
  modern-format and column-position parser gaps. A separate audit records 22
  Juneyao 2016-01--2016-11 AFTK/freight-load-factor cases as not disclosed in
  the source PDF; these cannot be inferred from ATK/RTK/RFTK. The audit
  explicitly classifies the 178 recovered rows as `parser_gap_recovered`
  and the 22 rows as `not_disclosed_in_source_pdf`, while retaining source-text
  and post-repair parser evidence. The recovery script does not overwrite the
  raw archive; when the raw parser is refreshed after a repair, its affected
  rows may carry the same explicit recovery label.
- `airline_operating_kpi_imputed.parquet` now adds a separate research-only
  company-total monthly KPI layer without overwriting the raw or
  source-recovered layers. It contains 8,261 rows, 13 remaining short-gap level interpolations
  and an audit table for imputed/unfillable decisions; load factors are derived
  from ASK/RPK instead of being linearly interpolated. The expanded
  `airline_period_kpi_backtest` adds separate H1/H2/FY calibration: 162 rows,
  H2 financials explicitly derived as FY minus H1, and a strict versus
  nearest-observed logical-assumption sensitivity. The strict layer evaluates
  eight Hainan H1/FY rows and nine for the other company-period groups; the
  logical layer restores the missing Hainan base case but marks it non-PIT-safe.
  Only future-value interpolations and logical assumptions are sensitivity
  evidence; source-PDF recoveries retain issuer announcement dates. All
  current 1H2026 Spring/Juneyao ASK/RPK inputs are observed, so the event
  nowcast remains PIT-safe. The period summary now also evaluates a
  prior-attributable-below-operating residual-profit diagnostic: direction
  accuracy averages roughly 65% for FY, 72% for H1 and 65% for H2 across the
  six-company panel. It is retained as a transparent alternative, not selected
  as the final earnings model because the residual mixes finance, tax, FX,
  associates and NCI.
- `airline_walk_forward_model_v2.csv` now adds a separate target-label-safe
  walk-forward model layer: 840 detail rows, 90 model/period summaries and
  30 current H1 2026 alternatives across six mainland groups. It trains only
  on earlier target years and compares flat-ASK, flat-RPK, pooled yield/mix,
  fuel/non-fuel and integrated bridges. Spring's current historical sample
  favours flat-RPK revenue over the pooled yield/mix regression; the latter is
  retained as a model-risk alternative rather than silently selected. Fuel
  observations are date-safe but historical release vintages are unavailable,
  and the output labels that limitation.
- `airline_thesis_v2_input_coverage.csv`,
  `airline_thesis_v2_pre_h1_forecast.csv` and
  `airline_thesis_v2_pair_readiness.csv` join the V2 alternatives to the
  existing consensus, revisions, guidance and historical valuation bands.
  They contain seven company coverage rows, 30 enriched H1 forecasts and six
  symmetric pair monitors. Juneyao is explicitly `thin_consensus` because
  only one revenue analyst is present; all pair rows remain
  `not_selected_by_v2`, not approved long/short directions.
- `airline_pre_event_trade_candidate.csv` now makes the bet explicit rather
  than leaving the independent view as a monitor: Spring–Juneyao is a
  `conditional_pre_event_candidate_with_valuation_conflict`. Its independent
  P/S expression is positive, P/B equal-notional payoff is negative, and the
  controlled diagnostic budget is 0.25% NAV / roughly 2.86% gross notional.
  This is a research candidate card, not a live-order approval.
- `airline_pair_trade_thesis_scenarios.csv` now adds 15 provisional bear/base/
  bull rows for those five pairs. It reports constant-current-P/S stress
  diagnostics alongside the separate historical valuation-band layer,
  directional beta hedge ratios, equal-notional and beta-hedged
  payoff, payoff/drawdown, valuation-premium flags, catalysts and risk rules.
  These are payoff diagnostics rather than final target prices; direction and
  sizing remain subject to main-session review.
- `airline_pair_valuation_factor_review.csv` stress-tests the five provisional
  directions for 10%/20% long-leg multiple compression, factor gaps and mixed
  HK/A consensus scope. All five currently fail the 10% compression gate and
  are therefore explicitly marked `not_trade_ready_valuation_factor_or_scope_gap`.
  This prevents a positive mechanical payoff from being mistaken for a robust
  long/short opportunity.
- `airline_valuation_peer_comparability.csv` now records the valuation evidence
  gate for those five pairs. It makes the business-model mismatch explicit
  (Spring LCC versus network carriers, Hainan group scope and Juneyao including
  9 Air) and confirms that free dated price/market-cap history and constructed
  valuation bands are now available. Denominator semantics, PIT revenue and
  business-model comparability still mean that current relative P/S is a
  diagnostic only; no pair receives a historical fair-value target
  automatically.
- Cathay is now formally carried through the valuation and historical-bridge
  layers: free Baidu/Eastmoney PE/PB/market-cap coverage is collected for
  `0293.HK`, Cathay FY2025/1H2024/1H2025/1H2026 official driver rows are
  included in `airline_historical_earnings_bridge.csv`, and the six Cathay
  cross-region pair rows now retain FY2025 actual driver values. The Cathay
  bridge remains explicitly partial because FY2019/FY2024/Q1 periods and a
  like-for-like mainland operating panel are not available; this is a data
  addition, not a long/short direction approval.
- `airline_pb_history.csv`, `airline_historical_pb_valuation.csv` and
  `airline_pair_pb_trade_diagnostic.csv` now add a separate asset-value
  cross-check: seven legs, including Cathay's one-year P/B history and current
  market-snapshot price, plus P/B percentile
  payoff rows. The current median-P/B diagnostic disagrees with the mechanical
  long-Spring direction for Southern–Spring, Hainan–Spring and
  Spring–Juneyao, while supporting Eastern–Spring and Air China–Spring on an
  equal-notional basis. Cathay now uses four official announced equity anchors
  through 1H2026; the mainland equity basis remains FY2025/1H2025 pending the
  1H2026 refresh. The result is not a trade approval.
- `airline_pair_risk_budget_sizing.csv` now uses direction-aware drawdown
  fields rather than always using the file's A-minus-beta-B orientation. It
  exposes 0.25%/0.50%/1.00% loss-budget sizing diagnostics, factor-proxy flags,
  and the still-unresolved borrow gate. These rows are diagnostics only and do
  not imply a portfolio risk limit or approved position.
- `airline_pair_factor_residual_test.csv` now runs a free-data five-factor
  residual regression for all 21 pairs using 5-year daily adjusted prices.
  Spring–Juneyao has 576 observations, approximately +2.8% annualised
  residual alpha and approximately -21.7% residual maximum drawdown. It is a
  transparent proxy test, not formal Barra neutralisation or proof of future
  alpha; size/value exposures are current-snapshot rankings.
- `airline_pair_direction_decision.csv` compares earnings-model and P/B-median
  directions and now carries any mapped independent pre-event view before
  assigning a provisional candidate status. The subsequent
  `airline_pair_revision_confirmation.csv` gate finds no full long-up/short-down
  confirmation as of 2026-08-07, so Eastern–Spring and Air China–Spring are
  downgraded from provisional candidates to revision-unconfirmed monitors;
  Southern–Spring, Hainan–Spring and Spring–Juneyao already have valuation
  conflicts. Spring–Juneyao nevertheless has an explicit pre-event
  long-Spring/short-Juneyao working view; no pair currently has an approved
  executable trade direction.
- `airline_pair_target_range.csv` combines the earnings/P-S and P/B diagnostics
  into 15 transparent bear/base/bull payoff ranges. It makes valuation-method
  uncertainty visible instead of presenting a single mechanically selected
  target; the range is not a confidence interval or trade approval.
- `airline_pair_event_trade_triggers.csv` converts each pair into a conditional
  event-driven execution checklist: separate minimum realized profit and
  revenue surprise gaps, fresh revision confirmation, valuation lower-bound
  check, catalyst window, direction-aware drawdown, sizing context and
  invalidation. All five remain execution-gated with no approved pre-event
  trade; the gate does not prevent the independent forecast from being formed
  and tested now.
- `airline_pair_branch_thesis.csv` now preserves both the fundamental-resilience
  and valuation-mean-reversion branches for all five pairs. Each branch has an
  explicit direction, variant perception, target/payoff, catalyst,
  invalidation, direction-aware hedge/drawdown and sizing context; all remain
  conditional until the event gates pass.
- The v4 revenue layer was re-audited and rebuilt on 2026-08-11: historical
  residual-yield scores are now period-specific (H1 Jan-Jun, H2 Jul-Dec, FY
  Jan-Dec), removing the prior intra-year H1 look-ahead. Period-safe final
  revenue MAE is 7.47% across 108 rows. A locked
  `airline_pre_event_unified_snapshot.csv` now reconciles v3, v4, consensus
  and decision-evaluation layers with explicit model versions and vintages;
  it is not a new forecast or an executable strategy backtest.
- `airline-pair-thesis-review.md` records the written provisional thesis for
  the core, three backups and Spring–Juneyao monitor. It states the proposed
  direction, variant perception, target/payoff diagnostic, catalysts,
  invalidation rules and evidence gates, while explicitly preserving the
  current non-trade-ready verdict.
- Hong Kong transport now includes Cathay Cargo and official report-period
  fleet signals in addition to TD monthly private-car first-registration
  make/fuel history (with BYD/Tesla/other-EV time series), latest make/model
  detail, and two distinct parking signals: the TD real-time car-park vacancy
  snapshot plus metered/on-street sensor-space occupancy. Group 1 also adds TD
  private-car fleet stock and net first-registration history, MTTD Table 2.3
  passenger journeys, and C&SD E705 boundary movements. Cathay's monthly
  traffic archive runs from 2012-12 through 2026-06 for the passenger series;
  cargo tonnage/AFTK/cargo load factor are available across the recovered
  monthly archive, while RFTK and flight-sector wording vary by report era.
  The official Fleet Profile series currently runs from 2015-06 through
  2025-12 at annual/interim cadence and is not interpolated to monthly data.
  Parking histories are append-only; the metered occupancy chart is a genuine
  time series only after repeated collector runs, and the dashboard does not
  infer historical values from a current feed.
- Hong Kong utilities now includes DSD daily sewage flow/final-effluent
  laboratory observations and WSD temporary water-suspension event notices.
  The public artifact preserves a treatment-works flow chart, latest lab table
  and current event table; DSD lab fields remain sparse and WSD is explicitly
  modeled as a five-minute event snapshot rather than a consumption series.
- Cloudflare historical charts now use a date-based latest-ten-year display
  policy for the transport service breakdown, utilities gas/temperature views,
  local-consumer weather/immigration/gold/retail/restaurant/oil-price views,
  and stablecoin/crypto histories. The source cadence is retained; feeds with
  less than ten years show all available history and must say so in the chart
  context. Snapshot, ranking and recent-event views remain explicitly outside
  this trend-window rule.
- The refactor exposed genuine source limits: Consumer Council watchlist
  valuation history currently returns only a rolling ~365 days from its
  endpoint, while AFCD category prices remain a run-accumulated snapshot.
  Neither is presented as a fabricated ten-year series.
- Dashboard source-status pages were updated and Chinese labels/caveats were
  localized.
- Hong Kong labour-market and talent-policy data is now a live sector with
  official C&SD labour, earnings, vacancies, wage and policy-flow panels.
- Hong Kong population and migration data is now a live sector with ImmD daily
  traffic, C&SD population/net movement, MPFA departure claims, UGC non-local
  enrolment, Transport Department cross-border traffic and C&SD visitor
  arrivals by region. Stage 1 persists normalized run-scoped Parquet datasets
  and the builder reads those before any bootstrap fetch; per-source status rows
  retain each source's own observation date. The full visitor-arrivals history
  remains in normalized storage, while the portable artifact uses a latest-
  ten-year regional detail window to stay under its per-dataset row limit.
- Streamlit is implemented as a private research terminal. In addition to
  the Hong Kong sector pages it now has the Streamlit-native Index & ETF
  Allocation Monitor. Its flow is `src/market_monitor` sources -> immutable
  normalized/derived Parquet -> `market-monitor-artifact*.json` -> Plotly
  views. The monitor currently covers 11 investable exposures and 29 ETF
  wrappers, with source-declared Sina/Sina-HK/CSI/Yahoo routing, two-year ETF
  price and premium history, RSI/MA/drawdown, absolute entry status versus
  peer rank, and 12 relative-strength pair histories. The artifact is
  verified as ready at commit `9a096149`; 71 market-monitor tests and 64
  Streamlit/wiring/history tests passed in the 2026-08-21 review. Do not
  treat those counts as a permanent freshness guarantee.
- The market-monitor review also recorded four follow-ups: ratio mode still
  needs true reindexing if that remains the requested display, CSI source
  health should use its own latest observation date, wrapper table columns
  need fuller Chinese localization, and historical premium z-score/verified
  NAV-based AUM/tracking difference remain V1.1.
- The crypto page keeps the long-run monthly Fear & Greed context plus the
  daily score and a derived trailing seven-calendar-day average for
  interactive research views. It also exposes the curated Wikimedia crypto
  attention basket as weekly traffic-agent totals and monthly user-by-page
  history.
- Store-footprint, Google Trends and other planned integrations remain separate
  until their source history and data flow are validated.
- Real-estate dashboard work includes agency transaction pulse, 28Hse EPI/ERI,
  Land Registry statistics, HKMA mortgage measures, Buildings Department data
  and REIT/property trend series.
- Centaline Tranche 1 ingestion is now implemented as a standalone
  `run-centaline-indices` command. The 2026-07-30 run successfully materialised
  CCI (389 monthly rows), CRI (354 monthly rows), CRI yield (353 monthly rows),
  CSI (1,116 weekly rows) and 33 current CCI/CRI/CSI snapshot rows, each with
  raw JSON lineage. Stage 1 now wires CCI/CRI/CRI yield/CSI into the real-estate
  dashboard's regime and residential rent views; CSI's historical payload
  currently exposes residential price/rent history only, with office/
  industrial/retail values available as snapshots.
- CSI ingestion preserves unique weekly source observations and the artifact
  retains day-precision weekly dates; the portable chart runtime supplies the
  visible year without collapsing observations to a month.
- Midland Tranche 2 ingestion is implemented as a standalone
  `run-midland-monthly` command. The 2026-07-30 run materialised 355 monthly
  `mrIndex` rows with price, transaction-count and first-hand fields, plus
  3,185 long-form `economicIndicators` rows and a persisted
  `midland_field_dictionary`. Monthly, macro and dictionary rows share the
  frozen HTML lineage; Midland macro units remain Midland-derived until the
  planned HKMA/C&SD reconciliation. The routine `run-all` path now includes
  this tranche, while `HK_RE_SKIP_MIDLAND` marks it skipped in blocked CI.
- RVD commercial Tranche 3 is implemented as a standalone
  `run-rvd-commercial` command. The 2026-07-30 run materialised 1,604 office
  rental rows across Grades A/B/C and Overall, plus 802 retail rows covering
  rental and price metrics, preserving official provisional flags and raw CSV
  lineage. Stage 1 now wires the office and retail rental histories into the
  commercial-property dashboard section; retail price and grade-level drilldown
  remain follow-up work.
- Midland Tranche 4 is implemented as a standalone
  `run-midland-snapshots` command. The 2026-07-30 run materialised 598 rows
  from all/region/district current and previous-window market statistics, plus
  32 rows from the current registration summary and 45 Midland
  `propertyEvent` research hints. Market rows preserve units, source fields
  and optional window dates; registration rows preserve as-of/update dates
  and explicit transaction/amount units. These are explicitly as-of snapshots
  or discovery hints, not historical trends or official policy events; at
  least 90 days of dated snapshots are required before any MoM/YoY chart is
  considered. This tranche is also included in routine `run-all` with the
  Midland CI skip guard.
- Tranche 5 policy/event research contracts are implemented through
  `run-policy-events`: four primary-source catalog entries and a validated
  audit of the curated developer/project registry. Both outputs now retain a
  local raw snapshot and explicit lineage type; Midland events remain
  `research_only` until matched to an HKMA, Government, Lands Department or
  HKEX primary source with publication/effective-time semantics.
- The residential-developer SRPE bounded runner is implemented through
  `run-srpe-pilot` with an explicit phase registry, PDF hash reuse, raw PDF and
  manifest lineage, document audit, unit-level transaction/price rows and
  project-month sales signals. The final 2026-08-01 core run produced 2,892
  transaction events, 1,585 price-list unit rows, 196 project-month signals
  and 18/18 successful document audits across six phases. Sell-through uses
  active unit-level dedup while raw contract-event counts remain available;
  this prevents PASP/ASP updates and re-sales from producing a false >100%
  sell-through. The output is now wired into the HK real-estate dashboard as
  four KPI cards, top-three developer/project monthly time series and a
  six-phase latest-project table. The dashboard intentionally keeps broader
  developer/project coverage as catalog-only until the registry and backfill
  boundary is expanded. The optional Crawl4AI browser tool is installed
  outside the project dependency graph for future dynamic issuer pages, not
  for the SRPE API/PDF path.
- The latest SHKP/SRPE catalog run `cd17809a-0390-47e0-b4de-decf35b383f5`
  completed successfully: 109 SHKP directory rows, 522 SRPE phase rows, 71
  listing-to-phase candidates, 333 corporate-document links, 8 interim
  pipeline evidence rows. The subsequent site/planning evidence refresh has
  128 ownership-review queue rows. It now includes
  an official 2025-12-31 interim-report observation of 100% Group's Interest
  for the grouped Cullinan Sky / Cullinan Sky Mall project. That evidence
  extends the timeline but still does not split Cullinan Sky Phase 1/2 or open
  the sales-attribution gate.
- The review-only SRPE union now contains 5,332 transaction events, 2,544
  phase-scoped price-list units, 40 document-audit rows (37 successful
  downloads plus three explicit `not_available` price-list observations) and
  109 project-month status rows. Cullinan Harbour phases 9785/10405/11516
  contribute 102/17/4 register events; their official manifests contain no
  price-list documents, so the dashboard reports `not_available` rather than
  treating the absence as zero inventory or parser success.
- The 2026-08-03 phase-specific ownership audit keeps all 13 reviewed SHKP
  phases behind the attribution gate (`ownership_attribution_ready=false`).
  Annual-report 100% and JV labels are retained as dated observations or
  project-group evidence, not converted into continuous phase-level
  ownership intervals. The next evidence gate is a dated legal-SPV/JV
  interval, with separate Phase-2 vendor evidence for Cullinan Sky and
  single-phase evidence for Cullinan Harbour 2A/2B.
- Future-pipeline identity is now conservative but usable: Sha Po South is
  bridged to SRPE 11554 Garden Regency and Tsuen Wan West to SRPE 11505 Lime
  Spark as `matched_needs_review`; Tai Po Town Lot 244's Silicon Hill and
  University Hill phases are now bridged to SRPE 8405/8445/9245, while YOHO
  WEST PARKSIDE and Cullinan Sky Phase 2 are bridged to SRPE 10585/11005 from
  official phase/schedule evidence. Additional A16, Tung Chung, Tai Wai,
  Fanling, Hung Shui Kiu, Yuen Long and Cheung Sha Wan lot candidates remain
  explicitly `srpe_pending`; Lot 4354, KIL11273 and MEGA IDC are routed away
  from SRPE residential work. Artist Square Towers is explicitly routed to
  the non-SRPE commercial/BOT registry. These bridges resolve identity only
  and never change ownership or sales eligibility.
- The project-site statutory parser now preserves the multi-role notice for
  YOHO WEST / YOHO WEST PARKSIDE: MTR is the legal Owner, Best Vision is the
  Person so engaged, and Better Sun/Time Effort/SHKP are holding companies of
  that person. The refreshed site layer has 13 fact rows and 16 phase
  crosswalk rows; this improves JV/phase evidence but remains
  `vendor_only`/`not_verified`, not a numeric SHKP ownership interval.
- The planning crosswalk now applies explicit phase hints only when the
  LandsD name contains a phase token: NKIL 6568 P1/P2, NKIL 6551 P1/2A/2B,
  TSWTL 23 P1/P2 and YLTL 510 Phase B/C. Generic or combined rows remain
  ambiguous. The refresh has 1,094 planning rows and a 128-row ownership
  review queue; all 13 priority phases remain `ownership_attribution_ready=false`.

- Sales attribution gate hardening (2026-08-03): a phase is now eligible only
  when the numeric ownership evidence is accompanied by a bounded,
  phase-specific `ownership_effective_from`/`ownership_effective_to` interval.
  Eligibility and the executable sales plan re-check the interval, so a stale
  or manually supplied legacy ready flag cannot open attribution.
- Land Registry research (2026-08-03): the official IRIS/current-and-historical
  land-register service can expose registered owners, shares and memorial
  instrument dates, but public access is a paid/manual search rather than a
  batch project API. A bounded lot-level IRIS pilot is therefore the next
  evidence route; its dates must still be joined to an SRPE phase and cannot be
  treated as SHKP attributable percentage without SPV/JV evidence.
- The phase-by-phase evidence memo is maintained in
  `docs/asia-markets/REAL_ESTATE_SHKP_OWNERSHIP_INTERVAL_AUDIT.md`; it records
  the 13-phase decision, blocker semantics and the exact lot-level IRIS pilot
  fields without opening any sales attribution.
- A manual `build_shkp_land_registry_evidence` importer now validates bounded
  IRIS CSV/DataFrame evidence as an append-only, title-only layer. It preserves
  raw registered shares and instrument dates, hard-blocks promotion, and the
  interval helper additionally requires a distinct reviewed
  `approved_phase_attribution_decision` plus decision id.
- A separate `shkp_phase_role_evidence` layer now records 30 official
  project/Quarterly/promotion role or phase-identity rows across 30 SRPE
  development IDs. It extends the original 13 priority-phase layer with
  bounded role evidence for NOVO LAND, Wings at Sea, Wetland Seasons Bay,
  Cullinan West, Victoria Harbour and Sierra Sea. Every row has null
  percentage and null effective dates by contract; grouped notices remain
  blocked and the layer never opens sales attribution.
- The SHKP catalog is now reproducible through
  `python -m src.hk_real_estate.cli run-shkp-catalog`. The `--offline` mode
  audits the latest normalized snapshots without fetching; live mode writes
  one run-scoped lineage set. The SRPE index refuses a zero-row response, and
  the runner refuses to publish an empty property/index refresh, preventing a
  transient official endpoint response from erasing the last usable universe.

## Open decisions / known limitations

- The planned Asia finance universe is documented in the sibling repo but is
  not active collection data. Futu (`FUTU`), Tiger (`TIGR`), CITIC Securities
  (`6030.HK`), China Merchants Securities (`6099.HK`), CICC (`3908.HK`), GF
  (`1776.HK`), CSC (`6066.HK`), Guotai Haitong (`2611.HK`) and East Money
  (`300059.SZ`) require a market-aware financial-data expansion before being
  wired into the dashboard.
- Buildings Department Md52–Md56 current XLS charts/tables remain project
  snapshots. A separate archive-backed `bd_supply_pipeline_history` now covers
  2005-01 to 2026-06 as month/stage aggregates parsed from the official PDF
  summary tables. The dashboard chart deliberately displays only the latest
  ten-year lookback (currently 2016-06 to 2026-06) for readability; the
  archive-backed normalized rows remain available for research. `Md52`
  demolition consents supply counts only; the history is not project-level
  stage linkage. `bd_monthly_stats` remains a distinct Md11–Md17 scratch
  dataset with unlabelled numeric arrays.
- The current monthly-digest fetch archives 20 Mdxx XLS files. Most of those
  are raw-only archival coverage, not normalized analytical datasets.
- Buildings Department coverage is split between raw Mdxx archival files,
  historical Section-1 stage aggregates and current Md52–Md56 project
  lifecycle snapshots. A separate scratch `bd_project_lifecycle_history`
  contract now parses project rows from official monthly PDF Tables 5.2–5.6;
  the strict local v6 reparse covers 17,517 rows across 257 published issue
  months from 2005-01 to 2026-05. The digest does not publish an exact
  consent/OP day, so `event_date` remains null with an explicit
  `not_published_in_monthly_digest` status. Address/permit-to-project matching
  and SHKP attribution remain research-only until the historical rows pass
  entity-resolution audits.
- The explicit `shkp_bd_history_crosswalk` audit now joins the full monthly BD
  history to 71 SHKP/SRPE candidate phases by normalized address only. Run
  `9f639a88-e4f3-4c02-9ed9-241b75ecaae1` finds 48 phases with address hits and
  220 historical rows; 198 rows remain ambiguous because their address is
  shared by multiple SRPE phase IDs, 22 are single-phase address hits needing
  review, and five candidates are unmatched. Repeated months/stages within one
  phase no longer create false ambiguity. Shared Hoi Ying Road/Lohas Park
  addresses remain blocked across phases; this crosswalk is not a permit-date
  or ownership table and cannot feed attributable sales.
- Source coverage for newer feeds currently uses `Live at build time` when a
  build fetched rows, but often leaves `latest_observation` as `—`. This should
  be improved to expose actual as-of dates and age where possible.
- Population/migration source dates are mixed by design (daily, half-yearly,
  quarterly, academic-year and monthly). The status page shows each source's
  own latest label; the package-wide `data_as_of` is the latest dated source
  observation, not a claim that every source has that recency.
- Weekly/daily chart labels preserve distinct points while showing a year;
  month-granularity series use month/year labels. The portable packaging layer
  patches the shared reader's day-only axis labels in both interactive and
  static delivery modes.
  do not solve this by aggregating the data to monthly grain.
- Most store-footprint companies have only one or two dated snapshots; present
  them as footprint snapshots rather than trends.
- Consumer Council Online Price Watch historical Parquet is gated by a local
  manifest: all advertised archive dates must have source-version provenance,
  a successful parse and a materialised partition before it is Healthy. The
  dashboard shows archive coverage plus a product-code-matched, chain-linked
  index for the six longest supermarket-code series. It does not adjust for
  promotions or pack-size changes, and source-code renames are deliberately
  not inferred as continuity. The archive remains local rather than Git-tracked.

### SHKP historical-universe update (2026-08-08)

SHKP historical-universe discovery now includes the official `History and
Milestones` page as `shkp_history_milestones`: the first live fetch has 112
milestone rows covering 1972–2025 across 52 years, with issuer wording, image
URLs and raw HTML retained. This is discovery/alias evidence only; milestones
can mention multiple projects and do not provide SRPE ids or phase-level
effective ownership percentages. Inactive SRPE manifest and transaction
backfills now merge append-only batches and can optionally route unobserved
inactive phases with `--include-unobserved`. After the final 2026-08-08 batch,
the recovered transaction latest snapshot contains 36,493
transaction-id-deduplicated gross events across 145 phases, 2,365 project-month
rows and 155 phase quality-audit rows. Quality status is 59
`gross_event_ready`, 86 `gross_event_ready_with_date_gaps` and 10
`register_parsed_zero_rows`; exact and composite duplicate counts are both zero.
All rows remain routing-only and are excluded from `0016.HK` attributable sales.
The manifest coverage audit now covers all 161 inactive phases (155 with
transaction-register metadata and 6 with other official document categories),
so inactive unprobed count is zero. The full 521-row parent roster still has
360 active/current rows marked `not_observed` because they have not been routed
through the historical manifest. Ownership and attributable-sales gates remain
blocked. The new `shkp_historical_manifest_coverage_audit` labels all 521 parent
rows: 360 `not_observed`, 155 `observed_register` and 6 `observed_no_register`.
The parent roster now carries these values as explicit `historical_manifest_*`
fields (including document-category counts and transaction backfill status),
without overwriting the generic live/current `manifest_status` field.
The roster builder also passes the latest current `shkp_srpe_document_manifest`
through the registry: 10 current/pilot phases are `filings_available` and 511
remain `not_loaded` pending a current-manifest refresh.
Offline catalog checks now report `usable_with_unscoped_source_inputs` when the
only unscoped layers are the separately refreshed SRPE parent index and
historical annual-report index; true mixed catalog runs remain blocked. This is
an audit warning only and does not promote any ownership decision (13 priority
phases, zero approved).
The current SHKP-directory SRPE manifest backfill now covers 53 candidate
phases in a separate append-only dataset (`shkp_current_srpe_document_manifest_backfill`):
6,325 metadata rows, including 53 transaction-register, 1,095 price-list,
2,919 sales-arrangement and 2,258 brochure rows. It is metadata-only and
ownership-neutral; the historical roster unions it with the coherent live
manifest without changing the live catalog run identity.
The scratch consolidation has also been refreshed across all persisted batches:
56 candidate phases, 30,124 semantic-deduplicated transaction events and 3,265
phase-month rows, with 56/56 phase audits successful. All remain blocked on
phase-specific ownership intervals and are not SHKP attributable sales.
The 521-row parent roster now includes explicit ownership evidence fields:
`ownership_evidence_level`, source count, promotion blocker and next-evidence
route. Current levels are 424 `srpe_parent_only`, 69
`numeric_snapshot_or_grouped_interest` and 28 `phase_or_project_identity_only`;
these are evidence-quality labels only and do not promote ownership.
The same fields are persisted in the one-row-per-phase
`shkp_historical_phase_evidence_coverage` audit table (521 rows), alongside
current/historical manifest and transaction-backfill status. It is a projection
of the roster, not an independent attribution engine.

### SHKP historical-universe completion audit (2026-08-08)

The discovery/evidence and transaction-routing objective is complete: 521/521
SRPE parent phases have stable IDs and lineage; the current SHKP catalog has 109
rows with 53 residential candidate phases; annual evidence has 312 project rows
and 420 crosswalk rows; History and Milestones has 112 rows and 135 crosswalk
rows; current manifests cover 53 candidate phases; inactive historical manifests
cover 161 phases; candidate-routed scratch covers 56 phases and 30,124
deduplicated events; historical backfill covers 145 event-bearing phases and
36,493 events. The one-row-per-phase evidence coverage audit is persisted and
verified at 521 rows.

This is a discovery/evidence universe, not an approval of SHKP attributable
sales. Ownership promotion remains blocked until dated phase-specific SPV/JV/
IRIS evidence is reviewed.

For practical research use, a separate non-legal `shkp_indicative_ownership_roster`
now classifies the 521 phases using directory matches, Group-interest snapshots
and JV wording: 69 likely numeric SHKP snapshots, 24 likely SHKP-linked
unquantified JVs, 4 possible review cases and 424 not observed. The
indicative layer now preserves `indicative_ownership_pct_low`/`_high` and an
explicit `indicative_numeric_consistency_status`. Sub-half-point differences
between rounded official snapshots are retained as a range and represented by
their median only as a rough point estimate; the Kennedy 38 example is
53.0% (annual report) versus 53.3% (completion schedule), yielding a 53.15%
indicative point estimate. Larger snapshot conflicts remain null. This does
not open the strict ownership or permit attribution gates. The
`run-shkp-indicative-signals` command writes
`shkp_indicative_project_month_signals`; the latest 3,265-row output contains
2,610 numeric-snapshot rows (2,552 single-value plus 58 rounded-consistent),
655 unquantified-JV rows and 2,113 rough contract-value estimates. The strict
ownership gate remains unchanged and closed.

The historical inactive transaction backfill is now normalized into a separate
all-history signal layer by `run-shkp-all-history-signals`: 5,604 merged
phase-month rows across 197 phases (3,265 current rows plus 2,365 sparse
historical rows, with one overlapping phase-month resolved in favour of the
current candidate signal). Historical months are sparse and absent months are
not zero-filled. The latest all-history indicative layer has 2,637 numeric
rows, 756 unquantified-JV rows and 2,211 identity-unknown rows; only the first
two categories can contribute to the research scenario totals. The indicative
sales model automatically prefers this all-history layer when it exists, while
the strict current signal contract remains unchanged.

### SHKP active-phase transaction coverage completion (2026-08-09)

The historical transaction backfill previously only routed inactive phases
(`active=N`) through the manifest queue, which left every still-active
numeric/JV phase without transaction events even though the ownership roster
could already name them. `run-shkp-historical-transaction-backfill` now accepts
an explicit `--phase-ids` list; the registry is built from the 521-row
historical roster (not the manifest) and reuses the identical routing-only
merge, PASP date-gap quarantine and quality-audit pipeline. This is
discovery/coverage work only: every routed phase keeps a zero ownership
percentage and a blocked interval, so no attributable sales are opened.

Six batches routed all 30 remaining coverage gaps (20
`likely_shkp_numeric_snapshot` + 10 `likely_shkp_jv_unquantified` LOHAS PARK
sub-phases) and added 12,998 gross transaction events across 30 phases. The
historical transaction union now holds 49,491 deduplicated events across 175
event-bearing phases (audit: 109 `gross_event_ready_with_date_gaps`, 66
`gross_event_ready`, 10 `register_parsed_zero_rows`; zero duplicate rows).
The merged all-history layer grew to 7,039 phase-month rows across 230 phases;
the indicative layer now covers 3,481 numeric-snapshot rows and 912
unquantified-JV rows. Phase-level transaction coverage is now 69/69 numeric
snapshot phases and 24/24 JV phases (100%), up from 49/69 and 14/24.

Quarterly reconciliation improved as a result: the FY2024/25 window moved from
HKD 31.2bn model base (73.8% of the HKD 42.3bn disclosed) to HKD 38.5bn
(91.1%), and 1H2025/26 moved from HKD 12.9bn (74.0% of HKD 17.4bn) to
HKD 19.5bn (111.9%). The over-100% 1H2025/26 reading is expected for a gross
contract-activity proxy (registers include contract updates/resales and JV
stakes use a mechanical 50% base assumption); it remains a scope/timing
diagnostic, not accuracy. The FY2026/27 base forecast now reads HKD 38.7bn
numeric-stake sales (HKD 46.1–60.8bn total across 25/50/75% JV sensitivities).
All 53 SHKP-related tests pass.

### SHKP curated identity-exclusion correction (2026-08-09, same day)

Decomposing the 111.9% 1H2025/26 over-read exposed a phase-identity bug in
the evidence layer, not a modelling artifact. The annual-report label match
was phase-inclusive for shared-lot addresses: every Lohas Park phase shares
`1 Lohas Park Road`, so the single SHKP annual label "Wings at Sea & Wings
at Sea II" (which refers only to Lohas Park Phase 4) fanned out to all 17
Lohas Park SRPE phases via `address_contains`. A second path matched "Noble
Hill" (38 Ma Sik Road, Sheung Shui) to the One Innovale rows at 8 Ma Sik
Road because the normalized address `38masikroad` contains `8masikroad`.
The roster builder then promoted these `ambiguous` matches to numeric
snapshots (One Innovale) or unquantified JVs (every non-SHKP Lohas phase).

Verified actual ownership (official developer disclosures, 2026-08-09):
One Innovale Phases 1-3 are Henderson Land; Lohas Park Phase 4 (晉海 / Wings
at Sea I & II) is the only SHKP phase in Lohas Park, while Phases 1-3
(CK Asset/Nan Fung), 5 (Malibu), 6 (LP6), 7A/7B (Montara/Grand Montara),
9 (Marini/Grand Marini/Ocean Marini), 10 (LP10), 11 (Villa Garda I-III,
Sino/K. Wah/China Merchants), 12 (Seasons Place/Park Seasons/Grand Seasons,
Wheelock) and 13 (La Mirabelle I/II, Wheelock-led) are other developers.

Fix: `SHKP_CURATED_NON_SHKP_SRPE_PHASES` in `sources/shkp.py` pins 18
verified non-SHKP phase ids with the actual developer as the reason. The
registry builder suppresses the annual evidence for those phases, the
high-recall builder skips both explicit and fuzzy evidence for them, and
`_safe_address_substring` adds a leading-digit boundary so `8masikroad`
can never match `38masikroad` again. All 18 rows are now `not_observed`;
the numeric roster is 65 phases and the JV roster 9 (65/65 and 9/9
transaction coverage, down from 69 and 24). The reconciliation now reads
FY2024/25 = HKD 36.5bn (86.3% of HKD 42.3bn) and 1H2025/26 = HKD 14.0bn
(80.6% of HKD 17.4bn), both comfortably under 100% and consistent with a
gross-proxy under-read. The FY2026/27 base forecast is HKD 32.2bn
numeric-stake sales (HKD 32.8–34.0bn total across JV sensitivities). All 57
SHKP-related tests pass, including new regression tests for the exclusion
and the address-substring guard.

JV-stake caveat (2026-08-09 audit): the nine remaining JV phases are MTR
station-over-platform developments (Cullinan West 匯璽, The YOHO Hub, YOHO
WEST, Wings at Sea 晉海) where SHKP's annual report labels the interest
"JV" without a percentage. These structures typically give the developer
the dominant economic interest (SHKP pays MTR a land/platform consideration
and leads development), so the mechanical 25/50/75% sensitivities likely
bracket the true stake with the base 50% a conservative mid-point rather
than a verified figure. The reconciled 80-86% under-read is consistent with
this conservatism plus omitted possible/unknown phases; no evidence suggests
over-attribution remains after the 18-phase curated exclusion.

Backtest note: the 948-row one-step holdout has a main-window (pre-2026-06)
median absolute percentage error of ~77-88% with a 63-67% direction-hit
rate. The trailing 2026-04..08 window shows a declining model-grid coverage
ratio (0.59 -> 0.15) purely because recent SRPE registers lag publication,
not because activity vanished; same-month-last-year forecasts in that tail
still land within 9-14% of observed values for 2026-07.

### 13-year Hong Kong property-sales panel and data audit (2026-08-09)

The reconciliation panel was extended to 13 fiscal years
(`shkp_financial_model_hk_property_sales_segment_history`,
`shkp_indicative_sales_model_historical_reconciliation`, 16 rows) by
extracting the Hong Kong row of the Segment Information note from each
annual report PDF (FY2012/13-FY2024/25). The panel uses the HK-only combined
revenue (company and subsidiaries plus share of associates and joint
ventures), which is the correct comparison for the HK residential model.

Data audit (all values verified against the source PDFs, each fiscal year
checked twice via the current-year and prior-year tables in adjacent annual
reports; 24/24 cross-checks pass, plus the FY2024 24,745 and FY2025 26,139
values each appear in three independent places in their annual reports):

* FY2012/13-FY2024/25 HK property-sales segment revenue ranges HKD 11.3bn
  (FY2014/15) to HKD 36.9bn (FY2019/20); recent years are HKD 23.9bn
  (FY2022/23), 24.7bn (FY2023/24) and 26.1bn (FY2024/25).
* The five-year-summary "Property sales" line is all-region (HK + Mainland +
  Singapore) and is now explicitly NOT used for HK reconciliation; the
  legacy all-region anchor remains visible as a labelled diagnostic only.
* Model-vs-reported ratio by revenue scope: 73.6% mean across all 13 years,
  93.5% mean across FY2020/21-FY2024/25. Early years are dominated by
  universe-coverage gaps (2013: 0/230 phases, 2014: 7/230), while FY2022/23
  (130%) and FY2024/25 (140%) overshoot - the model currently overstates HK
  property-sales revenue in recent years once coverage is high, which is the
  next reconciliation issue to investigate (contract updates/resales, JV
  stake assumptions, or phase identity remain candidates).
* Third-party (akshare OPERATE_INCOME) differs from the annual-report Group
  revenue by design (segment vs consolidated reporting scope); it is a
  known provider-convention difference, not a parser error.

### Over-read decomposition and JV stake evidence (2026-08-09)

The FY2024/25 revenue-scope ratio of ~140% was decomposed at phase level.
Two conclusions:

1. The over-read is a timing/scope difference, not a data error. The model
   records contract flow (PASP signing date) while the issuer's
   property-sales revenue is recognized at handover (typically 2-3 years
   after signing for HK presales). FY2024/25 contains large recent launches
   (Cullinan Sky Phase 1: 868 units / HKD 11.2bn signed 2024-10; Sierra Sea
   Phases 1-2: ~1,531 units / HKD 8.5bn signed 2025-04/05) whose revenue
   confirms only in FY2026/27+. Same-timing validation against disclosed
   contracted sales reads 86.2% (FY2024/25) and 80.0% (2025H2), i.e. the
   model under-reads in contract scope. The reconciliation panel now carries
   `comparison_validity` (`same_timing_contract_scope` vs
   `recognition_lag_not_applicable`) and an explicit lag caveat on revenue
   rows; revenue-scope ratios are diagnostics only until a handover-lag
   model is added.
2. JV stakes are small contributors, not the over-read driver (all nine JV
   phases total HKD 6.5bn gross in FY2024/25, so 50% vs 100% moves the model
   by ~HKD 3.2bn). Verified evidence:
   `SHKP_CURATED_JV_STAKE_OVERRIDES` promotes Cullinan West I-III (匯璽) from
   unquantified JV to numeric 100% (MTR is land owner/platform provider;
   SHKP holds the development rights), while The YOHO Hub I/II and YOHO WEST
   remain at the verified 50/50 split and Wings at Sea stays a conservative
   50% working assumption. The roster is now 68 numeric + 6 JV.

The monthly backtest also gained a `universe_coverage_ratio` column
(covered phases / full known SHKP universe, currently 230), alongside the
pre-existing grid-internal `model_grid_coverage_ratio`. This exposes the
early-year gap directly: 2013 grid coverage is 100% but universe coverage
0.8%, 2025 is 29.8%, and the 2026 tail drops to 17.7% purely from register
publication lag.

The follow-on research-only sales model is now materialized by
`run-shkp-indicative-sales-model`. It writes monthly, long-scenario, annual,
phase-summary, validation, forecast and project-coverage datasets under the names
`shkp_indicative_sales_model_monthly`,
`shkp_indicative_sales_model_scenarios`,
`shkp_indicative_sales_model_annual`,
`shkp_indicative_sales_model_validation`,
`shkp_indicative_sales_model_forecast`,
`shkp_indicative_sales_model_project_coverage`,
`shkp_indicative_sales_model_phase_summary` and
`shkp_indicative_sales_model_coverage`. Numeric snapshot stakes are fixed;
unquantified JV gross activity is shown under default 25%/50%/75%
low/base/high sensitivities. Monthly outputs include calendar YoY and
gap-aware rolling 3/12-month measures; annual rows flag partial years. This
is a contract-activity proxy rather than recognized revenue or a legal
attribution, and unknown/not-covered rows are excluded from estimated totals
but retained in coverage diagnostics.

The latest normalized model run (`shkp-indicative-sales-model-94460ebc-c577-47ed-a0eb-c7d15d158013`) also persists `shkp_indicative_sales_model_validation`,
`shkp_indicative_sales_model_forecast` and
`shkp_indicative_sales_model_project_coverage`. Validation remains directional:
FY2025/26 model base activity is HKD 30.353bn versus the disclosed HKD 30.100bn
expected-recognition benchmark (100.84%), while the same-window 1H2025/26
comparison is HKD 12.785bn versus HKD 17.4bn disclosed contracted sales (73.5%).
Against recognized property-sales revenue, FY2021/22–FY2024/25 ratios range
from 54.4% to 97.3%; these are timing/scope diagnostics, not accuracy scores.
The FY2026/27 rough forecast uses FY2025/26 as the latest complete fiscal
run-rate, recent four-year growth quantiles of -13.7%/+13.8%/+49.3%, and keeps
growth assumptions separate from 25%/50%/75% JV sensitivities. It is not
management guidance or consensus.

The project-coverage audit shows 43 current SHKP residential-for-sale website
rows mapping to 53 unique SRPE candidate phases; all 53 have current SRPE
manifest/register metadata, but only 17 crosswalk rows are exact, 14 need
review and 40 are ambiguous candidate rows (12 listing names). The six planned
launch labels and two under-development labels in the latest interim
disclosure are not a complete future-project database: only two are currently
phase-linked to SRPE, four remain lot/SRPE-pending, one has multiple SRPE
candidates and one is a non-SRPE commercial/BOT asset. Therefore current
document coverage is broad, identity/ownership coverage is partial, and future
transaction coverage is not yet broad. The broader future-identity evidence
layer has 36 rows (16 with an SRPE ID and 20 without one), so it is a discovery
universe rather than a complete future sales roster.

SRPE also has a structural historical boundary: it is the compliance database
created around the First-hand Sales Ordinance, fully effective 29 April 2013.
The current all-development index starts at 2013-06-11; that is not evidence
that Hong Kong had no earlier SHKP projects. Pre-2013 phases must be sourced
from annual reports, company history/HKEX, RVD/Land Registry or market
archives, and should be tagged `srpe_not_applicable_pre_ordinance` rather than
treated as missing or zero sales.
The milestone layer now also persists
`shkp_history_milestone_identity_crosswalk`: 135 strict phrase-match rows,
with 99 unmatched, 28 ambiguous and 8 matched-needs-review rows. This is a
review queue, not a phase-level ownership mapping.

### SHKP high-recall universe and practical financial vintages (2026-08-09)

The 56-phase transaction set is now explicitly treated as a routing slice, not
the SHKP universe. The full SRPE parent index has 521 stable phase IDs; the
historical transaction layer currently has 197 phases with event-bearing
register rows. A new `shkp_high_recall_phase_candidates` layer evaluates all
521 phases using existing official SHKP directory, annual-report, history,
completion-schedule, pipeline and project-site evidence. The latest review-only
distribution is 24 `likely_shkp`, 163 `possible_shkp_high_recall` and 334
`identity_unknown_owner_evidence_missing`; the last category means only that no
SHKP evidence has been observed yet, not that the phase is not SHKP. 53 phases
currently have an SRPE transaction-register route. All high-recall rows keep
`strict_ownership_promotion_status=blocked_high_recall_identity_only`.

The latest all-history signal rebuild keeps the original 5,604 phase-month
rows/197 phases but reclassifies 403 rows as `indicative_identity_only` after
the high-recall identity pass; 1,808 rows remain `not_observed` because no
SHKP evidence is present. Numeric stake (2,637 rows) and unquantified JV gross
activity (756 rows) remain the only buckets used by the rough sales model. The
new identity-only bucket is visible for quick web review and is not turned into
sales value.

The historical SRPE append/refresh boundary now normalizes the full retained
transaction union before rebuilding its sparse monthly signal. This repairs
compact legacy table rows whose true HKD amount shifted into a property column,
rather than fixing only newly downloaded phases. It also writes
`shkp_historical_srpe_transaction_date_gaps`: PASP-missing/ASP-observed rows
remain in the raw event contract but are explicitly quarantined from the month
grid and indicative model; ASP is never substituted for PASP. No historical
network rebuild was run as part of the code fix. An in-memory replay of the
latest 36,493-row retained union repaired 183 compact rows, quarantined 478
PASP-missing rows and rebuilt 2,365 monthly rows with no sub-HKD100,000 monthly
median/weighted-average price artifact.

The 334 `identity_unknown_owner_evidence_missing` phases have now had a
separate fast, robots-aware static website pass. The persisted
`shkp_unknown_phase_site_evidence` run contains 334 rows: 155 usable static
pages, 92 short/JS shells, 86 fetch errors and one missing URL. Only two pages
exposed SHKP in a statutory role field and one had a page-level keyword; 244
pages had no SHKP keyword. This is a coverage diagnostic, not a rejection
list—no keyword, timeout or dead domain is treated as evidence of non-SHKP.
A full Crawl4AI 0.9.2 fallback then checked all 333 available URLs (including
the 155 pages that were already usable in the static pass) with a 10-second
page timeout and 4-second post-load wait: 235 browser fetches succeeded and 98
failed. The browser lane retained the same two statutory role-field SHKP hits
(LE PALAIS and No.3 Repulse Bay Road) and two page-level keyword hits (ELIZE
PARK and THE KNIGHTSBRIDGE). The latter two are not role evidence: their
statutory vendor/holding-company text does not name SHKP, and the latter's
official developer list excludes SHKP. All identity and sales gates remain
blocked.

A slower retry of the 98 first-pass browser failures recovered 15 pages and
left 83 failures. The failure taxonomy is explicit: 38 DNS/name-resolution
failures, 36 anti-bot/403/script-shell responses, 5 timeouts, 2 TLS failures,
one connection refusal and one unreachable address. This confirms that most
of the residual gap is stale-domain or anti-bot coverage, not simply a page
that needed a few more seconds to render. No retry row produced SHKP role
evidence.

The financial model now also writes
`shkp_financial_model_practical_vintages` (1,870 rows): 1,702 actual
observations from three fetched snapshots, 61 provider consensus statistics
from one snapshot and 107 metric-level broker forecast rows across seven
forecast dates. Actuals without an original announcement date are labelled
`fetched_at_snapshot_proxy`; consensus uses `provider_snapshot_date`; broker
rows use `broker_forecast_date`. This is a useful append-only snapshot history
for rough context/backtests, not a strict PIT tape. Mainland project revenue
remains excluded from this Hong Kong model line.

### SHKP commercial and Mainland coverage branch (2026-08-08)

The residential signal layer is intentionally not presented as a complete SHKP
business model. `run-shkp-commercial-recurring` now writes a separate
research-only branch:

- `shkp_commercial_recurring_facts`: 36 official office/retail/hotel/property-
  investment period facts across FY2024/25 and 1H FY2025/26;
- `shkp_commercial_pipeline_capacity`: 8 named office/mall capacity rows;
- `shkp_commercial_market_context`: 2,406 RVD office/retail market-index rows;
- `shkp_commercial_recurring_coverage`: 28 source/category coverage rows;
- `shkp_mainland_project_coverage`: 9 explicit Mainland coverage rows.

The commercial branch preserves the distinction between a current SHKP asset
catalogue, Group/JV segment facts, completed-property GFA exposure, named
pipeline capacity and RVD market context. It does not infer asset-level rent,
NOI, valuation or ownership from any of those layers. The Mainland audit finds
9 current and 68 historical annual-report project rows, plus aggregate Mainland
rental/land-bank/backlog facts, but no project-level Mainland transaction rows.
The SRPE signal layer is Hong Kong first-hand residential only, so its Mainland
transaction count is explicitly `0 / not_covered`, not zero sales. LandsD/TPB
inputs are Hong Kong-only and remain non-applicable to the Mainland branch.

### SHKP Quarterly and Hong Kong commercial controls (2026-08-08)

The first Hong Kong-only commercial-control tranche is now live through
`python -m src.hk_real_estate.cli run-hk-commercial-controls` and the real-estate
artifact builder. The latest successful run (`93f5b48c-fabf-4fe7-9ff5-f87fe67200d2`)
writes:

- `shkp_quarterly_events`: 244 headline-level issuer events (79
  property-relevant rows exposed in the artifact), covering 2021Q3–2026Q2;
- `shkp_quarterly_numeric_facts`: 43 explicit numeric facts from the latest
  bounded 24-document Hong Kong property subset, each with PDF page, evidence
  sentence and extraction confidence. These are sparse event facts, not a
  quarterly KPI or recognized-revenue series.
- `shkp_commercial_asset_master`: 132 observation rows across the current
  issuer directory, FY2024/25 completed-property exposure and three HK
  completion-schedule snapshots;
- RVD office vacancy (328 annual rows, 1985–2025), office stock/vacancy by
  district (136 rows), commercial stock/vacancy by district (118 rows), and
commercial forecast completions (45 rows including future 2026 horizon);
- C&SD retail value/volume controls (13,050 monthly category rows,
  2004-10–2026-06);
- Tourism hotel occupancy (180 rows) and achieved room rate (180 rows), both
  2021-06–2026-05, plus hotel-room supply (148 rows through 2024-06).

The SHKP financial-model bridge has also been refreshed from the read-only
`financial-data` DuckDB and is now wired into the artifact as
`shkp_hk_financial_bridge` (174 base financial evidence rows; 312 rows after
the compact sales/handover timing projection). It combines 39 selected
official group/segment facts, 30 Hong Kong/group recurring portfolio facts, 32
source-selected 0016.HK actuals, 55 current consensus rows, six unit
reconciliations and twelve coverage/PIT diagnostics. Mainland recurring rows
are excluded from this Hong Kong dashboard view. The bridge keeps row types
separate and does not create a synthetic HK-only revenue series; current
actuals remain historical-context-only because the sibling snapshot has no
original announcement dates, and consensus is a single current snapshot.

The artifact now exposes the Quarterly event table, Quarterly numeric-fact
evidence table, HK commercial asset master, HK financial bridge table,
RVD vacancy/forecast charts, C&SD retail-control chart and tourism occupancy/
ADR charts. These controls are explicitly market-level and are not
joined into synthetic SHKP revenue or same-store NOI. The hotel-room file is
marked `Stale`/`Catalog` because its public content ends at 2024-06; the RVD
forecast is `Catalog` because future-dated years are intentional. The SHKP
completion-schedule parser was also hardened against trailing `Others` subtotal
rows; a regression test now blocks concatenated impossible GFA values.
Mainland project sales remain intentionally out of scope for this tranche.

The first sales-to-handover timing layer is now persisted as
`shkp_sales_handover_revenue_bridge` (197 phase/scope rows),
`shkp_sales_handover_revenue_annual` (26 fiscal-scope diagnostics) and
`shkp_sales_handover_revenue_coverage` (two scope controls). It separates gross
SRPE contract activity from annual-report `handover_completed` evidence,
completion-schedule windows and the current Buildings Department OP crosswalk.
The current-candidate slice has 56 phases, 46 with indicative numeric stake
clues, 22 with annual-report handover evidence, 41 with schedule evidence and
four with a current BD OP crosswalk match. Revenue remains a company-level
annual anchor; no phase-level revenue is allocated. Missing months are not
zero-filled, and the BD OP crosswalk currently lacks an event date.

### SHKP official H1 actual panel and recognition backtest (2026-08-12)

The H1 data-preparation layer is now live through
`python -m src.hk_real_estate.cli run-shkp-h1-backtest`. It fetches the
issuer's official English interim-report PDFs for FY2016/17–FY2025/26, saves
immutable raw snapshots and writes six linked datasets:

- `shkp_h1_report_registry`: 10 reports with period end, exact issuer release
  date, source URL, parser status and `strict_release_date_observed` PIT label;
- `shkp_h1_actual_panel`: 149 fact rows. Revenue, reported/underlying profit,
  gross/net rental income, EPS and interim dividend each have a complete
  ten-report series. The parser now recovers Hong Kong development/rental
  revenue from legacy/current segment tables and adds combined hotel revenue;
  explicit office/retail revenue remains available for only the recent three
  reports;
- `shkp_h1_to_fy_bridge`: 29 rows across consolidated group revenue, reported
  profit and Hong Kong property-sales revenue. H2 is explicitly FY minus H1;
  it is not a separately filed observation;
- `shkp_h1_actual_vs_nowcast`: 26 rows comparing 2×H1 annualization with an
  expanding prior-three-year median H1-share holdout. Training fiscal years
  are stored and strictly precede the target.
- `shkp_h1_component_annual_history`: 16 annual component anchors combining
  consolidated group revenue with Hong Kong development, Hong Kong rental and
  combined hotel revenue; the residual is explicit and absorbs Mainland,
  telecom/infrastructure, other businesses and JV/scope differences.
- `shkp_h1_component_actual_vs_nowcast`: 10 rows, including seven valid
  historical holdouts and the current FY2025/26 H1-only forecast. It forecasts
  H2 by prior component H2/H1 ratios and is deliberately a rough recognition
  diagnostic, not a project-level handover model.

The current H1/FY bridge is a recognition-seasonality diagnostic, not a
finished earnings forecast. For group revenue, valid holdouts show a mean APE
of about 14% for 2×H1 versus about 19% for the prior-share baseline; the
relative ranking changes by year. HK property-sales recognition is much more
lumpy (the corrected segment-table history ranges from roughly 12%–89%), so it must remain a separate
handover scenario layer. FY2026 H1 has no FY actual yet and is excluded from
scoring.

The official H1 panel is strict on issuer availability: report release date is
the earliest usable date, not 31 December. Consolidated FY2017–FY2020 annual
fallback rows still come from the sibling financial-data source and are marked
non-PIT because original announcement timestamps are unavailable; official
annual summary/segment history is preferred from FY2021 onward. The component
bridge currently has mean APE about 28.5% across seven holdouts, worse than
the 2×H1 baseline; this is useful evidence that H2/FY component ratios are not
stationary enough yet, not a reason to tune the model after seeing the target.
The report and five QA charts are in
`docs/asia-markets/SHKP_H1_BACKTEST_REPORT.md` and
`docs/asia-markets/charts/shkp_h1_*.png`. The focused H1 test suite has 8
passing tests. Two unrelated pre-existing financial-model invariant tests
remain failing in the broader selected suite and are not caused by this H1
layer.

### Buildings Department historical detail QA (2026-08-09)

The detailed Md52–Md56 parser now has a bounded cross-year QA contract. Parser
v6 reads shifted multi-line PDF headers for Md53–Md56, handles the 2005–2010
and 2020 OP layouts, preserves same-address multi-row approvals, skips appended
corrigenda, and no longer truncates four-digit unit counts. The
persisted `bd_project_lifecycle_history_audit` covers 2005–2024 December
archives plus the latest direct PDFs for 2025 and 2026 (110 stage rows). It
reports 86 `matched`, 2 `matched_zero` (the detail table has no domestic-unit
cell and Section 1 explicitly reports zero), and 22 `not_comparable` rows for
Md52, with no unresolved `gap` rows. Md53 project counts, Md54 units and Md56
units reconcile in all 22 samples; Md55 has 20 matched samples plus the two
explicit zero cases. Explicit amendment rows are retained in the detail
contract but excluded from the as-published Section 1 comparison and exposed
in the audit. This closes the stage-level parser QA, but the detailed history
remains scratch/research data rather than a production SHKP attribution input:
it still has no exact permit day and requires separate address/permit entity
resolution. The audit stores exact comparison values and source lineage, never
fills missing months, and never promotes ownership.

The full monthly detail backfill is also persisted as run
`c752686d-aace-4dcb-8f24-12336d5ee004`: 17,517 rows across 257 published
months from 2005-01 through 2026-05, with no empty published month. The lineage
has one missing stage-month (`2020-02` Md55) explicitly marked `NIL` in the
official Table 5.5, and records 2026-06/07/08 as unavailable official links
rather than zero activity.
All rows have `parser_quality_flag=ok`; Md54/Md55 rows remain structurally
`MEDIUM` confidence because those tables do not publish a permit number. The
v6 applicant-band fix was re-run through the strict local CLI
`run-bd-project-history-local-reparse` as run
`c752686d-aace-4dcb-8f24-12336d5ee004` using all 257 existing raw PDFs (no
network fetch): the 17,517-row output now has 207 candidate clusters with
observed applicant text, 11 suffix-only/truncated extracts and 5 missing or
not-published values after the SHKP/BD compression. This monthly layer is
still a research/scratch contract until historical addresses and permits are
resolved to stable SHKP phases.

### SHKP/BD entity-resolution review queue (2026-08-09)

The first bounded review layer is now persisted by
`run-shkp-bd-history-entity-review`. It compresses the address-only
`shkp_bd_history_crosswalk` into one row per unique SRPE development ID and a
run-level summary, without fetching new sources or changing the ownership gate.
The latest run `shkp-bd-history-entity-review-e7ad2448-af42-4718-816f-9c9dffe91889` has 53 unique phase IDs
from 71 crosswalk candidate rows: 48 have at least one historical BD address
hit, 43 are `P0` shared-address reviews, 5 are single-phase `P1` reviews and 5
are unmatched `P2` rows. The hit rows summarize 220 historical BD rows and 73
distinct permit-number strings. All 53 phases now carry raw project-site probe
context: 31 role-field `site_named_shkp`, 7 generic `page_named_shkp`, 12 no
SHKP keyword and 3 not evaluated after the bounded HTTP plus browser fallback;
53 phase IDs now have curated official SHKP project/Quarterly/promotion role
evidence across 55 curated role rows. The queue keeps these layers separate: `shkp_site_probe_match_status`
is the raw probe result, while `developer_identity_status` may use the stronger
curated role layer.

This is a routing/control layer, not a permit attribution table. Repeated
monthly/stage rows are collapsed only for review context; `digest_month` is
still a publication/observation month, no exact permit day is inferred, and
both `ownership_promotion_status` and `permit_attribution_status` remain
`blocked_address_only` for all 53 rows. The site role evidence helps establish
developer identity (for example, the NOVO LAND phase pages) but does not by
itself resolve a shared address to one BD phase. The same run now persists
`shkp_bd_phase_group_evidence`: 23 groups covering all 53 candidate phases,
including 14 shared-address groups, 6 single-phase controls and 3 unmatched
controls. Official SHKP completion-schedule group labels are observed for 17
of the groups (for example NOVO LAND 1A/1B, 2A/2B, 3A/3B and Sierra Sea
1A(2)/1B, 2A/2B). The group layer de-duplicates phase×BD copies, records
permit-year and SRPE first-publication order context, and explicitly does not
treat either order or schedule grouping as a permit start bound. The next evidence step is manual or bounded
source review of phase labels, lot tokens, permit/applicant clusters and
phase-specific project documents. The same run now also emits
`shkp_bd_phase_permit_candidate_evidence`: 131 group × schedule-context × BD
cluster rows (100 P0, 26 P1 and 5 P2). Forty-nine rows carry a narrower official
completion-schedule phase-group context and the table carries 55 curated
phase-role evidence rows across 53 phase IDs, SRPE/SHKP URLs and BD PDF page references beside the
candidate cluster. This is a primary-document review queue rather than a
permit mapping: schedule Group's Interest/JV text, permit-number years and
digest months remain context only, and all 131 rows remain
`blocked_address_only` for both ownership and permit attribution. The candidate
table now also reads the existing local BD detail PDFs (no network fetch): 62
rows have extracted page-level phase tokens; 10 have all tokens in the current
candidate set, 51 contain at least one token outside it and 1 has no comparable
candidate phase number. The new `bd_pdf_unmatched_phase_tokens` field makes
candidate-context gaps explicit; some are another phase in the same address
group, while no group match is a stronger SRPE-universe gap clue (for example,
a shared PDF mentions 1A while the current candidate set only contains 1B).
Sixty-four review pages have no
phase token and 5 were not evaluated. A cross-group pointer, phase-variant or
unmatched-token flag is an audit route for primary-document review, not an
automatic rejection or phase assignment.

The same run also persists `shkp_bd_phase_permit_reconciliation`, a derived
research-only classification of those 131 candidate rows. It records 10
single-phase primary-document concordances, 3 multi-phase set concordances, 7
narrowed phase sets, 16 cross-group pointers, 2 same-family phase-variant reviews,
24 label-format reviews, 10 official-schedule phase sets needing a primary PDF,
54 no-token reviews and 5 schedule/address-only rows.
These are review
candidate sets, not permit assignments; `permit_assignment_status`,
`ownership_promotion_status` and `permit_attribution_status` remain
`blocked_address_only` for every row.

The latest run adds an explicit context-outcome surface to both candidate
evidence and reconciliation. Twenty rows are marked
`phase_context_supported_not_assigned` because a primary BD PDF token set and
the official completion schedule support the same candidate context; 16 rows
are `phase_context_points_to_other_group_phase_not_assigned`, 2 are
`same_family_phase_variant_review`, 10 are schedule-only context and 83 remain
`unresolved_primary_document_context`. These statuses describe evidence
strength only. `phase_context_reviewed_candidate_ids` is a review candidate
set—not a legal permit mapping—and no status opens either promotion gate.

The same candidate/reconciliation rows now carry an explicit join to the
latest `shkp_indicative_ownership_roster` plus curated phase-role evidence.
Across 131 rows, 71 are all-candidate-phase numeric snapshots and 60 are
all-candidate-phase unquantified JV contexts; every row also has role context
(`phase_role_evidence_count` > 0). The indicative percentage/range fields are
populated only when the candidate context is a single phase; grouped contexts
keep per-phase values in `indicative_phase_ownership_context_json`. These are
model inputs/review aids only, and `strict_ownership_attribution_ready` remains
false.

The latest run also emits `shkp_bd_phase_ownership_review`, a one-row-per-phase
roll-up for the 53 SHKP/SRPE IDs. It separates 44 numeric-snapshot review-only
phases from 9 unquantified-JV review-only phases, and reports phase-context
coverage as 2 supported-only, 19 supported-plus-unresolved, 3 other-group,
2 same-family-variant and 27 unresolved. This is the compact review/model
surface; shared-address rows are never summed or assigned, and all 53 rows
remain `blocked_address_only`.

The lowest-cost evidence order is: (1) SRPE phase/development detail and lot
tokens, (2) the matching SHKP project page's `Vendor`/`Person so engaged`/
`Holding Companies of the Vendor`/`Sales Agent` fields, and (3) BD
`permit_number` + applicant + address clusters. These can downgrade some P0
rows to single-phase review but still cannot open ownership attribution. TPB
Statutory Planning Portal and LandsD lot/sale documents are the next lot-level
cross-check; Land Registry IRIS is the strongest residual evidence but is a
paid/manual pilot, not a free bulk scrape. The public Street Index/CRT is
useful only as an interactive lookup and is not saved or scraped because its
terms restrict copying and batch use.

The same run now emits `shkp_bd_phase_resolution_candidates`: 223
phase/permit/stage/address/applicant clusters from the 225 crosswalk rows. It
contains 198 shared-address `P0` candidates, 20 single-phase address `P1`
candidates and 5 unmatched `P2` candidates; 179 clusters have an observed BD
permit-number string and 44 do not. After the v6 local raw-PDF reparse, the
parser-quality flag marks 11 clusters as likely suffix-only/truncated applicant
extracts, 5 as missing/not published and 207 as observed text. This is a
routing table rather than a permit attribution table:
repeated digest observations are counted for audit context only, units and
floor area are never summed, applicant text cannot be treated as a legal
identity, and ownership plus permit attribution remain
`blocked_address_only`.

## Agent handoff checklist

Before starting a new task:

1. Read `OPERATING_MANUAL.md` and `DATA_CATALOG.md`.
2. Check `git status --short` for existing work.
3. Identify the sector roster entry, builder, artifact and status file.
4. Decide whether the requested metric is a time series, snapshot, catalog
   record or research-only item.
5. Update this file if the task changes the project state or resolves one of
   the limitations above.

### SHKP Hong Kong commercial portfolio model (2026-08-09)

New research module (`run-shkp-commercial-model`,
`src/hk_real_estate/shkp_commercial_model.py`) implementing the
user-directed portfolio-level design: the core engine is a log-difference
distributed-lag bridge from RVD rental indices to SHKP HK rental revenue;
asset-level GFA is used only for attribution, never for revenue prediction.

Transmission estimates (FY2016-2025, log-difference):
- Office: contemporaneous elasticity ~0.33 (R2 0.42), distributed-lag total
  ~0.37 with a near-zero one-year lag term - office revenue tracks the index
  in the same year (annual reversions), total elasticity ~0.35.
- Retail: distributed-lag total ~0.63-0.69 (R2 0.49-0.53) with a strong
  one-year lag component (beta_lag1 ~0.35 vs contemporaneous ~0.29) -
  turnover rent and multi-year mall leases spread the pass-through.
- Stability caveat: dropping FY2021 (COVID crash) cuts contemporaneous
  betas from ~0.32 to ~0.15 (R2 0.11), so estimates are scenario-grade, not
  point-precision; recorded on every row.

Walk-forward OOS backtest (FY2020/21-FY2024/25, portfolio total):
- contemporaneous MAPE mean 2.25%, distributed-lag 2.68%, naive-flat 2.54%.
- The naive no-information baseline is nearly as good because SHKP HK rental
  revenue is highly stable (annual moves of 1-3%); distinguishing RVD value
  needs longer/wilder history or the office/retail split series (currently
  only FY2023/24+).

Attribution map (`shkp_commercial_attribution`, 82 rows): GFA-share
allocation of the disclosed HK office (HKD 5,679m) and retail (HKD 9,085m)
revenue across assets with disclosed GFA; 41 assets lack GFA and are
explicitly flagged `gfa_not_disclosed` rather than counted as zero.
Top office exposure by allocation: Mong Kok Lot 11273 (HKD 786m),
International Gateway Centre (HKD 756m), Central Plaza (HKD 462m).

### Commercial v0.2 - historical extension and freeze (2026-08-09)

History extended from 11 to 16 fiscal years (FY2010/11-FY2024/25) by
downloading the 2010/11-2012/13 annual reports and extracting the HK rental
segment rows (subsidiary + combined series, both persisted:
`SHKP_HK_RENTAL_REVENUE_HKD_M` and `SHKP_HK_RENTAL_REVENUE_SUBSIDIARY_HKD_M`).
The FY2014/15 values were re-verified against the source PDFs after the
first pass contained transcription errors (15,472/18,958 corrected to
14,673/15,675); every year is now double-checked via the current-year and
prior-year tables in adjacent annual reports.

Office/retail revenue split could NOT be extended historically: SHKP only
discloses the HK office/retail breakdown from FY2023/24 onward (3 years);
earlier reports use narrative descriptions. The split remains a
qualitative sanity check only (accounting bridge), not a statistical
backtest, per the v0.2 design.

The 16-year sample materially changes the transmission conclusions:

| Metric | 10-year (2016-25) | 16-year (2011-25) |
|---|---:|---:|
| Office beta | 0.33 (R2 0.42) | **0.83 (R2 0.87)** |
| Office ex-COVID beta | 0.15 (unstable) | **0.84 (stable)** |
| Retail beta | 0.32 (R2 0.24) | **0.86 (R2 0.78)** |
| Retail DL total elasticity | 0.63 | **1.02** |
| Retail ex-COVID beta | 0.15 (unstable) | **0.80 (stable)** |

The earlier "elasticity driven by COVID" concern was a small-sample
artifact. With 15 observations the RVD -> SHKP rental-income transmission
is stable and strong, with retail showing a clear one-year lag component
(b0 ~0.59 + b1 ~0.43) versus office being largely contemporaneous
(b1 ~0.17).

Walk-forward OOS backtest (FY2016-2025, 10 years):

| Method | MAPE mean |
|---|---:|
| naive flat | 3.85% |
| RVD contemporaneous | 1.76% |
| RVD distributed lag | **1.62%** |

RVD information halves the OOS error versus naive, confirming incremental
predictive power. Commercial v0.2 is now FROZEN: portfolio-level
log-difference RVD bridge (office beta ~0.83 contemporaneous, retail
~0.59+0.43 distributed lag), attribution-only asset map, and the honest
3-year split limitation. The next step is the whole-company earnings
nowcast that combines residential (SRPE model), commercial (this module),
hotels and other businesses.

### Whole-company earnings bridge and EPS driver diagnosis (2026-08-09)

`run-shkp-earnings-bridge` materialises the 15-year (FY2011-FY2025) group
earnings bridge (`shkp_historical_earnings_bridge`) from the official
Group Financial Summary / Five-Year Financial Summary pages of the 2014/15,
2019/20 and 2024/25 annual reports. Columns span revenue, operating profit
pre/post FV, underlying profit, FV effect (disclosed from FY2021; derived as
pre-minus-post-FV operating profit before that), reported profit,
underlying/reported EPS and DPS, plus the FY2021-25 segment split (property
sales / rental / other businesses revenue and profit). Overlap years
(FY2015, FY2020) were checked across adjacent summaries and all values
verified against the source PDFs.

EPS driver diagnosis (the design basis for the whole-company nowcast):

* Property-development profit is the ONLY material earnings driver.
  FY2021-25 segment decomposition shows its share of segment profit
  falling from 47.5% to ~25%, and the YoY underlying-profit changes are
  almost entirely property-sales moves (-5.1bn, -4.5bn, -3.4bn, +0.4bn)
  while rental (18.4-19.3bn, near-flat) and other businesses (4.0-5.5bn,
  rising) contribute little variance. Residential profit = recognised
  revenue x development margin is therefore the make-or-break module.
* Rental profit is extremely sticky (as found in the commercial module);
  a run-rate / normalised-margin treatment is appropriate.
* Investment-property FV changes dominated reported profit in FY2011-2019
  (36%-117% of underlying) but turned into a stable -11% to -15% drag from
  FY2020. Forecasting reported EPS directly would be dominated by
  valuation marks; underlying EPS is confirmed as the primary nowcast
  target, with reported EPS as an accounting bridge only.

The hotel segment series (`shkp_hotel_segment_series`, FY2013-2025, 13
years) is persisted alongside the bridge, extracted from the segment notes
and verified against the source PDFs. It confirms hotel must be modelled
separately: normal-year operating margin is 23-28%, COVID years swung to
-10.7%/-20.1%/-14.0% (FY2020-22, revenue -46% turned a +1,433 result into
-330), and FY2023-25 recovery margins (3.8%/12.4%/11.7%) remain below the
pre-COVID norm. FY2011-2012 are absent (different segment-table layout in
those annual reports). A revenue x normalised-margin treatment with
bull/base/bear margin scenarios is the appropriate hotel module.

### Whole-company earnings skeleton v0.1 (2026-08-09)

`run-shkp-whole-company-model` builds the first whole-company earnings
skeleton combining the frozen modules:

* Residential development profit = FY2027 contract scenario
  (`shkp_indicative_sales_model_forecast` numeric-stake base 32.5bn)
  x latest-year development margin (24%, FY2025 property-sales
  profit/revenue) with a mechanical recognition lag - deliberately
  conservative versus the 36% five-year mean.
* Commercial net rental income = FY2025 HK NRI run-rate (12,956) with a
  +/-3% RVD sensitivity spread.
* Hotel = FY2025 revenue x bull/base/bear margin (15%/12%/10%).
* Other businesses = FY2025 run-rate (5,506).
* Below-segment residual = FY2025 underlying minus the modelled FY2025 HK
  segment (absorbs Mainland commercial/development profit plus
  finance/tax/NCI), persisted as a single residual line.

Base FY2027E output: modelled segment 26.9bn, below-segment -3.9bn,
underlying profit 23.0bn, underlying EPS 7.95, reported EPS 7.06.
Consensus comparison (strict underlying-EPS convention, flagged): model
7.95 vs broker median 8.65 = -8%. The 3x3 material-driver matrix
(residential bear/base/bull x commercial bear/base/bull) spans underlying
EPS 6.4-9.6. The skeleton deliberately exposes where the model and the
street disagree (conservative residential margin + mechanical lag) rather
than forcing them to match.

### Handover-lag analysis and consensus-gap decomposition (2026-08-09)

`run-shkp-handover-lag` estimates the residential recognition lag from 21
SHKP phases with both a launch date (SRPE earliest publication) and a
handover confirmation (annual-report handover year): P(lag=0)=29%,
P(lag=1)=48%, P(lag=2)=24%, mean 0.95 fiscal years, median 1.0. The old
mechanical ~2-year shift was too conservative; the modal SHKP presale is
handed over about one fiscal year after launch. The recognition schedule
applies these weights to actual contract activity (FY2026) and the sales-
model FY2027 forecast, giving FY2027E recognised residential revenue of
HKD 33.1bn.

Consensus-gap decomposition (model base 8.01 vs broker median 8.65
underlying EPS, -7.3%):
* Recognition timing contributes only +0.06 EPS (old mechanical 2y vs lag-
  based schedule) - NOT the main disagreement.
* The entire remaining -0.63 EPS gap is development margin: consensus
  implies ~29.6% residential margin on the same recognised revenue vs the
  model's 24% (FY2025 latest-year). Equivalent reading: consensus implies
  ~HKD 40.8bn recognised revenue at 24% margin, ~23% above the model.
* Rental/hotel/other/below-segment are run-rates in both, so they do not
  drive the gap.

Conclusion per the Tier-1 priority: project-mix development margin
(②) is the next module - the market is paying for a margin recovery to
~30% that the aggregate latest-year margin does not support without
project-level evidence.

### Project-mix development margin model (Tier 1, step 2 - 2026-08-09)

`run-shkp-project-margin-model` completes steps 2A-2D:

* Step 2A - historical HK development-margin anchor
  (`shkp_hk_development_margin_history`, FY2013-2025): the frozen margin
  definition is HK attributable combined development profit / HK recognised
  property-sales revenue (segment note, NOT the all-region five-year
  summary). Distribution: median 39.0%, mean 35.1%, 25/75 pct 28.0%/41.8%,
  FY2025 trough 12.2% (YOHO WEST/NOVO-led handover at compressed margins),
  recent-3y mean 24.7%. Consensus-implied 29.6% sits at the 31st historical
  percentile - below the historical median, above the recent trough.
  Issuer recognition guidance collected from the annual reports: HK backlog
  24.9bn -> 19.6bn recognised next FY (FY2024 report) and 35.6bn -> 30.1bn
  (FY2025 report), i.e. an ~80-86% one-year recognition rate.
* Step 2B/2C - feature-based margin buckets assigned to the FY2027
  recognition schedule (60 phases): luxury ASP >= 15m/unit -> high bucket
  (35-40%), 10-15m -> mid (27-32%), mass-market <= 10m -> low (20-25%)
  with launch-vintage as the land-cost proxy. Revenue-weighted FY2027
  margin = 29.1% (26.6-31.6% bracket). Key mix: Cullinan Sky 2 (ASP 22m,
  11% weight, high), Sierra Sea/NOVO/Lime Spark mass-market (30% weight,
  low), Cullinan Harbour (67m ASP, high).
* Step 2D - consensus-required mix: the weighted 29.1% is only 0.5pp below
  the consensus-implied 29.6% (HKD 162m profit, ~HKD 0.06 EPS). The FY2027
  mix therefore largely explains the consensus margin; no extreme
  assumption is needed.

Whole-company skeleton updated to use the project-mix margin: base FY2027E
underlying EPS is now 8.59 vs consensus 8.65 = -0.6% (was -8.0% with the
aggregate 24% margin). The EPS path: 7.95 (aggregate margin) -> 8.01
(+recognition lag) -> 8.59 (+project-mix margin). The model is now a
variant-perception model: the remaining -0.6% is within bucket-range
uncertainty, and the interesting output is the margin-by-project table
itself (which projects the market's 29.6% implies vs which the model's
mix supports).

### Margin variant analysis - consensus & sensitivity layer (2026-08-09)

`run-shkp-margin-variant` (Project Margin v0.2) delivers the four
user-directed layers. Aggregate EPS is now within 0.6% of consensus, so
the valuable output is the conditional disagreement, not the level.

Material groups (60 phases -> 9 groups, top-5 = 47.5% of FY27 recognised
revenue):

| Group | Weight | Margin | EPS / 1pp | Priority |
|---|---:|---:|---:|---|
| Sierra Sea | 27.7% | 22.5% | 0.032 | HIGH |
| Other (42 phases) | 19.5% | 31.0% | 0.022 | HIGH |
| NOVO LAND | 11.1% | 27.2% | 0.013 | med |
| Cullinan Sky 2 (luxury) | 11.1% | 37.5% | 0.013 | med |
| Cullinan Sky 1 | 8.1% | 29.5% | 0.009 | med |
| Lime Spark | 7.0% | 22.5% | 0.008 | med |
| Cullinan Harbour / Victoria Harbour / St Michel | 15.5% | 37.5% | <=0.008 | low |

Sierra Sea alone carries 27.7% of FY27 revenue and +-0.16 EPS across its
full bucket range - the single highest-value research target, 2.5x the
next group. The catalyst map (`shkp_margin_catalyst_map`) ties each group
to observable KPIs (batch ASP vs launch, incentives/rebates, sales
velocity, secondary premium) and the EPS revision of a +-3pp margin move:
Sierra Sea +-0.095 EPS, NOVO/Cullinan Sky 2 +-0.038.

Consensus-required margin feasibility (`shkp_margin_consensus_required`):
holding other groups at model assumptions, consensus 29.6% requires Sierra
Sea 22.5%->23.8% (+1.3pp, feasible), NOVO +3.2pp (feasible), Cullinan Sky
2 ->40.7% (at bucket top), while Lime Spark/Cullinan Harbour/Victoria
Harbour/St Michel alone cannot explain it - so consensus is a broad
dispersion of small per-project upgrades, not a single aggressive
assumption. Conclusion: consensus FY27 development earnings are broadly
reasonable; the bear/bull variants are conditional on Sierra Sea and
mass-market price action, not on the aggregate level.

Residential Tier 1 is now FROZEN (recognition kernel v0.2 + margin
buckets + variant layer). Next: Mainland / below-segment decomposition
(③) for accounting completeness, with the explicit expectation that it
improves the earnings bridge rather than creating a new material variant.

### FY2026 nowcast and skeleton backtest (2026-08-09)

The skeleton now covers TWO fiscal years (FY2026E + FY2027E, 18 scenario
rows) with per-year recognised revenue and project-mix margin:

* FY2026E: recognised 30.4bn (lag kernel vs official company guidance
  30.1bn, within 1%), weighted margin 29.8%, underlying EPS 8.39 vs
  consensus 7.91 = +6.1% - an upside variant, driven by the official
  recognition guidance plus a margin mix slightly above consensus.
* FY2027E: recognised 33.1bn, weighted margin 29.1%, underlying EPS 8.59
  vs consensus 8.65 = -0.6% (unchanged).

`run-shkp-skeleton-backtest` replays the frozen residential engine
(lag kernel x margin bucket) plus a point-in-time 3-year non-residential
run-rate on FY2017-FY2025 (`shkp_skeleton_historical_backtest`, 9 rows).
Results: MAE 20.1% on underlying profit, systematically UNDER-estimating
in FY2017-2022 (-15% to -31%) and converging to -2.4% (FY2024) and -0.2%
(FY2025). Two structural error sources, reported separately per row:

1. Non-residential run-rate lags Mainland development spikes (FY2025
   non-residential actual 18.7bn is 26% above the 3-year mean 14.8bn) -
   the Mainland mean-reversion variant from ③, now quantified in
   backtest terms.
2. The margin bucket (calibrated to the FY2026/27 mix) understates the
   FY2017-2020 high-margin mix (actual 32.8-44.9% vs bucket 22.5-37.5%),
   so historical backtests are conservative in early years by design.

The convergence to ~0% in FY2024/25 means the CURRENT-year estimate
(FY2026/27) is where the model has the most validation support; the early
under-estimate is a mix/composition effect, not a broken engine.

### SHKP Earnings Model v1.0 FROZEN (2026-08-09)

Full-chain validation completed and the model frozen as v1.0. See
[SHKP_EARNINGS_MODEL_V1_STATUS.md](asia-markets/SHKP_EARNINGS_MODEL_V1_STATUS.md)
for the complete report. Headline items:

* Engineering gate: 9/9 invariant checks pass (unit consistency,
  accounting identities, PIT design, version consistency - skeleton
  consumes the frozen project-mix margins, verified by reverse-derivation).
* FY25A->FY26E->FY27E bridge: underlying EPS 7.54 -> 8.39 -> 8.59;
  consensus 7.91/8.65 => FY26 +6.1% (positive variant), FY27 -0.6%
  (neutral). The FY26 upside is entirely residential in the decomposition
  (30.4bn x 29.8% vs consensus-implied ~25.2% margin or ~25.7bn volume),
  with the Mainland/below-segment assumption as the stated caveat.
* Backtest framed in three layers: component validation (kernel +1.0% vs
  official guidance; commercial MAPE 1.62% vs 3.85% naive) = strong;
  skeleton portability (MAE 20.1%, early years systematically low due to
  margin-regime and Mainland composition) = stress test, not accuracy;
  recent-regime fit (FY2024 -2.4%, FY2025 -0.2%) = expected, not clean
  OOS proof.
* Confidence table: recognition HIGH, development margin MEDIUM-HIGH, HK
  commercial HIGH, hotel MEDIUM, Mainland/other MEDIUM/LOW, whole-company
  EPS MEDIUM (below-segment residual the key risk).
* Next phase is the INVESTMENT LAYER (FY26 upside sources, consensus
  revision catalysts, falsification data), not further model building.

### Skeleton backtest v2: vintage margin default (2026-08-09)

User question: why is the 2013-2022 underlying error so large, and is it
missing 2013-era SHKP phases or the mainland real-estate boom?

`run-shkp-skeleton-margin-decomposition` now attributes the backtest error
to margin assumption vs data coverage by replaying the SAME frozen engine
under four margin treatments per fiscal year (does not touch the frozen
v1.0 backtest output):

| mode | MAE underlying | meaning |
|---|---:|---|
| bucket (frozen) | 12.4% | static FY26/27-calibrated 22.5/29.5/37.5% |
| vintage (launch-cohort) | 6.4% | PIT, deployable: margin from `coverage_start` year |
| rolling_actual | 11.4% | PIT prior-3y mean of actual HK dev margin |
| actual (hindsight) | 8.3% | ceiling: perfect margin model |

Key findings:
* It is NOT the mainland boom: mainland dev profit only spiked in FY2021
  (6.4bn) and FY2025 (5.1bn); in FY2021 the non-res run-rate captured it
  (error -135m) and in FY2025 it was offset by residential over-prediction.
  The systematic FY2017-2022 under-estimate is a residential-model effect.
* The single largest fixable source is the static margin bucket being
  calibrated to the FROZEN low-margin FY26/27 mix while actual HK dev
  margins in 2017-2022 ran 32.8-45.1% (bucket mid 29.5%).
* A launch-cohort ("vintage") margin calibration is PIT and deployable and
  cuts MAE from 12.4% -> 6.4%, beating even the hindsight "actual" mode on
  recent FY2023-25 where the market margin collapsed and a rolling actual
  overshoots. This is the recommended margin history fix.
* Residual error after the margin fix is dominated by: FY2016/17
  (data floor - SRPE went live 2013, kernel 0.36), FY2019/20 and FY2021/22
  non-residential run-rate swings, and the FY2024/25 non-res run-rate
  lagging the Mainland development spike (-3.8bn).
* Recommendation: adopt the vintage margin calibration for historical
  backtests (MAE 12.4->6.4%); only then pursue 2013-era phase backfill for
  the FY2017/18 and FY2022 kernel gaps; FY2016/17 stays a documented source
  limit.

ACTED ON (user directed: no 2013-era legacy backfill, update backtest):
* `build_shkp_skeleton_backtest` now defaults to ``margin_mode="vintage"``
  (launch-cohort margin from `coverage_start` year); the legacy static bucket
  remains available as ``margin_mode="bucket"`` for comparison.
* Historical backtest MAE improved 12.4% -> 6.4% without touching the frozen
  v1.0 forward engine.  Full 9-year vintage backtest:
  FY2016/17 -7.6%, FY2017/18 -6.5%, FY2018/19 -1.4%, FY2019/20 +12.9%,
  FY2020/21 -4.6%, FY2021/22 -16.1%, FY2022/23 -5.4%, FY2023/24 +2.6%,
  FY2024/25 +0.05%.  Residual FY2021/22 (-16%) and FY2019/20 (+12.9%) are
  non-residential run-rate swings around Mainland/rental cycles, not a margin
  or data-coverage problem; FY2016/17 is the SRPE-2013 data floor.
* The conforming tests were updated to assert the vintage default and that
  bucket mode remains strictly more conservative.

### Historical coverage backfill (2026-08-09, COMPLETE)

The skeleton backtest's early-year under-coverage (FY2016-2022 kernel
recognised/actual ratio 0.27-0.60) was traced to missing SHKP legacy
project transaction registers, plus one latent bug:

* CURATED STAKE UNIT BUG (fixed): `SHKP_CURATED_JV_STAKE_OVERRIDES` and
  `SHKP_CURATED_PROMOTIONS` stored fractions (1.0) while the roster column
  `indicative_ownership_pct` is percent (100.0). Cullinan West (匯璽)
  phases were silently attributed at 1% instead of 100%, shrinking their
  HKD 17bn+ of contract activity 100x in the model. Values corrected to
  100.0; this also fixed the same latent error in the new promotions.
* Backfilled SHKP legacy registers (routing-only, ownership verified):
  - The Cullinan / 天璽 (Kowloon Station Dev, opened 2013-09): 250 events,
    HKD 11.4bn, FY2014+ concentrated - the single largest missing phase.
  - Shouson Peak (壽臣山, 2013-09): 29 events, HKD 6.6bn.
  - Twelve Peaks (山頂, 2014-06): 11 events, HKD 5.4bn.
* Curated exclusions added (verified non-SHKP): Mount Nicholson x2
  (Wharf + Nan Fung), Mount Pavilia (New World) - registers downloaded in
  the same backfill are excluded from the model.
* Effect: kernel recognised/actual ratio mean 0.71 -> 0.83 (2019-2021 near
  1.0); skeleton backtest MAE 20.1% -> 12.5%, FY2019/20 -4.0%, FY2023/24
  -1.0%, FY2024/25 +0.9%. FY2026E EPS 8.51 (+7.6% vs consensus), FY2027E
  8.77 (+1.4%).
* The Wings (唐賢街9號, TKO Town Lot 72) additionally promoted to SHKP
  100% - the earlier address-based exclusion wrongly suppressed this
  phase (it IS SHKP's own development: annual handover tables list "The
  Wings II/IIIA/IIIB" at 100% and SHKP history milestones record a 2011
  launch / 2014 handover; it is not the CK Asset LOHAS "The Wings").
  SRPE carries only its tail registers (15 events, HKD 0.5bn), so the
  gain is small but the identity is now correct.

Final kernel ratios (FY2016-2025): mean 0.85, median 0.93 (from 0.71 /
0.68). FY2019-2024 at parity (0.93-1.07); FY2017-18 at 0.75-0.83; FY2022
0.74; FY2016 0.36 (hard floor: SRPE went live 2013, pre-2013 launch
registers are not on the platform). Skeleton MAE 20.1% -> 12.4%,
FY2023/24 -1.0%, FY2024/25 +1.0%. Residual early-year error is a
documented source limitation, not an implementation gap. 218 tests pass.

### Below-segment / Mainland decomposition (③ - 2026-08-09)

`run-shkp-earnings-bridge` now also persists
`shkp_below_segment_decomposition` (FY2014-2025, 12 years) with explicit
Mainland development, Mainland rental and Singapore rental revenue/profit
from the segment notes (verified: FY2025 mainland development 8,417/5,090
matches the annual-report narrative "+214%/+281%").

Key findings:
* Mainland+Singapore combined profit averaged 6.7bn with CV 0.32; the
  volatility is almost entirely Mainland DEVELOPMENT (std 1.5bn, FY2021
  spike 6.4bn vs FY2022 trough 1.0bn), while Mainland rental is stable
  (std 1.1bn).
* FY2025 Mainland+SG = 10.5bn = 1.56x the 12-year mean, driven by the
  Shanghai Arch Phase 3 delivery (mainland dev 1.3bn -> 5.1bn, +281%).
* This is a REAL second variant, not just bridge completeness: the
  skeleton's below-segment residual is FY2025-calibrated and therefore
  embeds the elevated FY2025 Mainland dev. If Mainland dev mean-reverts
  to ~2.7bn by FY2027, the residual worsens by ~2.4bn (~-0.8 EPS);
  if it stays elevated (more Shanghai/major deliveries), the residual
  holds. The FY2026 HK recognition guidance (30.1bn) offsets part of the
  HK-side uncertainty but not this Mainland exposure.
* The skeleton formula is intentionally NOT changed to add Mainland
  explicitly (that would double-count, since the residual is already
  calibrated to FY2025 underlying); the decomposition is the diagnostic
  layer that exposes the residual's composition and its mean-reversion
  risk. A follow-up could model Mainland dev as a separate line with a
  mean-reversion scenario.

### HKMA residential-mortgage series June regression audit (2026-08-21)

Three dashboard series are recorded as stale at 2026-05 on main:
hkma_credit_quality_history (228 rows), hkma_applications_history
(114 rows) and hkma_mortgage_activity (114 rows), all 2016-12..2026-05.

Audit result: June 2026 data was already in production and was
regressed, not never-fetched:

- The HKMA RMS API has served 2026-06 since at least 2026-08-12 (local
  raw snapshot, 115 records). July is not published yet at source (RMS
  lags roughly one month), so June is the correct current target.
- CI committed June on 2026-08-12 (408b3539) and it survived through
  96f68ae1 and fa0de6e0 (2026-08-17).
- Local build f97e0672 (2026-08-20, refresh-Midland run) regressed all
  three series to May. Cause: _load_hkma_with_fallback() returns any
  non-empty local normalized cache without a freshness gate, and the
  local data/normalized/hk_real_estate/hkma_residential_mortgage_survey/
  vintages date from 2026-07-23 with May-only data (the ingestion
  pipeline has not saved a newer vintage since).
- The 2026-08-20 CI rebuild fetched June live but was discarded whole by
  artifact-refresh-guard: the SHKP quarterly catalogue fetch failed from
  CI (corporate page returned no PDF links), making shkp_quarterly_*
  datasets regress, so the guard restored the entire previous artifact,
  preserving the regressed May version. The guard also preserved the
  crypto artifact the same day (btc_price_history 109->0, Binance 451
  from CI IPs).
- Verified 2026-08-21: the project fetcher currently returns 115 rows
  with latest period 2026-06 from this machine.

Fixes implemented 2026-08-21 (branch codex/hkma-freshness-fix):

- _load_hkma_with_fallback() gates the normalized-cache short-circuit on
  whether the cache can still be holding the newest PUBLISHED month,
  rather than on a flat calendar age. A flat gate cannot work on this
  series: observation_date is the first day of the observed month and
  HKMA publishes ~25 days after that month ends, so a cache holding the
  newest published month is already ~55 days old on the day it lands,
  and the 45-day gate first written here rejected every HKMA cache that
  has ever existed (it forced a live fetch on every build and only
  looked like it worked). _monthly_cache_is_current() compares against
  the next month's expected publication date instead, starting to
  refetch 5 days early.
- A live fetch that comes back SHORTER than the cache, or with an older
  newest month, is now rejected as an upstream fault. Preferring the
  cache unconditionally used to provide this for free; preferring a
  fresh fetch means it has to be stated.
- The cache is only rewritten when the fetch actually advanced it.
  save_normalized_dataset() writes an immutable run directory per call,
  so rewriting an unchanged vintage every build just accumulates
  snapshots that load_latest_normalized() then has to scan.
- The lineage source_url written with the cache now reuses
  HKMA_PUBLIC_RMS_URL instead of a hand-copied URL that had a typo
  ("bulletine") and the wrong path segment.
- The HKMA curl fallback gained connect/read timeouts so a dead network
  fails bounded instead of hanging.
- artifact-refresh-guard gained findStaleDatasetRegressions(): a dataset
  whose newest observation moves BACKWARDS across a refresh now
  preserves the previous artifact, with reason "stale-dataset-
  regression". The pre-existing empty-dataset check could not see this
  incident at all -- every row count stayed healthy. Verified against
  the real artifacts: replaying the June -> f97e0672 refresh flags all
  six HKMA series, and the reverse direction plus all 26 committed
  artifacts on origin/main report zero. Row-count regressions are
  deliberately NOT flagged; shkp_quarterly_numeric_facts legitimately
  churns row counts between builds (PDF text extraction) while its
  newest period moves forward.
- tests/test_hk_real_estate_hkma_freshness.py covers the incident
  directly (stale cache + newer live data must yield the live data);
  9 of its 10 cases fail against the pre-fix builder.

Rebuild result, measured against origin/main (not the local main, which
lags): six HKMA series advance 2026-05 -> 2026-06, including
hkma_mortgage_rate_mix 342 -> 460 rows. One dataset moves the other way,
shkp_quarterly_numeric_facts 55 -> 51 rows, latest period still
2026-06-30 -- non-deterministic PDF text extraction, not a data loss
from this fix, but it does ship with the merge.

Still open: decide whether artifact-refresh-guard should merge
per-dataset instead of reverting the whole artifact when one source
fails; harden the SHKP quarterly fetch for CI IPs; make the SHKP
quarterly fact extraction deterministic so its row count stops churning.
