# Hong Kong Stock Market — Sector & Company Map

Research note, part of a broader look at major sectors and free/alternative-data
opportunities across Asian equity markets (HK first, then South Korea, Japan,
Taiwan, China). This pass covers HK only: sectors, representative companies,
and market caps.

**Primary source found:** an existing internal dataset at
`~/Desktop/Quant/Research/data/processed/hsci_*.csv` (built for the factor
research in `Research/experiments/factor_model/04_hsci_signals_sweep.ipynb`,
write-up in `Research/experiments/factor_model/summary/04_hsci_factor_analysis.md`).
It covers the full **HSCI (Hang Seng Composite Index)** universe — ~508
constituents, i.e. the broad HK-listed universe, not just the 80-odd HSI
blue chips — with an official HSI industry classification
(`hsci_components.csv`, snapshot dated 2026-01-16) and a computed market-cap
time series (`hsci_mkt_cp.csv`, HKD, through 2026-01-14). This is
meaningfully better than scraping public trackers: one consistent
methodology, official sector tags, and full universe breadth. Figures below
are pulled directly from that dataset (~6 months stale vs. today, but
internally consistent) and converted to USD at ~7.8 HKD/USD.

## Market structure notes

HKEX listings are a mix of three blocs, which matters because a lot of the
biggest weights are effectively mainland China exposure booked through HK:

- **HK Ordinary shares** — locally incorporated (HSBC, AIA, Sun Hung Kai
  Properties, CK Hutchison, CLP, MTR, Galaxy Entertainment).
- **H-shares** — mainland-incorporated state-linked companies listed in HK
  (ICBC, China Construction Bank, PetroChina, Sinopec, China Life, China
  Mobile).
- **Red chips / mainland private tech** — mainland private-sector companies
  primarily or dually listed in HK (Tencent, Alibaba, Xiaomi, Meituan, BYD,
  CATL, NetEase, Baidu, SMIC).

## Sector breakdown (HSCI universe, official HSI industry classification)

Sector total = sum of market cap across all covered HSCI names in that
sector (not just the ones listed below — only top names shown per sector).
`n` = number of HSCI constituents tagged to that sector.

### 1. Financials — sector total ~$3,128B (n=48)
| Company | Ticker | Market Cap (USD bn) |
|---|---|---|
| ICBC (Industrial and Commercial Bank of China) | 1398.HK | 363.8 |
| HSBC Holdings | 0005.HK | 283.7 |
| Agricultural Bank of China | 1288.HK | 283.4 |
| China Construction Bank | 0939.HK | 269.1 |
| China Life Insurance | 2628.HK | 234.5 |
| Bank of China | 3988.HK | 233.9 |
| Ping An Insurance | 2318.HK | 170.5 |
| China Merchants Bank | 3968.HK | 153.6 |
| AIA Group | 1299.HK | 112.1 |
| Hong Kong Exchanges & Clearing (HKEX) | 0388.HK | 71.0 |
| BOC Hong Kong Holdings | 2388.HK | 54.6 |

By far the largest sector — dominated by the "big four" mainland state
banks + China Life + Ping An, with HK-native names (HSBC, AIA, HKEX, BOC HK)
mixed in further down.

### 2. Information Technology — sector total ~$1,248B (n=47)
| Company | Ticker | Market Cap (USD bn) |
|---|---|---|
| Tencent Holdings | 0700.HK | 714.3 |
| Xiaomi Corporation | 1810.HK | 123.2 |
| SMIC (semiconductors) | 0981.HK | 98.1 |
| NetEase | 9999.HK | 89.1 |
| Hua Hong Semiconductor | 1347.HK | 27.6 |
| ZTE Corporation | 0763.HK | 24.9 |
| Horizon Robotics | 9660.HK | 16.7 |
| Lenovo Group | 0992.HK | 14.1 |

Tencent alone (~$714B) is bigger than the next 7 names combined. Note
Alibaba, Meituan, Baidu, JD.com are classified as **Consumer Discretionary**
in this official taxonomy, not IT — a genuine classification quirk worth
remembering when building sector aggregates.

### 3. Consumer Discretionary — sector total ~$1,634B (n=104, largest by count)
| Company | Ticker | Market Cap (USD bn) |
|---|---|---|
| Alibaba Group | 9988.HK | 406.9 |
| BYD Company | 1211.HK | 116.0 |
| Midea Group | 0300.HK | 84.5 |
| Meituan | 3690.HK | 78.3 |
| Baidu | 9888.HK | 52.4 |
| JD.com | 9618.HK | 44.9 |
| Kuaishou Technology | 1024.HK | 43.7 |
| Trip.com Group | 9961.HK | 39.1 |
| MTR Corporation | 0066.HK | 24.7 |
| Galaxy Entertainment | 0027.HK | 22.6 |

