# 住宅开发商销售信号：SRPE 数据质量审计

## 2026-08-07 SHKP candidate scratch / parser audit

- SHKP candidate routing now has a separate scratch CLI and dataset prefix;
  it must not overwrite the generic six-phase dashboard pilot.
- A five-phase exact-candidate scratch batch (`shkp-srpe-transaction-scratch-8a31d1bd-fa38-49e5-a883-c76a55f1cd5a`, before the prefix isolation) produced 2,467 raw events, 72 project-month rows and 5/5 successful document audits. All five phases had one currently discoverable SRPE transaction-register metadata row.
- The core dashboard baseline was then restored with run
  `5fd8d4b9-ec55-4be7-bfe2-e4772dd459f0`: 6/6 document audits succeeded and
  4,047 raw transaction events were emitted. PAVILIA FARM III now emits 1,155
  rows rather than the erroneous one-row result from the prior run.
- Root cause: PAVILIA's 707-page register prints the transaction header on
  page 2 and emits headerless rows on later pages. The parser now carries the
  schema forward after the first valid transaction header and extracts pages
  lazily instead of retaining all page tables. A regression test covers a
  header page followed by a headerless data page.
- API detail requests now use explicit connect/read timeouts. A previous
  17-phase scratch attempt was stopped after one SRPE detail request held a
  pooled TLS read for several minutes; that is an ingestion availability gap,
  not a valid zero-transaction result.
- Prefix-isolation smoke run `shkp-srpe-transaction-scratch-874498c7-26d6-44c9-86a8-1e4e5bf584c2` completed 1/1 exact candidate (Garden Regency): 301
  events, 2 project-month rows and one successful audit, persisted under
  `shkp_srpe_scratch_*` rather than the dashboard baseline.

### Rendered project-site fallback

The ordinary HTTP site probe has a separate bounded Playwright/Chromium
fallback for `ok_short_or_js` and error rows. Run
`shkp-srpe-rendered-site-probe-3b8643f6-2369-41bb-962c-c1821480c010` covered 11
candidates: 7 `rendered_ok`, 2 `rendered_ok_short` and 2 TLS
`rendered_error`. Four rows exposed `Sun Hung Kai Properties Limited` in a
statutory role field after rendering. The rendered HTML is archived in
`shkp_srpe_phase_site_rendered_evidence`, independently keyed from the raw HTTP
evidence, and cannot promote ownership or an effective interval. HTTPS
certificate verification was not disabled; certificate failures remain visible
as errors. A local Scrapling CLI attempt was not usable because its
BrowserForge header-generation dependency raised before navigation, so it is
not part of the core ingestion path.

### SHKP candidate transaction expansion

After the original 17 exact website-matched phases, two bounded batches added
18 `matched_needs_review` phases and two further batches added all 21
`ambiguous` phases. The combined scratch layer now contains all 56 candidate
phase IDs, 56/56 successful transaction-register audits, approximately 30,124
unique raw transaction events and 1,087 unique project-month rows. Ambiguous
status is retained on the routing registry and blocks identity/ownership
promotion, but it no longer prevents phase-level raw ingestion. All scratch
rows remain `blocked_phase_specific_interval` and are not SHKP-attributable
sales.

> 核实日期：2026-08-02
>
> 目标：解释为什么 dashboard 的「住宅开发商销售信号」时间序列断断续续、不够完整，并区分官方数据限制与本地 pipeline 缺陷。

## 结论先行

当前的不完整不是单一原因，而是四个问题叠加；其中 PAVILIA 的明确 parser bug 已在本轮修复：

1. **原始 monthly signal 没有补零月份；状态网格已先在 pilot 层落地。** `build_srpe_sales_signals()` 仍只对实际出现交易事件的月份做 `groupby`，但新增的 `srpe_pilot_project_month_status` 会在 register parser 成功且有明确首末 PASP 日期的区间内生成完整月份，并区分零成交、解析缺口和未覆盖。dashboard 尚未切换到这张状态表。
2. **PAVILIA FARM III 的 headerless-table parser bug 已修复。** 官方最新成交纪录册有 707 页；修复后的真实 run 输出 1,154 行，扫描 668 个 tables，其中 662 个无重复表头数据 tables 被沿用 transaction schema 解析。后续项目仍需逐一通过同样的 completeness audit。
3. **当前运行本身是 bounded pilot，不是全香港开发商覆盖。** 目前只登记和回补六个核心项目阶段；`Blue Coast` 仍是 optional，不在 `core_pilot`。大量新鸿基、恒基、新世界及其他开发商项目尚未进入 registry。
4. **价单不是连续月度历史。** SRPE manifest 每个阶段通常有 11–66 份价单，但 pilot 默认 `price_selection=first_latest`，每个项目只取首份和最新一份。价单数据适合作为库存／价格快照，不是每月库存时间序列。

