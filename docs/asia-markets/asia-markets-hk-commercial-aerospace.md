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
- Verify US-side policy catalysts (NASA contracts, FAA licensing) —
  flagged as "almost certainly free" but not individually checked.
- Confirm Guowang's Celestrak designator by cross-referencing candidate
  international designators (e.g. `2026-168A`–`2026-168J`) against Launch
  Library 2's mission data once its rate limit resets.
- Periodically re-run the SSE STAR Market keyword search for Galactic
  Energy, Space Pioneer, and i-Space to catch when/if any of them gets an
  accepted filing.
- Check whether any of the 5 IPO-race companies has instead filed with
  Shenzhen's ChiNext rather than Shanghai's STAR Market — not checked
  this pass, since the confirmed API only covers Shanghai.
