# Index & ETF Allocation Monitor — Streamlit Handoff

This is the durable handoff for the Asia Markets Index & ETF Allocation
Monitor. It describes the current implementation, not a future proposal.

Last verified against commit `f7df114a` on 2026-08-22.

## Product boundary

This monitor is a Streamlit-native research-terminal feature. Its production
read path is:

```text
market_monitor sources
  -> data/raw/market_monitor (local, ignored)
  -> data/normalized/market_monitor
  -> data/derived/market_monitor
  -> apps/asia-markets-dashboard/.generated/market-monitor-artifact*.json
  -> apps/asia-markets-streamlit/app.py
```

The market-monitor artifact is a shared JSON read contract, but the monitor is
not a Cloudflare sector in V1. Do not add it to `sectors.json`,
`package-dashboard.mjs` or the public Cloudflare roster unless the user
explicitly reopens that scope. Cloudflare's existing public sectors and this
private/interactive Streamlit feature have different product boundaries.

## What the data model means

The hierarchy is:

```text
exposure -> index -> ETF wrapper
```

`src/market_monitor/config.py` is the source of truth for exposure labels,
provider ownership and whether a series is an investable exposure or a
relative-strength benchmark. `src/market_monitor/metadata.py` is the source
of truth for the tracked ETF cohort.

Investable V1 exposures currently are:

| Group | Exposure | Chinese label | ETF wrappers |
|---|---|---|---:|
| China size | CSI 300 | 沪深300 | 3 |
| China size | CSI 500 | 中证500 | 3 |
| China size | CSI 1000 | 中证1000 | 3 |
| China style | SSE Dividend | 上证红利 | 1 |
| China style | STAR 50 | 科创50 | 2 |
| Hong Kong | Hang Seng Tech | 恒生科技 | 3 |
| Hong Kong | Hang Seng Index | 恒生指数 | 2 |
| Hong Kong | HK Dividend | 港股红利 | 3 |
| Hong Kong | HK Internet | 港股通互联网 | 3 |
| United States | Nasdaq 100 | 纳斯达克100 | 3 |
| United States | S&P 500 | 标普500 | 3 |
| Japan | Nikkei 225 | 日经225 | 2 |
| China / Korea | CN-KR Semiconductor | 中韩半导体 | 1 |
| Europe | Germany DAX | 德国DAX | 1 |

The current tracked cohort therefore has 14 investable exposures and 33 ETF
wrappers. The last three are QDII wrappers: they carry `premium_regime`
`qdii`, which shares the quota-constrained scoring curve rather than the
domestic one, because NAV timing, FX and quota make a small premium ordinary
for them and abnormal for a mainland ETF. Relative-strength-only benchmark legs are fetched and stored for
pair calculations but are not shown as extra ETF-selection cards. They
include ChiNext, China information/consumer-staples baskets, HK mid-cap and
H-shares, S&P 500 equal-weight, Russell small/growth/value and US sector
baskets.

## Sources and history

Provider ownership is declared per exposure and routed explicitly:

- Sina mainland index daily: China index exposures and mainland benchmark legs.
- Sina HK index daily: Hang Seng / Hong Kong index exposures and HK benchmark
  legs.
- CSI index daily: HK Internet (`931637`) and CN-KR Semiconductor (`931643`),
  using each index's own official family rather than a proxy series.
- Yahoo Finance: Nasdaq 100, S&P 500, Nikkei 225 (`^N225`), Germany DAX
  (`^GDAXI`) and US relative-strength benchmark legs. The provider symbol is
  declared per exposure as `yf_symbol`; deriving it from `index_id` once
  produced a request for "SPX", which returns an empty frame rather than an
  error.
- Eastmoney ETF spot: current market price, IOPV premium/discount, turnover,
  bid/ask and market-cap proxy.
- Eastmoney published NAV endpoint: historical close-vs-NAV premium backfill.
- Eastmoney issuer fee endpoint: management and custody fee reconciliation.

The pipeline stores five years of index history for rolling relative-signal
baselines and two years of ETF price/premium chart history. Historical premium
rows are primarily close versus published NAV; the latest days can use live
IOPV until the fund publishes NAV. The artifact carries `basis` so these
measurements are not silently presented as identical observations.

## Current Streamlit views

The market page has four functional layers:

1. **Market Leadership / 市场领导力** — tabbed: core broad-based indices,
   China/HK themes, US 11 GICS sectors, and all exposures. Series are rebased
   to 100, or compared through an interactive A/B ratio selector.
2. **Relative Regime / 相对强弱** — 12 configured pair summaries and their
   daily ratio history, including size, growth/value, risk-appetite, HK, US
   breadth and China-versus-US comparisons.
3. **By Index / 按指数查看** — select one exposure and see RSI, distance to
   MA20, average premium, 60-day drawdown, index price + MA20 + RSI subplot,
   all ETF wrapper prices rebased to 100, premium history and the wrapper
   table.