因此，现阶段 dashboard 的项目销售图表不能被解释为「所有开发商每月完整销售额」。其中 PAVILIA 的新世界数据尤其不能直接使用。

## 当前 run 的数据 profile

使用 run：`3a111479-552c-43ee-a2ee-924016fbe109`（PAVILIA parser 修复后）

| Dataset | Rows | Grain |
|---|---:|---|
| `srpe_pilot_transaction_events` | 1,154 | PAVILIA FARM III 一手住宅成交纪录事件 |
| `srpe_pilot_price_list_units` | 520 | PAVILIA 选定价单中的单位快照 |
| `srpe_pilot_developer_monthly_signals` | 49 | PAVILIA 项目阶段 × 有交易事件的月份 |
| `srpe_pilot_document_audit` | 3 success | PAVILIA 的成交纪录／两份价单文件审计；交易行包含 707 页 parser diagnostics |
| `srpe_pilot_project_month_status` | 62 | PAVILIA register 覆盖区间的 62 个项目月份：6 个 `observed_transactions`、56 个 `observed_zero_transactions` |

## 新增审计：ownership-approved NOVO LAND 首批试点

为避免把“有 SRPE 文件”误当成“可以归属到上市公司”，当前 pipeline 已先
运行 `shkp_sales_ingestion_eligibility` promotion gate。最新 registry run
`037feb3a-9d5d-472d-bdd5-f290387277d9` 的 522 个 phase 中，只有 NOVO LAND
Phase 2A（SRPE registry ID `9146`）和 Phase 3B（`10045`）进入
`eligible_register_price_review`；另有 9 个 phase 虽有 filing metadata，仍因
ownership/JV 未解决而标为 `ownership_review_required`，其余 511 个为
`not_ready`。

最新下载／解析 run：`7c7af694-b0bc-4448-b247-512c5dce47a1`。

| Dataset | Rows | Quality observation |
|---|---:|---|
| `srpe_pilot_transaction_events` | 1,411 | 两个 phase 的 register 均完成；`transaction_id` 非空且唯一；`PASP` 无未来日期；raw grain 保留每个合同事件。 |
| `srpe_pilot_price_list_units` | 586 | 选定价单中的单位快照；unit key 无重复。 |
| `srpe_pilot_developer_monthly_signals` | 41 | 只聚合实际出现交易事件的月份，不应当作完整月度零填充历史。 |
| `srpe_pilot_project_month_status` | 64 | 在可靠首末 PASP 区间生成 `observed_transactions`／`observed_zero_transactions`；不在覆盖区间外填零。 |
| `srpe_pilot_document_audit` | 6 | 两个 register、四份价单文件均为 `success`；register 页数、table 数和 data-table 计数已保留。 |

交易事件中发现 16 个 physical unit key 重复（1,411 行中有 1,403 个唯一
unit key）。抽查显示同一单位有不同 PASP/ASP 日期或价格，属于登记更新／再售
事件，并非 exact duplicate；因此 raw event 不应删除这些行，active-unit
dedup 必须作为独立的 sell-through 口径。两个 phase 本次 `is_cancelled` 均为
False，不能由此推断其它项目没有取消交易。

本次质量检查另发现 8 条交易事件的 `date_of_asp` 为空，但都有有效 PASP、单位和
价格。它们集中在较早的首轮登记事件，符合“临时协议已登记、正式协议日期尚未填入”
的资料状态；不能把它们当作 parser error，也不能把 PASP 日期直接替代 ASP 日期。
两个 phase 的 PASP 范围分别覆盖 2023-06-10 至 2026-07-22，且没有未来日期；
累计 sell-through 最高约 71.7%／95.8%，没有超过 100%。

SRPE manifest 的历史 run 不能简单覆盖。旧的 9-phase run 有 484 行；针对
`9146`、`10045` 的新增 run 有 117 行；按
`development_id + document_category + document_id + serial_no + file_name`
合并后当前 union 为 601 行、11 个 phase IDs，composite key 无重复。相同
document ID 但不同 serial/file name 的 brochure 是合法版本变体，不能按较短
的 `(development_id, category, document_id)` 键误删。

