# News Sources and News Backtesting

**Status:** Research direction only; no implementation approved yet  
**Scope:** Free or already-available sources for the private research terminal  
**Primary objective:** Build a source-backed news layer for the future company decision page

## 1. Operating objective

The news layer should support two different uses:

1. **Research reading:** what happened to a company, sector or macro theme?
2. **Event research:** did a new article or disclosure contain information that was useful before the price reaction?

The target freshness is approximately ten minutes from source publication to local availability. This is a service-level objective, not a guarantee: the source may publish late, provide only a date rather than a timestamp, or revise an article after first publication.

Every item should preserve at least:

```text
article_id
source
source_class
source_url
published_at
observed_at
ingested_at
processed_at
ticker_or_entity
entity_match_confidence
headline
summary_or_text_reference
event_type
sentiment_or_tone
source_quality
```

The dashboard should show the source and timestamps. It should not present all items as equally authoritative.

## 2. Recommended source stack

### Tier A — official facts

| Source | Coverage | Best use | Main limitation |
|---|---|---|---|
| HKEXnews / HKEX public disclosure pages | Hong Kong listed issuers | Results, profit warnings, dividends, board changes, connected transactions, capital changes and other regulated disclosures | The official real-time Issuer Information Feed is a commercial service; free public pages and RSS do not provide the same guaranteed per-security feed |
| SEC EDGAR | US listed companies and issuers | 8-K, 10-Q, 10-K, 6-K, 20-F, XBRL facts and other filings | Filings are disclosures, not independent journalism |
| Company investor-relations pages | Issuer-specific | Press releases, presentations and event notices | No uniform schema or guaranteed feed across companies |

