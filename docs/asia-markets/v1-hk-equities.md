# V1 Hong Kong Equities Universe

**Prepared:** 2026-07-26  
**Market:** Hong Kong-listed equities and REITs  
**Purpose:** financial statements, daily prices, index membership, alternative-data joins and later point-in-time backtesting.

## Scope

V1 includes:

1. All current Hang Seng Index (HSI) constituents.
2. All current Hang Seng TECH Index (HSTECH) constituents.
3. Research-theme additions from the Asia Markets work:
   - HK-local consumer and restaurants;
   - HK-local transport, infrastructure and telecom;
   - HK-focused property and construction exposure;
   - stablecoin and crypto;
   - commercial aerospace;
   - consumer discretionary trend stocks;
   - minerals;
   - energy and power.

The list is deduplicated by Hong Kong stock code. A company may belong to multiple themes.

The property list is intentionally restricted to companies with meaningful Hong Kong property or infrastructure exposure. Mainland-focused property developers, mainland REITs and generic China-wide construction contractors are not assigned the HK-property theme, even if they remain in the database because of HSI/HSTECH membership.

Samsonite is retained as an HK-listed international consumer company, but is not labelled HK-local.

## Index membership is point-in-time

The index columns below are a current snapshot based on the latest official review available for this V1 list:

- HSI: 93 constituents after the review effective 2026-06-08.
- HSTECH: 30 constituents after the review effective 2026-06-08.
- Unique index-core securities after deduplication: 104.

Index membership must not be stored as a permanent company attribute. The database should maintain an effective-dated table such as:

```text
index_memberships
  ticker
  index_code
  effective_from
  effective_to
  announcement_date
  review_date
  weight_pct
  source_url
```

For historical backtests, use the membership valid on the signal date. Do not overwrite old additions, removals or constituent weights.