## 新增审计：未来推出／在建项目的 pipeline crosswalk

2025/26 interim-results 页面提供 8 个项目标签（6 个 `planned_launch_10m`、2
个 `under_development`）。最新 run `037feb3a-9d5d-472d-bdd5-f290387277d9`
把这些 evidence 转成 9 条 `shkp_pipeline_srpe_crosswalk`：

- `Cullinan Harbour Phase 2` 对应 SRPE `10405` 和 `11516` 两个 phase，状态为
  `ambiguous`，不能任选一期；
- Tsuen Wan West、Sha Po South 已通过官方 lot/address bridge 接到 SRPE
  `11505`/`11554`，但仍为 `matched_needs_review`；Kwu Tung adjacent、City
  One Sha Tin、Tung Shing Lei、Kwu Tung South 保留为 lot-resolved but
  `unmatched`/SRPE-pending；Artist Square Towers 已确认是非住宅商业 BOT，
  从住宅 SRPE identity queue 排出。
- 目前没有任何 pipeline disclosure 改变 `ownership_status` 或
  `ownership_attribution_ready`。

这里故意不把 Sha Tin、Tsuen Wan 等地区当成身份键。地区只能在名称／期数已有
候选之后作 corroborator；否则一个宽泛地区会把大量无关 SRPE phase 错接进来。
若下一次公告页面变体导致 `evidence_status=not_found`，crosswalk 会写成
`not_evaluated`，而不是 `unmatched` 或项目取消。

同一 planning-integrated run 另外落盘 `shkp_pipeline_project_registry`，共 23
行：它把年报交楼表／投资物业标签也保留下来，同时覆盖 6 个 planned launch、2
个 under-development、1 个 handover window 和 2 个 investment-property
completion 标签。这个 registry 解决了“尚未有 SRPE development ID 的在建／未来
项目完全消失”的覆盖问题，但它是 evidence-only layer：`srpe_match_status`
仍可为 `unmatched` 或 `ambiguous`，所有行的 `ownership_status` 都是
`not_verified`，`sales_ingestion_status` 都是 `not_ready`。因此它可以用于
项目发现和 review queue，不能直接进入 0016.HK 销售汇总。

年报附录的 legal-entity 入口也已单独落盘为
`shkp_annual_principal_subsidiaries`。catalog run
`50001779-b7f4-44e5-93e7-edead8658d40` 解析 2022/23、2023/24 和 2024/25
三个完整 `Principal Subsidiaries` 表及其 continuation pages，共 703 行
（229 + 233 + 241），包括 Super Great、Ease Gold、Well Capital、Best Vision、
Success Keep 等开发相关 subsidiary 名称；此前误用的 42 页短版 2024/25 PDF 已
被修正为官方 227 页完整年报。表尾 Notes／bond footnotes 现在会终止当前 row，
旧的伪 interest-rate row 已移除，三份 Zarabanda 记录也不再被脚注污染。该表的
`attributable_equity_pct` 只是报告期末 snapshot，不能自动转成 phase ownership、
effective interval 或 attributable sales；下一步仍要以 Companies Registry 历史
申报、JV/土地文件做 SPV 与项目 phase 的 dated reconciliation。

同一 run 新增 `shkp_annual_principal_subsidiary_crosswalk`，共 712 行：694 条
`unmatched_entity_only`、3 条单期 legal-SPV review rows，以及 15 条多期 legal
group rows。`candidate_count>1` 会显式标成
`matched_legal_spv_phase_group_ambiguous`；所有 rows 都保持
`snapshot_only_non_promoting`，`effective_from/effective_to` 为 null。这个
crosswalk 只是独立 bridge 提供的 phase 候选，不是 ownership、JV economics、effective
interval 或 sales attribution 事实。每行同时保留 `bridge_record_id`、bridge source
URL/page、`source_urls_json` 和年报 snapshot 与 bridge 的一致性状态，便于逐项回到
原始证据审阅。

## Md52–Md56 施工生命周期接入

最新 planning-integrated run `037feb3a-9d5d-472d-bdd5-f290387277d9` 已把当前
屋宇署 Md52–Md56 candidate evaluation 写入 `shkp_project_registry`。共有 57
条 crosswalk rows，覆盖 41 个 SRPE phases；目前 69 条 BD crosswalk rows 全部
是 `unmatched`，所以 registry 的 `bd_match_status` 只有 `unmatched` 或
`not_observed`，没有任何 permit stage 被晋级为项目施工事实。

