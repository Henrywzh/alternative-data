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
- DONE (2026-08-09): `scripts/mtr_srpe_transactions.py` downloads each phase's
  latest statutory register-of-transactions PDF and parses it with the shared
  `srpe_pdf.py` parser -> 5,921 registered transactions across 8 phases,
  stats written to `mtr_srpe_transactions_by_phase.csv` and into the master
  table (units_sold_registered / asp_median / first-last transaction date).
- STILL OPEN: total project units / GFA / sell-through % need a denominator.
  Candidates: price-list PDF metadata (`total_residential_properties`),
  sales brochures, or public project facts - all to be verified before use.

### 2. Occupancy Permit (OP) / handover timeline (Timing Engine inputs)
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
