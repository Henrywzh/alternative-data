# "Hot" / IP-Driven Consumer Trend Stocks (Laopu Gold, Pop Mart, and similar)

Companion to [asia-markets-hk-sectors.md](asia-markets-hk-sectors.md) and
[asia-markets-hk-alt-data-sources.md](asia-markets-hk-alt-data-sources.md).
Item #4 in the [focus list](asia-markets-hk-focus-list.md) — "Consumer
Discretionary Trend Stocks."

Pulled directly from the internal HSCI dataset (`Research/data/processed/`,
same source as the main sector doc) rather than re-scraping the web, so
these are on the same footing as the rest of the sector work — official
HSI industry tag + computed market cap, snapshot ~Jan 2026.

**akshare, already usable for every name in this list** (full audit:
[asia-markets-hk-akshare-capabilities.md](asia-markets-hk-akshare-capabilities.md)):
`stock_hk_dividend_payout_em(symbol)` for dividend event history,
`stock_financial_hk_analysis_indicator_em(symbol)` for margins/ROE/growth,
`stock_hk_profit_forecast_et(symbol)` for sell-side target prices — all
free, verified, work on any HK ticker including Pop Mart (9992), Laopu
Gold (6181), etc. `stock_hk_hot_rank_em()` (guba-attention-based
popularity ranking) is a possible free retail-sentiment proxy worth
checking against this specific basket. Note: akshare's IPO tracker
(`stock_ipo_hk_ths`) is confirmed broken/mislabeled — don't use it for
this cluster's recent-IPO names.

| Company | Ticker | Official sector tag | Market Cap (USD bn, ~Jan 2026) |
|---|---|---|---|
| Pop Mart International | 9992.HK | Consumer Discretionary | ~30.5 |
| Anta Sports | 2020.HK | Consumer Discretionary | ~29.1 |
| Chow Tai Fook Jewellery | 1929.HK | Consumer Discretionary | ~16.7 |
| Laopu Gold | 6181.HK | Consumer Discretionary | ~14.8 |
| Mixue Group (bubble tea) | 2097.HK | Consumer Staples | ~20.4 |
| Li Ning | 2331.HK | Consumer Discretionary | ~6.7 |
| Miniso | 9896.HK | Consumer Discretionary | ~6.0 |
| Guming Holdings (bubble tea) | 1364.HK | Consumer Staples | ~8.3 |
| Giant Biogene (skincare) | 2367.HK | Healthcare *(tag)* | ~4.8 |
| Mao Geping (cosmetics) | 1318.HK | Healthcare *(tag)* | ~5.4 |
| Chabaidao (bubble tea) | 2555.HK | Consumer Staples | ~1.2 |
| Bloks Group (blind-box building toys) | 0325.HK | Consumer Discretionary | ~2.2 |

Worth noting: the official HSI taxonomy tags **Giant Biogene and Mao
Geping under Healthcare**, not Consumer Discretionary — a cosmetics/skincare
classification quirk similar to the Alibaba-under-Consumer-Discretionary one
flagged in the main sector doc. Don't drop these two from a "hot consumer
names" screen just because they show up in the Healthcare bucket.

This is a real, identifiable cluster: **IP/brand-driven consumer names that
IPO'd or re-rated in 2024–2026** — collectibles (Pop Mart, Bloks Group),
heritage/luxury gold jewelry (Laopu Gold, vs. established Chow Tai Fook),
premium domestic cosmetics (Mao Geping, Giant Biogene), and the freshly-made
tea/bubble-tea wave (Mixue, Guming, Chabaidao). Alt-data angles specific to
*this* cluster, distinct from generic Consumer Discretionary/Staples
sources already listed:

