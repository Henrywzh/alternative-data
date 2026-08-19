# Research Control Tower Batch 5 — News Provider Contracts & Probe Evidence Specification

**Date:** 2026-08-19
**Status:** APPROVED FOR INTEGRATION
**Repo:** `alternative-data` (branch `codex/rtc-batch5-news`)
**Parent plan:** `docs/superpowers/plans/2026-08-19-research-control-tower-batch5-news.md`

---

## 1. Overview & Scope

This document defines the formal provider contracts, empirical HTTP probe evidence, official IR allowlist determinations, and acceptance test matrix for Batch 5 (News Metadata) of the Research Control Tower.

Following the design review challenge (`docs/superpowers/reviews/2026-08-19-batch5-news-design-challenge.md`), raw keyless scrapers (e.g., Google News RSS) are excluded from primary feed status. Ingesting keyless RSS through standard paths would mislabel discovery headlines as official metadata (violating design spec §8.1). Batch 5 relies exclusively on:
1. **Verified Official IR Allowlist Feeds** (strictly structured RSS/Atom feeds returning HTTP 200 with valid items).
2. **Entitled Structured News Providers** (probed API endpoints with explicit ticker symbols and real timestamps: Finnhub, Marketaux, FMP).

Strict data governance applies across all candidates:
- **Metadata Only:** Store only `document_id`, `headline`, `publisher`, `published_at`, `source_url`, `language`, `related_entity_ids`, `event_class`, and `source_quality`.
- **No Article Bodies:** Full text, HTML bodies, or licensed summaries are NEVER stored or committed.
- **Offline Builder:** The offline builder (`src/research_control_tower/build.py`) remains strictly network-forbidden. All network operations occur in dedicated collectors (`news_collector.py`).

---

## 2. Candidate Provider Contracts

### 2.1 Candidate A: Finnhub Company News

- **Provider Name:** Finnhub Stock API (`company-news`)
- **Source Quality Class:** `entitled` (or `secondary_probe` prior to key acquisition)
- **Default Event Class:** `market_news_metadata`

#### Endpoints & Example URLs (Stage 1 Entities)
- **HTTP Method:** `GET`
- **Base Endpoint:** `https://finnhub.io/api/v1/company-news`
- **Example Request URLs:**
  - **Alibaba (BABA.US):** `https://finnhub.io/api/v1/company-news?symbol=BABA&from=2026-08-01&to=2026-08-19&token={FINNHUB_API_KEY}`
  - **Tencent (0700.HK):** `https://finnhub.io/api/v1/company-news?symbol=0700.HK&from=2026-08-01&to=2026-08-19&token={FINNHUB_API_KEY}` *(Free tier returns empty array for international HK exchange)*
  - **ByteDance (Private):** `N/A` *(Private unlisted entity — no symbol mapping; collector emits `no_records`)*
  - **Baidu (BIDU.US):** `https://finnhub.io/api/v1/company-news?symbol=BIDU&from=2026-08-01&to=2026-08-19&token={FINNHUB_API_KEY}`
  - **Kuaishou (1024.HK):** `https://finnhub.io/api/v1/company-news?symbol=1024.HK&from=2026-08-01&to=2026-08-19&token={FINNHUB_API_KEY}` *(Free tier unsupported)*
  - **Bilibili (BILI.US):** `https://finnhub.io/api/v1/company-news?symbol=BILI&from=2026-08-01&to=2026-08-19&token={FINNHUB_API_KEY}`

#### Request Parameters Specification
| Parameter | Type | Required | Description / Value |
|---|---|---|---|
| `symbol` | string | Yes | Stock ticker symbol (`BABA`, `BIDU`, `BILI`, or `0700.HK`). |
| `from` | string | Yes | Start date in `YYYY-MM-DD` format (e.g., `2026-08-01`). |
| `to` | string | Yes | End date in `YYYY-MM-DD` format (e.g., `2026-08-19`). |
| `token` | string | Yes | Finnhub API access token (`FINNHUB_API_KEY`). |

