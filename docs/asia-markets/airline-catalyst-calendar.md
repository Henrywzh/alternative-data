# Airline Catalyst & Risk Calendar (Priority 7)

## Purpose

Moves the airline research from backward-looking nowcasting to forward
investment research. A dated calendar of events over the next 3-12 months
that can move airline earnings, each mapped to the KPI it hits and the
earnings line it feeds:

```
Event -> KPI -> Earnings -> Company
```

This is the natural bridge between the forecast stack (unit economics,
yield pressure, capacity pipeline, CASK driver model, consensus reverse)
and the H1-2026 validation playbook: every earnings-report row in the
calendar is a scheduled test of the pre-event forecast.

## Artifacts

- Data: `data/normalized/hk_transport/airline_catalyst_calendar.csv` (32 events)
- Module: `src/hk_transport/sources/airline_catalyst_calendar.py`
- Tests: `tests/test_hk_transport_airline_catalyst_calendar.py` (3 tests)
- Pipeline registry id: `airline_catalyst_calendar` (kind `event`, max age 45d)
- CLI: `run-airline-catalyst-calendar`

## Event categories (as of 2026-08-10)

| Category | Count | Window | Source |
|---|---|---|---|
| earnings_report | 5 | 2026-08-25 .. 08-31 (1H2026) | filing calendar |
| monthly_kpi | 1 (recurring) | monthly from 2026-08-15 | issuer operating releases |
| fuel | 1 (recurring) | monthly from 2026-09-01 | jet fuel benchmark + surcharge reviews |
| holiday_demand | 3 | Mid-Autumn 09-25, Golden Week 10-01, Spring Festival 2027-01-25 | official calendar |
| seasonal_schedule | 1 | 2026-10-25 (CAAC W26/27) | CAAC seasonal schedule |
| route_launch | 3 | 2026-03-29 domestic trunk routes (Spring 4 / Juneyao 2 / Southern 2) | CAAC route licence events |
| fleet_delivery | 15 | rolling 12/24/36-month horizons per carrier | capacity pipeline |

## Key links to existing layers

- **Earnings reports** (Aug 25-31 2026): feed `airline_h1_2026_validation_playbook`
  (pre-event EPS forecast vs consensus vs actual vs T+1/T+5 return vs analyst revisions)
- **Fuel reviews** (monthly): feed `airline_cask_driver_model` - 2026 fuel cost
  +66% is currently the single largest margin risk
- **Holiday demand** (Golden Week Oct 1, Spring Festival Jan 2027): feed
  `airline_yield_pressure_index` (RPK-ASK gap -> yield pressure)
- **Route launches / seasonal schedule**: feed `airline_capacity_pipeline`
  (forward ASK)
- **Monthly issuer releases** (Aug 15 onwards): monthly KPI cadence for the
  H1-2026 revenue bridge (RPK-ASK gap -> yield pressure)

## Usage

1. Refresh monthly: `python -m src.hk_transport.cli run-airline-catalyst-calendar`
2. Before any catalyst (esp. 1H2026 reports Aug 25-31):
   - update the pre-event forecast (v3 base + residual yield + CASK driver)
   - record consensus reverse-engineered assumptions
   - freeze the trade thesis (direction, invalidation rules)
3. After each earnings print: fill `airline_h1_2026_validation_playbook`
   with actual vs pre-event forecast vs consensus, plus T+1/T+5 returns.

## Honest limitations

- Windows are scheduled/projected, not guaranteed (filing dates can slip,
  CAAC schedule dates are seasonal conventions).
- The earnings link is a direction hypothesis, not a forecast magnitude.
- Fleet-delivery events use observed trailing-12m net-add pace as the
  capacity expectation; delivery delays are common (Juneyao's trailing-12m
  net add is 0, so its delivery event is flagged `low_no_recent_delivery_pace`).