| Source | What it is | Signal | Access |
|---|---|---|---|
| **Secondary-market resale prices** (StockX, eBay, Xianyu/闲鱼, Mercari) | Resale premiums on Pop Mart/Labubu figures | **Verified real** — standard editions resell $30–80, rare "chase" variants $200–1,500+; Xianyu chase variants trade at ~6x retail. This is one of the most direct, real-time hype gauges available for Pop Mart specifically — a widening or collapsing resale premium is a leading indicator ahead of quarterly GMV | **Checked robots.txt directly — StockX is genuinely locked down**: `/search*`, `/api/`, and most listing-discovery paths are disallowed, plus a long list of blocked parameter combinations — this isn't a scraper-friendly site by policy. **Xianyu is more tractable in practice**: it's Alibaba's C2C resale marketplace, and third-party tools (several on Apify) already scrape it successfully via Alibaba's internal `mtop` API endpoint, no login needed for basic search — this is the better of the two to actually build against |
| **Apple official top-charts JSON feed** (verified in the alt-data-sources doc, Round 3) | Pop Mart / brand companion-app rank, per country | Tracks international expansion momentum (US, SE Asia, Europe) for names exporting hype beyond China | Free, official, `rss.applemarketingtools.com` |
| **HK gold trade stats** (see the minerals doc) | Chinese gold import/export volumes through HK | Input-cost/demand-cycle context specifically for Laopu Gold and Chow Tai Fook, whose margins are gold-content-sensitive | Free, monthly |
| **Xiaohongshu (小红书/RED) and Douyin hashtag view counts** | China's dominant Gen-Z consumer-discovery platforms | The primary discovery channel for this whole cluster (bubble tea, collectibles, cosmetics) — mention volume/view counts are a leading indicator ahead of store traffic or GMV | Public view counts visible on-platform; scraping ToS not evaluated |
| **Delivery-app merchant listings by city** | Store count per brand, city by city | For the tea chains (Guming, Chabaidao, Mixue) whose core KPI is store-count growth, delivery-app merchant listings are a scrapable proxy for real-time footprint expansion, ahead of official same-store-sales disclosure | Use Meituan/Ele.me for mainland cities. For HK specifically: **foodpanda HK** (robots.txt checked, workable — see below) and **Meituan's Keeta** — real domain is `keeta-global.com` (not meituan.com, which 404s for HK purposes), **robots.txt checked and it's wide open**: only blocks a couple of ad-tracking query parameters (`gad_`, `subId1`), everything else including menu/restaurant listing pages is fair game. Deliveroo has fully exited Hong Kong, so it's out of the picture entirely |

## Trend-index tools for mainland China hype tracking

Google Trends is a secondary/international-interest signal here, not the
primary one — **Google itself is blocked in mainland China**, so it
structurally undercounts mainland search behavior for these China-domestic
brands. The right primary tools:

| Tool | What it is | Access reality |
|---|---|---|
| **Baidu Index (百度指数)**, `index.baidu.com` | Search-volume trends, the closest mainland equivalent to Google Trends | **Checked developer.baidu.com directly** — no official bulk/developer API for Baidu Index specifically (Baidu's other APIs — translation, cloud, etc. — don't cover this). Web lookup only |
| **Douyin Index / Ocean Engine Index (巨量算数)**, `trendinsight.oceanengine.com` | Douyin's own trend/analytics tool — video/hashtag view trends, demographic breakdowns | **Correction — this is harder than initially assumed, not "official web lookup similar to Baidu Index."** The underlying API endpoint exists (`.../api/open/index/get_multi_keyword_hot_trend`) but requires Douyin's standard anti-bot signature parameters (`msToken`, `X-Bogus`, `_signature`) — the same signing scheme any Douyin scraper has to crack, not a documented public API. Ocean Engine's real developer platform (`open.oceanengine.com`, with proper Java/Go SDKs) is for **advertising-campaign data**, not this trend tool. Also a moving target: 巨量算数 is scheduled to be renamed/merged into "抖音指数" (Douyin Index) on Jan 1, 2026, switching to Douyin's own login system |
| **WeChat Index (微信指数)** | Search-volume trends *within* WeChat | Only accessible via the WeChat mini-program itself — no official web/API. Third-party paid scraping services (e.g. TikHub, JustOneAPI) offer programmatic access |
| **Xiaohongshu/RedNote** | No official "index" tool at all (unlike Baidu/Douyin) | Third-party paid scraping APIs only (TikHub, JustOneAPI, Apify RedNote scraper) — same access tier as WeChat Index |
| **Google Trends via SerpApi** | Structured JSON access to Google Trends instead of the unofficial `pytrends` scrape | **Verified pricing**: 250 free searches/month, then $25/mo for 1,000, $75/mo for 5,000 — a real cost at scale, but removes the fragility of unofficial scraping |
| **Wikimedia Pageviews API** (`wikimedia.org/api/rest_v1/metrics/pageviews`) | Daily pageview counts for e.g. "Pop Mart", "Labubu", "Laopu Gold" article pages | Free, official, no auth, clean JSON — but same caveat as Google Trends: **Wikipedia has been blocked in all languages in mainland China since 2019**, so this reflects global/HK/diaspora attention, not mainland hype. Genuinely useful for Pop Mart's *international* expansion story specifically, same role as Google Trends here |

