# Stale Accuracy Claims Audit (2026-08-13)

Status: audit only. This document and the companion
`data/registries/stale_accuracy_claims_audit.csv` are the entire output of
this pass. **No other document was edited.** Every number below is a
finding, not a fix — the corresponding docs still say what they said before
this audit; a human decides what to change and when.

## What changed and why

A new unified KPI backtest engine (`scripts/run_backtest_engine.py`,
documented in `docs/asia-markets/unified-kpi-backtest-v1.md`) re-graded every
historical MTR, Airlines and SHKP forecast result against a stricter,
consistent methodology. Three things moved under docs that had already
quoted specific accuracy numbers:

1. **MTR's farebox backtest was never out-of-sample.**
   `scripts/mtr_farebox_revenue_backtest.py` calibrates its per-passenger
   yields from **FY2024 disclosed revenue**, then deflates backwards through
   the FAM schedule for 2017–2023. Every one of those historical rows is
   graded `C_structural_replay` in the new registry, not out-of-sample. Only
   FY2025 and H1 2025 are genuine forward (`B_practical_pit`) observations —
   **n=1 each.**
2. **`mtr_ridge_residual_v1` is not a distinct model outside 2019–2023.**
   Its residual adjustment is zero for 22 of 27 rows, so outside the
   structural-replay window its prediction equals the physics model's.
3. **Pooled Airlines metrics hid per-company performance.** Pooled FY
   revenue skill-vs-baseline is 0.7850; per-company it ranges from **Spring
   Airlines 0.4877** to **Juneyao Airlines 0.6902** — the two names the pair
   thesis rests on — and other targets are worse: `flat_ask_residual_v1` on
   `attributable_profit` scores skill **-1.94 to -0.19** (every carrier worse
   than the naive baseline), and `flat_ask_v1` on `operating_cost` scores
   **-1.55 to +0.05** (baseline wins for 5 of 6 carriers).
4. **The current headline set is empty.** Under a sample guard that counts
   distinct target periods rather than pooled rows, `headline_eligible=True`
   appears on **zero of 263 rows** in `asia_backtest_metrics.csv`. Every MTR
   and Airlines contract is `insufficient_sample`.

A fifth pattern turned up during this audit that was not in the original
brief: **the SHKP commercial-rental "walk-forward OOS" claim (1.62% MAPE vs
3.85% naive) is also contradicted by the new registry.**
`data/registries/asia_backtest_target_registry.csv` classifies
`shkp_commercial_backtest:FY:hk_rental_revenue:distributed_lag` as
`pit_grade=C_structural_replay`, `candidate_headline_eligible=False` — the
exact same "not actually OOS" problem as MTR's farebox backtest, but for a
figure four separate documents call "OOS," "validated" and "high-confidence."

Ground truth for all verdicts below is
`data/registries/asia_backtest_metrics.csv`,
`data/registries/asia_backtest_target_registry.csv`, and
`docs/asia-markets/unified-kpi-backtest-v1.md`.

## How to read this report

Each claim in `data/registries/stale_accuracy_claims_audit.csv` carries a
verdict:

- **invalidated** — the claim's framing is contradicted by the current
  ground truth (usually: called "OOS"/"validated"/"headline" when the
  registry says `C_structural_replay` / `insufficient_sample` /
  `candidate_headline_eligible=False`).
- **needs_scope** — the number itself is traceable and arithmetically fine,
  but the sentence is missing a qualifier the new engine now requires:
  sample size, PIT grade, or an entity/company breakdown where a pooled
  number is quoted.
- **still_valid** — checked against the registry and found accurate as
  written. Several docs already anticipated this migration and wrote
  careful language; those get credit here rather than being re-flagged.
- **unverifiable** — the underlying model/target is not (yet) present in
  the unified engine's artifacts, so no verdict can be traced to ground
  truth either way.

45 claims were logged. **7 invalidated, 19 needs_scope, 17 still_valid, 2
unverifiable.**

## Group 1 — SHKP commercial rental "OOS" claim (new finding, highest severity)

This is the most clear-cut invalidation in the audit: four documents call
the same number "OOS," "validated," or "high-confidence," and the ground
truth explicitly disagrees.

