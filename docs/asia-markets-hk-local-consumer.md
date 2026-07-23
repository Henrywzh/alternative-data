# Hong Kong Local Consumption (香港本地消费)

Companion to [asia-markets-hk-sectors.md](asia-markets-hk-sectors.md).
Item #5 in the [focus list](asia-markets-hk-focus-list.md). Watchlist
supplied directly (as a CSV, live quotes as of 2026-07-22); market caps
converted from the HKD figures in the source file (÷7.8 to USD) and are
therefore point-in-time, not from the HSCI dataset used elsewhere.

Retail, F&B, and personal-care names — overlaps with the
[consumer-trend-stocks doc](asia-markets-hk-consumer-trend-stocks.md)
(Chow Tai Fook already appears there) but this is a genuinely distinct
list: HK-local retail/dining chains rather than mainland IP-driven brands.

**akshare, already usable for every name in this list** (full audit:
[asia-markets-hk-akshare-capabilities.md](asia-markets-hk-akshare-capabilities.md)):
same fundamentals/dividend functions as the consumer-trend-stocks doc —
`stock_hk_dividend_payout_em`, `stock_financial_hk_analysis_indicator_em`,
`stock_hk_profit_forecast_et` — work directly on Chow Tai Fook (1929), Sa
Sa (0178), Café de Coral (0341), etc. `stock_hk_valuation_baidu` gives a
free daily valuation (P/E, P/B, market cap) time series per ticker, useful
alongside the retail-sales-index macro backdrop already sourced below.

## Watchlist

| Company | Ticker | Market Cap (USD bn) | Sector tag |
|---|---|---|---|
| Chow Tai Fook Jewellery | 1929.HK | ~15.6 | Other retail — also in the consumer-trend-stocks doc |
| Prada | 1913.HK | ~13.6 | Other apparel/accessories — Italian luxury brand's HK secondary listing |
| Samsonite | 1910.HK | ~2.4 | Other apparel/accessories — luggage |
| Luk Fook (六福集团) | 0590.HK | ~1.7 | Other retail — jewelry, direct HK-local competitor to Chow Tai Fook/Laopu Gold |
| Chow Sang Sang (周生生) | 0116.HK | ~1.0 | Other retail — another established HK jewelry chain |
| Café de Coral (大家乐集团) | 0341.HK | ~0.41 | F&B — HK's largest fast-food chain operator |
| Sa Sa International (莎莎国际) | 0178.HK | ~0.35 | Skincare & cosmetics retail — historically driven heavily by mainland tourist footfall |
| Giordano International (佐丹奴国际) | 0709.HK | ~0.29 | Apparel |
| Tai Hing Group (太兴集团) | 6811.HK | ~0.15 | F&B — HK/Hong Kong-style restaurant chain |
| TATA Health (TATA健康) | 1255.HK | ~0.08 | Apparel retail (despite the name) |
| Fairwood (大快活集团) | 0052.HK | ~0.07 | F&B — Café de Coral's smaller HK fast-food peer |

## Alt-data: Google Trends, web-scraped price/store data, HK macro

Three legs here, per the same framing pattern as the rest of this series.