**Revised tiering after checking actual access mechanics:** none of the
four mainland tools have a genuinely clean public API — this whole
category is harder than the "just use Baidu Index" framing suggested.
- **Baidu Index**: free, official, but manual web-lookup only.
- **Douyin/Ocean Engine Index**: browsable for free, but programmatic
  access means reverse-engineering the same anti-bot signature scheme any
  Douyin scraper faces — not meaningfully easier than scraping Douyin
  directly, and about to change format (Jan 2026 rename).
- **WeChat Index / Xiaohongshu**: no official API at all, paid
  third-party scrapers only (TikHub, JustOneAPI, Apify).
- **Xianyu resale-price data**: the one genuine bright spot — third-party
  tools already scrape it successfully via Alibaba's internal API, more
  tractable than StockX.

**Next step:** given none of these are truly "free API, just call it,"
the realistic build order is: (1) Xianyu resale-price scraping first,
since working tools already exist for it; (2) manual/periodic Baidu Index
lookups as a cheap directional check even without bulk access; (3) treat
WeChat Index/Xiaohongshu/Douyin Index as a paid-third-party-provider
decision, not a quick free build.

### Baidu Index deep dive — the real access story is "login required," not "web lookup"

Checked four candidate tools directly. The finding that matters most:
**every single one of them — official site included — requires a logged-in
Baidu account and a browser session cookie (`BAIDUID`/`BIDUPSID`).**
Baidu Index isn't a public webpage you can just query; you have to be
authenticated even to *view* it manually. That's a meaningfully bigger
practical barrier than the "official, free web lookup" framing earlier in
this doc implied — it means a real account (likely needing a Chinese phone
number to register) and ongoing cookie-freshness management, not just an
occasional anonymous page visit.