| File | Line(s) | Claim | Verdict |
|---|---|---|---|
| `SHKP_FULL_BACKTEST_REPORT.md` | 15 | "FY HK rental revenue \| 10 \| Distributed lag \| 1.62% \| **Walk-forward OOS**; scenario-grade elasticities" | invalidated |
| `SHKP_EARNINGS_MODEL_V1_STATUS.md` | 76–77 | "Commercial: **OOS MAPE** 1.62% vs naive 3.85% ... **strong, self-contained module validation**" | invalidated |
| `SHKP_EARNINGS_MODEL_V1_STATUS.md` | 108 | "Commercial is a **validated**, low-volatility earnings stream: RVD distributed-lag cuts **OOS MAPE** 3.85% -> 1.62%; **high-confidence module**." | invalidated |
| `SHKP_EARNINGS_MODEL_V1_STATUS.md` | 120 | Confidence table: "HK commercial \| 16Y + **OOS backtest** \| HIGH \| RVD lag stability" | invalidated |
| `PROJECT_STATUS.md` | 1485–1490 | "**Walk-forward OOS backtest** (FY2020/21-FY2024/25...)" — superseded 10-year figures, same label | invalidated |
| `PROJECT_STATUS.md` | 1532–1540 | "**Walk-forward OOS backtest** (FY2016-2025, 10 years)... confirming incremental predictive power" | invalidated |
| `PROJECT_STATUS.md` | 1765–1766 | "component validation... commercial MAPE 1.62% vs 3.85% naive) = **strong**" (contrast: same sentence correctly downgrades the skeleton/recent-regime legs) | needs_scope |

**Ground truth:** `asia_backtest_target_registry.csv` row
`shkp_commercial_backtest:FY:hk_rental_revenue:distributed_lag` has
`pit_grade=C_structural_replay` and `candidate_headline_eligible=False`.
**Honest current statement:** "The RVD distributed-lag commercial rental
model beats a naive same-period baseline on a 10-year retrospective replay
(1.62% vs 3.85% MAPE), but this replay is classified structural, not
out-of-sample, in the current registry — treat the improvement as evidence
the RVD signal correlates with rental revenue historically, not as a
forward-validated edge." The FY underlying-profit ("vintage margin replay,"
6.37% MAE) and skeleton-backtest figures in the same documents are **already
correctly labeled** and are not part of this finding — `SHKP_EARNINGS_MODEL_V1_STATUS.md`
itself applies the right discipline to those two legs in the same
paragraph where it fails to apply it to the commercial leg.

## Group 2 — MTR: mostly already fixed, two real gaps

This was expected to be the worst cluster going in, but MTR's canonical docs
turned out to already carry the "structural replay, not OOS" language for
the 4.78%/4.06% figures — likely from a prior remediation pass on
2026-08-11/12. `MTR_MODELLING_REPORT.md` §4.3 is the gold standard in the
whole corpus: it states the exact sample sizes (6 FY periods, 8 H1 periods)
next to the MAPE figures. Two real gaps remain:

| Issue | Where | Verdict |
|---|---|---|
| **n=1 forward-validation figures (+0.43% FY, +0.34% H1) presented without disclosing n=1**, and in `MTR_EARNINGS_ENGINE_SPEC.md` under a header literally titled "Validated Revenue Baselines" | `MTR_EARNINGS_ENGINE_SPEC.md:8-11`, `MTR_RESEARCH_STACK.md:21,23`, `MTR_MODELLING_REPORT.md:12,13,206` | needs_scope |
| **Walk-forward FY/H1 MAPE (9.32%/8.10%) below the new 10-observation headline guard** (n=6, n=8), not flagged as `insufficient_sample` | `MTR_EARNINGS_ENGINE_SPEC.md:16-21`, `MTR_RESEARCH_STACK.md:24`, `DATA_CATALOG.md:178` | needs_scope |
| **`MTR_LONG_SHORT_THESIS.md`'s data-maturity table rates the farebox nowcast "成熟" (mature)** without disclosing the structural-replay/n=1 status underneath that rating — this is the actual long/short thesis document | `MTR_LONG_SHORT_THESIS.md:38` | needs_scope |
| 4.78%/4.06% structural-replay MAPE, correctly labeled "not chronological OOS" | `MTR_EARNINGS_ENGINE_SPEC.md:12-14`, `MTR_RESEARCH_STACK.md:22`, `MTR_MODELLING_REPORT.md:12,13,66,68,94,97`, `DATA_CATALOG.md:178,180`, `PROJECT_STATUS.md:140-145` | **still_valid** |

