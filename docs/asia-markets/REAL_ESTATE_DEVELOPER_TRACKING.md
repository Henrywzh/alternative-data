# 香港开发商项目追踪框架

## 目的与范围

SHKP 的项目追踪已经拆出一个开发商无关的核心层，并以信和置业（Sino Land，**0083.HK**；不是 00283.HK）作为第一家适配器试点。目标是把「公司官网目录 → 官方项目身份 → SRPE 一手住宅成交队列 → 商业资产独立登记」做成可重复的事件流，而不是把某一家公司现有的规则复制成另一套特例。

当前合同的缺失数据规则是：

> `unknown_is_not_zero; no_srpe_is_not_no_sales`

因此，官网没有列出项目、SRPE 没有精确匹配、某个类别抓取失败，都只会进入 `pending / unresolved / source_gap` 状态，不会被解释为零销售或项目已结束。

## 共用核心

`src/hk_real_estate/developer_tracking.py` 提供：

- `DeveloperProfile`：公司 ID、股票代码、名称、官方域名及版本；
- 目录标准化与精确名称/别名 crosswalk；只接受 exact normalized name 或显式 registry alias，模糊相似度不自动升级为 ownership；
- append-only `project_events`，以 `event_key` 去重；旧版本 source-specific fallback key 会在读入时合并到稳定的 unresolved project key；
- 当前 `project_snapshot`，每个 canonical project 一行；
- `sales_ingestion_queue`：只把 active、身份已连到 SRPE、且 scope 是 `residential_first_hand` 的 phase 放入近期成交队列；
- 商业资产走 `not_applicable_non_residential / commercial_separate_registry`，出租住宅走 `not_applicable_non_first_hand_residential / residential_investment_separate_registry`，两者均不进入 SRPE 一手销售队列；
- ownership 只保留数值 snapshot / low-base-high 情景，并明确标注 `observed_snapshot_not_interval`，不推断历史生效区间。

## 信和置业适配器

实现位置：`src/hk_real_estate/sources/sino_land.py`

### 官方来源

1. 信和集团官网公开的 Kontent Delivery API proxy：
   `https://web-cdn.sino.com/20a53f0a-15c8-0029-b8df-e495023b403f/items`
2. 官网项目目录入口：
   `https://www.sino.com/en/`
3. 官方 2025 年报（issuer-hosted PDF）：
   `https://web-media.sino.com/20a53f0a-15c8-0029-b8df-e495023b403f/c468acfe-1a59-4c93-9131-6eeba511b501/E_SL_Annual%20Report%202025.pdf`
4. HKEX 备用年报副本：
   `https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0925/2025092501132.pdf`
5. 香港政府一手住宅物业销售资讯网 SRPE：
   `https://www.srpe.gov.hk/opip/all_development`

官网 API 按香港区域及业务类别分开抓取：在售住宅、出租住宅、写字楼、工业及商场。类别请求是独立的；一类失败不会把其它类别伪装成空结果，全部类别失败才会终止运行。项目官网角色抓取是可选的 bounded evidence lane，只记录 vendor/holding-company/role 文本，不把网页文字直接当作法定持股比例。

年报适配器只搜索明确披露的四个香港项目锚点：Yau Tong Ventilation Building Property Development、Grand Mayfair III、LOHAS Park Package Thirteen Property Development、Wing Kwong Street/Sung On Street Development Project。适配器会优先选择包含详细 JV 描述的 occurrence，并提取明确的 `equity interest` 百分比；目前能直接读出 Yau Tong 80% 和 Grand Mayfair III 33.33%。LOHAS 等只披露可归属面积而没有明确百分比的项目保持未知，不反推持股比例。`not_found` 也会保留在结果中；这不是“没有项目”的证明，只表示本次文本锚点没有命中。

## 运行方式

受限试跑（每个官网 API 类别最多一页）：

```bash
python -m src.hk_real_estate.cli run-sino-land-tracking \
  --timeout 45 --max-pages 1 --max-site-projects 0 \
  --max-srpe-manifest-projects 8 --max-srpe-transaction-documents 8 \
  --max-srpe-price-list-documents 8
```

