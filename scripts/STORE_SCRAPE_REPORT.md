# HK Retail & F&B Store-Count Scrapers — 调研报告

> 版本：v2（2026-07-25）· 基于 Action 门店爬虫（`scrape_action_stores.py`）模式

---

## 总览

目标：对关注的香港本地零售/餐饮/消费公司，建立类似 Action 的按周门店计数时序信号。

| # | 公司 | 代码 | 类型 | 脚本 | 门店数 | 数据源 | 状态 |
|---|------|------|------|------|--------|--------|------|
| 1 | **周大福 (Chow Tai Fook)** | 01929.HK | 黄金珠宝 | `scrape_ctf_stores.py` | **5,408** | Demandware (Salesforce) API | ✅ |
| 2 | **六福珠宝 (Luk Fook)** | 00590.HK | 黄金珠宝 | `scrape_lukfook_stores.py` | **2,505** | `www1.lukfook.com.hk` 内部 JSON API | ✅ |
| 3 | **周生生 (Chow Sang Sang)** | 00116.HK | 黄金珠宝 | `scrape_chowsangsang_stores.py` | **782** | PHP store locator API | ✅ |
| 4 | **佐丹奴 (Giordano)** | 00709.HK | 服装 | `scrape_giordano_stores.py` | **711** | WCF REST API (`GetShopsMap`) | ✅ |
| 5 | **大快活 (Fairwood)** | 00052.HK | 快餐 | `scrape_fairwood_stores.py` | **151** | Next.js `__NEXT_DATA__` | ✅ |
| 6 | **莎莎 (Sa Sa)** | 00178.HK | 化妆品 | `scrape_sasa_stores.py` | **86** | 91app API | ✅ |
| 7 | **大家乐 (Café de Coral)** | 00341.HK | 快餐 | `scrape_cafedecoral_stores.py` | **83** | eatcdc.com 分店地址页 | ✅ |
| 8 | **堡狮龙 (Bossini)** | 00592.HK | 服装 | `scrape_bossini_stores.py` | **26** | Shopline 門店地址 HTML | ✅ |

**已上线（8/8，100% 覆盖）**：全部 8 家关注公司均已建立稳定程序化数据源，每周合计可输出 **9,752 家** 门店的时序信号。

---

## 各公司详情（实测验证）

### ✅ 1. 周大福 (Chow Tai Fook) — 5,408 家门店（全国覆盖）

**数据源**: Demandware (Salesforce Commerce Cloud) Stores-SearchStores API

```
GET /on/demandware.store/Sites-ctfeshop-hk-Site/en_HK/Stores-SearchStores?format=ajax
```

- **直接返回完整 JSON**（5,408 条记录，~4.8MB）
- 每个门店包含：`ID`, `name`, `address1`, `city`, `stateCode`, `latitude`, `longitude`
- **稳定度**: 高。Demandware 是标准电商平台，API 结构稳定
- **覆盖范围**: 全国（含 HK），按 `stateCode` 可分区统计
- **推荐运行频率**: 每周一次（门店变化慢）

**结果示例**（按 `stateCode` 分组前十）:
```
上海市: 271 家
北京市: 172 家
重慶市: 116 家
成都市: 111 家
蘇州市: 107 家
```

### ✅ 2. 大快活 (Fairwood) — 151 家门店

**数据源**: Next.js `__NEXT_DATA__` 内嵌数据

```
GET https://www.fairwood.com.hk/en/stores
→ pageProps.data.stores (151 items)
```

- 每个门店包含：`id`, `name`, `address`, `latitude`, `longitude`, `category`, 营业时间等
- 按区域分布：新界 76 / 九龙 45 / 港岛 28 / 离岛 2
- **稳定度**: 高。Next.js SSG 数据在构建时嵌入页面，直接可用
- **覆盖**: 仅香港

---

### ✅ 3. 莎莎 (Sa Sa) — 86 家门店（仅香港）

**数据源**: 91app（莎莎电商平台）Location API

```
GET https://webapi.91app.hk/webapi/LocationV2/GetLocationList?lat=22.3193&lon=114.1694&shopId=17
```

- 使用中心坐标 (22.3193, 114.1694) 一次性拉取全部 86 家门店
- 按区域分布：九龙 30 / 新界 30 / 港岛 17 / 未知 9
- 每个门店包含：Name, Address, CityName, AreaName, Latitude, Longitude, Tel
- **稳定度**: 高。91app API 返回完整 JSON，接口稳定

### ✅ 4. 大家乐 (Café de Coral) — 83 家分店（仅香港）

**数据源**: eatcdc.com（大家乐网上商店）分店地址页

