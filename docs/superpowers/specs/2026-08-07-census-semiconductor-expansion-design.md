# Census semiconductor trade expansion design

## Decision

Extend the existing `us_census_trade_data` package with three related
capabilities:

1. Enrich the existing national HS dataset with air, containerized-vessel and
   vessel value/weight fields.
2. Add a separate Port × HS monthly dataset.
3. Allow the same national and port collectors to query multiple partner
   countries for competitive comparisons.

## Data grain and keys

The existing `us_census_memory_imports_monthly` dataset remains one row per
`period × partner_country_code × hs_code`. Its natural key does not change.

The new `us_census_memory_imports_port_monthly` dataset is one row per
`period × port_code × partner_country_code × hs_code`. It stores port name,
general import value and air/containerized-vessel/vessel value and
shipping-weight measures. The Port-HS endpoint does not publish the national
consumption-value field, so the port table intentionally stores general value
only. Port rows are never merged into the national table.

## Access and security

Both endpoints use the existing `CENSUS_DATA_API_KEY` credential resolution.
Raw snapshot URLs are redacted and never contain the API key. Multiple partner
codes are sent as repeated Census query parameters and are preserved in the
normalized rows for attribution.

## Failure handling and validation

HTTP 204 responses become empty snapshots. Parser filters enforce the requested
HS/partner scope and skip non-detail rows. Storage validates natural-key
uniqueness, value presence, period coverage and port-row counts. Quantity fields
remain nullable when Census returns a sentinel unit such as `-`; shipping
weight is treated as a separate physical-volume proxy.

## Testing

Add fixture-backed parser/fetch tests for both endpoint shapes, repeated partner
filters, API-key redaction, port natural keys and pipeline upserts. Run the
focused Census, Taiwan MOPS and existing semiconductor regression tests before
reporting completion.

## Follow-up data-quality corrections

The MOPS JSON endpoint exposes the response retrieval timestamp, not the
original historical filing date. The normalized contract therefore keeps
`scraped_at` as retrieval metadata and leaves `filing_date` null for JSON
snapshots unless an independently verified publication date is available.
Missing MOPS month-over-month values are derived from adjacent normalized
monthly revenue observations and are marked as derived.

The scheduled MOPS update covers all registered companies by default. Census
updates fail validation when a requested month returns no usable rows, and the
raw `LAST_UPDATE` sentinels observed in the API response are normalized to
missing rather than treated as dates. Historical coverage and the TSMC
2026-06 gap are explicitly checked during the data refresh.
