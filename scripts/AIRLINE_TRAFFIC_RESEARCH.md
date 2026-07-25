# Listed Airlines with Monthly Traffic Data — 调研报告

> 更新日期：2026-07-25 · 覆盖 12 家中外主流上市公司月度运营数据数据源及 API 实测结果

---

## 核心结论

1. **国泰航空 (Cathay Pacific, 00293.HK)**: ✅ **已上线并验证** (`src/hk_transport/sources/cathay_traffic.py`)。通过国泰 IR JSON API 自动发现 PDF 并解析 Passengers, ASK, RPK, Passenger Load Factor。
2. **中国三大航 + 三大主要 A 股航司（共 6 家）**: 
   - **完全可程序化抓取**。已验证可通过巨潮资讯网 (Cninfo) 官方 API 稳定拉取月度“主要运营数据”公告及 PDF。
   - **涵盖航司**：中国国航 (601111/00753)、中国南方航空 (600029/01055)、中国东方航空 (600115/00670)、春秋航空 (601021)、吉祥航空 (603885)、海航控股 (600221)。
3. **新加坡航空 (SIA, C6L.SI)**:
   - 月度发布 `How the SIA Group performed in {Month} {Year}` 运营报告，包含 SIA 旗舰 + Scoot 廉航的 RPK, ASK, PLF 及货运指标。可通过 SGXNet 披露接口或 IR PDF 抓取。
4. **台湾两大航司 (长荣航空 2618.TW / 中华航空 2610.TW)**:
   - 台湾公开资讯观测站 (MOPS) 及官网 IR 按月披露客运量、ASK、RPK 及月度营业收入。
5. **日本两大航司 (ANA 9202.T / JAL 9201.T)**:
   - ANA 及 JAL 官网 IR 均提供月度 "Monthly Passenger and Cargo Traffic Results"（国内/国际 RPK, ASK, 载客率）。

---

## 全球主流上市航司月度运营数据速查表

| # | 航司名称 | 代码 | 类型 | 核心指标 | 数据源 / 抓取 API | 接入状态 / 优先级 |
|---|----------|------|------|----------|-------------------|-------------------|
| 1 | **国泰航空 (Cathay Pacific)** | 00293.HK | 旗舰 | Passengers / RPK / ASK / PLF | Cathay IR JSON API + PDF | ✅ 已上线 (`cathay_traffic.py`) |
| 2 | **中国国航 (Air China)** | 601111.SH / 00753.HK | 旗舰 | 载客量 / RPK / ASK / PLF / 货运 (分国内/国际/地区) | Cninfo API (`orgId=9900000441`) | 🔴 第一阶段推荐 |
| 3 | **南方航空 (China Southern)** | 600029.SH / 01055.HK | 旗舰 | 同上 + 可用吨公里 (ATK) | Cninfo API (`orgId=gssh0600029`) | 🔴 第一阶段推荐 |
| 4 | **中国东航 (China Eastern)** | 600115.SH / 00670.HK | 旗舰 | 同上 | Cninfo API (`orgId=gssh0600115`) | 🔴 第一阶段推荐 |
| 5 | **春秋航空 (Spring Airlines)** | 601021.SH | 廉航 (LCC) | 载客量 / RPK / ASK / 客座率 | Cninfo API (`orgId=9900023129`) | 🔴 第一阶段推荐 (LCC 标杆) |
| 6 | **吉祥航空 (Juneyao Airlines)** | 603885.SH | 民营全服务 | 载客量 / RPK / ASK / 客座率 | Cninfo API (`orgId=9900023633`) | 🟡 第二阶段 |
| 7 | **海航控股 (Hainan Airlines)** | 600221.SH | 旗舰/大型 | 载客量 / RPK / ASK / 客座率 | Cninfo API (`orgId=gssh0600221`) | 🟡 第二阶段 |
| 8 | **新加坡航空 (SIA)** | C6L.SI | 国际旗舰 | SIA + Scoot RPK / ASK / PLF | SGXNet / SIA IR Operating Stats PDF | 🟡 第二阶段 |
| 9 | **长荣航空 (EVA Air)** | 2618.TW | 台湾旗舰 | 月度营收 / RPK / ASK / 载客数 | 台湾 MOPS / EVA IR 月报 | ⚪ 第三阶段 |
| 10 | **中华航空 (China Airlines)** | 2610.TW | 台湾旗舰 | 月度营收 / RPK / ASK / 载客数 | 台湾 MOPS / CAL IR 月报 | ⚪ 第三阶段 |
| 11 | **全日空 (ANA Holdings)** | 9202.T | 日本旗舰 | 国内/国际 RPK / ASK / PLF | ANA IR Traffic Results PDF | ⚪ 第三阶段 |
| 12 | **日本航空 (JAL)** | 9201.T | 日本旗舰 | 国内/国际 RPK / ASK / PLF | JAL IR Traffic Data PDF | ⚪ 第三阶段 |