**Honest current statement for the n=1 figures:** "FY2025 farebox revenue
came in 0.43% above the physics-model forecast and H1 2025 came in 0.34%
above — each a single observation, not a track record. The model has not
yet had a second forward-validation year." `MTR_THEISIS_A_CROSS_BOUNDARY.md`
and `MTR_THEISIS_B_COMMERCIAL_MIX.md` were also scanned and contain no
quantitative accuracy claims at all.

## Group 3 — Airlines pair thesis and backtest docs

The pair-thesis document itself (`airline-pair-thesis-review.md`) is
already reasonably scoped — its MAE figures are per-company (Spring) with
sample size stated in-line, and it explicitly says the pre-1H2025 panel
"lacks a complete issuer announcement-date tape, so the backtest is
calibration evidence rather than a strict PIT trading backtest." The gaps
that remain are about the new engine's stricter sample guard and about the
word "headline" itself:

| Issue | Where | Verdict |
|---|---|---|
| **"Spring's headline MAE (9.6% H1)"** — the word "headline" is now specifically false: `headline_eligible=True` on zero rows in the entire engine | `airline-history-backtest-view.md:74` | **invalidated** |
| Per-company MAE (n=9) stated without noting n=9 < 10 headline guard | `airline-pair-thesis-review.md:44-46`, `airline-backtest-audit-and-improvements.md:56-68` | needs_scope |
| Per-entity figure (Spring) compared in the same sentence to a pooled figure (walk-forward yield/mix) without labeling which is which | `airline-pair-thesis-review.md:77-79` | needs_scope |
| v4 model ablation (MAE 9.12%→7.47%, direction accuracy 98.6%→100.0%) pooled across 6 carriers; `unified-kpi-backtest-v1.md` classifies Airlines v4 as `C_structural_replay` and this is not disclosed here | `airline-earnings-model-v4.md:27-34`, `PROJECT_STATUS.md:521-524` | needs_scope |
| Pooled "aggregate cost MAE ~13.7%" — the unified engine's `flat_ask_v1`/`operating_cost` skill is negative for 5 of 6 carriers (-1.55 to +0.05), meaning the naive baseline usually wins; this document's framing ("weakest part of the stack") is directionally consistent but the aggregate number hides how bad it is per carrier | `airline-cask-driver-model.md:4` | needs_scope |
| `airline_cost_engine_v2` (company_shrink 13.43% Cost MAE) is a different model not yet present in `asia_backtest_metrics.csv` at all | `airline-cost-engine-v2.md:24-32` | **unverifiable** |
| Pooled "direction accuracy ~65-72%" for the residual-profit diagnostic across the six-company panel; the magnitude-based version of the same model (`flat_ask_residual_v1` on `attributable_profit`) scores skill -1.94 to -0.19 per carrier in the new engine — worse than baseline everywhere — and this is not surfaced next to the directional number | `PROJECT_STATUS.md:417-419`, `DATA_CATALOG.md:1194-1199` | needs_scope |
| Beat-probability Monte Carlo (per-company, good) draws on the same n=9 historical MAE samples flagged above; propagated small-sample uncertainty undisclosed | `airline-decision-eval.md:7-30` | needs_scope |

Several Airlines documents already do this correctly and needed no
correction: `airline-pair-spread-model.md:21` (discloses n=9 in-line),
`airline-residual-yield-model.md:27-33` (per-company table, explicitly
labeled in-sample), `airline-earnings-model-v4-live.md:66` (an honestly
reported 0/5 negative result with an explicit non-adoption decision), and
`airline-history-backtest-view.md`'s regime-MAE table (reports per-carrier
ranges, not a single pooled figure).

**Honest current statement for the pooled figures:** "Pooled FY revenue
skill-vs-baseline across six carriers is 0.785, but the pair thesis rests on
two names whose individual skill differs by 20 points: Spring 0.49, Juneyao
0.69. Neither the pooled nor the per-company number currently clears the
engine's headline-eligibility bar (independent-period + PIT + baseline-
coverage gates), so none of these figures should be quoted as a finished
accuracy result — they are the best currently-available research evidence,
not a track record."

## Group 4 — correctly scoped already (no action implied)

These were checked and found accurate as written; listed so a reader does
not have to re-derive that they are fine:

- `MTR_MODELLING_REPORT.md` §4.3 (states n=6/n=8 next to MAPE — the model
  the rest of the corpus should follow)
