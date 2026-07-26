# HK Focus List: Final Six

Six sectors/themes chosen as the initial focus, in the given order. Each
now has its own dedicated doc (split out so this file can stay a lean
index/priority-tracker rather than duplicating content). This file says
what's next for each; the linked doc has the full research.

**Current top priority: #1, Properties & Construction / HK real estate** —
flagged as the most interesting and unique of the six. Minerals (#6) is
explicitly on hold — there's already a working pipeline for it, revisit
later rather than investing further now.

## 1. Properties & Construction — ⭐ TOP PRIORITY

Full doc: [asia-markets-hk-real-estate.md](asia-markets-hk-real-estate.md)

Seven rounds deep: the official stack (SRPE, RVD, Housing Bureau, Lands
Department), independent private benchmarks (Centaline, Midland and weekly
28Hse EPI/ERI), transaction/new-project portals with source-lineage rules,
commercial/office/REIT cash flow, property policy and a full frequency audit.
The stock universe is now separated into HK developers/landlords, HK REITs,
mixed-geography names, agency exposure and mainland developers listed in HK.
The stock-translation layer maps projects/assets into revenue recognition,
project margins, debt/refinancing, realizable NAV, investment-property cash
flow, market positioning and HKEX corporate events.

**Next step — research first, no model or scraper yet:** Round 9 has completed
an initial four-series RVD vintage test, three-project SRPE/28Hse audit,
fourteen-company exposure pass and corporate-family map. Continue collecting
SRPE/RVD vintages and finish the genuinely open gates: a 14–45 day
agency-deal-to-registration follow-up, commercial KPI definition matching, and
HKEX publication/effective-time audit. Only after those produce a written
evidence log should source schemas, automation or modelling be fixed.

## 2. Stablecoin / Crypto

Full doc: [asia-markets-hk-stablecoin-crypto.md](asia-markets-hk-stablecoin-crypto.md)

Company tiers (licensed infra → bank/big-tech positioning → concept-stock
pivots → BTC/ETH/SOL treasury plays), a policy-catalyst watchlist
(HKMA/SFC/LegCo), a popularity-tracking layer (crypto price/volume, Fear &
Greed Index, confirmed US GENIUS Act as the key US catalyst), and
stablecoin market-share tracking (DefiLlama, Circle/CRCL as the public
comp). No further research needed to start — this is ready to build against.

## 3. Commercial Aerospace

Full doc: [asia-markets-hk-commercial-aerospace.md](asia-markets-hk-commercial-aerospace.md)

Verified free launch-cadence trackers (spacelaunchschedule.com,
nextspaceflight.com, rocketlaunch.live) and a confirmed policy-escalation
narrative (2024/2025 Government Work Report, CNSA's 2025–2027 action plan,
~$348bn 2025 market-size target). Best used as a theme-timing overlay
(Cirrus Aircraft and Continental Aerospace are the two verified "real
business" names; the rest is more diffuse theme exposure) — ready to build,
same caveat as before about stock-specific read-through being fuzzy.

## 4. Consumer Discretionary Trend Stocks (Laopu Gold, Pop Mart, and peers)

Full doc: [asia-markets-hk-consumer-trend-stocks.md](asia-markets-hk-consumer-trend-stocks.md)

Company list with tickers/market caps pulled directly from the internal
HSCI dataset — Pop Mart, Laopu Gold, Anta, Chow Tai Fook, Mixue, Guming,
Chabaidao, Mao Geping, Giant Biogene, Bloks Group. Plus the Labubu
resale-price mechanism (Xianyu/StockX, verified real), Apple's official
top-charts feed for international expansion, and a mainland trend-index
tool comparison (Baidu Index and Douyin/Ocean Engine Index are free and
official; WeChat Index and Xiaohongshu have no official API at all —
third-party paid scrapers only; Google Trends via SerpApi as a
secondary/international-interest option, verified pricing).

**Next step:** Baidu Index + Xiaohongshu/Douyin hashtag tracking is the
core build here — Google Trends/SerpApi is secondary for this basket
specifically, since Google is blocked in mainland China.

## 5. Local Consumer

Full doc: [asia-markets-hk-local-consumer.md](asia-markets-hk-local-consumer.md)

Google Trends (HK-region — the primary tool here, not secondary, since this
list is HK-local rather than mainland-driven), web-scraped store/price data
(delivery-app merchant listings, Google popular-times for flagship stores),
and verified HK macro (Census & Statistics Dept retail sales index,
Immigration/HKTB visitor arrivals). This is the best-instrumented of the
newer themes — official, free, monthly, and directly causal for this exact
company list (Café de Coral, Sa Sa, Chow Sang Sang, Luk Fook, Tai Hing,
Giordano).

## 6. Minerals — not just gold (ON HOLD)

Full doc: [asia-markets-hk-minerals.md](asia-markets-hk-minerals.md)

**On hold** — this repo already has a working pipeline for exactly this
(`src/minerals_signal_data/`), tracking the USGS critical minerals list (22
tracked live, 19 on ETF-style proxies, 19 flagged paywalled/impractical),
plus a dedicated `chinatungsten_scraper.py` that's likely the "half ready"
part referenced when this was deprioritized. Gallium, germanium, antimony,
and rare earths are exactly the minerals China has put export controls on
since 2023 — a stronger edge story than generic base-metals tracking, worth
revisiting later rather than now.

## Not in this focus list (parked separately)

Gaming (博彩) and Aviation (航空) were part of the original theme research
but didn't make the final six — both explicitly marked TODO in
[asia-markets-hk-parked-themes.md](asia-markets-hk-parked-themes.md).
