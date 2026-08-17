# Consensus Reverse Engineering v2: Sanity Checks + Implied Surface

Status: 2026-08-10.  Roadmap item 2.  The Spring +64.7% v4-vs-consensus
surprise was treated as a HYPOTHESIS to be aggressively audited.  Result:
the pair thesis survives, but with a materially revised size - and one
new, sharp insight about what the surprise actually means.

## The four sanity checks

| Check | Spring | Juneyao | Verdict |
|---|---|---|---|
| A. Annualisation | H1 share 49.1% -> x2.03 (x2 fine) | H1 share 37.5% -> **x2.67** | **Juneyao x2 understates FY** |
| B. Share count | -0.35% (sane) | +4.2% (sane, likely diluted) | OK |
| C. Parent vs attributable | 归母 NI confirmed | same | OK |
| D. One-offs | 1H25 other_income 651m = 32% of H1 PBT | 577m = 98% of H1 PBT | **both flagged** |

### A is the big find

The v4 live surprise used the x2 annualisation convention (H2 seasonally
stronger).  The sanity check computes each carrier's OWN 3-year H1/FY
profit split:

- Spring: 49.1% -> x2.03.  The x2 convention is essentially correct.
- Juneyao: 37.5% -> x2.67.  Juneyao's profit is heavily H2-weighted (2023:
  H1 only 10% of FY).  x2 materially understates Juneyao's FY surprise.

Seasonality-adjusted surprise: **Spring +67.5%, Juneyao +58.1%** (vs +64.7%
/+18.5% under x2).

**Pair edge shrinks from 46.2pp (x2) to 9.4pp (seasonality-adjusted).**
Spring still beats consensus more than Juneyao, and both are positive - the
thesis direction survives.  But the underwriting must use the adjusted
numbers, not the flattering x2 spread.

### D is the new insight

Spring's 1H2025 other income (651m, 32% of H1 PBT) is carried into the v4
H1-2026 bridge.  This is not a model error - it is the issuer's disclosed
"other income" line (typically fuel-hedge gains and government subsidies).
Its persistence through 1H2026 is the single biggest uncertainty in the
Spring beat probability: if it normalizes down, the EPS surprise narrows.

## Implied RASK/CASK surface

Consensus EPS -> NI -> implied operating profit -> implied RASK/CASK,
holding our model's other leg fixed:

| Company | Implied RASK gap vs our model | Implied CASK gap |
|---|---|---|
| Spring Airlines | **+2.6%** | +2.9% |
| Juneyao Airlines | +14.1% | +15.3% |
| Air China | +23.5% | +22.3% |
| China Eastern | +16.2% | +15.9% |
| China Southern | +21.7% | +20.7% |
| Hainan Airlines | +34.7% (stale cons) | +33.1% |

**The variant perception, stated as an assumption gap:**

> Street's Spring consensus needs RASK only +2.6% above our model (or CASK
> +2.9%) to reconcile - i.e. the +65-67% EPS gap is NOT primarily a yield
> disagreement.  It is a cost/profit-level gap: Street's implied Spring
> margin is far below what our unit economics and cost engine support.
> For Juneyao, Street needs RASK +14% above ours - the market is
> materially MORE bullish on Juneyao yield than our operating data justify,
> which is the core of the short thesis.

## Honest caveats

- Juneyao consensus is stale (age 94d, no revision history); Hainan stale
  (110d).  Refresh before the reports.
- Air China consensus implied shares +164% vs model - a data-quality flag
  on the consensus share count, not a model claim.
- Seasonality is unavailable for the big three (no profitable H1 in
  2023-25); their H1 annualisation remains invalid by construction.

## Files

- Module: `src/hk_transport/sources/airline_consensus_reverse_v2.py`
- Sanity: `data/normalized/hk_transport/airline_consensus_reverse_v2_sanity.csv`
- Surface: `data/normalized/hk_transport/airline_consensus_reverse_v2_surface.csv`
- Seasonality: `data/normalized/hk_transport/airline_consensus_reverse_v2_seasonality.csv`
- Tests: `tests/test_hk_transport_airline_consensus_reverse_v2.py` (8 tests)
- CLI: `run-airline-consensus-reverse-v2`
