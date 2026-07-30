# 香港劳动力市场数据层

本文件只描述官方数据采集与储存，不定义任何 dashboard 图表或投资评分。

## 采集规则

- C&SD 第一至第三阶段数据来自香港政府统计处完整历史 JSON API：`https://www.censtatd.gov.hk/api/get.php?id=<table_id>&lang=en&full_series=1`；第四阶段政策供给数据使用下表列出的劳工处／入境处开放数据。
- 每次 HTTP 成功响应先保存到 `data/raw/hk_labour_market/`，之后才进行质量检查；质量失败的响应也保留作审计证据。
- 每次质量通过的完整表保存为 run-scoped Parquet：`data/normalized/hk_labour_market/<dataset_id>/<run_id>/`，同目录的 `lineage.json` 指向 raw snapshot。
- 运行级 `manifest.json` 位于 `data/normalized/hk_labour_market/runs/<run_id>/`。
- 不计算、拼接或重定义官方指标。`period`、`frequency_code`、分类代码、统计符号均原样保留；`period_end` 仅是方便时间查询的标准化字段。

## 核心数据集

| Dataset | C&SD 表 | 原始频率 | 当前可比历史起点 | 核心维度／指标 |
|---|---:|---|---:|---|
| `labour_force_monthly` | 210-06101 | `M3M`、`Y` | 1985 | 性别；劳动力、就业、失业、就业不足、参与率、季调失业率 |
| `labour_demand_by_industry` | 215-16001 | `M`（期末观察） | 2000-03 | 行业；机构数、就业人数、职位空缺、空缺率 |
| `nominal_wage_index_by_industry` | 220-19001 | `M`（期末观察） | 2004-03 | 行业；名义工资指数及同比 |
| `real_wage_index_by_industry` | 220-19002 | `M`（期末观察） | 2004-03 | 行业；实际工资指数及同比 |
| `nominal_payroll_index_by_industry` | 220-19021 | `Q` | 2004-03 | 行业；名义人均薪酬指数及同比 |
| `real_payroll_index_by_industry` | 220-19022 | `Q` | 2004-03 | 行业；实际人均薪酬指数及同比 |
| `median_earnings_by_industry` | 210-06316 | `M3M`、`Y` | 2008 | 主行业、性别；就业收入中位数 |
| `median_earnings_by_occupation` | 210-06317 | `M3M`、`Y` | 2016 | 主职业、性别；就业收入中位数 |
| `economically_active_household_income` | 130-06608A | `Q`、`Y` | 1993 | 家庭人数；经济活跃住户收入中位数（不含外佣） |

## 标准化字段

所有 dataset 都有下列字段：

`source_table_id`, `source_title`, `source_url`, `period`, `period_end`, `frequency_code`, `frequency_label`, `metric_code`, `metric_label`, `value`, `status_flag`, `retrieved_at`, `data_source`。

可选分类字段为：`industry_code`/`industry`、`main_industry_code`/`main_industry`、`occupation_code`/`occupation`、`main_occupation_code`/`main_occupation`、`sex_code`/`sex`、`household_size_code`/`household_size`。

第四阶段另有 `dimension_type`/`dimension_label`，用于区分政策计划本身与 QMAS 的行业、地区、学历拆分。

`metric_code` 不可独自作为唯一指标键：C&SD 会用同一代码同时表示水平值与同比变化。因此自然键同时包含 `metric_label` 和全部适用分类维度。

## 第二阶段细分需求与建筑劳动力

| Dataset | C&SD 表 | 原始频率 | 当前历史起点 | 额外分类 |
|---|---:|---|---:|---|
| `labour_demand_industry_division_sex` | 215-16003 | `M`（期末观察） | 2000-03 | 行业大类／行业主类、性别 |
| `employment_by_industry_establishment_size` | 215-16006 | `M`（期末观察） | 2010-03 | 行业、机构规模、性别 |
| `vacancies_by_industry_occupation` | 215-16007 | `M`（期末观察） | 2016-03 | 行业、职业 |
| `construction_workers_vacancies_by_site_type` | 215-17001 | `M`（期末观察） | 2011-03 | 公营／私营、工程类型 |
| `construction_workers_vacancy_rate_by_site_type` | 215-17002 | `M`（期末观察） | 2011-03 | 公营／私营、工程类型 |
| `construction_workers_vacancies_by_end_use` | 215-17003 | `M`（期末观察） | 2011-03 | 公营／私营、项目用途 |
| `construction_workers_vacancies_by_site_size` | 215-17004 | `M`（期末观察） | 2011-03 | 公营／私营、地盘规模 |

为支持未来新表的未知分类字段，每行还保存 `dimension_key`（所有原始分类代码的稳定 JSON 签名）及 `source_dimensions_json`（代码和描述）。因此新维度不会被静默丢弃或合并。

## 第三阶段年度工资分布与工时

下列数据均为 C&SD 年度收入及工时调查（AEHS），最新参考期为 2025；年度发布滞后与月度／季度数据不同。

