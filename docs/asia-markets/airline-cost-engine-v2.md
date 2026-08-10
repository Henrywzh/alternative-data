# Airline Cost Engine v2: Driver-Based CASK Backtest

Status: 2026-08-10.  First deliverable of the post-revenue roadmap.  The
cost engine replaces the single-period CASK driver forecast with a
walk-forward backtest over 2017-2025 FY operating cost, anchored on the
FY2025 cost-table decomposition (5/6 carriers full, Juneyao partial).

## Architecture

    CASK = Fuel + Staff + Airport + Maintenance + Depreciation + Other

- FY2025 decomposition (unit economics) provides the component structure;
  aggregate operating cost history (akshare discovery layer, FY only)
  provides the backtest target.  Pre-2025 rows are period-end vintages -
  calibration, not a strict executable PIT backtest (stated, not hidden).
- Fuel is mechanical: fuel unit cost x ASK x fuel-price ratio (EIA jet
  fuel, annual averages).  Intensity from the FY2025 anchor.
- Non-fuel components are grown by their labelled drivers: ASK for
  staff/airport/maintenance/other (no free flight-count or block-hours
  source), fleet for depreciation.
- Company shrinkage uses the same anomaly lambda as v4 revenue
  (lambda_min 0.5 tuned by sweep).

## Ablation (47 rows, 6 carriers x 2018-2025)

| Layer | Cost MAE | Bias | Regime-year MAE (2020-23) |
|---|---|---|---|
| flat_ask_cost (baseline) | 18.76% | +3.29% | 32.43% |
| + fuel mechanical | 16.74% | +5.02% | 30.64% |
| + non-fuel drivers | 17.35% | -15.50% | 24.43% |
| + company shrink | 13.10% | -4.77% | 22.92% |
| + full CASK | **11.64%** | -3.04% | **20.42%** |

Full CASK cuts cost MAE by 38% vs baseline and regime-year MAE by 37%.
Largest single contributor is company shrinkage toward the FY2025 anchor
structure; fuel mechanical adds ~2pp; the non-fuel driver layer alone has
a large negative bias (-15.5%) because the FY2025 anchor applied backwards
overstates pre-2025 cost intensity - this is why the shrinkage layer is
needed, and why the full model (not the driver layer alone) is the
production form.

## EBIT error decomposition (eps_EBIT = eps_Revenue - eps_Cost)

Per historical row: revenue error (v4 overlay stage) vs cost error (full
CASK), and the directional EBIT error contribution.

- Mean |EBIT directional error| by carrier: 9.7-24.1% (Hainan worst).
- Revenue-cost error correlation: Air China 0.68, Southern 0.47, others
  ~0.  For Air China and Southern, revenue and cost errors move together
  (partial offset in EBIT terms); for the rest they are independent, so
  every point of cost-MAE improvement is a direct point of EBIT accuracy.
- Conclusion: cost is now the binding constraint on earnings accuracy, as
  the roadmap predicted (revenue normal-year MAE ~3.3% vs cost ~11.6%).

## Hedge diagnostic (cross-validated, honest)

Fuel intensity is calibrated on FY2025; applying it to 1H2025 (different
price, different ASK) gives an independent cross-check.  Implied hedge
residual (actual - mechanical) on 1H2025: **all five carriers positive,
+0.19% to +0.80%** - small, same-sign, no large hedge gains/losses.

Conclusion: with only two points per carrier persistence cannot be
estimated, but the uniformly small residual supports **shrinking any hedge
adjustment toward zero** (do not forecast a hedge P&L from two points).

## Files

- Module: `src/hk_transport/sources/airline_cost_engine_v2.py`
- Backtest: `data/normalized/hk_transport/airline_cost_engine_v2.csv`
- Ablation: `data/normalized/hk_transport/airline_cost_engine_v2_ablation.csv`
- EBIT decomposition: `data/normalized/hk_transport/airline_cost_engine_v2_ebit_decomposition.csv`
- Hedge diagnostic: `data/normalized/hk_transport/airline_cost_engine_v2_hedge_diagnostic.csv`
- Tests: `tests/test_hk_transport_airline_cost_engine_v2.py` (6 tests)
- CLI: `run-airline-cost-engine-v2`

## Next (per roadmap)

1. Consensus reverse engineering - audit the Spring +64.7% surprise with
   the four sanity checks (annualisation, share count, parent vs
   attributable, one-offs) and build the implied RASK/CASK surface.
2. Valuation (P/E, P/B, EV/EBITDAR) - Street vs own multiples.
3. Catalyst underwriting + thesis scoreboard.
