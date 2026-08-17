# Airline Official Filing Watch Design

## Objective

Add a point-in-time evidence layer that independently verifies whether each of
the six mainland airline groups has published its 1H2026 interim report. The
existing 10jqka calendar remains a scheduled-date discovery source and must
not be overwritten or treated as the official filing.

## Design

`airline_official_filing_watch.csv` will keep one row per company and retrieval
snapshot. The row will carry the scheduled date from the existing calendar,
the CNINFO query cutoff, whether a matching full interim report was found, the
official announcement date, announcement ID/title and the static.cninfo PDF
URL. A missing match means `official_not_found` at that retrieval cutoff; it
does not mean that the issuer has permanently failed to disclose.

The collector will use CNINFO's public announcement query with the issuer
stock code and org ID, restrict the category to half-year reports, and match
the 2026 half-year report title. If both a full report and an abstract are
returned, the full report is preferred. Historical rows are append-only by
`ticker + snapshot_date`, replacing only an identical same-day snapshot.

## Integration and safety

The layer gets its own CLI command and pipeline quality specification. It will
not change pair direction, valuation, guidance status or the scheduled-date
calendar. Its source note will explicitly distinguish official evidence from
public discovery and state that the absence result is query-scoped.

## Verification

Unit tests will cover title matching, full-report preference, announcement-time
normalization, no-match semantics, duplicate snapshot merging and the current
six-company output. The full aviation test suite and Python compilation check
must pass after the change.
