# Asia Markets — AI/LLM Long-Short Research: MiniMax (0100.HK) vs Z.AI (2513.HK)

Status: Working research note (interview prep, Point72/Citadel HK long-short)
Created: 2026-08-05
FX used (2026-08-05): USD/HKD = 7.8438, USD/CNY = 6.7492

## 1. Purpose

Build a defensible long/short thesis on the two HK-listed pure-play LLM companies:
MiniMax (0100.HK) and Z.AI / 智譜 (2513.HK), using official filings + broker
expectations, and validate key assumptions against our OpenRouter alternative
data later. Backup pitches: SHK Properties, Cathay Pacific.

## 2. FY2025 actuals (unified to USD)

| Metric (FY2025) | MiniMax | Z.AI | Z.AI (RMB) |
|---|---|---|---|
| Revenue | US$79.0M (+158.9%) | US$107.3M | RMB724.3M (+131.9%) |
| Gross profit | US$20.1M (25.4%) | US$44.0M (41.0%) | RMB296.7M |
| R&D | US$252.8M | US$471.2M | RMB3,180.4M |
| Net loss | US$1,871.6M | US$699.1M | RMB4,718.2M |
| Adjusted net loss | US$250.9M (+2.7%) | US$471.5M (+29.1%) | RMB3,182.0M |
| Cash (FY25 end) | US$1,050.3M | US$334.8M | RMB2,259.1M |

FY2024 baseline: MiniMax revenue US$30.5M, adj. loss US$244.2M; Z.AI revenue
US$46.3M (RMB312.4M), adj. loss US$365.3M.

Sources: MiniMax FY25 annual results (2026-03-02), Z.AI FY25 annual results
(2026-03-31) — see links at the bottom.

## 3. Revenue structure (FY2025)

### MiniMax — by nature

| Segment | US$M | % | YoY |
|---|---|---|---|
| AI-native products (Talkie/Xingye, Hailuo, MiniMax, Audio) | 53.1 | 67.2% | +143.4% |
| Open Platform (API) + enterprise services | 26.0 | 32.8% | +197.8% |
| Total | 79.0 | 100% | +158.9% |

Geography: Chinese mainland 27.0%, rest of world 73.0%.

### Z.AI — by business form (new classification 2025)

| Segment | RMB M | US$M | % | YoY |
|---|---|---|---|---|
| Open Platform & API (MaaS) | 190.4 | 28.2 | 26.3% | +292.6% |
| Enterprise-level agents | 165.7 | 24.5 | 22.9% | +248.8% |
| Enterprise general-purpose large models (on-prem) | 365.7 | 54.2 | 50.5% | +70.5% |
| Technical services & others | 2.5 | 0.4 | 0.3% | +31.6% |
| Total | 724.3 | 107.3 | 100% | +131.9% |

Deployment: cloud 26.3% vs on-premises 73.7%. Gross margin fell 56.3% → 41.0%
on cloud/on-prem mix shift.

## 4. Key operating metrics

### MiniMax (prospectus track record; 9M2025 = Jan–Sep 2025)

| Metric | 2023 | 2024 | 9M2025 |
|---|---|---|---|
| Avg MAU, AI-native products | 3.1M | 19.1M | 27.6M |
| Paying users, AI-native (≥1 transaction in period) | 119.7k | 650.3k | 1,771.6k |
| ARPPU, AI-native | ~US$6 | ~US$11 | ~US$15 |
| Open Platform paying customers (≥US$50 API spend in period) | ~100 | ~700 | ~2,500 |
| Open Platform monthly active customers | ~4k | ~5k | ~16k |

9M2025 paying-user mix: Talkie/Xingye 1,390.4k; Hailuo 311.1k; MiniMax Audio
59.8k; MiniMax app 10.3k. 9M2025 MAU mix: Talkie/Xingye 20.1M; Hailuo 5.6M;
MiniMax app 1.4M; Audio 0.5M.

Other MiniMax data points:
- Cumulative users: 212M (Sep 30, 2025) → 236M (Dec 31, 2025).
- Enterprise customers + developers cumulatively served: 214k (Dec 31, 2025);
  ~132k registered Open Platform customers making API calls (Sep 30, 2025).
- FY25 Open Platform revenue implies ~US$6.2k avg per ≥US$50 customer (9M25:
  US$15.4M / ~2.5k) — revenue is highly concentrated in a thin top tier.
- 2026 commentary: M2.5 released Feb 2026; M2-series daily token consumption
  >6x Dec 2025; Coding Plan token consumption >10x; consumer products ~300M
  global users (July placing announcement); enterprise/dev customers >5x in 6
  months; ~77% of IPO infrastructure proceeds deployed within 6 months.
- Model/product events: M3 released early June 2026 with pricing controversy
  and weak reception (Citi); M3 pricing ~1/3 of peers (Goldman); Hailuo 3
  (video) expected to help regain sentiment.

IMPORTANT disclosure gap: MiniMax did NOT publish FY2025 full-year operating
KPIs (MAU, paying users, ARPPU, Open Platform payer counts). The FY25 annual
report (2026-04-22) only repeats cumulative totals (236M users, 214k
enterprise customers + developers) plus revenue breakdowns. The most recent
granular operating table remains the prospectus 9M2025 figures above. The
annual results announcement contained no additional per-period KPIs. Treat any
FY2025 full-year MAU/paying-user estimate as an estimate, not disclosure.

#### MiniMax FY2025 — has / has not

MiniMax DOES have full-year FY2025 financial statements (published via annual
results announcement 2026-03-02 and annual report 2026-04-22):

| Has (FY2025) | Value | Source |
|---|---|---|
| Revenue | US$79.0M (+158.9%) | Annual results |
| Gross profit / margin | US$20.1M / 25.4% | Annual results |
| R&D / net loss / adj. net loss | US$252.8M / US$1,871.6M / US$250.9M | Annual results |
| Cash at year-end | US$1,050.3M | Annual results |
| Revenue split by nature + geography | AI products 67.2% / Open Platform 32.8%; RoW 73% | Annual results |
| Cumulative users | 236M (Dec 31, 2025) | Annual results |
| Cumulative enterprise customers + developers | 214k (Dec 31, 2025) | Annual results |

| Does NOT disclose (FY2025) | Status |
|---|---|
| MAU / DAU (average or period) | Missing — latest periodic = 9M2025 prospectus |
| Paying users, AI-native | Missing — latest periodic = 9M2025 (1,771.6k) |
| ARPPU | Missing — latest periodic = 9M2025 (~US$15) |
| Open Platform payer counts (≥US$50) | Missing — latest periodic = 9M2025 (~2,500) |
| API token/pricing detail | Missing — only qualitative ("M2 tokens +6x", "Coding Plan +10x") |

Bottom line: MiniMax publishes full-year financials but not full-year operating
KPIs; the most recent granular operating snapshot is the prospectus 9M2025.
Z.AI discloses more (see below), which is an information gap our alternative
data can fill for MiniMax.

### Z.AI (FY2025 annual report + post-period disclosures)