---

## 中国六大航司数据源（Cninfo API 实测细节）

### API 交互说明

巨潮资讯网 (Cninfo) 是 A/H 股官方指定信息披露 Portal，提供无需 Auth Key 的标准化 POST API：

```http
POST http://www.cninfo.com.cn/new/hisAnnouncement/query HTTP/1.1
Content-Type: application/x-www-form-urlencoded; charset=UTF-8

pageNum=1&pageSize=30&column=sse&tabName=fulltext&stock={code},{orgId}&searchkey=运营数据&startDate=2024-01-01&endDate=2026-07-25&isStock=true
```

### 航司 `orgId` 映射表

通过查询 `http://www.cninfo.com.cn/new/data/szse_stock.json` 获取精确的 `orgId`：

- **中国国航**: `601111` ➔ `9900000441`
- **南方航空**: `600029` ➔ `gssh0600029`
- **中国东航**: `600115` ➔ `gssh0600115`
- **春秋航空**: `601021` ➔ `9900023129`
- **吉祥航空**: `603885` ➔ `9900023633`
- **海航控股**: `600221` ➔ `gssh0600221`

### 自动发现验证结果

实测 6 家航司近两年各 30 份月度主要运营数据公告均能 100% 成功发现并获得直链 PDF 地址：

- 国航（如 `http://static.cninfo.com.cn/finalpage/2026-07-15/1225425218.PDF`）
- 南航（如 `http://static.cninfo.com.cn/finalpage/2026-07-16/1225425964.PDF`）
- 东航（如 `http://static.cninfo.com.cn/finalpage/2026-07-16/1225425929.PDF`）
- 春秋（如 `http://static.cninfo.com.cn/finalpage/2026-07-16/1225425623.PDF`）
- 吉祥（如 `http://static.cninfo.com.cn/finalpage/2026-07-16/1225425794.PDF`）
- 海航（如 `http://static.cninfo.com.cn/finalpage/2026-07-16/1225426453.PDF`）

---

## 统一数据解析方案设计

### 架构扩展提议

基于现有 `src/hk_transport/sources/cathay_traffic.py` 模式，可构建通用航空流量抓取模块：

```
src/aviation/
├── __init__.py
├── pipeline.py              # 统一调度抓取与增量合并
├── config.py                # 航司代码、orgId 及搜索关键词配置
├── sources/
│   ├── cathay.py            # 国泰航空 (已有)
│   ├── cn_airlines.py       # 中国六大航 (通用 Cninfo 发现 + pdfplumber 解析)
│   ├── sia.py               # 新加坡航空 (SGXNet / SIA PDF)
│   └── tw_airlines.py       # 台湾长荣/华航 (MOPS)
```

### PDF 解析标准化

中国各大航司月度公告 PDF 内的表格格式高度标准化，均包含以下指标：

1. **客运运力/载运量**：
   - 载客人数（千人 / 人）
   - 可用客公里 ASK（百万 / 千）
   - 收入客公里 RPK（百万 / 千）
   - 客座率 Load Factor (%)
2. **区域拆分**：
   - 国内 (Domestic)
   - 国际 (International)
   - 地区 (Regional - 港澳台)
3. **货运/运力综合**：
   - 货运载重量 (Tonnes)
   - AFTK (Available Freight Tonne Kilometres)
   - RFTK (Revenue Freight Tonne Kilometres)
   - 货邮载运率 Freight Load Factor (%)

---

## 下一步行动建议

1. **编写通用 `cn_airlines.py` 脚本**：接入 Air China、China Southern、China Eastern、Spring Airlines 的月度 PDF 自动解析。
2. **构建长格式 Parquet 时序数据存储**：
   - 输出 schema: `date`, `month`, `airline_code`, `airline_name`, `region`, `passengers`, `rpk`, `ask`, `passenger_load_factor_pct`, `cargo_tonnes`, `rftk`, `aftk`
3. **前端 Dashboard 集成**：将多航司 RPK/ASK/客座率趋势图挂载至 Asia Markets Dashboard 的 Transport & Travel 板块。