registry 已保留 `bd_permit_stage`、permit number、BD site address、住宅单位数、
楼面面积和 parser confidence 的聚合字段。这里的 `unmatched` 只表示当前官方
XLS 地址没有通过保守的 phase candidate join，不表示项目没有开工或没有入伙；
下一步应优先补充官方别名、地段／地契 lot 和 permit 号的连接，而不是放宽为宽泛
地区 fuzzy match。

## Ownership review queue

最新完整 catalog run `1e44d345-7449-4023-9f89-70e61cbc6dd1` 同时落盘
`shkp_ownership_review_queue`，共 126 行：13 个 `P0`（已有 SRPE filing、
但不能进入可归属销售）、93 个 `P1` 和 20 个 `P2`。P0 具体包括 Cullinan
Harbour/Sky、Garden Regency、Lime Spark、Sierra Sea 两期以及 YOHO WEST
两期。YOHO WEST 的阻塞原因是年报只写
`JV`；Cullinan/Sierra Sea 的阻塞原因是 LandsD 多方 entity/lot 证据仍未
完成 SPV 和持股比例核对。该 queue 只提供下一步官方来源和理由，不会改变
`ownership_attribution_ready`。

### 项目月份覆盖

| 项目阶段 | 覆盖区间 | 完整月份 | 实际有 signal 月份 | 月份覆盖率 |
|---|---|---:|---:|---:|
| Grand Victoria I | 2021-03–2026-07 | 65 | 48 | 73.8% |
| NOVO LAND Phase 2A | 2023-06–2026-07 | 38 | 19 | 50.0% |
| NOVO LAND Phase 3B | 2024-06–2026-07 | 26 | 22 | 84.6% |
| PARK YOHO NAPOLI | 2018-09–2026-07 | 95 | 64 | 67.4% |
| THE PAVILIA FARM III | 2021-06–2023-12 | 31 | 2 | 6.5% |
| The Henley II | 2022-05–2026-07 | 51 | 41 | 80.4% |

注意：`srpe_pilot_developer_monthly_signals` 仍只生成有事件的月份；状态网格是独立数据集，当前只对 PAVILIA 成功 register audit 的首末 PASP 区间生成。PAVILIA 的旧 6.5% 覆盖率属于 parser 修复前 artifact，不能用于当前判断。

## 发现一：普遍断线来自没有补零月

当前实现逻辑在 `src/hk_real_estate/sources/srpe_pdf.py`：

```python
tx["period"] = tx["date_of_pasp"].dt.to_period("M").dt.to_timestamp()
grouped = tx.groupby(key_columns + ["period"], dropna=False)
```

它只会生成发生过 PASP 的月份。例如一个项目在 2024-04 至 2025-03 没有交易行，结果不会生成这 12 个月的零值记录。

这会产生两个分析风险：

- 图表线条中断，用户无法判断是零成交、数据没覆盖，还是 parser 漏了；
- 开发商按月合计时，缺失月份被误认为不存在，而不是明确的零销售。

正确做法不是盲目把所有缺口都填成 0，而是建立完整月份网格，并同时增加状态字段：

```text
observed_transactions       有成交纪录
observed_zero_transactions   文件可信且该月没有成交行
not_covered                  项目尚未进入资料覆盖范围
parser_gap                   文件存在但解析完整性失败
```

在 parser 完整性修复和 register snapshot 校验之前，不能把所有缺口标成 `observed_zero_transactions`。

## 发现二：PAVILIA FARM III 的 parser 漏数已修复，但需保留审计

审计文件：

```text
data/normalized/hk_real_estate/srpe_pilot_document_audit/
  3a111479-552c-43ee-a2ee-924016fbe109/
  srpe_pilot_document_audit.parquet
```

PAVILIA FARM III 的官方 register：

- 707 页；
- 2026-07-29 更新；
- PDF 文本中可以看到大量成交记录，PASP 日期从 2021-06-05 开始；
- 文本中至少有 331 行以 `05/06/2021` 开始的交易记录；
- 修复前 audit 记录：`source_rows=1`、`rows_emitted=1`；这份结果已标记为历史 pre-fix artifact。
- 修复后 run `3a111479-552c-43ee-a2ee-924016fbe109`：`pages_scanned=707`、`tables_seen=668`、`transaction_header_tables=1`、`data_tables_parsed=662`、`date_row_candidates=1,154`、`parser_rows_emitted=1,154`。

