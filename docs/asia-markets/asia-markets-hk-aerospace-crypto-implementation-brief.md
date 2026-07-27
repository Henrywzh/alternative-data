# Implementation Brief: Commercial Aerospace + Stablecoin/Crypto Sectors

**Handoff context:** this repo is a Python/Node alt-data pipeline + dashboard
(`apps/asia-markets-dashboard/`) currently live for 6 HK/Asia sectors
(hk-real-estate, hk-local-consumer, hk-utilities, hk-transport, hk-telecom,
hk-reit — see `apps/asia-markets-dashboard/sectors.json`). Two more sectors
have been fully researched but not yet built: **Commercial Aerospace** and
**Stablecoin/Crypto**. Both are currently listed as `"planned"` (research-only,
non-clickable rows on the hub) in `sectors.json`.

The research is done and every source below has been independently fetched
and verified live, not assumed from documentation. Your job is to turn it
into working pipelines and dashboards. This brief tells you what's verified
and what the known traps are — it does not tell you the exact file layout,
task breakdown, or test list. Discover that by reading the existing sectors
and following their shape.

## Read these first
- `docs/asia-markets/asia-markets-hk-commercial-aerospace.md` — full aerospace research, all sources verified with exact endpoints, dates, and evidence.
- `docs/asia-markets/asia-markets-hk-stablecoin-crypto.md` — full crypto/stablecoin research, same standard.
- `.claude/skills/data-source-deep-dive/references/verified-hk-sources.md` — the running ledger both docs above were drawn from; has more granular verification detail (exact curl commands, response snippets) than the docs themselves if you need to double-check something.
- Pick 1-2 existing live sectors and read them end to end before writing anything: `src/hk_reit/` (smallest, cleanest) and `src/hk_transport/` (closest in spirit to aerospace — theme/catalyst-driven, not fundamentals-driven). Look at `sources/`, `storage.py`, `pipeline.py`, `config.py`, `cli.py`, and the matching `apps/asia-markets-dashboard/scripts/build_hk_reit_artifact.py` / `build_hk_transport_artifact.py`. Match their shape — don't invent a new pattern.

## What "done" looks like
A new sector goes live the same way the existing 6 did: a `src/hk_<sector>/`
package (sources + normalized storage + pipeline + CLI), a
`build_hk_<sector>_artifact.py` script producing the JSON artifact + status
file, tests with real fixtures, then — only once that's real and tested — an
entry in `sectors.json` moving it from `planned` to `live`, and (separately,
later) a scheduled GitHub Actions workflow. Don't wire the sector into
`sectors.json` until the pipeline actually produces real, verified data —
follow whatever validation gates the existing sectors use (`_validate_*`
functions, quality-spec checks) rather than skipping them.

## Data-quality philosophy — non-negotiable
This repo has been burned by fabricated/placeholder data before and now
enforces "**gap over wrong number**": when a value can't be reliably
determined, drop it — don't guess, interpolate, or silently zero-fill. Where
a gap is genuine and permanent (a real, understood limitation of the
source), document it explicitly with a reason, following the
`KNOWN_UNRECOVERABLE_MONTHS`-style pattern already used elsewhere in this
repo (see `tests/test_cn_airline_scraper.py`) — an allowlist with a written
reason beats a silent skip. If you hit a source that returns something
unexpected, verify it against the live endpoint yourself before writing a
fallback for it; don't assume documentation or a search result describes
current reality.

## Verified sources to build against