```
GET https://www.eatcdc.com/tch/main/terms.jsp?id=B2D0P2M0R0Y891E8L1D18188M4G0A802
```

- 官网 cafedecoral.com 仍被 Cloudflare WAF 拦截，改从电商站点抓取
- 页面 HTML 中包含全部分店列表（名称、地址、电话、营业时间）
- 按区域分布：新界 39 / 九龙 27 / 香港 17
- **稳定度**: 中。依赖页面 HTML 文本结构，可能随网站更新变化
- **注意**: 该页面属于大家乐网上商店(eatcdc.com)，非主站，结构变更风险较低

### ✅ 5. 周生生 (Chow Sang Sang) — 782 家门店（港台为主）

**数据源**: 官网 PHP Store Locator API

```
GET /script/api/css/getStoreLocator.php?region=HK&lang=zh_HK
```

- 支持按区域参数查询：`region=HK`(744 家)、`region=TW`(38 家)
- 每个门店包含：name, address, tel, lat, lng
- **稳定度**: 高。PHP API 返回完整 JSON，接口简单稳定
- **覆盖**: 香港为主（744 家），另有台湾（38 家）

---

### ✅ 6. 六福珠宝 (Luk Fook) — 2,505 家门店（全国及海外）

**数据源**: `www1.lukfook.com.hk` 内部地图 JSON API

- **省份列表 API**: `GET https://www1.lukfook.com.hk/LF-AMap/home/getprovince`（返回 31 个省份及 ID）
- **国内门店 API**: `GET https://www1.lukfook.com.hk/LF-AMap/home/getshop?pid={pid}&keyword=`（按省份 ID 返回全量门店 JSON，共 2,416 家）
- **港澳及海外门店 API**: `GET https://www1.lukfook.com.hk/LF-AMap/home/GetShopAbroad?region={region}&keyword=`（涵盖香港 48 家、澳门 20 家、新加坡、马来西亚、美国等 12 个地区，共 89 家）
- **稳定度**: 高。直接返回包含店名、英文/中文地址、经纬度、电话及营业时间的完整 JSON 数据

### ✅ 7. 佐丹奴 (Giordano) — 711 家门店（10 个主要市场）

**数据源**: WCF REST API (`https://giordanoappsite.giordano.com/SVC/AppsFunc.svc/rest/GetShopsMap`)

- **接口结构**: `GET /GetShopsMap?market={market_code}&langid=EN&longitude=0&latitude=0`
- **主要市场覆盖**: 泰国 (148), 台湾 (140), 印尼 (107), 菲律宾 (97), 马来西亚 (89), 越南 (36), 香港及澳门 (32), 新加坡 (31), 英国 (28), 澳大利亚 (3)
- **稳定度**: 高。直接返回 JSON 数组，包含门店 SimpleID, Address, Tel, Latitude, Longitude 等

### ✅ 8. 堡狮龙 (Bossini) — 26 家门店（港澳地区）

**数据源**: Shopline 平台門店地址页 HTML (`https://www.bossini.com/pages/shop-address?locale=zh-hant`)

- **页面解析**: 解析 HTML 文本中的分店名称、英文/中文地址及电话号码
- **区域分布**: 新界 12 / 九龙 7 / 港岛 6 / 澳门 1
- **稳定度**: 高。页面结构清晰，包含全部港澳实体店地址

---

## 数据源发现过程

### 主要发现

| 公司 | 原尝试（失败） | 最终方案 |
|------|---------------|---------|
| **莎莎** | sasa.com 403 / corp.sasa.com 无数据 ➔ | 91app 电商平台 API（全新发现） |
| **大家乐** | cafedecoral.com Cloudflare WAF ➔ | eatcdc.com 分店地址页 |
| **周生生** | 主站无 store 页面 ➔ | `getStoreLocator.php` 直接返回 JSON |
| **六福** | API handle not found / Playwright 无结果 | 暂无可行方案 |

### Playwright 浏览器自动化尝试

在第二轮中，使用 Playwright（带真实浏览器渲染）重新尝试了所有当时无数据的公司：

| 公司 | Playwright 结果 | 结论 |
|------|----------------|------|
| **六福珠宝** | ⚠️ 页面加载成功但门店通过图片地图交互，无 API 请求 | ❌ 不可用 |
| **大家乐** | ❌ cafedecoral.com 仍返回 403 | 绕过方案：改用 eatcdc.com ✅ |
| **佐丹奴** | ⚠️ C1.aspx 返回产品 HTML，非门店数据 | ❌ 不可用 |
| **莎莎** | ⚠️ store-locator 路径 404 | 绕过方案：91app API ✅ |
| **周生生** | ⚠️ 未找到 store 页面 | 绕过方案：PHP API ✅ |
| **堡狮龙** | ⚠️ Shopline 平台确认，无门店 API | ❌ 不可用 |