HKEX describes its Issuer Information Feed as an instantly transmitted real-time feed for listed-company announcements and trading news, including profit warnings, dividends, executive changes and changes to share capital. The free public RSS catalogue is mainly for HKEX news, regulatory communications and market communications, so it should not be treated as a replacement for the paid feed. ([HKEX IIS](https://www.hkex.com.hk/Services/Market-Data-Services/Infrastructure/Issuer-Information-feed-Service-%28IIS%29?sc_lang=en), [HKEX real-time data overview](https://www.hkex.com.hk/Services/Market-Data-Services/Real-Time-Data-Services/Overview?sc_lang=en), [HKEX RSS feeds](https://www.hkex.com.hk/services/rss-feeds?sc_lang=en))

The SEC states that its submissions and XBRL APIs are updated throughout the day in real time; typical processing delay is less than a second for submissions and under a minute for XBRL, although peak periods can be slower. ([SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces))

### Tier B — financial news APIs

| Source | Coverage | Best use | Main limitation |
|---|---|---|---|
| Finnhub | Strongest free candidate for US company news | Company news, market news, sentiment and event enrichment | Free plan is personal-use; international market coverage and quote latency are not equivalent to US coverage |
| Marketaux | Global news, entities, languages and market metadata | Cross-market coverage and entity-linked news enrichment | Free plan is only 100 requests/day and three articles per news request |

Finnhub's current free-plan description includes one year of company news and real-time updates, with a 60-calls-per-minute limit. Its international market-data table separately shows delayed or end-of-day coverage for markets outside the main US scope, so it is primarily a US news source for this project. ([Finnhub pricing](https://finnhub.io/pricing), [Finnhub API overview](https://www.finnhub.io/))

Marketaux advertises instant global news, 5,000+ sources, 80+ markets and 30+ languages, but its free plan is capped at 100 requests per day and three articles per request. It should be queried for holdings, watchlists and event-triggered names rather than every security on every polling cycle. ([Marketaux pricing](https://www.marketaux.com/pricing))

### Tier C — discovery and attention

| Source | Best use | Main limitation |
|---|---|---|
| GDELT DOC / GKG | Global topic discovery, media attention, coverage breadth and emerging narratives | Approximately 15-minute heartbeat; variable source quality; duplicates and syndicated articles; not a verified company-fact source |
| HKEJ | Hong Kong-local context and Chinese-language commentary | Narrower coverage and less professional/institutional than a global financial wire |
| Google News RSS or other public feeds | Additional discovery | Feed stability, licensing and entity precision vary |

GDELT's DOC API supports recent time windows down to 15 minutes, while GDELT's broader processing operates on a roughly 15-minute cycle. This makes it useful for a news radar, but it cannot guarantee a strict ten-minute end-to-end objective. ([GDELT DOC 2.0](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/), [GDELT real-time processing note](https://blog.gdeltproject.org/identifying-breaking-online-news-stories-across-the-world-in-realtime-with-the-gcp-timeseries-insights-api-natural-language-api/))

### Collection infrastructure — not news sources

[RSSHub](https://github.com/DIYgod/RSSHub) and [RSS-Bridge](https://github.com/RSS-Bridge/rss-bridge) can convert websites without stable feeds into RSS-like inputs. They are useful source adapters, but they do not improve source quality, guarantee latency or grant permission to redistribute content. Public instances should not be treated as production infrastructure; a self-hosted deployment is preferable.

## 3. Proposed source roles

```text
Official disclosures
  -> facts and event classification

Finnhub / Marketaux
  -> professional-news enrichment and article-level context

GDELT / RSS / HKEJ
  -> discovery, narrative breadth and local context

Local classifier and entity matcher
  -> ticker, event type, novelty, tone and confidence

Price-reaction evaluator
  -> abnormal return, volume and volatility response
```

The first version should show separate sections on a company page:

- Official disclosures
- Professional news
- Market attention / broader coverage
- Event classification and sentiment
- News-to-price reaction

## 4. Freshness contract

Do not use one generic `last_updated` field. Track the full timing chain:

```text
source_published_at
source_observed_at
ingested_at
processed_at
latency_seconds = processed_at - source_published_at
```

Suggested targets:

| Feed | Target |
|---|---:|
| SEC submissions | P90 under 10 minutes |
| HKEX public disclosure polling | P90 under 10 minutes where a precise publication time is available |
| Finnhub news | P90 under 10 minutes |
| Marketaux | P90 under 15 minutes |
| GDELT | P90 under 20 minutes |
| Classification and deduplication | Less than 3 additional minutes |

The system should report measured P50/P90 latency by source. A source that is fast but misses half of relevant events is not a successful low-latency feed.

## 5. Can news be backtested?

Yes, but the reliable object is usually **the market reaction to a timestamped news event**, not a generic “positive sentiment means buy” strategy.

The most defensible initial questions are:

1. Does a new official disclosure produce an abnormal return or volume response?
2. Does the same event category have a repeatable response across companies?
3. Does professional-news coverage add information beyond the official disclosure?
4. Does an unusual increase in coverage predict short-term attention or volatility?
5. Does a news signal improve an existing factor or alternative-data strategy after costs?

### 5.1 Event-level backtest

Each article or disclosure becomes an event with a point-in-time timestamp. For each event, measure:

```text
forward_return_5m
forward_return_30m
forward_return_1d
forward_return_3d
abnormal_return_vs_market
abnormal_return_vs_sector
volume_surprise
volatility_surprise
```

For a Hong Kong stock, the event should be compared with a suitable market benchmark, such as HSI or the relevant sector proxy. Overnight and lunch-break timing must be handled explicitly.

### 5.2 Signal-level backtest

Convert event data into signals, for example:

- official profit warning;
- results release;
- dividend change;
- management change;
- capital raising or placement;
- regulatory or legal event;
- positive/negative novelty score;
- unusual news-volume z-score;
- cross-source confirmation;
- source-weighted sentiment.

The signal must only use information available at `processed_at` or at a deliberately defined decision timestamp. The trade should execute at the next available tradable bar, not at the article's original timestamp if the article was not yet observable locally.

### 5.3 Portfolio-level backtest

The most useful final test is incremental value:

```text
baseline strategy
  + news filter or news overlay
  -> compare return, Sharpe, drawdown, turnover, hit rate and tail risk
```

For example, news may be more useful as:

- a risk-off filter after negative company events;
- a volatility or position-size adjustment;
- a confirmation layer for an alternative-data signal;
- a catalyst detector for event-driven trades;
- a ranking feature within a sector.

This is generally more credible than building a standalone sentiment strategy.

## 6. Why news backtests are easy to fool yourself with

### Look-ahead and time-travel

The backtest must use the first observed version of the article, not a later corrected headline, later sentiment label or later entity mapping. LLM summaries created after the event must not be used unless the same model and prompt are replayed using only information available at that time.

### Publication time versus availability time

The publisher's timestamp may be earlier than the time the article became visible to the strategy. Use `observed_at` or `processed_at` for execution eligibility. Otherwise the backtest will assume a trade could be placed before the system saw the information.

### Duplicate and syndicated coverage

The same event may appear in HKEX, an issuer website, Marketaux, Finnhub and GDELT. Without article clustering, one event can be counted five times and make the signal look stronger than it is.

### Entity-matching errors

A company name may refer to a subsidiary, competitor or product rather than the listed issuer. Ticker mapping must preserve a confidence score and allow an `unresolved` state.

### Selection and survivorship bias

Only backtesting articles for today's watchlist will bias results. The historical universe, delisted names and historical ticker mappings need to be represented if the result is intended to support a systematic strategy.

### Multiple testing

Trying many sources, event categories, sentiment models and holding periods will generate false discoveries. Keep a research holdout period and predefine the primary horizon before looking at results.

### Market and execution confounding

News often arrives during market-wide shocks, earnings seasons or major macro releases. Use market/sector abnormal returns, event-time controls, realistic spreads, trading fees and market-hours rules.

## 7. Reliability assessment

News backtesting is suitable for research, but it is not automatically reliable. A result should only be promoted to a dashboard signal after it passes:

- point-in-time timestamp validation;
- source and entity coverage checks;
- duplicate-event checks;
- latency measurement;
- market-hours and next-bar execution rules;
- out-of-sample or walk-forward testing;
- subperiod and sector stability checks;
- transaction-cost and turnover analysis;
- comparison with a no-news baseline;
- negative-control tests using unrelated articles or shuffled timestamps.

Useful evidence is not just a high hit rate. Report sample size, average abnormal return, confidence interval, t-statistic, information coefficient where appropriate, drawdown, turnover and the share of events that were actually tradable.

## 8. Recommended first research pilot

The first pilot should be narrow and auditable:

1. Start with HKEX official disclosures for a controlled set of liquid HK names.
2. Add Finnhub for US names and Marketaux for cross-market enrichment.
3. Use GDELT only as a coverage/attention feature.
4. Keep HKEJ as local commentary, not as the truth source.
5. Preserve raw headlines, URLs, timestamps and source identifiers.
6. Classify a small number of event types before adding generic sentiment.
7. Measure the event reaction at 30 minutes, one day and three days.
8. Test whether news improves an existing quant or alternative-data baseline.

The first success criterion is not positive PnL. It is proving that the pipeline can reconstruct, point-in-time, what information was available and when.

## 9. Current recommendation

For a free first version:

```text
HK company facts: HKEX public disclosures
US company facts: SEC EDGAR
US professional news: Finnhub
Global professional-news supplement: Marketaux
Global attention radar: GDELT
Feed adapters: RSSHub / RSS-Bridge
Local Hong Kong context: HKEJ
```

News should initially be used as an event and context layer. It should only become a standalone trading signal after the point-in-time event store and reaction backtest have demonstrated stable incremental value.
