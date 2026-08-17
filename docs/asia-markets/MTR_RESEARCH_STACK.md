# MTR Research Stack — Handoff & Status (2026-08-09)

End-to-end MTR (66.HK) quantamental research stack: from official/free
alternative data to FY26 property-profit and EPS ranges vs Street.

## 1. Data layer (all verified sources)

| Dataset | Source | Coverage | Key fields |
|---|---|---|---|
| MTR monthly patronage | mtr.com.hk investor page | 2000-01..2026-06 (318m) | domestic / cross-boundary / HSR / AEL / LRT+bus |
| ImmD daily boundary traffic | immd.gov.hk opendata CSV | 2021-01..daily T+1 | 17 control points (HSR West Kowloon, Lo Wu, LMC Spur, Airport...) |
| MTR historical earnings bridge | official results PDFs 2010-2025 | 16 FYs annual | segment revenue, recurrent post-tax, HK prop-dev post-tax, underlying, NPAT, EPS, DPS; identity underlying=recurrent+propdev holds 2014-2025 |
| MTR property master | official results 2021-2025 + SHKP repo data | 19 packages | recognition years, tender years, SRPE crosswalk |
| SRPE transaction registers | srpe.gov.hk statutory PDFs | 9,819 deals / 13 phases | date_of_pasp, price, unit; cancelled flagged |
| BD lifecycle history | Buildings Dept Md51-56 digests | 2005-01..2026-05 (17,517 rows) | OP permits, consent-to-commence, units |
| Consensus | yfinance 0066.HK | current | FY26E EPS 2.52 (7 analysts), revenue 55.2bn |

## 2. Model chain

1. **Farebox nowcast** — `scripts/mtr_farebox_revenue_backtest.py`
   - FY2025 practical forward validation: forecast 23,696 vs reported 23,595 = **+0.43%**
   - 2019-2023 structural replay MAPE: 4.06% (Ridge L2 residual; not chronological OOS)
   - H1 backtest: official 2017-2025 interim actuals; 2019-2023 H1 structural replay MAPE 5.99%; FY2025 H1 practical forward validation +0.34%; FY2026 H1 forecast 11,976.7 HK$m
   - Strict chronological track: `scripts/build_mtr_walk_forward_oos.py`; FY MAPE 9.32% and H1 MAPE 8.10% on prior-period-yield practical OOS rows, with forecast origin, information cutoff and input bundle recorded
   - Monthly companion is forecast-only because MTR publishes no monthly transport-operations revenue actuals; it is not a scored monthly OOS series
2. **Timing Engine** — `scripts/mtr_timing_engine.py`
   - OP -> recognition: same calendar year (median lag ~1 month, 4 strong cases)
   - H1/H2 split from interim reports (2022H1 7,747 / 2024H2 8,525 / 2025H1 5,542...)
3. **Magnitude Engine** — `scripts/mtr_magnitude_engine.py`
   - registered sales value per phase (cancelled excluded)
   - implied profit/sales ratio anchor: G2022H1 **17-24%** (upper bound 24.5%)
4. **Expected Profit V1** — `scripts/mtr_property_expected_profit.py`
   - E[profit] = P(recognition) x eligible value (PIT: as of FY25 year end) x 15/20/25%
5. **EPS Bridge** — `scripts/mtr_property_eps_bridge.py`
   - FY26E reported EPS 1.44 / 1.71 / 2.01 (bear/base/bull) vs Street 2.52

## 3. Current FY26 output (2026-08-09)

```
Property expected profit (post-tax): bear 4,609 / base 6,330 / bull 8,145 HK$m
  vs FY25 actual 11,084 HK$m
Reported EPS (our): 1.44 / 1.71 / 2.01 vs Street 2.52
  -> -43% / -32% / -20%  (Street implies +7% growth; our data implies a
     property-profit reset year after the FY25 super-cycle)
```

Assumptions (explicit):
- FY26E recurrent post-tax = FY25 5,653 x 1.03
- FY26E IP fair-value movement (post-tax) = -1,500
- P(recognition) values are rule-based from official FY25-outlook naming
- Only P6 and Yau Tong VB remain ASSUMED-scenario (no SRPE data yet)
- LP13 mapping to SRPE 10486 is SUSPECTED (not confirmed)

## 4. Key empirical findings

1. OP issuance and MTR property-profit recognition fall in the SAME calendar
   year (晉環 OP 2022-04 -> 2022H1; 瑜一 OP 2024-11 -> 2025H1; 凱柏峰 OP
   2024-12 -> 2024H2 bulk).
2. 凱柏峰 I/II/III registered deals (1,961) cross-check the BD OP 2024-12
   units (1,880) — independent datasets agree.
3. P5 滶晨 sold 12.2bn in its first 7 months (2025-05..12) — fast absorption.
4. LP12 海瑅灣 had ZERO registered deals before FY25 year end; its FY25
   recognition came via OP 2025-10 handover, not sales — the FY26 residual
   will draw on FY26 sales (87bn registered by 2026-08).
5. EPS sensitivity ranking: property recognition timing is the dominant EPS
   variable (one package ~ ±0.45 EPS = ±18% of consensus), vs farebox +1%
   (+1.5%), HIBOR +100bp (-3.4%), Mainland +10% (+0.3%).

## 5. Remaining uncertainties / next steps

- [ ] Confirm LP13 = SRPE 10486 (official name/link check)
- [ ] P6 (presale consent in progress) and Yau Tong VB: no SRPE data; find
      public project scale to replace ASSUMED values
- [ ] Sharpen P(recognition) with transaction-velocity (months since last
      deal, sell-out pace) — first pass: P5 87% absorbed in 7 months
- [ ] Street property-profit decomposition: consensus 2.52 EPS implies FY26
      property profit much higher than our base — verify via sell-side notes
- [x] HK transport H1 history backtest: `mtr_farebox_revenue_h1_backtest.csv` plus official actuals table and H1 chart
- [ ] HK transport FY26 full-year nowcast refresh (H2 2026 as data lands)
- [ ] 2026 interim results (Aug 2026): validate H1 property recognition
      against our timing probabilities (the first true forward test)

## 6. Repo map

- scripts: mtr_farebox_revenue_backtest.py, mtr_consensus_bridge.py,
  mtr_srpe_transactions.py, mtr_timing_engine.py, mtr_magnitude_engine.py,
  mtr_property_expected_profit.py, mtr_property_eps_bridge.py
- src/hk_transport/sources/: mtr_patronage.py, mtr_historical_earnings_bridge.py,
  mtr_property_project_master.py
- data/normalized/hk_transport/: mtr_* CSVs
- docs: MTR_EARNINGS_ENGINE_SPEC.md (architecture), MTR_PROPERTY_ENGINE_TODO.md
  (field-level gaps), MTR_RESEARCH_STACK.md (this file)
