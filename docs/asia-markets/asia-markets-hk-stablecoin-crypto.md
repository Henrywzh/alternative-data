# Hong Kong Stablecoin & Crypto Stocks

Built from two watchlists supplied directly (the larger one, ~28 names,
described as stablecoin-related; the smaller one, ~19 names, crypto-related
— they overlap substantially). Every non-obvious name below was
individually web-searched and confirmed before being written up — this
sector was flagged as needing "extra care" and it earns it: several of
these are unrelated legacy businesses that pivoted into a crypto/stablecoin
*narrative* within the last 6–12 months, which is a very different quality
of company than an actual licensed exchange.

**akshare note** (full audit: [asia-markets-hk-akshare-capabilities.md](asia-markets-hk-akshare-capabilities.md)):
`stock_hk_ggt_components_em()` gives today's Southbound-Connect-eligible
HK universe — worth checking which of this sector's thin-float
concept-stock names are actually Connect-eligible, since that affects
mainland retail-investor access to them. Standard fundamentals functions
(`stock_financial_hk_analysis_indicator_em`, etc.) work on these tickers
too, though for the Tier 3/4 "concept stock" names the fundamentals will
say little — the theme-momentum framing further down is more informative
than the balance sheet for this particular basket.

## Regulatory backdrop
Hong Kong's **Stablecoins Ordinance** took effect (licensing regime for
fiat-referenced stablecoin issuers) in 2025, and HKMA ran an issuer sandbox
before that. This is *the* catalyst driving almost every name below —
whether a company is (a) actually building licensed infrastructure, (b) a
bank/big-tech name positioning for a license, or (c) an unrelated small-cap
that bolted on a "stablecoin cooperation MOU" press release to catch the
theme. Telling these three apart matters more than anything else in this
sector.

### HKMA stablecoin issuer register — the cleanest ground-truth source in the sector
`https://www.hkma.gov.hk/eng/regulatory-resources/registers/register-of-licensed-stablecoin-issuers/`
— a real, free, static HTML table, parseable directly with `pandas.read_html()`.
No API-discovery grind needed.

**Confirmed live 2026-07-26: exactly 2 licensed issuers exist**, full stop:
| Issuer | Licence | Effective date |
|---|---|---|
| Anchorpoint Financial Limited | FRS01 | 10/04/2026 |
| HSBC (The Hongkong and Shanghai Banking Corporation Limited) | FRS02 | 10/04/2026 |

This is the single cleanest "who's actually licensed" read in the whole sector
— a 2-name register, not a broad list. Worth checking periodically for exactly
that reason: a 2-name register would immediately reveal the *next* licensee
before it hits headlines.

**New company link surfaced by this register, not previously on this doc's
radar**: Anchorpoint Financial is a joint venture of **Standard Chartered
(02888.HK, already Tier 2 below) + Animoca Brands (private, not HK-listed) +
HKT (06823.HK — new, added to Tier 2 below)**, targeting a regulated
HKD-pegged stablecoin branded **"HKDAP" (HKD At Par)**, phased rollout from
Q2 2026 — confirmed via SCMP, CoinDesk, The Block, and Standard Chartered's
own press release. This upgrades Standard Chartered from "linked to the
sandbox" (soft) to "confirmed licensed via its Anchorpoint JV" (hard) — see
Tier 2 table.

**Naming collision — easy to get wrong, flag clearly**: **"Anchorpoint"**
(this HKMA licensee, SCB/Animoca/HKT JV, targeting **HKD**-pegged HKDAP) and
**"AnchorX"** (Tier 3 below, via Jinyong Investment/01328.HK, targeting
**AxCNH** pegged to offshore RMB) are two completely different
companies/projects with confusingly similar names. Do not conflate them.

## Tier 1 — Licensed virtual-asset infrastructure (the real thing)
**Nuance confirmed via the SFC's VATP register** (endpoint in the "Alt-data
ideas" table near the bottom of this doc): "licensed exchange operator" and
"licensed to deal in virtual assets" are materially different regulatory
statuses, and this doc previously didn't distinguish them.

