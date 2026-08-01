# Hong Kong Commercial Aerospace / Aviation Manufacturing (商业航天)

Companion to [asia-markets-hk-sectors.md](asia-markets-hk-sectors.md).
Item #3 in the [focus list](asia-markets-hk-focus-list.md). Watchlist
supplied directly (as a CSV, live quotes as of 2026-07-22); market caps
converted from the HKD figures in the source file (÷7.8 to USD) and are
therefore point-in-time, not from the HSCI dataset used elsewhere.

**Framing note:** HK theme stocks trade on momentum beta to the *theme*,
and HK themes tend to be short-lived — once a theme is "hot," most names
tagged to it move together regardless of individual fundamentals. That
means the highest-value alt data for a theme like this is usually the
theme's own catalyst feed (policy announcements, launch calendars) more
than company-specific data — which is exactly the case here.

**akshare note** (full audit: [asia-markets-hk-akshare-capabilities.md](asia-markets-hk-akshare-capabilities.md)):
standard fundamentals functions work on Cirrus Aircraft (2507) and
Continental Aerospace (0232), the two verified "real business" names here
— useful as a background check, though per the framing above, launch
cadence and policy escalation are the higher-value signal for this
basket, not company financials.

## Watchlist

A more mixed watchlist than the name suggests — mostly aerospace/defense
manufacturing and satellite names, with two renewable-energy names that
look like they may not belong (flagged below).

| Company | Ticker | Market Cap (USD bn) | Note |
|---|---|---|---|
| Lens Technology (蓝思科技) | 6613.HK | ~15.1 | Electronics components (smartphone glass/casings) — dual-listed, primarily a consumer-electronics supplier; aerospace connection unclear from this pull |
| Goldwind (金风科技) | 2208.HK | ~5.3 | Wind turbine manufacturer — **sector tag says "环保工程" (environmental engineering), not aerospace**; likely thematically adjacent (advanced manufacturing / new-energy overlap) rather than a true aerospace name — flag before treating as core |
| AVIC Aviation Industry (中航科工) | 2357.HK | ~3.0 | Core AVIC (Aviation Industry Corp of China) aerospace/defense manufacturing arm |
| Cirrus Aircraft (西锐) | 2507.HK | ~1.9 | **Verified**: world's largest private/general-aviation aircraft manufacturer (Wisconsin-founded, 11,000+ SR2X piston aircraft + 700+ Vision jets delivered), acquired by China Aviation Supplies (中航通飞) in 2011, listed on HKEX July 2024. Controlling shareholders: China Aviation Supplies Holding + China State Shipbuilding |
| Topu CNC (拓璞数控) | 7688.HK | ~0.78 | Aerospace manufacturing equipment (CNC machining systems used in aircraft component production) |
| Junda Co. (钧达股份) | 2865.HK | ~0.65 | Solar cell manufacturer — **sector tag says "新能源物料" (new energy materials)**, same flag as Goldwind |
| Continental Aerospace Technologies (大陆航空科技控股) | 0232.HK | ~0.50 | **Verified**: general-aviation piston aircraft engine design/manufacture + aftermarket support; another China Aviation Supplies-linked general-aviation name, same corporate family as Cirrus |
| APT Satellite (亚太卫星) | 1045.HK | ~0.26 | Satellite operator (Asia Pacific communications satellites) |
| China Aerospace International Holdings (航天控股) | 0031.HK | ~0.20 | Part of the China Aerospace Science and Technology Corp (CASC) group |

**Flag:** Goldwind and Junda are tagged to renewable-energy sectors in the
source data itself, not aerospace/defense — worth confirming with whoever
built this watchlist whether they're intentional (e.g. shared
supply-chain/materials exposure) or a mis-tag before using this list as a
clean "aerospace" screen.

## Theme catalyst tracking (easy — public launch/policy data)

Per the framing above: this theme is directly, publicly driven by China +
US rocket launch activity and government policy announcements — both are
genuinely easy, free, high-frequency data.