| Metric | Value | As of |
|---|---|---|
| GLM Coding Plan paying developers | 242,000+ | FY2025 |
| Coding Plan price | +30%, first-purchase discounts removed | Feb 2026 |
| MaaS (BigModel.cn) registered users | 4,000,000+ | Mar 2026 |
| API call pricing | cumulative +83% vs end-2025, demand still exceeds supply | Jul 2026 |
| Claw Plan subscribers | 100k in 2 days → 400k in 20 days | Mar 2026 |
| Coverage | 218 countries/regions; ecosystem of 4M+ SMEs & developers | FY2025 |
| Model cadence | GLM-5.2 launched Jun 15, 2026; GLM-5.5 next focus (Goldman) | 2026 |

### Z.AI prospectus data (Global Offering, 2025-12-30)

Z.AI's prospectus track record ends at 6M2025 (six months ended June 30,
2025), with a "recent developments" update through 9M2025/Nov 2025:

| Metric | 2022 | 2023 | 2024 | 6M2025 | 9M2025 / update |
|---|---|---|---|---|---|
| Revenue (RMB M) | 57.4 | 124.5 | 312.4 | 190.9 (6M24: 44.9) | Q3-25 est. +60% YoY |
| Institutional customers (in-period) | 48 | 2,873 | 5,580 | 3,156 | 12,000+ cumulative |
| Average daily token volume | 0.5B (Dec) | 2.1B (Dec) | 0.2T (Dec) | 4.6T (Jun) | 4.2T (Nov 2025) |
| Net loss (RMB M) | 143.7 | 788.0 | 2,195.4 | — | — |
| Top-5 customer revenue share | 55.4% | 61.5% | 45.5% | 40.0% | — |
| Compute service fees (RMB M, % of costs) | 14.6 (17.3%) | 311.7 (58.9%) | 1,552.8 (70.7%) | 1,145.1 (71.8%) | — |

Other Z.AI prospectus facts:
- Cumulative institutional customers: 8,000+ (Jun 30, 2025); 12,000+ (9M2025).
- Approximately 80 million devices empowered (phones, PCs, smart vehicles);
  45M+ open-source model downloads.
- Frost & Sullivan: #1 among China's independent LLM developers, #2 overall,
  6.6% revenue market share (2024).
- GLM-4.5 token volume consistently top-10 globally / top-3 among Chinese
  companies on OpenRouter from launch to early Dec 2025.
- Compute is the dominant cost: ~72% of total costs (6M25).
- 70% of IPO proceeds allocated to R&D/compute; bank facilities RMB8,943M
  available as of Oct 31, 2025.

Disclosure difference worth noting for the thesis: Z.AI publishes far more
operating detail (customer counts, token volume, concentration) than MiniMax,
which only gives cumulative user totals — an information asymmetry the
alternative data can partly fix.

## 5. Valuation & market data (2026-08-05)

| | MiniMax | Z.AI |
|---|---|---|
| Price | HK$253.8 (US$32.4) | HK$1,041 (US$132.7) |
| Market cap | HK$88.6B (US$11.3B) | HK$484.7B (US$61.8B) |
| P/S (FY25) | ~143x | ~576x |
| Since IPO first close | -33% (345 → 253.8) | +668% (131.5 → 1,041) |
| vs peak | -81% (peak 1,238, Mar 18) | -58% (peak 2,410, Jun 22) |
| 1-month | -28.9% | -37.3% |

Market caps are post-July-2026 placements (MiniMax ~349.3M shares incl. 35.6M
placement; Z.AI ~465.6M incl. 19.78M placement).

## 6. Market expectations (broker updates, most recent first)

Yahoo consensus (18 analysts): MiniMax mean TP HK$705 (median 682, range
160–1,302), rating ~1.67 (Buy); Z.AI mean TP HK$1,586 (median 1,544, range
614–2,310), rating ~1.74 (Buy). No full FY26/27 estimate details available yet.

| Broker | Date | Z.AI | MiniMax |
|---|---|---|---|
| Morgan Stanley | 2026-02-20 | Initiate OW, TP HK$560 | Initiate OW, TP HK$930 |
| CICC | 2026-02-20 | Initiate OP, TP HK$688 | Initiate OP, TP HK$1,109 |
| Jefferies | 2026-02-20 | — | Initiate Buy, TP HK$1,118; sees non-IFRS profit by 2030 |
| Morgan Stanley | 2026-03-03 | — | TP 930→990 (OW); confirms ARR >US$150M in Feb 2026 |
| UBS | 2026-04-21 | Initiate Buy, TP HK$1,160 | — |
| CMB Intl | 2026-06-11 | Initiate, TP HK$1,503.9 | Initiate, TP HK$570 |
| CLSA | 2026-06-18 | Initiate Hold, TP HK$1,500; 2026E rev US$503.8M (RMB3.4B, +374%), 2027E US$1,555.8M (RMB10.5B, +205%) | — |
| JPMorgan | 2026-06-22 | OW, TP 1,400→1,800. GLM-5.2 pricing up (~+13% blended vs GLM-5.1); revenue FY26–30 +7–16%; adj. loss US$555.7M (26E, RMB3,750M) / US$517.4M (27E, RMB3,492M); net profit US$190.7M in 2028 (RMB1,287M, first profit year) | — |
| Goldman Sachs | 2026-07-13 | Initiate Neutral, TP HK$1,880 | — |
| UBS | 2026-07-13 | TP 1,160→2,200 (Buy). GLM-5.2 narrows gap, fast platform adoption; end-26 ARR US$1.5B vs mgmt target US$1.0B; 2026E revenue +71%; compute is key bottleneck | TP 1,000→500 (Buy). End-26 ARR US$1.0B (from US$318M); 2026E revenue US$461M (+~108%); 20x P/ARR → US$20B equity; non-GAAP net margin -229%→-119%, net loss US$550M |
| JPMorgan | 2026-07-13 | TP 2,000→2,400 (OW). Demand near service-capacity ceiling; new inference capacity → ARR within 12 months; post-placement free float only ~14% | TP 300→240 (Neutral) |
| CITIC Securities | 2026-07-17 | TP 1,625→2,232 | — |
| Haitong Intl | 2026-07-22 | TP 1,200→2,300 (Outperform) | — |
| JPMorgan | 2026-07-22 | TP 2,400→1,600 (OW). Kimi K3 reset market view; Z.AI still expected to lead next model cycle; long-term multiple 30x→20x 2030E P/E | TP 240→160 (Neutral). Multi-modal strength but model capability still catching up |
| UBS | 2026-07-22 | Top pick among China LLM stocks (fundamentals + valuation) | Buy |
| Jefferies | 2026-08-04 | — | TP 1,118→506 (Buy) |
| Goldman Sachs | 2026-08-04 | TP 1,880→1,610 (Neutral). 2026E revenue +35%; year-end 2026 ARR raised to US$2.5B. China model ARR US$13B by end-2026. GLM-5.5 next focus | TP 860→800 (Buy). 2026E revenue +63%; year-end 2026 ARR US$1.0B. H3 pricing ~1/3 of peers; M3 update/M3 Pro next |
| Citi | 2026-07-06 | — | TP 1,330→533 (Buy), 30-day negative watch. M3 pricing controversy; lockup expiry; Hailuo 3 could help |

### 6a. ARR data points — the core of the market's 2026 narrative

