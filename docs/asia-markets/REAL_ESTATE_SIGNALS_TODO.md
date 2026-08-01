# 香港房地产 Signals TODO

**状态：** bounded SRPE pilot 已完成，并已接入 `hk-real-estate` dashboard；已完成 phase-level registry、PDF 下载/解析、hash 去重、Parquet/lineage、开发商月度 signals 和 quality checks。当前 dashboard 只展示六个明确登记的试点阶段，不代表全港开发商覆盖。

**2026-08-01 pilot 结果：** SRPE 的 JSON manifest 和 PDF 下载端点可用；最终 core run `2a390f89-439d-4619-b30c-c9ab0b8cfa1e` 覆盖 6 个 phase，解析出 2,892 条交易事件、1,585 个价单单位和 196 条项目月度 signals，18/18 文档 audit 成功。价单的“期数总住宅数”和当前价单释放单位必须分开保存。当前代码位于 `src/hk_real_estate/sources/srpe_pdf.py` 和 `src/hk_real_estate/srpe_pilot.py`，并保留 PDF hash、价单版本 key、取消／终止日期和持股比例调整后的 attributable sales。实时 manifest 已将旧 NOVO LAND 文件替换为新 document ID；PAVILIA FARM 的 `Tower Number / Flat` 版式也已纳入 parser。Crawl4AI 已作为独立可选工具安装，但不用于 SRPE 核心 ingestion；它只留给之后需要 JavaScript 浏览器的开发商官网抓取。

**第一阶段：** 香港住宅开发商项目 → 公司 → 收入／股价 signals

**第二阶段：** 地产代理交易及佣金收入代理 signal，复用第一阶段的成交事件层

## 1. 第一阶段范围

### 核心住宅开发商

| 股票 | 公司 | 纳入理由 | 当前项目映射状态 |
|---|---|---|---|
| `0016.HK` | 新鸿基地产 | 大型香港开发商，住宅、投资物业及酒店业务并存 | 已有 YOHO WEST、NOVO LAND、Towneria 等 registry 记录 |
| `0012.HK` | 恒基地产 | 大型开发商，住宅及投资物业组合 | 已有 The Henley、ONE INNOVALE、The Henderson 等 registry 记录 |
| `0083.HK` | 信和置业 | 住宅开发及投资物业，适合测试 JV 持股 | 已有 Grand Victoria（22.5%）、ONE ST. ANDREWS 记录 |
| `0017.HK` | 新世界发展 | 住宅、商业及综合项目，适合测试项目／SPV／合作开发 | 已有 PAVILIA FARM、K11 MUSEA 记录 |
| `1113.HK` | 长实集团 | 大型开发商，作为尚未进入当前 registry 的外部扩展样本 | 需要从官方年报及项目文件建立映射 |

### 混合型对照样本

| 股票 | 公司 | 为什么保留 |
|---|---|---|
| `0066.HK` | 港铁公司 | 物业发展项目与铁路客流并存，可验证地产 signal 不应覆盖公司的运输业务 |

暂不纳入第一阶段评分的股票：商业物业业主（`1972.HK`、`1997.HK`、`0014.HK`、`0101.HK`）、REIT、酒店公司及以内地物业为主的公司。它们需要不同的收入和资产模型。

## 2. 目标链条

```text
新盘／期数识别
  → 价单及销售安排
  → 单位成交、取消及剩余库存
  → 施工、开工及 Occupation Permit
  → 预计交楼时间
  → 开发商持股及可归属销售额
  → 财报收入确认窗口
  → 公司财务及股票回测
```

重要会计限制：预售合约金额不是当期收入。项目销售可以领先交楼及会计确认一年或更久；`handover` 只能先作为收入时间代理，不能直接标记为财报 revenue。

## 3. 数据来源及获取方式

### 已经存在、可以直接用于第一版 market signals 的数据

- CCL、MHPI、CCI、CRI、CSI、28Hse EPI／ERI：房价、租金、市场信心及周期。
- RVD 住宅价格／租金：官方住宅市场基准。
- Land Registry 月度一手／二手成交统计：成交数量、金额及市场流动性。
- HKMA Residential Mortgage Survey：按揭申请、批出、提取、LTV、利率组合及信贷质素。
- Buildings Department 历史供应及工程阶段：计划批准、Consent to Commence、开工通知、Occupation Permit。
- Housing Bureau 私人住宅供应：市场级已完成未售、兴建中及已批地未开工供应。