| Dataset | C&SD 表 | 历史起点 | 额外分类 |
|---|---:|---:|---|
| `monthly_wage_distribution_by_employment_nature_sex` | 220-23011 | 2009 | 雇佣性质、性别、月薪分位数 |
| `hourly_wage_distribution_by_sex_age` | 220-23022 | 2009 | 性别、年龄、时薪分位数 |
| `hourly_wage_distribution_by_industry_occupation` | 220-23025 | 2016 | 行业、职业、时薪分位数 |
| `employees_by_hourly_wage_industry` | 220-23027 | 2025 | 行业、雇佣性质、时薪区间 |
| `weekly_hours_distribution_by_sex_age` | 220-23031 | 2010 | 雇佣性质、性别、年龄、每周工时分位数 |
| `weekly_hours_distribution_by_sex_education` | 220-23032 | 2012 | 雇佣性质、性别、学历、每周工时分位数 |
| `weekly_hours_distribution_by_sex_occupation` | 220-23033 | 2016 | 雇佣性质、性别、职业、每周工时分位数 |
| `weekly_hours_distribution_by_industry` | 220-23034 | 2010 | 雇佣性质、行业、每周工时分位数 |
| `employees_by_weekly_hours_industry` | 220-23035 | 2010 | 行业、雇佣性质、每周工时区间 |

## 第四阶段：可验证的劳动力供给政策数据

| Dataset | 来源 | 历史范围 | 指标 | 状态 |
|---|---|---:|---|---|
| `esls_applications_annual` | 劳工处 ESLS 开放数据 XML | 以官方 XML 实际返回为准 | 补充劳工计划／补充劳工优化计划年度申请数 | 已接入 |
| `immd_gep_applications_annual` | 入境处开放数据 CSV | 2016年至今 | GEP 接收／批准申请 | 已接入 |
| `immd_asmtp_applications_annual` | 入境处开放数据 CSV | 2016年至今 | ASMTP 接收／批准申请 | 已接入 |
| `immd_techtas_applications_annual` | 入境处开放数据 CSV | 2018年至今 | TechTAS 接收／批准申请 | 已接入 |
| `immd_ttps_applications_annual` | 入境处开放数据 CSV | 2022年至今 | TTPS 接收／批准申请 | 已接入 |
| `immd_iang_applications_annual` | 入境处开放数据 CSV | 2016年至今 | IANG 接收／批准申请 | 已接入 |
| `immd_assg_applications_annual` | 入境处开放数据 CSV | 2016年至今 | ASSG 接收／批准申请 | 已接入 |
| `immd_qmas_applications_annual` | 入境处开放数据 CSV | 2016年至今 | QMAS 接收申请／获配名额 | 已接入 |
| `immd_qmas_industry_annual` | 入境处开放数据 CSV | 2016年至今 | QMAS 获配名额按行业／领域 | 已接入 |
| `immd_qmas_region_annual` | 入境处开放数据 CSV | 2016年至今 | QMAS 获配名额按申请人地区 | 已接入 |
| `immd_qmas_academic_annual` | 入境处开放数据 CSV | 2024年至今 | QMAS 获配名额按学历拆分 | 已接入 |

当前未接入的是 facts page／年度报告中没有稳定 CSV 历史接口的结构性字段（例如个别计划的行业、薪酬或实际抵港人数）。QMAS 地区拆分目前使用官方简体中文 CSV endpoint，因为英文 resource 当前返回 404；数值口径相同，但地区标签保留来源语言。所有已接入数据均代表申请接收／批准／名额分配，不等同于已实际入境或就业；QMAS 的 `quota_allotted` 特别是甄选成功名额，不是就业人数。

## 分析层与更新方式

`src/hk_labour_market/marts.py` 会从最新成功 run 生成三个长格式 Parquet：

- `labour_sector_panel`：行业就业人数、职位空缺、空缺率、名义／实际工资及人均薪酬同比、行业就业收入中位数；保留每个来源的频率和分类，避免把不同 C&SD 分类强行拼接。
- `labour_income_panel`：行业／职业收入中位数、经济活跃住户收入、AEHS 月薪／时薪／工时分布。
- `labour_policy_supply_panel`：ESLS、GEP、ASMTP、TechTAS、TTPS、IANG、ASSG 和 QMAS 的接收／批准／名额指标及 QMAS 拆分。

首次或单独重建分析表：`python -m hk_labour_market.cli build-marts`。完整更新入口：`python -m hk_labour_market.cli run-update`；它会重新抓取官方完整序列、为每一组保存不可变 run，并只在整组通过后更新 `data/normalized/hk_labour_market/latest_runs.json`。因此这里的“增量”是新增 run/vintage 与指针更新，不会覆盖历史 raw 快照。

## 已知口径边界

- `M3M` 是截至该月的三个月滚动估计，不是单月数据。
- C&SD 的 `M` 在职位空缺／工资指数表中表示期末观察代码；不可据此假定它是逐月发布。
- 工资指数与人均薪酬指数不同：前者衡量正常工资，后者覆盖较广薪酬成分。
- 210-06317 的职业分类自 2022 年起调整并由 C&SD 回推至 2016；不与旧分类无标签拼接。
- `status_flag` 如 `p`、`N.A.` 等必须保留；无数值不等于零。
