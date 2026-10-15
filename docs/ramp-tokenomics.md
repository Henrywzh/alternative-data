# Ramp Tokenomics

## Collection and publication

The existing `.github/workflows/ramp-monthly.yml` workflow checks Ramp at
**05:00 UTC Monday and Thursday**. The filename is retained to preserve its
Actions history. GitHub scheduled runs may start late.

```sh
python -m ramp_data.cli --base-dir . tokenomics
```

The collector reads `tokenVolumes` and `tokenPrices` from the public AI Index
server-rendered payload, using the existing HTTP transport and RSC decoder.
It does not need a browser or API key. Its workflow step runs even if an
earlier monthly-index or filter-mode step failed. All Tokenomics validation
passes before any normalized Tokenomics table is written. A Tokenomics
failure remains visible as a failed workflow, while other successful datasets
can still be committed by the existing commit step.

Normalized Parquet files live under `data/normalized/ramp/` on `main`.
The Streamlit **Ramp → Tokenomics** tab uses the existing runtime GitHub data
loader and remote data SHA cache key. Code deployment continues through
`streamlit-deploy`; no extra application or data publication branch is needed.

## Dataset contracts

| Dataset | Observation grain | Values and units |
| --- | --- | --- |
| `ramp_ai_token_activity` | Monday–Sunday week × metric × maker × raw model series | `metric_key=token_volume`: tokens; `token_spend`: USD |
| `ramp_ai_token_prices` | Daily window-end date × maker × token type | `token_cost_usd_7d`: rolling seven-day USD; `token_count_7d`: corresponding tokens |
| `ramp_ai_token_activity_vintages` | Activity natural key × capture timestamp | Captured versions of activity values and labels |
| `ramp_ai_token_prices_vintages` | Price natural key × capture timestamp | Captured numerator and denominator versions |

The exact fields and natural keys are defined in `src/ramp_data/schemas.py`.
Each row carries source URL, run ID and capture time. Existing observation
keys are revised by upsert; historical observations absent from a later
payload are retained. The latest table is therefore accumulated history,
not a statement of current provider membership.

Vintages start with our first capture on **2026-10-15**. Earlier observation
dates are backfilled source history, not proof that those values were
available at the time. Changed values append a new version; unchanged
values keep their original provenance and do not add versions.

## Interpretation and coverage

[Ramp's source and methodology](https://ramp.com/data/ai-index?metric=token-spend&detail=maker&mode=volume)
describe connected-provider usage and billing among businesses using Ramp
Token Spend Management (TSM). This differs from the monthly adoption-index
cohort. It is not representative of total Ramp AI spend and cannot be used as
provider revenue or ARR.

At initial collection, activity spans weeks ending 2025-01-12 through
2026-10-11: 19,156 observations, 14 makers, 809 raw model identifiers.
Identifiers include aliases and zero rows; 809 is **not** a count of unique
underlying models. The dashboard retains maker plus raw series key for model
selection and sums the reported model rows for maker views. It does not
deduplicate aliases by display name.

Spend and volume have different row coverage. Their weekly tables must not
be divided to invent model prices. The dedicated price table initially has
3,894 observations from 2025-01-01 through 2026-10-11, covering OpenAI and
Anthropic for `all_tokens`, `uncached_input` and `output`. It does not publish
model-level prices.

Effective USD per million tokens is:

`sum(token_cost_usd_7d) / sum(token_count_7d) * 1_000_000`

Each date is the end of its own overlapping seven-day window; never sum
daily anchors to produce monthly spend. A zero denominator yields missing
price. All-token prices also reflect the mix of cached input, uncached input
and output, so a movement need not imply a list-price change.

## Quality and display

The pre-write gate rejects missing dimensions, duplicate natural keys,
non-finite or negative values, future observations, malformed weekly windows,
unexpected metrics/token types, incomplete price token-type coverage per
maker, and positive cost with a zero denominator. Minimum row counts are
500 activity and 100 price observations. Both activity metrics and each
maker/token-type price group must have observations within 21 days, allowing
for source latency and one missed poll. The run manifest records dates per
breakdown. A fresh fetch never changes observation dates.

Charts preserve missing values as gaps and reported zeros as zero. Shares
use the full reported sample before chart-series selection. Latest tables
show missing latest-period values rather than carrying older numbers
forward. Capture time is labelled separately from observation date.

No new fields are added to `investment_feed.v1` by this change. Market Recap
can consume the committed Parquet tables through its existing alternative-data
adapter after its own consumer changes; it does not acquire Tokenomics
automatically from this producer update.