Official references: [HSI review results](https://www.hsi.com.hk/static/uploads/contents/en/news/pressRelease/20260522T174500.pdf), [HSTECH factsheet](https://www.hsi.com.hk/static/uploads/contents/en/dl_centre/factsheets/hsteche.pdf), [HSI factsheet](https://www.hsi.com.hk/static/uploads/contents/en/dl_centre/factsheets/hsie.pdf).

## 1. Index core — HSI constituents

### Financials

| Ticker | English name | 中文名称 | Index membership |
|---|---|---|---|
| 0005.HK | HSBC Holdings | 汇丰控股 | HSI |
| 1299.HK | AIA Group | 友邦保险 | HSI |
| 0939.HK | China Construction Bank | 中国建设银行 | HSI |
| 1398.HK | Industrial and Commercial Bank of China | 中国工商银行 | HSI |
| 0388.HK | Hong Kong Exchanges & Clearing | 香港交易所 | HSI |
| 2318.HK | Ping An Insurance | 中国平安 | HSI |
| 3988.HK | Bank of China | 中国银行 | HSI |
| 2628.HK | China Life Insurance | 中国人寿 | HSI |
| 3968.HK | China Merchants Bank | 招商银行 | HSI |
| 2388.HK | BOC Hong Kong | 中银香港 | HSI |

### Consumer discretionary and staples

| Ticker | English name | 中文名称 | Index membership |
|---|---|---|---|
| 9988.HK | Alibaba Group | 阿里巴巴 | HSI + HSTECH |
| 3690.HK | Meituan | 美团 | HSI + HSTECH |
| 1211.HK | BYD Company | 比亚迪 | HSI + HSTECH |
| 9618.HK | JD.com | 京东集团 | HSI + HSTECH |
| 9888.HK | Baidu | 百度 | HSI + HSTECH |
| 0669.HK | Techtronic Industries | 创科实业 | HSI |
| 1024.HK | Kuaishou Technology | 快手 | HSI + HSTECH |
| 0175.HK | Geely Automobile | 吉利汽车 | HSI |
| 9992.HK | Pop Mart | 泡泡玛特 | HSI |
| 2020.HK | Anta Sports | 安踏体育 | HSI |
| 9961.HK | Trip.com | 携程集团 | HSI + HSTECH |
| 9633.HK | Nongfu Spring | 农夫山泉 | HSI |
| 2015.HK | Li Auto | 理想汽车 | HSI + HSTECH |
| 0288.HK | WH Group | 万洲国际 | HSI |
| 0027.HK | Galaxy Entertainment | 银河娱乐 | HSI |
| 0066.HK | MTR Corporation | 港铁公司 | HSI |
| 0300.HK | Midea Group | 美的集团 | HSI + HSTECH |
| 2319.HK | Mengniu Dairy | 蒙牛乳业 | HSI |
| 6690.HK | Haier Smart Home | 海尔智家 | HSI + HSTECH |
| 0291.HK | China Resources Beer | 华润啤酒 | HSI |
| 2331.HK | Li Ning | 李宁 | HSI |
| 2313.HK | Shenzhou International | 申洲国际 | HSI |
| 1928.HK | Sands China | 金沙中国 | HSI |
| 6181.HK | Laopu Gold | 老铺黄金 | HSI |
| 9901.HK | New Oriental | 新东方 | HSI |
| 6862.HK | Haidilao | 海底捞 | HSI |
| 0322.HK | Tingyi | 康师傅控股 | HSI |
| 1929.HK | Chow Tai Fook Jewellery | 周大福珠宝 | HSI |
| 1044.HK | Hengan International | 恒安国际 | HSI |
| 1876.HK | Budweiser APAC | 百威亚太 | HSI |

### Information technology

| Ticker | English name | 中文名称 | Index membership |
|---|---|---|---|
| 0700.HK | Tencent Holdings | 腾讯控股 | HSI + HSTECH |
| 1810.HK | Xiaomi Corporation | 小米集团 | HSI + HSTECH |
| 0981.HK | SMIC | 中芯国际 | HSI + HSTECH |
| 9999.HK | NetEase | 网易 | HSI + HSTECH |
| 0992.HK | Lenovo Group | 联想集团 | HSI + HSTECH |
| 0285.HK | BYD Electronic | 比亚迪电子 | HSI + HSTECH |

### Energy, materials, industrials and conglomerates

| Ticker | English name | 中文名称 | Index membership |
|---|---|---|---|
| 0883.HK | CNOOC | 中国海洋石油 | HSI |
| 0857.HK | PetroChina | 中国石油 | HSI |
| 2899.HK | Zijin Mining | 紫金矿业 | HSI |
| 0001.HK | CK Hutchison | 长和 | HSI |
| 1088.HK | China Shenhua Energy | 中国神华 | HSI |
| 3750.HK | CATL | 宁德时代 | HSI |
| 1378.HK | China Hongqiao | 中国宏桥 | HSI |
| 0386.HK | Sinopec | 中国石化 | HSI |
| 0267.HK | CITIC | 中信股份 | HSI |
| 2057.HK | ZTO Express | 中通快递 | HSI |
| 3993.HK | CMOC Group | 洛阳钼业 | HSI |
| 1519.HK | J&T Express | 极兔速递 | HSI |
| 2382.HK | Sunny Optical | 舜宇光学科技 | HSI + HSTECH |
| 2600.HK | Chalco | 中国铝业 | HSI |
| 2618.HK | JD Logistics | 京东物流 | HSI |
| 0868.HK | Xinyi Glass | 信义玻璃 | HSI |
| 0316.HK | OOIL | 东方海外国际 | HSI |
| 0968.HK | Xinyi Solar | 信义光能 | HSI |

### Telecommunications and utilities

| Ticker | English name | 中文名称 | Index membership |
|---|---|---|---|
| 0941.HK | China Mobile | 中国移动 | HSI |
| 0002.HK | CLP Holdings | 中电控股 | HSI |
| 0006.HK | Power Assets Holdings | 电能实业 | HSI |
| 0003.HK | Hong Kong & China Gas | 香港中华煤气 | HSI |
| 0728.HK | China Telecom | 中国电信 | HSI |
| 0762.HK | China Unicom | 中国联通 | HSI |
| 2688.HK | ENN Energy | 新奥能源 | HSI |
| 0836.HK | China Resources Power | 华润电力 | HSI |
| 1038.HK | CK Infrastructure | 长江基建 | HSI |

### Healthcare

| Ticker | English name | 中文名称 | Index membership |
|---|---|---|---|
| 6160.HK | BeOne Medicines / BeiGene | 百济神州 | HSI |
| 1801.HK | Innovent Biologics | 信达生物 | HSI |
| 2269.HK | WuXi Biologics | 药明生物 | HSI |
| 2359.HK | WuXi AppTec | 药明康德 | HSI |
| 1093.HK | CSPC Pharmaceutical | 石药集团 | HSI |
| 1177.HK | Sino Biopharmaceutical | 中国生物制药 | HSI |
| 3692.HK | Hansoh Pharma | 翰森制药 | HSI |
| 6618.HK | JD Health | 京东健康 | HSI + HSTECH |
| 0241.HK | Alibaba Health | 阿里健康 | HSI + HSTECH |
| 1099.HK | Sinopharm | 国药控股 | HSI |

### HK property and infrastructure exposure

| Ticker | English name | 中文名称 | Index membership |
|---|---|---|---|
| 0016.HK | Sun Hung Kai Properties | 新鸿基地产 | HSI |
| 1109.HK | China Resources Land | 华润置地 | HSI |
| 0823.HK | Link REIT | 领展房产基金 | HSI |
| 1113.HK | CK Asset Holdings | 长实集团 | HSI |
| 0688.HK | China Overseas Land & Investment | 中国海外发展 | HSI |
| 0012.HK | Henderson Land Development | 恒基地产 | HSI |
| 1997.HK | Wharf Real Estate Investment | 九龙仓置业 | HSI |
| 1209.HK | China Resources Mixc Lifestyle | 华润万象生活 | HSI |
| 0960.HK | Longfor Group | 龙湖集团 | HSI |
| 0101.HK | Hang Lung Properties | 恒隆地产 | HSI |

The four names above with primarily mainland exposure—China Resources Land, China Overseas Land, China Resources Mixc and Longfor—remain here because they are index constituents, but they should not receive the `hk_local_property` theme tag.

## 2. HSTECH constituents not already in HSI

The other 19 HSTECH constituents are marked `HSI + HSTECH` above.

| Ticker | English name | 中文名称 | Index membership |
|---|---|---|---|
| 9868.HK | XPeng | 小鹏汽车 | HSTECH |
| 9626.HK | Bilibili | 哔哩哔哩 | HSTECH |
| 9863.HK | Leapmotor | 零跑汽车 | HSTECH |
| 0780.HK | Tongcheng Travel | 同程旅行 | HSTECH |
| 9866.HK | NIO | 蔚来 | HSTECH |
| 1698.HK | Tencent Music Entertainment | 腾讯音乐娱乐 | HSTECH |
| 1347.HK | Hua Hong Semiconductor | 华虹半导体 | HSTECH |
| 9660.HK | Horizon Robotics | 地平线机器人 | HSTECH |
| 0020.HK | SenseTime | 商汤科技 | HSTECH |
| 2513.HK | Z.AI / Beijing Zhipu Huazhang Technology | 北京智谱华章科技 | HSTECH |
| 0100.HK | MiniMax Group | 稀宇科技 | HSTECH |

## 3. Non-index thematic additions

These companies are added because they belong to the V1 research themes, even though they are not current HSI/HSTECH constituents.

### HK-local consumer and restaurants

| Ticker | English name | 中文名称 | Theme |
|---|---|---|---|
| 0590.HK | Luk Fook Holdings | 六福集团 | hk_local_consumer |
| 0116.HK | Chow Sang Sang | 周生生 | hk_local_consumer |
| 0341.HK | Café de Coral Holdings | 大家乐集团 | hk_local_restaurant |
| 0178.HK | Sa Sa International | 莎莎国际 | hk_local_consumer |
| 6811.HK | Tai Hing Group | 太兴集团 | hk_local_restaurant |
| 0052.HK | Fairwood Holdings | 大快活 | hk_local_restaurant |
| 1910.HK | Samsonite | 新秀丽 | hk_listed_international_consumer |
| 9987.HK | Yum China | 百胜中国 | restaurant |

`1929.HK Chow Tai Fook Jewellery / 周大福珠宝` is already in the HSI core. Prada, Giordano International and TATA Health are intentionally excluded.

### HK-local transport, infrastructure and telecom

| Ticker | English name | 中文名称 | Theme |
|---|---|---|---|
| 0293.HK | Cathay Pacific | 国泰航空 | hk_local_transport |
| 0019.HK | Swire Pacific A | 太古股份公司 A | hk_local_conglomerate |
| 0087.HK | Swire Pacific B | 太古股份公司 B | hk_local_conglomerate |
| 0008.HK | PCCW | 电讯盈科 | hk_local_telecom |
| 6823.HK | HKT Trust and HKT | 香港电讯 | hk_local_telecom |
| 1310.HK | HKBN | 香港宽频 | hk_local_telecom |
| 1883.HK | CITIC Telecom International | 中信国际电讯 | hk_local_telecom |

MTR, CLP, Towngas, Power Assets and CK Infrastructure are already in the HSI core.

### HK-focused property and infrastructure additions

| Ticker | English name | 中文名称 | HK business focus | Theme |
|---|---|---|---|---|
| 1972.HK | Swire Properties | 太古地产 | 甲级办公楼、商场、住宅、酒店 | hk_local_property |
| 0017.HK | New World Development | 新世界发展 | 香港住宅、办公楼、商场、酒店 | hk_local_property |
| 0683.HK | Kerry Properties | 嘉里建设 | 住宅、办公楼、商场、酒店 | hk_local_property |
| 0014.HK | Hysan Development | 希慎兴业 | 铜锣湾办公楼、商场、酒店、服务式住宅 | hk_local_property |
| 0041.HK | Great Eagle Holdings | 鹰君集团 | 酒店、办公楼、商场 | hk_local_property |
| 0071.HK | Miramar Hotel & Investment | 美丽华酒店企业 | 酒店、商场、餐饮、商业物业 | hk_local_property |
| 2778.HK | Champion REIT | 冠君产业信托 | 甲级办公楼、商场 | hk_local_property_reit |
| 0778.HK | Fortune REIT | 置富产业信托 | 社区商场、零售物业、停车场 | hk_local_property_reit |
| 0435.HK | Sunlight REIT | 阳光房地产基金 | 办公楼、商业物业 | hk_local_property_reit |
| 0808.HK | Prosperity REIT | 泓富产业信托 | 写字楼、工业及零售物业 | hk_local_property_reit |
| 1200.HK | Midland Holdings | 美联集团 | 地产代理、住宅成交及楼市周期 | hk_property_services |

Sun Hung Kai Properties, MTR, CK Asset, Wharf REIC, Hang Lung Properties and Link REIT are already in the HSI core. Sino Land is a separate HK-local property addition, not an HSI-core constituent.

The following are deliberately excluded from this HK-local property addition list: Yuexiu REIT, Spring REIT, CMC REIT, Beike, Hopefluent, E-House, C C Land, Tian An China, China Railway Group and China Communications Construction. They are mainland-focused, overseas-focused, mixed exposures or China-wide infrastructure rather than clean HK property exposures.

### Stablecoin and crypto

| Ticker | English name | 中文名称 | Theme |
|---|---|---|---|
| 0863.HK | OSL Group | OSL集团 | crypto_infrastructure |
| 3887.HK | HashKey Holdings | HashKey集团 | crypto_infrastructure |
| 1788.HK | Guotai Junan International | 国泰君安国际 | crypto_finance |
| 8540.HK | Victory Securities | 胜利证券 | crypto_finance |
| 1499.HK | OKG Technology | 欧科云链 | blockchain_data |
| 1611.HK | Sinohope Technology | 新火科技 | crypto_infrastructure |
| 2888.HK | Standard Chartered | 渣打集团 | stablecoin_adjacent |
| 1328.HK | Jinyong Investment | 金涌投资 | stablecoin_concept |
| 8087.HK | China 33 Group | 中国三三传媒 | stablecoin_concept |
| 2477.HK | Jingwei Tiandi | 经纬天地 | stablecoin_concept |
| 0290.HK | Guofu Quantum | 国富量子 | blockchain_concept |
| 0399.HK | Starcoin Group | 星太链集团 | crypto_concept |
| 1647.HK | Xiongan Technology | 雄岸科技 | crypto_concept |
| 0736.HK | China Properties Investment | 中国置业投资 | crypto_treasury |
| 0434.HK | Boyaa Interactive | 博雅互动 | crypto_treasury |
| 8267.HK | Lion Rock Group | 蓝港互动 | crypto_treasury |
| 2440.HK | MemeStrategy | 迷策略 | crypto_treasury |
| 0442.HK | Domain Holdings | 域能控股 | crypto_watchlist_check |
| 2562.HK | Synagistics | 狮腾控股 | blockchain_watchlist_check |

HSBC, BOC Hong Kong, Alibaba and JD.com are already in the index core and should also receive stablecoin/crypto theme tags.

### Commercial aerospace

| Ticker | English name | 中文名称 | Theme |
|---|---|---|---|
| 6613.HK | Lens Technology | 蓝思科技 | commercial_aerospace |
| 2208.HK | Goldwind | 金风科技 | commercial_aerospace_watchlist |
| 2357.HK | AVIC Aviation Industry | 中航科工 | commercial_aerospace |
| 2507.HK | Cirrus Aircraft | 西锐 | commercial_aerospace |
| 7688.HK | Topu CNC | 拓璞数控 | commercial_aerospace |
| 2865.HK | Junda | 钧达股份 | commercial_aerospace_watchlist |
| 0232.HK | Continental Aerospace Technologies | 大陆航空科技控股 | commercial_aerospace |
| 1045.HK | APT Satellite | 亚太卫星 | commercial_aerospace |
| 0031.HK | China Aerospace International | 航天控股 | commercial_aerospace |

Goldwind and Junda are retained but marked as lower-confidence theme classifications because their primary businesses are renewable energy rather than aerospace.

### Consumer discretionary trend stocks

| Ticker | English name | 中文名称 | Theme |
|---|---|---|---|
| 2097.HK | Mixue Group | 蜜雪集团 | consumer_trend |
| 9896.HK | Miniso | 名创优品 | consumer_trend |
| 1364.HK | Guming Holdings | 古茗 | consumer_trend |
| 2367.HK | Giant Biogene | 巨子生物 | consumer_trend |
| 1318.HK | Mao Geping | 毛戈平 | consumer_trend |
| 2555.HK | Chabaidao | 茶百道 | consumer_trend |
| 0325.HK | Bloks Group | 布鲁可 | consumer_trend |

Pop Mart, Anta, Chow Tai Fook, Laopu Gold and Li Ning are already in the HSI core and receive `consumer_trend` tags.

### Minerals

| Ticker | English name | 中文名称 | Theme |
|---|---|---|---|
| 2259.HK | Zijin Gold International | 紫金黄金国际 | minerals |
| 1787.HK | Shandong Gold Mining | 山东黄金 | minerals |
| 1772.HK | Ganfeng Lithium | 赣锋锂业 | minerals |

Zijin Mining, CMOC and China Hongqiao are already in the HSI core and receive `minerals` tags.

### Energy and power

| Ticker | English name | 中文名称 | Theme |
|---|---|---|---|
| 1898.HK | China Coal Energy | 中国中煤能源 | energy |
| 1171.HK | Yankuang Energy | 兖矿能源 | energy |
| 1816.HK | CGN Power | 中广核电力 | power_utilities |
| 0902.HK | Huaneng Power International | 华能国际 | power_utilities |
| 0916.HK | China Longyuan Power | 龙源电力 | power_utilities |
| 1193.HK | China Resources Gas | 华润燃气 | gas_utilities |

CNOOC, PetroChina, China Shenhua, Sinopec, ENN Energy, CLP, Towngas, Power Assets, CK Infrastructure and China Resources Power are already in the index core and receive energy or power-utility tags.

## 4. V1 implementation notes

The database registry should separate:

- `company`: stable legal entity and bilingual names;
- `security`: Hong Kong listing, ticker, share class and listing status;
- `index_memberships`: effective-dated HSI/HSTECH history;
- `theme_memberships`: research-theme membership and confidence;
- `price_history`: daily OHLCV;
- `financial_history`: point-in-time financial statements;
- `source_documents`: the Markdown or external source supporting inclusion.

Recommended theme/status values include:

```text
index_core
hk_local_consumer
hk_local_restaurant
hk_listed_international_consumer
hk_local_transport
hk_local_telecom
hk_local_property
hk_local_property_reit
hk_property_services
stablecoin_adjacent
crypto_infrastructure
crypto_concept
commercial_aerospace
consumer_trend
minerals
energy
power_utilities
research_only
```