#### Response Schema & Field Mapping
Response format is a JSON array of article objects:
| Raw Finnhub Field | Target Parquet Field | Data Type | Transform / Mapping Rule |
|---|---|---|---|
| `id` | `document_id` | string | Derived SHA-256 hash over `("news_finnhub", url, headline, published_at)` rather than raw numeric ID for cross-source collision prevention. |
| `headline` | `headline` | string | Clean text string; strip leading/trailing whitespace. |
| `source` | `publisher` | string | Publisher name string (e.g., `"PR Newswire"`, `"MarketWatch"`). |
| `datetime` | `published_at` | string | Convert Unix epoch seconds to ISO-8601 UTC string (`YYYY-MM-DDTHH:MM:SSZ`). |
| `url` | `source_url` | string | Direct HTTP/HTTPS link to published article. |
| N/A | `language` | string | Hardcode `"en"` for US exchange symbols; default `"unknown"` if unverified. |
| `related` | `related_entity_ids` | list[string] | Map symbol string (e.g. `BABA` -> `ALIBABA`) via registry crosswalk (`listings.csv` `vendor_tickers`). |
| N/A | `sentiment` | N/A | **OUT OF SCOPE FOR V1** (Paid endpoint only; design §7 forbids composite/sentiment scores). |
| `summary` | N/A | N/A | **DISCARDED** (Do not store body text or snippets). |

#### Free-Tier Entitlement & Limits
- **Call Rate Limit:** 60 requests / minute.
- **Daily Call Limit:** Unlimited within rate limit (~1,000 queries/day practical max).
- **Historical Depth:** Up to 1 year of historical company news.
- **Geography & Exchange Coverage:** Strong coverage for US-listed primary/ADR symbols (`BABA`, `BIDU`, `BILI`). HK ordinary shares (`0700.HK`, `9988.HK`, `1024.HK`, `9626.HK`) are unsupported/delayed on free tier.
- **Private Entity Coverage:** None for `BYTEDANCE`.

#### License & Redistribution Terms
- Free API usage is permitted for personal, internal, non-commercial quantitative research.
- Storage of metadata fields (`headline`, `source_url`, `published_at`, `publisher`, `document_id`) is compliant. Full-text scraping or redistribution of article bodies is strictly prohibited by Finnhub ToS.

#### Probe Evidence Checklist (Pre-Adoption Requirements)
1. [ ] HTTP `200 OK` returned for US symbols (`BABA`, `BIDU`, `BILI`) with valid API token.
2. [ ] Payload is valid JSON array containing non-empty `headline`, `source`, `datetime`, and `url`.
3. [ ] `datetime` converts cleanly to UTC timestamps within 45-day freshness window.
4. [ ] Rate limiter respects 60 calls/min window without receiving HTTP 429.
5. [ ] HK tickers (`0700.HK`) return empty array `[]` cleanly without throw/crash.

#### Failure Modes & State Mappings
- **HTTP 200 + Non-empty array:** Collector state -> `available` (or `partial` if only US tickers return data).
- **HTTP 200 + Empty array `[]`:** Collector state -> `no_records`.
- **HTTP 429 (Rate limit exceeded) / 401 (Invalid token) / 5xx:** Collector state -> `unavailable` with error logged in state sidecar. Builder emits `degraded` status in manifest.

---

### 2.2 Candidate B: Marketaux News API

- **Provider Name:** Marketaux Financial News API (`/v1/news/all`)
- **Source Quality Class:** `entitled` (or `secondary_probe`)
- **Default Event Class:** `market_news_metadata`

#### Endpoints & Example URLs (Stage 1 Entities)
- **HTTP Method:** `GET`
- **Base Endpoint:** `https://api.marketaux.com/v1/news/all`
- **Example Request URLs:**
  - **Alibaba (BABA.US / 9988.HK):** `https://api.marketaux.com/v1/news/all?symbols=BABA,9988.HK&limit=3&api_token={MARKETAUX_API_KEY}`
  - **Tencent (0700.HK):** `https://api.marketaux.com/v1/news/all?symbols=0700.HK&limit=3&api_token={MARKETAUX_API_KEY}`
  - **ByteDance (Private):** `https://api.marketaux.com/v1/news/all?search=ByteDance&limit=3&api_token={MARKETAUX_API_KEY}`
  - **Baidu (BIDU.US / 9888.HK):** `https://api.marketaux.com/v1/news/all?symbols=BIDU,9888.HK&limit=3&api_token={MARKETAUX_API_KEY}`
  - **Kuaishou (1024.HK):** `https://api.marketaux.com/v1/news/all?symbols=1024.HK&limit=3&api_token={MARKETAUX_API_KEY}`
  - **Bilibili (BILI / 9626.HK):** `https://api.marketaux.com/v1/news/all?symbols=BILI,9626.HK&limit=3&api_token={MARKETAUX_API_KEY}`

