# Valuation v2: Street vs Own Multiples

Status: 2026-08-10.  Roadmap item 3.  Answers: even if Spring beats, is
the stock still cheap?  Two valuation sets per carrier - what the market
pays for Street expectations vs what it pays for OUR expectations.

## The pair table (the key read)

| Metric | Spring | Juneyao | Edge |
|---|---|---|---|
| PE_street (price / consensus EPS) | **20.9x** | **27.0x** | Spring cheaper on Street numbers |
| PE_own (price / v4 season-adjusted EPS) | **12.5x** | **17.1x** | Spring cheaper on our numbers |
| PE_v3 (price / v3 model EPS) | 16.3x | 22.3x | Spring cheaper |
| Re-rate if OUR EPS materialises | **-40.3%** | -36.7% | Spring compresses more |
| P/B current / 1y percentile | 2.40x / **10.1%** | 2.32x / 18.4% | Spring near 1y low |

### Interpretation

1. **Spring is cheaper than Juneyao under EVERY EPS set** (Street, v3,
   own) - the pair is not a "buy a rerating at any price" trade; it buys
   the cheaper stock with the bigger earnings surprise.
2. **Spring's Own P/E (12.5x) vs Street P/E (20.9x)** means: if our
   season-adjusted EPS materialises and the price holds, Spring de-rates
   40% to a 12.5x multiple - i.e. the market is paying for Spring to
   MISS consensus badly.  That is the definition of an expectation gap.
3. **P/B at the 10th percentile of its 1y range** (vs Juneyao's 18th)
   gives valuation downside protection on the long leg: even a neutral
   print leaves little multiple compression room, while an EPS beat has
   asymmetric upside.
4. The combined framework now reads:
   `Operating edge (unit economics + cost) + Expectation gap (surprise
   +58%/67%) + Valuation (cheaper both ways) + Catalyst (1H26 reports)`.

## Per-carrier detail

| Company | PE_street | PE_own | P/B 1y pct | Notes |
|---|---|---|---|---|
| Spring Airlines | 20.9x | 12.5x | 10.1% | Full valuation case |
| Juneyao Airlines | 27.0x | 17.1x | 18.4% | Full valuation case |
| Air China / Eastern / Southern | n/a | n/a | 7-23% | EPS near zero -> P/E artifact, suppressed |
| Hainan Airlines | 26.6x | n/a | 3.8% | Consensus stale (110d) |

## Honest limits

- EV/EBITDAR remains missing for most carriers (free debt/cash/lease
  split not reliable for all six); only Air China has a value
  (10.9x, lease add-back from unit aircraft CASK).
- P/B history is ~1 year of public Baidu valuation data, not a long
  cycle; percentiles are 1y only.
- Prices are the 2026-08-10 snapshot; consensus Juneyao/Hainan stale.
- Seasonality adjustment (Spring x2.03, Juneyao x2.67) is the 3-year
  average of profitable years; it is an assumption, not a target.

## Files

- Module: `src/hk_transport/sources/airline_valuation_v2.py`
- Valuation: `data/normalized/hk_transport/airline_valuation_v2.csv`
- Pair: `data/normalized/hk_transport/airline_valuation_v2_pair.csv`
- Tests: `tests/test_hk_transport_airline_valuation_v2.py` (6 tests)
- CLI: `run-airline-valuation-v2`
