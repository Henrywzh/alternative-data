# Airline Pre-Event Locked Baseline (1H2026)

## Purpose

Freezes the six mainland carriers' pre-report forecast positions into one
point-in-time snapshot before the 1H2026 report cycle (2026-08-25 .. 08-31).
The whole airline research stack (unit economics, yield pressure, capacity
pipeline, residual-yield model, driver-based CASK, consensus reverse,
v3 earnings model) is designed to answer one question: *what will the
1H2026 print show, and is the market's expectation wrong?*  Without a
locked pre-event record, it is too easy to rationalise a miss after the
fact.  This file is the anchor for that discipline.

## Artifacts

- Data: `data/normalized/hk_transport/airline_pre_event_locked_baseline.csv`
- Module: `src/hk_transport/sources/airline_pre_event_locked_baseline.py`
- Tests: `tests/test_hk_transport_airline_pre_event_locked_baseline.py` (5 tests)
- Pipeline registry id: `airline_pre_event_locked_baseline` (kind `snapshot`, max age 15d)
- CLI: `run-airline-pre-event-locked-baseline` (add `--overwrite` only after
  deliberately reviewing a new pre-event vintage)

## What is locked per carrier (as of 2026-08-11)

| Company | Filing | H1 ASK YoY | H1 RPK YoY | H1 flat-yield revenue (RMB mn) | Fuel CASK | FY26 v3 base (USD mn) | FY26 consensus (USD mn) | Model vs consensus |
|---|---|---|---|---|---|---|---|---|
| Air China | 08-31 | +1.7% | +6.8% | 82,167 | 0.226 | 34.6 | 40.0 | -13.5% |
| China Eastern | 08-31 | +1.7% | +4.3% | 67,985 | 0.229 | 58.0 | 64.3 | -9.9% |
| China Southern | 08-29 | +4.1% | +3.4% | 89,868 | 0.225 | 50.9 | 104.8 | -51.4% |
| Hainan Airlines | 08-25 | -1.7% | +0.1% | 32,523 | 0.207 | 277.0 | 313.1 | -11.5% |
| Juneyao Airlines | 08-31 | +1.1% | +2.7% | 11,131 | 0.182 | 154.0 | 137.4 | +12.1% |
| Spring Airlines | 08-29 | +15.4% | +18.0% | 11,888 | 0.167 | 392.0 | 315.3 | +24.3% |

Notes:

- Southern's -51% gap reflects the v3 NCI / operating-contribution fix
  (previously a spurious +588%): the model is conservative but comparable.
- Juneyao's total CASK is blank because its annual report does not disclose
  the full cost decomposition (a known disclosure limit, not a parser miss);
  the fuel CASK leg is present.
- Fuel price at snapshot: 3.506 USD/gallon (jet fuel benchmark).
- H1 revenue is the flat-yield baseline (ASK x prior RASK) from the
  residual-yield model - deliberately the conservative prior, not the
  shrunk yield-adjusted version.

## Catalyst calendar alignment (Aug 10 - Aug 31)

| Date | Event | Feeds |
|---|---|---|
| 08-15 | Issuer monthly operating releases | ASK/RPK/LF -> revenue bridge (yield pressure) |
| 08-25 | Hainan 1H2026 report | validation playbook + post-earnings tracker |
| 08-29 | China Southern / Spring 1H2026 reports | same |
| 08-31 | Air China / Eastern / Juneyao 1H2026 reports | same |

The calendar rows carry the same `event -> KPI -> earnings -> company`
chain as the baseline columns, so a monthly-KPI surprise before 08-25 can
be mapped directly to the affected carrier's baseline row.

## Discipline rules

1. **Locked means locked.**  After a print, do not silently revise this
   file's numbers; corrections belong in the validation playbook
   (`airline_h1_2026_validation_playbook.csv`) and the post-earnings
   tracker (`airline_post_earnings_tracker.csv`).
2. Refresh cadence: normal pipeline runs read the existing lock and do not
   replace it.  If a materially better pre-event input arrives (e.g. a
   monthly release changes H1 ASK/RPK), explicitly run the CLI with
   `--overwrite` and preserve the previous file in the audit trail first.
3. After the last filing (08-31), the baseline becomes the "pre-event"
   reference for the tracker's beat/miss and T+1/T+5 return study.