**Licensed exchange operators** (appear directly on the SFC's VATP-operator list):
| Company | Ticker | What they actually do |
|---|---|---|
| OSL Group | 00863.HK | Licensed HK virtual asset exchange/custodian — SFC VATP-licensed 15/12/2020, one of the two original SFC-licensed VASPs |
| HashKey Holdings | 03887.HK | The other major licensed HK virtual asset exchange operator — SFC VATP-licensed 09/11/2022 |

**Licensed to deal in virtual assets** (a brokerage-side licence upgrade — NOT
on the SFC's VATP-operator list, confirmed 2026-07-26; a different, lesser
regulatory status than an actual exchange licence):
| Company | Ticker | What they actually do |
|---|---|---|
| Guotai Junan International | 01788.HK | First mainland-backed brokerage to obtain a HK virtual asset dealing upgrade — confirmed via press ("首家中资券商杀入币圈") |
| Victory Securities | 08540.HK | HK brokerage licensed for virtual asset dealing |

**Infrastructure / data / asset-management (neither of the above)**:
| Company | Ticker | What they actually do |
|---|---|---|
| OKG Technology Holdings (OKLink) | 01499.HK | Blockchain **data** business (multi-chain explorer, on-chain analytics, AML/compliance tooling) — linked to OKX; this is infrastructure/data, not an exchange itself. Note: OKX itself formally withdrew its own HK VATP application in May 2024 (confirmed via the SFC's withdrawn-applicants list) — OKX has no path to a licensed HK exchange right now, which matters when weighing how much this "linked to OKX" positioning is worth |
| Sinohope / 新火集团 | 01611.HK | Blockchain tech solutions + a licensed (SFO Type 1/4/9) virtual-asset asset-management arm managing 12 crypto funds; hired ex-Huobi executives in 2025, launched "Alpha BTC" HK's first Bitcoin-denominated compliant asset-management product in 2026 |

## Tier 2 — Big-name stablecoin-adjacent (banks & big tech positioning for licenses)
| Company | Ticker | Angle |
|---|---|---|
| HSBC Holdings | 00005.HK | **Confirmed licensed** — HKMA stablecoin issuer register, licence FRS02, effective 10/04/2026. No longer just "sandbox-linked"; this is the hard confirmation |
| BOC Hong Kong | 02388.HK | Among banks linked to HKMA's stablecoin issuer sandbox |
| Standard Chartered | 02888.HK | **Upgraded 2026-07-26**: confirmed licensed via its **Anchorpoint Financial** JV (HKMA licence FRS01, effective 10/04/2026) — SCB + Animoca Brands + HKT, targeting HKD-pegged "HKDAP," phased rollout from Q2 2026. Previously only "sandbox-linked"; now hard-confirmed. See HKMA register callout above — do not confuse "Anchorpoint" with Tier 3's "AnchorX" |
| HKT | 06823.HK | **New addition.** Confirmed via HKMA register cross-check (SCMP/CoinDesk/The Block/SCB press release): co-JV partner in Anchorpoint Financial (licence FRS01) alongside Standard Chartered and Animoca Brands, targeting HKD-pegged "HKDAP" |
| Alibaba | 09988.HK | Ant International reportedly pursuing stablecoin initiatives |
| JD.com | 09618.HK | JD's own stablecoin push was the headline story that kicked off this whole theme in mid-2025 (confirmed via search: "稳定币赛道爆火！京东之后 蚂蚁国际也将入局" — "after JD, Ant International also entering the stablecoin race") |

## Tier 3 — "Concept stock" pivots (extra care — these are the volatile ones)
These are pre-existing companies, often in unrelated legacy businesses,
that announced a stablecoin/blockchain MOU or pivot within the last year.
Several had single-day moves of 40–650%. Treat press-release cooperation
announcements here as far weaker signal than an actual license or product
launch.

| Company | Ticker | Legacy business | The pivot |
|---|---|---|---|
| Jinyong Investment | 01328.HK | HK brokerage (Type 1/4/9 licensed) | July 2025: strategic framework with **AnchorX** to launch **AxCNH**, a stablecoin pegged 1:1 to offshore RMB — stock spiked >650% intraday on the news at one point |
| China 33 Group (China 33 Media) | 08087.HK | Media | Announced plans to apply for a HK stablecoin license; surged ~40% on the announcement |
| Jingwei Tiandi | 02477.HK | Wireless telecom network optimization / ICT integration | July 2025: launched **Fopay**, a self-built stablecoin payment app (custody + prepaid card via licensed partners) |
| Guofu Quantum | 00290.HK | Securities brokerage, margin financing, money lending, art investment (an unusually scattered conglomerate) | Investing in RWA (real-world-asset tokenization) platforms, blockchain asset-tokenization ambitions |
| Starcoin Group (星太链集团) | 00399.HK | **Beauty product trading + oral insulin R&D** (genuinely unrelated legacy business) | Oct 2025: MOU with Starcoin Foundation for a token airdrop to shareholders (1 Starcoin per 10 shares); Feb 2026: gold RWA-tokenization framework agreement — one of the more extreme "unrelated business bolts on crypto MOU" cases in this list, stock moved +250% over 3 days on the news |
| Xiongan Technology | 01647.HK | Diversified tech/media (e-commerce, live-streaming, AIoT) | Partnership with Lion Group to co-operate a crypto asset trading platform; Lion Group separately raising an $800m fund for BTC/ETH/blockchain-equity investments |
| China Properties Investment | 00736.HK | Property investment | Sept 2025: discounted share placement, proceeds earmarked to buy **BNB** and other digital assets; also RWA-tokenization tie-up with Kimber Labs and a "TokenMarket" AI-model marketplace platform |

## Tier 4 — Bitcoin/ETH/SOL treasury plays (MicroStrategy-style, not infrastructure)
These hold crypto on the balance sheet as a treasury/speculative asset —
closer to a leveraged bet on token prices than a crypto *business*.
| Company | Ticker | Holdings disclosed |
|---|---|---|
| Boyaa Interactive | 00434.HK | Gaming company; one of the earliest HK-listed BTC/ETH treasury plays |
| Lion Rock / 蓝港互动 (game co.) | 08267.HK | Disclosed (Aug/Sep 2025) 116 BTC directly (212 incl. affiliates), 663 ETH (2,040 incl. affiliates), 7,692 SOL (18,205 incl. affiliates); set up an "LK Crypto" division and a $100m fund; running ETH/SOL staking |
| MemeStrategy (迷策略) | 02440.HK | Bought Solana on the open market (~HK$2.9m in June 2025); partnered with Helio (a MoonPay company) on a meme/token trading system called "Moonit" — the name is a deliberate MicroStrategy pun |

## Weak/unclear fits — flag before trusting the source list
| Company | Ticker | Note |
|---|---|---|
| 域能控股 (jewelry) | 00442.HK | Web search found **no crypto/stablecoin connection** — it's a long-established HK jewelry design/manufacturing/export ODM. Possibly included in the source watchlist by mistake, or there's a very recent pivot not yet indexed — worth double-checking the original source before treating this as a crypto name |
| Synagistics (狮腾控股) | 02562.HK | SE Asia data/e-commerce platform (Alibaba Singapore is a shareholder); added "blockchain infrastructure" as one ingredient of its AI platform "Geene" in H1 2025 — a genuine but minor blockchain mention, not a core crypto business |

**Not independently verified this pass** (present in the source lists,
plausible given the overall brokerage/fintech pattern, but not individually
confirmed): 06099 (brokerage), 02598 联连数字/Lianlian DigiTech (cross-border
payments), 09959 联易融/Linklogis (supply-chain fintech), 09923 移卡/Yeahka
(payments), 01709 德林控股 (brokerage), 00165 中国光大控股 (investment
holding), 00376 云锋金融/Yunfeng Financial (Jack Ma-linked financial
holding), 01911 华兴资本控股/China Renaissance (investment bank), 06060
众安在线/ZhongAn Online (insurtech/virtual bank), 00856 伟仕佳杰/VSTECS (IT
distributor — plausible crypto-mining-hardware distribution link, not
confirmed), 06682 范式智能 (unclear business, not confirmed).

## Theme-momentum framing (why this matters more than any single company)

HK theme stocks trade on **momentum beta to the theme, not fundamentals** —
when "crypto/stablecoin" is hot, most of Tiers 1–4 above move together
(and Tier 3/4 often move *harder* than Tier 1, since they're lower-float,
more speculative, and purely narrative-driven). That means the highest-value
alt data here isn't anything company-specific — it's tracking the theme's
catalyst and popularity directly, then treating individual tickers as
levered bets on that theme. Two angles, per your framing:

**A. Policy/regulatory catalyst tracking (HK government + financial authorities)**
This sector's price action is driven almost entirely by regulatory news
flow, so the "alt data" is really a news/filing monitor:
| Source | What to watch |
|---|---|
| **HKMA** press releases/circulars | Stablecoin issuer licensing decisions, sandbox updates, any Ordinance amendments |
| **SFC** announcements | VASP licensing, virtual asset ETF approvals/rejections, investor warnings (warnings are often bearish catalysts for Tier 3 names specifically) |
| **HKEX** — Virtual Asset product listings | New BTC/ETH ETF or index launches signal official-channel legitimization |
| **LegCo** (Legislative Council) bills/records | Any stablecoin/virtual-asset legislation moving through committee |
| **HK Government policy addresses / Financial Secretary speeches** | HK has repeatedly used these to signal "we want to be a Web3 hub" — a recurring soft catalyst |

**B. Popularity/momentum tracking (easy — direct market data)**
| Source | What it gives you | Access |
|---|---|---|
| **Crypto spot price & volume** (CoinGecko/CoinMarketCap free APIs, Binance public market-data API) | BTC/ETH/SOL price and volume — this is probably the single highest-beta driver of the whole HK crypto-concept-stock basket, more than any company fundamental | Free, well-documented, no auth needed for basic endpoints. **Re-verified live 2026-07-26**: `api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd&include_24hr_vol=true` → 200 OK, real BTC/ETH/SOL price + 24h volume, no auth — works exactly as previously described |
| **Coinbase public ticker + Binance public ticker ("Coinbase Premium")** | `api.exchange.coinbase.com/products/BTC-USD/ticker` (Coinbase) and `api.binance.com/api/v3/ticker/price?symbol=BTCUSDT` (Binance), both confirmed 200 OK, no auth. The spread between the two legs is the well-known **"Coinbase Premium"** — a real-time proxy for US institutional buying pressure vs. global flow. Complementary to the COIN/CRCL leading-indicator angle below (magnitude gauge vs. that section's directional/timing signal) | Free, real-time, no auth on either leg |
| **Crypto Fear & Greed Index** (alternative.me, free API) | A simple, single-number sentiment gauge already widely used as a crypto-cycle proxy | Free. **Re-verified live 2026-07-26**: `api.alternative.me/fng/?limit=3` → 200 OK, real daily values (e.g. 26 = "Fear"), no auth — accurate as previously described |
| **US crypto regulatory/legislative actions** | Confirmed: the **GENIUS Act** (federal stablecoin framework) was signed into law July 18, 2025 — the single biggest US stablecoin catalyst to date, with rulemaking still unfolding (OCC issued a Notice of Proposed Rulemaking in 2026) — this kind of US legislative/rulemaking news reliably ripples into HK crypto-stock sentiment same-day. Also worth tracking: SEC crypto ETF approvals, CFTC/SEC market-structure bills (e.g. CLARITY Act-style efforts) | Free — Congress.gov, Federal Register, OCC/Treasury press releases |
| **Polymarket** (Gamma API) | Forward-looking probability markets on exactly the global regulatory catalysts above — confirmed live: "U.S. enacts stablecoin bill in 2025?", "Will Meta/X launch a USD stablecoin in 2026?", "Will USDC flip USDT in market cap?", live BTC/ETH ETF-approval markets. **Checked specifically for HK relevance and found none** — `q="Hong Kong crypto"` returns only an unrelated boxing event and a Trump/Xi meeting market. Use as a supplement for the *global/US* catalyst angle only, not a source of HK-specific signal | Free, no auth: `gamma-api.polymarket.com/public-search?q=<term>`. Note: the `tag=` filter didn't reliably scope results in testing — use `public-search` with a keyword instead |
| **Google/Baidu Trends** for "stablecoin," "稳定币," "crypto," "比特币" | Retail attention proxy, same tool already flagged generally in the companion alt-data doc, directly applicable here. **Gap confirmed 2026-07-26**: this repo already runs a full scheduled Google Trends pipeline (`src/google_trends_data/`, watchlist-driven — see `src/google_trends_data/watchlist.json`, 17 entries, ticker + geo-scoped keyword schema, e.g. the existing Pop Mart entry) but has **zero crypto/stablecoin keywords configured today**. Near-zero-cost win: no new pipeline engineering needed, just add HK-geo-scoped entries following the existing pattern | Free |

### COIN/CRCL as a leading indicator for HK crypto-concept-stock catalysts — n=2, macro-catalyst-only
Hypothesis tested: does Coinbase (COIN)/Circle (CRCL) stock price+volume give
advance warning before a HK-listed crypto-concept stock's next catalyst spike?
Tested against 2 real historical events using free Yahoo Finance chart-API
historical data — `query1.finance.yahoo.com/v8/finance/chart/<ticker>?period1=...&period2=...&interval=1d`,
confirmed working for both `.HK`-suffixed and US tickers, no auth needed.

**Case 1 — Guotai Junan International (01788.HK), CONFIRMS the pattern:**
Spiked 2025-06-25 ($1.24 → $3.70, +198% close-to-close, ~700% intraday). Seven
days earlier, the US Senate passed the GENIUS Act (2025-06-17, 68-30 vote);
COIN +16% and CRCL +33% the next day (2025-06-18) on ~4-5x normal volume
(COIN volume 37.4M vs. a typical 7-12M/day), and COIN kept climbing through
06-24 (+17% over the week). A genuine ~1-week lead from a macro/regulatory
catalyst that hit pure-play US crypto stocks first, then diffused into the
HK concept-stock basket.

**Case 2 — Jinyong Investment (01328.HK), does NOT show the same lead:**
Spiked 2025-07-08 ($1.99 → $12.60, +533% close-to-close, its AnchorX/AxCNH
partnership announcement). COIN/CRCL were flat/choppy with no elevated
volume in the preceding week (07-01 to 07-08) — their own next rally leg
didn't start until 07-09, i.e. *after* Jinyong's spike, not before.

**Refined conclusion**: COIN/CRCL price+volume (watch for a double-digit %
single-day move on multiple-times-normal volume, matching the June 18
pattern) is a real, verified leading indicator specifically for
**macro/regulatory-catalyst-driven, sector-wide** moves across the whole HK
crypto-concept basket — a US legislative/regulatory event hits COIN/CRCL
directly and first, before the theme diffuses to HK names. It is explicitly
**not** a predictor of **idiosyncratic single-company deal announcements**
(bilateral partnerships/MOUs) — those run on an independent timeline
unrelated to COIN/CRCL's price action, and Case 2 proves it.

**Practical implication**: this can't predict *which* HK shell company bolts
on the next crypto MOU, but it can tell you *when the sector-wide theme is
heating up*, roughly a week ahead, via a free, real-time, no-auth signal.
Pair with the Coinbase/Binance public tickers above (the "Coinbase Premium"
spread) as a complementary real-time sentiment-magnitude gauge.

**Caveat — this is n=2, not a settled rule.** Two events tested, a
well-evidenced pattern worth building against, but not yet proven
statistically. Good next step before treating the macro-vs-idiosyncratic
split as settled: check 1-2 more of this doc's own Tier 3 catalyst dates
(China 33 Group, Starcoin Group) against COIN/CRCL.

### HKEX-listed spot Bitcoin/Ether ETFs as a HK-specific institutional-adoption gauge

Distinct from COIN/CRCL (US sentiment) and DefiLlama (global stablecoin
share): this is the one signal in this doc that measures actual
**Hong Kong-domiciled capital**, not global/US flow.

The 6 HKEX-listed crypto ETFs (Asia's first spot BTC/ETH ETFs, launched
2024-04-30):
| ETF | Ticker | HKEX fundId |
|---|---|---|
| Bosera HashKey Bitcoin ETF | 3008.HK | `BUU104` |
| Bosera HashKey Ether ETF | 3009.HK | `BUU105` |
| ChinaAMC Bitcoin ETF | 3042.HK | `BUU163` |
| ChinaAMC Ether ETF | 3046.HK | `BUU164` |
| Harvest Bitcoin Spot ETF | 3439.HK | `BUT244` |
| Harvest Ether Spot ETF | 3179.HK | not yet found (a `BUT245` guess 404'd; trivial to look up via the fund's own `ifp.hkex.com.hk` page) |

**The real, working, free API** (found via a real browser's network log — the
fund page itself is a React SPA, `curl` alone only gets a blank shell):
`https://ifp.hkex.com.hk/ifp/api/v1/fund/getFundSizeList?fundId=<ID>&page=1&size=<N>&startDate=&endDate=&lang=en`
on HKEX's own "Integrated Fund Platform." Works with a plain `curl`, **no
auth, no special headers needed** (unlike SSE's API above, which needs a
Referer header).

**Verified live 2026-07-27**, real monthly AUM history (USD) back to each
ETF's Sept 2024 inception:
| ETF | May 2026 AUM | Range since inception |
|---|---|---|
| Bosera Bitcoin | $80.06M | $77.81M–$196.33M |
| ChinaAMC Bitcoin | $186.76M | $142.03M–$306.71M |
| Harvest Bitcoin | $15.51M | $14.23M–$37.66M |
| Bosera Ether | $18.94M | — |
| ChinaAMC Ether | $36.91M | — |

**Caveats**: this is **monthly** AUM, not daily — fine for a scheduled
monthly/weekly pipeline, not a real-time flow signal. It's point-in-time
AUM, not creation/redemption unit flow directly — net flows would need to
be approximated by differencing consecutive months' AUM net of the
underlying crypto's price move over that period. No working "list all
virtual-asset funds" discovery endpoint was found (`keyword=` and a guessed
`fundTypeIds=` filter both returned unfiltered generic fund lists) —
fundIds were found via web search instead, and are static/one-time-lookup
once known.

**C. Stablecoin-specific: market share & major issuers**
| Source | What it gives you | Access |
|---|---|---|
| **DefiLlama stablecoins API** (`stablecoins.llama.fi/stablecoins?includePrices=true`) | **Verified live 2026-07-26**, 200 OK: 413 tracked stablecoins with real circulating-supply figures — USDT $184.3B, USDC $73.5B, USDS (Sky Dollar) $6.65B, DAI $4.85B, USD1 (World Liberty Financial) $4.14B, USDe (Ethena) $3.97B — broadly consistent with the doc's earlier dashboard snapshot below, small drift expected. This is the actual automatable API behind the dashboard, not just a page to check manually. **Confirmed**: neither AxCNH nor any HKD-pegged stablecoin (including Anchorpoint's HKDAP) is tracked yet — reinforces the "DefiLlama listing would itself be a 'did it actually launch' signal" framing below. One near-comparable found in passing: `CNHT` ("Tether CNH," ~$3.0M circulating) — a different, much smaller, pre-existing CNH-pegged coin, not to be confused with AnchorX's AxCNH. Rate limit: free tier is 500 req/min, no auth — far more than a scheduled pipeline needs; the $300/mo Pro tier only unlocks unrelated protocol-level data (TVL, token unlocks, active users), nothing stablecoin-specific is gated | Free, no auth, live |
| **DefiLlama stablecoins dashboard** (`defillama.com/stablecoins`) | Human-readable view of the same data above. As of mid-2026: total stablecoin market ~$314–321B; **USDT (Tether) ~59% share (~$187B)**, **USDC (Circle) ~24% share (~$75B)** — combined ~83% of the entire market. This single dashboard is the cleanest "who's actually winning" read, and directly comparable against whatever HK/China-linked stablecoins (AxCNH, any future JD/Ant HKD-stablecoin) manage to capture | Free, no auth, live |
| **Circle (CRCL)** — Nasdaq/NYSE-listed USDC issuer | Circle IPO'd June 5, 2025 (NYSE: CRCL, priced $31, +168% on debut) — now a **public company with quarterly filings**, making it the cleanest fundamental proxy for "how is the stablecoin business actually doing" anywhere in the world, HK-listed names included. **Checked for a direct public API 2026-07-26 and found none** — Circle publishes weekly reserve reports and monthly Big-4 attestations as PDFs, not a documented endpoint (a guessed `api.circle.com/v1/stablecoins/usdc/reserves` 404'd; Circle's own blog post about "stabilizing USDC supply via Circle APIs" doesn't publish a URL and reads as business/partner-facing, not open). Not worth chasing further — DefiLlama already gives the same USDC circulating-supply data for free. For Circle-*specific* fundamentals (revenue, reserve yield), both Circle and Coinbase (Nasdaq: COIN) are SEC-registered and file 10-Q/10-K, free via EDGAR — this repo already has a scheduled daily SEC EDGAR full-text-search pipeline (`src/sec_edgar_data`, `.github/workflows/sec-edgar-daily.yml`) that could pick up both companies' filings for near-zero added engineering cost if added to its search config | Free — SEC filings via EDGAR, quarterly earnings calls |
| **Tether** transparency/attestation reports | Tether isn't public but publishes quarterly reserve attestations | Free, published by Tether |
| **HK/China-specific issuers to track directly**: AnchorX (AxCNH), Anchorpoint (HKDAP), any JD.com/Ant International stablecoin once launched | Whether these ever show up on DefiLlama's tracked-stablecoin list would itself be a meaningful "did it actually launch" signal — confirmed none of them are listed yet as of 2026-07-26 | Free to monitor once/if listed |

