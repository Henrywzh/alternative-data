# Asia Markets Project Status

This file is a short, human-maintained handoff for the next agent. It is not a
replacement for the operating manual or generated source-status JSON.

## Current state

- Production surface: Cloudflare Pages, non-Streamlit dashboard.
- Canonical financial-data sibling: `/Users/henrywzh/Desktop/Quant/financial-data`;
  see `REPO_BRIDGE.md` for the shared contract.
- Live sector roster: 8 sectors; see `apps/asia-markets-dashboard/sectors.json`.
- English and Chinese hub/data-status pages are published.
- Sector artifacts are generated as portable HTML from `.generated/*.json`.
- The dashboard has explicit month/year chart ticks and visible copy-title
  controls in the current packaging path.
- The project contains both historical time series and current snapshots. Do
  not treat every non-empty dataset as a trend.

## Recent completed work

- China listed airline monthly operating data is wired into transport: passenger
  traffic, ASK, RPK, load factor and regional split.
- Dashboard source-status pages were updated and Chinese labels/caveats were
  localized.
- Store-footprint, Google Trends and other planned integrations remain separate
  until their source history and data flow are validated.
- Real-estate dashboard work includes agency transaction pulse, 28Hse EPI/ERI,
  Land Registry statistics, HKMA mortgage measures, Buildings Department data
  and REIT/property trend series.

## Open decisions / known limitations

- The planned Asia finance universe is documented in the sibling repo but is
  not active collection data. Futu (`FUTU`), Tiger (`TIGR`), CITIC Securities
  (`6030.HK`), China Merchants Securities (`6099.HK`), CICC (`3908.HK`), GF
  (`1776.HK`), CSC (`6066.HK`), Guotai Haitong (`2611.HK`) and East Money
  (`300059.SZ`) require a market-aware financial-data expansion before being
  wired into the dashboard.
- Buildings Department Md52–Md56 charts/tables are current-month snapshots,
  not historical MoM/YoY series. `Md52` demolition consents supply project
  counts only, not units or floor area. `bd_monthly_stats` is a different
  Md11–Md17 dataset and currently retains unlabelled numeric arrays.
- The current monthly-digest fetch archives 20 Mdxx XLS files. Most of those
  are raw-only archival coverage, not normalized analytical datasets.
- Buildings Department coverage should eventually be split into distinct
  source-coverage rows for raw Mdxx archival files, historical Md11–Md17
  monthly statistics and current Md52–Md56 project-lifecycle snapshots.
- Source coverage for newer feeds currently uses `Live at build time` when a
  build fetched rows, but often leaves `latest_observation` as `—`. This should
  be improved to expose actual as-of dates and age where possible.
- Weekly/daily chart labels must preserve distinct points while showing a year;
  do not solve this by aggregating the data to monthly grain.
- Most store-footprint companies have only one or two dated snapshots; present
  them as footprint snapshots rather than trends.

## Agent handoff checklist

Before starting a new task:

1. Read `OPERATING_MANUAL.md` and `DATA_CATALOG.md`.
2. Check `git status --short` for existing work.
3. Identify the sector roster entry, builder, artifact and status file.
4. Decide whether the requested metric is a time series, snapshot, catalog
   record or research-only item.
5. Update this file if the task changes the project state or resolves one of
   the limitations above.
