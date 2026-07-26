# Hong Kong Stock Market — Free Alternative Data Sources by Sector

Companion to [asia-markets-hk-sectors.md](asia-markets-hk-sectors.md). This
merges two independent brainstorms (Gemini, pasted into chat; Google
Antigravity's own brainstorm saved at
`~/.gemini/antigravity/brain/4b16082d-718a-4c9e-a111-7797780937ef/hk_alt_data_sources.md`)
into one deduplicated list, mapped to the same 12 HSCI sectors. The two lists
overlapped heavily (HKEX Stock Connect, PBOC/NFRA filings, NPPA game
approvals, CPCA EV sales, Macau DICJ GGR, SCFI, SHFE/LME inventories,
clinical trial registries, HK Land Registry, MIIT telecom stats, NBS retail
sales, NEA power stats, HKO weather, Cathay/HKIA traffic, port throughput) —
that convergence itself is a decent confidence signal.

**Verification status:** spot-checked a couple of the highest-value/most
HK-specific ones (HK Land Registry via data.gov.hk, HKEX Stock Connect
stats) — both real, both free, though the exact URLs either AI gave were
stale/wrong; corrected links below. The rest are *not yet individually
verified* — treat entries below as a prioritized research backlog, not a
confirmed-working list, until each is actually hit with a script.

## 1. Financials
*Key names: ICBC, HSBC, ABC, CCB, China Life, Ping An, CMB, AIA, HKEX, BOC HK*