**Google Trends (HK-region search interest):** track brand-name and
category search volume (e.g. "周大福", "六福珠宝", "Sa Sa", "太兴") as a
retail-attention proxy — free via `pytrends`, directly applicable to this
exact list. (Note: unlike the mainland-hype consumer-trend-stocks doc,
Google Trends is the *primary* tool here, not secondary — this is HK-local
search behavior, not mainland-China search behavior, so the "Google is
blocked in China" caveat doesn't apply.) **Frequency correction**: Google
Trends actually gives **daily granularity for any query window up to
~90 days** (the real cutoff is 269 days) — it only silently degrades to
weekly/monthly for longer single pulls. Query in rolling ~90-day windows
rather than one long history pull to get genuinely daily data, not weekly.

**Web-scraped price/store data:**
- **Delivery-app merchant listings**: **foodpanda HK and Meituan's Keeta
  (`keeta-global.com`) are both confirmed workable** (robots.txt checked —
  foodpanda blocks only admin/auth/campaign paths; Keeta only blocks a
  couple of ad-tracking query parameters). Deliveroo has fully exited the
  Hong Kong market entirely, so it's out of the picture.
- **Google popular-times data** for flagship jewelry stores (Chow Tai Fook,
  Luk Fook, Chow Sang Sang, Sa Sa) — **this needs a harder caveat than
  previously given.** Popular-times is not an official Google API at all;
  the community libraries that provide it (`populartimes`, `LivePopularTimes`)
  explicitly describe it as scraping combined with the Places API, and
  their own maintainers call it **"not currently supported by Google and
  legally questionable."** Treat this as a real ToS/legal-risk item, not a
  routine free data source — worth a deliberate decision before using it,
  not an assumed default the way the property-portal scraping was.

**HK monthly/quarterly macro data (verified, official, free):**
| Source | What it gives you |
|---|---|
| **HK Census & Statistics Dept — Retail Sales Index** | Monthly retail sales by value/volume — verified: e.g. +6.5% YoY in November 2025 to HK$33.7bn. This is the single cleanest read on the whole sector's actual trading conditions |
| **HK Immigration Dept / HK Tourism Board — visitor arrival statistics** | Monthly mainland vs. total visitor arrivals — verified: e.g. +17.4% YoY to 4.19m visitors (85% of pre-pandemic level), mainland visitors +18.9% YoY to 3.04m, in one recent month. Directly explains footfall-driven names (Sa Sa, jewelry chains) more than almost any other single number |
| **HKTB monthly research publications** (`partnernet.hktb.com`) | Same visitor-arrival data plus more detail (source market breakdown, spending patterns) |

This sector is arguably the best-instrumented of the whole HK series —
government tourism/retail statistics are frequent, official, and directly
causal for the exact names on this list.

## Round 2 — direct company-site scraping, and confirming the macro data is actually structured (not just PDFs)

**Gold price tracking — a genuinely easy, high-value target, and there's
already an aggregator.** Chow Tai Fook, Luk Fook, and Chow Sang Sang all
publish live retail gold/platinum prices on their own sites (e.g. Chow Tai
Fook's `chowtaifook.com/zh-hk/eshop/realtime-gold-price.html`), and better
still, **`goldpricehk.com` already aggregates all of them daily in one
place** — checked its robots.txt and it's wide open (only blocks `/pg/`).
This is a single, easy scrape target instead of three separate ones, and
it's a genuine margin/input-cost proxy for the jewelry names, distinct
from the HK gold-trade-statistics angle already in the minerals doc (that
one is import/export volume; this is retail selling price).

**Checked robots.txt for each company site directly:**
| Site | Result |
|---|---|
| `chowtaifook.com` | Mostly open — blocks servlet paths, megasale eshop pages, login/cart/captcha (all normal), and "demandware" (Salesforce Commerce Cloud) paths except PDFs. The realtime-gold-price page itself isn't in the disallowed list |
| `lukfook.com` | Very open — only blocks the CMS directory and two specific PDF files |
| `chowsangsang.com` | **403 Forbidden on the robots.txt fetch itself** — a stronger signal than a normal disallow, suggesting server-level bot-blocking (e.g. a WAF/Cloudflare rule), not just a policy preference |
| `sasa.com` | Standard e-commerce (Shopify-style) robots.txt — checkout/admin/search blocked, product pages and collections open |
| `cafedecoral.com` | **Also 403 Forbidden on robots.txt** — same harder-to-scrape signal as Chow Sang Sang |

**Takeaway:** Chow Tai Fook, Luk Fook, and Sa Sa are workable direct-scrape
targets; Chow Sang Sang and Café de Coral look meaningfully more
bot-resistant at the server level, not just policy — worth trying a real
request before assuming either is accessible.

**HK macro data — confirmed genuinely structured, not just monthly PDFs.**
- **Retail Sales Index**: multiple specific data.gov.hk tables — Total
  Retail Sales (620-67001), Value/Value-Index by outlet type (620-67002),
  Volume Index (620-67003), plus category breakdowns for supermarkets
  (620-67011) and department stores (620-67012) — all downloadable in
  **XLSX, CSV, and JSON**, with a real API (`data.gov.hk/en/help/api-spec`,
  max 10,000 results/request) and a published data dictionary.
- **Visitor arrivals**: two C&SD tables — arrivals + length of stay
  (650-80005) and arrivals by nationality/region (650-80001) — both on
  data.gov.hk with CSV access. A separate Immigration Dept dataset (overall
  passenger/visitor/vehicular traffic) is also on data.gov.hk with CSV +
  a data-specification PDF. HKTB's own Tourism Statistics Database
  (`partnernet.hktb.com`) has the same visitor-arrival data with more
  narrative detail (source-market breakdown, spending patterns) but reads
  more like monthly reports than a queryable table — **C&SD's own tables
  are the better machine-readable route**, HKTB is the better source for
  qualitative/narrative context.

This confirms the earlier "best-instrumented sector" claim isn't just
about *existence* of official data — it's genuinely API-accessible, not
locked in PDFs the way some of the real-estate sources were.

## Round 3.5 — F&B subindustry deep dive (subagent research, verified via direct fetches)

Covers Café de Coral (0341.HK), Tai Hing Group (6811.HK), Fairwood
Holdings (0052.HK). Everything below was directly fetched/read (PDFs, CSV,
robots.txt), not just search-summarized — flagged explicitly where a claim
is documented-only.

**Best new find: CenStatD's Quarterly Survey of Restaurant Receipts and
Purchases — verified via direct PDF read.** Free, structured tables on
data.gov.hk (625-68001 through 625-68011, CSV/queryable). Splits the whole
HK restaurant sector into 5 HSIC categories every quarter, and **"Fast
food shops" is its own line** — both a receipts index (value/volume YoY,
an SSS-style signal) and a "purchases" figure (YoY %, a genuine COGS/
input-cost proxy). Q1 2026: fast-food receipts −0.6% value/−1.5% volume
YoY, sector-wide purchases +3.6% YoY — and this **corroborates directly**
against Café de Coral's own disclosed same-store sales (−3% fast food,
−2% congee) for the same period. Published ~1.1 months after quarter-end
(provisional), revised ~1 month later. Stronger and more sector-specific
than the general Retail Sales Index for this subindustry.

