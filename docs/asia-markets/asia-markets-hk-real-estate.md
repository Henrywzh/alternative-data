# Hong Kong Real Estate — Operational Tracking Stack (SHKP as reference case)

Companion to [asia-markets-hk-sectors.md](asia-markets-hk-sectors.md) and
[asia-markets-hk-alt-data-sources.md](asia-markets-hk-alt-data-sources.md).
Current top priority in the [focus list](asia-markets-hk-focus-list.md).
This is a folded/summarized version of ten research rounds — narrative
"here's what I checked" framing has been cut; what remains is the current
state of knowledge and what's still open. Status: **research-first, with
Tranche 1 Centaline ingestion now implemented and validated; no new series is
promoted to the dashboard until its contract gate passes.**

akshare's Hong Kong macro functions (`macro_china_hk_cpi`, `_gbp` [GDP],
`_rate_of_unemployment`, `_ppi`, `_building_amount`, `_trade_diff_ratio`,
and the bonus daily **HIBOR curve** via `macro_china_hk_market_info`) are
free, verified, and directly relevant here — see
[asia-markets-hk-akshare-capabilities.md](asia-markets-hk-akshare-capabilities.md).

---

## 1. The verified data stack

### Official sources (system of record)
| Source | What it gives you | Key caveat |
|---|---|---|
| [RVD property-market statistics](https://www.rvd.gov.hk/en/publications/property_market_statistics.html) | Official monthly sale/rental/transaction series by class/district since 1979/1982; annual stock/vacancy/take-up | **Recent months are provisional and revise.** A four-series vintage test (May 2025) found small downward revisions (-0.03% to -0.5%) that took 3–4 monthly releases to finalize. First-release lag ~26 days (domestic), ~37 days (office). File/API ingestion with saved release vintages, not a scraper |
| [SRPE](https://www.srpe.gov.hk/) (Sales of First-hand Residential Properties) | Statutory sales brochures, price lists/revisions, sales arrangements, transaction registers for every covered project | Official project-level PDF library, **not a universal API** — no official real-time unsold-inventory field. A 3-project audit found totals reconcile against 28Hse portal figures, but current documents alone can't fully reconstruct historical unit-by-unit states — need continued snapshots |
| [Housing Bureau private supply](https://www.hb.gov.hk/eng/publications/housing/private/pshpm/index.html) | Quarterly market-wide 3-part snapshot: completed-unsold, under-construction (net of presale), disposed-not-started; ~105,000 units total as of end-Mar 2025; historical PDFs to 2004 | Market-wide only, not developer-level, not RVD vacancy |
| [Land Registry monthly statistics](https://www.landreg.gov.hk/en/monthly/monthly.htm) | Deeds/ASP received for registration, by market/price-band/region | Receipt month ≠ signing month — official sample shows ASP-signing-to-submission averages ~16 days. IRIS (paid interactive search) is restricted to qualifying institutions, not a public pipeline |
| [Buildings Department monthly digests](https://www.bd.gov.hk/en/whats-new/monthly-digests/index.html) | Plan approval, consent-to-commence, actual-commencement, occupation-permit events | Consent ≠ actual start; OP ≠ handover/sale |
| [HKMA Residential Mortgage Survey](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/banking/residential-mortgage-survey/) | Applications/approvals/undrawn/drawdowns, HK$ value + count, primary vs. secondary. May 2026: HK$40.2bn approved (+10.1% m/m), split HK$11.7bn primary/HK$23.8bn secondary | Leading indicator, but approval → drawdown is not guaranteed; treat as separate pipeline stages |
| [Lands Department land-sale records](https://www.landsd.gov.hk/en/resources/land-info-stat/land-sale/land-sale-records.html) | Land-bank appetite: tender results, lease modifications, land exchanges | Modification/exchange publication can lag the actual premium agreement |

### Private benchmarks — same-family sources, don't double-count
| Source | Distinct value | Classification |
|---|---|---|
| Centaline **CCL** | Weekly (Fridays 4pm), provisional-agreement based | Fast, private |
| Centaline **CCI** | Monthly, Land Registry-based | Slow, official-linked — **CCI and CCL are different event layers from one compiler, not two independent votes** |
| Centaline **CRI** (rental) | Monthly (confirmed — not weekly like CCL) | Non-price signal, distinct product |
| Midland **MHPI** | Weekly, district sub-indices (HK Island/Kowloon/NT), ~129 pts | Independent of Centaline |
| Midland **Confidence Index (MCI)** | Sentiment survey, not price-derived | Non-price signal |
| **28Hse EPI/ERI** | Weekly hedonic sale (EPI) **and rental (ERI)** indices, 148 estates, since 2016-01 | Fills the weekly-rental gap CRI doesn't; mixed upstream lineage (Land Registry + agency + SRPA), no published revision policy |
| Top-10-estates weekend transaction count (Centaline/Midland) | Weekly **volume**, not price — complements CCL/MHPI | Reported via HK financial media |
| MacroMicro / ETNet | Charting only | **Presentation layer, not an independent observation** — trace back to the real upstream source |

### Property portals — checked directly, tiered by access
| Tier | Sites | Notes |
|---|---|---|
| Workable | 28Hse, Squarefoot | `robots.txt` fully open (`Allow: /`); 28Hse has an explicit EPI historical-download surface |
| Workable with limits | Spacious.hk | Listing pages allowed; 100-page pagination cap, 60s crawl-delay for known scraper bots |
| Blocks API/search paths | Centaline, House730, Ricacorp | Confirmed blocked at the robots.txt level — do not bypass |
| Downgrade — lineage undisclosed | House730, Property.hk | No record-level source label found; treat any "deal" as `unknown` provenance, not registered |
| New-project nowcast (28Hse) | `total/remaining/on-sale/sold` fields | Platform nowcast only — sold-source and cancellation treatment undocumented; **3-project audit found totals matched SRPE but unit-level states weren't independently verifiable** |

**`robots.txt` is a technical crawl signal, not a licence** — it doesn't
substitute for checking site terms, copyright/database rights, or rate
limits. This applies to every portal above.

### Commercial / office / REITs
Every residential source above is residential-only. HK REITs fill the
office/retail gap and disclose (not scraped) at every earnings release:
| REIT | Ticker | Verified figures |
|---|---|---|
| Link REIT | 0823.HK | 97.6% occupancy, mid-to-high single-digit reversion (everyday retail) |
| Champion REIT | 2778.HK | Occupancy fell 82.6%→81.6%, WAULT 2.4yr, **passing rent -15% YoY to HK$73.7/sqft** — concrete evidence of Grade-A office stress |
| Fortune REIT | 0778.HK | 95.8% occupancy, negative reversion concentrated in supermarket tenants |
| Prosperity REIT | 0808.HK | Smaller, less disclosed |

Market-wide complement: **JLL's free newsroom press releases** (not the
paywalled full report) give city-wide Grade-A office vacancy monthly —
13.1% overall mid-2026, Central down to 8.8% (43-month low, IPO-pipeline
driven), Kowloon East/HK East still rising. CBRE/Colliers/Cushman &
Wakefield presumably publish similarly — not individually checked.

### Policy catalysts
- **Stamp duty deregulation, Feb 28 2024** (verified, major): all
  demand-side cooling measures (BSD 7.5%, NRSD 7.5%, SSD up to 20%)
  abolished in one move. Only standard AVD (≤4.25%) remains — arguably the
  single biggest HK property policy event in recent years.
- **HKMA countercyclical LTV/DSR — a standing, periodically-adjusted lever,
  not a one-off**: Oct 2024 reverted max LTV to a flat 70% (pre-2009
  baseline); Dec 2024 cut the Countercyclical Capital Buffer 1%→0.5%.
  Monitor HKMA press releases for the *next* adjustment.
- **HIBOR vs. Prime mortgage spread**: H-Plan (HIBOR+~1.3%) vs. P-Plan
  (Prime−~2.5%). As of March 2026, 1M HIBOR 2.05%, Prime 5.375% — P-Plan
  cheaper since HIBOR fell off its 2023–24 peak. Spread direction is a
  real, trackable affordability signal.

### Demand-side / demographic
- **Population/migration**: Top Talent Pass Scheme + QMAS approval stats
  on data.gov.hk are **annual only** (116k+ TTPS applications by end-2024,
  92k approved). Higher-frequency proxy: HK Immigration's **daily**
  cross-boundary passenger traffic dataset (`hk-immd-set5`) — use as a
  nowcast/interpolation signal against the annual base rate, not a direct
  substitute.

### Cadence map
| Frequency | Source |
|---|---|
| Quasi-real-time / statutory delay | SRPE registers (PASP within 24h, ASP/termination ~1 working day); portal nowcasts unverified |
| Daily | HIBOR fixing; HK Immigration daily passenger traffic (proxy only) |
| Weekly | CCL, MHPI, 28Hse EPI/ERI, top-10-estates weekend transaction count |
| Monthly | RVD (provisional), CRI, HKMA mortgage survey, Land Registry receipts, Buildings Dept events, JLL market dynamics |
| Quarterly | Housing Bureau supply snapshot, REIT occupancy/reversion (often semi-annual in practice) |
| Event-driven | Lands Dept tenders, stamp duty changes, HKMA LTV/DSR adjustments |
| Semi-annual | SHKP's own land-bank disclosure |
| Annual | RVD stock/vacancy/take-up, TTPS/QMAS, Housing Landscape Navigator |

---

## 2. Stock universe (initial exposure screen, not exhaustive)

**Core HK developers/landlords:** Sun Hung Kai (0016), MTR property segment
(0066), Henderson Land (0012), CK Asset (1113), Wharf Holdings (0004),
Wharf REIC (1997), Swire Properties (1972), Sino Land (0083), New World
Development (0017), Hysan (0014), Hang Lung Properties/Group (0101/0010),
Kerry Properties (0683), Great Eagle (0041), Miramar (0071), K. Wah Intl
(0173), Kowloon Development (0034), Far East Consortium (0035), HKR
International (0480), Soundwill (0878), Wing Tai Properties (0369), Lai
Sun Development (0488), Chinese Estates (0127), Emperor International
(0163), Hongkong Chinese (0655), Tai Cheung (0088), Hong Kong Ferry (0050,
**Henderson is the substantial shareholder, not Wheelock**), Liu Chong
Hing (0194), Chuang's Consortium/China (0367/0298), Century City Intl
(0355, **not 0105**), Associated International Hotels (0105, iSQUARE —
separate from Century City).

**REITs/agency:** Link (0823), Champion (2778), Fortune (0778), Prosperity
(0808), Regal REIT (1881), Langham Hospitality Trust (1270, Great
Eagle-controlled — don't double-count with 0041), Sunlight REIT (0435), SF
REIT (2191, **mixed geography** — Tsing Yi + Changsha/Foshan/Wuhu, not
pure HK), Midland Holdings (1200, agency commission exposure, not property
ownership).

**Corporate-family dedup (don't treat parent + operating layer as
independent observations):** Henderson↔0050↔0071↔0435; Hang Lung
0010↔0101 (use 0101 for operating exposure); Sino 0247 (parent, holds
majority of 0083 — don't include both); Great Eagle 0041↔2778↔1270;
Wharf 1997↔0051 (Harbour Centre, majority-owned); Century City chain
0355→0617 (Paliburg)→0078 (Regal Hotels)→1881 (Regal REIT), plus 0120
(Cosmopolitan, mainland-heavy).

**Listed in HK but not a clean HK-property proxy:** Yuexiu REIT (0405),
Spring REIT (1426), CMC REIT (1503) — mainland/overseas assets, shouldn't
be driven by RVD/CCL. Pacific Century Premium Developments (0432), Central
Properties/ex-C C Land (1224), Tian An China (0028), Nanyang Holdings
(0212) — limited/non-dominant HK exposure. The large mainland-developer
bloc listed in HK (CR Land, COLI, Longfor, Vanke, China Jinmao, Greentown,
Yuexiu Property, Seazen, Country Garden, Shenzhen Investment, Poly
Property, plus distressed-era names Sunac/Kaisa/Logan/Agile/Shimao/R&F/
Aoyuan/CIFI/KWG/Yuzhou/Zhongliang/Zhenro/Fantasia/Central China) needs a
**separate mainland-property data stack** — HK listing venue doesn't make
them HK proxies. Mainland proptech (Beike/KE Holdings, Hopefluent,
E-House) belongs with that stack too. Hongkong Land has real HK assets but
is SGX-listed (C07) — comparable, not a constituent.

**Research-first compact set** (vs. the full ~200-name screen): residential
0016/0012/0083/0017/0173 + 0066's property segment; commercial 1997/1972/
0014/0823/0778/2778; agency 1200; mixed-geography cross-check 0683.

---

## 3. Analytical framework — property/project → listed-equity translation

The data stack above describes the *market*; it doesn't by itself say
which listed equity benefits. Key translation rules:

- **Presale ≠ revenue.** Chain is price list → PASP → ASP → construction/
  occupation milestones → handover → accounting recognition. Under HKFRS
  15, HK residential presales are generally recognized **at handover**, not
  contract signing — contracted sales can lead reported revenue/EPS by a
  year or more. Track contract liabilities and expected completion
  schedule separately from SRPE-observed sales pace.
- **Debt/refinancing**: track the 12/24/36-month maturity wall, cash +
  committed undrawn facilities, covenant headroom, fixed/floating mix,
  and HIBOR reset dates — net gearing alone is insufficient. `liquidity
  coverage = (unrestricted cash + undrawn facilities − mandatory
  capex/land/dividends) / next-12m maturities`.
- **Realizable NAV ≠ book NAV.** Build base/stress NAV after JV look-through,
  cap-rate stress, minorities, and disposal costs — a low P/NAV isn't
  automatically cheap; the discount should track leverage, liquidity, and
  governance.
- **Project economics**: model net realized sales (after discounts/
  cancellations) minus land/construction/marketing/financing cost, at
  100% first, then attributable ownership + JV waterfall. GFA and
  saleable area are not interchangeable denominators.
- **Investment-property/hotel cash flow**: track NPI/NOI, physical vs.
  committed occupancy, passing vs. market rent, WALE — occupancy and
  reversion can move in *opposite* directions since market rent only
  affects expiring leases. RVD gives the market anchor; company
  disclosures give actual cash flow.
- **Equity/positioning signals**: Southbound flow is marginal demand, not
  fundamental improvement. HKEX short-selling data is turnover/flow, not
  "short interest." Options OI has no inherent direction without
  liquidity context. DI filings/buybacks/placements need filing-time (not
  transaction-time) stamps for any backtest.
- **Unified event pipeline** (cross-sector, not real-estate-specific): one
  HKEXnews announcement can generate results + dividend + operating-KPI +
  financing events simultaneously — model as raw-document → normalized
  event(s), never overwrite a correction/supplement, keep both versions.

---

## 4. Empirical pilot results (what's actually been tested)

- **RVD vintage test** (4 series, May 2025, consecutive releases): all
  four revised down slightly (-0.03% to -0.5%), finalized after 3–4
  releases; too small a sample to claim a general bias, but sufficient to
  reject treating today's CSV as historically known at the time.
- **3-project SRPE/28Hse audit** (YOHO WEST PARKSIDE, Belgravia Place
  Phase 2, DEEP WATER PAVILIA/THE SOUTHSIDE): unit totals matched between
  SRPE and 28Hse in all three cases, but sold/remaining/on-sale states
  could not be fully independently verified — one case had an unresolved
  price-list-version discrepancy (28Hse referenced 3H, official directory
  only showed through 3G/4G).
- **14-company exposure pass**: economic categories mapped (residential
  development vs. commercial landlord vs. agency vs. mixed) with
  appropriate external evidence per category — see the stock universe
  section above for the grouping.

### Evidence-gate status
| Gate | Status |
|---|---|
| RVD release-vintage revisions | Pilot complete for 4 series/1 month — broaden before generalizing |
| SRPE identifiers/version behaviour | Partially complete — phase/SPV/version issues surfaced, full as-of reconstruction still fails |
| SRPE vs. 28Hse inventory reconciliation | Partially complete — totals match, unit-level states unverified |
| Agency deal → Land Registry follow-up (14–45 day window) | **Not started** |
| Corporate-family deduplication | Initial pass complete (see section 2) |
| Commercial KPI definition matching (company vs. RVD/JLL concepts) | **Not started** |
| HKEX event publication/effective-time audit | **Not started** |

---

## 5. Next workstreams (prioritized by effort vs. information value)

Research/recommendation briefs only — none of these are authorized for
scraping, automation, or model-building yet.

| Priority | Workstream | Objective |
|---|---|---|
| A — low-effort market pulse | CCL/EPI/ERI ingestion; agency realtime transaction pages; 28Hse new-project nowcast | Cheap, higher-frequency monitoring layer |
| B — official benchmark | RVD vintage-aware ingestion; Land Registry aggregate | Point-in-time official truth, validates private feeds |
| C — project→stock attribution | SRPE document pipeline; Buildings Dept event timeline | Connect launch/sale/construction/completion to listed companies |

Each still needs: source-access/terms confirmation, a stable-identifier
proposal (legal phase/SPV, not marketing name), and a small validation
pilot before any schema or automation decision.

### Discovery TODO — low-effort private benchmarks and missing market layers

These items are **not yet implemented**. They are deliberately ordered as
source-contract work before ingestion, model or dashboard work.

| Order | Source family | Intended use | Validation / implementation plan | Do not infer |
|---|---|---|---|---|
| P0 | Centaline CCI, CRI and CSI APIs | Monthly price cross-check, monthly rent/yield, weekly manager sentiment | Preserve sample responses; define series, geography, index base, publication lag, revisions and overlap with CCL/RVD/ERI. Then add normalized history and source-owned tests. | CCI is not a longer-history replacement for CCL; CRI is not the first rental series; CSI is survey sentiment, not transaction data. |
| P0 | Centaline CVI API + first-party methodology | Potential valuation/credit-condition signal | Verify its published construction and whether it genuinely represents bank valuation before any chart. | That a CVI move equals a bank credit-policy change or mortgage valuation. |
| P1 | Midland `mrIndex` and `economicIndicators` | Monthly price-volume, affordability and macro context | Validate field units, segment definitions, release/revision behaviour and provenance; cross-check official fields against HKMA/C&SD. | That a Midland-derived affordability or ratio field is an official statistic. |
| P2 | Midland `marketStat*`, district statistics and `langRegRecords` | Rolling-market/district snapshots | Persist as-of snapshots before calculating trends; document every window and previous-period comparator. | MoM/YoY from a one-off rolling-window response. |
| P2 | RVD office/retail rent, vacancy and completion data | Commercial landlord / REIT market anchor | Build a separate commercial contract and reconcile terms with company occupancy, passing rent and reversion disclosures. | That RVD rent, occupancy and company-reported KPIs share a definition. |
| P2 | Policy-event layer | Chart annotations and catalyst monitoring | Use `propertyEvent` only to discover events; cite and timestamp HKMA/Government/Lands primary releases. | Completeness or legal effect from an agency event list alone. |
| P3 | Market-to-equity transmission | Explain stock earnings / valuation channels | Join SRPE, mortgage/supply, completion, corporate disclosures and the financial-data sibling only after issuer/project identifiers and point-in-time availability rules are defined. | That presales equal revenue, or that market price indices alone explain a developer's earnings. |

### Proposed ingestion order — planning only

The unit of work below is a source-owned ingestion contract, not “add every
field visible in a response.” Each completed tranche must write immutable raw
payloads and a run manifest before the next tranche begins. No dashboard chart
is part of the tranche exit gate unless stated explicitly.

#### Tranche 0 — shared contract harness (first)

1. Extend the existing real-estate storage/run-manifest pattern for the new
   source families: `source_url`, `fetched_at`, raw payload hash, parser
   version, source observation period, and a `data_status` of `live`,
   `stale`, `incomplete` or `research_only`.
2. Add fixture-based tests for parser shape and one generic dated-series gate:
   non-null date/value, uniqueness at the declared series grain, bounded
   numeric values, explicit cadence, and latest-observation age.
3. Declare a separate normalized dataset for every distinct grain. Never put
   weekly CCL/CSI, monthly CCI/CRI/MHPI, rolling-window snapshots and event
   records in one “market data” table.

**Exit:** a failed fetch or parser cannot overwrite the last validated
normalized run, and every successful run has raw lineage.

#### Tranche 1 — Centaline structured indices: CRI, CSI, then CCI

| Dataset | Endpoint | Proposed normalized grain | Required fields / gates |
|---|---|---|---|
| `centaline_cri_monthly` | `/CCI/api/Index/CRI` | one `observation_date × series_id` | index level, regional/size split, rental-yield flag/value where supplied, source period, series label; monthly uniqueness, positive index/yield, lag/freshness check. |
| `centaline_csi_weekly` | `/CCI/api/Index/CSI` | one `observation_date × sector × measure` | residential/office/industrial/retail price and rent sentiment fields, published week, label; weekly uniqueness and a documented survey-scale/range. |
| `centaline_cci_monthly` | `/CCI/api/Index/CCI` | one `observation_date × series_id` | overall and documented regional/size splits, level, source period; monthly uniqueness and comparison-only caveat versus CCL. |

Plan: capture two raw payloads on different publication dates before
normalizing, so field stability and revision behaviour are observed rather
than assumed. Backfill the history only after the parser fixture passes. Keep
CRI/yield, CSI and CCI in separate datasets, then expose only their source
health initially. Add charts after a manual overlap check against RVD/ERI/CCL.

**Do not ingest CVI in this tranche.** First store a methodology note sourced
from Centaline; if its construction cannot be stated precisely, its endpoint
remains `research_only` even if it is technically fetchable.

#### Tranche 2 — Midland monthly price-volume and macro context

Use the same Market Insight page acquisition as the existing weekly Midland
pipeline, but save the complete versioned `__NEXT_DATA__` payload once per run
before extracting either family. Midland's WAF constraint in CI means initial
validation and scheduling must be local/residential-IP compatible; CI should
consume only successfully materialised normalized output.

| Dataset | Payload block | Proposed grain | Required checks |
|---|---|---|---|
| `midland_mhpi_monthly` | `mrIndex` | `month × region/overall` | index, `net_ft_price`, all transaction-count fields retained separately; one row per declared segment/month; units are documented in the persisted `midland_field_dictionary`. |
| `midland_economic_indicators_monthly` | `economicIndicators` | `month × indicator_name` | numeric value, unit, Midland field name and source attribution; preserve raw field name; do not relabel as official without reconciliation. |

Plan: first build a field dictionary from a frozen payload; then normalize all
observations without deriving ratios. Reconcile mortgage rate and unemployment
against HKMA/C&SD for a short overlap; label non-reconcilable affordability
metrics “Midland-derived.” Only then add monthly price-volume or affordability
views. `mrIndexWeekly` remains a separate existing contract.

#### Tranche 3 — official commercial market series

1. Fetch the configured RVD office-rental (`2.3M.csv`) and retail-rental
   (`3.2M.csv`) files as separate raw snapshots, preserving any provisional
   flags/release date exactly as with residential RVD.
2. Discover and separately contract RVD vacancy/completion files; do not
   assume their period, stock universe or unit from a filename.
3. Normalize to `rvd_office_rental_index_monthly`,
   `rvd_retail_rental_index_monthly`, and (only after definition review)
   `rvd_commercial_vacancy_*` / `rvd_commercial_completion_*`.
4. Run a small reconciliation notebook against a disclosed office/retail REIT
   period. The expected result is a definition map, not numerical equality.

**Exit:** every displayed commercial metric states market, class, unit,
observation period and provisional/revision status.

#### Tranche 4 — rolling Midland market snapshots

For `marketStatDistrict`, `marketStatAll`, `marketStatRegion` and
`langRegRecords`, save the complete response daily with both `fetched_at` and
the source's own as-of/window fields. Normalize into snapshot tables keyed by
`snapshot_date × geography × metric`; retain `window_start`, `window_end`,
`as_of_date`, `update_date` and `previous_window_*` fields when provided.
Market and registration metrics carry explicit units and source-field names.
Operate for a minimum 90 calendar
days before considering a trend chart. Until then, allow only an explicitly
dated snapshot card/table.

#### Tranche 5 — policy events and market-to-equity joins

`propertyEvent` is discovery input only. Ingest no event until a primary
HKMA/Government/Lands source supplies the publication time, effective date,
policy channel and URL. In parallel, define (but do not yet automate) the
join registry for issuer, legal project phase/SPV, attributable ownership,
asset type and availability time. That registry is the prerequisite for SRPE,
supply, mortgage, HKEX and financial-data facts to become an equity-facing
dataset.

### Promotion rule

A tranche may be promoted from `research_only` to a dashboard source only when
it has: (1) two successful raw captures or an archived history with known
vintage semantics, (2) a tested normalized schema, (3) period/freshness and
revision rules, (4) a documented unit and interpretation caveat, and (5) a
small visual/record-count QA in both dashboard languages.

## Open questions
- Complete the three not-started evidence gates above.
- Quantify RVD provisional revisions across more periods (only 1 month tested so far).
- Run the 14–45 day agency-deal-to-registration follow-up.
- Whether CBRE/Colliers/Cushman & Wakefield match JLL's free-monthly vacancy pattern — not checked.
- Portal terms/rate-limit review remains mandatory before any automation, regardless of what `robots.txt` allows.