#### Request Parameters Specification
| Parameter | Type | Required | Description / Value |
|---|---|---|---|
| `symbols` | string | Conditional | Comma-separated symbols (`BABA,0700.HK,BIDU`). |
| `search` | string | Conditional | Text query for unlisted/private entities (`ByteDance`). |
| `limit` | integer | Yes | Capped at `3` on free tier (`FREE_TIER_LIMIT = 3`). |
| `published_after` | string | No | ISO-8601 timestamp (e.g., `2026-08-01T00:00:00`). |
| `api_token` | string | Yes | Marketaux API key (`MARKETAUX_API_KEY`). |
| `language` | string | No | Preferred languages (e.g. `en,zh`). |

#### Response Schema & Field Mapping
Response format is a JSON object with a `data` array of article objects:
| Raw Marketaux Field | Target Parquet Field | Data Type | Transform / Mapping Rule |
|---|---|---|---|
| `uuid` | `document_id` | string | SHA-256 hash over `("news_marketaux", url, title, published_at)`. |
| `title` | `headline` | string | Clean headline string. |
| `source` | `publisher` | string | Domain / source name (e.g., `"reuters.com"`). |
| `published_at` | `published_at` | string | ISO-8601 UTC timestamp string (`YYYY-MM-DDTHH:MM:SS.000000Z`). |
| `url` | `source_url` | string | Canonical web link. |
| `language` | `language` | string | Two-letter language code (`"en"`, `"zh"`). |
| `entities[].symbol` | `related_entity_ids` | list[string] | Map matched entity objects to canonical entity IDs using registry crosswalk. |
| `entities[].sentiment_score` | N/A | N/A | **OUT OF SCOPE FOR V1** (Ignored per design §7). |
| `snippet` / `description` | N/A | N/A | **DISCARDED** (Metadata only; no body snippet stored). |

#### Free-Tier Entitlement & Limits
- **Daily Call Limit:** 100 requests / day hard cap across account.
- **Per-Request Limit:** Maximum 3 articles returned per call (`limit=3`).
- **Historical Depth:** ~30 days on free tier.
- **Geography & Exchange Coverage:** Global multi-language coverage including US, HK, and CN issuers.
- **Private Entity Coverage:** Supports text search (`search=ByteDance`).

#### License & Redistribution Terms
- Free tier non-commercial evaluation.
- Store metadata only (uuid hash, title, url, published_at, publisher, language, matched entity symbols).

#### Probe Evidence Checklist
1. [ ] HTTP `200 OK` returned for symbol queries with valid `api_token`.
2. [ ] Free tier enforces limit cap (maximum 3 articles per request).
3. [ ] `published_at` contains valid ISO-8601 UTC timestamps.
4. [ ] `entities` array correctly maps `BABA` or `0700.HK` to issuer objects.
5. [ ] Request counter stays under 100 requests/day ceiling.

#### Failure Modes & State Mappings
- **HTTP 200 + Non-empty `data` array:** Collector state -> `available`.
- **HTTP 200 + Empty `data: []`:** Collector state -> `no_records`.
- **HTTP 429 (Daily 100 limit exhausted) / 401 / 5xx:** Collector state -> `unavailable`. Builder emits `degraded` status.

---

### 2.3 Candidate C: Financial Modeling Prep (FMP) Stock News

- **Provider Name:** Financial Modeling Prep (`stock_news`)
- **Source Quality Class:** `entitled` (or `secondary_probe`)
- **Default Event Class:** `market_news_metadata`

#### Endpoints & Example URLs (Stage 1 Entities)
- **HTTP Method:** `GET`
- **Base Endpoint:** `https://financialmodelingprep.com/api/v3/stock_news`
- **Example Request URLs:**
  - **Alibaba (BABA.US):** `https://financialmodelingprep.com/api/v3/stock_news?tickers=BABA&limit=10&apikey={FMP_API_KEY}`
  - **Tencent (0700.HK):** `https://financialmodelingprep.com/api/v3/stock_news?tickers=0700.HK&limit=10&apikey={FMP_API_KEY}` *(Free tier returns 403 or empty array)*
  - **ByteDance (Private):** `N/A` *(Unlisted; unsupported)*
  - **Baidu (BIDU.US):** `https://financialmodelingprep.com/api/v3/stock_news?tickers=BIDU&limit=10&apikey={FMP_API_KEY}`
  - **Kuaishou (1024.HK):** `https://financialmodelingprep.com/api/v3/stock_news?tickers=1024.HK&limit=10&apikey={FMP_API_KEY}` *(Free tier unsupported)*
  - **Bilibili (BILI.US):** `https://financialmodelingprep.com/api/v3/stock_news?tickers=BILI&limit=10&apikey={FMP_API_KEY}`

