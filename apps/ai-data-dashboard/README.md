# AI data dashboard

A static site on Cloudflare Pages with five pages, grouped in the top menu:

| Group | Page | Data |
| --- | --- | --- |
| USAGE | OpenRouter | Daily per-model revenue estimates (`openrouter_derived`), the ARR nowcast and task spend |
| ADOPTION | Ramp | Ramp AI Index, PEPM, model share, vendor adoption, jobs study, and Tokenomics (`data/normalized/ramp/`) |
| ADOPTION | Downloads | PyPI, npm, Hugging Face and GitHub adoption (`provider_adoption`) |
| COMPUTE | Semis | Taiwan monthly revenue, Korea/Japan/HK chip trade, US PPI (`semiconductor_*`, `taiwan_*`, `us_census_trade`) |
| COMPUTE | GPU Rental | GetDeploying, R. Mittal and Compute Screener rental prices (`gpu_price_history`, see `docs/gpu-price-history.md`) |

It replaces these sections of the Streamlit dashboard, which still runs and
is untouched. The numbers come from the same code: `build.py` calls the
Streamlit sections' loaders and `compute_*` functions, so both show the same
values.

## Layout

- `web/`: the pages, one `index.html` each, plus `shared/ui.js` (top menu,
  subtabs, chart defaults, formats, sortable tables) and
  `shared/terminal.css`. Plain HTML and JavaScript; no build tooling.
  ECharts 5.5.1 is downloaded by the build (hash-checked, cached in
  `.cache/`) and served from the site, not from a CDN.
- `build.py`: copies `web/` to `dist/` and writes each page's `data.json`.
  Any page that fails fails the build.
- `gpu.py`: the GPU page's data, including the chained rental indices.
- `smoke.py`: opens every page and subtab of `dist/` in headless Chromium and
  fails on a script error, a console error, NaN/undefined on the page, or a
  chart that did not draw.
- `wrangler.toml`: the Pages project (`ai-data-dashboard`).

## Build and preview

From the repository root:

```sh
DATA_SOURCE=local PYTHONPATH=src:. python apps/ai-data-dashboard/build.py
python apps/ai-data-dashboard/smoke.py
python -m http.server 4331 --directory apps/ai-data-dashboard/dist
```

## Deploy

`.github/workflows/ai-data-dashboard-deploy.yml` builds, smoke-tests and runs
`wrangler pages deploy` at 11:23 and 23:23 UTC, on a push to main that changes
the site's code, and on a manual run. Data commits from the scraper workflows
use GITHUB_TOKEN and so cannot trigger it; the schedule picks them up. A failed
build or smoke test publishes nothing, so the last good site stays live.

The workflow needs two repository secrets, `CLOUDFLARE_API_TOKEN` (with
Cloudflare Pages: Edit) and `CLOUDFLARE_ACCOUNT_ID`, and the Pages project
must exist (`npx wrangler pages project create ai-data-dashboard
--production-branch main`, once).

## Data notes

- OpenRouter: a latest day under half the prior week's median is a partial
  scrape and is left out of the charts. In a month's first days the ARR
  nowcast cannot run, so the page shows the previous month instead, labelled.
- Ramp Tokenomics comes from Ramp's Token Spend Management customers, a sample
  that grows as customers connect providers, so levels are shown indexed and
  shares are the comparable series.
- Ramp's vendor adoption scale (0–1) is shown as published; its definition is
  not yet confirmed.
