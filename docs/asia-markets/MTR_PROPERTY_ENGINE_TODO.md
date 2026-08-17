# MTR Property Engine TODO (P0B)

## Status: v2 SRPE crosswalk done (2026-08-09)

`src/hk_transport/sources/mtr_property_project_master.py` now carries 19
official MTR railway-property packages with:

- profit-recognition years from MTR annual results (2021-2025)
- tender years (THE SOUTHSIDE P5/P6 2021; Tung Chung East P1 2024-12;
  Tuen Mun A16 P1 2025-11)
- SRPE development crosswalk with first-price-list dates for 8 name-confirmed
  phases (晉環 7585 / 揚海 7787 / 海盈山 9345 / 瑜一 8745 / 凱柏峰I 8545 /
  晉海 4745 / 晉海II 4865 / 柏傲莊I 7225)

## Fields intentionally unpopulated (need new verified sources)

### 1. Units / GFA / sell-through (Magnitude Engine inputs)
- DONE V1 (2026-08-09): `scripts/mtr_magnitude_engine.py` -> registered sales
  value per phase (exact sums from 5,921 transactions, cancelled excluded),
  price distribution, and an honest confirmation-group profit/sales reference.
  Reliable anchor: G2022H1 7,747m recognised profit vs 晉環+揚海 31,578m
  registered sales = UPPER bound 24.5% (~17% if LP10 ~15bn). G2024H2/G2025H1
  ratios are flagged unreliable (missing SRPE data for most members).
- STILL OPEN: total project units / GFA for sell-through; fill LP10/凱柏峰
  II/III/朗賢峯/SOUTHSIDE P3/P5/P6 SRPE data to sharpen the take-rate reference.

- DONE (2026-08-09): `scripts/mtr_srpe_transactions.py` downloads each phase's
  latest statutory register-of-transactions PDF and parses it with the shared
  `srpe_pdf.py` parser -> 5,921 registered transactions across 8 phases,
  stats written to `mtr_srpe_transactions_by_phase.csv` and into the master
  table (units_sold_registered / asp_median / first-last transaction date).
- STILL OPEN: total project units / GFA / sell-through % need a denominator.
  Candidates: price-list PDF metadata (`total_residential_properties`),
  sales brochures, or public project facts - all to be verified before use.

### 2. Occupancy Permit (OP) / handover timeline (Timing Engine inputs)
- DONE (2026-08-09): Timing Engine V0 in `scripts/mtr_timing_engine.py` uses the
  full 17,517-row `bd_project_lifecycle_history` parquet (257 months, 2005-2026)
  to locate OPs for mapped phases: 11 Heung Yip Road = THE SOUTHSIDE (晉環
  PR4/2022/OP 2022-04, 揚海 PR6/2022/OP 2022-08, 海盈山 PR12/2024/OP 2024-11),
  1 Chung Hau Street = 瑜一 (PR11/2024/OP 2024-11), 1 Lohas Park Road = shared
  lot for LOHAS Park phases (P11 PR13-15/2024/OP 2024-12, P12 PR7-9/2025/OP
  2025-10, SUSPECTED attribution). Empirical: OP and recognition same year.
- NEXT: split recognition into H1/H2 using MTR interim results (property
  development profit in each interim announcement) to sharpen the lag.

- `bd_project_lifecycle_events` only contains a SHKP-filtered subset; the
  only MTR-project hit is a bare "Tai Wai" OP row without permit number.
- Options:
  a. Full Buildings Department Md52/Md56 monthly digests for 香葉道 (Wong
     Chuk Hang), 康城路 (LOHAS Park), 忠孝街 (Ho Man Tin), 車公廟路 (Tai
     Wai), 深旺道 (Nam Cheong) - requires address/permit entity resolution
     (same approach as SHKP BD history, which is still
     `blocked_address_only` for attribution).
  b. MTR annual/interim reports mention handover progress per package
     (qualitative) - extract into a notes column.
- Do NOT infer OP dates from price-list dates; presale-to-OP lag is exactly
  the 2-3 year recognition window we are trying to measure.

## Next steps

1. SRPE transaction API probe for the 8 mapped ids (units + ASP + first/last
   transaction date) - same pattern as `shkp_high_recall`/SRPE scripts.
2. BD Md52/Md56 OP matching for the five station addresses above.
3. Once units/ASP/OP are populated, build the Timing Engine
   (P(recognition in FY) per package) and the Magnitude Engine
   (expected MTR profit = P x remaining profit share) skeleton.
4. Consensus skeleton (P0C) can proceed in parallel - it only needs the
   earnings bridge + a Street estimate source.
