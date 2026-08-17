# Airline Unit Economics: RASK - CASK Decomposition

Status: 2026-08-10.  This layer upgrades the aggregate earnings bridge into a
per-company unit-economics decomposition.  It answers where an earnings
change comes from (demand vs pricing vs fuel vs efficiency) instead of
treating net profit as a black-box bridge.

## FY2025 unit economics (RMB per ASK)

| Company | RASK | CASK | Unit profit | Ex-fuel CASK | Fuel CASK | Fuel share | Component coverage |
|---|---:|---:|---:|---:|---:|---:|---|
| Spring Airlines | 0.339 | 0.300 | **+0.039** | 0.199 | 0.101 | 33.6% | full |
| Juneyao Airlines | 0.375 | 0.345 | +0.030 | 0.235 | 0.110 | 33.1% | fuel-only |
| China Southern | 0.405 | 0.424 | -0.018 | 0.288 | 0.136 | 32.1% | full |
| China Eastern | 0.423 | 0.433 | -0.009 | 0.295 | 0.138 | 31.9% | full |
| Air China | 0.421 | 0.442 | -0.021 | 0.306 | 0.136 | 30.8% | partial |
| Hainan Airlines | 0.375 | 0.394 | -0.019 | 0.269 | 0.125 | 31.8% | partial |

Sources: official-report driver layer (Big 3 + Hainan components), Spring
FY2025 annual-report cost table (p27, full composition), Juneyao FY2025
unit-cost disclosure (p22) plus p39 fuel share anchor (33.11%, fuel
consumption 117.79万吨).  Machine-readable output:
`data/normalized/hk_transport/airline_unit_economics.csv`.

## What this says about the Spring-Juneyao pair

The pair is not "Spring earnings higher".  It is:

* **Spring CASK 0.300 vs Juneyao 0.345** - Juneyao unit cost is 14.7% higher.
* **Spring ex-fuel CASK 0.199 vs Juneyao 0.235** - Juneyao non-fuel unit cost
  is 17.6% higher.  The LCC advantage is entirely non-fuel.
* **Fuel shares are nearly identical (33.6% vs 33.1%)** - both carriers are
  narrowbody fuel-exposed in the same way, so the pair is fuel-neutral on
  unit-cost grounds.  The advantage is operational: seat density, aircraft
  utilisation, distribution cost, service cost.
* **Spring unit profit +0.039 vs Juneyao +0.030** - Spring earns 29% more
  operating margin per ASK despite a 10.5% lower RASK (0.339 vs 0.375),
  because its CASK advantage (14.7%) exceeds its RASK discount (10.5%).

Juneyao's higher RASK reflects its hybrid/full-service positioning and
international route mix, but the earnings conversion from that mix is diluted
by the higher cost base.  This is the quantitative core of the variant
perception: the market underestimates the durability of Spring's unit-cost
advantage while overestimating the earnings conversion from Juneyao's
international capacity recovery.

## Data limitations

* Spring component split is exact (annual-report cost table); Juneyao only
  discloses fuel + unit costs, so its staff/aircraft/airport components are
  absorbed into "other" (0.235) and are not comparable with Spring's "other"
  (0.024).  The pair comparison is therefore made on total CASK, ex-fuel
  CASK, fuel CASK and fuel share - all available for both.
* Air China and Hainan are partial (aircraft/airport/maintenance absorbed
  into "other"); Big 3 components are from official driver layer.
* This is a FY2025 static decomposition; forward unit economics require the
  walk-forward ASK/RPK layer and the fuel/FX scenario surface.