完整类别分页：省略 `--max-pages`。如需额外核查项目官网角色，可设置 `--max-site-projects N`；这会增加请求量，但仍然是 bounded fetch。
`--max-srpe-manifest-projects` 只核验近期成交队列的 SRPE 文件清单，不下载 PDF；如需单独刷新 SRPE index，可运行：

```bash
python -m src.hk_real_estate.cli run-srpe-index --timeout 30
```

输出的 normalized datasets：

- `sino_land_property_catalog`
- `sino_land_project_identity_evidence`
- `sino_land_pipeline_disclosures`
- `sino_land_project_events`
- `sino_land_project_snapshot`
- `sino_land_sales_ingestion_queue`
- `sino_land_srpe_document_manifest`（近期可抓取 phase 的 SRPE 文件元数据；不等于已下载/解析交易）
- `sino_land_srpe_price_list_units`（最新价单中的单位级报价行；不等于全部未售库存）
- `sino_land_srpe_price_list_document_audit`（价单下载/解析、文件大小和去重审计）
- `sino_land_srpe_price_list_coverage`（价单缺失、下载失败、解析为空及总单位数是否明确）
- `sino_land_srpe_transaction_events`（已下载登记册的单位级合同事实；不等于收入确认）
- `sino_land_srpe_monthly_signals`（只输出实际观察到 PASP 交易月份）
- `sino_land_srpe_transaction_document_audit`
- `sino_land_srpe_transaction_coverage`（包含无登记册、下载失败、解析为空等状态）
- `sino_land_project_site_role_evidence`（只有设置 site limit 且有结果时才落盘）

### 香港住宅成交→入伙 timing bridge（研究用途）

`run-sino-residential-bridge` 把上述 SRPE 月度成交 cohort 与屋宇署
`bd_project_lifecycle_history` 的入伙纸（Occupation Permit）做保守的地址层
对账，并输出三个独立层：

- `sino_land_hk_residential_bridge_phase`：每个近期 eligible phase 的成交总额、
  active-snapshot 总额、入伙匹配状态、observed/estimated lag 与 stake 情景；
- `sino_land_hk_residential_recognition_schedule`：按成交月份展开的 low/base/high
  入伙月份和归属成交额情景；
- `sino_land_hk_residential_bridge_coverage`：phase、登记册、入伙匹配、数值 stake
  及 schedule 覆盖审计；同时记录 recognition period 缺失、负值和 low/base/high
  lag 顺序检查。

运行方式：

```bash
python -m src.hk_real_estate.cli run-sino-residential-bridge
```

这个 bridge **绝不是财报收入或会计确认表**。SRPE 记录的是合同/PASP 活动；只有
明确匹配到 BD 入伙记录的月份才标为 `observed_bd_occupation_match`，否则使用
明确标注的 12/18/24 月估计情景。数值 stake 只在身份层有明确百分比 snapshot
时使用；其余 phase 保留 50%/75%/100% low/base/high 假设，并标为
`unknown_assumed_50_75_100_scenario`。地址共享、无登记册、项目别名或 JV 生效
时点不清楚时，输出 `ambiguous`/`unknown`，不填成零，也不把成交额直接改称收入。

2026-08-24 的最新一次本地 bridge 快照覆盖 8 个 eligible phase、7 个有成交
观察的 phase、151 条月度 cohort schedule；其中 2 个 phase 有可用 BD 入伙月份、
3 个 phase 因共享/不足以唯一归属地址而保持 ambiguous，只有 1 个 phase 有明确的
数值 stake snapshot。该快照用于研究和回测，不代表信和全部历史住宅项目或法律
ownership 清单。

weekly GitHub Actions 会在 Sino adapter 前先刷新 2022 年至当前年的 BD 月报明细，
并要求至少存在一行 occupation-permit 记录后才构建 bridge；这些 BD 原始 PDF 和
中间 normalized snapshot 不直接提交进仓库，避免每周产生大体积历史文件。若需要更
早年份或完整审计，仍应单独运行 `run-bd-project-history-backfill`。