根因及修复均在 `src/hk_real_estate/sources/srpe_pdf.py`：

- 第 2 页有 transaction table 表头，因此 `_transaction_table()` 返回 True；
- 第 3 页以后很多页面只包含数据行，不重复 transaction header；
- `_transaction_table()` 只检查每个 table 的前几行是否含有 `Date of PASP` / `Transaction Price`；
- 所以后续数据 table 全部被跳过；现已在首次识别 transaction header 后沿用 schema 解析无表头数据 table，并把页面/table/date-row diagnostics 写入 document audit。

修复前结果解释了为什么 New World Development／PAVILIA Farm III 曾只有 2 个项目月份；这不是项目真实销售只有一两套。修复后仍需重跑完整六 phase core run，不能把一次 PAVILIA 修复自动外推到其他 PDF 版式。

## 发现三：register 是当前版本的历史登记册，不是每月 API

每个 pilot 阶段的 SRPE manifest 当前通常只提供一个 `register_of_transactions` 文件。该文件本身包含历史 PASP／ASP／终止日期，但 SRPE 没有直接发布“项目月度销售额”这一层的官方聚合数据。

因此要区分：

- 文件没有某个月的交易行：可能是真实没有成交，也可能是当前 PDF parser 没有解析到；
- 文件本身不是实时流：只有下一次 register 更新后，才会看到更晚的成交纪录；
- PASP、ASP、价格修改和终止记录可能描述同一单位的不同状态，不能简单把所有 rows 当成销售单位。

现有代码已经对 active unit 做了去重，这部分方向是正确的；但还缺少 register 的解析完整性计分和版本 diff。

## 发现四：pilot 覆盖范围本来就有限

当前 `data/registries/hk_srpe_project_registry.csv` 的 `core_pilot` 只有六个阶段：

- Grand Victoria Phase 1
- NOVO LAND Phase 2A
- NOVO LAND Phase 3B
- PARK YOHO NAPOLI
- The Henley II
- PAVILIA FARM III

`Blue Coast` 是 `optional_mtr_control`，因此没有进入本次核心 run。其他开发商和阶段没有进入 signal，不代表没有销售，只代表没有 registry ownership mapping 和 PDF backfill。

此外，dashboard 还故意把 developer chart 限制为累计销售额最高的三家开发商，把 project chart 限制为最高的三个阶段；最新项目表才保留全部登记阶段。这是移动端可读性设计，不是完整覆盖表。

## 发现五：价单数据的断续是设计结果

PAVILIA manifest 有 18 份价单，Grand Victoria 有 50 份，PARK YOHO NAPOLI 有 66 份；但 pilot 默认只选第一份和最新一份。因此每个项目最终通常只有两份价单 snapshot。

这会造成：

- 单位级价格历史不是连续的；
- 价单中的具体单位只代表某些发售批次；
- 不能用两份价单直接推断每月剩余库存变化；
- `total_residential_properties` 是项目总户数元数据，不等于当前两份价单中出现的单位行数。

这属于 **Medium severity、High confidence** 的 coverage limitation，不是 parser bug。要做完整库存／价单历史，需要按 `all` 选择全部版本，并保留每个 price-list version 的生效日期、修订关系和 unit-level diff。

## 修复优先级

### P0：维持 transaction parser completeness gate

- 维持 parser 在识别到 transaction header 后，把 schema 状态传递到后续无表头页面；
- 继续用 PAVILIA 707 页 PDF 做真实 regression；
- audit 保留 `pages_scanned`、`tables_seen`、`transaction_header_tables`、`data_tables_parsed`、`date_row_candidates`、`rows_emitted`；
- 如果超大 PDF 只解析出极少量 rows，标记 `partial`，不要写成 success。

### P1：建立完整月份网格和状态

- 每个项目从 first PASP month 到 latest register month 建立完整月序列；
- 对真实零成交月份填 `sales_units_gross=0`、`sales_value_gross_hkd=0`，并保留 `month_status`；
- 对 parser 不可信或尚未覆盖的月份保留空值，不填 0；
- dashboard 用虚线或灰色标记 `parser_gap` / `not_covered`，避免造成连续历史的错觉。

### P1：扩大 registry 和 document history

- 将 Blue Coast 纳入单独 run 并核对 MTR／新世界 ownership；
- 继续扩展新鸿基、恒基、新世界、信和等核心开发商的 active phases；
- 价单由 `first_latest` 切换到受控 `all`，或至少保存每一版的 manifest metadata 和 unit diff；
- register PDF 每次 hash 变化都保留 snapshot，并比较新增／修改／终止交易。