| Source | What it is | Signal | Access |
|---|---|---|---|
| [HKEX Stock Connect — Historical Daily](https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Statistics/Historical-Daily?sc_lang=en) | Daily Northbound/Southbound turnover, quota usage | Proxy for HKEX (0388) clearing revenue + mainland investor appetite for HK names | Verified real & free; confirmed working URL (the "Consolidated-Reports" path both AIs gave 404s) |
| HKEX daily short-selling turnover by stock | Daily short turnover per ticker | Short conviction on financials/H-shares | Known to exist on HKEX site; exact current URL not yet confirmed |
| [PBOC statistical data](http://www.pbc.gov.cn/) | Monthly M2, Total Social Financing, new RMB loans, LPR | Leading indicator for state bank (ICBC/CCB/ABC/CMB) NIM and credit demand | Public, Chinese-language, monthly press releases |
| NFRA (National Financial Regulatory Administration) premium data | Monthly gross written premium by insurer, life vs. property | Pre-earnings top-line proxy for Ping An, China Life | Public but scattered across NFRA announcements + insurer IR pages |
| HKMA Monthly Statistical Bulletin | HKD deposits, loan growth, mortgage delinquency | Local HK bank health (BOC HK, HSBC's HK book) | Free, published monthly by HKMA |

## 2. Information Technology
*Key names: Tencent, Xiaomi, SMIC, NetEase, Hua Hong, Lenovo*

| Source | What it is | Signal | Access |
|---|---|---|---|
| [NPPA game approval list ("banhao")](https://www.nppa.gov.cn/) | Monthly official game license list | Leading indicator for Tencent/NetEase monetization pipeline | Public, Chinese-language, monthly |
| Qimai.cn / AppMagic / Sensor Tower free tiers | App Store / Play Store download & grossing ranks | Revenue proxy for mobile game blockbusters, Xiaomi IoT app installs | Free tiers exist but rate-limited; Qimai is Chinese-only |
| GACC customs IC (integrated circuit) trade data | Monthly IC export/import volumes & values | Foundry utilization proxy for SMIC, Hua Hong | Free, monthly, via China customs portal |
| CAICT/MIIT smartphone shipment reports | Monthly China phone shipment volumes | 5G/replacement cycle tracker for Xiaomi | Free, published monthly |
| DRAMeXchange free summaries, distributor stock counts (Mouser/DigiKey/Arrow) | Spot wafer/memory pricing, inventory levels | Margin proxy for SMIC/Hua Hong; demand signal from rising distributor stock | Free-tier price summaries; inventory counts scrapable from product pages |

## 3. Consumer Discretionary
*Key names: Alibaba, BYD, Meituan, Baidu, JD.com, Trip.com, Galaxy Entertainment*

| Source | What it is | Signal | Access |
|---|---|---|---|
| CPCA (China Passenger Car Association) weekly/monthly reports | Retail & wholesale passenger vehicle sales, NEV breakdown | High-frequency demand tracker for BYD, ahead of official monthly deliveries | Free, weekly cadence for insurance-registration-based numbers |
| [Macau DICJ](https://www.dicj.gov.mo/) monthly Gross Gaming Revenue | Official GGR release, 1st of each month | Direct macro driver for Galaxy Entertainment | Free, official government bureau |
| Macau DSEC (Statistics and Census Service) | Visitor arrivals, hotel occupancy | Complements DICJ GGR for gaming/tourism read-through | Free |
| State Post Bureau (SPB) monthly parcel volume | National courier parcel counts | Retail activity proxy for Alibaba/JD.com e-commerce | Free, monthly |
| Centaline / Trip.com / Autohome-style scraping (hotel "sold out" status, ticket pricing) | Scraped listing/price data | Leading demand read for Trip.com travel segment | Requires a scraper; ToS risk not evaluated |
| MTR Corporation monthly ridership stats | HK local + cross-boundary passenger traffic | Direct revenue driver, published on MTR's own site | Free, company-published |

## 4. Energy
*Key names: PetroChina, Shenhua Energy, CNOOC, Sinopec*

| Source | What it is | Signal | Access |
|---|---|---|---|
| NBS industrial production data | Monthly crude processing, raw coal, gas output | Output proxy for PetroChina/Shenhua | Free, monthly, NBS portal |
| GACC customs energy trade logs | Monthly coal/crude/LNG import-export volumes | Domestic supply/demand balance | Free, monthly |
| Qinhuangdao port coal inventory (via SXCoal/Mysteel free sections) | Daily coal stockpile levels at China's largest coal hub | Inverse proxy for power demand — high inventory = weak demand (bad for Shenhua) | Free summaries; full data may be paywalled |
| MarineTraffic / VesselFinder free tiers (AIS) | Tanker/offshore vessel density near CNOOC fields | Extraction/throughput proxy | Free tier has coverage/history limits |
| Sentinel-2 / Landsat-8 via Copernicus Browser or Sentinel Hub Playground | Satellite infrared gas flaring detection | Flaring intensity ~ refinery/extraction throughput | Genuinely free (Copernicus is open data) but needs real remote-sensing effort to turn into a usable signal |

## 5. Industrials
*Key names: CATL, CRRC, COSCO Shipping, ZTO Express, J&T Express*

| Source | What it is | Signal | Access |
|---|---|---|---|
| Shanghai Containerized Freight Index (SCFI) + Ningbo CFI (NCFI) | Weekly container spot freight rates | Direct revenue driver for COSCO Shipping | Free, published weekly by Shanghai Shipping Exchange |
| State Post Bureau (SPB) express delivery data | Monthly parcel volume + avg unit revenue | Direct driver for ZTO, J&T Express | Free, monthly |
| SMM (Shanghai Metals Market) battery supply chain data | Lithium carbonate / Ni / Co spot prices | Margin proxy for CATL | Free-tier weekly summaries |
| AIS ship telemetry (VesselFinder/MarineTraffic) + port authority stats | Port congestion, ship wait times | Spot rate pressure signal for COSCO | Free tier limited to recent history/coverage |

## 6. Materials
*Key names: Zijin Mining, CMOC, China Hongqiao, Ganfeng Lithium, Shandong Gold*

| Source | What it is | Signal | Access |
|---|---|---|---|
| SHFE (Shanghai Futures Exchange) daily/weekly warehouse inventory | Copper/aluminum/zinc/lead stock levels | Cash-flow proxy for Zijin/Chalco/Jiangxi Copper | Free, published by SHFE |
| LME daily warehouse stock reports | Global metals inventory | Complements SHFE for global supply/demand read | Free, published by LME |
| China Nonferrous Metals Industry Association (CNIA) reports | Capacity utilization, production volumes | Direct output proxy for Hongqiao (aluminum), Ganfeng (lithium) | Public, Chinese-language |
| SMM / Fastmarkets free summaries | Spot price assessments (lithium carbonate, neodymium, cobalt) | Pricing input for Ganfeng, CMOC | Free-tier bulletins |

## 7. Healthcare
*Key names: Hengrui, WuXi AppTec, BeiGene, Innovent, JD Health, WuXi Biologics*

| Source | What it is | Signal | Access |
|---|---|---|---|
| [ClinicalTrials.gov API v2](https://clinicaltrials.gov/api/v2/studies) | Global clinical trial registry, queryable by sponsor | Pipeline milestones for BeiGene, Hengrui; outsourcing demand for WuXi | **Verified working** — a runnable example already exists at `~/.gemini/antigravity/brain/4b16082d-718a-4c9e-a111-7797780937ef/scratch/track_beigene.py` (simple `requests` call, no auth needed) |
| Chinadrugtrials.org.cn (CDE registry) | China-specific trial registry | Same as above, domestic filings | Public, Chinese-language |
| NHSA VBP (Volume-Based Procurement) results | Government tender price-cut/winner lists | Margin compression estimate for generics/mAbs | Free, published after each tender round |
| WIPO Patentscope / Google Patents / CNIPA | Patent filings | Early pipeline-expansion signal | Free, queryable by assignee name |

## 8. Properties & Construction
*Key names: Sun Hung Kai, CR Land, Beike, Henderson Land, CK Asset*

| Source | What it is | Signal | Access |
|---|---|---|---|
| [Centa-City Leading Index (CCL)](https://hk.centanet.com/CCI) | Weekly HK secondary-market residential price index | The premier high-frequency HK property proxy | **Free, verified concept** — Centaline publishes this weekly; highly recommend prioritizing this one |
| [Land Registry monthly statistics](https://www.landreg.gov.hk/en/monthly/monthly.htm) | Free aggregate ASP/deed counts and values by receipt month, including primary/secondary, price-band and regional cuts | Transaction volume/liquidity proxy for SHKP, Henderson, CK Asset | **Verified free web tables, not a public unit-level API.** Receipt month is later than contract signing; IRIS and the restricted institutional Land Search API are separate paid services |
| CRIC / Wind public summaries | Top-100 mainland developer monthly contracted sales & GFA | Direct driver for CR Land, COLI | Free summaries; full CRIC data is paid |
| HK Buildings Department monthly bulletins | Construction starts, occupation permits, plans approved | Forward pipeline measure | Free, government-published |
| KE.com (Lianjia/Beike) listing scraping | Listing counts, price-cut ratios by city | Real-time transaction velocity/sentiment | Requires scraper; ToS risk not evaluated |

## 9. Telecommunications
*Key names: China Mobile, China Telecom, China Unicom, China Tower*

| Source | What it is | Signal | Access |
|---|---|---|---|
| MIIT monthly telecom industry bulletins | 5G subscriber adds, broadband adds, base station counts | Market share + China Tower tenancy proxy | Free, monthly, Chinese-language |
| Operator IR pages (China Mobile/Telecom/Unicom) | Voluntary monthly KPI disclosures | Subscriber/ARPU tracking ahead of quarterlies | Free, published directly by companies |
| OpenCelliD / Mozilla Location Service | Open cell tower geolocation database | Network build-out speed/density (filter MCC 460 = China) | Free, community-maintained, may lag actual rollout |

## 10. Consumer Staples
*Key names: Nongfu Spring, Haitian, WH Group, Budweiser APAC, Tsingtao*

| Source | What it is | Signal | Access |
|---|---|---|---|
| China Ministry of Agriculture (MARA) weekly reports | Hog prices, grain/barley prices | Input cost tracker: hogs → WH Group margins; barley → Budweiser/Tsingtao | Free, weekly |
| NBS monthly retail sales (F&B/alcohol) | Retail trade breakdown | Category-level demand read | Free, monthly |
| PET resin / glass / packaging material pricing (industrial chemical portals) | Input cost | Packaging cost driver for Nongfu Spring | Free-tier pricing pages, scattered sources |
| Manmanbuy.com / e-commerce price scraping (JD/Tmall) | Retail shelf price tracking | Detects price hikes/promos ahead of margin reports | Requires scraper |

## 11. Utilities
*Key names: CGN Power, CLP Holdings, CK Infrastructure, Towngas, Huaneng*

| Source | What it is | Signal | Access |
|---|---|---|---|
| [Hong Kong Observatory Open Data API](https://data.weather.gov.hk/weatherAPI/doc/HKO_Open_Data_API_Documentation.pdf) | HK temperature/precipitation, JSON API | Heatwave → cooling demand (CLP); cold snap → gas heating (Towngas) | Free, official, well-documented API |
| NEA (National Energy Administration) monthly power stats | Generation by source (nuclear/wind/solar/thermal) | Utilization proxy — nuclear for CGN, wind for Longyuan | Free, monthly |
| NBS electricity consumption data | Consumption by sector | Complements NEA generation-side data | Free, monthly |

## 12. Conglomerates
*Key names: CITIC Ltd, Swire Pacific, CK Hutchison, Fosun*

| Source | What it is | Signal | Access |
|---|---|---|---|
| HKIA (HK Intl Airport) traffic statistics + Cathay Pacific monthly traffic disclosures | Passenger/cargo throughput, load factors | Direct Cathay earnings driver → Swire Pacific | Free, published monthly |
| FlightRadar24 (free tier) | Flight activity/frequency at HKG | Supplementary real-time traffic read | Free tier is delayed/limited |
| ISL Container Port Monitor / Drewry free summaries | Global container throughput indexes | Trade-volume driver for CK Hutchison's Hutchison Ports | Free summaries; full reports are paid |
| HK Marine Department — Kwai Tsing container throughput | Local HK port TEU volumes | Direct measure of the HK leg of CK Hutchison's ports business | Free, government-published |

## Cross-sector / universal trackers
| Source | Applies to | Access |
|---|---|---|
| Google Trends (`pytrends`) | Trip.com travel interest, Meituan services, Xiaomi launch hype | Free, unofficial API, well-trodden Python library |
| **GitHub REST API** | Tencent/Alibaba/Baidu developer ecosystem activity, open-model release momentum (Qwen, DeepSeek), crypto/blockchain project activity | **Verified**: 60 req/hour unauthenticated, 5,000 req/hour with a free personal access token — genuinely free and developer-friendly, no paid tier needed. **This repo already has working infra for it** — `src/github_trending_data/` and `src/provider_adoption_data/sources/github.py` — extending the existing provider registry to more orgs/repos is cheaper than building a new pipeline |
| **Wikimedia/Wikipedia Pageviews API** | Any named company, person, or topic — genuinely universal | **Verified real, free, no auth**: `wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{project}/{access}/{agent}/{article}/daily/{start}/{end}` — clean JSON, daily granularity, history going back years. A structured, non-fragile alternative/complement to Google Trends for "is attention on this rising" questions (rocket launches, IPO debuts, policy events). **Caveat, same shape as the Google Trends/China issue**: Wikipedia has been **blocked in all languages in mainland China since 2019** — so pageview data reflects global/HK/Taiwan/diaspora interest, not mainland domestic attention. Fine for HK-specific or international-facing questions (Pop Mart's overseas expansion, a HK-listed company's English-language press coverage), weak as a mainland-hype proxy — same role Google Trends plays vs. Baidu Index in the consumer-trend-stocks doc |
| WIPO Patentscope / Google Patents API | Any patent-filing company (SMIC, CATL, BeiGene, Hengrui, Horizon Robotics) | Free, queryable by assignee |
| data.gov.hk API | Properties, Utilities, Industrials — general HK government open data | Free, has a documented API spec (`data.gov.hk/en/help/api-spec`) |
| **GDELT Project** | Global news-event sentiment for any company/topic mentioned in world media | **Confirmed 100% free and open** — full event database via Google BigQuery or raw file downloads, updated every 15 minutes, backed by Google Jigsaw. Not a real-time push API, more a queryable dataset, but genuinely no paywall at any tier |
| **akshare (Python library)** | Wraps dozens of HK/mainland sources into one consistent interface | **Already a dependency of this repo**, already used in `src/minerals_signal_data/market_data.py`. **Full audit done** — see [asia-markets-hk-akshare-capabilities.md](asia-markets-hk-akshare-capabilities.md) for the complete function-by-function breakdown (pip-installed and tested live, not just doc-read). Headline results: strong on HK company financials/dividends/analyst estimates and HK macro (CPI/GDP/unemployment/PPI, plus a bonus daily HIBOR-curve function relevant to the real-estate doc); aggregate Southbound Stock-Connect flow has full history since 2014, but per-stock Southbound holding data is capped at a ~2-year rolling window either way it's queried. **Correction to an earlier note here**: `stock_hsgt_north_net_flow_in_em`/`south_net_flow_in_em` were previously cited as confirmed free per-stock functions — direct testing found **they don't exist** in current akshare; the real function is `stock_hsgt_hist_em`. No HK coverage at all for insider/DI disclosure, margin trading, block trades, buybacks, rights issues, sector/concept classification, or per-stock news — all mainland-only in akshare. Two functions are confirmed broken/mislabeled (`stock_hsgt_hold_stock_em`, `stock_ipo_hk_ths`) — see the linked doc before using either. |

## Additional ideas (independent brainstorm, layered on top of the merged list)

These are ideas neither Gemini nor Antigravity's list surfaced, or genuine
refinements (a better/more-authoritative version of a source they did
suggest). Same caveat as above: not yet verified end-to-end.

**1. Financials**
- **HIBOR fixing** (published daily by the Hong Kong Association of Banks,
  free) — direct bank funding-cost input, more precise than HKMA's monthly
  bulletin for tracking NIM pressure in near-real-time.
- **SFC aggregated short-position reports** (weekly, from the regulator
  itself) — a second, independent short-interest source distinct from
  HKEX's own designated-securities short-selling turnover.
- **PBOC wealth-management-product (WMP) registration data** — proxy for
  insurer/bank off-balance-sheet product flows, relevant to the insurance
  rotation story already noted in the sector doc.

**2. Information Technology**
- **Hugging Face model download counts for Chinese open-weight models**
  (Qwen, DeepSeek, etc.) — this repo *already has a pipeline for exactly
  this* (`src/provider_adoption_data/sources/huggingface.py`,
  `huggingface_models_daily`). Extending its provider registry to
  Alibaba/Tencent/Baidu's model orgs would give an AI-momentum signal for
  free, reusing existing code rather than building something new.
- **QuestMobile free monthly MAU/engagement summary PDFs** — covers
  WeChat/Alipay-ecosystem engagement at a level Google/App Store rankings
  don't capture.
- **SEMI free capex/equipment-billings data** — foundry capex context for
  SMIC/Hua Hong, complementing the wafer-pricing idea already listed.

**3. Consumer Discretionary**
- **Singles Day (11/11) and 618 GMV trackers** — concentrated, calendarized
  catalysts; third-party aggregators (e.g. Syntun) publish free previews
  alongside Alibaba/JD's own official press releases.
- **Douyin/Kuaishou livestream-commerce GMV rankings** — livestream
  commerce is now a real chunk of Alibaba/JD/Meituan GMV; free-tier
  third-party trackers exist for top-anchor rankings.

**4. Energy**
- **Regional China power exchange day-ahead clearing prices** (e.g.
  Guangdong Power Exchange Centre) — a direct read on gas/coal dispatch
  economics that the NBS/GACC monthly stats can't give at daily
  granularity.

**5. Industrials**
- **Caixin/NBS Manufacturing PMI** — official, free, monthly, and arguably
  the single cleanest industrials-wide leading indicator; oddly absent
  from both source lists.
- **China National Railway Administration freight-volume stats** — rail
  bulk-freight complement to SCFI's containerized-shipping focus.
- This repo's **`src/ai_hiring_data`** pipeline is built to track hiring
  demand — the same mechanism (job-posting volume/velocity) could in
  principle be pointed at CATL/BYD/COSCO postings as an industrials hiring
  signal, no new infrastructure needed.

**6. Materials**
- **China rare-earth export quota / customs data** — supply-chain signal
  specific to Ganfeng/CMOC that's more targeted than general GACC trade
  logs.

**7. Healthcare**
- **NMPA drug-approval announcements** — actual approval *events*, a step
  more concrete than the CDE trial-registry status changes already listed.
- **Biotech out-licensing deal press releases** — Chinese biotechs
  (BeiGene, Innovent, Hengrui) routinely disclose upfront + milestone
  dollar amounts the day a licensing deal signs; genuinely free, high
  signal, and easy to monitor via press-release feeds.

**8. Properties & Construction**
- **HK Rating and Valuation Department** — official government property
  price/rental/stock statistics; arguably more authoritative than
  Centaline's private CCL index, worth tracking alongside it rather than
  instead of it.
- **Google popular-times data for malls owned by SHKP/Henderson** (IFC,
  APM, etc.) — an unconventional but genuinely free footfall proxy.

**9. Telecommunications**
- **Ookla Speedtest Global Index** — free, monthly, comparative network
  quality across the three carriers; a capex-effectiveness / churn-risk
  proxy neither list mentioned.

**10. Consumer Staples**
- Reuse the HKO/CMA weather-anomaly data already sourced for Utilities —
  summer heat is a direct driver of Nongfu Spring bottled-water sales, no
  new source needed, just a second use of an existing one.
- **China Alcohol Association** production/sales bulletins.

**11. Utilities**
- **China national carbon market (Shanghai Environment and Energy
  Exchange) daily allowance settlement price** — real cost input for
  coal/thermal generators (Huaneng, CR Power) and a potential revenue
  tailwind for cleaner generators (CGN, Longyuan) that can sell surplus
  allowances.
- **China Electricity Council** monthly thermal-plant utilization-hours
  report.

**12. Conglomerates**
- **NY Fed Global Supply Chain Pressure Index** — free, monthly, US-
  published but a genuine leading read on global trade conditions relevant
  to Hutchison Ports and Cathay cargo volumes.

**Cross-sector — the biggest gap in both source lists:**
- **Baidu Index (百度指数)** — roughly "Google Trends for China," one of
  the most commonly used free tools in China-linked alt-data work, and
  notably absent from both Gemini's and Antigravity's lists. Applies
  broadly: BYD model launches, Xiaomi phone launches, property-brand
  searches, staple-brand searches.
- **Xueqiu (雪球)** — China's largest stock-focused social platform; post
  volume/sentiment per ticker is a genuine retail-sentiment proxy
  (China/HK's analogue to WSB or Stocktwits), and specific to this market
  in a way Google Trends isn't.

## Round 3: brainstorm + web-verified (this pass)

Same exercise again, deliberately hunting for angles the first two passes
missed, but this time each item was actually web-searched before being
included — so confidence here is higher than the two sections above.

**1. Financials**
- **HKMA Daily Monetary Statistics API** — verified: HKMA has a real,
  documented API (`apidocs.hkma.gov.hk/documentation/market-data-and-statistics/daily-monetary-statistics/`)
  including a **Daily Figures of Monetary Base** endpoint. This is a much
  cleaner, programmatic alternative to scraping the monthly bulletin —
  worth using over the HKMA bulletin idea from round 1.
- **HKMA Exchange Fund Abridged Balance Sheet** — published monthly
  (`hkma.gov.hk/eng/news-and-media/press-releases/...`), shows HKMA's own
  reserve/liability position — a peg-stability read that indirectly signals
  HKD liquidity conditions banks operate under.
- **HK Insurance Authority — Mainland Visitor new business statistics** —
  verified real: the IA publishes exactly this (e.g. "$46.6bn new business
  premiums from Mainland visitors, 27.6% of individual business" for the
  first three quarters of 2024), a very direct, named-metric proxy for
  AIA/Prudential's HK new-business growth. **Note:** IA switched from
  quarterly to semi-annual reporting starting Q1 2025 — cadence just got
  slower, worth knowing before building a pipeline around it.

**2. Information Technology**
- **Apple's official Marketing Tools RSS/JSON top-charts feed** — verified
  real and genuinely free/unauthenticated:
  `https://rss.applemarketingtools.com/api/v2/{country}/apps/top-paid/{limit}/apps.json`
  (also `top-free`, `top-grossing` variants). This is a much better find
  than the paid-tool-adjacent Sensor Tower/AppMagic free tiers mentioned in
  round 1 — no scraping, no rate-limit uncertainty, official Apple
  infrastructure. Directly usable for Tencent/NetEase game and Xiaomi app
  rank tracking, per-country (use `cn`, `hk`).

**3. Consumer Discretionary**
- **CABIA (China Automotive Battery Innovation Alliance) monthly battery
  installation data** — verified and very concrete: monthly manufacturer
  market share by installed GWh (e.g. "CATL 42.70%, BYD 18.49%, June
  2026"), freely republished in English by trackers like CnEVPost/CnEVData
  every month. This is a cleaner, more granular signal than CPCA vehicle
  sales for both **BYD** (Consumer Discretionary) and **CATL** (Industrials)
  — installed-GWh share moves ahead of revenue recognition.

**4. Energy** — nothing new verified this round beyond round 1/2; the
GACC customs release (round 1) remains the best free option found so far.

**5. Industrials**
- Same CABIA data above applies directly to CATL's Industrials-sector
  market-share tracking.

**6. Materials**
- **SMM social/weekly inventory flashes** (`news.metal.com`) — verified
  real and current: SMM publishes free weekly copper/aluminum "social
  inventory" flash updates with exact tonnage changes (e.g. "SMM copper
  cathode social inventory fell 34,900 mt WoW, -17.46%, July 2026"). This
  is a much more concrete, numbers-in-hand version of the "SMM free tier"
  idea from round 1 — these are short news-style posts, easily scraped, and
  the single most-watched number in Chinese base-metals trading. Directly
  relevant to Zijin/Chalco/Jiangxi Copper.

**7. Healthcare**
- **NHSA NRDL (National Reimbursement Drug List) negotiation results** —
  verified and high-signal: an annual, calendarized, stock-moving event.
  The Dec 2025 round: 311 candidates submitted, 114 added (37% overall
  success rate), ~60% average price cut for newly negotiated drugs, plus a
  brand-new "Commercial Health Insurance Innovative Drug List" launched
  alongside it for the first time — a genuinely new catalyst category to
  watch for Innovent/Hengrui/BeiGene-style names going forward.

**8. Properties & Construction**
- **NBS 70-city new home price index** — verified, official, free, monthly
  (mid-month release, e.g. "-3.3% YoY new home prices, June 2026, 36th
  straight month of declines"). This is *the* single most-watched mainland
  property indicator and was a surprising gap in both round-1 lists —
  direct read on CR Land/COLI/Beike housing-market health, arguably more
  important than the CRIC developer-sales data already listed.
- **HK Lands Department land sale tender results** — verified real, posted
  as press releases per site after each tender
  (`landsd.gov.hk/en/resources/press-releases.html`). Direct read on
  developer land-bank appetite and capital deployment timing for
  SHKP/Henderson/CK Asset — a cleaner "are they actually deploying capital"
  signal than construction-starts bulletins.

**9–12 (Telecom, Staples, Utilities, Conglomerates):** nothing new
verified this round; round 1/2 ideas stand.

## What to do next (not yet done)
1. **Prioritize by effort-to-signal ratio.** The best starting points look
   like: Centa-City Leading Index (HK property, weekly, no scraping
   needed beyond a page fetch), ClinicalTrials.gov API (already has a
   working example script), Macau DICJ GGR (monthly, single clean
   government release), HKO Open Data API (documented JSON API).
2. **Actually verify the rest** — many entries above (Qimai, SMM, CNIA,
   MARA, Manmanbuy) are Chinese-language sites where "free" may still mean
   registration walls or JS-heavy scraping; don't commit to a pipeline
   design before confirming access mechanics for each.
3. Cross-reference against what's already built. `akshare` is **already a
   dependency of this repo** (`pyproject.toml`, `requirements.txt`) and is
   already used in `src/minerals_signal_data/market_data.py` +
   `daily_report.py` — akshare has built-in wrappers for a lot of exactly
   this kind of Chinese market data (SHFE/exchange futures prices and
   warehouse stocks, macro releases, etc.), so several of the Materials/
   Energy sources above may need zero new scraping, just a new akshare
   call. `~/Desktop/Quant/Research/experiments/akshare/` (notebooks
   `01_港股数据.ipynb`, `02_申万行业指数.ipynb`) is worth a read too —
   it's already pulling HK stock data and Chinese industry indices via the
   same library.
4. Repeat this alt-data mapping exercise for South Korea, Japan, Taiwan,
   and China once the HK pass is validated end-to-end.