这些数据可以先形成住宅需求、成交流动性、按揭 impulse、供应压力等市场级 signals，但不能自动分配给某一家开发商。

### 需要新增抓取或解析的数据

#### A. 项目归属 registry

优先使用：

1. SRPE 法定销售文件及 development ID；
2. 上市公司年报／业绩公告中的项目、vendor、SPV、JV 及持股比例；
3. 屋宇署地址、permit number 及工程阶段；
4. 官方卖地及地契资料；
5. 28Hse 仅用于发现项目名称、别名及交叉核对。

每条归属记录至少要有：

```text
project_id
development_id
phase_id
marketing_name
legal_name
aliases
site_address
legal_vendor
spv_name
listed_parent
ticker
ownership_pct
effective_from
effective_to
source_url
evidence_level
last_verified_date
```

`legal_vendor／SPV`、销售代理和上市母公司必须分开保存。不能把销售代理名称直接当成开发商，也不能把 JV 项目 100% 归给单一股票。

#### B. SRPE PDF 文件及历史版本

SRPE connector 已经可以发现文件 metadata 和下载端点，但当前标准化数据还不是完整的单位级销售历史。第一阶段需要：

- 取得选定项目的价单、销售安排、成交登记及修订版本；
- 保存原始 PDF、下载时间、文件 hash、submission／printing date；
- 文本抽取优先，必要时才使用 OCR；
- 解析单位、面积、售价、折扣、成交日期、取消／终止状态；
- 保留每个价单版本，不能覆盖旧版本；
- 以 `development_id + phase_id + document_id + unit_id` 去重。

不要一开始抓取所有香港楼院。先针对 0016、0012、0083、0017、0066 的重点项目做小规模回溯，再决定是否扩大。

#### C. 屋宇署及交楼时间线

- 解析项目地址、permit number、工程阶段、单位数及楼面面积；
- 用项目 registry 的地址和 legal project alias 进行匹配；
- `EXACT`／官方别名匹配才能进入 production signal；
- `FUZZY` 只作研究提示，不得自动分配给股票；
- 保存每次月度快照，避免把后来修订的工程状态当成当时已知资料。

#### D. 公司财报及 HKEX 公告

- 补充项目持股、土地储备、合约销售、预计交楼及分部收入；
- 记录 publication time 和 effective／observation date；
- 将项目销售、交楼与财报的 property-sales revenue 分开；
- 从 financial-data sibling repo 复用财务历史及每日股价，但必须按公司分部和披露日期连接。

## 4. 住宅开发商事件表

事件类型建议包括：

```text
price_list_issued
price_list_revised
sales_arrangement
launch
unit_sold
unit_cancelled
construction_started
occupation_permit
handover_window
annual_report_update
```

每条事件至少保存：

```text
project_id
event_type
event_date
as_of_date
unit_id
units
saleable_area
price_hkd
source_document
source_url
parser_version
```

## 5. 第一阶段 signals

### 项目层

- **销售速度：** 7 日／30 日已售单位数及金额。
- **吸纳率：** 累计已售单位 ÷ 已推出单位。
- **实际 ASP：** 成交 ASP 与首发价单 ASP 的差异。
- **市场相对定价：** 项目 ASP 相对于同区 RVD／CCL／EPI 基准。
- **取消率：** 取消／终止数量 ÷ 已登记销售数量。
- **库存压力：** 未售单位 ÷ 过去 12 个月销售速度。

### 公司层

- **可归属合约销售额：** 项目成交金额 × 持股比例。
- **收入可见度：** 已售金额 × 预计交楼概率 × 持股比例。
- **交楼集中度：** 未来 12／24 个月预计交楼金额占可归属销售额的比例。
- **项目组合动量：** 同一股票旗下项目的销售速度、ASP 及库存压力加权汇总。
- **开发商 cycle signal：** 项目层信号与住宅价格、按揭及成交市场 signal 的组合。

第一阶段不直接估算精确项目利润。土地、建筑、销售营销及融资成本需要另外建立成本层；没有公司或项目级成本证据时，只输出收入／库存／交楼可见度，不伪造 margin。

## 6. 历史回溯策略

### 第一轮：近三年、重点项目

- 先覆盖当前仍有公开文件的重点项目；
- 建立完整的 project master 和事件时间线；
- 验证至少一个 JV 项目、一个多期项目及一个商业／综合项目；
- 将当时可见的文件版本与之后修订版本分开保存。

### 第二轮：向前扩展

