# Decision-Usefulness Evaluation (Priorities 4 + 5)

Status: 2026-08-10.  Switches evaluation from aggregate MAE to
investment-decision metrics: consensus-relative beat probability, forecast
ensemble, and uncertainty intervals.

## Beat probability (P[annualised model net profit > FY26 consensus])

| Company | Model H1 net (RMB mn) | Annualised (x2) | Consensus FY26 | Beat prob |
|---|---:|---:|---:|---:|
| Spring Airlines | 1,794 | 3,588 | 2,110 | **69.9%** |
| Juneyao Airlines | 528 | 1,055 | 927 | 52.5% |
| China Southern | -302 | -605 | 707 | 47.0% |
| China Eastern | -984 | -1,969 | 434 | 42.6% |
| Air China | -9,772 | -19,543 | 270 | 13.4% |
| Hainan Airlines | -1,166 | -2,332 | 2,113 | 31.4% |

Beat probability comes from a Monte Carlo (2,000 draws) over historical
revenue and cost MAE distributions with a 0.3 revenue-cost error
correlation; H1 net is annualised x2 (conservative lower bound - H2 is
seasonally stronger for mainland carriers).

Pair read: **Spring ~70% vs Juneyao ~52% beat probability** - the model is
far more confident Spring beats consensus than Juneyao does.  This is the
decision-useful version of "Spring EPS 1.84 vs Juneyao 0.24".

## Ensemble (OOS-loss weights)

Revenue leg: flat-ASK weight 0.65 / yield-mix 0.35 (flat-ASK has the best
H1 revenue MAE).  Cost leg: fuel/non-fuel weight 0.61 / flat-ASK 0.39.
The natural architecture the data supports: flat-ASK revenue + driver-based
cost, rather than forcing one integrated model.

## Uncertainty intervals (P5 / P50 / P95, RMB mn)

| Company | P5 | P50 | P95 |
|---|---:|---:|---:|
| Spring Airlines | -572 | 1,839 | 4,065 |
| Juneyao Airlines | -1,851 | 543 | 2,801 |

The intervals make the point-estimate uncertainty explicit: Spring's P5 is
slightly negative (a bad draw loses money), which is exactly why the
sensitivity surface and invalidation rules matter.

## Limitations

* Consensus is FY2026 A-share detailed; H1 model annualised x2 is a crude
  seasonal assumption.
* Monte Carlo assumes normal errors with fixed correlation; the true
  distribution is fat-tailed (COVID years).
* Direction accuracy vs consensus is not yet computable - it requires the
  actual 1H2026 prints (fill into the validation playbook after 8-29/31).
