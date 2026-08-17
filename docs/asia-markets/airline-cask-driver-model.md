# Driver-Based CASK Model (Priority 3)

Status: 2026-08-10.  Cost is the weakest part of the stack (aggregate cost
MAE ~13.7% vs revenue ~5.8%).  This model replaces the fully free cost
extrapolation with a driver-based decomposition.

## Construction

```
Fuel CASK_t     = FY fuel CASK x (fuel price now / fuel price FY2025)
Fuel efficiency = FY fuel cost / (FY ASK x fuel price)   (residual: hedge/FX/mix)
Staff CASK      = FY staff CASK x ASK ratio
Airport CASK    = FY airport CASK x ASK ratio
Maintenance     = FY maintenance CASK x ASK ratio
Depreciation    = FY aircraft CASK x ASK ratio (fleet proxy)
Other           = FY other CASK x ASK ratio
```

## H1-2026 result (RMB per ASK)

| Company | Fuel CASK | CASK forecast | vs FY2025 CASK |
|---|---:|---:|---:|
| Spring Airlines | 0.167 | 0.276 | -0.024 |
| Juneyao Airlines | 0.182 | partial | - |
| China Southern | 0.225 | 0.369 | -0.055 |
| China Eastern | 0.229 | 0.375 | -0.058 |
| Air China | 0.226 | 0.376 | -0.066 |
| Hainan Airlines | 0.207 | 0.336 | -0.058 |

Key driver finding: **2026 spot fuel (~3.51 USD/gal) is ~66% above the
FY2025 average (~2.11)**, so fuel CASK scales UP materially (Spring 0.101 ->
0.167).  Non-fuel components scale with ASK growth, so the CASK forecast
falls on ASK leverage even as fuel rises.

## Why driver-based is better

* Fuel is priced explicitly (EIA jet fuel x implied efficiency) instead of
  being inside one aggregate cost growth - the fuel shock is separated from
  efficiency.
* Non-fuel components scale with their economic driver (ASK as the free
  proxy for staff/airport/maintenance, fleet for depreciation) rather than
  one shared growth rate.
* The model surfaces the fuel price assumption as a first-class input; the
  3D sensitivity surface already varies it.

## Limitations (labelled)

* Block-hours and employee counts are not free; ASK is the proxy driver for
  staff/airport/maintenance, so utilisation-driven cost moves are missed.
* Implied fuel efficiency embeds hedging, FX and mix; it is held constant
  forward, so a hedging reset or mix shift is not modelled.
* Juneyao is partial (only fuel + other in its cost decomposition - its
  annual report has no full cost table).
