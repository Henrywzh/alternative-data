# 信和置业（0083.HK）H1-to-FY nowcast baseline

## 定位

这是一个透明的输入层，不是正式 earnings forecast，也没有拟合统计模型。它把最新官方中期报告拆成两条互不混淆的线：

1. **集团 baseline**：对 consolidated H1 actual 使用 `2 × H1`，作为最简单 benchmark；
2. **分部 shape scenario**：用上一年度「H1 → FY」的形状估计当前年度 H2，并在该形状上做 low/base/high（±20%）敏感性。

分部 operating-segment 数字包括 associates/JVs 的 share，不能与集团 consolidated revenue 或 profit 相加。分部表只用于判断 property sales、rental、hotel 等业务的 H2 timing，不是集团目标的组成桥。

## 当前结果（FY2026）

集团 baseline：

| 指标 | H1 FY2026 actual | H2 benchmark | FY2026 `2×H1` |
|---|---:|---:|---:|
| Consolidated revenue | 5,185 | 5,185 | 10,370 |
| Property sales | 2,543 | 2,543 | 5,086 |
| Rental income | 1,337 | 1,337 | 2,674 |
| Hotel operations | 515 | 515 | 1,030 |
| Underlying profit attributable | 2,220 | 2,220 | 4,440 |
| Profit attributable | 1,533 | 1,533 | 3,066 |

分部情景目前落盘 36 行：6 个 operating segments × `segment_revenue` / `segment_result` × low/base/high。base 使用 FY2025 的 H1/FY 形状，low/high 是该 H2/H1 ratio 的 80%/120%。

例如 `property_sales / segment_revenue`：FY2025 H1 为 2,544、FY 为 10,920，历史 H2/H1 ratio 约 3.29；把这个形状套到 FY2026 H1 6,912 后，base FY2026 segment scenario 约 HK$29,669m。这个数**不是 consolidated turnover，也不是香港-only revenue**，只反映一次性的项目交付形状，必须与集团 baseline 分开阅读。

## 数据质量及限制

- 当前只有一个可用的 prior-FY/H1 anchor，不能称为稳定季节性参数；
- 没有把 SRPE contract value 当成会计收入；
- 没有把 research-only residential bridge、非 PIT consensus 或 global/JV segment rows 混入集团 baseline；
- 分部 scenario 的 ±20% 不是置信区间；
- `model_fit_performed=false`，所有输出都标记 `research_only=true`；
- 正式模型仍需要更多历史 H1/FY pairs、项目交楼时间、持股/归属桥和公告 vintage。

## 落盘数据集

- `sino_land_h1_nowcast`：6 行集团 `2×H1` baseline；
- `sino_land_h1_segment_scenarios`：36 行分部 H2/FY 情景；
- `sino_land_h1_nowcast_quality`：5 个 scope、coverage 和研究边界检查；
- `sino_land_h1_history`：六份官方 H1 interim reports 的 108 个当前期间 facts（FY2020/21–FY2025/26）；
- `sino_land_h1_history_audit`：每份 PDF 的抓取、页码、单位缩放和缺失指标审计；
- `sino_land_h1_backtest`：75 行历史 benchmark 对 FY actual 的比较，其中 15 行是 consolidated `2×H1`、12 行是 prior-H1-share 对照、48 行是独立的 associates/JVs-inclusive segment diagnostic；
- `sino_land_h1_backtest_quality`：历史覆盖、重复、scope 和研究边界检查。
- `sino_land_h1_residential_h2_scenario`：21 行 H1 cutoff 后住宅 recognition-cohort proxy（3 个 portfolio scenarios + 6 个 phase × 3 个 scenario）；
- `sino_land_h1_residential_h2_quality`：8 个 cutoff、日期、schema、非负金额和 research-only 检查。

## 历史 H1 摄取及 benchmark backtest

历史层现在抓取并保留了六份官方 HKEX interim-report PDF：

- [2020-2021 Interim Report](https://www1.hkexnews.hk/listedco/listconews/sehk/2021/0315/2021031500181.pdf)
- [2021-2022 Interim Report](https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0307/2022030700723.pdf)
- [2022-2023 Interim Report](https://www.hkexnews.hk/listedco/listconews/sehk/2023/0309/2023030900217.pdf)
- [2023-2024 Interim Report](https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0311/2024031100217.pdf)
- [2024-2025 Interim Report](https://www.hkexnews.hk/listedco/listconews/sehk/2025/0314/2025031400265.pdf)
- [2025-2026 Interim Report](https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0317/2026031700201.pdf)

解析器只取每份报告的 current-period column，并把旧版 raw HKD 数字统一转换为 HK$ million；comparative column 不会重复当成历史 fact。当前六份报告均通过 parser audit（每份 18 facts，`parse_status=pass`）。

用历史 FY2021–FY2025 actual 对 `2×H1` benchmark 做的 consolidated group 结果如下：

| 指标 | 年数 | MAPE | 平均误差方向 |
|---|---:|---:|---:|
| Consolidated revenue | 5 | 26.45% | -2.52% |
| Underlying profit attributable | 5 | 25.30% | -6.24% |
| Profit attributable | 5 | 32.97% | -6.49% |

另一个对照模型把 FY 预测写成 `H1 actual ÷ prior H1/FY share`。它在可用的 12 行上 MAPE 为 **96.56%**；即使只看有完整三年历史窗口的 6 行，MAPE 仍为 **22.10%**。FY2022 的一/两年窗口尤其不稳定，因此 prior-share 只保留作诊断，不作为当前 forecast engine。

### H2 住宅 cohort overlay（FY2026）

最新 H1 截止日为 2025-12-31。系统只保留在该日期或之前已经出现的 SRPE sale cohorts，再按 low/base/high handover lag 与 stake 情景筛选 2026-01 至 2026-06 的 recognition window。当前 portfolio proxy 为：

| 情景 | H2 recognition contract proxy |
|---|---:|
| Low | HK$1,737.8m |
| Base | HK$1,769.4m |
| High | HK$3,631.4m |

这些数是可归属合同额的时间代理，不是会计收入；它们没有加到 `2×H1` consolidated baseline。后续需要用已披露的 property-sales revenue、项目交楼事实和 ownership/JV 资料做校准后，才能变成 component H2 forecast。

这已经显示 `2×H1` 不能被当成成熟预测器：FY2021/22 的项目确认 timing 令误差特别大，而 FY2023–FY2025 的 revenue absolute error 降到约 5.8%–12.3%。这些数字是研究 benchmark，不是 PIT-clean score；下一步才是加入项目交楼／确认桥，并比较 prior-share 与 component H2 model。

运行历史 PDF 摄取（会保存 raw PDF 和 normalized facts）：

```bash
PYTHONPATH=src python -m src.hk_real_estate.cli \
  run-sino-land-h1-history
```

运行 nowcast、历史 backtest 和 quality layers：

```bash
PYTHONPATH=src python -m src.hk_real_estate.cli \
  run-sino-land-h1-nowcast
```

只做 smoke、不落盘：

```bash
PYTHONPATH=src python -m src.hk_real_estate.cli \
  run-sino-land-h1-nowcast \
  --no-persist
```

官方输入为 [Sino Land 2025 Annual Report](https://web-media.sino.com/20a53f0a-15c8-0029-b8df-e495023b403f/c468acfe-1a59-4c93-9131-6eeba511b501/E_SL_Annual%20Report%202025.pdf) 和 [2025/26 Interim Report](https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0317/2026031700201.pdf)。