#### Request Parameters Specification
| Parameter | Type | Required | Description / Value |
|---|---|---|---|
| `tickers` | string | Yes | Comma-separated ticker symbols (`BABA,BIDU,BILI`). |
| `limit` | integer | No | Maximum number of articles to return (e.g. `50`). |
| `from` | string | No | Start date `YYYY-MM-DD`. |
| `to` | string | No | End date `YYYY-MM-DD`. |
| `apikey` | string | Yes | FMP API access key (`FMP_API_KEY`). |

#### Response Schema & Field Mapping
Response format is a JSON array of news item objects:
| Raw FMP Field | Target Parquet Field | Data Type | Transform / Mapping Rule |
|---|---|---|---|
| `url` | `document_id` | string | SHA-256 hash over `("news_fmp", url, title, publishedDate)`. |
| `title` | `headline` | string | Headline string. |
| `site` | `publisher` | string | Publisher/website name (e.g., `"Seeking Alpha"`). |
| `publishedDate` | `published_at` | string | Convert `"YYYY-MM-DD HH:MM:SS"` to ISO-8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`). |
| `url` | `source_url` | string | Direct web URL. |
| N/A | `language` | string | Default `"en"` for US exchange tickers. |
| `symbol` | `related_entity_ids` | list[string] | Map ticker string (`BABA` -> `ALIBABA`) via registry crosswalk. |
| `text` | N/A | N/A | **DISCARDED** (No snippet or body text stored). |

#### Free-Tier Entitlement & Limits
- **Daily Call Limit:** 250 requests / day hard limit.
- **Rate Limit:** 30 requests / minute.
- **Historical Depth:** Restricted on free tier (~recent articles only).
- **Geography & Exchange Coverage:** Restricted to US exchange listings (`BABA`, `BIDU`, `BILI`). HK/CN ordinary shares unsupported on free tier.

#### License & Redistribution Terms
- Non-commercial free tier. Store metadata only.

#### Probe Evidence Checklist
1. [ ] HTTP `200 OK` returned for US tickers (`BABA`, `BIDU`, `BILI`).
2. [ ] `publishedDate` converts cleanly to UTC timestamps.
3. [ ] Unsupported HK tickers return empty array `[]` or clear 403 response without crashing collector.

#### Failure Modes & State Mappings
- **HTTP 200 + Non-empty array:** Collector state -> `available` / `partial`.
- **HTTP 200 + Empty array `[]`:** Collector state -> `no_records`.
- **HTTP 403 / 429 / 5xx:** Collector state -> `unavailable`. Builder emits `degraded` status.

---

## 3. Official IR Allowlist & Empirical Probe Evidence

### 3.1 Policy & Inclusion Criteria
In accordance with design review challenge decision §3.1:
- Official IR news rows MUST originate from genuine, structured RSS/Atom feeds that return HTTP 200 OK with non-zero structured item elements (`<item>` or `<entry>`).
- HTML IR press pages, client-rendered JavaScript shells, and keyless scraping are EXCLUDED.
- If an entity lacks a verified structured RSS/Atom feed, its official IR feed state is recorded as `no_records`. HTML is never scraped to manufacture fake official rows.

### 3.2 Stage 1 Entity Verification Matrix (Actual Probes Recorded 2026-08-19)

| Entity | Entity ID | Candidate URL Tested | HTTP Status | Content-Type | Format Detected | Item Count | Allowlist Verdict | Action / State |
|---|---|---|---|---|---|---|---|---|
| **Alibaba** | `ALIBABA` | `https://www.alibabagroup.com/en-US/rss.xml` | 200 | `text/html; charset=utf-8` | HTML Shell | 0 items | **REJECTED** | Primary IR feed returns HTML shell; record `no_records` for main IR. |
| **Alibaba (Corporate)** | `ALIBABA` | `https://www.alizila.com/feed/` | 200 | `application/rss+xml; charset=UTF-8` | RSS 2.0 | **10 items** | **ADMITTED** | Official corporate newsroom feed verified. Map to `source_quality="official"`. |
| **Tencent** | `TENCENT` | `https://www.tencent.com/en-us/rss` | 200 | `text/html; charset=UTF-8` | HTML Page | 0 items | **REJECTED** | Returns HTML page shell; record `no_records`. |
| **Tencent** | `TENCENT` | `https://www.tencent.com/rss.xml` | 200 | `text/html; charset=UTF-8` | HTML Page | 0 items | **REJECTED** | Returns HTML page shell; record `no_records`. |
| **ByteDance** | `BYTEDANCE` | `https://www.bytedance.com/feed.xml` | 200 | `text/html; charset=utf-8` | HTML Page | 0 items | **REJECTED** | Unlisted entity; returns HTML page shell; record `no_records`. |
| **Baidu** | `BAIDU` | `https://ir.baidu.com/rss/news-releases.xml` | 200 | `application/rss+xml; charset=utf-8` | RSS 2.0 | **10 items** | **ADMITTED** | Genuine structured official IR feed. Map to `source_quality="official"`, `event_class="official_news_metadata"`. |
| **Kuaishou** | `KUAISHOU` | `https://ir.kuaishou.com/rss` | 404 | `text/html; charset=UTF-8` | HTTP Error | 0 items | **REJECTED** | Endpoint 404; record `no_records`. |
| **Bilibili** | `BILIBILI` | `https://ir.bilibili.com/rss/news-releases.xml` | 404 | N/A | HTTP Error | 0 items | **REJECTED** | Endpoint 404; record `no_records`. |