This is the catch-all bucket for mainland internet platforms, e-commerce,
EVs/appliances, travel, and HK transit/gaming — hence both the largest
sector by constituent count and second largest by total cap.

### 4. Energy — sector total ~$714B (n=16)
| Company | Ticker | Market Cap (USD bn) |
|---|---|---|
| PetroChina | 0857.HK | 259.1 |
| China Shenhua Energy | 1088.HK | 143.3 |
| CNOOC | 0883.HK | 138.0 |
| Sinopec Corp | 0386.HK | 101.7 |
| China Coal Energy | 1898.HK | 22.2 |
| Yankuang Energy | 1171.HK | 20.1 |

(This confirms the ~$260B PetroChina figure is the right order of
magnitude — an earlier web-sourced pull of "$1.8T" was almost certainly a
combined/A-share-inclusive number, not the HK-line market cap. Good catch to
retire.)

### 5. Industrials — sector total ~$697B (n=60)
| Company | Ticker | Market Cap (USD bn) |
|---|---|---|
| CATL (Contemporary Amperex Technology) | 3750.HK | 283.5 |
| CRRC Corporation | 1766.HK | 33.8 |
| COSCO Shipping Holdings | 1919.HK | 30.6 |
| Sanhua Intelligent Controls | 2050.HK | 27.4 |
| Weichai Power | 2338.HK | 26.3 |
| Shanghai Electric | 2727.HK | 19.4 |
| ZTO Express | 2057.HK | 17.6 |
| J&T Express | 1519.HK | 13.0 |

### 6. Materials — sector total ~$500B (n=23)
| Company | Ticker | Market Cap (USD bn) |
|---|---|---|
| Zijin Mining Group | 2899.HK | 137.7 |
| China Molybdenum (CMOC) | 3993.HK | 70.2 |
| Zijin Gold International | 2259.HK | 57.0 |
| China Hongqiao Group | 1378.HK | 44.7 |
| Aluminum Corp of China (Chalco) | 2600.HK | 30.6 |
| Jiangxi Copper | 0358.HK | 29.8 |
| Shandong Gold Mining | 1787.HK | 29.3 |
| Ganfeng Lithium | 1772.HK | 21.9 |

### 7. Healthcare — sector total ~$497B (n=73, wide but shallow)
| Company | Ticker | Market Cap (USD bn) |
|---|---|---|
| Jiangsu Hengrui Pharmaceuticals | 1276.HK | 69.3 |
| WuXi AppTec | 2359.HK | 46.9 |
| BeiGene | 6160.HK | 37.4 |
| Hansoh Pharmaceutical | 3692.HK | 32.8 |
| JD Health | 6618.HK | 27.6 |
| WuXi Biologics | 2269.HK | 21.1 |
| Innovent Biologics | 1801.HK | 19.7 |
| Sino Biopharmaceutical | 1177.HK | 15.9 |

73 constituents but the sector total is smaller than Materials or
Industrials — long tail of small/mid-cap biotech.

### 8. Properties & Construction — sector total ~$396B (n=59)
| Company | Ticker | Market Cap (USD bn) |
|---|---|---|
| Sun Hung Kai Properties | 0016.HK | 41.8 |
| China Resources Land | 1109.HK | 26.8 |
| China Communications Construction | 1800.HK | 21.8 |
| KE Holdings (Beike) | 2423.HK | 19.7 |
| Henderson Land Development | 0012.HK | 19.6 |
| CK Asset Holdings | 1113.HK | 19.3 |
| China Overseas Land & Investment | 0688.HK | 18.4 |
| China Railway Group | 0390.HK | 18.4 |

### 9. Telecommunications — sector total ~$380B (n=8, smallest count)
| Company | Ticker | Market Cap (USD bn) |
|---|---|---|
| China Mobile | 0941.HK | 224.8 |
| China Telecom | 0728.HK | 80.1 |
| China Unicom | 0762.HK | 30.2 |
| China Tower | 0788.HK | 25.7 |
| HKT Trust | 6823.HK | 11.3 |
| PCCW | 0008.HK | 5.5 |
| HKBN (HK Broadband) | 1310.HK | 1.3 |
| CITIC Telecom International | 1883.HK | 1.2 |