## 试点结果与解读

2026-08-24 的一次受限实抓（每类一页）得到 170 条官网目录记录：13 条在售住宅、36 条出租住宅、39 条写字楼、24 条工业及 58 条商场。2025 年报的四个 pipeline 锚点均成功命中当前 PDF 文本；结果仍保留 `found/not_found` 状态，以便年报版本或版式变化时显式暴露缺口。SRPE 精确/显式 alias crosswalk 后，只有可确认的 active first-hand phase 才进入近期 SRPE queue；Grand Victoria 的多 phase 候选仍保留为 `ambiguous`，不会强行绑定某一期。最新 8 个 eligible phase 的 manifest 核验得到 509 条文件元数据，其中 7 个 phase 有交易登记册、6 个 phase 有最新价单。进一步下载并解析 7 份登记册得到 3,816 条单位级合同事件、151 条项目月信号；PASP 日期均可解析、交易金额均为正、交易事件 ID 无重复。6 份价单得到 600 条去重单位报价行，并明确读出总住宅单位数；因此 103/151 条项目月信号现在有显式 sell-through 分母。St. George's Mansions 与 One Central Place 没有价单记录，仍保留为 `manifest_no_price_list`，不是零库存或零成交结论。此步骤仍没有把“有文件”解释成“已售收入”。

这些数字是一次抓取快照，不是「信和所有历史项目」或法律 ownership 清单。官网目录偏向当前业务/挂牌组合；早期已售住宅、项目 phase 历史、JV 生效日期仍需要年报、地契、销售文件或人工 review。下一步最有价值的是：

1. 完整分页并记录目录变化（新增、移除、名称变化）；
2. 对没有价单的 phase（目前 St. George's Mansions、One Central Place）继续观察后续 manifest；缺失仍不能填成零库存；
3. 对 `ambiguous / unmatched / registry_known_srpe_pending` 做地址、phase、销售代理及年报证据核查；
4. 将商业 master 与 RVD/C&SD/旅游控制变量接入同一公司 ID，但不把商业租赁收入混进 SRPE 住宅成交指标。

### 本阶段 code review 结论

- 交易层以最新登记册为主，并按稳定 `transaction_id` 去重；取消记录保留，不能把取消行当作新的有效销售。
- 价单层按 phase 只下载最新版本；`total_residential_properties` 只有在 PDF 明确提供时才作为 sell-through 分母，价单单位行本身不被误称为完整未售库存。
- SRPE 有时会在 manifest、交易登记册和价单中返回不同的空 phase 占位符（例如 `-` / `--`）。月度信号在 join 前改用 `development_id` 对齐交易 phase，避免 One Park Place 一类的合法库存分母因文字占位差异丢失。
- 仍未实现收入确认、开发商持股生效区间、PIT 共识或项目全部历史覆盖；这些不属于本事实层的输出。

## 扩展到另一家开发商

新增公司时只需：

1. 建立一个 `DeveloperProfile`，填入正确 HKEX ticker、名称和官方域名；
2. 写一个 adapter，把该公司官网/公开 CMS 结果映射到 `DEVELOPER_PROPERTY_CATALOG_COLUMNS`；
3. 写 pipeline disclosure extractor，保留 source URL、publication date、evidence context 和 `not_found`；
4. 将公司目录与最新 `srpe_development_index` 送入共用 crosswalk；
5. 运行共用 events/snapshot/queue builder，并为网站分页、空 body、partial category failure、名称歧义加离线 fixture；
6. 只有人工或高质量法律/年报证据足够时，才把 ownership snapshot 升级成有时点的 attribution interval。

SHKP 的历史年报/项目里程碑/法定 ownership review 仍保留在 `shkp_*` 模块中；这些是 issuer-specific evidence lane，不应复制到其它公司，也不应被共用层假定为所有开发商都有。