### 3.3 Admitted Official IR Allowlist Summary
The official IR allowlist for Batch 5 comprises exactly two verified feeds:
1. `baidu_ir_rss`: `https://ir.baidu.com/rss/news-releases.xml` (`entity_id="BAIDU"`)
2. `alizila_rss`: `https://www.alizila.com/feed/` (`entity_id="ALIBABA"`)

All other Stage 1 entities (`TENCENT`, `BYTEDANCE`, `KUAISHOU`, `BILIBILI`) report `no_records` for their official IR news feed.

---

## 4. Acceptance Test Matrix (Integration Guidance)

The implementation slice must pass the following acceptance test matrix before Batch 5 completion is declared:

### Group 1: Schema & Freshness (45d Boundary)
- `test_news_schema_validity`: Assert generated news input parquet strictly matches `ai_news_blog_posts_v1` required columns (`document_id`, `headline`, `publisher`, `published_at`, `source_url`, `language`, `related_entity_ids`, `event_class`, `source_quality`).
- `test_news_freshness_boundary`: Assert builder excludes news items published older than 45 days relative to the run cutoff timestamp.

### Group 2: Entity Resolution & Negative Exclusions
- `test_entity_resolution_primary_listings`: Assert US and HK exchange tickers (`BABA.US`, `9988.HK`, `0700.HK`, `BIDU.US`, `9888.HK`, `1024.HK`, `BILI.US`, `9626.HK`) resolve accurately to canonical entity IDs (`ALIBABA`, `TENCENT`, `BAIDU`, `KUAISHOU`, `BILIBILI`).
- `test_entity_resolution_private_entity`: Assert private entity search matches for `ByteDance` resolve to `entity_id="BYTEDANCE"` without requiring listing crosswalks.
- `test_entity_resolution_negative_exclusions`: Assert subsidiary and portfolio entity names (e.g., `Tencent Music`, `Alibaba Pictures`, `Baidu Video`) do NOT resolve to parent entity IDs (`TENCENT`, `ALIBABA`, `BAIDU`).
- `test_unmatched_entity_empty_list`: Assert headlines with no recognized entity match produce an empty list `related_entity_ids = []` rather than guessed links.

### Group 3: Source Quality & Event Class Mapping
- `test_source_quality_official_ir`: Assert items from official IR allowlist feeds (`baidu_ir_rss`, `alizila_rss`) emit `source_quality="official"` and `event_class="official_news_metadata"`.
- `test_source_quality_entitled_provider`: Assert items from Finnhub, Marketaux, or FMP emit `source_quality="entitled"` (or `secondary_probe`) and `event_class="market_news_metadata"`.
- `test_source_quality_discovery_never_official`: Assert discovery adapters or RSS searches NEVER emit `source_quality="official"` or `event_class="official_news_metadata"`.

### Group 4: No-Body Policy & Privacy Constraints
- `test_no_article_body_stored`: Assert news schema and collector parquet contain no article body text, HTML, or full transcript columns.
- `test_stable_document_id_hashing`: Assert `document_id` is a deterministic SHA-256 hash derived from `(source_id, source_url, headline, published_at)`.

### Group 5: Offline Builder Network Guard
- `test_builder_offline_network_guard`: Assert running `build.py` with `--news-input` executes with zero network calls (socket connections raise error if attempted).

### Group 6: Failure Modes & Degraded Manifest Rules
- `test_degraded_manifest_on_provider_error`: Assert collector writes state sidecar `unavailable` or `partial` when provider API fails, and builder emits `degraded` status in output manifest without throwing an unhandled exception.
- `test_honest_no_records_state`: Assert entities missing official feeds (`TENCENT`, `BYTEDANCE`, `KUAISHOU`, `BILIBILI`) report explicit `no_records` status in source health.
