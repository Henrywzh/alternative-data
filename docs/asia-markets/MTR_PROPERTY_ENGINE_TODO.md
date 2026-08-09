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
- NOT in current repo for non-SHKP phases (SRPE price lists are PDFs in
  `data/raw/hk_real_estate/srpe_review_price_list/`; transaction scratch
  data is SHKP-specific).
- Options, in order of preference:
  a. SRPE official transaction API for development ids 7585/7787/9345/8745/
     8545/4745/4865/7225 -> count registered units + median ASP (network
     call, verify schema first).
  b. Parse `srpe_review_price_list` PDFs (costly; only covers SHKP phases).
  c. Public phase websites / sales brochures as reference only (label as
     non-PIT).

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