## Alt-data ideas specific to this sector
| Source | What it gives you | Access |
|---|---|---|
| **HKMA stablecoin issuer license register** | Who has actually applied/been approved — the single best way to separate Tier 1/2 from Tier 3 hype. See the dedicated subsection above the Tier tables — confirmed live 2026-07-26, exactly 2 licensees (Anchorpoint, HSBC), real `pandas.read_html()`-parseable table | Free, official, updated as licenses are granted: `hkma.gov.hk/eng/regulatory-resources/registers/register-of-licensed-stablecoin-issuers/` |
| **SFC licensed VATP (virtual-asset trading platform) register** | Official registry of licensed virtual asset trading platforms — 4 tables: licensed, pending, withdrawn, forced-closure. **Confirmed live 2026-07-26**: 14 licensed VATPs including OSL (15/12/2020) and HashKey (09/11/2022), matching this doc's Tier 1 for those two. Guotai Junan International and Victory Securities do **not** appear on this list at all (different licence category — dealing in virtual assets, not operating an exchange; see Tier 1 split above). Bybit (via Spark Fintech Limited) and Crypto.com (via Foris DAX HK Limited) are both still pending, not yet licensed. OKX Hong Kong FinTech Company Limited and Huobi HK both formally withdrew their applications (OKX in May 2024) | Free, official, real `pandas.read_html()`-parseable HTML table: `sfc.hk/en/Welcome-to-the-Fintech-Contact-Point/Virtual-assets/Virtual-asset-trading-platforms-operators/Lists-of-virtual-asset-trading-platforms` |
| **On-chain data** (Dune Analytics free tier, Glassnode free tier, CoinGecko/CoinMarketCap free APIs) | Actual usage/volume for any stablecoin these companies claim to be building (e.g. AxCNH) once live | Free tiers exist; full historical/granular data is usually paywalled |
| **HKEX company announcements (RNS-equivalent)** | This entire sector moves on same-day announcement press releases (MOUs, treasury purchases, placements) — an announcement-scraper/alert on these specific 20-odd tickers is probably higher-value than any macro data source for this group | Free, official, but needs per-company monitoring given how scattered/frequent these are |
| **Stablecoin reserve attestation reports** (e.g. for AxCNH via AnchorX, once published) | Whether a claimed peg is actually backed 1:1 | Free once published, but disclosure quality/frequency unverified |

## Open questions
- Whether 域能控股 and 狮腾控股 belong on this list at all — recommend
  confirming with whoever built the original watchlist.
- None of the Tier 3/4 announcements were checked for follow-through (i.e.
  whether the MOU actually resulted in a shipped product) — for a sector
  this driven by press releases, that follow-through gap is probably the
  single biggest source of false signal.
