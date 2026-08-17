# HSCI Point-in-Time Reconciliation Audit

**Audit date:** 2026-08-07  
**Scope:** Hang Seng Composite Index (HSCI) membership reviews from 2021 onward, reconciliation against the legacy `Research` history, and the free-source automation boundary.

This is an audit and design artifact. It does not modify the legacy `Research` data. The implementation and generated artifacts live in the canonical sibling repository at `/Users/henrywzh/Desktop/Quant/financial-data`.

## Executive conclusion

The legacy Research history is useful as a historical candidate event log, but it is not a safe source of truth for PIT backtests.

The free official Hang Seng sources are sufficient to build a live and incremental HSCI pipeline:

- the live endpoint supplies the complete current snapshot;
- the notices catalog supplies quarterly review files and ad-hoc constituent notices;
- the review workbooks provide structured HSCI Add/Delete records;
- the PDFs provide suspension, privatisation, delisting, fast-entry and other ad-hoc changes.

The main semantic rule is mandatory:

> HSCI total-index membership must be parsed from `Index Code = HSCI`. Sector Add/Delete rows are a separate industry-membership layer and must not be replayed as HSCI membership events.

## Implementation status

The first official-source collector is now implemented in the canonical sibling
repository at `/Users/henrywzh/Desktop/Quant/financial-data`:

```bash
python -m hk_financials.cli run-hsci-pit
```

The verified run produced 443 notice rows, 23 review-workbook documents, 646
HSCI total-index events, 49 deterministic-but-unreviewed HSCI PDF candidates,
150 traceable ad-hoc PDF manual-review items and a 534-row live snapshot. The
advertised-count gate passed. An explicit
`validate-hsci-pit --seed-path ...` command now fails closed on replay errors
or exact-set mismatches.

The 49 PDF candidates are stored separately from canonical events and remain
`candidate_status=pending_review`. A replay including only those candidates is
deliberately imperfect: it reaches 539 members versus 534 live and reports
four duplicate/inactive event errors plus five unresolved historical
memberships. The candidate parser is therefore useful for triage but has not
been promoted to the PIT universe.

For controlled debugging, `config/hk_pit_manual_review_decisions.json` records
9 explicit, non-canonical decisions: 7 scope-confirmation removals from a
Hang Seng Family notice, 1 provisional-seed correction, and 1 diagnostic
no-op. With both candidates and these decisions included, the replay reaches
534/534 with zero interval errors. The output remains `canonical=false` and
the intervals are labelled `seed_provenance=review_decisions_pending`; this
is evidence that the reconciliation machinery is internally consistent, not
approval of those events as official HSCI history.

For audit only, the legacy Research raw `HSCI` sheet can generate a
`provisional=true, canonical=false` bootstrap seed. Its 2008 snapshot plus
pre-2021 HSCI replay reaches 493 members on 2021-03-14 with zero source-count
mismatches after same-code Add/Delete replacements are treated as replacements.
The subsequent official-event replay currently fails exact live-set validation
(566 replayed versus 534 live, with 11 duplicate-add errors), because the
ad-hoc PDF queue is not yet canonicalized. This provisional artifact must not
be used as the production universe.

## Official free sources

