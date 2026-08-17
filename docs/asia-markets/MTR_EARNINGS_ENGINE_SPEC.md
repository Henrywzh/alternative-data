# MTR Total Earnings Engine & Global Architecture Specification

## 1. Executive Summary & Validated Baselines

This document defines the canonical specification for the **MTR (66.HK) Total Earnings Engine & Buy-Side Research Specification**.

### Validated Revenue Baselines
- **FY2025 Practical Forward Validation**:
  - **Forecast HK Transport Operations Revenue**: **HK$23,696.2M**
  - **Reported Actual (MTR 2025 Annual Results)**: **HK$23,595.0M** (+2.5% YoY)
  - **Practical forward validation error**: **+0.43%**
- **2019-2023 Structural Replay Diagnostics** (not chronological OOS):
  - Baseline Physics Model MAPE: **4.78%**
  - Regularized Ridge L2 Residual Model MAPE: **4.06%** (2023 error: −0.5%; leave-one-out structural replay)

The independent chronological track is `scripts/build_mtr_walk_forward_oos.py`.
It yields FY MAPE 9.32% and H1 MAPE 8.10% on the currently available prior-
period-yield practical-OOS rows. These are not A-grade strict PIT metrics
because the MTR patronage page does not provide historical monthly release
vintages; the model records this caveat and the SHA-256 input bundle for each
run.

Its monthly companion is a forecast-only series (`mtr_farebox_monthly_nowcast.csv`):
MTR does not publish monthly transport-operations revenue actuals, so it is not
scored as a monthly backtest. It is intended for current-period monitoring and
for future scoring if an official monthly revenue history becomes available.

---

## 2. Financial Statement Accounting Architecture

MTR is an integrated **"Rail plus Property" (R+P)** urban developer and asset manager. Models must follow MTR's exact financial reporting structure rather than flattening operations into four simple revenue categories.

### FY2025 Consolidated Revenue Breakdown (Total: HK$55,455M)
1. **Hong Kong Transport Operations**: HK$23,595M (42.6%)
2. **Hong Kong Station Commercial**: HK$5,345M (9.6%)
3. **Hong Kong Property Rental & Management**: HK$5,067M (9.1%)
4. **Mainland China & International Subsidiaries**: HK$20,686M (37.3%)
5. **Other Businesses**: HK$762M (1.4%)

### HK Property Development Profit (Separate Accounting Line)
- Property Development does **NOT** enter Consolidated Revenue as full sales top-line.
- It is reported as **Hong Kong Property Development Profit** (FY2025: **HK$13,212M gross profit** / **HK$11,066M post-tax profit attributable to MTR**).
- In property handover years (e.g. 2025), Property Development Profit is the single largest contributor to group EBIT and Underlying Profit.

```text
                                  MTR Total Earnings Architecture

          ┌────────────────────── Recurrent Businesses ──────────────────────┐
          │                                                                  │
 HK Transport Operations          Station Commercial             Property Rental & Management
          │                               │                                   │
 Passenger Farebox Revenue          Ads / Retail / Telecom              Attributable GFA / Rent /
 (ImmD Daily Traffic Nowcast)    (Monetisation per Trip)                 Lease Roll Engine
          │                               │                                   │
          └───────────────────────────────┴───────────────────────────────────┘
                                          │
                                 Recurrent EBIT / OPEX
                                          │
                   Mainland China & International Operations
                     (3-Tier Model: Fare Risk / O&M / Project)
                                          │
                   ──────────────────────────────────────────
                                          │
                               HK Property Development
                            (2-Layer Engine: Timing + Magnitude)
                                          │
                   ──────────────────────────────────────────
                                          │
                         D&A / Rate Reset Engine (HIBOR) / Tax
                                          │
                               Underlying Business Profit
                                          │
                   IP Revaluation / One-off Impairments
                                          │
                                   Reported NPAT & EPS
                                          │
                              vs Street Consensus Delta
                                 (Earnings Surprise)
```

---

## 3. HK Property Development Engine (Two-Layer Model)

Integrates with `src/hk_real_estate` (SHKP + MTR TOD JVs: Cullinan Sky, YOHO WEST, Cullinan West 匯璽, The YOHO Hub, THE SOUTHSIDE, etc.).

### Layer 1: Timing Engine
Predicts the probability of profit recognition in a given half-year $P(\text{recognition}_{i, t})$:
- Inputs: LandsD Presale Consents, Buildings Dept (BD) Occupancy Permits (OP), Certificate of Compliance (CA), developer handover announcements.
- **Recognition Lag**: Accounting recognition occurs at handover (OP/CA issuance), 2–3 years after PASP contract sales.

### Layer 2: Magnitude Engine
Projects MTR's expected remaining profit per project:
$$\text{Expected Property Profit}_t = \sum_i P(\text{recognition}_{i, t}) \times E[\text{Remaining MTR Profit}_i]$$

Where each project maintains an explicit economics record:
$$\text{Project Economics}_i = \{\text{Units}, \text{GFA}, \text{ASP}, \text{SellThrough}, \text{MTR Arrangement}, \text{Land Premium}, \text{Profit Sharing \%}, \text{Prior Booked}, \text{Remaining Profit}\}$$

---

## 4. Recurrent Commercial & Rental Engines

