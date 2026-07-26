# 🏪 Hong Kong & Mainland Retail Store Scraper Summary Report

> **Last Updated**: 2026-07-26  
> **Status**: **11 Active Verified Scrapers (10,788 Total Real Locations Tracked)**

---

## 📊 Active Verified Store Scrapers Summary Table

| # | Company Name | Stock Code | Sector | Scraper Script | Location Granularity | Lat/Long Coordinates | Active Scraper? | Total Locations Tracked | Data Source Method |
|---|--------------|------------|--------|----------------|----------------------|-----------------------|-----------------|-------------------------|--------------------|
| 1 | **周大福 (Chow Tai Fook)** | 01929.HK | 珠宝 | `scrape_ctf_stores.py` | 省份 / 城市 / 区域 | ✅ 纬度/经度 | ✅ Yes | **5,408** | Demandware JSON API |
| 2 | **六福珠宝 (Luk Fook)** | 00590.HK | 珠宝 | `scrape_lukfook_stores.py` | 国家 / 省份 / 城市 | ✅ 纬度/经度 | ✅ Yes | **2,505** | Official REST / JSON API |
| 3 | **周生生 (Chow Sang Sang)** | 00116.HK | 珠宝 | `scrape_chowsangsang_stores.py` | 地区 (HK/TW) | ✅ 纬度/经度 | ✅ Yes | **781** | Official JSON API |
| 4 | **佐丹奴 (Giordano)** | 00709.HK | 服装 | `scrape_giordano_stores.py` | 10个国际市场 (TH, TW, ID, PH, MY, VN, HK, SG, GB, AU) | ✅ 纬度/经度 | ✅ Yes | **711** | WCF REST API |
| 5 | **太兴集团 (Tai Hing Group)** | 06811.HK | 餐饮 | `scrape_taihing_stores.py` | 品牌 (太兴/敏华冰厅/亚参鸡饭/茶木等32个品牌) | 🟡 门牌地址 | ✅ Yes | **231** | Official Category Directory (`taihing.com`) |
| 6 | **泡泡玛特 (POP MART)** | 09992.HK | 潮玩 | `scrape_popmart_stores.py` | 19个市场 (中国大陆/美国/加拿大/香港/新加坡/日本/韩国/澳洲/新西兰/泰国/马来西亚/越南/菲律宾/印尼/英国/法国/德国/西班牙/意大利/荷兰/丹麦) & 门店类型 (直营店/机器人商店/快闪店/合作店) | ✅ 纬度/经度 | 🟡 Partial[^1] | **768** | 4 official REST/RPC backends (`popmart.com.cn`, `prod-na-api`, `prod-apac-api`, `prod-uk-online-api`) |
| 7 | **大快活 (Fairwood)** | 00052.HK | 餐饮 | `scrape_fairwood_stores.py` | 18区 (新界/九龙/港岛) | ✅ 纬度/经度 | ✅ Yes | **151** | `__NEXT_DATA__` SSR JSON |
| 8 | **莎莎 (Sa Sa)** | 00178.HK | 化妆品 | `scrape_sasa_stores.py` | 地区 (新界/九龙/港岛) | ✅ 纬度/经度 | ✅ Yes | **86** | 91app Location API |
| 9 | **大家乐 (Café de Coral)** | 00341.HK | 餐饮 | `scrape_cafedecoral_stores.py` | 地区 (新界/九龙/港岛) | 🟡 门牌地址 | ✅ Yes | **83** | DOM HTML Directory |
| 10 | **老铺黄金 (Lao Pu Gold)** | 06181.HK | 珠宝 | `scrape_laopugold_stores.py` | 16个核心城市/地区 (北京/上海/深圳/香港/澳门/新加坡等) | ✅ 高端商场门牌 | ✅ Yes | **37** | Official Category Directory (`lphj.com`) |
| 11 | **堡狮龙 (Bossini)** | 00592.HK | 服装 | `scrape_bossini_stores.py` | 地区 (新界/九龙/港岛/澳门) | 🟡 门牌地址 | ✅ Yes | **26** | HTML Store Address Page |

**Total Locations Tracked Across All 11 Active Scrapers**: **10,788 Locations**

[^1]: **POP MART is a known partial dataset, not a complete global count.** Two confirmed gaps as of 2026-07-26:
    - **Taiwan** could not be captured this run. Taiwan's store list is served by a separate, signed backend (`prod-intl-api.popmart.com`) that direct HTTP cannot reach (WAF-blocked, HTTP 471) and that had to be attempted via a real Playwright browser session instead. That session confirmed the backend's own health-check endpoint (`serverMaintenance/info`) reporting `inMaintenance: 1` -- i.e. POP MART's own backend was down at scrape time, not a block on this scraper. The scraper retries this market every run and will pick it up automatically once the backend is back.
    - **Mainland China Roboshops are not included.** The public `popmart.com.cn` store locator only ever returned POP MART's own-brand retail stores (364 of them, across 90 cities) -- no field or UI element on that page referenced Roboshops/vending machines. POP MART's public disclosures put mainland China Roboshops in the thousands; none of that is captured here because no public web endpoint for it was found.
    - Everything else in the 768-row total (US, Canada, Hong Kong, Singapore, Japan, South Korea, Australia, New Zealand, Thailand, Malaysia, Vietnam, Philippines, Indonesia, UK, France, Germany, Spain, Italy, Netherlands, Denmark) is a real, verified per-store record with lat/long pulled directly from POP MART's own official REST/RPC APIs.
    - **Cross-check against public disclosures**: POP MART's FY2025 results state 630 retail stores + 2,637 Roboshops (~3,267 total) across 20 countries/regions by end-2025. This scraper's 768 rows (586 tagged Retail Store, 170 tagged Roboshop) land close to the disclosed retail-store figure once mainland China's 364 CN retail rows are counted in, but come in far short on Roboshops specifically -- almost entirely because mainland China's Roboshops (very likely the large majority of that 2,637) are the one gap this scraper could not find a public endpoint for. Do not read 768 as "POP MART's global footprint" -- read it as "every store this scraper could verify with a real API response," which is a meaningfully smaller, mostly-non-China-Roboshop-shaped subset of the true count.

---

## ⚡ Master Execution Runner

Run all 11 verified active store scrapers:

```bash
bash scripts/run-store-scrapers.sh
```