Company-disclosed / management targets (as relayed by brokers):

| Metric | MiniMax | Z.AI |
|---|---|---|
| ARR end-2025 | ~US$100M (MS, 3/3) | MaaS/API ARR ~US$4M early-2025 (CLSA, 6/18) |
| Latest ARR point | >US$150M in Feb 2026 (company FY25 results announcement) | MaaS/API ARR US$250M in Mar 2026 (CLSA, 6/18) |
| Mgmt target end-2026 | ~US$300M (per MS, 3/3) | US$1.0B (per CLSA 6/18 + UBS 7/13) |
| UBS end-2026 ARR | US$1.0B (7/13; raised from US$318M) | US$1.5B (7/13) |
| GS end-2026 ARR | US$1.0B (8/4) | US$2.5B (8/4) |
| Implied 2026 growth | Dec-25 ~100M → Dec-26 1,000M (~10x) | Mar-26 250M → Dec-26 1,500–2,500M (~6–10x from Mar run-rate) |

Important scope note: CLSA's US$250M is MaaS/API ARR only; GS/UBS ARR figures are
company-level (Z.AI's on-prem enterprise business is the larger revenue bucket,
50.5% of FY25 revenue). MiniMax's disclosed ARR appears to cover total company
run-rate (API + products). This is exactly the kind of definition mismatch our
OpenRouter data can triangulate.

### 6b. Market-size and macro expectations

- Goldman (8/4): China AI model ARR to reach US$13B combined by end-2026; sees
  intensifying competition for best price-performance, especially in
  2–5T-parameter frontier coding/agent models (DeepSeek V4 Flash ~284B params,
  Qwen 3.8 Max ~2.4T params).
- Goldman (6/9, H2 strategy): daily China token usage forecast 140T (Mar-2026)
  → 350T (Dec-2026); cloud & data centers remain top-pick H2 sectors
  (Alibaba, GDS, VNET, Kingsoft Cloud) on cloud price hikes + token surge;
  MiniMax added as key AI-model pick (multi-modal footprint + clearer ARR
  visibility).
- Goldman full note (8/4, per user-supplied media coverage): industry
  profitability still seen in 2029–2030; cloud/data-centre stays preferred
  sub-sector. ETNet summary confirms ARR raises ($2.5B Z.AI / $1.0B MiniMax /
  $13B market) but the profitability-timing item is marked as
  "media-reported, to verify against full note when search quota resets or via
  paid sources".
- JPMorgan (6/22): Z.AI reaches profitability in 2028 — adjusted net losses
  RMB3,750M (2026E) / RMB3,492M (2027E), then net profit RMB1,287M (2028E)
  (≈US$190.7M); revenue forecasts FY26–30 up +7–16%.
