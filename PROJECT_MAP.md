# PROJECT_MAP

## 📅 Daily Progress
- Added the `provider_adoption_data` ingestion stack, including GitHub/PyPI collectors, storage, tests, and daily plus backfill GitHub Actions that persist raw and normalized outputs.
- Reworked the dashboard to treat provider adoption as a first-class domain, simplified the provider view, and invalidated cached state when underlying data files change.
- Expanded OpenRouter app monitoring to include Hermes Agent and refreshed app ranking, trending, usage, and top-model datasets plus related parser coverage.

## 🏗️ System Architecture
```mermaid
graph TD
    PAD[".github/workflows/provider-adoption-daily.yml"] --> PACLI["src/provider_adoption_data/cli.py"]
    PAB[".github/workflows/provider-adoption-backfill.yml"] --> PACLI
    PACLI --> PAPIPE["src/provider_adoption_data/pipeline.py"]
    PAPIPE --> PACFG["src/provider_adoption_data/sources/config.py"]
    PAPIPE --> PAGH["src/provider_adoption_data/sources/github.py"]
    PAPIPE --> PAPYPI["src/provider_adoption_data/sources/pypi.py"]
    PAPIPE --> PASTORE["src/provider_adoption_data/storage.py"]
    PAGH --> GHAPI["GitHub Search and Contents APIs"]
    PAPYPI --> PYPIAPI["PyPIStats API"]
    PASTORE --> PARAW["data/raw/provider_adoption"]
    PASTORE --> PANORM["data/normalized/provider_adoption"]

    ORCLI["src/openrouter_data/cli.py"] --> ORPIPE["src/openrouter_data/pipeline.py"]
    ORPIPE --> ORAPPS["src/openrouter_data/sources/apps.py"]
    ORAPPS --> ORWEB["openrouter.ai apps pages"]
    ORPIPE --> ORNORM["data/normalized/openrouter"]

    GTCLI["src/github_trending_data/cli.py"] --> GTPIPE["src/github_trending_data/pipeline.py"]
    GTPIPE --> GTNORM["data/normalized/github_trending"]

    PANORM --> DDATA["dashboard/data.py"]
    ORNORM --> DDATA
    GTNORM --> DDATA
    DDATA --> DCHECKS["dashboard/checks.py"]
    DDATA --> DAPP["dashboard/app.py"]
    DCHECKS --> DAPP

    TPA["tests/test_provider_adoption_pipeline.py"] --> PAPIPE
    TDA["tests/test_dashboard_data.py"] --> DDATA
    TAPP["tests/test_apps_pipeline.py"] --> ORAPPS
```

## 🧠 Context Memo
The provider-adoption pipeline is intentionally split into candidate repos, first-match signals, repo rollups, and derived momentum. That keeps the raw evidence auditable before it is compressed into a scoring layer, which matters because the GitHub side is heuristic and needs a clear path from search hit to final metric.

The GitHub collector only searches a few language buckets and a bounded set of likely files per repo. That is a deliberate API-budget and precision tradeoff: broad codebase scans would be expensive and would increase false positives, while the current path list still captures the highest-signal dependency, import, env-var, and model-name indicators.

The dashboard cache now fingerprints files under both `data/raw` and `data/normalized` before loading state. Without that signature, Streamlit could keep serving stale provider-adoption or app views even after a workflow committed fresh datasets.

The Hermes Agent monitor in `src/openrouter_data/sources/apps.py` tries the canonical app detail page first and then falls back to the origin-filtered `/apps` URL. That fallback exists because OpenRouter app detail routing is not always stable, but the parser still needs a page that exposes the same analytics payload structure.

## 🔗 Obsidian Links
- No new `.md` files were created in the last 24 hours.
- `README.md` was updated to document the new provider-adoption commands, datasets, and workflow entry points; it is the main note that now links the operational CLIs to `src/provider_adoption_data/`, `src/openrouter_data/`, and `dashboard/app.py`.
