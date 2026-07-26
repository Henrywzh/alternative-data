# 港股财务数据来源对比：yfinance vs akshare vs HKEX

 > 审计日期：2026-07-25
 > 目的：为 equities alt data 项目选择最佳财务数据来源

 ---

 ## 目录

 1. [结论速览](#1-结论速览)
 2. [yfinance 财务数据详解](#2-yfinance-财务数据详解)
 3. [akshare 财务数据详解](#3-akshare-财务数据详解)
 4. [港交所 (HKEX) 数据详解](#4-港交所-hkex-数据详解)
 5. [三者对比](#5-三者对比)
 6. [推荐方案](#6-推荐方案)

 ---

 ## 1. 结论速览

 | 维度 | yfinance | akshare | HKEXnews |
 |------|----------|---------|----------|
 | **财务报表** | ✅ 5 年年度 + 5-6 季度 | ⚠️ 2 年（9 个季度） | ⚠️ PDF 原始文件 |
 | **分红历史** | ✅ 最深到 2000 年 | ✅ 3-4 年 | ⚠️ PDF 公告 |
 | **估值指标** | ✅ PE/PB/ROE 实时 | ✅ 估值日频（百度源） | ❌ 无 |
 | **盈利预测** | ❌ 无 | ✅ 券商预测 | ❌ 无 |
 | **行业对比** | ❌ 无 | ✅ 估值/成长/规模对比 | ❌ 无 |
 | **HIBOR** | ❌ 无 | ✅ 9 年日频 | ❌ 无 |
 | **公告/年报** | ❌ 无 | ❌ 无 | ✅ 完整历史 PDF |
 | **免费** | ✅ 完全免费 | ✅ 完全免费 | ✅ 完全免费 |
 | **稳定性** | ✅ 高 | ⚠️ 行情类不稳定 | ✅ 高 |
 | **API 易用性** | ✅ 极简 | ⚠️ 参数复杂 | ⚠️ 需要解析 |

 **一句话：yfinance 是财务报表的主力，akshare 补充宏观/行业/HIBOR，HKEX 留着当原始数据后盾。**

 ---

 ## 2. yfinance 财务数据详解

 ### 2.1 可用数据

 | 数据类型 | 属性 | 字段数 | 说明 |
 |---------|------|--------|------|
 | **利润表** | `ticker.income_stmt` | 55 个 | 年度，含 Revenue/Net Income/EBITDA/EPS 等 |
 | **利润表（季度）** | `ticker.quarterly_income_stmt` | 55 个 | 季度，5-6 个季度 |
 | **资产负债表** | `ticker.balance_sheet` | 46 个 | 年度，含 Assets/Liabilities/Equity 等 |
 | **资产负债表（季度）** | `ticker.quarterly_balance_sheet` | 46 个 | 季度 |
 | **现金流量表** | `ticker.cashflow` | 50 个 | 年度，含 Operating/Investing/Financing 等 |
 | **现金流量表（季度）** | `ticker.quarterly_cashflow` | 50 个 | 季度 |
 | **分红历史** | `ticker.dividends` | 2 列 | 日期 + 金额，最深到 2000 年 |
 | **实时指标** | `ticker.info` | 50+ 个 | PE/PB/ROE/市值/股息率等 |

 ### 2.2 历史深度实测

 | 股票 | 年报年数 | 资产负债表 | 现金流 | 分红记录 |
 |------|---------|-----------|--------|---------|
 | 0005.HK (汇丰) | 5 年 (2021-2025) | 5 年 | 5 年 | **91 笔** (2000-2026) |
 | 0388.HK (港交所) | 5 年 (2021-2025) | 5 年 | 5 年 | 52 笔 (2000-2026) |
 | 0002.HK (中电) | 5 年 (2021-2025) | 5 年 | 5 年 | **106 笔** (2000-2026) |
 | 0003.HK (煤气) | 5 年 (2021-2025) | 5 年 | 5 年 | 53 笔 (2000-2026) |
 | 0883.HK (中海油) | 5 年 (2021-2025) | 5 年 | 5 年 | 45 笔 (2004-2026) |
 | 1299.HK (友邦) | 5 年 (2021-2025) | 5 年 | 5 年 | 30 笔 (2011-2026) |
 | 2313.HK (申洲) | 5 年 (2021-2025) | 5 年 | 5 年 | 30 笔 (2006-2026) |
 | 2318.HK (平安) | 4 年 (2022-2025) | 5 年 | 5 年 | — |
 | 2628.HK (国寿) | 5 年 (2021-2025) | 5 年 | 5 年 | 23 笔 (2006-2026) |
 | 0700.HK (腾讯) | 5 年 (2021-2025) | 5 年 | 4 年 | — |
 | 9988.HK (阿里) | 4 年 (2023-2026) | 5 年 | 5 年 | 4 笔 (2023-2026) |
 | 9992.HK (泡泡玛特) | 4 年 (2021-2024) | 5 年 | 4 年 | 6 笔 (2021-2026) |
 | 1398.HK (工行) | 4 年 (2022-2025) | 5 年 | 5 年 | 22 笔 (2007-2026) |
 | 3988.HK (中行) | 4 年 (2022-2025) | 5 年 | 5 年 | 24 笔 (2007-2026) |

 **结论：yfinance 对港股覆盖良好，大多数公司提供 5 年年度财务数据 + 最深到 2000 年的分红记录。**

 ### 2.3 关键字段（利润表）

 ```
 Total Revenue                    # 总营收
 Operating Revenue                # 营业收入
 Cost Of Revenue                  # 营业成本
 Gross Profit                     # 毛利润
 Operating Expense                # 营业费用
 Selling General And Administration  # 销管费用
 Research And Development         # 研发费用
 Operating Income                 # 营业利润
 Net Interest Income              # 净利息收入（银行关键）
 Interest Expense                 # 利息支出
 Interest Income                  # 利息收入
 Pretax Income                    # 税前利润
 Tax Provision                    # 所得税
 Net Income                       # 净利润
 Basic EPS                        # 基本每股收益
 Diluted EPS                      # 稀释每股收益
 EBITDA                           # 息税折旧摊销前利润
 Depreciation And Amortization    # 折旧摊销
 ```

 ### 2.4 关键字段（资产负债表）

 ```
 Total Assets                     # 总资产
 Total Liabilities Net Minority Interest  # 总负债
 Stockholders Equity              # 股东权益
 Total Debt                       # 总债务
 Cash And Cash Equivalents        # 现金及等价物
 Current Assets                   # 流动资产
 Current Liabilities              # 流动负债
 Net Tangible Assets              # 有形净资产
 Retained Earnings                # 留存收益
 Invested Capital                 # 投入资本
 ```

 ### 2.5 关键字段（现金流量表）

 ```
 Free Cash Flow                   # 自由现金流
 Operating Cash Flow              # 经营现金流
 Investing Cash Flow              # 投资现金流
 Financing Cash Flow              # 筹资现金流
 Capital Expenditure              # 资本支出
 Cash Dividends Paid              # 已付股息
 Repurchase Of Capital Stock      # 回购股份
 Issuance Of Debt                 # 发行债务
 Repayment Of Debt                # 偿还债务
 Sale Of Investment               # 出售投资
 Purchase Of Business             # 收购
 ```

 ### 2.6 `.info` 实时指标

 ```python
 ticker.info['returnOnEquity']     # ROE
 ticker.info['returnOnAssets']     # ROA
 ticker.info['trailingPE']         # 滚动 PE
 ticker.info['forwardPE']          # 前瞻 PE
 ticker.info['priceToBook']        # PB
 ticker.info['dividendYield']      # 股息率
 ticker.info['marketCap']          # 市值
 ticker.info['trailingEps']        # 滚动 EPS
 ticker.info['forwardEps']         # 前瞻 EPS
 ticker.info['debtToEquity']       # 负债权益比
 ticker.info['currentRatio']       # 流动比率
 ticker.info['quickRatio']         # 速动比率
 ticker.info['revenueGrowth']      # 营收增长率
 ticker.info['earningsGrowth']     # 盈利增长率
 ticker.info['profitMargins']      # 利润率
 ticker.info['grossMargins']       # 毛利率
 ticker.info['operatingMargins']   # 营业利润率
 ```

 ---

 ## 3. akshare 财务数据详解

 ### 3.1 港股财务函数

 | 函数 | 数据 | 历史深度 | 稳定性 |
 |------|------|---------|--------|
 | `stock_hk_valuation_baidu` | 估值（市值/PE/PB/PCF） | 365 天日频 | ✅ |
 | `stock_hk_financial_indicator_em` | 最新财务指标（EPS/BPS/股息等） | **仅当前** | ✅ |
 | `stock_financial_hk_analysis_indicator_em` | 财务分析（ROE/毛利率/净利率等） | **2 年（9 个季度）** | ✅ |
 | `stock_financial_hk_report_em` | 三大报表 | **返回 0 行** | ❌ Broken |
 | `stock_hk_dividend_payout_em` | 分红派息历史 | 3-4 年 | ✅ |
 | `stock_hk_profit_forecast_et` | 券商盈利预测 | **前瞻（2027 财年）** | ✅ |
 | `stock_hk_company_profile_em` | 公司资料 | 仅当前 | ✅ |
 | `stock_hk_security_profile_em` | 证券资料 | 仅当前 | ✅ |
 | `stock_hk_valuation_comparison_em` | 行业估值对比 | 仅当前 | ✅ |
 | `stock_hk_growth_comparison_em` | 行业成长对比 | 仅当前 | ✅ |
 | `stock_hk_scale_comparison_em` | 行业规模对比 | 仅当前 | ✅ |

 ### 3.2 核心发现

 **akshare 的港股财务数据历史深度严重不足：**

 - `stock_financial_hk_analysis_indicator_em`：只有 **2 年**（9 个季度）
 - `stock_financial_hk_report_em`：**Broken**（返回 0 行）
 - `stock_hk_financial_indicator_em`：**仅当前快照**（1 行）

 **akshare 真正有价值的财务相关数据：**

 1. `macro_china_hk_market_info` — HIBOR **9 年日频** ⭐⭐⭐⭐⭐
 2. `stock_hk_profit_forecast_et` — 券商盈利预测 ⭐⭐⭐⭐
 3. `stock_hk_*_comparison_em` — 行业对比（当前快照）⭐⭐⭐
 4. `stock_hk_dividend_payout_em` — 分红历史（3-4 年）⭐⭐⭐

 ---

 ## 4. 港交所 (HKEX) 数据详解

 ### 4.1 HKEXnews API（可用！）

 **端点：** `https://www1.hkexnews.hk/search/titleSearchServlet.do`

 **参数：**

 | 参数 | 类型 | 说明 |
 |------|------|------|
 | `stockId` | string | 股票代码（如 `0005`） |
 | `from` | string | 开始日期 `YYYYMMDD` |
 | `to` | string | 结束日期 `YYYYMMDD` |
 | `category` | string | `0` = 全部 |
 | `market` | string | `SEHK` |
 | `documentType` | string | `-1` = 全部，`6` = 年报，`7` = 中报 |
 | `rowRange` | string | `0-10`（分页） |
 | `lang` | string | `EN` / `TC` / `SC` |

 **返回格式：** JSON，包含公告标题、日期、文件链接、文件大小

 **实测结果：**
 ```json
 {
   "result": "[{\"NEWS_ID\":\"12254881\",\"STOCK_CODE\":\"00005\",...}]",
   "totalCount": "7"
 }
 ```

 **能获取的数据：**

 | 数据类型 | documentType | 说明 |
 |---------|-------------|------|
 | 年度报告 | `6` | Annual Report PDF |
 | 中期报告 | `7` | Interim Report PDF |
 | 公告 | 全部 | 所有公告（分红、业绩、关联交易等） |
 | 环境/ESG 报告 | `9` | ESG 报告 PDF |

 **限制：**

 - 返回的是 **PDF 文件链接**，不是结构化数据
 - 需要下载 PDF → 解析 → 提取财务数据
 - 不同公司年报格式不同，解析成本高
 - 适合做**文档存档**，不适合做**实时数据源**

 ### 4.2 HKEX 历史数据服务（付费）

 | 服务 | 价格 | 内容 |
 |------|------|------|
 | Historical Data Services | HK$2,400/年 | 历史市场数据批量文件 |
 | Data Marketplace | 按量计费 | API 访问市场数据 |
 | Stock Connect Data | 付费 | 沪深港通数据 |

 **结论：** 付费服务主要覆盖行情数据，不是财务报表数据。不推荐。

 ---

 ## 5. 三者对比

 ### 5.1 财务报表深度

 ```
 yfinance:   ████████████████████ 5 年年度 + 5-6 季度
 akshare:    ████████ 2 年（9 个季度）
 HKEX:       ████████████████████████████ 完整历史（但需要 PDF 解析）
 ```

 ### 5.2 覆盖范围

 ```
yfinance:   覆盖全球主要交易所，港股 ~200+ 只
 akshare:    覆盖港股 ~500+ 只（但财务数据深度不足）
 HKEX:       覆盖所有港股上市公司（~2,600 只）
 ```

 ### 5.3 数据类型对比

 | 数据 | yfinance | akshare | HKEX |
 |------|----------|---------|------|
 | 利润表 | ✅ 55 字段 × 5 年 | ⚠️ 2 年 | ⚠️ PDF |
 | 资产负债表 | ✅ 46 字段 × 5 年 | ❌ Broken | ⚠️ PDF |
 | 现金流量表 | ✅ 50 字段 × 5 年 | ❌ Broken | ⚠️ PDF |
 | 分红历史 | ✅ 2000-至今 | ⚠️ 3-4 年 | ⚠️ PDF 公告 |
 | 估值指标 | ✅ 实时 | ✅ 日频（百度） | ❌ |
 | ROE/ROA | ✅ `.info` | ⚠️ 2 年 | ⚠️ PDF |
 | PE/PB | ✅ `.info` | ✅ 日频 | ❌ |
 | 股息率 | ✅ `.info` | ✅ 日频 | ❌ |
 | 行业对比 | ❌ | ✅ 估值/成长/规模 | ❌ |
 | 券商预测 | ❌ | ✅ 51 条 | ❌ |
 | HIBOR | ❌ | ✅ 9 年日频 | ❌ |
 | 公告/年报 | ❌ | ❌ | ✅ PDF |

 ---

 ## 6. 推荐方案

 ### 6.1 数据架构

 ```
 ┌─────────────────────────────────────────────────┐
 │              数据来源分层                          │
 ├─────────────────────────────────────────────────┤
 │                                                  │
 │  Layer 1: yfinance (财务报表主力)                 │
 │  ├── 三大报表：5 年年度 + 5-6 季度               │
 │  ├── 分红历史：最深到 2000 年                     │
 │  ├── 实时指标：PE/PB/ROE/市值/股息率              │
 │  └── 覆盖：~200+ 港股                            │
 │                                                  │
 │  Layer 2: akshare (补充数据)                      │
 │  ├── HIBOR 日频：9 年 (macro_china_hk_market_info)│
 │  ├── 券商盈利预测：前瞻 (stock_hk_profit_forecast_et)│
 │  ├── 行业对比：估值/成长/规模 (stock_hk_*_comparison)│
 │  ├── 分红详情：3-4 年 (stock_hk_dividend_payout_em)│
 │  └── 港股人气榜：当日 (stock_hk_hot_rank_em)      │
 │                                                  │
 │  Layer 3: HKEXnews (原始文档存档)                 │
 │  ├── 年报/中报 PDF：完整历史                       │
 │  ├── 公告：分红/业绩/关联交易等                    │
 │  └── ESG 报告                                    │
 │                                                  │
 └─────────────────────────────────────────────────┘
 ```

 ### 6.2 实施步骤

 **Phase 1：yfinance 财务数据模块（立即）**

 1. 新建 `src/hk_financials/` 模块
 2. 实现 `yfinance_fetcher.py`：获取三大报表 + 分红 + `.info`
 3. 实现 `storage.py`：Parquet 存储
 4. 添加 watchlist：目标公司列表
 5. GitHub Actions 定时采集（季度更新即可）

 **Phase 2：akshare 补充数据（1-2 周）**

 1. 集成 `macro_china_hk_market_info`（HIBOR）到 pipeline
 2. 集成 `stock_hk_profit_forecast_et`（券商预测）
 3. 集成 `stock_hk_*_comparison_em`（行业对比）
 4. 评估 `stock_hk_hot_rank_em`（人气榜）的信号价值

 **Phase 3：HKEXnews 文档存档（可选）**

 1. 实现公告搜索 API 调用
 2. 下载关键公司年报 PDF
 3. 评估 PDF 解析的 ROI（可能不值得）

 ### 6.3 成本

 | 数据来源 | 月成本 | 备注 |
 |---------|--------|------|
 | yfinance | $0 | 完全免费 |
 | akshare | $0 | 完全免费 |
 | HKEXnews API | $0 | 完全免费 |
 | **总计** | **$0** | |

 ---

 ## 附录：yfinance 使用示例

 ```python
 import yfinance as yf

 # 获取港股财务数据
 ticker = yf.Ticker('0005.HK')  # 汇丰

 # 三大报表
 income = ticker.income_stmt          # 年度利润表
 balance = ticker.balance_sheet       # 年度资产负债表
 cashflow = ticker.cashflow           # 年度现金流量表

 # 季度数据
 income_q = ticker.quarterly_income_stmt
 balance_q = ticker.quarterly_balance_sheet

 # 分红历史
 dividends = ticker.dividends         # 日期 + 金额

 # 实时指标
 info = ticker.info
 roe = info['returnOnEquity']
 pe = info['trailingPE']
 market_cap = info['marketCap']
 div_yield = info['dividendYield']

 # 关键财务指标提取
 revenue = income.loc['Total Revenue']
 net_income = income.loc['Net Income']
 eps = income.loc['Basic EPS']
 fcf = cashflow.loc['Free Cash Flow']
 ```

 ## 附录：akshare HIBOR 使用示例

 ```python
 import akshare as ak

 # 获取 HIBOR 日频数据
 df = ak.macro_china_hk_market_info()

 # 数据包含：ON/1W/2W/1M/2M/3M/6M/1Y 所有期限
 # 时间范围：2017-03-20 ~ 今天
 # 每条包含：定价 + 涨跌幅

 # 筛选 3M HIBOR
 hibor_3m = df[['日期', '3M-定价', '3M-涨跌幅']]
 ```

 ## 附录：HKEXnews API 使用示例

 ```python
 import requests

 # 搜索公告
 url = 'https://www1.hkexnews.hk/search/titleSearchServlet.do'
 params = {
     'stockId': '0005',        # 股票代码
     'from': '20250101',       # 开始日期
     'to': '20260725',         # 结束日期
     'market': 'SEHK',
     'documentType': '-1',     # -1=全部, 6=年报, 7=中报
     'rowRange': '0-10',
     'lang': 'EN'
 }
 r = requests.get(url, params=params)
 data = r.json()
 # 返回 JSON，包含公告标题、日期、PDF 链接
 ```