### 10. Consumer Staples — sector total ~$260B (n=37)
| Company | Ticker | Market Cap (USD bn) |
|---|---|---|
| Nongfu Spring | 9633.HK | 73.3 |
| Haitian Flavouring & Food | 3288.HK | 29.0 |
| Mixue Group | 2097.HK | 20.4 |
| WH Group | 0288.HK | 14.4 |
| Budweiser APAC | 1876.HK | 13.0 |
| China Resources Beer | 0291.HK | 10.7 |
| Tsingtao Brewery | 0168.HK | 10.0 |
| Tingyi (Master Kong) | 0322.HK | 8.6 |

### 11. Utilities — sector total ~$232B (n=27)
| Company | Ticker | Market Cap (USD bn) |
|---|---|---|
| China General Nuclear Power | 1816.HK | 25.7 |
| CLP Holdings | 0002.HK | 23.6 |
| CK Infrastructure Holdings | 1038.HK | 19.3 |
| Hong Kong & China Gas (Towngas) | 0003.HK | 17.2 |
| Huaneng Power International | 0902.HK | 16.5 |
| Power Assets Holdings | 0006.HK | 15.5 |
| China Longyuan Power | 0916.HK | 14.2 |
| China Resources Power | 0836.HK | 12.0 |

### 12. Conglomerates — sector total ~$126B (n=6, smallest sector)
| Company | Ticker | Market Cap (USD bn) |
|---|---|---|
| CITIC Limited | 0267.HK | 44.9 |
| Swire Pacific A | 0019.HK | 33.7 |
| CK Hutchison Holdings | 0001.HK | 29.7 |
| Swire Pacific B | 0087.HK | 11.6 |
| Fosun International | 0656.HK | 4.4 |
| Shanghai Industrial Holdings | 0363.HK | 2.0 |

## Sector ranking by total market cap
1. Financials — ~$3,128B
2. Consumer Discretionary — ~$1,634B
3. Information Technology — ~$1,248B
4. Energy — ~$714B
5. Industrials — ~$697B
6. Materials — ~$500B
7. Healthcare — ~$497B
8. Properties & Construction — ~$396B
9. Telecommunications — ~$380B
10. Consumer Staples — ~$260B
11. Utilities — ~$232B
12. Conglomerates — ~$126B

## Caveats
- Snapshot is ~6 months old (industry tags dated 2026-01-16, market caps
  through 2026-01-14) — treat as directional, not current-day.
- Market cap methodology in `hsci_mkt_cp.csv` isn't fully documented inline;
  cross-checks against independent web trackers (ICBC, AIA, HKEX, PetroChina)
  landed within ~10-15% of these figures, so the numbers look sound, but
  worth reading `src/qresearch/universe/hsci.py` before relying on this for
  anything quantitative (e.g. confirming whether it's full share count or
  free float, and how dual A+H listings are handled).
- Official HSI taxonomy buckets big mainland internet platforms (Alibaba,
  Meituan, Baidu, JD.com) under **Consumer Discretionary**, not Information
  Technology — different from how a GICS-style scheme would usually class
  them.

## Next steps (not yet done)
- Map each sector above to candidate **free alternative-data sources** (e.g.
  HKEX filings/announcements, shipping/AIS data for CK Hutchison/COSCO
  ports, casino gaming revenue stats for Galaxy Entertainment, property
  transaction registries for HK real estate names, app download/usage
  rankings for Meituan/Alibaba/Tencent, EV registration data for BYD).
- Repeat this sector/company/market-cap pass for South Korea (KOSPI), Japan
  (TOPIX/Nikkei), Taiwan (TAIEX), and China A-shares — check whether
  `~/Desktop/Quant/Research` has similar per-market datasets already (the
  `experiments/akshare/` notebooks suggest at least some China A-share /
  HK data work exists via akshare too).

## Sources
- `~/Desktop/Quant/Research/data/processed/hsci_components.csv` — official
  HSI industry classification per constituent (snapshot 2026-01-16)
- `~/Desktop/Quant/Research/data/processed/hsci_mkt_cp.csv` — computed daily
  market cap time series per ticker, 2009–2026
- `~/Desktop/Quant/Research/data/processed/hsci_sector_map_yf.csv` —
  alternate yfinance-derived sector mapping (used for the factor-model
  neutralisation work)
- `~/Desktop/Quant/Research/src/qresearch/universe/hsci.py` — the code that
  builds/maintains this HSCI universe
- `~/Desktop/Quant/Research/experiments/factor_model/summary/04_hsci_factor_analysis.md` —
  the factor-research write-up this dataset was originally built for
- Cross-checks (web, for sanity only): [Top 25 Hang Seng Index Stocks Ranked by Weight (2026) — The Investing Engineer](https://investingengineer.com/top-25-hang-seng-index-stocks-ranked-by-weight/), [companiesmarketcap.com](https://companiesmarketcap.com/hong-kong/largest-companies-in-hong-kong-by-market-cap/)
