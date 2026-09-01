# Airline Future Capacity Pipeline

Status: 2026-08-10.  This layer answers the forward question behind the pair
thesis: why will Spring keep outperforming Juneyao after the H1-2026 print?
It builds dated future events per carrier (fleet deliveries, route launches,
utilisation trend) and decomposes trailing ASK growth, following the same
pipeline logic as the MTR project.

Machine-readable output: `data/normalized/hk_transport/airline_capacity_pipeline.csv`
(27 rows).

## Fleet delivery pipeline (on-order book anchored to delivery pace)

| Carrier | On-order | Trailing-12m net add | Est. deliveries 12m | Confidence |
|---|---:|---:|---:|---|
| Air China | 237 | +31 | ~31 | high |
| China Southern | 238 | +21 | ~21 | high |
| China Eastern | 280 | +15 | ~15 | high |
| Hainan Airlines | 159 | +13 | ~13 | high |
| Spring Airlines | 42 | +4 | ~4 | medium |
| Juneyao Airlines | 25 | **0** | ~8 (uniform) | **low_no_recent_delivery_pace** |

Key observation: **Juneyao's fleet has been flat for 12 months (net add 0)
despite a 25-aircraft order book**, so its forward capacity growth is
unproven; Spring is delivering steadily (~4/yr) against a 42-aircraft book.
The order book alone (static inventory) does not tell you this - the
delivery-pace anchor does.

## Route launches (CAAC 2026 summer/autumn licences)

| Carrier | New routes | Weekly frequency |
|---|---:|---:|
| Spring Airlines | 4 | 56 |
| Air China | 4 | 56 |
| Juneyao Airlines | 2 | 28 |
| China Southern | 2 | 28 |
| 9 Air (in Juneyao scope) | 2 | 28 |
| China Eastern | 1 | 14 |

Spring is adding the most new route capacity (4 routes / 56 weekly), Juneyao
2 / 28 - consistent with the ask-decomposition divergence.

## Trailing-12m ASK decomposition (observed)

| Carrier | Trailing-12m ASK growth |
|---|---:|
| Spring Airlines | **+14.7%** |
| China Southern | +5.5% |
| China Eastern | +3.6% |
| Air China | +2.7% |
| Hainan Airlines | +1.4% |
| Juneyao Airlines | +0.9% |

Growth is the last twelve months of ASK against the twelve before them.  It
was previously computed as the latest month against the same month a year
earlier while carrying this same "trailing-12m" label, which is why an earlier
revision of this table showed four of the six carriers shrinking: single-month
ASK YoY swings on Spring Festival timing and weather, and the month that
happened to be last was a soft one everywhere.  Nobody was contracting.

Industry utilisation: CAAC sector daily utilisation fell 8.9h -> 8.2h YoY
(-0.7h), a sector-wide capacity-efficiency headwind that hits all carriers.

## Thesis implication

The pair is not just unit economics (Spring CASK 0.300 vs Juneyao 0.345).  It
is also forward capacity: Spring is growing ASK ~15% while keeping the lowest
unit cost, and adding the most new route licences; Juneyao's ASK is flat and
its fleet delivery pace is unproven.  The forward capacity/mix/route economics
support the durability of the Spring advantage rather than a one-period
earnings gap.

## Limitations

* Delivery estimates assume steady pace and cap at the order book; real
  schedules are lumpy and issuer-confirmed only at delivery.
* Route licences are planned supply, not operated ASK.
* Utilisation is sector-wide, not company-specific.
* ASK decomposition is trailing-12m observed, not a forward forecast.  It
  is a twelve-month sum ratio, deliberately not a single-month YoY print.
