# SHKP forecast / backtest research baseline

**Status:** research-only baseline; not investment advice and not a full
point-in-time earnings-vintage backtest.

**Latest run:** `shkp-forecast-backtest-382d36e8-f8b0-4034-b25d-9bee367ad3e1`

**Input model run:**
`shkp-financial-model-d7109705-f911-4f89-9d5a-5d2159df6e62`

## What is safe to use now

The command

```bash
python -m src.hk_real_estate.cli run-shkp-forecast-backtest
```

creates three run-scoped datasets:

| Dataset | Rows | Interpretation |
|---|---:|---|
| `shkp_forecast_scenarios` | 51 | Broker min/median/max ranges and provider consensus low/mean/high values for FY2026–FY2028 EPS, net profit, dividend and target price. Current snapshot only. |
| `shkp_release_event_study` | 8 | Descriptive +1/+5/+20 trading-day adjusted-close returns around eight releases with curated exact HKEX publication timestamps. |
| `shkp_forecast_backtest_coverage` | 1 | Input run ID, coverage, and explicit research-only/PIT caveats. |

The broker and consensus layers are not averaged together. Broker ranges use
the min/median/max of the current broker batch; consensus rows retain the
provider's low/mean/high statistics. This avoids hiding different aggregation
semantics behind one false precision number.

The event study treats the curated releases as after-close HKT events. The
release-date close is the event reference price and the first forward return is
the next trading session. All eight events have a complete 20-trading-day
window in the current 2010-01-04–2026-08-05 price history.

## Current observed examples

The current consensus snapshot (2026-07-26) gives the following base values:

| Fiscal year | EPS (HKD) | Dividend (HKD/share) |
|---:|---:|---:|
| FY2026 | 7.88 | 3.90 |
| FY2027 | 8.65 | 4.15 |
| FY2028 | 9.08 | 4.33 |

These are market expectations, not SHKP guidance or our own validated
forecast. The corresponding consensus target-price range for FY2026 is
HKD121–168, with a mean of HKD146.68.

The eight-event sample is descriptive and mixed: the +1-day return ranges from
−9.5% to +7.1%, and the +20-day return ranges from −5.1% to +15.0%. This is too
small and too confounded to support a causal claim or a trading rule.

## Hard limitations that remain

- The 952 sibling financial-fact rows have fiscal periods but no original
  announcement dates; `available_at` is fetch-time metadata.
- Consensus has one snapshot date and missing `estimate_period_end` values;
  broker forecast dates were fetched in one batch rather than as historical
  vintages.
- Yahoo adjusted-close history is a vendor replay, not an exchange-native PIT
  price tape.
- All 13 priority SHKP phases remain blocked by the ownership gate. Project
  activity is not used as attributable sales in this baseline.
- The completed-property table is exposure metadata, not rent/NOI, valuation or
  recognized revenue.

Therefore this artifact is a reproducible scenario/event-study control layer,
not the final earnings forecast or an investable long/short backtest. The next
upgrade is an append-only dated filing/consensus vintage store, followed by a
project-level economics layer once phase-specific ownership intervals are
reviewed.
