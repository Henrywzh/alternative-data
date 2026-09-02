# 信和置业（0083.HK）Forecast-input contract

## 目的

`sino_land_forecast_inputs` 是信和官方事实层与下一步 earnings model 之间的输入契约。它目前**不拟合预测、不生成 EPS 目标，也不把项目成交额改名为会计收入**。每行都带有来源、地域/归属口径、可用时间和 `model_eligibility`，后续模型必须按这个字段筛选。

配套的 `sino_land_forecast_input_selection` 会把每行分成 `hk_core_control`、`reported_group_context`、`group_scenario_only`、`research_only_scenario` 和 `current_snapshot_only`，并单独提供 `include_pit_backtest`。下游模型不应自行重新解释这些边界。

另外会生成 `sino_land_h1_annualisation_baseline`。这是最新 H1 的 `2 x H1` benchmark，不是正式 forecast：

| 项目 | H1 FY2026 | `2 x H1` benchmark |
|---|---:|---:|
| Consolidated revenue | 5,185 | 10,370 |
| Property sales | 2,543 | 5,086 |
| Rental income | 1,337 | 2,674 |
| Hotel operations | 515 | 1,030 |
| Underlying profit attributable | 2,220 | 4,440 |
| Profit attributable | 1,533 | 3,066 |

这些数值没有加入 H2 seasonality、交楼时点或项目 mix，也没有与口径不同的 FY2025 业务回顾数字计算增长率。

## 年度香港 scope 粗略情景

`sino_land_hk_scope_proxy_scenario` 使用 H1 已披露的香港 external-revenue share：

- H1 FY2025：约 83.99%
- H1 FY2026：约 86.56%
- 两个观察值的 base 平均：约 85.27%

把这个范围套到「中国内地及香港」全年 external revenue 后，FY2025 的香港 external-revenue proxy 为约 **HK$6,003m–6,186m**，base 约 **HK$6,095m**。这只是 geography control scenario，不是香港 segment revenue；它没有分配 associates/JVs，也不进入核心模型或 PIT backtest。

运行：

```bash
PYTHONPATH=src python -m src.hk_real_estate.cli \
  run-sino-land-forecast-inputs \
  --skip-financial-data
```

加入 sibling `financial-data` 快照时去掉 `--skip-financial-data`；若数据库不可读，应该先修复数据库路径/权限，不要用空值代替。

默认行为是严格模式：sibling DuckDB 读失败会直接报错，避免把旧快照误当成 PIT 数据。若只是为了当前研究/监控而需要显式使用最近一个非空 normalized actual/consensus snapshot，可使用：

```bash
PYTHONPATH=src python -m src.hk_real_estate.cli \
  run-sino-land-forecast-inputs \
  --use-persisted-financial-fallback \
  --no-persist
```

该 fallback 会在输出中标记 `financial_data_load_status=persisted_snapshot_fallback_used`，并把对应 rows 的 `availability_quality` 设为 `persisted_snapshot_fallback_not_pit_clean`。这些 rows 仍然是 `model_eligibility=not_pit_clean`、`include_pit_backtest=false`，只能用于当前快照观察，不能用于历史回测。生产刷新不应把这个选项当成修复数据库路径/权限的替代品。

如果只需要刷新官方事实和研究性对账，可用：

```bash
PYTHONPATH=src python -m src.hk_real_estate.cli \
  run-sino-land-financial-model \
  --skip-financial-data
```

## 当前四层输入

| component | 内容 | 当前用途 |
|---|---|---|
| `group_context` / `property_sales_context` / `commercial_rental_context` / `hotel_context` | 年报及中期报告的集团、segment、业务回顾数字 | 报告事实/情景；多数是全地域，segment 还含 associates/JVs，不能直接当香港目标 |
| `hk_scope_controls` | 中期报告按市场列出的香港 consolidated external revenue，以及由香港/集团收入推导的 H1 比例 | 香港地域控制变量；目前只有 H1，不能静默年化 |
| `geography_context` | 年报 Note 6 的「中国内地及香港」与「新加坡及澳洲」全年 external revenue、JV share 和 non-current assets | 年度地域控制；可确认有全年 Greater-China 口径，但不能拆成香港-only |
| `residential_handover_bridge` | SRPE 合同 cohort × stake/lag 的 low/base/high FY 聚合 | `research_only_scenario`，用于检查住宅交付时点，不是 revenue |
| `financial_data_actuals_snapshot` / `consensus_snapshot` | sibling `financial-data` 的 0083 行 | 保留快照，但 `not_pit_clean`；announcement-vintage 缺失时不能做严格 PIT backtest |

## 当前质量结论（本地 smoke run）

在不读取 sibling 财务库、只用官方事实和最新本地住宅桥接快照的运行中：

- 201 行 tagged inputs；
- 6 行 H1 香港地域控制，其中 4 行为直接香港 external revenue，另有 2 行 H1 香港/集团比例派生行；
- 21 行住宅桥接情景，全部保持 `research_only_scenario`；
- 201 行 selection contract 与输入面板一一对应，研究桥接和 snapshot 行均被 PIT guard 排除；
- 年度「中国内地及香港」地域 facts 已纳入，但年度香港-only segment 仍为 0，因此 `annual_hk_scope_gap` 继续为 `warn`；
- global/JV 情景行被隔离，不得进入香港核心模型；
- 尚未进行 model fit。

## 下一步边界

下一步才是建立模型筛选规则：

1. 用 `eligible_as_hk_scope_control` 作为香港地域控制；
2. 为住宅建立独立的香港项目/交楼收入桥，不能用全集团 `property_sales_context` 代替；
3. 商业租金和酒店先做集团情景，直到获得香港资产/地域桥；
4. 对 `not_pit_clean` 的 actual/consensus 先补 announcement-vintage，再进行 OOS backtest。

H1-to-FY 的第一版透明 baseline 已另存为 [`REAL_ESTATE_SINO_H1_NOWCAST.md`](REAL_ESTATE_SINO_H1_NOWCAST.md)。它只把 `2×H1` 作为集团 benchmark，并把分部 H2 shape scenario 单独保存；分部/JV rows 不得加总成 consolidated target。

任何把 `research_only_scenario`、`scenario_only_until_hk_scope_bridge` 或 `not_pit_clean` rows 直接混进核心 forecast 的代码，都应视为质量错误。
