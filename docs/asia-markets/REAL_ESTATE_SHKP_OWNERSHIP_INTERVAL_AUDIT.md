# SHKP ownership-interval audit

**Audit date:** 2026-08-06  
**Scope:** the 13 priority SRPE phases used by the first-stage SHKP project
universe.  This document is an evidence memo, not an ownership assertion.

## Promotion rule

A phase may enter attributable SRPE sales only when one phase-specific legal or
economic-interest record provides all of the following:

```text
srpe_development_id
phase-specific SPV/JV identity
numeric SHKP attributable/economic percentage
effective_from
effective_to (the current implementation requires a bounded end date;
open-ended intervals would need a separate explicit policy)
source document and date semantics
continuity / no unresolved grouped-phase conflict
```

Annual-report “Group's Interest” values, project websites, tender awards,
consent-to-sell dates and completion schedules are evidence layers, but do not
automatically satisfy this rule.

## Results by phase

| SRPE phase | Official evidence reviewed | Numeric result | Interval result | Blocker |
|---|---|---:|---|---|
| `9366` Cullinan Sky Phase 1 | Super Great 100% in dated principal-subsidiary snapshots; NKIL 6568 tender award; grouped Sky/Sky Mall table in the [2025/26 interim announcement](https://www.shkp.com/en-US/media/press-releases/sun-hung-kai-properties-202526-interim-results-announcement) | 100% snapshots | `effective_from=null`, `effective_to=null`, `legally_continuous=false` | 2018 tender and later reporting dates do not prove continuity; latest 100% row groups Phase 1/2 and mall |
| `11005` Cullinan Sky Phase 2 | NKIL 6568 Phase 2 row in the 2023/24 annual-report project table; Super Great subsidiary observations; [FY2026 interim-results presentation](https://www.shkp.com/sites/assets/files/2026-02/FY26%20Interim%20Results_For%20Website.pdf) page 16 | 100% phase snapshots | blocked | The latest presentation is still a point-in-time stake disclosure; it has no effective-from/to or continuous SPV/title chain |
| `9785` Cullinan Harbour Phase 1 | Well Capital tender award and 100% principal-subsidiary snapshots; [2024/25 annual report](https://www.shkp.com/Content/Uploads/FinReports/SHKPAR_EN_2024_25.pdf) | 100% snapshot | blocked | Well Capital/lot evidence covers P1, 2A and 2B together |
| `10405` Cullinan Harbour Phase 2A | Same Well Capital and NKIL 6551 evidence; phase statutory page | 100% grouped/SPV snapshot | blocked | No phase-level allocation or effective dates |
| `11516` Cullinan Harbour Phase 2B | NKIL 6551 Phase 2B row in the 2023/24 annual-report project table; Well Capital subsidiary observations; [FY2026 interim-results presentation](https://www.shkp.com/sites/assets/files/2026-02/FY26%20Interim%20Results_For%20Website.pdf) page 17; phase statutory page | 100% phase snapshots | blocked | No effective-from/to or continuous SPV/title chain |
| `11554` Garden Regency | Ease Gold 100% snapshots, [FY2026 interim-results presentation](https://www.shkp.com/sites/assets/files/2026-02/FY26%20Interim%20Results_For%20Website.pdf) page 17, Lot 1071 DD103, official project vendor page | 100% snapshots | blocked | The latest number is still a presentation-date lot/project stake snapshot; no legal start/end of the economic interest |
| `11505` Lime Spark | Tippon vendor/holding-company notice; LandsD/TPB lot and planning evidence; 2024/25 annual-report address row and [FY2026 interim-results presentation](https://www.shkp.com/sites/assets/files/2026-02/FY26%20Interim%20Results_For%20Website.pdf) page 17 for 13–23 Wang Wo Tsai Street | 100% project snapshots via address bridge | blocked | The latest number is still not a phase-specific Tippon/SPV effective interval |
| `11305` Sierra Sea Phase 2A | 2024/25 annual-report page 40 Tai Po Town Lot 253, Sai Sha Phases 2A & 2B / Sai Sha Residences; phase-specific statutory page | 100% grouped P2A/P2B | blocked | Grouped phase disclosure cannot be split |
| `11345` Sierra Sea Phase 2B | Same 2024/25 annual-report page 40 and Sai Sha/TPTL 253 evidence | 100% grouped P2A/P2B | blocked | Grouped phase disclosure cannot be split |
| `9565` YOHO WEST Phase 1 | JV in SHKP reports/schedules; MTR Owner and SHKP-linked person-so-engaged roles on statutory page | No SHKP percentage | blocked | JV economics and effective dates undisclosed |
| `10585` YOHO WEST PARKSIDE Phase 2 | JV in reports/schedules; MTR Owner / Best Vision person-so-engaged statutory notice | No SHKP percentage | blocked | Material date is not an ownership-effective date |
| `7845` The YOHO Hub Phase B | JV in SHKP reports/schedules; Yuen Long Property Development Owner / Success Keep person-so-engaged | No SHKP percentage | blocked | JV partner economics and phase interval undisclosed |
| `8525` The YOHO Hub II Phase C | JV in SHKP reports/schedules; phase statutory notice | No SHKP percentage | blocked | JV partner economics and phase interval undisclosed |

The detailed legal-observation dataset records the same conclusion in a
machine-readable `interval_blocker`. No row is eligible to set
`ownership_attribution_ready`.

The companion `shkp_ownership_coverage_audit` makes phase coverage explicit:
9 phases have numeric or grouped snapshots but no bounded interval, while 4 JV
phases have phase identity/role evidence (owner/vendor/person-so-engaged labels)
but no numeric economics. These are coverage statuses, not ownership
assertions. The 117-row annual-report-to-SRPE crosswalk is persisted as a
review-only evidence layer; it does not change this interval conclusion.

## Best next evidence route: IRIS / Land Registry pilot

The Land Registry says current and historical land registers can provide the
registered-owner chain, owner capacity, lot share and memorial/instrument
details. Any user can access IRIS ad hoc, but the searches and memorial copies
are paid; the official service also documents an API only for subscriber
authorized institutions under the Banking Ordinance. There is no public batch
project-ownership endpoint for this research workflow. See the [official search
FAQ](https://www.landreg.gov.hk/en/faq/faq_search_1.htm), [historical/current
register description](https://www.landreg.gov.hk/en/faq/faq_search_2.htm), [IRIS
land-record service](https://www.landreg.gov.hk/en/services/services_b_2.htm) and
[official search fees](https://www.landreg.gov.hk/en/faq/faq_search_4.htm).

The Land Registry's free [Street Index / New Territories Lot-Address Cross
Reference browsing service](https://www.landreg.gov.hk/en/public/pu-si_agree.htm)
is useful for manually checking a lot/address before ordering IRIS records, but
its terms explicitly prohibit downloading, saving, copying or reproducing the
SI/CRT data. It is therefore a manual reference aid, not a source to scrape or
persist in this repository.

Run a bounded pilot for these lots first:

| Lot / land package | SRPE phases to test | Why first |
|---|---|---|
| NKIL 6568 | `9366`, `11005` | Cullinan Sky phase split and Super Great chain |
| NKIL 6551 | `9785`, `10405`, `11516` | Cullinan Harbour three-phase split |
| Lot 1071 in DD103 | `11554` | Strong one-to-one Garden Regency identity |
| TWTL 160 and related Tsuen Wan West lots | `11505` | Tippon / Win Profit chain |
| Tai Po Town Lot 253 RP | `11305`, `11345` | Sierra Sea 2A/2B split |
| TSWTL 23 | `9565`, `10585` | MTR / Best Vision JV economics |
| YLTL 510 | `7845`, `8525` | YOHO Hub B/C JV economics |

The seven-package execution worksheet is stored in
`docs/asia-markets/REAL_ESTATE_SHKP_IRIS_ORDER_PLAN.csv`. It intentionally lists
the base full-register fee and per-document fee separately; it is an order
plan, not an instruction to make a purchase. After records are obtained, map
each memorial/document into
`REAL_ESTATE_SHKP_IRIS_PILOT_TEMPLATE.csv`, preserve the order/reference and
source hash, and only then create a reviewed decision CSV.

For each lot, order the Historical and Current Land Register and relevant
memorials (Assignment, Transfer, Deed of Assignment, new grant or variation).
Store at minimum:

```text
lot_no
srpe_development_id
memorial_no
instrument_type
instrument_date
registered_owner
owner_capacity
registered_share
consideration_if_published
source_order_or_image_reference
date_semantics
```

Land Registry dates can establish a registered-title event. They do **not** by
themselves establish SHKP's attributable percentage: the registered owner,
SPV/JV agreement and SRPE phase still need to reconcile. Consent-to-assign and
consent-to-sell dates must remain regulatory dates, not title-transfer dates.

The repository now includes `build_shkp_land_registry_evidence` in
`src/hk_real_estate/sources/shkp.py` for a bounded manual CSV/DataFrame import.
It validates lot/date/provenance fields, preserves `registered_share` as raw
title data, never converts `1/2` into `50%`, and forces
`promotion_status=blocked_land_registry_owner_only`. It is intentionally not
passed into the legal-observation layer or the sales gate.

The blank, non-sensitive pilot layout is stored at
`docs/asia-markets/REAL_ESTATE_SHKP_IRIS_PILOT_TEMPLATE.csv`. It is a
collection worksheet, not an import-ready evidence claim: fill the memorial,
instrument, owner and provenance fields from IRIS, then run the importer and
keep any ambiguous phase match as review-only.

The separate `shkp_phase_attribution_decisions` layer is now consumed by
`run-shkp-catalog`: the current normalized snapshot contains 13 explicit
`blocked_review` placeholders (one per priority phase) and zero approved
decisions. If a reviewed decision is later imported, the next catalog refresh
passes it into the registry; only an approved row with the required bounded
interval and evidence IDs can change `ownership_attribution_ready`.

The reviewed decision input boundary is the blank
`REAL_ESTATE_SHKP_PHASE_DECISION_TEMPLATE.csv`. Use
`python -m src.hk_real_estate.cli import-shkp-phase-decisions <CSV>` to validate
and merge reviewed rows. The command deliberately does not rebuild the
registry or sales plan; run the catalog refresh afterward and inspect the
coverage audit before any attribution is promoted.

Paid register images and owner personal details should stay in controlled
storage. The normalized evidence should retain an order/reference and source
hash or locator, not expose credentials or unlicensed document images in the
public repository.

## Current decision

Until the IRIS pilot or an equivalent dated SPV/JV instrument supplies a
phase-specific interval, all SRPE transaction and price-list outputs remain
review-only. The system must not allocate them to `0016.HK`, even when a
project-level snapshot says 100%.