**AFCD wholesale fresh-food prices — verified via direct CSV fetch, and
genuinely daily.** Free daily CSV at
`afcd.gov.hk/english/agriculture/agr_fresh/files/Wholesale_Prices.csv`
(also on data.gov.hk). Confirmed contents: live pig (pork proxy), live
chicken (local + mainland), 13 vegetable varieties, assorted fish, eggs.
**Confirmed gap: no rice or cooking oil** — would need a different source.
This is HK-specific wholesale pricing (distinct from the mainland China
commodity data elsewhere in this series) and a genuine daily margin-
pressure leading indicator — raw-materials cost is 27.2% of revenue at
Café de Coral, 24.6% at Fairwood, 26.6% at Tai Hing.

**OpenRice — upgraded from "mentioned in passing" to verified workable.**
Direct robots.txt fetch confirmed: blocks four named AI crawlers (GPTBot,
PerplexityBot, meta-externalagent, Bytespider) specifically, but for the
generic crawler the disallow list only covers functional paths (review
submission, report/flag, admin) — **restaurant profile/rating/review
pages themselves aren't blocked**. Several existing open-source scrapers
already exist on GitHub confirming practical feasibility. Review-count/
rating time series per chain location is a real, buildable customer-
sentiment/foot-traffic proxy. ToS itself wasn't separately read — a legal
pass is still warranted before production use.

**Company disclosure differences — a real, useful distinction between the
three:**
| Company | SSS/SSSG disclosure | Store count granularity | Cost structure (materials/staff/rental, % of revenue) |
|---|---|---|---|
| Café de Coral | **Only one of the three to quantify hard SSS%** — Café de Coral fast food −3%, Super Super Congee −2%, mainland fast food −8% (FY24/25) | By brand: QSR 224 shops (174 Café de Coral + 50 Super Super), Casual Dining 57, Institutional Catering 100 | 27.2% / 34.4% / 11.5% |
| Tai Hing | Revenue by brand with %, not same-store growth | 217 total (188 HK/Macau + 29 mainland, 17 in GBA) | 26.6% / 36.0% / 15.1% (rental incl. ROU amortisation) |
| Fairwood | SSSG named as a forward strategic priority, but **no historical % disclosed this period** — worth checking older filings | 150 Fairwood HK (+3 net), 8 specialty, 23 GBA (+4 net) | 24.6% / 34.8% / **19.1%** (notably highest rental ratio of the three — a real structural difference) |

**Unresolved threads, explicitly flagged rather than assumed:**
- **HKFORT** (HK Federation of Restaurants & Related Trades, 1,400+
  members) — its own site returned a server error this round; its
  reported "Food Establishment Revenue and Purchasing Amount Quarterly
  Survey" has a suspiciously similar name to CenStatD's own survey above —
  **may just be HKFORT relaying government data**, not an independent
  source. Needs a retry once the site is reachable.
