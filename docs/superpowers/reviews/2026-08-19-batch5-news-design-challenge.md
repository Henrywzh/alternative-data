# Batch 5 News Design — Gemini Design Review Challenge (verbatim record)

Reviewed by: Gemini subagent "Carson" (google-antigravity/gemini-3.6-flash, max effort)
Date: 2026-08-19
Verdict: **REVISE**

Challenged artifact: `docs/superpowers/plans/2026-08-19-research-control-tower-batch5-news.md`

## Summary of the challenge (original draft = Google News RSS-first)

The reviewer argued the original draft was flawed: Google News RSS is
un-SLA'd, IP-block/rate-limit prone, returns obfuscated redirect links,
handles Chinese-language queries for CN/HK issuers poorly, and has ToS /
hotlink / database-right risk. It warned that `_source_quality_class` labels
any source containing "rss" as `official` and `_news_rows` hardcodes
`event_class="official_news_metadata"`, so ingesting keyless RSS via the stock
path would mislabel discovery headlines as official metadata (violating design
spec §8.1 and §10). It recommended (1) mart isolation + fixing the quality
classifier / event class, (2) either re-sequencing consensus revisions before
news or restricting batch 5 to an official-IR allowlist + entitled probes, and
(3) registry-backed entity resolution with negative-exclusion rules instead of
a standalone alias dictionary. It also argued consensus revisions carry higher
signal density than raw headlines for the app's stated "what changed" goal.

## Verification against code (by main session)

All factual claims that were code-checkable were confirmed:
- build.py `_source_quality_class`: `if "official" in source_text or "rss" in
  source_text or "public_metadata" in source_text: return "official"` — true,
  a discovery/RSS source would be mislabelled official.
- build.py `_news_rows` hardcodes `event_class="official_news_metadata"` —
  true.
- alibabagroup.com/en-US/rss.xml returns an HTML shell with 0 `<item>` rows —
  verified live; official-IR structured feeds are scarce.
- `_explicit_related_ids` uses `listing_by_ticker` / `entity_by_listing` from
  the registries — reuse, not a new dict, is the right seam.

Disagreement recorded: the reviewer proposed re-ordering Batch 6/7 ahead of
Batch 5. The sequencing order is an explicit user decision and stands; Batch 5
proceeds with narrowed scope instead.

## Adopted position (see plan section 0)

1. No Google News RSS as primary; structured providers (Finnhub/Marketaux/FMP)
   on free-tier probes + a verified official-IR allowlist.
2. Fix the builder quality/event-class bug first.
3. Registry-backed entity resolution + small versioned alias table with
   negative-exclusion rules.
4. Keep Batch 5-first sequencing, narrowed scope.
