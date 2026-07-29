# Buildings Department Md52–Md56 Historical Backfill Design

## Goal

Provide a first-party, month-level historical supply-pipeline series from the
Hong Kong Buildings Department (BD) for Md52–Md56. The first delivery is a
stage-level aggregate series, not a claim that a project can be reliably
tracked across lifecycle stages.

## Evidence and source contract

- BD's Monthly Digest index publishes annual archives named `Md2005e.zip`
  through `Md2024e.zip`. Each sampled archive contains twelve monthly PDF
  digests named `MdYYYYMMe.pdf`.
- The monthly PDF has machine-readable text and detailed tables 5.2–5.6:
  demolition consents, plans approved, consent to commence, notices of
  commencement, and occupation permits.
- Current-month XLS files remain the preferred source for the existing
  project-snapshot parser. Historical PDFs are an independent, archival
  source format and must not be silently parsed by the XLS parser.

## Scope

1. Discover the annual archive URLs from the first-party digest index, with a
   deterministic fallback for 2005–2024. Fetch each annual ZIP once and retain
   every constituent PDF as an immutable raw snapshot.
2. Extract tables 5.2–5.6 from historical monthly PDFs with `pdfplumber`.
   Parse only the publication's aggregated table semantics required for a
   historical series: record count; domestic-unit count where published; and
   domestic/non-domestic floor area where published.
3. Emit one observation for each source month and stage. Use `None`, never
   zero, when a table does not publish a metric. In particular, Md52 carries a
   count only.
4. Preserve `observation_month`, official source URL, raw snapshot path,
   archive year, extraction method/version, and a parser confidence flag on
   every emitted observation. A monthly digest that contains an amendment is
   recorded as a revision observation for the month being amended, rather than
   combined implicitly with the digest-month total.
5. Use the series in the real-estate dashboard as a monthly trend. Keep the
   current XLS snapshot datasets available for project-level detail; do not
   repurpose them as historical observations.

## Explicit non-goals

- No entity resolution or cross-stage project matching.
- No attempt to infer unavailable Md52 units/floor area.
- No OCR fallback in this stage. A PDF that does not expose table text is
  surfaced as an unparsed document rather than guessed.
- No automatic full-history download in normal dashboard builds or the daily
  incomplete-source pipeline. A dedicated opt-in backfill command owns the
  potentially large historical download.

## Dataset contract

`bd_supply_pipeline_history` has one row per:

`observation_month × permit_stage × property_category × revision_status`

Required fields:

- `date` and `observation_month`: ISO month start, e.g. `2024-12-01`.
- `permit_stage`: one of the existing five user-facing stage names.
- `property_category`: `All`; historical aggregate extraction does not infer
  region or domestic/non-domestic project class from PDF layout.
- `total_projects_count`: count supplied by the detailed table.
- `total_domestic_units`, `total_domestic_gfa_sqm`,
  `total_non_domestic_gfa_sqm`, `total_domestic_ufa_sqm`, and
  `total_non_domestic_ufa_sqm`: source metrics or null when unpublished.
- `revision_status`: `original` or `amendment`.
- `parser_confidence`: `HIGH`, `MEDIUM`, or `LOW`.
- `source_agency`, `source_url`, `archive_year`, `raw_snapshot`, and
  `parser_version`.

The initial parser outputs `HIGH` only when table headings, table number, and
parseable totals are all present. Otherwise it emits no row for the table and
records the document as unparsed; it must never issue a plausible-looking
partial total.

## Design choices

### Chosen: aggregate PDF backfill, then dashboard history

It delivers 2005-to-present cycle analysis at the correct source grain while
containing the risks created by decades of layout changes. It also keeps raw
PDF lineage and makes later parser improvements reproducible.

### Rejected: XLS-only rolling history

It is simple but cannot answer the intended historic-cycle question and would
need years to build useful coverage.

### Deferred: project-level PDF extraction and lifecycle linkage

Historical detailed tables have wrapped addresses, amendments, and layouts
that vary by year. That work needs a separate entity-resolution design and
manual validation sample; it is not a safe prerequisite for monthly stage
aggregates.

## Quality gates

- Archive discovery must produce 12 PDFs for a complete annual archive and
  reject unexpected names.
- A synthetic text fixture verifies every stage's parser and metric null
  semantics.
- A 2005 and a 2024 official PDF fixture are smoke-tested before a full
  backfill run; both must identify Tables 5.2–5.6.
- No duplicate key on `observation_month`, `permit_stage`,
  `property_category`, `revision_status`, and `source_url`.
- The backfill command reports month/table coverage, raw files saved, and
  low-confidence/unparsed documents; dashboard builds may use the latest
  normalized successful historical run but must not fetch archives.
