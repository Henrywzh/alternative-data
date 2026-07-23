# akshare Capability Audit for HK Equity Alt-Data

Companion to [asia-markets-hk-alt-data-sources.md](asia-markets-hk-alt-data-sources.md).
`akshare` is already a dependency of this repo (`pyproject.toml`) and already
used for HK/mainland spot quotes in
[src/minerals_signal_data/market_data.py](../src/minerals_signal_data/market_data.py)
(`ak.stock_hk_spot_em()`, `ak.stock_zh_a_spot_em()`). This is a full audit of
what else it offers for HK-specific research.

**Method:** pip-installed fresh (got 1.18.74) in a scratch venv and
cross-checked against the repo's actual installed version (1.18.64) —
findings matched on both. Real network calls were run against most
functions. **VERIFIED** below means real data came back in this session;
**DOC-ONLY** means only the docstring/signature was read, not executed.

## Correction to an earlier claim in this doc series

The alt-data-sources doc previously stated `stock_hsgt_north_net_flow_in_em`
and `stock_hsgt_south_net_flow_in_em` were confirmed free Stock-Connect
per-stock functions. **That was wrong — those functions do not exist** in
either akshare version tested (confirmed via `dir(ak)`). They were cited
from a web search summary, not tested directly, and this is exactly the
kind of gap direct verification catches. The correct function is
`stock_hsgt_hist_em(symbol='南向资金'|'北向资金')` — see below, verified
working with full history since 2014.

## What's genuinely strong

**HK company fundamentals — the best-covered category:**
| Function | What it returns | Status |
|---|---|---|
| `stock_financial_hk_report_em(stock, symbol='资产负债表'\|'利润表'\|'现金流量表', indicator)` | Balance sheet / income statement / cash flow, long/tidy format | **Verified** (1,124 rows tested) |
| `stock_financial_hk_analysis_indicator_em(symbol, indicator)` | 36 columns: EPS, BPS, ROE, ROA, margins, debt/current ratios, YoY/QoQ growth, by report period | **Verified** |
| `stock_hk_financial_indicator_em(symbol)` | Latest snapshot: EPS, dividend/share TTM, payout ratio, dividend yield TTM, market cap, P/E, P/B, ROE | **Verified** |
| `stock_hk_profit_forecast_et(symbol, indicator)` | Sell-side analyst estimates — broker, rating, target price, forecast EPS/net profit by fiscal year (source: etnet.com.hk) | **Verified** |
| `stock_individual_basic_info_hk_xq(symbol)` | Company profile via Xueqiu — legal name, industry, listing date | **Verified** |
| `stock_hk_dividend_payout_em(symbol)` | Clean dividend-event table: announcement date, fiscal year, DPS, distribution type, ex-date, record-date, payment date | **Verified** — directly answers "when does this company pay dividends" |
| `stock_hk_fhpx_detail_ths(symbol)` | Alternate/longer-history dividend detail (THS), flags stock-dividend cases | **Verified**, 93 rows back to 2004 on a test ticker |
| `stock_hk_valuation_baidu(symbol, indicator, period)` | Daily valuation time series (market cap tested; P/E, P/B available via `indicator` param) | **Verified**, 365 rows/year |
| `stock_hk_valuation_comparison_em` / `growth_comparison_em` / `scale_comparison_em` | Industry-peer comparison tables | DOC-ONLY |

**HK macro data — much richer than expected, all real historical series:**
| Function | Coverage | Status |
|---|---|---|
| `macro_china_hk_cpi()` | Monthly, back to 2008-01, 172 rows | **Verified** |
| `macro_china_hk_gbp()` *(name is a typo for GDP)* | Quarterly, back to 2008, 74 rows | **Verified** |
| `macro_china_hk_rate_of_unemployment()` | Monthly, back to 2008, 223 rows | **Verified** |
| `macro_china_hk_ppi()` | Quarterly manufacturing PPI YoY, 74 rows | **Verified** |
| `macro_china_hk_building_amount()` | Property transaction value, monthly since 2008 | **Verified** — relevant to the real-estate doc |
| `macro_china_hk_trade_diff_ratio()` | Trade balance YoY, monthly since 2008 | **Verified** |
| `macro_china_hk_market_info()` | **Daily HIBOR curve** (ON/1W/2W/1M/2M/3M/6M/1Y + day-over-day change), since 2017-03-20, 2,292 rows | **Verified — bonus find, directly relevant to the real-estate doc's HIBOR/mortgage-spread tracking** |

All sourced from eastmoney's economic calendar — one consistent interface
for numbers that would otherwise mean checking six different official HK
government sources individually.

