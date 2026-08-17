# Airline Post-Earnings Tracking Ledger (Priority 8)

## Purpose

The final layer that turns the airline stack from an earnings-forecast
system into a learning loop.  For every carrier / report period the ledger
records the full event chain:

```
pre-event model & consensus
  -> actual reported result
  -> market reaction (T0 / T+1 / T+5 returns)
  -> analyst revision signal
  -> validation status
```

This is what makes the project answer "what kind of earnings surprise
actually matters" - after several prints, the ledger supports a
price-reaction study (surprise size vs T+1/T+5 returns, revision
persistence) instead of one-off backtests.

## Artifacts

- Data: `data/normalized/hk_transport/airline_post_earnings_tracker.csv`
- Module: `src/hk_transport/sources/airline_post_earnings_tracker.py`
- Tests: `tests/test_hk_transport_airline_post_earnings_tracker.py` (6 tests)
- Pipeline registry id: `airline_post_earnings_tracker` (kind `measure`, max age 30d)
- CLI: `run-airline-post-earnings-tracker`

## Current contents (2026-08-11)

7 rows: six mainland carriers (`awaiting_report`) + Cathay Pacific (`filled`).

Cathay is the first filled example - its 1H2026 print (announced
2026-08-05) doubles as a live test of the market-reaction machinery:

| Field | Value |
|---|---|
| Actual 1H2026 attributable profit | 6,243 HKD mn |
| H1 share of FY2026 consensus | 58.0% |
| T0 return (announcement-day close vs prior close) | +2.78% |
| T+1 return | +2.30% |
| T+5 return | pending (not elapsed in price capture) |

The six mainland rows also carry the locked v4 fields, including H1 revenue,
H1 EPS, simple x2 annualised surprise and seasonality-adjusted surprise. For
example, the current Spring/Juneyao seasonality-adjusted values are +67.5%
and +58.1%, respectively. These are pre-event model fields, not actual
post-print surprises.

## Design rules (honesty constraints)

1. **No direct H1-vs-FY beat/miss.**  The H1 actual is compared with the
   FY2026 consensus/model only via explicit `h1_share_of_*` ratios - a
   seasonal-adjustment trap avoided by construction.
2. **Net-income-leg transparency.**  `model_vs_consensus_pct` inherits the
   v3 `net_income_leg` choice.  For NCI-forward legs (e.g. China Southern,
   `share_based_nci_forward`, minority share ~68%) the model line is total
   profit, not attributable net income, and must not be read as a
   consensus beat/miss.  The leg is carried in its own column.
3. **Return horizon honesty.**  T+5 is `None` until the fifth trading day
   has elapsed; the status distinguishes `complete` / `t5_pending` /
   `no_price_history` (mainland A-share tickers are not yet in the yfinance
   layer).
4. **Revision signal caveat.**  The analyst revision snapshot is the 30d
   window ending at the expectation-bridge snapshot date and may straddle
   the announcement; it is labelled with its snapshot date rather than
   claimed as a strict post-print revision.

## Workflow after each 1H2026 / FY2026 print

1. Refresh the expectation bridge (actuals land there first).
2. Re-run `run-airline-post-earnings-tracker`; fill any remaining actual
   columns from the filing.
3. After five trading days, re-run to capture T+5 (status flips to
   `complete`).
4. Re-run after ~30 days for the post-print revision signal.
5. Log the learning note: what did the model miss, and did the market
   react to the surprise or to something else (guidance, capex, FX)?