| Source | Purpose | Audit result |
|---|---|---|
| [HSCI live JSON](https://www.hsi.com.hk/data/eng/rt/index-series/hsci/constituents.do) | Current full HSCI snapshot | 534 rows, `constituentsCount = 534`, refreshed on 2026-08-07 |
| [HSI live JSON](https://www.hsi.com.hk/data/eng/rt/index-series/hsi/constituents.do) | Current HSI snapshot | 93 rows |
| [HSTECH live JSON](https://www.hsi.com.hk/data/eng/rt/index-series/hstech/constituents.do) | Current HSTECH snapshot | 30 rows |
| [Hang Seng notices catalog](https://www.hsi.com.hk/data/eng/download/notices.json) | Incremental discovery of official files | 443 notices; 22 quarterly review cycles represented by 23 spreadsheets; 85 constituent-change PDFs |
| [2026-05 review workbook](https://www.hsi.com.hk/static/uploads/contents/en/news/indexChgNotice/20260522T174510.xlsx) | Structured review example | `Summary` contains effective date; `Review Result` contains index code, action, security code and company name |
| [2026-06-22 suspension notice](https://www.hsi.com.hk/static/uploads/contents/en/news/indexChgNotice/20260622T163141.pdf) | Ad-hoc HSCI removal | Removes 1448 from HSCI effective 2026-06-23 |
| [2026-07-02 suspension notice](https://www.hsi.com.hk/static/uploads/contents/en/news/indexChgNotice/20260702T163000.pdf) | Ad-hoc HSCI removals | Removes 754, 2627 and 2629 from HSCI effective 2026-07-10 |

The HSCI live response advertises historical workbook links, but both current HSCI historical links return 404. HSI and HSTECH historical links are available; HSCI history therefore needs the review-file pipeline plus the legacy backfill.

The February 2021 review workbook is an encrypted `.xls` file. The official press-release PDF is a viable free fallback for that cycle. The May and August 2021 `.xls` files are readable with an old-format Excel parser; later files use either legacy workbook sections or a flat `Review Result` sheet.

## Legacy Research evidence

Primary files:

- [Processed HSCI history](/Users/henrywzh/Desktop/Quant/Research/data/processed/hsci_components_history.csv)
- [Research ticker master](/Users/henrywzh/Desktop/Quant/Research/data/processed/hsci_ticker_master.csv)
- [Legacy HSCI workbook](/Users/henrywzh/Desktop/Quant/Research/data/raw/history_hsci.xlsx)
- [Research HSCI replay implementation](/Users/henrywzh/Desktop/Quant/Research/src/qresearch/universe/hsci.py)

Observed properties of the processed history:

- 1,637 rows;
- 2008-09-08 through 2026-01-15;
- 926 Add rows and 711 Delete rows;
- no exact duplicate rows found;
- no invalid effective dates or invalid numeric stock codes found;
- sector sheets are mixed into the same event log.

The last point is the critical risk. The existing replay logic maps every sector-sheet Add/Delete to a generic action and then ignores the sheet when building a membership mask. Same-day sector migrations can therefore become false membership exits or false turnover.

## Quarterly review reconciliation

Official event counts are HSCI total-index events only. `sector_clean` means that same-day Add/Delete pairs in the Research log were identified as sector migrations and removed from the total-index comparison. `next_day` indicates that Research used the next trading day rather than the official effective date.

| Official effective date | Official Add/Delete | Research comparison | Result |
|---|---:|---|---|
| 2021-03-15 | 36 / 29 | exact | raw exact |
| 2021-06-07 | 4 / 0 | exact | raw exact |
| 2021-09-06 | 17 / 22 | exact | raw exact |
| 2021-12-06 | 3 / 0 | exact | raw exact |
| 2022-03-07 | 29 / 12 | exact | raw exact |
| 2022-06-13 | 1 / 0 | exact | raw exact |
| 2022-09-05 | 24 / 14 | sector_clean exact | one sector migration pair |
| 2022-12-05 | 3 / 0 | exact | raw exact |
| 2023-03-13 | 35 / 28 | sector_clean exact | one sector migration pair |
| 2023-06-05 | 1 / 0 | exact | raw exact |
| 2023-09-04 | 22 / 27 | next_day sector_clean | Research activates on 2023-09-05 |
| 2023-12-04 | 2 / 0 | exact | raw exact |
| 2024-03-04 | 25 / 29 | exception | Research misses HSCI removal 6878; also contains sector-only 1797 transfer |
| 2024-06-11 | 1 / 0 | exact | raw exact |
| 2024-09-09 | 38 / 29 | exception | Research activates on 2024-09-10 and misses HSCI addition 2459; 14 sector migrations are present |
| 2024-12-09 | 2 / 0 | exact | raw exact |
| 2025-03-10 | 29 / 41 | exact | raw exact |
| 2025-06-09 | 3 / 0 | exact | raw exact |
| 2025-09-08 | 24 / 22 | sector_clean exact | four sector migration pairs |
| 2025-12-08 | 6 / 0 | exact | raw exact |
| 2026-03-09 | 53 / 28 | stale | absent from Research |
| 2026-06-08 | 7 / 0 | stale | absent from Research |

This is a reconciliation of source events, not an approval to use the legacy replay implementation unchanged.

## Current snapshot validation

The 2026-06-08 official review reported 538 HSCI constituents. The subsequent official ad-hoc notices removed four HSCI constituents:

```text
538 - 1 (1448) - 3 (754, 2627, 2629) = 534
```

The result matches the current official live snapshot exactly. This validates the combination of scheduled review events and at least the latest ad-hoc HSCI removals.

## Canonical event contract

The raw source event and the canonical semantic event should remain separate.

### Raw source event

```text
source_document_id
source_url
retrieved_at
published_at
content_hash
source_format
source_sheet
source_row
raw_index_code
raw_action
raw_security_code
raw_company_name
```

### Canonical event

```text
event_id
security_id
ticker
index_code
event_type
official_effective_date
activation_trading_date
announcement_at
from_sector
to_sector
reason
source_document_id
is_inferred
confidence
review_status
```

Recommended mutually exclusive `event_type` values:

```text
HSCI_MEMBERSHIP_ADD
HSCI_MEMBERSHIP_REMOVE
SECTOR_MIGRATION
NAME_CHANGE
TICKER_CHANGE
ENTITY_REPLACEMENT
SUSPENSION_REMOVAL
PRIVATISATION_REMOVAL
DELISTING_REMOVAL
FAST_ENTRY
```

`official_effective_date` must not be silently overwritten by a locally chosen trading date. Both dates should be retained until the execution convention is explicitly selected and tested.

## Automation design

1. Fetch `notices.json` on a scheduled cadence and use URL plus content hash as the idempotency key.
2. Classify new documents as quarterly review workbook, ad-hoc constituent PDF, appendix workbook, or irrelevant notice.
3. Parse quarterly workbooks with format-specific handlers:
   - encrypted February 2021 workbook: official PDF fallback;
   - legacy `.xls` and legacy benchmark sheets: section parser;
   - modern `.xlsx`: `Review Result` parser.
4. For quarterly workbooks, use only `Index Code = HSCI` for total-index membership. Store sector rows separately.
5. Parse ad-hoc PDFs with a deterministic PDF-text/table parser. Any missing effective date, ambiguous code, or failed table extraction goes to a manual-review queue; it must not be silently inferred. Keep explicit review decisions in a separate, non-canonical decision file until independently approved.
6. Normalize stock codes to four-digit `.HK` tickers while preserving the raw code and any cross-market suffix.
7. Build non-overlapping PIT membership intervals from canonical HSCI membership events.
8. Validate the latest interval state against the live HSCI snapshot by exact set comparison, not count only.

## Automated quality gates

The collector should fail publication when any of the following occurs:

- a review document cannot be parsed;
- the same document hash changes unexpectedly;
- an HSCI event has an unknown action or security code;
- an interval overlaps another interval for the same security and index;
- a sector migration changes the HSCI membership mask;
- the reconstructed current set differs from the live HSCI set;
- a stale source has passed its freshness SLA;
- an ad-hoc PDF is classified as irrelevant without a recorded reason;
- a security code is reused without an entity-resolution decision.

## Remaining known gaps

- Historical HSCI workbooks advertised by the official live endpoint are currently unavailable.
- The 2008 Research seed and pre-2021 history remain legacy data with incomplete provenance.
- The full ad-hoc PDF archive still needs human review and scope confirmation before any candidate or decision can be promoted to canonical PIT events.
- The provisional seed still contains legacy Research-derived membership and is not an official historical seed.
- Entity replacement and ticker reuse require a security master keyed by more than ticker alone.
- Effective-date timing needs a documented execution convention and explicit tests against the trading calendar.

Until these gaps are handled, the legacy Research replay should not be used as the canonical universe for news or factor backtests.