**Stock Connect / fund flow — strong for aggregate, capped for per-stock history:**
| Function | What it does | Status |
|---|---|---|
| `stock_hsgt_hist_em(symbol='南向资金')` | Aggregate daily Southbound net buy, cumulative net buy, balance, aggregate holding value, plus **today's top-mover ticker** | **Verified**, 2,676 rows, **full history since 2014-11-17** |
| `stock_hsgt_fund_flow_summary_em()` | Today's snapshot split by SH/SZ Connect × North/South, net-buy, balance, advancers/decliners | **Verified** |
| `stock_hsgt_individual_em(symbol='00700')` | Per-stock Southbound holding time series, works directly with HK codes | **Verified working, but only ~2-year rolling window** (469 rows, no deeper history) — column labels have a copy-paste bug ("占A股百分比" on an HK ticker) but the data itself is correct |
| `stock_hsgt_stock_statistics_em(symbol='南向持股', start_date, end_date)` | All ~3,600 Southbound-held stocks per day: shares held, holding value, % of issued shares held via Connect | **Verified for recent dates (2026-07-15→22); FAILED for 2023/2020/2018 date ranges** — this endpoint is also rolling-window only, not full history |
| `stock_hsgt_hold_stock_em()` | (whatever it's supposed to return) | **BROKEN** — every parameter combination raised `TypeError`, reproduced on both akshare versions tested. Real bug in akshare itself, not an environment issue |

**Practical takeaway:** aggregate Southbound flow (`stock_hsgt_hist_em`) is
excellent — full history, works today. Per-stock Southbound *ownership
level* is capped at a ~2-year rolling window in both functions that
attempt it; there's currently no working akshare path to deep historical
per-stock Southbound holding data.

**Southbound-eligible universe:**
`stock_hk_ggt_components_em()` — **verified**, 613 rows, a live quote
snapshot of currently Southbound-Connect-eligible names. No inclusion/
exclusion date or historical membership — just today's list.

**HK REITs:** no dedicated REIT function, but confirmed all major HK REITs
(Link 00823, Champion 02778, Fortune 00778, Yuexiu 00405, Prosperity 00808,
Spring 01426, Sunlight 00435, SF REIT 02191, CMC REIT 01503, Champion's RMB
counter 87001) are just ordinary tickers in `stock_hk_spot_em()` — every
general function above (dividend history, financials, valuation) works on
them like any stock.

## What's confirmed broken or mislabeled — don't use as-is
1. **`stock_hsgt_hold_stock_em`** — broken in both akshare versions tested.
2. **`stock_ipo_hk_ths`** — runs without error, but returns *mainland
   A-share IPO data* (ChiNext/STAR codes, A-share lottery terminology)
   despite being named/branded as HK IPO data. Likely an akshare bug where
   the underlying source page changed. Do not use for HK IPO tracking.
3. **`stock_hk_gxl_lg()`** (HSI dividend yield via legulegu) — `JSONDecodeError`, source site issue.
4. `stock_hsgt_north_net_flow_in_em` / `stock_hsgt_south_net_flow_in_em` —
   **do not exist** (see correction above). Use `stock_hsgt_hist_em` instead.

## Confirmed gaps — no HK coverage at all
These all have mainland-only equivalents in akshare, confirmed by
signature/params (mainland report-period formats, SSE/SZSE/BSE-only
symbol choices, cninfo-sourced), with no HK option:
- **Insider/major-shareholder disclosure** — no SFC Disclosure-of-Interests
  equivalent. (`stock_gdfx_holding_analyse_em`, `stock_inner_trade_xq`, etc.
  are all mainland-only.)
- **Margin trading / securities lending** — `stock_margin_sse/szse/bse`
  family is mainland-exchange-specific only (expected, since HKEX doesn't
  publish aggregate margin data the way mainland exchanges do).
- **Sector/concept classification** — `stock_board_industry_*` /
  `stock_board_concept_*` are mainland A-share boards only. HK stocks only
  get an industry tag inside the company-profile functions, not a proper
  taxonomy.
- **Block trades** — `stock_dzjy_*` symbol choices are literally
  `{'A股','B股','基金','债券'}` — no HK option.
- **Buybacks** — `stock_repurchase_em()` is A-share only (5,363 rows, all
  mainland codes).
- **Rights issues / placements** — no HK function; mainland has
  `stock_allotment_cninfo`, `stock_xgsglb_em`, etc.
- **Per-stock news/announcements** (an HKEXnews equivalent) — no such
  function; `stock_notice_report` is cninfo/mainland only. Generic
  (non-ticker-scoped) global news wires exist as unstructured headline
  feeds (`stock_info_global_futu/ths/sina`) but would need text parsing to
  associate with a ticker.

## Bonus finds worth knowing about
- **`stock_hk_hot_rank_em()`** — **verified**, EM's HK "popularity ranking"
  (guba-attention-based), 100 rows — a possible retail-sentiment proxy.
- **`stock_zh_ah_daily` / `stock_zh_ah_name` / `stock_zh_ah_spot_em`** —
  DOC-ONLY but clearly built for **A+H dual-listed share pairs** — directly
  useful if tracking the AH premium as a signal.
- **`news_trade_notify_suspend_baidu(date)`** — DOC-ONLY trading-suspension
  calendar; scope (A-share vs. HK) not confirmed, worth a follow-up check
  since HK trading suspensions are a real research signal.
- **`stock_esg_msci_sina()` / `_rate_sina` / `_rft_sina` / `_zd_sina`** —
  DOC-ONLY ESG ratings from Sina; whether HK tickers are included wasn't
  tested.

## Alternatives worth knowing
- **`tushare`** — free but requires registration + API token (Chinese-only
  signup flow).
- **`baostock`** — free, zero registration at all, but mainland-A-share-
  focused; HK coverage unclear, not evaluated.

## Open follow-ups
- Whether ESG ratings and the trading-suspension calendar actually include
  HK tickers — not tested.
- Whether a deeper per-stock Southbound holding history exists anywhere
  else (HKEX's own site, a different akshare function not yet found, or a
  paid vendor) given both akshare paths cap out around 2 years.