- **RVD's Private Retail Excel** (Hong Kong Property Review) — confirmed
  the data exists, but whether it breaks out restaurant/F&B rent
  specifically from general retail wasn't confirmed from the index page
  alone — the actual Excel needs opening.
- **HK Consumer Council's "Online Price Watch"** tool — built for exactly
  the chain-vs-chain price comparison use case, but fetch was
  inconclusive; the Council's annual supermarket survey (300 items, 3
  chains) is aggregate-only in its public press release, chains not named.
- **"Two Dishes One Soup Index"** — a monthly household cost-of-living
  index published by the HK Federation of Trade Unions (labor-advocacy
  body, not government) since 2011, 7 ingredients across all 18 districts.
  Documented, not independently cross-checked — treat as directional
  color given the advocacy provenance, not an official statistic.
- **FEHD restaurant licensing counts** (17,154 licensed as of April 2025;
  net −255 in the trailing 12 months — first annual contraction since
  2018) — a genuine market-level opening/closing statistic, but sourced
  via trade press, not confirmed as a queryable FEHD dataset directly.
- **C&W/CBRE/JLL F&B-specific rent forecasts** — Cushman & Wakefield's
  1H2026 forecast explicitly separates F&B rents (−1% to −3%) from
  overall high-street retail (+2% to +3%), a real F&B-specific data
  point, but delivered via periodic paid-research-firm press releases,
  not a live database.
- **Store-locator scraping** for real-time network size (beyond the
  semi-annual disclosure above) — not established either way for any of
  the three; `cafedecoral.com` remains 403 on robots.txt (harder target),
  `taihing.com` still has no robots.txt file at all (untested).

## Round 3 — a genuinely HK-unique find (Octopus), remaining company sites, and a company-ID correction

**Octopus card tourist-spending press releases — the best new find this
round.** Confirmed real and, better, **recurring**: Octopus (HK's
transit/payment card, 20M+ cards in circulation vs. ~7.5M population, 95%
of the 16–65 population owns one, ~190,000 acceptance points across
transport/retail/dining) publishes a press release around **every major
holiday period** with tourist-specific transaction data:
- Chinese New Year 2025 (Jan 29–Feb 7): HK$100m tourist transaction value,
  +10% YoY, retail spending specifically called out as strong, Tourist
  Mobile Octopus users +80% YoY.
- National Day/Golden Week 2024 (Oct 1–7): also HK$100m tourist
  transaction value, **+30% YoY**, Tourist Mobile Octopus active users
  tripled, spending on that feature up 4x YoY.

This is genuinely HK-unique (no other market has a single payment card
this ubiquitous) and event-driven at exactly the holiday windows that
matter most for retail footfall — a real, free, higher-signal complement
to the monthly visitor-arrival stats, specifically for the tourist-driven
names (Sa Sa, jewelry chains). Cadence is holiday-driven (~4–6 releases/
year around CNY, Easter, Golden Week, Christmas/New Year), not continuous.

**Remaining company-site checks:**
| Site | Result |
|---|---|
| `fairwood.com.hk` | **Confirmed wide open** — empty disallow list, unrestricted, sitemap provided |
| `taihing.com` | **No robots.txt file exists at all** (404, not a block) — technically means unrestricted under the robots-exclusion convention, but the absence could also just mean the site never configured one; worth a real test request rather than assuming either way |
| `giordano.com.hk` | Also no robots.txt found (404) — same caveat as Tai Hing |

**Correction: TATA Health (1255.HK) isn't really a local-consumption
pure-play.** Checked what it actually does — it's a diversified holding
company across **four segments**: footwear trading (majority of revenue,
hence the "Apparel Retail" industry tag), healthcare products trading,
financial services, and online medical services, operating across HK,
Australia, Macau, mainland China, and Singapore (majority revenue still
from HK). Keep it on the watchlist since it's HK-majority-revenue, but
don't expect it to move on the same drivers as Café de Coral or Sa Sa —
it's a trading conglomerate, not a retail/F&B operator.

