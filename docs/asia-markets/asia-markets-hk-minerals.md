# Hong Kong-listed Mineral / Mining Stocks — beyond gold

Companion to [asia-markets-hk-sectors.md](asia-markets-hk-sectors.md) and
[asia-markets-hk-alt-data-sources.md](asia-markets-hk-alt-data-sources.md).
**Status: ON HOLD** per the [focus list](asia-markets-hk-focus-list.md) —
there's already a working pipeline for critical-minerals tracking in this
repo (`src/minerals_signal_data/`), so this sector isn't being actively
built right now. Notes below are kept for when it comes back into focus.

The companion alt-data-sources doc's Materials section already covers
SHFE/LME inventories and SMM's free weekly social-inventory flashes
(verified — real tonnage figures for copper/aluminum). This adds
mining-stock-specific angles: gold demand-side data, and each miner's own
production disclosures.

*Key names: Zijin Mining (2899.HK), Zijin Gold International (2259.HK),
Shandong Gold (1787.HK), CMOC (3993.HK), China Hongqiao (1378.HK), Ganfeng
Lithium (1772.HK)*

| Source | What it is | Signal | Access |
|---|---|---|---|
| **HK Census & Statistics Dept — gold trade statistics** | Monthly China gold import/export volumes *through Hong Kong* (HK is a major physical gold trading conduit) | A well-known macro proxy for Chinese gold demand — directly relevant to Zijin/Shandong Gold's pricing environment, and to Laopu Gold/Chow Tai Fook's input costs (see the consumer-trend-stocks doc) | **Verified real & free** — published monthly, also mirrored on CEIC |
| **Company quarterly/interim production reports** (e.g. Zijin's own IR announcements) | Actual tonnes mined, by metal, ahead of full financials — e.g. Zijin's 2025 results disclosed 90 tonnes mined gold (+23% YoY), 1.09m tonnes mined copper, plus explicit next-year guidance (105t gold, 1.2m t copper, 120,000t LCE, 520t silver for 2026) | This is more granular and forward-looking (explicit guidance) than anything a price/inventory tracker gives you | **Verified real & free** — published on `zijinmining.com/news` and via HKEX announcements; likely similarly detailed for other large HK-listed miners, worth checking each company's own IR page |
| **China Gold Association** monthly domestic production data | National gold output stats | Sector-wide production context | Public, Chinese-language |
| **Rare-earth/lithium export quota & customs data** | Covered in the alt-data-sources doc's Round 3 section | Supply-chain signal for Ganfeng/CMOC | Free, GACC |
| USGS Mineral Commodity Summaries | Annual global reserve/production context by mineral | Background/benchmarking, not a trading signal | Free, annual |

**Why the gold trade stat matters specifically:** it's a genuinely
distinctive HK angle — because Hong Kong is a physical bullion trading hub,
its customs data captures Chinese gold demand at a finer, more real-time
grain than most macro gold-demand proxies, and it touches both the miners
(Zijin, Shandong Gold — supply side) and the jewelry retailers (Laopu,
Chow Tai Fook — demand/input-cost side) in one dataset.

## What this repo already has (why it's on hold)

`src/minerals_signal_data/` already tracks the **USGS critical minerals
list**:
- **22 minerals already tracked live** (aluminum, antimony, cobalt,
  copper, gallium, germanium, graphite, indium, lead, lithium, manganese,
  neodymium, nickel, palladium, platinum, silicon, silver, tantalum, tin,
  uranium + 2 more) via yfinance futures, FRED series, or investing.com,
  most already surfaced in the live dashboard (`dashboard/sections/minerals.py`)
- **19 more on ETF-style proxies** — including tungsten and most rare-earth
  oxides (cerium, dysprosium, europium, lanthanum, praseodymium, samarium,
  terbium, yttrium, etc.) via instruments like `REMX`
- **19 flagged paywalled/impractical** (arsenic, beryllium, hafnium,
  rhodium, titanium, zirconium, etc.) — the known, already-mapped gap
- A dedicated `chinatungsten_scraper.py` pulling tungsten/molybdenum/
  rare-earth prices directly from news.chinatungsten.com — **this is
  almost certainly the "half ready" part**: it exists and runs, but rare-earth
  extraction is explicitly thin/text-only (no OCR yet per its own docstring),
  and its output doesn't yet look fully merged into the tracked/proxy split
  above (tungsten still shows as `proxy_index`, not `already_tracked`,
  despite having a dedicated direct-scrape source).

**Why this reframing matters:** gallium, germanium, antimony, and rare
earths are exactly the minerals China has put **export controls** on since
2023 — this isn't generic commodity tracking, it's tracking a
geopolitically live category with real policy-catalyst risk, which is a
much stronger edge story than base-metals inventory data.

## Next steps (when this comes off hold)
1. Finish wiring `chinatungsten_scraper.py`'s tungsten/moly/rare-earth
   output into the main tracked bucket (sounds like the concrete "finish
   the half" task).
2. Add a China export-control/customs-announcement policy layer for
   gallium/germanium/antimony/rare earths specifically — same
   policy-catalyst pattern already built for crypto (HKMA/SFC) and
   aerospace (Government Work Report/CNSA) — MOFCOM export-control
   announcements would be the equivalent source here, not yet verified.
3. Map which HK-listed miners actually have direct exposure to *these
   specific* critical minerals (as opposed to the copper/gold names
   already covered in the main Materials sector doc) — not yet done; the
   HSCI Materials list so far only confirms copper/gold/aluminum/lithium
   names (Zijin, CMOC, Hongqiao, Ganfeng), not gallium/germanium/rare-earth
   pure-plays specifically.
4. Zijin's production-report cadence/format was confirmed for Zijin
   specifically; whether Shandong Gold, CMOC, and Ganfeng disclose at the
   same granularity hasn't been checked individually.
