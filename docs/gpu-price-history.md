# GPU rental price history

GPU rental prices feed the GPU RENTAL page of the AI data dashboard
(`apps/ai-data-dashboard/`, see its README). The collector is
`src/gpu_prices/`; the page's tables and the chained rental indices are built
by `apps/ai-data-dashboard/gpu.py`.

```sh
PYTHONPATH=src:. python -m gpu_prices.cli --base-dir .
```

`.github/workflows/gpu-price-history-daily.yml` runs this daily at 06:17 UTC
and commits `data/normalized/gpu_price_history/<source>.parquet` and
`latest_run.json`. A source that fails keeps its last good table; the job
commits the sources that succeeded and then fails.

## Source contracts

| Source | Grain and measure | History and qualifications |
| --- | --- | --- |
| [GetDeploying](https://getdeploying.com/dataset/gpu-prices) | GPU slug × week starting Monday × billing type × reservation months; listing median and median of provider medians, USD/GPU-hour. | Published dataset is a rolling 53 weeks per model, updated daily. The latest week is provisional. The median is based on daily captures of priced offerings not marked sold out, including unknown or waitlisted availability. Models may mix configurations and regions. Counts are weekly medians, not unique counts accumulated across the week. CC BY 4.0; credit GetDeploying and link the license. |
| [R. Mittal, gpu-price-history](https://github.com/rahilmittal1/gpu-price-history/blob/main/data/rent/README.md) | Month × GPU × form factor × market segment; median advertised USD/GPU-hour and the published matched-provider chain index. | Reconstructed monthly history, not a point-in-time trading dataset. Chain links can use a median fallback, and some months have only one provider. Repository dataset is CC BY 4.0; underlying third-party sources retain their own terms. See [DATA_LICENSE.md](https://github.com/rahilmittal1/gpu-price-history/blob/main/DATA_LICENSE.md). |
| [Compute Screener](https://computescreener.com/methodology) | GPU × US Central date; standardized rental index in USD/GPU-hour, provider count, finality, weekly and restatement flags. | Latest day may be provisional. Before 2026-10-23, values are reconstructed; much early history is weekly and draws on GetDeploying. Some provider values may be carried forward. Thus its early history is not an independent cross-check of GetDeploying. Null index values remain null. CC BY 4.0 with attribution to Compute Screener (computescreener.com). |
| [Ornn](https://data.ornn.com/faq) | Transaction-based daily index, as described by Ornn, with its own GPU and contract definitions. | Its [usage terms](https://data.ornn.com/legal) restrict redistribution. The dashboard only links to Ornn; it does not store, republish, calculate with, or claim permission to embed its data. |

Quotes, standardized indices and Ornn's reported transaction-based prints
are different populations and should not be joined to calculate an implied
spread or discount. No data from these sources represents the entire market.

## Collection and validation

`gpu_prices.pipeline.refresh` collects each enabled public source independently.
Before each normalized write it checks required fields, natural-key uniqueness,
valid dates, nonnegative finite values, a minimum row floor and newest-date
regression against the previous capture. Replacement datasets are also
rejected when their row count falls by more than half. A failure is recorded
in `latest_run.json`, returns a nonzero CLI status and leaves that source's
last successful table intact. One source's failure does not prevent the other
sources from being fetched.

The weekly GetDeploying table upserts by source key and retains observations
that have left the source's rolling window. Changed source values replace the
current view. Raw response bytes are kept by SHA-256 under
`data/raw/gpu_price_history/` only on the machine that ran the refresh (raw
data is not committed, so a CI run discards them); every row carries its
capture timestamp and source hash. Reconstructed observations older than our first capture were not
necessarily known at their observation dates. The GitHub and Compute
Screener tables are replaced with their latest complete source payload, and
prior captured responses remain available by content hash. The most recent
attempt manifest records each source's status, URL, content hash, row count
and source date range. No guessed values or date interpolation are introduced.

## Rental index

The GPU page's headline indices (data center, frontier, prior generation) are
chained, matched-model indices over GetDeploying's weekly on-demand provider
medians: each week moves by the provider-weighted geometric mean of the price
relatives of chips listed by at least two providers in both weeks, so a chip
entering or leaving the listings does not move the level. A monthly version
over the Mittal history starts at the first month with four matched chips and
is omitted if that leaves under a year. Sources are never spliced together.

## Open items

- Confirm redistribution for every third-party dataset and derivative,
  including the historical dataset's underlying source terms. The site shows
  CC BY attribution for GetDeploying, R. Mittal and Compute Screener. Ornn
  stays link-only unless it grants explicit rights.
- The chip specs (BF16 TFLOPS, memory) in `gpu.py` have not been reviewed
  against a cited source.
- Review the thresholds against real outages and source restatements; monitor
  provider coverage, schema drift, partial weeks and non-final days.