**Launch-cadence tracking (verified free trackers):**
| Source | Coverage | Access |
|---|---|---|
| `ll.thespacedevs.com` (Launch Library 2) | **New primary recommendation (verified 2026-07-26).** Free structured JSON API, not HTML scraping — `/2.2.0/launch/upcoming/` and `/launch/previous/` for schedules, `/agencies/?search=<name>` for company lookup. Confirmed every major Chinese commercial launch company resolves to a distinct, correctly-typed agency record: LandSpace, Galactic Energy, CAS Space, Orienspace Technology, Deep Blue Aerospace, i-Space (must search `"i-Space"` with the hyphen — bare `"iSpace"` matches unrelated foreign entities). Free tier is rate-limited to **15 requests/hour** (confirmed against the official docs at thespacedevs.com/llapi and their GitHub FAQ, not just observed empirically); a paid Patreon tier raises the limit, and `lldev.thespacedevs.com` is an unlimited-but-stale-data dev endpoint alternative. Fine for a scheduled daily/weekly pull, not for interactive ad hoc querying. | Free (rate-limited) |
| `spacelaunchschedule.com` | Dedicated China launch category (real-time schedule, timezone-converted, mission/payload details) | Free |
| `nextspaceflight.com` | Global launch schedule incl. US (SpaceX/ULA/etc.) and China. **Confirmed real and server-rendered** (China launch data — Long March, Kinetica-1, Ceres — is baked into the raw HTML), but no JSON API was found on the domain, and a Cloudflare challenge script is present that may add friction to a scheduled scraper. Demoted to an HTML-scrape fallback/cross-check now that Launch Library 2 is available. | Free |
| `rocketlaunch.live` | Global, filterable by country including China | Free |