### Station Commercial (FY2025 HK$5,345M)
- Monetisation per Passenger Trip:
$$\text{Monetisation}_t = \frac{\text{Station Commercial Revenue}_t}{\text{Passenger Trips}_t}$$
- ImmD Cross-Border passenger weighting: High-yielding Cross-Border/HSR passengers drive Duty Free & high-end retail revenue significantly more than local commuters.

### Property Rental & Management (FY2025 HK$5,067M)
- Driven by Elements, Telford Plaza, Maritime Square, PopCorn, The Wai, THE SOUTHSIDE.
- Lease Roll Engine:
$$\text{Rental Growth}_t = \text{Expiry Share}_t \times \text{Reversion Spread}_t + \text{New GFA}_t + \text{Turnover Rent Growth}_t$$

---

## 5. Mainland China & International Operations (Three-Tier Engine)

Mainland & International Subsidiaries revenue was **HK$20,686M in 2025** (-18.8% YoY due to UK Elizabeth Line contract handover). Revenue scale does not equal EBIT importance.

### Business Model Classification

| Tier | Model Type | Examples | Economic Mechanism | Key Inputs / Drivers |
|---|---|---|---|---|
| **Tier A** | **Fare-Risk / PPP** | Shenzhen Line 4, Shenzhen Line 13, Hangzhou Line 5 | Revenue = Passengers $\times$ Average Fare + Subsidies | Patronage, fares, train-km, route extensions (Shenzhen L13 North ext June 2026) |
| **Tier B** | **O&M Service Contract** | Melbourne Metro Trains, Sydney Metro M1, legacy Elizabeth Line | Fixed Service Fee + CPI Indexation + Performance Bonus - Penalties | Contract value, indexation, punctuality, availability. **Government holds fare risk!** |
| **Tier C** | **Project Delivery & Systems** | Sydney Metro West TSMO Contract | Contract Value $\times$ % of Completion / Milestone Accounting | Construction milestones, systems delivery schedule |

### Accounting Treatment
- **Consolidated Subsidiaries** (e.g. Shenzhen Line 4, Melbourne Metro Trains): Top-line revenue and operating expenses fully consolidated.
- **Associates & JVs** (e.g. Beijing Lines 4/14/16/17, Hangzhou Line 1): Top-line revenue = 0 in consolidated income statement; profit appears in **Share of Profit of Associates & JVs**.

### FX Sensitivity Overlay
$$\text{HKD EBIT} = \text{Local Currency EBIT} \times \text{FX Rate (RMB/AUD/GBP)}$$

---

## 6. MTR Global Projects Master Table Schema

| Field | Type | Description |
|---|---|---|
| `project_id` | String | Unique project token (e.g. `sz_line4`, `sydney_m1`) |
| `geography` | String | Region (`Shenzhen`, `Beijing`, `Hangzhou`, `Melbourne`, `Sydney`, `UK`) |
| `line_name` | String | Line / Asset name |
| `mtr_ownership_pct` | Float | MTR equity ownership percentage |
| `accounting_type` | Enum | `Subsidiary`, `Associate`, `JV` |
| `business_model` | Enum | `Fare_Risk_PPP`, `OM_Service_Contract`, `Project_Delivery` |
| `fare_risk` | Boolean | Whether MTR bears passenger volume/fare risk |
| `contract_start_year` | Integer | Contract commencement year |
| `contract_end_year` | Integer | Contract expiry / renewal year |
| `current_stage` | Enum | `Build`, `Ramp_up`, `Mature`, `Handover_Exit` |
| `p1_driver` | String | Key operational/financial driver (e.g. `patronage`, `cpi_indexation`, `milestone`) |

---

## 7. Cost Bridge & Rate Reset Engine

### Finance Cost (Rate Reset Engine)
$$\text{Interest Expense}_t = \sum_j \text{Average Debt}_{j, t} \times \text{Effective Rate}_{j, t} - \text{Capitalized Interest}_t$$
- Debt tranches (fixed vs floating, HIBOR spread, interest rate swaps).
- Group debt in 2025: **HK$88.9bn** (average borrowing cost 3.5%).

### OPEX Drivers
1. **Staff Costs** (~35-40% of recurrent OPEX): Annual 7 July wage adjustment (3.5%–5.0%).
2. **Energy & Utilities** (~8-12% of OPEX): CLP / HEC monthly fuel clause charge.
3. **Depreciation Step-changes**: Step-up upon new line commissioning (Kwu Tung, Tung Chung Line Extension, Tuen Mun South).

---

## 8. Earnings Surprise Engine (Buy-Side Trading Alpha)

The ultimate objective of the model is to output **Earnings Surprise Delta** vs Street Consensus:

$$\text{Alpha Delta} = \text{Our Nowcast Estimate} - \text{Consensus}$$

```text
Metric                        Our Estimate    Consensus    Delta
----------------------------------------------------------------
HK Transport Revenue (HK$M)       23,696       23,500       +196
HK Property Profit (HK$M)         11,066        9,500     +1,566
Recurrent EBIT (HK$M)              6,200        6,050       +150
Finance Cost (HK$M)               -2,900       -3,100       +200
----------------------------------------------------------------
Underlying EPS (HK$)                2.15         1.92      +0.23 (+12.0%)
```

---

*Specification Version: 2.0*
*Maintained in: `docs/asia-markets/MTR_EARNINGS_ENGINE_SPEC.md`*