- 从年报土地储备及历史项目表发现旧项目；
- 用 SRPE 历史文件补回价单和成交登记；
- 用屋宇署月报补回施工及入伙事件；
- 对缺失期间保留 null，不用当前状态倒填历史。

### 历史数据限制

- 市场级指数和土地注册处统计通常有较长历史；
- 项目级单位销售历史取决于 SRPE 的文件保留、期数及版本完整度；
- 公开资料不保证每个项目都有连续的月度收入或交楼数据；
- 只有完整保留的文件快照才可以用于 point-in-time 回测。

## 7. 验证门槛

- 每个纳入 signal 的项目必须有官方归属证据；
- 项目期数、SPV、营销名称和别名必须可以追溯；
- JV 项目必须保存持股比例及有效日期；
- 成交金额、单位数和 ASP 要通过至少一个官方或可复核来源校验；
- 销售、取消、施工和入伙事件不得混用 observation date 与 publication date；
- RVD provisional revision、Land Registry 注册滞后及按揭批出未必提取必须保留；
- 未匹配项目不能进入公司级 signal；
- 在有足够历史之前，只展示项目事件和当前快照，不宣称月度趋势。

## 8. TODO 清单

### 基础 registry

- [x] 审核当前 registry 记录及证据文件，并通过 registry contract 校验。
- [x] 为 0016、0012、0083、0017、0066 建立第一批重点项目映射；已补充 PARK YOHO NAPOLI → 0016。
- [ ] 加入 1113 的项目和 SPV 映射。
- [ ] 统一 project／phase／SPV／ticker 的稳定 ID。
- [ ] 增加 `evidence_level`、`effective_from`、`effective_to` 和 `source_url`。
- [ ] 建立 parent／subsidiary／JV 去重规则。

### SRPE 文件层

- [ ] 选定每家公司 1–3 个重点住宅项目。
- [x] 验证 development ID、期数及历史文件清单。
- [x] 下载并保存价单、销售安排和成交登记 PDF metadata。
- [x] 设计 PDF 原文、解析结果、文件 hash 和价单 version key 的存储关系。
- [x] 先解析 Grand Victoria 和 NOVO LAND Phase 3B 的交易登记；价单版本链和全量项目 backfill 仍待下一轮。
- [x] 实现 bounded CLI：`python3 -m src.hk_real_estate.cli run-srpe-pilot`，输出交易事件、价单单位、开发商月度 signals 和 document audit。
- [x] 用 unit-level active dedup 计算 sell-through；保留 raw contract-event counts，不把 PASP→ASP 更新重复计为新单位。
- [ ] 与 28Hse 的单位总数和状态做对账，但不把 28Hse 当作最终事实来源。

### 施工及收入时间线

- [ ] 将屋宇署地址和 permit number 连接到 project_id。
- [ ] 连接 plans approved、commencement、OP 和 handover window。
- [ ] 从公司年报补充财报收入确认窗口。
- [ ] 明确“合约销售”“交楼代理”“会计收入”三种日期和金额。

### Signal 与验证

- [ ] 计算销售速度、吸纳率、ASP、取消率和库存压力。
- [ ] 计算持股比例调整后的可归属合约销售额。
- [ ] 建立住宅市场 signal 与公司级项目 signal 的分层展示。
- [ ] 设定最小历史长度和 point-in-time 回测规则。
- [ ] 与公司披露的合约销售／分部收入做方向及时间验证。
- [ ] 再连接每日股价，测试未来 1／3／6 个月表现，而不是直接宣称因果关系。

### 第二阶段：地产代理

- [ ] 复用单位成交和 Land Registry 事件。
- [ ] 建立成交金额、成交量、新盘推出和按揭的代理收入 pulse。
- [ ] 补充代理市占率和佣金率假设，并单独标记估算值。

## 9. 第一阶段完成标准

第一阶段的 bounded 信号已经进入 dashboard；以下条件是扩展到更多开发商和项目阶段前必须满足的门槛：

1. 五家核心公司及港铁对照样本都有可追溯的项目 registry；
2. 至少一批重点项目拥有连续的价单／销售／施工事件时间线；
3. 所有公司级销售 signal 都经过持股比例调整；
4. 未匹配和低置信度记录不会进入正式 signal；
5. 历史回测使用当时可见的文件版本，不使用未来修订资料；
6. 能够解释 signal 如何连接到项目销售、交楼和公司收入，而不只是展示相关性。
