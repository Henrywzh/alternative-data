# 香港房地产 Signals TODO

**状态：** bounded SRPE pilot 已完成，并已接入 `hk-real-estate` dashboard；已完成 phase-level registry、PDF 下载/解析、hash 去重、Parquet/lineage、开发商月度 signals 和 quality checks。当前 dashboard 只展示六个明确登记的试点阶段，不代表全港开发商覆盖。

**2026-08-01 pilot 结果：** SRPE 的 JSON manifest 和 PDF 下载端点可用；最终 core run `2a390f89-439d-4619-b30c-c9ab0b8cfa1e` 覆盖 6 个 phase，解析出 2,892 条交易事件、1,585 个价单单位和 196 条项目月度 signals，18/18 文档 audit 成功。价单的“期数总住宅数”和当前价单释放单位必须分开保存。当前代码位于 `src/hk_real_estate/sources/srpe_pdf.py` 和 `src/hk_real_estate/srpe_pilot.py`，并保留 PDF hash、价单版本 key、取消／终止日期和持股比例调整后的 attributable sales。实时 manifest 已将旧 NOVO LAND 文件替换为新 document ID；PAVILIA FARM 的 `Tower Number / Flat` 版式也已纳入 parser。Crawl4AI 已作为独立可选工具安装，但不用于 SRPE 核心 ingestion；它只留给之后需要 JavaScript 浏览器的开发商官网抓取。

**最新 SHKP catalog / ownership review：** `run-shkp-catalog` run `cd17809a-0390-47e0-b4de-decf35b383f5` 已成功刷新 109 条 SHKP 目录、522 条 SRPE phase、71 条 listing-to-phase candidates、333 条 corporate-document links、8 条 interim pipeline evidence；规划 phase-hint 与项目网站证据刷新后的 ownership-review queue 为 128 条。新加入的 SHKP 2025/26 中期报告（截至 2025-12-31）将 Cullinan Sky / Cullinan Sky Mall 的 grouped project interest 记录为 100%，但仍不能拆分 Phase 1/2 或建立有效期间，因此不改变 `0016.HK` attribution gate。

**Review-only backfill：** 当前 union 为 5,332 条 register events、2,544 个 phase-scoped price-list units、40 条 document-audit rows（37 个成功下载、3 个明确 `not_available`）和 109 条 project-month status。Cullinan Harbour 9785/10405/11516 分别有 102/17/4 条成交登记；三个官方 manifest 均没有 `prices` payload，系统将其标记为 `price_list=not_available`，不把空值当作零库存或 parser success。

**可重复运行：** SHKP/SRPE catalog 现通过 `python -m src.hk_real_estate.cli run-shkp-catalog` 统一编排；`--offline` 只审计最新 normalized snapshots，live run 使用单一 run ID 写入 lineage。SRPE development-index 的 zero-row response 会被视为 source failure，不允许覆盖上一份有效 snapshot；这次 smoke test 产生的 partial empty run 已丢弃并恢复至上一份有效数据。

**2026-08-03 phase-specific ownership audit：** 针对当前 13 个重点 SRPE phase（Cullinan Sky 9366/11005、Cullinan Harbour 9785/10405/11516、Garden Regency 11554、Lime Spark 11505、Sierra Sea 11305/11345、YOHO WEST 9565/10585、YOHO HUB 7845/8525）完成了官方文件复核。结论是 **13/13 仍为 `ownership_attribution_ready=false`**：年报的 100% 是 SPV 或项目组的 reporting-date snapshot，`JV` 也没有给出 SHKP 的 attributable/profit-share；所有记录现在显式保存 `legally_continuous=false`、`effective_from/effective_to=null` 和 `interval_blocker`。因此本阶段不会把任何 review-only 成交额汇总到 `0016.HK`。

主要证据缺口已经明确：Cullinan Sky Phase 1/2 的 100% 只能由 Super Great 的 lot/SPV 证据和 grouped Sky/Sky Mall 行支持，不能拆 phase；Cullinan Harbour 1/2A/2B 虽共享 Well Capital vendor，但官方页面和年报仍是 grouped project/point-in-time evidence；Garden Regency 是最强的一对一候选但仍只有离散年度快照；Lime Spark 缺少 Tippon/Win Profit 的持股链；Sierra Sea、YOHO WEST 和 YOHO HUB 的年报／completion schedule 只确认 JV，未披露 phase-level percentage。项目网站页脚是当前 vendor/holding-company 身份证据，不是 ownership-effective-from 日期。