4. **Wrapper selection** — entry cost is premium plus half the bid/ask spread
   in basis points; peer rank is within the same exposure; liquidity is shown
   separately; hold rank uses management plus custody fee, size proxy and age.

### US sector board

The US 11 GICS Sectors tab is a separate subsystem and does not come from the
market-monitor artifact. `src/market_monitor/us_etf/` fetches the 11 Select
Sector SPDRs plus a pure-play sub-industry layer from Yahoo Finance, computes
Wilder RSI, 20/60-day returns, MA distance and 60-day drawdown, and publishes
one JSON to Cloudflare R2. Nothing it produces is committed: the local copy
lives in `data/cache/us_etf/`, which `.gitignore` covers.

Three properties of that board are load-bearing and easy to undo:

- Every plotted series shares one base date, taken from the calendar rather
  than from the shortest series. Rebasing each line against its own first row
  compares cumulative returns measured over different windows on one axis, and
  it starts doing that silently the moment one ticker returns short.
- A partial fetch is stated, not hidden. The artifact carries `coverage`, and
  the tab reports which sectors are missing rather than rendering four of
  eleven as though four were all there is.
- Missing metrics stay null. A fund without 20 sessions has no MA20; filling
  that with the latest close renders it as sitting exactly on its own average.

The loader tries R2, then the git-ignored local cache, then a live fetch, and
stamps which tier answered plus the cache age. A stale local read and a fresh
publish must not look alike.

At the last artifact check (`status: ready`, generated 2026-08-22), the
snapshot contained 14 technical rows, 33 wrapper rows, 12 pair summaries,
5,889 pair-history rows, 15,679 ETF price chart rows, 6,874 index price rows,
15,703 premium-history rows and 5 source-health rows. These are a verification
snapshot, not a promise that every future daily run has the same row count.

## Important semantics and caveats

- `entry_status` is an absolute eligibility gate (`ATTRACTIVE`, `FAIR`,
  `EXPENSIVE`, `AVOID`, `UNAVAILABLE`); `peer_rank` only says which wrapper
  is relatively cheapest within an exposure. A peer rank of 1 is not a buy
  recommendation.
- `aum_proxy` is Eastmoney market-cap-derived size, not verified NAV-based
  fund assets. Do not label it as authoritative AUM in research prose.
- Fees are issuer-published where available and are cached/reconciled; missing
  fees remain missing rather than becoming zero. Tracking difference/error is
  not yet in V1.
- QDII/cross-border premium is not interpreted with the same thresholds as a
  domestic ETF. NAV timing, FX, futures and quota effects remain visible in
  the wrapper caveat.
- The index and wrapper data are daily/session data, not intraday execution
  data. A run timestamp and an observation date are different things.
- SSE Dividend currently has only one tracked wrapper; HSI and STAR 50 have
  two. This is a cohort-coverage limitation, not evidence that rank #1 is
  informative.

## Known follow-ups found during the latest review

These are real implementation gaps and should not be forgotten:

1. `render_market_ratio_chart()` describes a reindexed ratio but currently
   plots raw `A / B`; if the product requirement remains “reindexed ratio”,
   rebase that ratio to 100 and update the title/caption together.
2. ~~The CSI source-health row uses the Sina latest-date variable.~~ Closed
   on 2026-08-22. The Sina HK row had the same defect, which this note did not
   record; both now date themselves by their own observations, so a stalled
   HK or CSI feed can no longer read as fresh for as long as the mainland one
   keeps updating.
3. Chinese exposure labels and controls are localized, but the wrapper table
   still exposes many English field names and ETF chart labels/fund names are
   not fully bilingual. Complete this as a UI localization task, not by
   changing the source identifiers.
4. Historical premium z-scores for each wrapper, verified NAV-based AUM and
   tracking difference remain V1.1 work.
5. ~~The US sector universe has no fee reconciliation.~~ Closed on
   2026-08-22. The concern was well founded: verifying the 27 entries against
   the issuers found **17 stale**, including all eleven SPDR sectors at 0.09%
   where State Street publishes 0.08%, and SOXX 0.35% against a published
   0.33%. `src/market_monitor/us_etf/reconcile.py` now checks the registry
   against the provider and reports a disagreement as an event rather than
   applying it silently. Eleven funds sharing one figure remains the shape
   that hides this: the fee component of the score differentiates nothing, so
   nothing looks wrong.

## Required validation after changes

```bash
PYTHONPATH=src python -m pytest tests/market_monitor -q
python -m pytest tests/test_asia_markets_wiring.py \
  tests/test_asia_markets_streamlit_contracts.py \
  tests/test_dashboard_history_policy.py -q
python -m py_compile apps/asia-markets-streamlit/app.py \
  apps/asia-markets-dashboard/scripts/build_market_monitor_artifact.py
```

If the artifact contract changes, rebuild both English and Chinese JSON
artifacts and run the Streamlit AppTest smoke suite in both languages. Do not
silently fall back to an older dataset or make a failed source look healthy.
