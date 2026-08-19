# Research Control Tower Batch 5 — News Metadata Design Draft

**Date:** 2026-08-19
**Status:** REVISED after design review challenge
**Repo:** `alternative-data` (branch `codex/rtc-batch5-news`)
**Parent scope:** Control Tower data-coverage batch sequence (Batch 5 of 8)

## 0. Design review outcome (2026-08-19)

The original draft was challenged by a Gemini design reviewer (`Carson`) and
the challenge returned **REVISE**. After verifying every factual claim against
the code, the following changes are adopted:

1. **Do NOT make Google News RSS the primary news feed.** `_source_quality_class`
   in `src/research_control_tower/build.py` returns `official` whenever
   `"rss" in source_text`, and `_news_rows` hardcodes
   `event_class="official_news_metadata"`. Ingesting keyless Google News RSS
   through the stock path would mislabel discovery headlines as official
   metadata, violating design spec §8.1. The collector must instead write
   explicit `discovery` / `entitled` / `official` quality and a distinct event
   class per source kind, and the builder classification bug is fixed first.
2. **Scope Batch 5 to structured sources, not raw keyless scrapers.** A probe
   of `https://www.alibabagroup.com/en-US/rss.xml` returned an HTML shell with
   zero RSS items — official IR feeds are scarcer and less reliable than the
   draft assumed. Primary fill comes from structured providers with explicit
   symbols and real publish timestamps (Finnhub company News / Marketaux /
   FMP news on free-tier probes) plus an explicit official IR allowlist only
   where a genuine feed exists.
3. **Sequence stays Batch 5 (news) before 6/7 (consensus revisions)** — an
   explicit user decision — but scope is narrowed; no noisy keyless feed, no
   scraping of IR HTML.
4. **Entity resolution reuses the registry crosswalks** (`entities.csv`,
   `listings.csv` vendor_tickers / `financial_data_security_id`), with
   negative-exclusion rules; no standalone alias dictionary.

Full challenge text is preserved in the review result; this plan records the
adopted position.

## 1. What batch 5 is

Fill the `news` half of the existing `news_filings.parquet` mart. Today that
mart carries only `document_type="filing"` rows (SEC/HKEX metadata). The
`news` rows and their input schema (`ai_news_blog_posts_v1`) already exist but
are unpopulated: the only registered news source
(`news_official_ai_rss`) is an optional placeholder with no collector and no
inputs, reported as `unavailable`.

This batch adds a news **collector** (allowed to touch the network, scheduled
process) that writes a standardized local input parquet, which the existing
offline builder then consumes with its network-forbidden policy. That keeps
the established architecture: collectors are network-entitled, the app/builder
is not.

## 2. Source hierarchy (from design spec §8)

The approved design defines a strict hierarchy:

1. Official facts — SEC, OpenDART, company IR, exchange/regulator feeds.
2. Professional enrichment — entitled IBKR providers, Finnhub, Marketaux or
   another validated API (probe first).
3. Discovery — GDELT, Google News RSS, search/RSS adapters. Discovery cannot
   confirm financial or regulatory facts.

## 3. Proposed position (the claim to be challenged)

I propose the following defaults for Batch 5:

### 3.0 Structured sources first, no keyless scraper as primary

Fill the news layer from **structured providers with explicit tickers and real
publish timestamps**: Finnhub company-news, Marketaux and FMP news, each on a
free-tier entitlement probe recorded before wiring. Where a probe passes free
entitlement + metadata-only storage rules, that provider becomes a
`secondary_probe`/`entitled` source.

Google News RSS and GDELT are explicitly NOT the primary feed. Reasons are in
section 0: builder classification bug, redirect-obfuscated URLs, no SLA,
unstable Chinese-language query coverage for CN/HK issuers, and ToS/redistribution
risk. They may appear later only as an explicitly-labelled `discovery` layer,
and only after `_source_quality_class`/`_news_rows` correctly emit
`discovery` quality + a non-official event class.

### 3.1 Official IR: explicit allowlist, honest no_records elsewhere

Company IR newsrooms are mostly HTML, sometimes an irregular RSS, often
geo/JS-gated. The collector maintains a small **official IR allowlist** of
genuine structured feeds (verified content-type and item count by a probe, not
by assumption). Only those become `official` news rows. Every other entity's
official IR feed is recorded as `no_records`; IR HTML is never scraped to
manufacture official rows.

Rationale: verified feed → official; absent feed → honest `no_records`;
scraping HTML would (a) mislabel scraped data as official, (b) be fragile,
(c) duplicate what filings already carry.

### 3.2 Professional enrichment: probe then wire

Finnhub and Marketaux are **probed** in this batch (a short-lived
research/entitlement check recording endpoint, free-tier limits, fields,
geography, license display terms), and wired only if the probe passes free
entitlement + metadata-only storage rules. Otherwise they stay
`unavailable`/`probe_pending` with recorded evidence — matching the existing
coverage semantics and the plan’s “entitlement probe before adoption” rule.

### 3.3 Entity/linkage discipline (registry-backed)

Rows resolve to `related_entity_ids` through the existing registry
crosswalks (`entities.csv`, `listings.csv` `vendor_tickers` and
`financial_data_security_id`), plus an explicit small alias table for common
English/Chinese name variants that is versioned with the registry. Negative
exclusion rules (e.g. `Tencent Music` ≠ `Tencent 0700.HK`; `Alibaba Pictures`
≠ `9988.HK`) stop subsidiary/portfolio false positives. Unmatchable rows get
**empty** related ids, never a guessed link. `document_id` is a stable hash
over (source_id, link, headline, published). No article bodies.

### 3.4 Label honesty

`source_quality` distinguishes `official` / `discovery` / `secondary_probe`.
UI never presents a discovery row as a confirmed fact. A private entity
(ByteDance) uses the same alias dictionary for discovery coverage, flagged
`not_applicable` only where a concept does not apply.

## 4. Concrete pieces expected in this batch

- `src/research_control_tower/news_collector.py` — structured-provider
  adapters (Finnhub/Marketaux/FMP free-tier probes) + official-IR allowlist
  adapter, `collect_news()` writing the standardized input parquet + state
  sidecar (available/partial/no_records/unavailable), in the
  `quote_collector` / `official_filings` style.
- Fix `_source_quality_class` (the `"rss" → official` rule) and give `_news_rows`
  a non-hardcoded event class keyed off source kind.
- Registry-backed entity resolution + versioned alias table under
  `config/research_control_tower/` with negative-exclusion rules.
- Builder wiring: `--news-input` path and source ids per provider
  (`news_finnhub`, `news_marketaux`, `news_official_ir_allowlist`, ...).
- Entitlement-probe recorder (endpoint, fields, limits, license class, probe
  date) so a future provider can be adopted only with evidence on file.
- Tests: schema, freshness (45d), entity resolution + negative exclusions,
  source-quality/event-class mapping (discovery never → official), no-body
  policy, network forbidden in builder, degraded manifest when feed fails.
- Plan/spec checkboxes marked from Batch 5.

## 5. Deliberately out of scope for Batch 5

- Sentiment scoring or any composite score (design §7 forbids it in V1).
- Google News RSS / GDELT as a primary layer (blocked by review §0/§3.0; may
  return later as explicit `discovery` only).
- Full narrative/news sentiment NLP.
- Transcript extraction (spec §8.3) — separate later batch.
- Any paid key / account-gated provider becoming a hard dependency.