### P2：修正 dashboard 表达

- 最新项目表增加 `coverage_start`、`coverage_end`、`observed_months`、`missing_months`、`month_status`；
- developer chart 明确显示“已登记 pilot phases”，不要看起来像公司全口径销售；
- 对 PAVILIA 在 parser 修复前隐藏销售率和可归属销售额，或显示 `解析不完整`；
- 将 raw event count、unique active units、monthly sales value 分成不同指标。

## 最终判断

当前住宅开发商销售信号的断续来源大致是：

| 原因 | 影响程度 | 是否真实缺数据 |
|---|---|---|
| 没有补零月 | 高 | 不是；是表示层／数据模型问题 |
| PAVILIA parser 漏行 | 高 | 已修复；其他项目仍需逐项验证 |
| 只有六个 pilot phases | 高 | 是；属于覆盖范围限制 |
| 每项目只选首份／最新价单 | 中 | 是设计限制 |
| 真实项目可能某些月份无成交 | 中 | 可能，需要完整 parser 后才能确认 |
| PASP／ASP／终止事件混在 register | 中 | 是源数据语义，需要去重与状态模型 |

当前最应该做的不是继续增加更多开发商，而是补齐月度状态、把 completeness audit 变成强制门槛，再逐批扩展 registry。否则扩展只会把“看起来很丰富但不完整”的 signal 规模扩大。

## 新增审计：active-unit 断崖是 coverage artifact（2026-08-08）

在 56-phase aggregate 中，`active_units_eom` 从 2026-05 的 13,766 降至
2026-08 的 2,286；同期有交易登记覆盖的 phase 数从 30 降至 6。原始
transaction events 仍有 2026-08-07 的 PASP 日期，但只来自 6 个 phase；其余
phase 的当前 register 最后观察月份多集中在 2026-06 或 2026-07。

根因不是 parser gap：56/56 document audits 为 `success`，而是旧 signal grid
只生成到每个 phase 的 `coverage_end`，随后 phase 静默从 aggregate 消失。这样
跨 phase 求和会把“没有最新 register”误读成“有效单位已卖出／消失”。

现已将每个 phase 的月份扩展到全体 transaction set 的最新观察月份，并在
coverage_end 之后写入 `month_status=not_covered`；这些行的成交和 active-unit
指标保持 null。最新网格为 3,265 行，其中 622 行 `not_covered`。Dashboard 同时
显示 covered-phase active units 和 SRPE register coverage count，避免把部分覆盖
的总和当作完整 SHKP inventory trend。`observed_zero_transactions` 仍只用于
phase 自身 register coverage 区间内的真实空月。

## 新增审计：28Hse 单位状态与 SRPE phase signal 对账（2026-08-07）

本轮新增 `run-shkp-28hse-reconciliation`，输入是当前
`hse28_new_projects_catalog`、56 个 `shkp_srpe_phase_candidates`、既有
crosswalk，以及 `shkp_srpe_project_month_signals` 的最新月度状态。对账坚持
**exact-unique alias only**：不会因为相似营销名称、同一项目多期或当前仍在售
就自动合并。

最新 run `shkp-28hse-reconciliation-d51af593-80de-4f18-bcc4-2a6f0e34dd1e`
的结果是：

- 16 行当前 28Hse new-project listing；
- 56 行 SRPE candidate phase；
- 72 行双边 coverage bridge；
- 0 个 exact-unique alias match；
- 16 个 28Hse-only、56 个 SRPE-only；
- 0 个可以安全比较总户数／SRPE inventory 的 unit-comparable rows。

这不是“两个来源没有共同项目”的结论，而是当前 28Hse 页面是动态的项目门户
快照，而 SRPE 是按 development/phase 的法定一手销售登记层；缺少稳定别名桥和
期数映射时，任何 fuzzy match 都会把总户数、余货或已售数错误归给另一期。因此
对账表明确保留 `match_status`、`status_comparison` 和 `coverage_note`，所有
non-match 均解释为 coverage/identity gap，不能填成零库存，也不能打开 ownership
gate。

同时落盘 `shkp_ownership_review_priority`（63 行）作为人工审核队列。它按既有
证据优先级、register 覆盖和 phase activity 排序，仅改变 review 顺序；当前没有
任何 phase 获得日期有界且经 review 的 ownership interval，故仍为
`blocked_interval_missing`，没有生成 SHKP attributable sales。
