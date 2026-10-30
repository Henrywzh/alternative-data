# asia_markets research feed

Generated: 2026-10-30T14:12:38.810231Z · Status: **degraded**

Source commit: `aaeceaffe913a3006733ee2d651d9f415c27b9da`

Observation dates differ by record. Generated time is not a market-data timestamp.

| Section | Record | Observation | Quality | Values |
|---|---|---|---|---|
| Hong Kong Labour Market & Talent Policy | Labour Force | 2026-09-30 | current | labour_force_thousands: 3810.0 thousand_people; employed_thousands: 3655.0 thousand_people; unemployment_rate: 0.041 fraction; underemployment_rate: 0.02 fraction |
| Hong Kong Labour Market & Talent Policy | Labour Demand | 2026-06-30 | current | vacancies: 45380.0 jobs; persons_engaged: 2697387.0 people; vacancy_rate: 0.017 fraction |
| Hong Kong Labour Market & Talent Policy | Wage | 2026-06-30 | current | nominal_wage_yoy: 0.034 fraction; real_wage_yoy: 0.016 fraction; nominal_payroll_yoy: 0.035 fraction |
| Hong Kong Labour Market & Talent Policy | Income | 2026-08-31 | current | median_monthly_earnings: 21000.0 HKD_per_month |
| Hong Kong Labour Market & Talent Policy | Talent Policy | 2025-12-31 | current | applications_received: 147454.0 applications; applications_approved: 124460.0 applications; qmas_quota: 7101.0 cases |
| Hong Kong Real Estate Monitor | Rvd Price | 2026-09-01 | current (source_provisional) | latest: 320.8 index_points; period_change: 0.001874 fraction; year_change: 0.093388 fraction |
| Hong Kong Real Estate Monitor | Rvd Rent | 2026-09-01 | current (source_provisional) | latest: 212.2 index_points; period_change: 0.004735 fraction; year_change: 0.061531 fraction |
| HK Transport & Aviation Sector Monitor | Mtr | 2026-09-01 | current | latest: 171407.0 thousand_journeys; domestic_thousands: 139085.0 thousand_journeys; cross_boundary_thousands: 9527.0 thousand_journeys; hsr_thousands: 2553.0 thousand_journeys; recovery_vs_2019_pct: 0.074477 fraction |
| HK Transport & Aviation Sector Monitor | Cathay | 2026-09-01 | current | latest: 2453635.0 passengers; load_factor_pct: 84.2 percent; hkia_passengers: 4835000.0 passengers; period_change: -0.13222 fraction; recovery_vs_2019_pct: -0.159684 fraction |
| HK Transport & Aviation Sector Monitor | Journeys | 2026-07-01 | stale | kmb_k: 74364.335 thousand_journeys; total_k: 349101.83599999995 thousand_journeys; period_change: 0.009501 fraction |
| HK Transport & Aviation Sector Monitor | Fleet | 2026-08-01 | current | total_registered: 650227.0 vehicles; ev_share_pct: 27.4633 percent; ev_share_change_pp: 0.2152 percentage_points |
| HK Transport & Aviation Sector Monitor | Private Car First Reg | 2026-07-01 | stale | total_first_reg: 3253.0 vehicles; electric_first_reg: 1969.0 vehicles; ev_share_pct: 60.5287 percent |
| HK Utilities & Infrastructure Sector Monitor | Clp | 2026-03-31 | stale | latest: 7319.0 GWh; commercial_gwh: 3032.0 GWh; ai_data_centre_yoy_pct: 11.1 percent |
| HK Utilities & Infrastructure Sector Monitor | Towngas | 2026-09-01 | current | latest: 1875.3 TJ; domestic_tj: 865.3 TJ; commercial_tj: 880.7 TJ |
| Hong Kong Telecom Sector Monitor | Hkt | 2026-06-30 | current (partial_metric_coverage) | latest_arpu: None HKD; postpaid_subscribers_thousands: 3522.0 thousand_subscribers; ftth_connections_thousands: 1101.0 thousand_connections |
| Hong Kong Telecom Sector Monitor | Smartone | 2026-06-30 | current (partial_metric_coverage) | latest_arpu: 220.0 HKD; postpaid_subscribers_thousands: None thousand_subscribers; arpu_5g_to_4g_ratio: 2.0 ratio |
| Hong Kong Telecom Sector Monitor | Hutchison | 2026-06-30 | current | latest_gross_arpu: 184.0 HKD; latest_net_arpu: 173.0 HKD; postpaid_customers_thousands: 1304.0 thousand_subscribers; churn_rate_pct: 0.9 percent |
| Hong Kong REITs Sector Monitor | Linkreit | 2026-03-31 | stale | nav_per_unit_hkd: 57.75 HKD_per_unit; dpu_hkd: 2.5361 HKD_per_unit; occupancy_pct: 97.8 percent; rental_reversion_pct: -8.2 percent |
| Hong Kong REITs Sector Monitor | Championreit | 2025-12-31 | stale (partial_metric_coverage) | nav_per_unit_hkd: 6.45 HKD_per_unit; dpu_hkd: 0.1263 HKD_per_unit; occupancy_pct: 81.6 percent; rental_reversion_pct: None percent |
| Hong Kong REITs Sector Monitor | Regalreit | 2026-06-30 | stale | nav_per_unit_hkd: 3.844 HKD_per_unit; hotel_occupancy_pct: 74.3 percent; revpar_hkd: 685.75 HKD |
| Hong Kong Local Consumer Monitor | Retail | 2026-08-01 | current | latest: 114.8 index_points; period_change: 0.033303 fraction; year_change: -0.088889 fraction |
| Hong Kong Local Consumer Monitor | Restaurant | 2026-06-30 | current | latest: 27210.0 HKD_million; period_change: -0.040482 fraction; year_change: 0.020056 fraction |
| Hong Kong Population & Migration | Population estimates | 2026-06 | current | mid_year_population_thousands: 7518.3 thousand_people; net_movement_thousands: 39.8 thousand_people; natural_growth_thousands: -20.4 thousand_people |
| Hong Kong Population & Migration | MPF permanent-departure claims | 2026-Q2 | current | claims_count: 5200 claims; amount_mhkd: 1203.0 HKD_million |

## Rule candidates

- **continuing** `6fc3967d3bb227459f74425f`: hk-labour-market/labour_force_card / hk.unemployment.ge_4pct.v1

## Changes

- new_observation: hk-utilities/towngas_card

## Excluded coverage

- private_research: Events & Consensus, ETF Monitor, Global Market Regime, Hong Kong Flows and Control Tower require their existing private read contracts.
- agency_property_data: Centaline/Midland redistribution review is outside this public subset.
- crypto_aerospace: Mixed-date KPI summaries need per-metric provenance adapters before export.
- other_dashboard_detail: V1 selects the listed official headline datasets; other history, forecasts and private overlays remain in their canonical surfaces.

Use the JSON for provenance, definitions, methodology, previous observations and quality evidence.