**HKTB spending-pattern data — confirmed genuinely granular, not just
narrative.** Concrete 2024 figures: overnight visitors HK$5,490 per
capita, same-day visitors HK$1,235 — a real 4.4x gap that matters because
same-day visitors (mostly mainland day-trippers via land crossings) and
overnight visitors have very different spending baskets. By market:
mainland ~70% of visitor volume at HK$4,958/capita (overnight); Americas
HK$7,854; Southeast Asia HK$7,100 (avg. 3.4-night stay). Published via
HKTB's bi-annual "**Tourism Expenditure Associated to Inbound Tourism**"
report (per-capita + category-level spending breakdown), with per-capita
headline figures and MICE arrivals on a **quarterly** cadence — better
frequency than I'd characterized this data as having before.

## Round 4 — cosmetics/apparel/misc subindustry deep dive (subagent research)

Covers Sa Sa (0178.HK), Prada (1913.HK), Samsonite (1910.HK), Giordano
(0709.HK), TATA Health (1255.HK). Verified via direct fetches where noted.

**Sa Sa (0178.HK):**
- **Best new find: HK Consumer Council's "Online Price Watch" — verified
  free, daily-updated, JSON/CSV on data.gov.hk** (`cc-pricewatch-pricewatch`),
  documented API + data dictionary. Covers 7 major retailers including
  **Watsons and Mannings** (Sa Sa's direct competitors) across ~2,200
  products in 10 categories including personal care — the best
  machine-readable HK cosmetics-retail price benchmark found in this
  series, even though it isn't Sa Sa's own storefront.
- **China Customs cosmetics import data** — verified accessible (GACC's
  English monthly-report portal returns 200, no paywall); a free
  structured alternative exists too (**China Data Portal**, `chinadata.live`,
  no-login REST API, monthly GACC trade flows). Caveat: fine-grained
  monthly SKU-level cosmetics data is patchier post-2018/post-PIPL —
  annual/broad-category figures are more reliable.
- **Hainan duty-free** (the real substitution-risk data — Hainan sales
  dipped -9.2% in one recent half despite tourism growth elsewhere,
  genuine evidence of demand diverting from HK): official source is
  Haikou Customs' monthly offshore duty-free sales table, but **confirmed
  NOT practically scrapable despite an open robots.txt** — direct fetch
  returned HTTP 412 (server-level WAF block), the same "policy says open,
  server says no" pattern already seen at Chow Sang Sang and Café de
  Coral. Press re-coverage (Moodie Davitt Report, Yicai Global) is a
  reliable manual-check fallback.
- HK Consumer Council also runs recurring skincare product-testing (e.g.
  a 17-product moisturizer test, ~530 tester trials, efficacy + price per
  product) multiple times a year — genuine price/quality survey data, and
  its magazine went **fully free online starting January 2025**.

**Prada (1913.HK) — a real correction to the framing used earlier.**
**HK is not currently a secondary listing — as of mid-2026 it appears to
be the ONLY listing.** Prada IPO'd on HKEX in 2011 and has never completed
a Milan listing; its CFO said in Nov 2025 a Milan dual-listing is "still
on the table" but not committed. So there's currently no HK-vs-Milan
comparison to make — that becomes relevant if/when Milan actually
launches. Free float is thin (~20%), consistent with a family-controlled
large-cap. **Bain & Company's luxury reports are confirmed free** (direct
fetch, no paywall) — Spring 2026 update: global luxury spend €1,443bn in
2025, mainland China down an estimated 6-8% with signs of H2
stabilization. Contrast: Altagamma (Bain's usual co-publisher) explicitly
gates its own full reports to member companies — **use bain.com directly**
for the free version of the joint studies, not altagamma.it.

**Samsonite (1910.HK):** IATA has two distinct products — the actual
traffic dataset (region/carrier/route-level) is confirmed paywalled
(subscription storefront), but the **monthly "Air Passenger Market
Analysis" narrative PDFs are confirmed free**, no login required — useful
as a directional travel-volume read (hence luggage demand), not a
granular dataset. No good free luggage-specific trade association found;
the free primary-source alternative to paywalled market-research reports
is UN Comtrade/World Bank WITS under HS code 4202 (travel goods/luggage
trade).

**Giordano (0709.HK):** HKTDC Research publishes real apparel/textile
industry content (e.g. "clothing exports -13% YoY in 2025") but free/
paywall status wasn't confirmed this round — documented only. The more
promising machine-readable route is HK's own Trade and Industry Dept /
Census & Statistics Dept trade tables (same data.gov.hk infrastructure
already confirmed reliable elsewhere in this doc) — apparel/textile
HS-code series are very likely accessible the same way, just not pulled
this round.

**TATA Health (1255.HK):** clarified its Clarks distribution rights are
for **HK/Taiwan/Macau, not Australia** (an initial hypothesis linking it
to an Australian footwear distributor was checked and ruled out — no
evidence of a connection). Since it's a Western-brand *trading/
distribution* business, not a manufacturer, the right data angle is **HK's
own footwear import statistics** (via the same TID/C&SD trade
infrastructure), not the China footwear-export/manufacturing data that's
more relevant to Anta/Li Ning (covered in the consumer-trend-stocks doc).

**Cross-cutting note:** Statista surfaces constantly across all five
companies' searches but is a paywalled aggregator — useful for spotting
what numbers exist, not as a source to build against.

## Round 5 — jewelry subindustry deep dive (subagent research, verified via direct fetches)

Covers Chow Tai Fook (1929.HK), Luk Fook (0590.HK), Chow Sang Sang
(0116.HK) — deeper than the gold-price-aggregator angle already found.

**Best find: all three file a quarterly "Unaudited Key Operational Data"
HKEXnews announcement — the same Pop-Mart-style disclosure pattern flagged
as unchecked earlier, now confirmed for all three, not just CTF.**
Directly fetched CTF's actual PDF (stock code 1929); Luk Fook and Chow
Sang Sang confirmed via multiple independent Chinese-press citations
explicitly naming HKEXnews as the source (high confidence, not
primary-source-verified for those two). One filing gives, every ~3-4
weeks after quarter-end:
- Retail Sales Value growth, Group + by region (Mainland/HK&Macau/other)
- **Same-Store-Sales growth by region and product category** (gem-set/
  platinum/K-gold vs. gold-weight) — for CTF, also **Same-Store Average
  Selling Price** by category/region, genuinely granular price-mix data
  not available anywhere else free
- A full store-network table: opening/additions/reductions/net/closing,
  by region and even by brand — e.g. Chow Sang Sang's most recent filing
  (17 July 2026 press coverage) shows a real net contraction: 776 stores
  at 30 June 2026 vs. 840 at 31 Dec 2025

This single free filing type gives both the SSS angle and the store-count
angle in one recurring document — better than either separately, and
zero scraping risk since it's an official HKEXnews announcement.

**Gold benchmark pricing — solved via akshare, no scraping needed.**
`ak.spot_golden_benchmark_sge()` (+ `spot_silver_benchmark_sge`,
`spot_hist_sge`, `spot_quotations_sge`) pulls the **Shanghai Gold
Exchange** benchmark price directly — verified as a working, documented
akshare interface, and SGE is the actual benchmark China's domestic gold
price references (more relevant than LBMA for these three). **Correction:
LBMA gold price is not actually free** — checked directly, LBMA's own
tables moved behind a login-required "MyLBMA Portal," and a licence from
ICE Benchmark Administration is required to use or redistribute the data;
World Gold Council pulled its free historical LBMA mirror in March 2025 at
IBA's request. Third-party "free" APIs sitting on top of it are unofficial
redistributors, not a genuine free source.

**China Gold Association — quarterly gold consumption split by end-use,
genuinely free.** `cngold.org.cn` publishes gold jewelry vs. bars-&-coins
vs. industrial consumption every quarter (Q1 2026: jewelry 84.6t, **-37.1%
YoY**, vs. bars/coins 202.1t, +46.4% YoY) — more specific than the HK
gold-trade-volume proxy already in the minerals doc, since this is the
actual jewelry-vs-investment demand split that matters for these three
names specifically.

**HKTDC jewelry-specific channel** (distinct from HKTDC's generic
twice-yearly trade-fair stats already noted): an annual "Global Jewellery
Sourcing Barometer" buyer survey (1,507 respondents in the 2026 edition,
confirmed free) plus a roughly-monthly "Market News" feed specific to the
jewelry trade (export data, regulatory changes, buyer sentiment) — both
confirmed freely accessible.

