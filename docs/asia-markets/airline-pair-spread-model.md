# Spring - Juneyao Direct Earnings-Spread Model (Priority 6)

Status: 2026-08-10.  Forecasts the pair spread directly instead of the two
absolute earnings levels, letting common risks (fuel, macro, RMB, domestic
demand) cancel.

## Construction

```
Spread_t = Spring net income - Juneyao net income (annual, 2016-2025)
Drivers: ASK-growth gap, RPK-ASK gap difference, load-factor difference
```

The load-factor difference is derived from total RPK/ASK (no company-total
LF row is published; same convention as the imputed KPI layer).  CASK
difference from unit economics is the structural cost advantage held as
context.

## Historical fit (2017-2025)

Direction accuracy **78%** (7/9).  The model gets the sign of the
Spring-minus-JUNEYAO spread right in most years; the COVID year 2020 misses
(predicted +563 vs actual -115) because the two carriers' losses were not
symmetric despite the common shock.

## H1-2026 forecast

Driver-based spread forecast **+630m RMB** (annualised), from the most
recent pair-level gaps (ASK-growth gap +4.4pp, LF diff +5.6pp).  This is
NOTABLY more conservative than the independent-model difference (forward
bridge H1 1,266m, annualised ~2,532m).  The gap between the two views is
itself informative: the direct spread model uses the recent operating gap
(which has narrowed vs 2025's 10pp), while the independent model embeds
the full unit-cost advantage.  Both are reported; the 1H2026 print decides.

## Why direct spread is better for the pair

* Fuel/macro/RMB shocks affect both legs; differencing removes the common
  component before modelling, so the drivers measure the RELATIVE
  advantage (capacity, demand-pricing, load factor).
* It matches the trade: the position IS the spread, so modelling it
  directly avoids compounding two absolute-level errors.
* The structural CASK advantage (Juneyao 0.345 vs Spring 0.300) is the
  persistent part; the operating gaps are the cyclical part.

## Limitations

* Only 9 annual observations; the regression is sensitive to the 2023
  outlier (-49pp ASK gap year).
* LF is derived (RPK/ASK), not issuer-disclosed company total.
* The forecast spread (+630m) is a conservative central case; the
  sensitivity surface and beat probability (Spring 69.9% vs Juneyao 52.5%)
  are the uncertainty layers around it.