### Commercial Aerospace
- **Launch Library 2** (`ll.thespacedevs.com`) — free JSON API, the primary launch-tracking source. Every major Chinese commercial launch company (LandSpace, Galactic Energy, CAS Space, Orienspace, Deep Blue Aerospace, i-Space, Space Pioneer) resolves to a distinct agency record. **Hard limit: 15 requests/hour on the free tier** — design the fetch to batch a day's worth of calls in one scheduled run, never loop live/interactively.
- **SSE STAR Market IPO status** (`query.sse.com.cn/commonSoaQuery.do`, JSONP) — the highest-value signal found: real-time IPO filing status for the actual rocket companies (LandSpace and CAS Space both confirmed `已问询`/under-inquiry as of the doc's last check). **Requires a `Referer: https://www.sse.com.cn/...` header or every request gets silently rejected** with no useful error message. Use the `sqlId=SH_XM_LB&keyword=<company>` search endpoint — don't hardcode numeric `auditId`s.
- **Celestrak** (`celestrak.org/NORAD/elements/gp.php`) — free, no-auth, live satellite constellation counts. Qianfan and Jilin-1 both confirmed working via `GROUP=`/`NAME=` params. **Guowang/国网's identifier is still unresolved** — the doc has a working hypothesis (unnamed international designators, cross-reference against Launch Library launch data) but it's untested. This is a good first-week discovery task for whoever builds this, not a blocker.
- **Google Patents** (`patents.google.com/xhr/query`) — free, no-auth, works for R&D-progress tracking on these companies. The structured `assignee:()` query syntax errors out — use plain free-text search and filter the `assignee` field client-side instead.
- **Do not attempt**: ITU's Space Explorer (genuine login/paid-subscription wall, confirmed not bypassable) or CNIPA's own patent search (actively bot-blocked, not just gated — Google Patents is the working substitute for the same data).
- The existing HK-listed watchlist (Cirrus Aircraft, Continental Aerospace, AVIC, etc.) is diffuse supplier exposure, not the rocket companies themselves — see the doc's framing note on why catalyst-timing (launches, IPO status, policy) matters more here than company financials.

### Stablecoin/Crypto
- **HKMA stablecoin issuer register** (`hkma.gov.hk/eng/regulatory-resources/registers/register-of-licensed-stablecoin-issuers/`) — real static HTML table, `pandas.read_html()` works directly, no API discovery needed. Ground truth for "who's actually licensed" (2 issuers as of the doc's last check: Anchorpoint, HSBC).
- **SFC VATP register** (`sfc.hk/en/.../Lists-of-virtual-asset-trading-platforms`) — same deal, real HTML tables (licensed/pending/withdrawn/forced-closure), `pandas.read_html()` works directly.
- **DefiLlama stablecoins API** (`stablecoins.llama.fi/stablecoins?includePrices=true`) — free, no auth, 500 req/min. Real-time circulating supply for all tracked stablecoins; useful to poll periodically for whether any HK/China-linked stablecoin (AxCNH, HKDAP) has actually launched.
- **HKEX crypto-ETF AUM** (`ifp.hkex.com.hk/ifp/api/v1/fund/getFundSizeList?fundId=<ID>`) — free, no auth, no special headers. Monthly AUM for all 6 HKEX-listed spot BTC/ETH ETFs. **One fundId (Harvest Ether Spot ETF, 3179.HK) is still unknown** — look it up via the fund's own `ifp.hkex.com.hk` page before wiring in all 6; the other 5 are already confirmed in the doc.
- **Coinbase/Binance public tickers** (`api.exchange.coinbase.com`, `api.binance.com`) — free, no auth, real-time. Useful both as a standalone "Coinbase Premium" spread and as the leading-indicator signal below.
- **Polymarket** (`gamma-api.polymarket.com/public-search?q=<term>`) — free, no auth. Use `public-search`, not the `tag=` filter (confirmed unreliable). Global/US regulatory-catalyst angle only — confirmed no HK-specific markets exist.
- **A tested, non-obvious finding worth preserving in the implementation**: COIN/CRCL price+volume is a real leading indicator for *macro/regulatory-catalyst-driven* moves in the HK crypto-concept basket (~1 week lead, confirmed against the Guotai Junan/GENIUS Act case) but is **not** predictive of idiosyncratic single-company deal news (confirmed against the Jinyong/AnchorX case, which shows no such lead). If you build an alert/signal off this, preserve that distinction rather than treating COIN/CRCL as a blanket predictor — it'll produce false confidence otherwise. This is n=2; a good validation task before leaning on it further is checking it against 1-2 more of the doc's own Tier 3 catalyst dates.
- **Do not chase**: Circle's own API (checked, no public endpoint exists — DefiLlama already covers the same USDC data for free). Circle/Coinbase SEC filings are available for free via this repo's existing `src/sec_edgar_data` pipeline if you want fundamentals — that's a config addition to existing infra, not a new source to build.
- The company watchlist (Tiers 1-4 in the doc) needs real care: several names are unrelated legacy businesses that bolted on a crypto press release. The doc's tiering (licensed exchange operator vs. licensed-to-deal-in-virtual-assets vs. infrastructure vs. concept-stock pivot vs. treasury play) reflects real, verified regulatory-status differences — preserve that distinction in whatever the dashboard shows, don't flatten it into one undifferentiated list.

## A cross-sector idea flagged but not yet built anywhere
Company career-page/job-posting activity as a general "is this company actually building this or just issuing a press release" signal — this repo already has reusable scraping infrastructure for this shape of data (`src/ai_hiring_data/`, `src/ramp_data/`). Worth considering for the crypto sector's Tier 3 concept-stock names specifically (hiring for blockchain/crypto roles vs. a name-only pivot), but this hasn't been verified or scoped yet — treat it as a stretch idea, not a requirement.

## Guardrails
- This is a shared working tree with other concurrent work in flight — scope any commits precisely to the files you actually touch, never a broad `git add -A`.
- Don't invent a UI template — both of these sectors are catalyst/theme-tracking dashboards, not fundamentals dashboards like the 6 live sectors. It's fine (probably better) if the layout ends up different from the existing card+chart+table pattern — e.g. an IPO-status tracker, a launch-cadence timeline, a licensing-register table — as long as it's still built from real, sourced data with the same source-attribution convention the existing sectors use.
- Everything above was verified on 2026-07-26/27. Re-verify anything before trusting it if meaningful time has passed — endpoints, rate limits, and especially the two open items (Guowang's Celestrak ID, Harvest Ether's fundId) may have changed or been resolved by then.