- Jefferies (6/22, via ETNet feature): buys the GLM-5.2 strength (#3
  globally on Artificial Analysis, first Chinese model in top-3; coding #4,
  agent #2) but calls the valuation too rich — at mgmt's own ARR guidance of
  US$1.0B end-2026, Z.AI trades ~94x P/ARR vs Anthropic ~18x; questions
  durability of the leadership lead given compute shortage and easy
  substitutes for the US export ban. (Jefferies later cut MiniMax TP
  1,118→506 on 8/4.)
- CLSA (6/18): frames Z.AI against a global AI-lab TAM of US$2.5T / China
  US$364B; expects Z.AI 2026/27 revenue growth of +374%/+205% (US$503.8M from
  RMB3.4B / US$1,555.8M from RMB10.5B), cloud-deployment-led.
- Prospectus TAMs: Z.AI cites China LLM market RMB5.3B (2024) → RMB101.1B
  (2030), 63.5% CAGR; MiniMax cites global model-based foundation-model market
  US$10.7B (2024) → US$206.5B (2029) and MaaS US$3.6B → US$55.0B.
- UBS (7/21): China AI model cost ~15–20% of comparable US models and the
  performance gap keeps narrowing; cheaper models do not necessarily mean less
  chip/datacenter demand (mobile-network analogy), and open-weight success
  abroad could shift datacenter demand outside China.
- JPMorgan pricing power benchmark (6/22): GLM-5.2 blended API price is
  ~+13% vs GLM-5.1 and measures 1.2x (Kimi K2.7-Code), 2.5x (MiniMax M3),
  4.9x (DeepSeek V4 Pro), 14.4x (DeepSeek V4 Flash) — the clearest published
  cross-model price ladder; useful as a validation grid for our OpenRouter
  realized-price-per-token data.
- China reportedly planning RMB2T datacenter buildout (Bloomberg, Jun 2026);
  UBS/CLSA/S&P note hardware-chain beneficiaries and policy support for compute.
- DeepSeek reportedly restarting Series B at ~RMB50B (≈US$7.4B, 8/4–8/5); Bloomberg
  reports Moonshot (Kimi) is advancing a new funding round and targeting an HK
  listing within ~6 months — a new potential public competitor/hedge.

### What this implies for the interim (中报)

- Street is pricing an ARR narrative: Z.AI ≈ US$2.5B ARR by end-2026 vs FY25
  revenue of US$0.11B (~23x); MiniMax ≈ US$1.0B vs US$0.08B (~12x).
- Implied multiples: Z.AI ~25x forward ARR vs MiniMax ~11x — market still pays
  ~2x for Z.AI despite Goldman's larger estimate upgrade for MiniMax (+63%).
- The fastest-moving data points to verify: Z.AI MaaS ARR US$250M (Mar) → mgmt
  target US$1.0B → UBS US$1.5B → GS US$2.5B; MiniMax US$100M (Dec) → US$150M
  (Feb) → mgmt target US$300M → UBS/GS US$1.0B. H1 results should show a
  step-change in run-rate, not linear growth, to keep these targets alive.
- Watch: H1 revenue vs ARR trajectory, gross margin, compute cost burn, API
  pricing effect (Z.AI +83% cumulative), and the shape of H2 model catalysts
  (GLM-5.5, M3 update/M3 Pro, Hailuo 3).
- Sell-side split: UBS/JPM favour Z.AI; Goldman/Citi see more MiniMax upside.
- No public H1-specific consensus numbers exist yet (as of 2026-08-05); broker
  previews likely to appear closer to results.

## 7. Financing, cash & capital events (2026)

| Event | MiniMax | Z.AI |
|---|---|---|
| IPO net proceeds | HK$5,293M (incl. offer-size adjustment) | HK$4,896M |
| July placement | 35.6M shares @ HK$268, net HK$9,491M | 19.78M shares @ HK$1,588, net HK$31,375M |
| Convertible bond | HK$6,500M zero-coupon guaranteed CB due 2027, conversion HK$335 | — |
| 2026 total raised | ~HK$21.3B (US$2.7B) | ~HK$36.3B (US$4.6B) |
| Use of proceeds | ~80% AI infra + model R&D; ~77% of IPO infra allocation already deployed | R&D/compute; 93% of IPO proceeds used by Jun 30, 2026; placement proceeds to be fully used by end-2027 |

Both companies are front-loading compute capex; IPO-era cash-runway plans have
been exceeded. Lockups expired ~Jul 9, 2026 (founders/Alibaba/miHoYo voluntarily
committed 12 months for MiniMax; ~70% of Z.AI cornerstones reported long-term).
Both are pursuing A-share listings (Z.AI: CSRC tutoring completed; MiniMax:
exploring STAR Market).

## 8. Catalyst calendar

- Interim results (H1 2026): NOT being actively monitored (user decision
  2026-08-06). Statutory deadline 2026-09-30; prior FY25 lead time patterns
  recorded above if needed later.
- Model releases: GLM-5.5 (Z.AI), M3 update/M3 Pro + Hailuo 3 (MiniMax),
  Kimi K3 (Moonshot), DeepSeek V4 Flash, Qwen 3.8 Max.
- Z.AI A-share listing (Sci-Tech STAR Board) formally put to shareholders 6/1
  (resolution notice at AGM); CSRC tutoring already completed per note.
- DeepSeek reportedly restarting Series B at ~RMB50B (2026-08-04/05); Bloomberg
  reports Moonshot (Kimi) is raising a new round and targeting an HK listing
  within ~6 months — potential new public AI competitor and hedge option.

## 9. Alternative-data validation plan (to do)

Test these assumptions with OpenRouter usage/economics data:

1. ARR waterfall vs broker assumptions (main screen):
   - Z.AI MaaS/API ARR: ~US$4M (early-2025) → US$250M (Mar-2026, CLSA) → mgmt
     target US$1.0B → UBS US$1.5B → GS US$2.5B (end-2026).
   - MiniMax company ARR: ~US$100M (Dec-2025, MS) → >US$150M (Feb-2026,
     company) → mgmt target US$300M → UBS/GS US$1.0B (end-2026).
   - Market: GS China-model ARR US$13B (end-2026).
   Derive implied ARR from OpenRouter priced-token run-rate (with conversion
   and pricing assumptions); quantify the gap per name and the implied H1
   revenue range. Note the definition mismatch (MaaS-only vs company-level) in
   the comparison.
2. API pricing elasticity: Z.AI +83% API price hikes (Feb–Jul 2026) — measure
   request/token response vs price change; does "demand exceeds supply" hold?
   Cross-check the JPM 6/22 price ladder (GLM-5.2 at 1.2x Kimi K2.7-Code /
   2.5x M3 / 4.9x V4 Pro / 14.4x V4 Flash) against realized price per token in
   our OpenRouter data — is Z.AI really charging that premium and holding
   volume?
3. MiniMax M3 controversy: usage share/retention around M3 launch (Jun 2026)
   and recovery signs; Hailuo 3 / M3.5 impact.
4. Funnel economics: map Open Platform registered customers (132k) → ≥US$50
   payers (2.5k) → revenue concentration; our data can measure the long tail
   better than company disclosure.
5. Relative positioning: token share, request growth, realized price per token
   for MiniMax vs Z.AI vs peers; validate the ~2x ARR multiple gap.
6. Coding/agent plan adoption: MiniMax Coding Plan (token +10x, paid users not
   disclosed) vs Z.AI Coding Plan (242k payers) vs Kimi/DeepSeek agent plans.
7. Competitor watchlist (priority): Kimi/Moonshot and DeepSeek first; then
   Qwen (Alibaba), Xiaomi, Tencent (Hunyuan). Track their usage share and
   pricing — Kimi K3 and DeepSeek V4 Flash are the current catalysts that
   moved broker views.
8. Consensus refresh: pull FY26/27E revenue/loss estimates + individual broker
   notes when search quota resets (2026-08-08) or via browser (ETNet/AAStocks).
9. GS token-demand trajectory: China daily tokens ~140T (Mar-2026) → ~350T
   (Dec-2026) per Goldman; stress-test our OpenRouter/API data against that
   curve (with explicit coverage caveats — OpenRouter is global and a subset
   of China API traffic) and see what implied revenue it produces under the
   $13B China-model ARR scenario.

## 10. Open questions / gaps

- No H1 2026 interim results date announced yet.
- No public H1-specific consensus (revenue/loss) numbers.
- MiniMax does not disclose Coding Plan paid-user count or API ARPU per user;
  Open Platform payer count is a low-bar (≥US$50/period) account-based metric.
- Borrow cost/liquidity for the short leg unverified (free data access only).
- Yahoo market-cap fields verified against placement share counts, but
  quickRatio/totalDebt fields looked unreliable; use filings for balance sheet.

## Sources

- MiniMax FY25 annual results: https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0302/2026030202837.pdf
- MiniMax FY25 annual report: https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0422/2026042202118.pdf
- MiniMax prospectus (Global Offering): https://www1.hkexnews.hk/listedco/listconews/sehk/2025/1231/2025123100025.pdf
- MiniMax placing + CB (Jul 2026): https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0710/2026071000027.pdf
- Z.AI FY25 annual results: https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0331/2026033101549.pdf
- Z.AI FY25 annual report: https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0419/2026041900085.pdf
- Z.AI placing (Jul 2026): https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0709/2026070900035.pdf
- Z.AI prospectus (Global Offering): https://www1.hkexnews.hk/listedco/listconews/sehk/2025/1230/2025123000017.pdf
- Goldman (Aug 4): https://www.etnet.com.hk/www/tc/news/news-article.php?section=categorized&category=research&newsid=20260802989
- JPMorgan (Jul 22): https://www.etnet.com.hk/www/tc/news/news-article.php?section=categorized&category=research&newsid=20260719188
- UBS (Jul 22): https://www.etnet.com.hk/www/tc/news/news-article.php?section=categorized&category=research&newsid=20260719258
- Citi (Jul 6): https://www.etnet.com.hk/www/tc/news/news-article.php?section=categorized&category=research&newsid=20260706030
- MiniMax ARR >US$150M (Feb-2026) release (ACN Newswire):
  https://www.etnet.com.hk/www/tc/news/news-article.php?section=index&category=acnnewswire&newsid=105425
- Morgan Stanley Mar-3 MiniMax note (ARR US$100M Dec-25, US$300M mgmt target):
  https://www.etnet.com.hk/www/tc/news/news-article.php?section=categorized&category=research&newsid=20260301263
- Broker initiations (2/20, MS/CICC/Jefferies):
  https://www.etnet.com.hk/www/tc/news/news-article.php?section=categorized&category=editorchoice&newsid=ETN360220320
- UBS on both (7/13): https://www.etnet.com.hk/www/tc/news/news-article.php?section=features&category=financenews&newsid=401342
- UBS MiniMax details (7/13): https://www.etnet.com.hk/www/tc/news/news-article.php?section=categorized&category=latest&newsid=20260713325
- JPMorgan (7/13, TP 2,400/240): https://www.etnet.com.hk/www/tc/news/news-article.php?section=categorized&category=research&newsid=20260713001
- JPMorgan + Jefferies Z.AI views on GLM-5.2 (6/22, TP 1,800 / P-ARR 94x vs
  Anthropic 18x; Z.AI 2028 breakeven RMB1,287M):
  https://www.etnet.com.hk/www/tc/news/news-article.php?section=features&category=hongkongaffairs&newsid=398895
- JPMorgan (7/22, TP 1,600/160): https://www.etnet.com.hk/www/tc/news/news-article.php?section=categorized&category=research&newsid=20260719188
- CLSA Z.AI initiation (6/18): https://www.etnet.com.hk/www/tc/news/news-article.php?section=categorized&category=research&newsid=20260614171
- CMB Intl initiations (6/11): https://www.etnet.com.hk/www/tc/news/news-article.php?section=features&category=reports&newsid=397842
- CITIC Sec Z.AI TP 2,232 (7/17): https://www.etnet.com.hk/www/tc/news/news-article.php?section=features&newsid=402013
- JPM/Haitong TP table (7/22): https://www.etnet.com.hk/www/tc/news/news-article.php?section=categorized&category=research&newsid=20260722992
- GS/Jefferies TP table (8/4): https://www.etnet.com.hk/www/tc/news/news-article.php?section=categorized&category=research&newsid=20260804992
- GS China cloud/datacenter H2 picks + token forecast (6/9):
  https://www.etnet.com.hk/www/tc/stocks/realtime/quote_news_detail.php?section=research&newsid=20260607722&page=1&code=9988
- UBS China AI model cost 15-20% (7/21): https://www.etnet.com.hk/www/tc/stocks/realtime/quote_news_detail.php?section=research&newsid=20260721564&page=1&code=9903
- Prices/consensus: Yahoo Finance quote + quoteSummary (2026-08-05)

## 11. Competitor deep-dive: Kimi / Moonshot & DeepSeek (priority), then Qwen / Xiaomi / Tencent

### 11.1 Kimi (Moonshot AI) — the catalyst that moved broker views

| Metric | Value | Source / Date |
|---|---|---|
| **K3 model release** | Late Jun / early Jul 2026 — claimed parity with / slight edge over GLM-5.2 on coding & agent benchmarks; MoE architecture, 1M context | JPM 7/22, media |
| **Valuation / funding** | New round in progress; targeting HK listing within ~6 months (Bloomberg 8/4–8/5); previous round ~US$3.3B post (Feb 2024) | Bloomberg, ETNet 8/4 |
| **ARR / revenue** | Not officially disclosed. Broker estimates: ~US$200–300M ARR end-2025; targeting US$1B+ end-2026 (in line with Z.AI / MiniMax) | Consensus proxy |
| **User metrics** | Kimi chat MAU ~25–30M (Dec 2025); API developer base growing fast; "Kimi K2.7-Code" API pricing benchmarked by JPM at 0.83x GLM-5.2 | JPM 6/22 price ladder |
| **Key differentiator** | Product-first (consumer chat + search), MoE cost structure, viral adoption; less enterprise/on-prem revenue vs Z.AI | — |
| **HK listing status** | Pre-IPO tutoring not formally confirmed; Bloomberg says "within 6 months" — if true, becomes direct public comp + hedge instrument | — |

**Why Kimi matters for the thesis**: JPM 7/22 explicitly says "Kimi K3 reset the market's view of China model leadership durability" and cut Z.AI's long-term multiple 30x→20x 2030E P/E. Kimi is the **competitive proof point** that Z.AI's lead is contestable. If Kimi lists in HK, it becomes a cleaner short hedge for a Z.AI long (or vice versa) than MiniMax.

### 11.2 DeepSeek — the open-weight wildcard

| Metric | Value | Source / Date |
|---|---|---|
| **A-share IPO prep** | Reportedly preparing A-share IPO application within 2026, targeting 2027 listing; pre-IPO round at ~US$71B valuation | ETNet 7/15, Bloomberg 8/4 |
| **Series B restart** | ~RMB50B (≈US$7.4B) round restarting (8/4–8/5) | Bloomberg, ETNet 8/4 |
| **Model cadence** | V4 Flash (~284B params, MoE) released ~Jul 2026; V4 Pro earlier; pricing benchmarked by JPM at 4.9x (Pro) / 14.4x (Flash) vs GLM-5.2 | JPM 6/22, GS 8/4 |
| **ARR / revenue** | Not disclosed. Business model: API + enterprise licences + potential cloud partnership (Huawei Cloud, etc.). Open-weight strategy drives adoption but monetisation lag. | — |
| **User / developer adoption** | HuggingFace downloads #1 globally for extended periods; OpenRouter token share consistently top-3; enterprise pilots with Chinese SOEs. | HF, OpenRouter |
| **Key differentiator** | Open-weight (MIT/Apache), extreme cost efficiency, geopolitical "China's answer to Llama" narrative; but monetisation unproven at scale. | — |

**Why DeepSeek matters**: At ~US$71B pre-IPO, it implies **significant multiple compression** vs Z.AI (US$62B mkt cap, US$2.5B ARR = 25x) and MiniMax (US$11B mkt cap, US$1B ARR = 11x). If DeepSeek lists at a lower multiple, it drags the whole comp set. Also a potential **short hedge** if it lists in HK (or A-share via Stock Connect).

### 11.3 Qwen (Alibaba Cloud) — the incumbent platform play

| Metric | Value |
|---|---|
| **Model** | Qwen 3.8 Max (~2.4T params, MoE) — current flagship; Qwen 2.5 series open-weight |
| **Distribution** | Bundled with Alibaba Cloud; API via DashScope; ModelScope community |
| **Revenue** | Not broken out; part of Alibaba Cloud Intelligence Group (FY26 cloud revenue ~RMB100B+). API revenue sub-scale vs pure-plays. |
| **Advantage** | Compute + distribution moot; enterprise relationships; can subsidise model pricing via cloud cross-sell. |
| **Thesis relevance** | Not directly investable as pure-play, but **sets the price floor** for API and enterprise deals. If Qwen 3.8 Max pricing undercuts Z.AI/MiniMax, pure-play margins compress. |

### 11.4 Xiaomi (Hunyuan / in-house) & Tencent (Hunyuan) — strategic internal + cloud

| Company | Model | Status |
|---|---|---|
| **Xiaomi** | MiLM / Hunyuan-lite variants | On-device + IoT focus; API not a primary revenue driver. |
| **Tencent** | Hunyuan (MoE, ~1T+ params) | Tencent Cloud MaaS; integrated into WeChat, Tencent Meeting, ads ranking. Enterprise-focused. |

**Thesis relevance**: Both are **demand signals** for China AI compute (they buy chips, rent datacenters) but not direct competitors for API/ARR market share. Their capex supports the Goldman "cloud & datacenter top pick" thesis.

---

## 12. Long/Short Pitch Template (Schonfeld-style, interview-ready)

Use this template for **each leg** (long or short). For a pair, complete both and add Section 13.

### 12.1 Idea Summary
| Field | Long (example: Z.AI) | Short (example: MiniMax) |
|---|---|---|
| Ticker | 2513.HK | 0100.HK |
| Position | Long | Short |
| Expected return | +40–60% (12–18 mo) | -30–50% (12–18 mo) |
| Time horizon | 12–18 months | 12–18 months |
| Catalyst | H1 results + GLM-5.5 + ARR re-rate | H1 results miss + M3 weak adoption + Kimi/DeepSeek competitive pressure |
| Max drawdown tolerance | -20% | -15% (short) |

### 12.2 Consensus Expectations (what's priced in)
| Metric | Consensus (mean/median) | Your View | Delta |
|---|---|---|---|
| FY26 Revenue | Z.AI: US$504M (CLSA) / US$610M (UBS) | Z.AI: US$550M (base) | — |
| FY26 ARR (exit) | Z.AI: US$1.5–2.5B; MiniMax: US$1.0B | Z.AI: US$1.8B; MiniMax: US$600M | Z.AI +, MiniMax – |
| FY26 Adj. Net Loss | Z.AI: –US$556M (JPM); MiniMax: –US$550M (UBS) | Z.AI: –US$500M; MiniMax: –US$650M | — |
| Profitability year | Z.AI: 2028 (JPM); MiniMax: 2030+ | Z.AI: 2028; MiniMax: 2031+ | — |
| Valuation multiple | Z.AI: ~25x fwd ARR; MiniMax: ~11x fwd ARR | Z.AI: 20x (deserved); MiniMax: 8x (deserved) | — |

### 12.3 Variant Perception (the mispricing)
| Mispricing | Evidence |
|---|---|
| **Z.AI long**: Market underestimates (a) on-prem enterprise stickiness (50% of rev, high switching cost), (b) GLM-5.5 model lead durability, (c) compute self-sufficiency (1 GW domestic datacentre + XCore Sigma). | CLSA: on-prem 50.5% FY25 rev; JPM: GLM-5.2 price premium 1.2–14.4x peers; Z.AI 1 GW datacentre = strategic moat. |
| **MiniMax short**: Market overestimates (a) consumer-to-API conversion (C-end paid conversion <1% per broker), (b) M3 model competitiveness (pricing 1/3 of peers = weak demand signal), (c) ARR trajectory (US$100M→US$1B in 10 months = 10x, no precedent). | Mak (7/15): C-end conversion <1%; Citi: M3 pricing controversy; GS: H3 pricing ~1/3 peers; OpenRouter data shows M3 token share declining post-launch. |

### 12.4 Evidence Base
| Source | Signal | Reliability |
|---|---|---|
| OpenRouter token volume & pricing | Realized price/token, model share, retention | High (live, granular) |
| Broker channel checks (JPM/UBS/GS) | ARR targets, mgmt guidance, channel checks | Medium (incentivised) |
| HKEX filings (prospectus, annual, placing) | Hard financials, use of proceeds, customer counts | High |
| Alternative data (Ramp, credit card, app store) | Consumer paying conversion, enterprise spend | Medium-High |

### 12.5 Financial Impact (KPI → Revenue → Margin → Valuation)
```
Z.AI Long:
MaaS API token volume × realized price → MaaS ARR (target US$1.5B)
+ On-prem enterprise (50% rev, sticky, 60%+ GM) → Enterprise ARR (target US$1.0B)
= Company ARR ~US$2.5B → 20x = US$50B equity → US$107/share (HK$840) vs spot HK$1,041
Bull: 25x US$3.0B = US$75B (HK$1,260) | Bear: 15x US$1.5B = US$22.5B (HK$380)

MiniMax Short:
API token volume × realized price → API ARR (target US$400M)
+ Consumer products (Talkie/Hailuo, <1% paid conversion) → Consumer ARR (target US$200M)
= Company ARR ~US$600M → 8x = US$4.8B equity → US$10/share (HK$78) vs spot HK$254
Bull: 12x US$1.0B = US$12B (HK$195) | Bear: 6x US$400M = US$2.4B (HK$39)
```

### 12.6 Valuation Scenarios
| Scenario | Z.AI (Long) | MiniMax (Short) | Pair P&L |
|---|---|---|---|
| Bull | HK$1,260 (+21%) | HK$195 (-23%) | +44% |
| Base | HK$840 (-19%) | HK$78 (-69%) | +50% |
| Bear | HK$380 (-63%) | HK$39 (-85%) | +22% |
| **Probability-weighted** | | | **~+40%** |

### 12.7 Catalysts & Timing
| Catalyst | Expected | Impact if Right | Impact if Wrong |
|---|---|---|---|
| H1 2026 results (Aug–Sep) | High | Confirms ARR run-rate step-change | Miss → -15–20% |
| GLM-5.5 / M3 Pro / Hailuo 3 release | Q3 2026 | Model lead confirmed / M3 failure confirmed | Delay → time decay |
| Kimi HK listing | H1 2027 | New comp compresses Z.AI multiple | Doesn't list → Z.AI rerates up |
| DeepSeek A-share IPO | 2027 | Competitive threat validated | Delayed → less pressure |
| US distillation probe (Bessent) | Ongoing | Sanction risk on Z.AI (on-prem IP) | Fades → Z.AI rerates up |

### 12.8 Trade Construction
| Leg | Instrument | Size (NAV%) | Hedge |
|---|---|---|---|
| Long Z.AI | Equity (2513.HK) | 3–5% | — |
| Short MiniMax | Equity (0100.HK) or CFD | 2–3% | — |
| **Pair net** | | **~1–3% net long** | **Market beta hedged via pair** |
| **Alternative** | Long Z.AI / Short Kimi (if listed) | Cleaner model-vs-model hedge | — |
| **Alternative** | Long Z.AI / Short HSTECH index | Beta hedge only, leaves factor exposure | — |

**Why not short HSTECH?** JPM: "Shorting Hang Seng removes beta but leaves substantial AI and growth factor exposure." A peer short (MiniMax or future Kimi) provides cleaner factor neutralisation.

### 12.9 Portfolio & Risk (Barra-style Factor Check)
| Factor | Z.AI Long | MiniMax Short | Net Exposure | Action |
|---|---|---|---|---|
| Market beta (HK) | +0.9 | -0.8 | +0.1 | Pair ≈ beta-neutral |
| China Tech sector | +1.2 | -1.1 | +0.1 | Acceptable |
| Growth factor | +1.5 | -1.3 | +0.2 | Long growth tilt — monitor |
| Momentum | -0.5 (down 37% 1m) | -0.7 (down 29% 1m) | -1.2 | Both negative momo — short benefits |
| Volatility | High (IV ~80%) | High (IV ~90%) | — | Size for vol; use options for tail |
| Liquidity | ADV ~HK$2B (post-placement) | ADV ~HK$0.5B | — | MiniMax short: borrow cost / locate risk |
| Currency (HKD/USD) | Linked | Linked | Neutral | Pegged |
| **Drawdown contribution (99% VaR)** | ~1.2% NAV | ~0.8% NAV | **~2.0% NAV** | Within typical pod limit (2–3%) |

**Borrow check needed**: MiniMax free float ~30% post-placement; cornerstones (Alibaba, miHoYo, founders) 12-mo voluntary lockup. Short borrow likely available but cost unknown — **verify with prime broker**.

### 12.10 Pre-Mortem (What Makes This Wrong?)
| Risk | Early Warning Signal | Exit Trigger |
|---|---|---|
| Z.AI ARR double-counts on-prem as recurring | H1 results show on-prem revenue non-recurring / lumpy | Cut long if MaaS ARR < US$800M exit-2026 |
| MiniMax M3 Pro / Hailuo 3 surprises on upside | OpenRouter token share stabilises >15%; Coding Plan paid users >50k | Cover short if ARR run-rate > US$800M by Q3 |
| Kimi / DeepSeek list at >US$50B, compress multiples | IPO filings appear; cornerstone anchors announced | Reduce gross if new comp trades <15x ARR |
| US sanctions on Z.AI (distillation probe) | Treasury / Commerce official action | Cut long immediately; pair becomes directional |
| Compute shortage stalls both | Capex guides cut; GPU delivery delays | Reduce both; rotate to cloud/datacenter plays |

---

## 13. Pair-Specific Construction: Z.AI Long / MiniMax Short

### 13.1 Thesis in One Sentence
> **Z.AI's enterprise/on-prem moat and model lead (GLM-5.5) justify a premium multiple; MiniMax's consumer-heavy, low-conversion model and weakening model competitiveness (M3 pricing 1/3 peers) warrant a discount. The ~2x ARR multiple gap (25x vs 11x) should narrow to ~1.5x as H1 results verify Z.AI's stickier revenue and MiniMax's conversion ceiling.**

### 13.2 Key Risk: Correlation Breakdown
| Scenario | Z.AI | MiniMax | Pair P&L |
|---|---|---|---|
| **China AI bull market** (policy + liquidity) | +30% | +40% (high beta) | **-10%** (short loses more) |
| **China AI bear market** (sanctions + macro) | -35% | -50% | **+15%** (short wins) |
| **Z.AI idiosyncratic win** (GLM-5.5 beats K3) | +25% | -10% | **+35%** |
| **MiniMax idiosyncratic win** (Hailuo 3 viral) | -10% | +30% | **-40%** |

**Mitigation**: Cap short leg at 60% of long leg notional; use stop-loss on short at +25% from entry; consider put spread on MiniMax instead of linear short to cap tail risk.

### 13.3 Sizing Framework (Pod-Level)
| Parameter | Value |
|---|---|
| Gross long | 4% NAV |
| Gross short | 2.5% NAV |
| Net long | 1.5% NAV |
| Factor-neutral? | ~Yes (beta ~0.1, growth ~0.2) |
| Max drawdown (99% VaR, 20-day) | ~2.0% NAV |
| Liquidity horizon (90% ADV) | Z.AI: 2 days; MiniMax: 5 days |
| Borrow cost (est.) | Z.AI: N/A; MiniMax: 3–5% p.a. (verify) |

---

## 14. Next Steps (Before Interview)

| Priority | Task | Owner | Deadline |
|---|---|---|---|
| 1 | Run OpenRouter validation: MiniMax vs Z.AI vs Kimi vs DeepSeek token share, realized price/token, retention (Jan–Jul 2026) | You + alt-data | Before interview |
| 2 | Verify MiniMax short borrow availability & cost with prime broker | You | Before interview |
| 3 | Build MiniMax consumer funnel model: MAU → paying users → ARPPU → ARR; stress-test <1% conversion | You | Before interview |
| 4 | Model Z.AI on-prem revenue durability: contract length, renewal rate, gross margin vs MaaS | You | Before interview |
| 5 | Prepare 10-slide pitch deck: Idea → Consensus → Variant → Evidence → Financials → Valuation → Catalyst → Trade → Risk → Pre-mortem | You | 1 week before interview |
| 6 | Practice Q&A: "Why not long Z.AI / short HSTECH?" "What if Kimi lists at US$30B?" "How do you know MiniMax conversion is <1%?" | You | Ongoing |

---

## 15. Appendix: Data Sources & Access

| Source | Access Method | Coverage |
|---|---|---|
| HKEXnews filings | `curl` + titleSearchServlet (see §8) | Official, complete |
| ETNet / AAStocks broker notes | Browser + search (Chinese) | Timely, sell-side |
| Yahoo Finance quoteSummary | `yfinance` / API | Prices, consensus TP |
| OpenRouter | API / dashboard | Token volume, pricing, model share (global, dev-focused) |
| Ramp / credit card alt-data | If available | Consumer SaaS spend, enterprise API spend |
| App Store / Sensor Tower | If available | Consumer app MAU, download, revenue |
| Bloomberg / Terminal | If available | DeepSeek funding, Kimi IPO prep, institutional holdings |

---

## 16. Thesis selection framework — from research to a trade

### 16.1 The central question

The trade should not be framed as "which model is technically best?" The
investable question is:

> **Can the market's assumed ARR be converted into durable revenue, acceptable
> gross economics and eventually cash flow — and which listed company has the
> better quality of growth?**

That creates four linked debates:

1. **ARR definition:** Is the number API/MaaS-only, company-level run-rate or
   a mixture of recurring and lumpy on-premise contracts?
2. **Volume versus price:** Is growth coming from more tokens, higher prices,
   or temporary launch traffic? Does a price increase reduce usage?
3. **Monetisation quality:** Are users paying, are coding/agent plans retained,
   and are enterprise/on-prem contracts recurring and margin-accretive?
4. **Expectation versus valuation:** What must happen by the next catalyst to
   justify the current multiple, and what happens if the company merely grows
   quickly rather than achieving the extreme ARR hurdle?

### 16.2 Candidate trade tree

| Candidate | Why it is interesting | What must be true | Main weakness | Priority |
|---|---|---|---|---|
| **Z.AI long / MiniMax short** | Closest listed pure-play comparison; Z.AI has more disclosed enterprise/on-prem revenue and pricing power, while MiniMax is more consumer-heavy and M3 usage is concentrated | Relative Z.AI usage/monetisation beats MiniMax in at least two of price, retention and enterprise/coding proxies; MiniMax fails its ARR hurdle | Both can rally together in an AI/liquidity bull market; borrow and short squeeze risk | **1** |
| **Long cloud/datacenter / short MiniMax or Z.AI** | Expresses a view that AI demand is real but model-company monetisation and multiples are too aggressive; consistent with the cloud/data-centre preference in the GS framing | Token demand translates into sustained compute demand while model revenue/margins disappoint | Larger factor mismatch; needs Barra and earnings bridge for the infrastructure leg | **2** |
| **MiniMax long / Z.AI short** | Explicit falsification of the initial view; Z.AI's premium is vulnerable if its price hikes hurt volume or on-prem revenue proves lumpy | MiniMax usage, coding/consumer monetisation and product breadth improve; Z.AI fails price elasticity or ARR quality tests | Current evidence does not yet support it; Z.AI enterprise data is more visible | **3 / falsification** |
| **Long one / short HSTECH** | Simple market-beta hedge | Only useful if the thesis is genuinely idiosyncratic after factor neutralisation | Leaves AI/growth/China-tech factor exposure; not a primary pair | **Hedge only** |
| **Kimi or DeepSeek pair** | Important competitive read-through and future public comparables | A listed, borrowable instrument becomes available | Not currently a clean executable hedge; use as watchlist, not core trade | **Watchlist** |

### 16.3 Consensus hurdle rates

The Goldman end-2026 ARR figures translate into very demanding exit monthly
run-rates:

| Company | GS end-2026 ARR | Implied exit MRR | Latest disclosed/reference ARR | Growth hurdle to exit |
|---|---:|---:|---:|---:|
| Z.AI | US$2.5B | US$208M/month | US$250M MaaS/API ARR in Mar-2026; scope differs from company-level GS number | ~10x from the Mar MaaS reference, before reconciling scope |
| MiniMax | US$1.0B | US$83M/month | >US$150M company ARR in Feb-2026 | ~6.7x from the Feb reference |

These are **hurdle rates**, not forecasts. We should not call a company a
miss merely because OpenRouter usage does not equal reported revenue: OpenRouter
is global developer traffic and does not observe domestic channels, consumer
subscriptions or on-prem deployments. It is useful for testing the direction,
breadth and persistence of the API/developer component.

### 16.4 Decision gates before selecting the final pair

#### Gate 1 — Absolute ARR plausibility

For each company, build an explicit bridge:

`tokens × realized price/token → API revenue`

`consumer MAU × paid conversion × ARPPU → consumer revenue`

`enterprise customers × contract value × renewal/recognition factor → on-prem/agent revenue`

Then compare the implied run-rate with the broker target and identify the gap.
The output must show base, upside and downside assumptions rather than one
point estimate.

#### Gate 2 — Relative quality of growth

Use the same definitions for both names:

- token share and 7/30-day momentum;
- flagship-model retention after launch;
- programming/coding share;
- realized price proxy and token response to price changes;
- concentration in one model or one task category;
- evidence of broadening beyond the flagship;
- public evidence on paid users, enterprise customers and contract quality.

The pair is only defensible if the relative conclusion survives both raw
volume and normalized/share-based comparisons.

#### Gate 3 — Tradeability and risk

Before calling it a trade, verify:

- borrow availability, annualized borrow fee and recall risk;
- average daily value traded and liquidation horizon;
- beta, country, industry, growth, momentum and volatility exposures;
- event gaps around model launches, placements and policy headlines;
- stop/reduce conditions tied to operating KPIs, not only a share-price stop.

### 16.5 Preliminary OpenRouter read — hypothesis only

The official daily model-ranking dataset covers 2026-06-13 through 2026-08-05
with one observation per day. Comparing the latest seven complete days with the
preceding seven days, token share within the official ranked sample moved as
follows:

| Provider | Change in sample token share (pp) | Interpretation |
|---|---:|---|
| DeepSeek | **+4.5** | Strongest positive rotation in the sample |
| Tencent | +0.4 | Slight improvement |
| Z.AI | **-0.8** | Mild relative deterioration |
| MiniMax | **-0.3** | Mild relative deterioration |
| Kimi | -0.3 | Roughly stable to slightly weaker |
| Qwen | -0.4 | Weaker in this sample |
| Xiaomi | **-8.5** | Large reversal from an unusually strong prior week |

Flagship-model daily token averages also require caution because 2026-08-05 is
the last complete observation and model launches create short histories. The
initial read is directionally consistent with a **relative-quality test of
Z.AI versus MiniMax**, but it does not yet prove a short thesis. The next
checks are price elasticity, programming/coding share, retention after the
launch window and whether the model-level result is robust to the official
"Other" bucket.

Data-quality note: the current OpenRouter legacy/provider activity tables have
good recent daily continuity, but they are top-model/provider activity views,
not a census of all China traffic. The official reconciliation shows roughly
86–91% provider coverage of official daily ranked tokens in the recent window;
the residual and the separate "Other" bucket must stay visible in every chart.
The duplicate `:batch` MiniMax model variant in the legacy activity table is
deduplicated by base model before any share calculation.

#### Coding and agent breadth proxy

The official task-model dataset provides a stronger developer-use case proxy
than the older programming-ranking table. It has daily 7-day-window snapshots
from 2026-07-17 through 2026-08-05, with nine `code:*` task tags and five
`agent:*` tags. On the latest snapshot:

| Metric | Z.AI | MiniMax | What it says |
|---|---:|---:|---|
| Code-task tag coverage | 9/9 | 1/9 | Z.AI has materially broader presence across code workflows |
| Average code-task rank | 4.1 | 10.0 | MiniMax appears only at the edge of the ranked set |
| Average within-task token share | 6.9% | 4.4% | Z.AI has higher share where it appears |
| Agent-task tag coverage | 4/5 | 1/5 | Z.AI is also broader in the agent sample |
| Average agent-task rank | 6.5 | 10.0 | MiniMax is not yet a leading agent model in this sample |

Across the latest seven daily snapshots, Z.AI remained present in all nine
code tags with average within-task token share of about 6.3%; MiniMax appeared
in about 4.3 of the nine tags on average with about 3.6% share and no top-three
placements in the aggregate. This is supportive evidence for a **Z.AI quality
and developer-breadth advantage**, not proof of Coding Plan revenue: the
measure is a within-task share among ranked models, uses equal weighting across
tags, is global OpenRouter traffic and does not reveal paid conversion,
retention or domestic usage.

#### List-price versus demand grid

The latest official benchmark snapshot also gives a useful starting grid for
the price-elasticity test. These are public list prices in the benchmark feed,
shown as US dollars per one million input/output tokens; they are **not** the
companies' realized blended prices.

| Model | Input | Output | Latest official ranked-sample token share |
|---|---:|---:|---:|
| GLM-5.2 | US$1.40 | US$4.40 | ~5.3% on 2026-08-05 |
| MiniMax M3 | US$0.30 | US$1.20 | ~2.5% on 2026-08-05 |
| Kimi K3 | US$4.50 | US$22.50 | ~2.0% on 2026-08-05 |
| DeepSeek V4 Flash 0731 | US$0.139 | US$0.278 | ~11.7% on 2026-08-05 |
| Xiaomi MiMo V2.5 | US$0.112 | US$0.224 | ~8.0% on 2026-08-05 |

The immediate test is not simply "is GLM expensive?" It is whether GLM-5.2
can retain or grow token share after controlling for task mix, launch age,
reasoning mode and availability. A premium with stable share supports a
pricing-power thesis; a premium with persistent share loss supports a
commodity/competition thesis. The current snapshot is a starting observation,
not an elasticity estimate.

### 16.6 Working decision rule

Keep **Z.AI long / MiniMax short** as the lead candidate only if all of the
following hold:

1. Z.AI wins at least two of three relative tests: usage persistence, pricing
   power/elasticity and monetisation quality;
2. MiniMax's implied API plus consumer funnel cannot support the US$1.0B exit
   ARR without an aggressive, clearly identified assumption;
3. the pair remains manageable after borrow, liquidity and Barra-style factor
   checks.

If both names fail the absolute ARR bridge while token demand and compute
capex remain strong, switch to **long infrastructure / short the weaker
model-company expression**. If MiniMax wins the relative tests and Z.AI's price
hikes cause persistent volume loss, the correct action is to reverse the pair
—or reject the initial thesis—not rationalize it.

The final interview pitch should therefore present the lead pair, one explicit
reverse-pair falsification and one sector-expression alternative. This shows
trade selection discipline rather than attachment to the first two names
tracked.

### 16.7 Local evidence used for this section

- `data/normalized/openrouter_official/official_model_rankings_daily.parquet`
- `data/normalized/openrouter_official/official_legacy_reconciliation.parquet`
- `data/normalized/openrouter_official/official_task_models.parquet`
- `data/normalized/openrouter_official/official_benchmarks.parquet`
- `data/normalized/openrouter/provider_daily_activity.parquet`
- Broker/financial expectations summarized in §§2–6 of this note

*End of research note. Update live as new data arrives.*
