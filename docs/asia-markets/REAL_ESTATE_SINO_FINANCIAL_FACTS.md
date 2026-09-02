# 信和置业（0083.HK）issuer-specific financial facts

这层资料是信和置业财务建模的事实层，不是 forecast。当前保存：

- 2020–2025 年报 summary：turnover、underlying profit、reported profit、EPS；
- FY2022–FY2025 operating-segment note：property sales、property rental、property management/other services、hotel operations、investments、financing 的 segment revenue 和 segment result；
- FY2022–FY2025 Chairman's business review：attributable property-sales activity revenue、gross/net rental revenue、investment-property occupancy、hotel revenue/profit；
- FY2022–FY2025 Note 6 geographical information：中国内地及香港、新加坡及澳洲的 external revenue、associates/JVs revenue share 和 non-current assets；
- 2025/26 H1：segment table、consolidated revenue、property/rental/hotel revenue、underlying/reported profit，以及香港／中国内地／新加坡 consolidated external revenue；
- 2020/21–2025/26 六份官方 H1 interim reports：当前期间的集团 facts、operating-segment facts、release-date/source-page audit 及 raw PDF snapshots；
- 现有 Sino SRPE contract→handover schedule 的年度诊断对账。

## 重要口径

年报 operating segments 包含公司及附属公司、以及 associates/JVs 的 share，且覆盖集团披露的多个地理市场。因此这些数字**不是香港-only**。全年 Note 6 的 geographical rows 只把「中国内地及香港」合并，不能拆成香港-only；H1 报告才对 consolidated external revenue 单独提供香港、内地和新加坡拆分，也不能拿来替代 segment-level 香港收入。

Chairman's business review 中的 property-sales activity revenue 也单独保存，不强行等同于 segment-note 的 property-sales revenue；例如 FY2025 两者分别为 HK$10,813m 与 HK$10,920m。两者都是官方披露，但用途和范围不同。

SRPE 项目 bridge 的输出仍然是研究用 contract cohort × stake × handover-lag。`sino_land_financial_model_project_reconciliation` 只是与 reported facts 的诊断比较，不能解释成 accounting revenue 或 earnings reconciliation。

## 运行

```bash
PYTHONPATH=src python -m hk_real_estate.cli run-sino-land-financial-model
```

输出的 normalized datasets：

- `sino_land_financial_model_official_facts`
- `sino_land_financial_model_financial_data_actuals`
- `sino_land_financial_model_consensus`
- `sino_land_financial_model_project_reconciliation`
- `sino_land_financial_model_quality`

H1 历史与 benchmark backtest 另存为：

- `sino_land_h1_history`
- `sino_land_h1_history_audit`
- `sino_land_h1_backtest`
- `sino_land_h1_backtest_quality`
- `sino_land_h1_residential_h2_scenario`
- `sino_land_h1_residential_h2_quality`

## 当前数据质量结论

- 官方事实行均有 URL、页码和报告 release timestamp；
- 0083 financial-data actuals 当前没有原始 `announcement_date`，只能当作 fetched snapshot，不能当作严格 PIT；
- annual revenue/profit 存在 AkShare 与 yfinance 重叠来源差异，不能相加或静默选择；
- 绝大部分官方分部事实有 `group_all_geographies` 标记，不能直接作为香港-only forecast driver；
- 项目 bridge 与 reported property sales 的 gap 目前只表示覆盖、时点、ownership 和会计 scope 差异，不能当成 model error。
- `sino_land_h1_backtest` 的 `2×H1` 结果是 research benchmark；group rows 使用 consolidated annual facts，segment rows 包含 associates/JVs 且严格分栏，不能互相相加。
- `sino_land_h1_residential_h2_scenario` 只按 H1 截止日前已观察到的 sale cohorts 做 handover-window proxy，仍然不是会计收入，也没有并入 consolidated baseline。

下一步再做 forecast 输入：先建立香港 scope bridge（至少把 consolidated Hong Kong revenue 与集团 segment/JV scope 分开），再决定哪些 property-sales、rental、hotel 指标可以进入 model；不要把现有 SRPE 合同额直接喂进收入模型。
