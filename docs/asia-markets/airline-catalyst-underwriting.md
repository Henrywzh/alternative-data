# Catalyst Underwriting + Thesis Scoreboard

Status: 2026-08-10.  Roadmap item 4 (final).  Upgrades the event calendar
into a decision tree and consolidates every research layer into one
scoreboard.  The thesis is now underwriteable:

    Operating edge + Expectation gap + Valuation + Catalyst

## Catalyst tree (Event -> KPI -> EPS -> Thesis)

| Event | Window | Expected sign | Magnitude hypothesis | Invalidation threshold |
|---|---|---|---|---|
| 1H2026 reports | 08-29/31 | Spring beat, Juneyao beat-less | v4 season-adj surprise +67.5% vs +58.1% | Spring surprise < Juneyao, or Spring misses consensus |
| Jet fuel into H2 | 09-01.. | neutral, pair near-hedged | fuel +5% EPS: Spring -11% vs Juneyao -36% (relative sensitivity) | fuel >10% move within print month |
| Golden Week yield test | 10-01 | Spring RPK-ASK gap positive | yield -3% EPS: Spring -35% vs Juneyao -122% | Spring gap negative or LF edge <2pp |
| Juneyao intl ramp | 09-01.. | negative for Juneyao margin | consensus needs Juneyao RASK +14% vs ours | Juneyao closes RASK gap to <5% |
| HSR openings | 09-01.. | mild negative domestic yield | caps fare upside; Juneyao more exposed | not near-term; monitor H2 guidance |
| RMB vs USD | 09-01.. | second-order | FX -3%/+3% in 3D surface | only >5% move within print month |

Key finding: **Juneyao's RELATIVE EPS sensitivity to fuel and yield is 3x
Spring's** (fuel +5%: -36% vs -11%; yield -3%: -122% vs -35%) because its
EPS base is small.  This supports the short leg but means the pair is NOT
a clean hedge - a large fuel move in the print month dominates the pair
either way.

## Thesis scoreboard

| Component | Spring | Juneyao | Edge | Status |
|---|---|---|---|---|
| Capacity | ASK +15.4% H1 | ASK +1.1% H1 | Spring | confirmed |
| Load factor | 91.5% | 85.6% | Spring | confirmed |
| Yield | consensus needs RASK +2.6% | needs RASK +14.1% | Spring | variant perception |
| Fuel CASK | 0.167 | 0.182 | Spring | shared risk (relative) |
| Non-fuel CASK | 0.199 | 0.235 | Spring (+15%) | confirmed |
| International mix | low intl | intl ramp | Juneyao risk | key uncertainty (short leg) |
| Earnings vs Street | +67.5% | +58.1% | Spring, gap ~9pp (season-adj) | confirmed |
| Valuation | PE 20.9/12.5x, P/B 10% | PE 27.0/17.1x, P/B 18% | Spring | confirmed |
| Catalyst | 08-29 print | 08-31 print | Spring first | upcoming |
| Risk (one-offs) | 1H25 other income 32% PBT | 98% PBT | both flagged | watch |

## What would invalidate the trade (pre-registered)

1. Spring season-adjusted EPS surprise < Juneyao's at the 1H26 prints.
2. Spring misses consensus on a season-adjusted basis.
3. Juneyao's international ramp converts at consensus-level margins
   (RASK gap closes to <5%).
4. Fuel moves >10% within the print month (dominates the pair).
5. Spring's 1H25 651m other-income line normalises down without a
   compensating operating gain.

## Files

- Module: `src/hk_transport/sources/airline_catalyst_underwriting.py`
- Catalyst: `data/normalized/hk_transport/airline_catalyst_underwriting.csv`
- Scoreboard: `data/normalized/hk_transport/airline_thesis_scoreboard.csv`
- Tests: `tests/test_hk_transport_airline_catalyst_underwriting.py` (5 tests)
- CLI: `run-airline-catalyst-underwriting`