| Tool | What it is | Maintenance / reliability |
|---|---|---|
| `Saber2pr/baidu-chart-api` | TS/JS CLI + programmatic wrapper (`new BaiduChart(cookie).search(keyword)`), caches cookie locally | Low — 2 stars, 1 fork, appears dormant |
| `dzqann/BaiduIndex` | Python/Excel GUI scraper, paste cookie into a form, batch-query keywords from a spreadsheet | Very low — 1 commit total, 11 stars, essentially abandoned |
| `justinzm/gopup` | A **much broader** Python data library (2.6k stars) — Baidu Index is one small piece of a set that also covers Weibo/Sogou/Google index equivalents, Chinese macro data (GDP/CPI/PPI/PMI/rates/FX), unicorn-company data, Weibo KOL/influencer data, oil prices, **migration pattern data**, and even COVID tracking. Some interfaces need a registered token on top of the cookie | **Real risk**: last release Sept 2022 — ~4 years stale as of this session. Baidu's anti-bot measures almost certainly evolved since then, so the underlying scraping logic may simply be broken now, untested |
| `BaiduIndexHunter` (found via the Juejin write-up, repo at `Auroral0810/BaiduIndexHunter`) | Full Flask + Vue3 web platform, cookie-based with **cookie rotation** across multiple accounts (implying single-account usage hits limits fast), 6 data dimensions, exports to CSV/Excel/Parquet/SQLite, WebSocket progress tracking, checkpoint recovery | Reported "46.4k stars" — **worth treating with real skepticism** (that's an unusually large number for a niche single-purpose scraper; could reflect star-inflation, which is a known issue on GitHub). The most feature-complete of the four by description, but independent maintenance/reliability wasn't confirmed |

**Given the login/cookie reality across the board, the practical
recommendation changes:** rather than adopting one of these fragile,
mostly-unmaintained community scrapers (which will break whenever Baidu
tweaks its anti-bot page, same failure mode as any of them), **a scheduled
agent session (Claude/Codex/Antigravity) that logs in, holds the
authenticated session, and periodically queries the specific keywords we
care about is probably more resilient than any static reverse-engineered
tool** — an agent can adapt to UI changes and re-authenticate; a hardcoded
scraper just breaks. Treat the four tools above as reference/acceleration
if a pure-code path is wanted later, not as the primary plan.

## Round 2 — corporate-events layer, and two access-mechanics corrections

**IPO lock-up expiry — a genuine, calendarized, mechanical catalyst for
this exact cluster.** Confirmed via HKEX rulebook: controlling shareholders
are barred from disposing shares from the listing-document date through
**6 months after trading starts**, and can't drop below "controlling
shareholder" status for a further 6 months after that — effectively a
12-month restriction window in two stages. Every 2024–2026 IPO in this
sector (Bloks Group, Jan 10 2025; Guming, Feb 2025; Mao Geping; Chabaidao)
has an exact, computable lock-up date straight from its listing date — this
is the same "policy catalyst calendar" pattern used for stamp duty/HKMA
LTV moves in the real-estate doc, just corporate rather than governmental.
Most of the *initial* 6-month windows for this batch have already passed
by now, so the near-term value is in **tracking future IPOs in this cluster
going forward**, not the historical ones.

**Pop Mart and Laopu Gold specifically now have single-stock options with
weekly expiries.** HKEX announced (Sept 2025) it's introducing weekly
expiries for 17 stock-option classes, explicitly naming Pop Mart and Laopu
Gold among them. This makes the universal free HKEX stock-options
open-interest report (confirmed free earlier this session) **directly,
specifically actionable for this sector** — weekly expiries give a much
finer-grained positioning/sentiment read than the standard monthly cycle
most HK single-stock options run on.

**Pop Mart issues standalone quarterly trading updates, not just
semi-annual results.** Confirmed: a Q3 2025 update disclosed **245–250%
YoY revenue growth**, released as a standalone HKEXnews announcement ahead
of the next full results (Aug 25, 2026). This is a genuine, free,
company-specific disclosure pattern worth monitoring directly via
HKEXnews for this name (and worth checking whether Mixue/Guming/Chabaidao
do the same, not confirmed this round).

**Two access-mechanics corrections, one worse than expected, one better:**
- **Xiaohongshu — checked `robots.txt` directly, and it's essentially a
  hard wall.** `Disallow: /` for all agents by default, with narrow
  exceptions only for a couple of specific paths (`/worldcup26`,
  `/explore/`) and only for Baidu/Bing/Sogou/Yisou bots — **Googlebot is
  explicitly excluded even from those**. This upgrades the earlier "no
  official API" note to "actively disallowed by policy," not just
  unsupported.
- **foodpanda HK — checked `robots.txt`, and it's genuinely workable.**
  Only the normal admin/auth/campaign paths are blocked; restaurant/menu
  listing pages aren't. It explicitly allows OAI-SearchBot/ChatGPT-User
  (though blocks plain GPTBot, an interesting split between OpenAI's
  search crawler and its training crawler). This confirms foodpanda HK as
  the real replacement for the Deliveroo correction from the local-consumer
  doc, not just an assumption.

**Tmall/JD shopping-festival brand rankings — real, but press-reported,
not a clean API.** Tmall does publish category leaderboards each 618/
Double 11 (including "toys and trendy playthings" — directly Pop Mart/
Bloks Group's category, and "jewelry" — Laopu/Chow Tai Fook's), but the
distribution channel is industry trade press (e.g. Digitaling) covering
the official platform data after the fact, not a queryable live feed.
Useful as a twice-a-year read, not a build target.

## Open questions / not yet done
- The resale-price and social-media angles are the least "clean API" of
  anything in this doc — real signal, but scraping-dependent and
  ToS-unverified; flag before building anything automated on top of them.
- WeChat Index / Xiaohongshu programmatic access requires picking and
  vetting a specific paid third-party provider (TikHub vs. JustOneAPI vs.
  Apify) — not done.
- Whether Mixue/Guming/Chabaidao issue voluntary trading updates the way
  Pop Mart does — not checked.
- Future IPO calendar for this cluster (who's next) — not checked; would
  make the lock-up-expiry catalyst forward-looking rather than historical.
