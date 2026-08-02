# Asia Markets Streamlit V1

Private research-terminal V1 for the five currently connected Hong Kong sectors:

- Hong Kong Labour Market & Talent Policy
- Hong Kong Population & Migration
- Hong Kong Transport & Aviation (separate Cathay, China-listed-airline and MTR tabs; airline passenger/cargo/fleet/route signals)
- Hong Kong Commercial Aerospace (verified China launches, constellation inventory, SATCAT and Wikipedia attention)
- Global Crypto Market Context (stablecoin supply, DEX volume and Fear & Greed)

The app reads the existing source-backed artifacts from
`apps/asia-markets-dashboard/.generated/`. It does not fetch data during page
navigation.

Run from the repository root:

```bash
streamlit run apps/asia-markets-streamlit/app.py
```

The sidebar intentionally contains only the V1 scope: Overview, the five
sectors, Data Explorer and Source Health. The stablecoin/crypto page currently
shows global context indicators and validated regulatory/news attention layers;
Hong Kong-local on-chain adoption remains future scope. Other markets, company
explorer and cross-market comparison are not connected yet.

## Deploy on Streamlit Community Cloud

This app is ready to deploy from the `Henrywzh/alternative-data` GitHub
repository. In Streamlit Community Cloud, create a new app with:

- Repository: `Henrywzh/alternative-data`
- Branch: `main`
- Main file path: `apps/asia-markets-streamlit/app.py`
- Python version: 3.11 for local-environment parity, if available

The dependency file is next to the entrypoint at
`apps/asia-markets-streamlit/requirements.txt`. The app reads committed JSON
artifacts under `apps/asia-markets-dashboard/.generated/` and does not fetch
external data during page navigation, so no Secrets are required for this V1.
Never paste the repository-root `.config` file into Streamlit Cloud.

After the first deployment, pushes to the selected branch automatically trigger
an app update. A data refresh therefore needs the refreshed generated artifacts
to be committed to GitHub; changing only a local parquet or raw cache is not
enough for the hosted app.