Launch Library 2 should be the **primary** launch-tracking source going
forward — structured fields (status, NET time + precision, pad, orbit,
launch_service_provider) instead of parsed HTML, plus built-in
per-company/per-agency filtering. Launch **cadence itself** (launches per
month, by provider) is a genuine activity proxy for this sector — more
launches from a specific Chinese commercial provider (e.g. names tied to
中航科工/Topu CNC's supply chain) is a real leading indicator, not just
noise. Launch failures are the obvious negative catalyst and are
immediately public.

**Correction:** 天兵科技's registered English/international name in Launch
Library 2's agency database is **"Space Pioneer,"** not "Space Epoch" — if
any external list or note refers to it as "Space Epoch," that's wrong;
fix it wherever it's cross-referenced.

**Policy catalyst tracking (verified):**
- China's commercial space sector was named a **"new engine of economic
  growth"** in the 2024 Government Work Report (its first appearance there)
  and mentioned again in the 2025 report — this two-year progression is a
  real, trackable policy escalation.
- The Central Economic Work Conference (Dec 2023) designated commercial
  space a **strategic emerging industry**.
- CNSA (China National Space Administration) published a named **"Action
  Plan for Promoting High-Quality and Safe Development of Commercial
  Space"** covering 2025–2027 — a citable multi-year policy document,
  worth monitoring for the 2026/2027 milestones it presumably lays out.
- Market-size framing already public: China's commercial space market
  projected to exceed **RMB 2.5 trillion (~$348bn) in 2025**.
- US-side equivalent policy catalysts (not yet checked): NASA commercial
  launch contract awards, FAA launch-license approvals — same "easy,
  public" category, just not individually verified yet.

## Listed-exposure catalyst: SSE STAR Market (科创板) IPO filing status — highest-value finding this pass

The watchlist above is entirely diffuse supplier/theme exposure: **none of
the actual rocket companies are listed today.** An IPO filing status
change is the actual trigger for direct listed exposure to this theme to
exist, which makes tracking filing status the single highest-value
catalyst feed found so far — more direct than launch cadence or policy
language, because it's the thing that turns theme exposure into a real
security.

**Confirmed live and fully automatable (2026-07-26):** the real API is
`https://query.sse.com.cn/commonSoaQuery.do` (JSONP). It requires a
`Referer: https://www.sse.com.cn/...` header — a bare `curl` without it
gets rejected with an `ExceptionInterceptor` error; adding the header
works with no other auth/session/cookie needed. This endpoint was only
discoverable via a real browser's network/resource-timing log — the page
itself is a JS single-page-app, and curling it directly just returns a
generic shell with no useful data in the static HTML.

**Search endpoint** (the actual unlock — no need to already know a
numeric ID): `sqlId=SH_XM_LB&keyword=<company name>` searches by company
name directly, e.g. `keyword=中科宇航`.

**Confirmed results for the 5-company IPO-race set:**
| Company | Result |
|---|---|
| LandSpace (蓝箭航天) | **Active, accepted filing** (auditNum 2174), status **已问询 (under inquiry)** as of update date 2026-06-29 |
| CAS Space (中科宇航) | **Active, accepted filing** (auditNum 2180), status **已问询 (under inquiry)** as of the same update date 2026-06-29 |
| Galactic Energy (星河动力) | Zero results by keyword — no accepted Shanghai filing yet |
| Space Pioneer (天兵, corrected name — see above) | Zero results by keyword — no accepted Shanghai filing yet |
| i-Space (星际荣耀) | Zero results by keyword — no accepted Shanghai filing yet |

The zero-result three are consistent with other reporting describing
i-Space as still in pre-acceptance "tutoring" status since 2020. Caveat:
this endpoint only covers Shanghai's STAR Market, not Shenzhen's ChiNext —
it's possible one or more of these three is instead pursuing a Shenzhen
listing, which has not been checked.

**Detail endpoint** (`sqlId=SH_XM_LB&stockAuditNum=<id>&isPagination=true`)
goes further: financing amount, sponsor bank, named bankers/lawyers/
accountants, and the company's legal representative — all real, specific,
verified data (e.g. LandSpace's listed legal representative matches its
actual known founder/CEO, not placeholder data).

**Verdict:** go — a free, no-auth-beyond-a-header, `curl`-able API giving
exact IPO-review status for the actual rocket companies. This should be
polled periodically (see "What to do next" below) as the leading
indicator for when this theme gets its first direct listed pure-play.

## Satellite constellation deployment tracking — new capability

Celestrak (`celestrak.org/NORAD/elements/gp.php`) is free, no-auth, live
orbital element (TLE) data — a source not previously in this doc or the
watchlist. It's a genuinely new, quantifiable proxy: pulling the
satellite count per constellation/operator on a schedule gives a real
"how many satellites has this operator actually deployed"
execution/capability time series, distinct from and complementary to
launch-cadence tracking above (cadence tells you how often a provider
launches; this tells you how much hardware is actually in orbit and
operating).

**Confirmed live** 2026-07-26, both with today's epoch timestamp
(confirming real-time currency, not stale/cached data):
- `GROUP=qianfan` returns hundreds of real 千帆/G60 megaconstellation
  satellites (Shanghai-backed Starlink rival).
- `NAME=JILIN` returns 50 live 长光卫星/Jilin-1 satellites (Chang Guang
  Satellite Technology's constellation).

**Open gap:** Guowang/国网 (SatNet), the other major Chinese
megaconstellation, has no working Celestrak `GROUP` or `NAME` string yet —
`guowang`, `SATNET`, `SATNET GROUP`, and `GW-` were all tried and all
failed. Current working hypothesis: Guowang's satellites are cataloged
under generic unnamed international designators (e.g. launch batches like
`2026-168A` through `2026-168J`, sized consistent with a typical Guowang
launch) rather than a friendly constellation name, unlike Qianfan/Jilin-1
which get proper names quickly. Confirming this hypothesis requires
cross-referencing those designators against Launch Library 2's mission
data to match designator to launch — not yet done, since Launch Library 2
was rate-limited at the time this was checked.

## How to use this

Best used as a **theme-timing overlay** (is commercial-aerospace narrative
intensity rising — launch cadence up, new policy language, new provincial
subsidies) rather than a stock-specific signal — most of the names on the
watchlist are tangential suppliers, not direct launch-revenue plays. Cirrus
Aircraft and Continental Aerospace are the two verified "real business"
names; the rest is more diffuse theme exposure.

## What to do next
- Confirm whether Goldwind/Junda genuinely belong in this watchlist.
- Confirm Guowang's Celestrak designator by cross-referencing candidate
- international designators against Launch Library 2 mission data once the
  provider/API rate limit resets.
- Periodically re-run the SSE STAR Market keyword search for Galactic
  Energy, Space Pioneer, and i-Space to catch when/if any of them gets an
  accepted filing.
- Separate the 25 SZSE aerospace-industry projects into pure commercial
  space, aviation, rail and other adjacent categories before using them as a
  company basket.
- Fix Google Patents' XHR request shape and normalize patent families before
  considering it for a signal.

## Stage 1 / Stage 2 ingestion update (2026-08-01)

The first implementation pass now carries the following normalized datasets
into the artifact builder:

- Launch Library 2 historical launch events are filtered by exact launch
  service provider IDs, deduplicated by `launch_id`, and retained as
  provider/status detail in `launch_monthly`. The visible monthly chart uses
  the separate zero-filled `launch_monthly_total` series, so missing months
  are shown as zero rather than being silently bridged; national-program
  launches are not included in that commercial series. The normalized event history is retained in
  `data/normalized/hk_commercial_aerospace/launch_events_history.jsonl` so a
  clean scheduled CI checkout does not lose prior events when the free API
  returns HTTP 429. Raw provider snapshots remain a local fallback; cached or
  persisted rows are never reported as new live observations.
- The official national baseline is now retained in
  `data/normalized/hk_commercial_aerospace/china_launch_events.jsonl`.
  It combines the first-party CASC Long March table with the CALT archive's
  historical Long March/Jielong records, deduplicating overlapping first-party
  rows by date, rocket signature and launch site. The current verified baseline
  covers 1970-04-24 through 2026-07-30: 598 Long March events classified as
  `national_program` and 11 Jielong events classified as
  `state_owned_commercial`. It preserves official sequence, payload summary,
  explicit payload counts where the source states them, outcome and source
  snapshot lineage.
- `china_launch_monthly` is the zero-filled comparison series across
  `national_program`, `state_owned_commercial` and the existing
  `commercial_provider` events. `china_launch_events` is the canonical mission
  table; LL2-only candidates are never counted. Launch Library 2 provider IDs
  88 and 272 are used only to enrich official events with time, pad, orbit,
  mission type and structured status fields. A cached LL2 enrichment is marked
  stale when the 15-request/hour free-tier limit is hit.
- Kuaizhou/CASIC and other state launch families remain outside the verified
  V1 baseline until a first-party historical source contract is separately
  validated. The absence of those families is visible coverage scope, not a
  claim that they did not launch.
- CelesTrak Qianfan and Jilin-1 counts are appended to
  `data/normalized/hk_commercial_aerospace/celestrak_constellation_history.jsonl`.
  The count means tracked/catalogued objects, not confirmed operational
  satellites. The short six-day snapshot run is retained for audit/Data
  Explorer but is not published as a production history chart until at least
  8 distinct observations accumulate; the current inventory bar remains the
  visible signal. The threshold is observation-count based, not a daily-fetch
  requirement. Guowang remains a documented gap.
- SZSE's public `/api/ras/projectrends/query` endpoint is filtered to the
  broad industry classification `铁路、船舶、航空航天和其他运输设备制造业`.
  This is an aerospace-adjacent IPO feed, not a pure commercial-space list;
  the original industry field is retained for review.
- The official FAA Commercial Space By the Numbers page contributes current
  cumulative/active authorization KPIs. It is not a historical launch series.
- USAspending contributes keyword-discovered federal award events. Award
  amounts are government award values, not company revenue, and the keyword
  feed is filtered for space-related terms and obvious false matches.
- SEC submissions contribute filing metadata for Rocket Lab, AST SpaceMobile,
  Planet Labs, Intuitive Machines and Redwire. The feed is an official event
  discovery layer; it does not infer order or financing amounts from a filing.
- The UNOOSA-derived Our World in Data series contributes annual World,
  China and US objects-launched benchmarks. It counts objects/payloads, not
  rocket launches.
- The direct UNOOSA Online Index object-level route was tested for a higher-
  frequency rebuild but is currently unavailable: UNOOSA says the Online
  Index and related export functionality are temporarily offline during
  mandatory UN IT infrastructure changes. The annual OWID series therefore
  remains the authoritative benchmark until the index is restored.
- CelesTrak's public SATCAT CSV is now a separate higher-frequency candidate.
  It provides one current catalogue row per known object with a launch date;
  the dashboard aggregates the latest ten years to launch-month × object type
  (`Payload`, `Rocket body`, `Debris`, `Unknown`). Payload counts are close to
  the OWID annual benchmark in recent years but are not identical or
  interchangeable: SATCAT is a tracking catalogue, includes non-payload
  objects, and can be revised. The full raw snapshot is retained locally and
  the compact monthly contract is written to
  `data/normalized/hk_commercial_aerospace/global_cataloged_objects_monthly.jsonl`.
  If a live SATCAT request fails, the builder now serves that normalized
  monthly cache as stale rather than dropping the chart from the artifact.
- The annual global objects benchmark keeps numeric `year` values in the data
  contract and a separate textual `year_label` for chart axes. The benchmark
  remains annual object/payload activity and is not a rocket-launch cadence
  series.
- Wikimedia Wikipedia Pageviews is now a separate public-attention signal. The
  production basket contains nine explicit English Wikipedia pages (SpaceX,
  Starlink, Rocket Lab, Falcon 9, New Glenn, Long March, Chinese space
  program, Satellite constellation and Commercial spaceflight) and preserves
  monthly `user`, `spider`, `automated` and `all-agents` rows from 2015-07
  onward in `data/normalized/hk_commercial_aerospace/wikimedia_aerospace_pageviews_monthly.jsonl`.
  The artifact publishes aggregated agent history, user views by page and a
  latest-page/agent table. The fetcher uses a 0.75-second throttle, retries
  HTTP 429 responses and falls back to the normalized snapshot as cache; a
  partial/cache result is reported as degraded/stale. Pageviews count page
  loads, not unique people, search volume or mainland-China domestic demand.
  Massviews remains the discovery/maintenance path for candidate pages, not a
  changing production category.

Google Patents remains a degraded, non-core source until the direct Google
Patents request shape, assignee normalization and patent-family deduplication
are fixed. SerpAPI is deliberately not used for this source. The dashboard
should keep that gap visible rather than treating an empty result as zero
patents.
