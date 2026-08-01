# Asia Markets Streamlit V1

Private research-terminal V1 for the four currently connected Hong Kong sectors:

- Hong Kong Labour Market & Talent Policy
- Hong Kong Population & Migration
- Hong Kong Transport & Aviation (separate Cathay, China-listed-airline and MTR tabs; airline passenger/cargo/fleet/route signals)
- Global Crypto Market Context (stablecoin supply, DEX volume and Fear & Greed)

The app reads the existing source-backed artifacts from
`apps/asia-markets-dashboard/.generated/`. It does not fetch data during page
navigation.

Run from the repository root:

```bash
streamlit run apps/asia-markets-streamlit/app.py
```

The sidebar intentionally contains only the V1 scope: Overview, the four
sectors, Data Explorer and Source Health. The stablecoin/crypto page currently
shows global context indicators only; Hong Kong-local regulatory and adoption
signals remain future scope. Other markets, company explorer and cross-market
comparison are not connected yet.
