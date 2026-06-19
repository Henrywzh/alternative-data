# USGS Minerals Extraction Design

## Objective

Build a simple, repeatable USGS-only extraction pipeline that ingests a Mineral Commodity Summaries PDF, starting with `/Users/henrywzh/Desktop/mcs2026.pdf`, and produces structured datasets that can be rerun for future editions such as 2027 without redesigning the data model.

## Project Boundaries

This first sub-project is intentionally narrow.

Included:
- Ingest one USGS Mineral Commodity Summaries PDF.
- Extract the list of mineral commodities covered by the report.
- Produce a stable mineral master table.
- Produce separate tables for applications and metrics derived from the PDF.
- Write outputs as CSV and parquet.
- Add lightweight validation to make reruns trustworthy.

Excluded for this phase:
- External price history sources.
- Equity/security mappings.
- Country-level producer ownership graphs.
- Non-USGS enrichment.
- A full importance-ranking methodology.
- Manual annotation workflows beyond small parser overrides if needed.

## Why This Shape

The project needs a foundation for 2027 and later, but it should stay simple. The design therefore separates stable mineral identity data from changing or multi-valued facts.

This avoids a wide, fragile table and gives us room to add:
- multiple report years,
- multiple metrics per mineral,
- revised extraction logic,
- later enrichment from market or equity data sources.

## Recommended Approach

Use a text-first extraction pipeline based on `pdftotext`.

Rationale:
- simple to rerun,
- easy to inspect,
- fits the current repo style of source-specific extract/clean/store pipelines,
- good enough for a structured first pass because the USGS report has a predictable table of contents and consistent two-page mineral summaries.

We are explicitly not using a layout-heavy or vision-heavy parser in v1 because that adds complexity before we know it is necessary.

## Source Characteristics

Primary source:
- `/Users/henrywzh/Desktop/mcs2026.pdf`

Relevant structure observed in the 2026 report:
- front matter with contents, introduction, critical minerals update, and summary tables,
- one two-page section per mineral commodity,
- consistent section titles that can be used as extraction anchors.

This structure suggests two parser layers:
- report-level parsing for contents and summary sections,
- mineral-section parsing for per-commodity data.

## Data Model

### 1. `minerals_master`

Purpose:
- stable identity table, one row per mineral commodity in the report.

Initial fields:
- `mineral_id`: stable slug derived from the normalized mineral name
- `mineral_name`: normalized display name used by the project
- `usgs_section_name`: exact section title from the report
- `category`: broad classification such as `metal`, `industrial_mineral`, `rare_earth`, or `other`
- `is_critical_mineral_2025`: boolean based on the report's final 2025 critical minerals list
- `notes`: optional parser or normalization notes

Rules:
- keep this table small and stable,
- do not store long text summaries here,
- do not store year-varying metrics here.

### 2. `mineral_applications`

Purpose:
- store one-to-many application or use statements for each mineral.

Initial fields:
- `mineral_id`
- `application_text`: extracted or normalized application statement
- `source_year`: report year, starting with `2026`
- `source_type`: fixed value such as `usgs_mcs`
- `source_section_name`
- `source_page_hint`: optional page number or page range if available
- `extraction_confidence`: simple label such as `high`, `medium`, `low`

Rules:
- one mineral can have multiple application rows,
- text can be lightly normalized, but the initial meaning should stay close to the source,
- no attempt to force a taxonomy in v1.

### 3. `mineral_metrics`

Purpose:
- store year-based or year-pair-based numeric and categorical facts for a mineral.

Initial fields:
- `mineral_id`
- `metric_name`
- `metric_value`
- `metric_unit`
- `metric_period`
- `metric_year`
- `comparison_year`
- `source_year`
- `source_type`
- `source_section_name`
- `source_page_hint`
- `notes`

Expected v1 metric coverage:
- `net_import_reliance`
- `price_change_pct_2024_2025`
- other clearly extractable USGS metrics only if they are reliable and consistently parsed

Rules:
- keep metric names normalized and enumerable,
- support both single-year and year-pair metrics,
- allow null `comparison_year` for point-in-time metrics.

## Output Artifacts

The source of truth inside the repo should be flat files:
- CSV for inspection and debugging
- parquet for downstream analysis

Proposed output layout:
- `data/raw/minerals_usgs/<report_year>/` for source text intermediates
- `data/processed/minerals_usgs/<report_year>/minerals_master.csv`
- `data/processed/minerals_usgs/<report_year>/minerals_master.parquet`
- `data/processed/minerals_usgs/<report_year>/mineral_applications.csv`
- `data/processed/minerals_usgs/<report_year>/mineral_applications.parquet`
- `data/processed/minerals_usgs/<report_year>/mineral_metrics.csv`
- `data/processed/minerals_usgs/<report_year>/mineral_metrics.parquet`