**土地注册处的可行性结论（2026-08-03）：** 土地注册处的历史／现有土地登记册和 memorial chain 理论上可以提供 lot 的登记业主、owner capacity、share、instrument nature 和 instrument date，但官方公开说明要求通过 IRIS 或柜台付费查册；没有可直接批量抓取的公开项目 ownership API。[官方查册说明](https://www.landreg.gov.hk/en/faq/faq_search_1.htm) [历史业主及登记册字段](https://www.landreg.gov.hk/en/faq/faq_search_2.htm) 因此下一步应以优先 lot（NKIL 6568、NKIL 6551、DD103 Lot 1071、TWTL 160、TPTL 253、TSWTL 23、YLTL 510）做小规模人工/授权 IRIS pilot，保存 `lot_no`、`memorial_no`、`instrument_date`、`registered_owner`、`share`、`instrument_type` 和查册订单/影像 lineage；即使拿到转让日期，也必须再将登记业主/SPV 与 SRPE phase 对齐，不能直接把土地登记 owner 当成上市公司 attributable percentage。

逐 phase 的证据、blocker 语义和 IRIS pilot 字段已另存为 [`REAL_ESTATE_SHKP_OWNERSHIP_INTERVAL_AUDIT.md`](REAL_ESTATE_SHKP_OWNERSHIP_INTERVAL_AUDIT.md)。

**可安全加入的未来项目 identity bridge：** Sha Po South → SRPE 11554 Garden Regency、Tsuen Wan West → SRPE 11505 Lime Spark；Tai Po Town Lot No. 244 的 Silicon Hill / University Hill Phase 1、Phase 2A、Phase 2B 已分别桥接到 SRPE 8405、8445、9245，YOHO WEST PARKSIDE / Tin Wing Stop Phase 2 → SRPE 10585，Cullinan Sky Phase 2 → SRPE 11005（官方 phase 名称、地址、网站或 schedule 一致）。另外新增了 A16 Station、Tung Chung Lot 55、STTL651、Fanling Lot 307、Hung Shui Kiu Lot 5、DD105 Lot 2091、DD104 Lot 4805、3 Fat Tseung Street 等 lot-only pending candidates；Lot 4354、KIL11273、MEGA IDC 则明确排除在 SRPE 住宅队列之外。上述桥接只解决身份，不改变 ownership gate。

**2026-08-03 statutory-notice parser refresh：** YOHO WEST 9565 / YOHO WEST PARKSIDE 10585 的官方项目页现在能正确解析多段法定角色：MTR Corporation 为 Owner，Best Vision Development 为 Person so engaged，Better Sun／Time Effort／SHKP 为后者的 holding companies；PARKSIDE 还显示预计 material date。该证据改善 phase identity/JV 解释，但仍是 current-page statutory role evidence，不是 SHKP equity percentage 或 ownership-effective interval，因此两个 phase 继续保持 `annual_jv_unresolved`。

**2026-08-03 planning phase-hint refresh：** LandsD/TPB crosswalk 现在只在官方 lot/name 文本明确出现 phase token 时收窄候选：NKIL 6568 → Cullinan Sky P1/P2、NKIL 6551 → Cullinan Harbour P1/2A/2B、TSWTL 23 → YOHO WEST P1/P2、YLTL 510 → YOHO Hub B/C。合并或无 phase 的行仍保留 ambiguous；该修正改善 identity/date linkage，不改变 ownership 或 sales gate。当前 planning crosswalk 为 1,094 行，review queue 为 128 行。

**30-phase statutory/official role layer：** `shkp_phase_role_evidence` 现在覆盖 30 个 SRPE development IDs：原有 13 个 priority phases，加上 NOVO LAND、Wings at Sea、Wetland Seasons Bay、Cullinan West、Victoria Harbour 和 Sierra Sea 的官方项目/SHKP Quarterly/SHKP Club promotion 角色或 phase-identity evidence。所有行的 `ownership_pct`、`effective_from`、`effective_to` 都是 null，grouped notice 仍为 blocked，避免把角色身份误当成 SHKP 经济权益。

**2026-08-03 attribution gate hardening：** `ownership_attribution_ready` 现在必须同时满足 `consistent_numeric`、phase-specific `ownership_effective_from` 和 `ownership_effective_to`、可验证的 numeric ownership（且区间百分比必须与年报／curated numeric snapshot 一致），以及非 blocked promotion status。旧 normalized snapshot 或手工传入的 ready flag 如果缺少完整有效区间或百分比不一致，会被 eligibility/plan 二次降级为 `ownership_review_required`；因此任何销售 PDF 都不能仅凭“100% snapshot”进入公司归属汇总。

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

### SHKP historical universe discovery（2026-08-08）

- 已接入新鸿基官方 `History and Milestones` 页面：
  `shkp_history_milestones` 当前有 112 条里程碑记录，覆盖 1972–2025、52 个
  年份。页面原文（一次里程碑可同时提到多个项目）和图片 URL 均保留；这是
  历史项目发现／别名对账证据，不是 phase-level ownership 或完整项目清单。
- 已新增 `shkp_history_milestone_identity_crosswalk`：以严格的 normalized
  phrase containment 把里程碑映射到 SRPE candidate，当前 135 行（99
  unmatched、28 ambiguous、8 matched-needs-review）。phase name 优先于
  development name；同名多期全部保留为 ambiguous，不会提升 ownership 或
  sales attribution。历史 roster build 已同时落盘这张 crosswalk，并在
  521-row roster 中保留每个 phase 的里程碑年份、摘要及 match status。
- SRPE inactive phase 的 manifest backfill 已改为增量合并；新增
  `--include-unobserved` 后，可以把没有既有 SHKP evidence 的 inactive phase
  作为 discovery-only routing candidate，不会提升 ownership。
- 历史 transaction backfill 也改为增量合并，并优先选择尚未审计的
  transaction-register phase；旧批次不会因下一批写入而从 latest snapshot 消失。
  2026-08-08 完成最后一批后，latest snapshot 有 36,493 条以
  `transaction_id` 去重的 gross events，覆盖 145 个 phase、2,365 条
  project-month rows，以及 155 个 phase quality-audit rows。质量状态为 59 个
  `gross_event_ready`、86 个 `gross_event_ready_with_date_gaps` 和 10 个
  `register_parsed_zero_rows`；exact/composite duplicate 均为 0。所有 rows 仍是
  routing-only，未进入 `0016.HK` attributable sales。manifest coverage audit
  已覆盖全部 161 个 inactive phase（155 个有 transaction-register metadata，6 个
  为其他官方文件类别），因此 inactive 未探测数为 0；521-row parent roster
  中仍有 360 个 active/current rows 尚未通过历史 manifest 路由，统一标为
  `not_observed`。roster 现在同时保存 `historical_manifest_status`、历史
  register/price/sales-arrangement/brochure 行数和 transaction backfill 状态；
  它们与 live/current 的通用 `manifest_status` 分开，避免把历史已探测误显示为
  `not_loaded`。同时，roster build 现在会读取当前
  `shkp_srpe_document_manifest`；最新 snapshot 中 10 个 current/pilot phase
  标为 `filings_available`，其余 511 个标为 `not_loaded`，不把未加载误当成
  无官方文件。
- offline catalog audit 现在将 `srpe_development_index` 和
  `shkp_historical_annual_report_index` 的独立 backfill lineage 显示为
  `usable_with_unscoped_source_inputs`，而不是误报整个 catalog 为 incoherent；
  任何真正 mixed catalog run 仍会 hard-block。该 warning 不会打开 ownership
  promotion，当前 13 个 priority phase 仍是 0 个 approved。
- 当前 SHKP residential-directory crosswalk 的 53 个候选 SRPE phase 已完成
  metadata-only manifest backfill，新增独立 dataset
  `shkp_current_srpe_document_manifest_backfill`：6,325 条官方文件 metadata，
  包括 53 个 transaction registers、1,095 个 price-list、2,919 个
  sales-arrangement 和 2,258 个 brochure rows。它与 live catalog run 分开保存，
  roster rebuild 时 union；没有下载/解析 PDF，也没有提升 ownership。
- 现有 candidate-routed transaction scratch batches 已重新跑 signal contract：
  56 个 candidate phase、30,124 条 semantic-deduplicated transaction events、
  3,265 条 phase-month rows，56/56 phase audit 为 `success`。所有 phase 的
  `ownership_review_status` 仍为 `blocked_interval_missing`；因此这是完整的
  phase-level leading-indicator/transaction entry，不是 SHKP attributable sales。
- 521-row roster 现在另存 `ownership_evidence_level`、
  `ownership_evidence_source_count`、`ownership_evidence_promotion_status` 和
  `ownership_next_evidence`。当前分布为 424 个 `srpe_parent_only`、69 个
  `numeric_snapshot_or_grouped_interest`、28 个 `phase_or_project_identity_only`；
  这层只描述证据完整度，不会把 snapshot、JV 或网站角色提升为 ownership。
- 另外持久化了一张一行一 phase 的
  `shkp_historical_phase_evidence_coverage`（521 行）审计表，把上述
  ownership/evidence 状态、current/historical manifest 状态和交易 backfill
  状态放在同一个 review surface；它是 roster 的投影，不是第二套归属逻辑。

### Historical-universe completion audit (2026-08-08)

The bounded SHKP historical-universe objective is complete as a
discovery/evidence and transaction-routing layer:

- 521/521 SRPE parent phases are present with unique stable IDs and lineage;
- the current SHKP catalog has 109 rows, with 71 residential crosswalk rows
  resolving to 53 candidate phases;
- historical annual-report evidence has 312 project rows and 420 crosswalk
  rows, while History and Milestones has 112 rows and 135 identity-crosswalk
  rows;
- current candidate manifests cover 53 phases and historical inactive manifests
  cover 161 phases; both are append-only metadata layers with no PDF/ownership
  inference hidden inside them;
- candidate-routed transaction entry covers 56 phases / 30,124 deduplicated
  events / 3,265 phase-month rows, and historical inactive backfill covers 145
  event-bearing phases / 36,493 events / 2,365 phase-month rows;
- the 521-row evidence coverage audit makes every ownership state explicit.

This completion statement does **not** mean that SHKP attributable sales are
approved. The separate ownership-promotion gate remains intentionally closed
until dated, phase-specific SPV/JV/IRIS evidence is reviewed.

### SHKP high-recall phase universe + practical financial vintage layer（2026-08-09）

这次把“56 个 phase”重新定义为交易路由 slice，而不是 SHKP 全部项目。SRPE
完整 parent index 有 521 个 stable phase ID，历史成交层目前有 197 个有事件记录
的 phase。新增 `shkp_high_recall_phase_candidates` 对 521 个 phase 使用已有的
SHKP 官方目录、年报、History and Milestones、completion schedule、pipeline 和
项目网站证据做高召回分类：24 个 `likely_shkp`、163 个
`possible_shkp_high_recall`、334 个 `identity_unknown_owner_evidence_missing`。
最后一个状态只表示暂时没有观察到 SHKP 证据，不能解读成“不是 SHKP”；其中 53
个 phase 已经有 SRPE transaction-register route。所有高召回结果都保持
`strict_ownership_promotion_status=blocked_high_recall_identity_only`。

重建后的 all-history signal 仍是 5,604 行、197 个 phase；高召回身份层把 403 行
从原先的 `not_observed` 细分为 `indicative_identity_only`，剩余 1,808 行仍是
真正没有 SHKP 证据的 `not_observed`。2,637 numeric stake 行和 756 JV gross 行
继续进入粗略 sales model；identity-only 行只用于 web review，不折算金额。

财务侧新增 `shkp_financial_model_practical_vintages`（1,870 行）：1,702 条
actual observations（3 个抓取快照）、61 条 consensus statistics（1 个 snapshot）
和 107 条 broker forecast metric rows（7 个 forecast dates）。actual 缺少原始公告日
时标为 `fetched_at_snapshot_proxy`，consensus 用 `provider_snapshot_date`，broker
用 `broker_forecast_date`。这是可用于粗略历史比较的 append-only snapshot 层，不是
严格 PIT tape；内地项目收入继续排除在香港模型之外。

### Indicative ownership layer (research-use, non-legal)

Because the immediate research question is whether a project is plausibly SHKP,
the repository now has a separate `shkp_indicative_ownership_roster`. It uses
current-directory exact matches, annual/completion-schedule Group-interest
snapshots and explicit JV wording. It does **not** modify strict ownership
fields. The current 521-row distribution is 69
`likely_shkp_numeric_snapshot`, 24 `likely_shkp_jv_unquantified`, 4
`possible_shkp_review` and 424 `not_observed`.

`run-shkp-indicative-signals` applies only the numeric indicative percentages to
the 4,196 current phase-month rows and saves
`shkp_indicative_project_month_signals`. The latest output has 3,106
numeric-status rows, 655 unquantified-JV rows, 435 identity-only rows and
2,461 rows with an indicative contract-value estimate. These are rough research signals, not
attributable revenue or legally verified ownership.

The indicative ownership contract also keeps the observed numeric range and a
consistency label. Values differing by no more than 0.5 percentage points are
treated as rounded-consistent snapshots and use the median only for the rough
model; larger conflicts remain explicitly non-numeric. This is a modelling
convenience, not an effective ownership interval, and strict promotion remains
blocked.

`run-shkp-all-history-signals` now materializes a separate merged layer,
`shkp_srpe_project_month_signals_all_history` and
`shkp_indicative_project_month_signals_all_history`. It combines the 4,196-row
current candidate grid with the 2,365-row sparse historical backfill, resulting
in 5,604 phase-month rows across 197 phases after one overlapping phase-month
deduplication rule (current candidate rows take precedence). The historical
layer contributes 27 numeric-snapshot rows and 101 JV rows; 2,211 rows remain
identity-unknown and are excluded from indicative SHKP totals. Missing months
in historical registers are retained as unobserved sparse coverage, not filled
with zero. The sales model uses this all-history layer when present.

The current SRPE contract also writes `shkp_srpe_transaction_date_gaps` and
adds date-gap fields to `shkp_srpe_signal_coverage`. Events without PASP are
quarantined rather than silently assigned to their ASP month; events with PASP
but no ASP remain in the raw event layer and are flagged for source-quality
review. The latest refresh has 276 date-gap events (8 missing PASP with ASP
observed; 268 missing ASP with PASP observed), so the strict month grid and
indicative sales model remain conservative.

### Indicative SHKP sales/growth model (research-only, 2026-08-08)

`run-shkp-indicative-sales-model` now aggregates the indicative signal layer
into nine separate normalized outputs:

- `shkp_indicative_sales_model_monthly`: monthly numeric-stake value/units,
  JV gross value/units, low/base/high JV-adjusted totals, calendar YoY and
  gap-aware rolling 3/12-month fields;
- `shkp_indicative_sales_model_scenarios`: long low/base/high rows for charts;
- `shkp_indicative_sales_model_annual`: calendar-year sums with partial-year
  flags so an incomplete 2026 is not silently compared with a full year;
- `shkp_indicative_sales_model_validation`: directional comparisons with
  disclosed property-sales revenue, expected-recognition backlog and interim
  contracted sales;
- `shkp_indicative_sales_model_quarterly_reconciliation`: monthly model sums
  over the issuer's explicit annual/interim attributable contracted-sales
  intervals. Only anchors explicitly marked `sales_scope=hong_kong` are used;
  group-total or scope-unknown figures are retained as excluded evidence. The
  output does not manufacture a calendar-quarter reported series;
- `shkp_indicative_sales_model_universe_coverage`: the 521-phase high-recall
  roster joined to model-signal and transaction-event coverage. The latest
  run has 24 likely phases with signals, 69 possible phases with signals, 111
  identity-unknown phases with signals (excluded from attribution), and 317
  roster-only phases without a signal or route. This is a routing audit, not a
  negative ownership conclusion;
- `shkp_indicative_sales_model_forecast`: FY2026/27 mechanical growth × JV
  sensitivity combinations;
- `shkp_indicative_sales_model_project_coverage`: separate current-listing and
  future-pipeline coverage audit;
- `shkp_indicative_sales_model_phase_summary`: cumulative phase-level numeric,
  JV-gross and scenario totals plus latest active-unit state;
- `shkp_indicative_sales_model_coverage`: input coverage, unknown/uncovered
  rows and the assumptions used.

The default JV sensitivity is 25% / 50% / 75% (low/base/high). Numeric
snapshot stakes are held fixed across those scenarios; only unquantified JV
gross activity changes. `not_covered`, `not_observed` and identity-only rows
are kept visible in the audit and excluded from the estimated SHKP total. The
model is a gross SRPE contract-activity proxy: contract updates, resales and
register-version limitations mean it is not recognized revenue, cash flow or
legal ownership attribution. The strict ownership gate remains closed.

### Indicative model validation and rough forecast (research-only, 2026-08-08)

The same CLI run now also writes `shkp_indicative_sales_model_validation`,
`shkp_indicative_sales_model_quarterly_reconciliation` and
`shkp_indicative_sales_model_forecast`. Validation is deliberately directional,
not an accuracy score: the historical comparison is against SHKP's segment
property-sales revenue (a recognized-revenue measure), while the FY2025/26
cross-check also uses the disclosed HKD 30.1bn expected-recognition backlog and
the HKD 17.4bn 1H2025/26 contracted-sales disclosure.

The latest normalized run (`shkp-indicative-sales-model-94460ebc-c577-47ed-a0eb-c7d15d158013`) has a FY2025/26 base activity proxy of HKD 30.353bn versus the disclosed HKD
30.100bn expected-recognition figure (100.84% ratio), but the matching number
is not independent validation because timing, phase coverage, JV scope and
contract-event semantics differ. Against recognized property-sales revenue,
the base proxy/revenue ratio ranges from 54.4% to 97.3% in FY2021/22–FY2024/25
(20.8% in FY2020/21); this is consistent with a directional leading indicator,
not a revenue reconstruction. The same-window 1H2025/26 proxy is HKD 12.785bn
versus HKD 17.4bn disclosed contracted sales (73.5%).

The latest issuer-interval reconciliation has three explicit Hong Kong
anchors: 1H FY2023/24 (HKD 12.9bn), FY2024/25 (HKD 42.3bn) and 1H FY2025/26
(HKD 17.4bn). The model/base ratios are approximately 43.5%, 73.4% and
73.5%, respectively. These are coverage/timing diagnostics, not accuracy
scores; four group-total or scope-unknown anchors were deliberately excluded
from the Hong Kong comparison.

The rough FY2026/27 forecast starts from the latest complete FY2025/26 model
year and applies the latest four full-year base-growth observations' 25th/50th/
75th percentiles (-13.7% / +13.8% / +49.3%) separately from the 25%/50%/75% JV
ownership sensitivities. It is a mechanical research range, not guidance or
consensus, and unlinked future projects are not added to the numeric formula.

`shkp_indicative_sales_model_project_coverage` records the separate universe
audit: current website-listed residential projects have broad document routing,
while future disclosure labels remain only partially phase-resolved. It must
not be summarized as one all-project coverage percentage.

The broader future-identity evidence layer currently has 36 rows, with 16
linked to an SRPE ID and 20 still lacking one. It is useful for routing future
research, not evidence that all future SHKP residential phases are covered.

### SRPE historical boundary

SRPE is not a pre-2013 Hong Kong residential archive. The SRPA and SRPE were
created for the Residential Properties (First-hand Sales) Ordinance, which
came fully into effect on 29 April 2013. Our current all-development index
therefore begins at 2013-06-11 and has no pre-2013 SRPE brochure/register
contract. Post-2013 projects that stopped sales remain discoverable through the
historical/18-month route, but SRPA terms allow information to be omitted,
suspended or edited.

For SHKP projects before 2013, use annual reports and corporate history, HKEX,
developer archives, RVD/Land Registry or market-data sources. A pre-2013 phase
absent from SRPE should be tagged `srpe_not_applicable_pre_ordinance`, not
`not_observed` or zero sales; unit-level SRPE transaction backfill is not
available for that period.

### Commercial and Mainland coverage audit (2026-08-08)

The residential signal model is now explicitly separated from the recurring
commercial and Mainland research layers. `run-shkp-commercial-recurring`
materialises:

- `shkp_commercial_recurring_facts`: 36 FY2024/25 and FY2025/26 interim
  office/retail/hotel/property-investment period facts. They include the
  disclosed Group/JV scope but are not an asset-level monthly rent roll.
- `shkp_commercial_pipeline_capacity`: 8 named office/mall capacity rows with
  opening/completion windows. These are capacity-only; no rent, NOI, valuation
  or legal ownership interval is inferred.
- `shkp_commercial_market_context`: 2,406 RVD office/retail market-index rows.
  These are Hong Kong market context, not SHKP same-store rent data.
- `shkp_commercial_recurring_coverage`: source-by-source coverage rows for the
  24 office, 27 mall, 10 hotel and 3 serviced-suite catalogue entries, report
  period facts, completed-property GFA exposure, named capacity and RVD
  context. Duplicate coverage IDs are rejected by tests.

The same command writes `shkp_mainland_project_coverage`. Current and
historical annual reports provide 9 and 68 Mainland project rows respectively,
with report-period Group-interest/GFA evidence, while recurring facts and
disclosed backlog remain aggregate geography/segment anchors. The current SRPE
phase-month layer contributes **zero Mainland project transaction rows** because
its scope is Hong Kong first-hand residential; that is recorded as
`not_covered`, never as zero Mainland sales. LandsD/TPB planning sources are
Hong Kong-only in this repository. A project-level Mainland sales feed remains
the next source gap (developer Mainland site, mainland filings/project
portals, and report-vintage sales disclosures).

### SHKP Quarterly + Hong Kong commercial control tranche (2026-08-08)

The first Hong Kong-only commercial branch is now ingested separately from the
Mainland research layer. `python -m src.hk_real_estate.cli
run-hk-commercial-controls` writes ten run-scoped datasets:

- `shkp_quarterly_events`: 244 issuer quarterly-article headline rows from
  2021Q3–2026Q2; the dashboard keeps 79 property-relevant rows. The parser
  classifies event type, asset class and geography from the headline and keeps
  issuer/quarter-end date semantics. It does **not** download or interpret PDF
  body text, so these are dated event-context rows, not quarterly sales, rent,
  occupancy or earnings facts.
- `shkp_quarterly_numeric_facts`: the latest bounded 24-document HK subset
  produced 43 explicit numeric facts (units, square feet, property rates,
  retail-store counts, lease term and one nominal HKD land-rent fact). Each row
  retains the source PDF, page, evidence sentence and extraction confidence.
  This is deliberately a sparse event-fact layer, not a quarterly KPI series;
  PDFs with no interpretable numeric fact remain observed documents with zero
  extracted facts rather than being filled with zero.
- `shkp_commercial_asset_master`: 132 HK commercial asset observations across
  the current SHKP directory, FY2024/25 completed-property exposure and three
  completion-schedule snapshots. The same `asset_id` can appear in multiple
  source layers; this is an observation master, not a legal title/ownership
  master and not an asset-level NOI/rent roll. Completion-schedule GFA parsing
  now explicitly stops before the trailing `Others` subtotal; the regression
  test prevents concatenated impossible areas.
- `rvd_office_vacancy_annual`: 328 annual grade/total rows from 1985–2025;
  `rvd_office_stock_vacancy_district_annual`: 136 annual district rows
  (2023–2024); `rvd_commercial_stock_vacancy_district_annual`: 118 rows
  (2023–2024); and `rvd_commercial_forecast_completions_annual`: 45 rows
  including the future 2026 forecast horizon. These are market controls, not
  SHKP pipeline or asset performance. The forecast is labelled Catalog because
  future dates are intentional.
- `cnsd_retail_sales_control_monthly`: 13,050 economy-wide retail value/volume
  index observations from 2004-10–2026-06. It is a demand control, not tenant
  sales at an SHKP mall.
- `tourism_hotel_occupancy_category_monthly` and
  `tourism_hotel_adr_category_monthly`: 180 category-month observations each
  from 2021-06–2026-05; these are industry hotel controls, not SHKP hotel KPIs.
  `tourism_hotel_rooms_category_monthly` has 148 rows through 2024-06 only and
  is explicitly marked `Stale`/`Catalog` until the publisher updates the file.

The dashboard adds the Quarterly property-event table, Quarterly numeric-fact
evidence table, HK commercial asset master table and the
`shkp_hk_financial_bridge` evidence table, alongside RVD vacancy/forecast,
C&SD retail-control and tourism occupancy/ADR views. The financial bridge
combines selected official group/segment facts, Hong Kong recurring portfolio
facts, source-selected `0016.HK` actuals, current consensus and PIT diagnostics;
it keeps row types separate and deliberately does not create a synthetic
SHKP Hong Kong revenue series. Mainland project sales remain out of scope for
this tranche.

The first Hong Kong-only sales-to-handover timing bridge is now materialized as
`shkp_sales_handover_revenue_bridge`, `shkp_sales_handover_revenue_annual` and
`shkp_sales_handover_revenue_coverage`. It covers 197 phase/scope rows (56
current-candidate phases and 141 historical-inactive routes), 26 fiscal-year
diagnostic rows and two scope-level coverage rows. The phase layer keeps gross
SRPE activity, annual-report `handover_completed` evidence, completion-schedule
windows and the current Buildings Department OP crosswalk in separate fields;
the annual layer places issuer property-sales revenue and HK contracted-sales
backlog beside gross activity without allocating revenue to a phase. The latest
current-candidate snapshot has 46 phases with indicative numeric stake clues,
22 with annual-report handover evidence, 41 with completion-schedule evidence
and four with a current BD OP crosswalk match. All phase-level revenue
allocation remains zero by policy. Missing months are not zero-filled, and a
BD OP row currently has no event date in the crosswalk, so this is a timing and
coverage monitor rather than a revenue model.

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
- [x] 为 SHKP future-pipeline labels 建立 non-promoting lot/phase identity evidence；明确区分 SRPE residential phase 与商业 BOT 项目。
- [ ] 为每个 legal vendor/SPV 补齐可审计的 `effective_from`／`effective_to`（或覆盖完整销售月份的连续正式披露）；在此之前保持 `blocked_effective_interval`。
- [ ] 单独取得 Cullinan Sky Phase 2 的法定 vendor notice，以及 Harbour 2A/2B 的 single-phase、带日期 ownership evidence；不能复用 grouped-phase 页脚。
- [ ] 对 NKIL 6568、NKIL 6551、DD103 Lot 1071、TWTL 160、TPTL 253、TSWTL 23、YLTL 510 做一轮付费 IRIS 历史／现有土地登记册 pilot；保存 memorial/instrument dates 和 registered-owner chain，再与 SRPE phase 对齐。
- [x] 建立 IRIS/Land Registry evidence-only importer；title evidence 强制保持 `blocked_land_registry_owner_only`，不能直接进入 legal ownership 或 sales attribution。
- [ ] 建立独立的 `approved_phase_attribution_decision` review layer；只有该 layer 同时具备 phase identity、独立 SPV/JV economic evidence、numeric pct、bounded interval、continuity basis 和 reviewer sign-off 时，才可将 phase 放入 sales plan。
- [x] 将 SHKP/SRPE catalog 的 live/offline runner 接回 CLI，并为 SRPE zero-row response 加入 fail-safe，避免空数据刷新抹掉有效项目 universe。

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
- [x] 连接 annual-report handover table、completion schedule window 和当前 BD OP crosswalk（保留各自 date semantics；未把预计窗口当作已交付）。
- [x] 已建立独立 `bd_project_lifecycle_history` scratch parser/runner；全月 run `c752686d-aace-4dcb-8f24-12336d5ee004` 已回填 17,517 个项目行，覆盖 2005-01 至 2026-05 的 257 个已发布月份，并保留 `digest_month`、revision status、source page 与 PDF lineage。v6 修复申请人栏位截断，并通过 `run-bd-project-history-local-reparse` 使用全部既有 raw PDF 重跑；官方月报不提供 OP/permit 的精确事件日；2026-06/07/08 尚无官方直链，保持为未覆盖而非零。
- [x] 建立并刷新 research-only `shkp_bd_history_crosswalk`：full monthly BD history 与 71 个 SHKP/SRPE candidate rows（53 个 unique development IDs）的 normalized-address 连接现在有 48 个 ID 命中、220 个历史行；198 行因同址多 phase 保持 `ambiguous`，22 行是单 phase 地址命中但仍需 review，5 个 candidate unmatched。最新 crosswalk run `9f639a88-e4f3-4c02-9ed9-241b75ecaae1`。重复月份／阶段行不再被误标成 ambiguity；Hoi Ying Road／Lohas Park 的 phase-group ambiguity 继续 blocked。
- [x] 将 address-only crosswalk 压缩成 `shkp_bd_history_entity_resolution_review_queue` 与 run-level summary：53 个 unique phase IDs（来自 71 个 candidate rows），48 个有地址命中、43 个 P0 同址歧义、5 个 P1 单 phase review、5 个 P2 unmatched；所有行仍强制 `blocked_address_only`。这是 review routing，不是 permit 或 ownership attribution。
- [x] 新增 `shkp_bd_phase_group_evidence`：最新 entity-review run `shkp-bd-history-entity-review-e7ad2448-af42-4718-816f-9c9dffe91889` 产出 23 个 address groups，覆盖全部 53 个 phase（14 个 shared-address、6 个 single-phase control、3 个 unmatched）；其中 17 个 group 有官方 SHKP completion-schedule 的 phase/lot 分组线索（如 NOVO LAND 1A/1B、2A/2B、3A/3B，以及 Sierra Sea 1A(2)/1B、2A/2B）。group 层去重 phase×BD 复制，保留 permit/applicant/stage、permit year、SRPE first-publication order 和 schedule grouped context；这些顺序和分组只作研究线索，不能当作 permit start bound 或 phase-to-permit mapping，也不打开 attribution gate。
- [x] 对 56 个 SHKP/SRPE candidate 逐一 probe 官方项目网站，并对 JS/error rows 做浏览器 fallback；review queue 保留 raw probe 的 31 个 role-field `site_named_shkp`、7 个 `page_named_shkp`、12 个无关键词和 3 个未评估结果，并接入 55 个 curated official role-evidence rows，覆盖 53 个 phase IDs。项目归属证据与 BD phase 匹配仍保持分离。
- [x] 对剩余 334 个 high-recall unknown phases 做一轮快速官方项目网站核查；静态 pass 覆盖 334/334（155 usable、92 short/JS、86 error、1 无 URL），发现 2 个 statutory role-field SHKP 命中和 1 个 page-level keyword 命中。再对全部 333 个可用 URL 用 Crawl4AI 0.9.2 做完整慢渲染观察（235 成功、98 失败），完整浏览器层仍只有 2 个 statutory role-field SHKP 命中（LE PALAIS、No.3 Repulse Bay Road）和 2 个普通 page keyword（ELIZE PARK、THE KNIGHTSBRIDGE）；后两者的 Vendor/Holding Companies 不支持 SHKP 归属。无关键词/失败均不作非 SHKP 结论。结果落盘到 `shkp_unknown_phase_site_evidence`、`shkp_unknown_phase_identity_review` 和独立的 `shkp_unknown_phase_crawl4ai_evidence`，所有 ownership/sales gate 继续 blocked。
- [x] 对完整浏览器层剩余 98 个失败 URL 做低并发慢重试（30 秒 page timeout、8 秒 post-load wait）；15 个页面恢复，83 个仍失败，其中 38 个 DNS、36 个 anti-bot/403/script shell、5 个 timeout、2 个 TLS、1 个 connection refused、1 个 unreachable；没有新增 SHKP role hit。失败主要是域名／反爬覆盖缺口，不再继续无上限等待；结果独立落盘到 `shkp_unknown_phase_crawl4ai_retry98_evidence`。
- [ ] 对 86 个 fetch-error、92 个 short/JS rows 继续按价值排序做少量人工／浏览器复核；优先有 transaction-register route、近期 active phase、或站点能明确显示 Vendor／Holding Companies 的项目，不做无上限全站重试。
- [x] 将 crosswalk 压缩成 `shkp_bd_phase_resolution_candidates`：最新 run `shkp-bd-history-entity-review-e7ad2448-af42-4718-816f-9c9dffe91889` 产生 223 个 `phase × permit/stage/address/applicant` review clusters（198 个 P0 shared-address、20 个 P1 single-phase、5 个 P2 unmatched）；重复 digest rows 只作观察计数，不累加单位数。v6 raw-PDF reparse 后，`bd_applicant_quality_status` 为 207 个 observed text、11 个 suffix-only/truncated、5 个 missing/not published；ownership／permit attribution 仍为 `blocked_address_only`。
- [x] 新增 `shkp_bd_phase_permit_candidate_evidence`：entity-review run `shkp-bd-history-entity-review-e7ad2448-af42-4718-816f-9c9dffe91889` 产出 131 个 `phase-group × schedule-context × BD-cluster` 候选（100 个 P0、26 个 P1、5 个 P2），其中 49 个有更窄的官方 completion-schedule phase-group 语境，并把 55 个 curated SHKP phase-role evidence（覆盖 53 个 phase IDs）、SRPE/SHKP 项目页及 BD PDF page/source 链接放在同一 review surface。进一步读取既有本地 BD detail PDF（不联网）后，62 行有 page-level phase token：10 行所有 token 都在当前 candidate set、51 行含有 candidate set 外 token、1 行没有可比较的 candidate phase number；64 行没有 token、5 行未评估。`bd_pdf_unmatched_phase_tokens` 与 `bd_pdf_token_coverage_status` 记录相对当前候选集的 token 缺口（其中部分只是同一 address group 的另一 phase，只有没有 group match 时才是更强的 SRPE universe 缺口线索），不把其自动降级为合法 phase mapping。该表只缩小 primary-document review 范围，不分配 permit、不把 Group's Interest/JV 当作 phase ownership；两条 promotion gate 全部保持 `blocked_address_only`。
- [x] 新增 `shkp_bd_phase_permit_reconciliation`：最新 run `shkp-bd-history-entity-review-e7ad2448-af42-4718-816f-9c9dffe91889` 把上述 131 条 candidate evidence 按 primary BD PDF／official schedule 语境分类为 10 条单 phase concordant、3 条多 phase set concordant、7 条 narrowed、16 条 cross-group pointer、2 条 same-family phase-variant review、24 条 label-format review、10 条 official-schedule phase set needing primary PDF、54 条无 phase token和 5 条仅 schedule/address context。另有 20 条显式 `phase_context_supported_not_assigned`、16 条 `phase_context_points_to_other_group_phase_not_assigned`、2 条 `same_family_phase_variant_review`、83 条 `unresolved_primary_document_context`；这些状态只表达 review evidence strength，`resolved_phase_candidate_ids` 仍表示研究候选集，不表示 permit assignment；ownership／permit gates 全部保持 `blocked_address_only`。
- [x] 将 `shkp_indicative_ownership_roster` 与 curated `shkp_phase_role_evidence` 对齐到同一 candidate/reconciliation review surface：131 行中 71 行为全候选 phase 的 numeric snapshot、60 行为全候选 phase 的未量化 JV；每行均保留 role-evidence count。单 phase 才填直接 numeric pct/range，多 phase context 保留 `indicative_phase_ownership_context_json`；这只是 rough-model/review context，`strict_ownership_attribution_ready` 仍全部为 false。
- [x] 新增 `shkp_bd_phase_ownership_review`：最新 run `shkp-bd-history-entity-review-e7ad2448-af42-4718-816f-9c9dffe91889` 逐 phase 汇总 53 个 SHKP/SRPE IDs；44 个为 numeric snapshot review-only、9 个为未量化 JV review-only。phase-context 状态为 2 个 supported-only、19 个 supported-plus-unresolved、3 个 other-group、2 个 same-family variant、27 个 unresolved。该汇总只用于 review/rough model，不把 shared-address rows 相加或分配，53 行仍保持 `blocked_address_only`。
- [x] 先完成跨年布局／单位数／重复／地址 spillover QA：`bd_project_lifecycle_history_audit` 已覆盖 2005–2026 的年度样本；Md53 项目宗数、Md54 单位数和 Md56 单位数均在 22/22 样本与 Section 1 对上，Md55 为 20 个 matched 加 2 个 `matched_zero`。显式 AMENDMENT 行仍保留在 detail，但不混入 as-published 对账；未把未经 entity resolution 的数值喂给 SHKP signal。
- [x] 逐项解释 audit gap 并完成全月 2005–2026 detail backfill；当前没有 unresolved `gap`，仅 Md52 因没有 like-for-like Section 1 指标标为 `not_comparable`。下一步仍需把历史 OP 地址／permit 与 project_id 做稳定 entity resolution，才能进入 SHKP 生产信号。
- [ ] 再把历史 OP 地址／permit 与 project_id 做稳定 entity resolution，不能直接把 digest month 当 permit date；下一步按 `shkp_bd_phase_resolution_candidates` 的 P0 → P1 顺序，用 SRPE phase/lot、SHKP role fields、BD permit/applicant primary documents 做人工／规则复核。
- [ ] 按 P0 review queue 顺序，用 SRPE phase/lot 字段 + 对应 SHKP 项目页的 Vendor／Person so engaged／Holding Companies／Sales Agent 角色字段，先拆分 shared-address phase groups；即使拆开也只能降为 `matched_needs_review`。
- [ ] 将 BD permit number（如有）、applicant、地址和 stage 聚成 permit clusters，并与 SRPE/SHKP phase evidence 对齐；不把 applicant 自动视为 SPV 或上市公司。
- [ ] 对剩余高价值 shared-address groups 小批量查 TPB/LandsD lot 文件；只有仍无法拆分且值得付费时，才做 Land Registry IRIS 人工 pilot。Street Index/CRT 仅交互查阅，不抓取、不保存。
- [x] 从公司年报补充 SHKP 合约销售、物业销售、香港 recurring portfolio 与收入确认相关的披露锚点（financial bridge 已接入 dashboard）。
- [ ] 明确“合约销售”“交楼代理”“会计收入”三种日期和金额。

### Signal 与验证

- [ ] 计算销售速度、吸纳率、ASP、取消率和库存压力。
- [ ] 计算持股比例调整后的可归属合约销售额。
- [ ] 建立住宅市场 signal 与公司级项目 signal 的分层展示。
- [ ] 设定最小历史长度和 point-in-time 回测规则。
- [x] 接入官方 History and Milestones 历史项目证据，并保留原文、年份及 raw HTML。
- [x] 将 SHKP 官方披露、financial-data `0016.HK` actuals、共识及 filing-vintage diagnostics 接入同一 evidence table；保留 HK-only scope 与 PIT caveats。
- [x] 建立 gross SRPE activity → handover evidence → company annual revenue 的方向性诊断；明确 ratio 不是 accuracy score，也不做 phase-level revenue allocation。
- [ ] 用更多已解析的 OP 月份和销售安排／交楼文件做方向及时间验证。
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