---

## 推荐的替代方案：高德地图 POI API

对于 Luk Fook 等无法从官网获取的公司，可以使用高德地图 POI 搜索 API：

```
https://restapi.amap.com/v3/place/text?keywords={品牌名}&key={API_KEY}&offset=20&page=1
```

**优点**：
- 一个免费 API Key 搜索全部品牌
- 数据更新通常比官网及时

**缺点**：
- **必须申请 API Key**（已验证：无 key 返回 `INVALID_USER_KEY`）
- 免费版每日配额约 5000 次
- 可能包含非直营/已关闭门店

**替代方案 — OpenStreetMap**:
- 免费无需 API Key
- Luk Fook 仅 14 条结果，Giordano/Bossini 0 条 — HK 覆盖严重不足
- Overpass API 功能更强但需调试 Content-Type 头

**替代方案 — locator.hk**:
- 通用香港地图服务目录网站
- 无公开 API 或结构化数据，不可用

---

## 推荐的技术方案对比

| 方式 | 适合公司 | 难度 | 稳定性 | 频次 | 备注 |
|------|---------|------|--------|------|------|
| **官网 API** | CTF, CSS | 低 | 高 | 周 | Demandware/PHP API 标准接口 |
| **SSR 数据** | Fairwood | 低 | 高 | 周 | Next.js `__NEXT_DATA__` |
| **电商 API** | Sa Sa | 中 | 高 | 周 | 91app Location API |
| **HTML 解析** | Café de Coral | 中 | 中 | 周 | eatcdc.com 分店页 |
| **第三方 POI API** | 六福、Giordano、Bossini | 中 | 中 | 周 | 高德/百度地图需免费 API Key |
| **OpenStreetMap** | 补充 | 低 | 低 | 周 | 免费但 HK 覆盖不全 |
| **Playwright 渲染** | — | 高 | 低 | 周 | 需浏览器环境 |

---

## 当前状态 & 建议

### ✅ 全量上线（8/8，100% 覆盖，每周合计 9,752 家门店）
- **CTF (周大福)**: 5,408 家（全国）
- **Luk Fook (六福珠宝)**: 2,505 家（全国及海外）
- **CSS (周生生)**: 782 家（HK 744 + TW 38）
- **Giordano (佐丹奴)**: 711 家（10 个国际市场）
- **Fairwood (大快活)**: 151 家（香港）
- **Sa Sa (莎莎)**: 86 家（香港）
- **Café de Coral (大家乐)**: 83 家（香港）
- **Bossini (堡狮龙)**: 26 家（港澳）

### 📋 下一步建议
1. **申请高德地图 API Key**（免费），写一个通用 POI 搜索脚本一次性覆盖全部品牌
2. **OpenStreetMap Overpass API**（需修复 Content-Type 头）可作为免费补充
3. **数据可视化**：将 parquet 时序挂载到 asia-markets-dashboard 的 Consumer Trends 板块
4. **自动化**：在 GitHub Actions 中每周自动运行 `run-store-scrapers.sh`

---

## 文件结构

```
scripts/
├── scrape_action_stores.py       # ✅ Action 欧洲折扣店（模板参照）
├── scrape_ctf_stores.py          # ✅ 周大福 (5,408)
├── scrape_lukfook_stores.py      # ✅ 六福珠宝 (2,505)
├── scrape_chowsangsang_stores.py # ✅ 周生生 (782)
├── scrape_giordano_stores.py     # ✅ 佐丹奴 (711)
├── scrape_fairwood_stores.py     # ✅ 大快活 (151)
├── scrape_sasa_stores.py         # ✅ 莎莎 (86)
├── scrape_cafedecoral_stores.py  # ✅ 大家乐 (83)
├── scrape_bossini_stores.py      # ✅ 堡狮龙 (26)
├── run-store-scrapers.sh         # ✅ 批量运行脚本
└── STORE_SCRAPE_REPORT.md        # 📄 本报告

data/processed/
├── action_stores/                # ✅ Action 时序数据（多国）
├── ctf_stores/                   # ✅ 5,408
├── lukfook_stores/               # ✅ 2,505
├── chowsangsang_stores/          # ✅ 782
├── giordano_stores/              # ✅ 711
├── fairwood_stores/              # ✅ 151
├── sasa_stores/                  # ✅ 86
├── cafedecoral_stores/           # ✅ 83
└── bossini_stores/               # ✅ 26
```