## Pipeline Design

### Input Stage

Accept a PDF path and a report year.

Responsibilities:
- confirm the PDF exists,
- create an intermediate text extraction artifact,
- record lightweight metadata such as source filename and report year.

Expected intermediate artifact:
- extracted plain text under `data/raw/minerals_usgs/<report_year>/`

### Parsing Stage

Split into three responsibilities:

1. Report parser
- read contents and front-matter sections,
- locate mineral section names,
- identify critical-mineral list references and summary tables that may contain import-reliance and price information.

2. Mineral section parser
- split the extracted text into per-mineral sections,
- normalize section names into stable `mineral_id` values,
- extract applications/uses from each section.

3. Metric parser
- extract only metrics that can be parsed with clear rules,
- attach period metadata,
- preserve source context for traceability.

### Normalization Stage

Responsibilities:
- normalize mineral names,
- map section names to categories,
- standardize metric names and units,
- de-duplicate rows produced by parsing noise.

This is where project-specific conventions live, not in the raw parser.

### Storage Stage

Responsibilities:
- materialize each output table,
- write both CSV and parquet,
- keep schemas stable across reruns.

### Validation Stage

Minimum checks:
- expected mineral count matches the contents list,
- no duplicate `mineral_id` values in `minerals_master`,
- required columns are non-null where mandated,
- metric names belong to an allowed set,
- output files are written successfully.

If any of these fail, the CLI should exit non-zero.

## Repo Integration

The existing repo uses small source-oriented packages with `models`, `pipeline`, `storage`, `cli`, and optional `sources` modules. The new work should follow that pattern.

Proposed package:
- `src/minerals_usgs_data/`

Expected modules:
- `src/minerals_usgs_data/__init__.py`
- `src/minerals_usgs_data/models.py`
- `src/minerals_usgs_data/pipeline.py`
- `src/minerals_usgs_data/storage.py`
- `src/minerals_usgs_data/cli.py`
- `src/minerals_usgs_data/sources/__init__.py`
- `src/minerals_usgs_data/sources/pdf_text.py`
- `src/minerals_usgs_data/sources/parser.py`
- `src/minerals_usgs_data/sources/config.py`

Expected tests:
- parser unit tests for section splitting and name normalization,
- metric extraction tests for known sample text blocks,
- pipeline smoke test for output creation,
- validation tests for missing or duplicate minerals.

## Naming and Identity

`mineral_id` should be stable across editions when the underlying commodity is the same.

Examples:
- `rare_earths`
- `rare_earths_heavy`
- `iron_ore`
- `bauxite_and_alumina`

Rules:
- derive from normalized USGS section titles,
- prefer stability over perfect prettiness,
- keep the original USGS section label in `usgs_section_name`.

## Category Strategy

Use a small project-owned category set in v1.

Suggested initial values:
- `metal`
- `industrial_mineral`
- `rare_earth`
- `fuel_or_related`
- `other`

This is intentionally coarse. It is enough to support browsing and joins now without inventing a deep taxonomy too early.

## Error Handling

The pipeline should fail loudly when:
- the PDF cannot be read,
- no mineral sections are detected,
- the contents list and parsed sections disagree materially,
- required output files cannot be written.

The pipeline should tolerate and log:
- missing application text for some minerals,
- missing metrics for some minerals,
- minor formatting noise in extracted text.

## Testing Strategy

Testing should focus on determinism and rerunnability, not exhaustive NLP correctness.

Priority tests:
- normalization of mineral names into stable ids,
- section boundary detection from extracted text,
- extraction of critical-mineral flags,
- extraction of at least one known application from a sample mineral section,
- validation failure on duplicate master rows,
- successful writing of CSV and parquet outputs.

## Non-Goals for the First Implementation

The first implementation should not attempt to:
- infer missing metrics from narrative text if the source is ambiguous,
- build a full ontology of applications,
- rank minerals by investment or geopolitical importance,
- integrate price-history APIs or market data vendors,
- map equities or producers.

## Success Criteria

This first sub-project is successful if:
- a single command can ingest the 2026 USGS PDF,
- the repo produces the three agreed output tables,
- outputs are written in CSV and parquet,
- validations catch obvious extraction breakage,
- the design remains reusable for the 2027 report with minimal code changes.

## Follow-On Work Enabled by This Design

Once this foundation exists, later sub-projects can add:
- external mineral price history series,
- importance ranking methodology,
- company and stock mappings by jurisdiction,
- multi-year joins across 2026 and 2027 reports,
- dashboards or notebooks for exploration.