- `MTR_EARNINGS_ENGINE_SPEC.md:12-14`, `MTR_RESEARCH_STACK.md:22`,
  `DATA_CATALOG.md:178,180`, `PROJECT_STATUS.md:140-145` (4.78%/4.06%
  labeled "structural replay," "not OOS")
- `SHKP_FULL_BACKTEST_REPORT.md:14`, `SHKP_SKELETON_BACKTEST_V2_REPORT.md:6-15,48`,
  `SHKP_EARNINGS_MODEL_V1_STATUS.md:79-92`, `PROJECT_STATUS.md:1787-1819`
  (underlying-profit skeleton MAE correctly labeled "not strict PIT/OOS")
- `airline-earnings-model-v4.md:40-43` (self-discloses `lambda_min=0.5` was
  not independently OOS-tuned)
- `airline-pair-spread-model.md:21`, `airline-residual-yield-model.md:27-33`,
  `airline-earnings-model-v4-live.md:66`, `airline-history-backtest-view.md:62-70`

## Unverifiable claims

Two claims could not be traced to any current artifact:

1. `airline-cost-engine-v2.md:24-32` — `airline_cost_engine_v2` (the
   driver-based CASK model, "company_shrink" 13.43% production MAE) has no
   corresponding rows in `asia_backtest_metrics.csv`; only `flat_ask_v1` and
   the same-period-last-year baseline are tracked for `operating_cost`
   today. Would need this model migrated into the unified engine before it
   can be graded.
2. `SHKP_H1_BACKTEST_REPORT.md:8` — the group-revenue H1-to-FY recognition
   backtest (2×H1 baseline mean APE 14.2%) is not one of the three SHKP
   targets the unified engine currently tracks
   (`contract_activity_proxy`, `underlying_profit`, `hk_rental_revenue`).
   The document's own framing is already appropriately cautious
   ("recognition diagnostic, not a finished earnings forecast"), so this is
   a scope gap in the engine rather than a stale claim in the doc.

## Scope notes and exclusions

- **Numbered duplicates.** Of the ~55 numbered copies under
  `docs/asia-markets/`, none of the files carrying an `invalidated` or
  `needs_scope` claim in this audit have a numbered twin — `MTR_*`,
  `PROJECT_STATUS.md`, `DATA_CATALOG.md`, `SHKP_*`, and every
  `airline-*.md` file cited above exist only as a single canonical copy per
  `data/registries/asia_backtest_document_registry.csv`. The one exception,
  `airline-pair-thesis-review.md`, does have a numbered copy
  (`airline-pair-thesis-review 2.md`), but it is an earlier draft with
  materially different content — it does not contain the specific MAE
  figures flagged above, so no parallel CSV rows were created for it.
- **Excluded as non-claims.** `NEWS_SOURCES_AND_NEWS_BACKTESTING*.md`,
  `HSCI_PIT_RECONCILIATION_AUDIT*.md`, `HKEX_EVENT_HISTORY_AUDIT*.md`,
  `hk-airlines-data-quality-audit*.md`, `hk-airlines-research-pack-manifest*.md`,
  `hk-airlines-long-short-data-plan*.md`, `hk-airlines-sector-map*.md`,
  `REAL_ESTATE_SHKP_FINANCIAL_MODEL*.md`,
  `REAL_ESTATE_SHKP_FORECAST_BACKTEST*.md`, `OPERATING_MANUAL.md`,
  `v1-hk-equities.md`, `airline-free-data-source-research.md`, and
  `airline-post-earnings-tracker.md` were all grep-matched on the search
  shapes (MAPE/backtest/OOS/etc.) but contain only methodology language
  ("not a strategy backtest," "use for trend/model calibration, not strict
  PIT backtesting") with no attached numeric accuracy figure to verify —
  they are already correctly hedged and were not logged as individual CSV
  rows.
- **`unified-kpi-backtest-v1.md` itself** is the ground-truth source
  document for this audit and was read in full but not logged as a claim —
  it defines the methodology rather than reporting a result against it.
- **`REAL_ESTATE_SIGNALS_TODO.md:415-439`** was checked and is already
  well-hedged ("Validation is deliberately directional, not an accuracy
  score... These are coverage/timing diagnostics, not accuracy scores") —
  excluded as a non-claim for the same reason as the methodology docs above.

## Files

- `data/registries/stale_accuracy_claims_audit.csv` — the full 45-row
  machine-readable log (file path, line number, verbatim claim,
  canonical/copy status, verdict, reason, and where a corrected figure
  would come from).
