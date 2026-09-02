# SHKP refresh contract

`run-shkp-refresh` is the bounded operational entry point for the SHKP
(0016.HK) workstream. It is designed for a weekly GitHub Actions run and can
also be run locally:

```bash
PYTHONPATH=src python -m src.hk_real_estate.cli run-shkp-refresh --skip-financial-data
```

The refresh does the following in order:

1. Refreshes the SHKP property directory, SRPE all-development index and
   pipeline disclosures. Deep annual-report, planning and project-site layers
   are reused when the bounded mode skips those network calls; they are never
   replaced by empty frames.
2. Refreshes current active SHKP candidate filing manifests. If no candidate
   is older than the configured refresh threshold, the step is recorded as
   `no_op`.
3. Parses a bounded recent batch of SRPE transaction registers, then
   consolidates all persisted scratch batches into deduplicated phase-month
   signals and the separate indicative-ownership layer.
4. Runs the research-only indicative sales model when signal inputs exist.
5. Builds the SHKP official financial-input model. If the private sibling
   `financial-data` DuckDB is available it is read read-only; otherwise the
   explicit official-only lane emits empty actual/consensus frames and visible
   warnings. No values are backfilled or fabricated.

Every run writes one immutable
`shkp_developer_tracking_refresh_status` snapshot with one row per step plus a
summary row. `status=success` means the step ran; `status=no_op` means the
queue was already current; `status=warning` records a known coverage gap; and
`status=failed` is reserved for a failed step. The command exits non-zero only
for required-step failures when strict mode is enabled.

## Durable CI outputs

`.github/workflows/hk-real-estate-shkp-refresh-weekly.yml` runs Monday and
commits a compact set of indexes, registries, current manifests, transaction
signals, refresh status, and official financial-input snapshots. Raw PDFs and
per-run disposable caches remain ignored. To include the private financial
data lane, configure a repository secret named
`FINANCIAL_DATA_REPO_TOKEN` with read access to `Henrywzh/financial-data`.

## Deliberate limits

The workflow does not claim complete legal ownership or revenue attribution.
SRPE activity is a project/contract leading indicator; a phase enters the
company-attributable lane only after a reviewed, date-bounded ownership
interval. Missing months remain unknown rather than zero, and a current
manifest no-op does not imply that no transaction occurred.