**Marriage registration statistics — real but weaker as a timing signal
than hoped.** HK's own dataset (data.gov.hk) is free but **annual**, not
monthly/quarterly. China's Ministry of Civil Affairs publishes a genuinely
quarterly, free national count (Q1 2026: 1.697m registrations) — but
registration timing may lag/lead actual gift-purchase moments by weeks to
months, and the companies' own quarterly filings above already give more
direct SSS timing. Rank below the operational-data filings, not above.

**Company-specific notes:** Chow Tai Fook has the richest disclosure
(ASP data the other two don't appear to have) and the most press-visible
social footprint (Tmall members, WeCom contacts, Weibo/Douyin/Xiaohongshu
followers — all press-reported, no live API). Luk Fook has the widest
disclosed international footprint (3,180+ points, 11 countries) and a
real M&A discontinuity to flag: it acquired Kam Chi Chuen (金至尊) Group
as a subsidiary in January 2024 — any time series crossing that date needs
a break flag, same pattern as the IPO lock-up tracking in the
consumer-trend-stocks doc. Chow Sang Sang's own site remains the most
bot-resistant of the three (403 on robots.txt), making it the most
dependent on the quarterly HKEXnews filing as its primary data channel.

**Not pursued further:** HK Jewellery Manufacturers'/Jewellery & Jade
Manufacturers Associations are real trade bodies but publish only
qualitative newsletters, not structured data — deprioritized versus
HKTDC's jewelry channel above.

## Round 6 — real test fetches, not just robots.txt (closing the "not sure yet" gaps)

Robots.txt tells you what's *allowed*; it doesn't tell you what a page
actually *returns*. This round did real fetches against the previously
"confirmed via robots.txt only" targets.

**goldpricehk.com — confirmed genuinely easy, best-verified scrape target
in the whole sector.** Real fetch returned plain static HTML, no
JavaScript rendering needed: each jeweler is a consistent pattern (name,
price/tael, a trend-chart link). Current read (2026-07-23): 周生生
$46,710, 周大福 $46,788, 六福 $46,708, **謝瑞麟 (Tse Sui Luen) $46,560**,
**金至尊 (Kam Chi Chuen/King's Gold) $46,708** — two more jewelers than
previously noted, and 金至尊 is tracked as its own line despite being
Luk Fook's 2024 acquisition (confirms that M&A discontinuity is visible
in this data source too, not just the company's own filings).

**Fairwood homepage — confirmed the actual data lives on sub-pages, not
the homepage.** The homepage itself is promotional banners + navigation
only; store/menu data is behind `/stores` and `/food_menus` — those are
the real scrape targets, not yet fetched themselves.

**Meituan's Keeta — confirmed a genuine JS-rendered SPA shell, no data in
static HTML.** Real fetch returned only a page title, nothing else — this
means Keeta needs a headless browser (Playwright/Puppeteer) or reverse-
engineered API calls to actually extract merchant data, **despite its
robots.txt being wide open**. This is the same "policy allows it, but the
technical reality is harder" lesson as the WAF-blocked sites, just a
different failure mode (client-side rendering vs. server-level block) —
worth remembering that an open robots.txt only clears the policy gate,
not the technical one.

**Luk Fook — a real primary-source HKEXnews PDF fetched and read
directly** (confirms the Read tool can extract Chinese-language financial
tables from HKEXnews PDFs, including ones that render as scanned-style
images rather than text-layer PDFs — a genuine capability check passed).
What was actually pulled was Luk Fook's **FY2026 full annual results**
(year ended 31 March 2026), not the quarterly operational-data filing —
still useful and now directly verified: revenue HK$17.2bn (+29.0% YoY),
gross margin 36.7% (+3.6pp), operating margin 15.4% (+4.8pp), net profit
HK$2.02bn (+88.7%), EPS HK$3.48, full-year dividend HK$1.57/share (45%
payout) — company narrative attributes the year to strong gold demand
plus a higher mix of fixed-price (vs. gold-weight) jewelry sales driving
margin. **Still open**: the specific quarterly "unaudited key operational
data" filing (the one with SSS/ASP/store-count detail) wasn't isolated
from Luk Fook's or Chow Sang Sang's HKEXnews filing history this round —
my constructed HKEXnews title-search query returned zero results (likely
a parameter-format issue, not proof the filing doesn't exist) — worth a
follow-up using HKEXnews's own search UI directly rather than a
hand-built query string.

**Net effect of this round:** goldpricehk.com moves from "robots.txt open"
to "fully verified, ready to scrape today." Keeta moves from "robots.txt
open" to "technically harder than it looked — needs a browser, not a
simple request." Fairwood's real target is now the specific sub-pages,
not the homepage. Luk Fook's annual results are confirmed readable, but
the specific quarterly filing that has the SSS/store-count granularity
still needs to be located and fetched directly before treating it as
verified rather than press-cited.
