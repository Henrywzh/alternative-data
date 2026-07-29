# 全球财务数据来源研究：FMP · Finnhub · SEC EDGAR · 香港官方 API

 > 审计日期：2026-07-25
 > 目的：调研除 yfinance 外的其他财务数据来源，评估是否值得集成

 ---

 ## 目录

 1. [Financial Modeling Prep (FMP)](#1-financial-modeling-prep-fmp)
 2. [Finnhub](#2-finnhub)
 3. [SEC EDGAR API](#3-sec-edgar-api)
 4. [香港官方 API](#4-香港官方-api)
 5. [全球数据源对比总表](#5-全球数据源对比总表)
 6. [英文一句话总结](#6-英文一句话总结)

 ---

 ## 1. Financial Modeling Prep (FMP)

 ### 1.1 是什么

 FMP 是一个面向零售投资者的财务数据 API。覆盖股票、ETF、加密货币、股指等。

 ### 1.2 核心能力

 | 功能 | 说明 |
 |------|------|
 | **财务报表** | 利润表、资产负债表、现金流量表（年度 + 季度） |
 | **估值指标** | PE/PB/PS/EV/EBITDA 等 |
 | **财务比率** | ROE/ROA/ROIC/毛利率/净利率等 |
 | **DCF 估值** | 内置的贴现现金流模型 |
 | **公司简介** | 市值、行业、CEO、员工数等 |
 | **股票列表** | 所有可用的股票代码 |
 | **市场新闻** | 公司相关的新闻 |
 | **股价数据** | 实时 + 历史行情 |

 ### 1.3 定价

 | 套餐 | 价格 | 请求次数/天 | 说明 |
 |------|------|-----------|------|
 | **Free** | $0/月 | **250 次/天** | 仅限部分端点，延迟 ~3 秒 |
 | **Starter** | ~$19/月（年付）~$24/月（月付） | **300 次/分钟** | 完整财务报表 |
 | **Premium** | ~$49/月（年付） | **750 次/分钟** | 更高速率 |
 | **Ultimate** | ~$99/月（年付） | **3,000 次/分钟** | 全功能；另有定制 Enterprise（$2,500+/年） |

 ### 1.4 港股覆盖

 **支持港股吗？** 支持，格式为 `symbol.Exchange`，如 `0005.HK`、`9988.HK`

 **覆盖深度？** **50,000–70,000+** 个股票代码，覆盖全球主要交易所（美/港/A/欧/日等）

 ### 1.5 与我们项目的匹配度

 | 维度 | 评分 | 说明 |
 |------|------|------|
 | 财务报表 | ⭐⭐⭐⭐ | 完整三大报表，但免费版有 demo 限制 |
 | 估值指标 | ⭐⭐⭐⭐ | PE/PB/EV/EBITDA 等，Free 版有限 |
 | DCF 估值 | ⭐⭐⭐ | 内置 DCF，对 equities research 有用 |
 | 港股覆盖 | ⭐⭐⭐ | 覆盖但有延迟 |
 | 性价比 | ⭐⭐⭐ | 免费版 250 次/天，比 yfinance 强？**不，yfinance 免费但有速率限制（~2k req/hr）** |
 | **vs yfinance** | ⭐⭐ | **免费版不如 yfinance 全面**，付费版 ($23.99/月) 才有竞争力 |

 **结论：FMP 免费版不如直接用 yfinance。付费版有价值（DCF 估值、财务比率更丰富），但 $24/月的成本对初始阶段不划算。**

 ---

 ## 2. Finnhub

 ### 2.1 是什么

 Finnhub 是一个面向金融科技的实时市场数据 API。主打**替代数据**——基本面数据以外，还提供新闻情绪、内幕交易、ESG、IPO 日历等。

 ### 2.2 核心能力

 | 功能 | 说明 |
 |------|------|
 | **财务报表** | 三大报表（年度 + 季度），利润表/资产负债表/现金流 |
 | **关键指标** | ROE/PE/PB/股息率等 |
 | **新闻情绪** | 公司新闻 + NLP 情绪打分 |
 | **内幕交易** | 高管/机构买卖纪录 |
 | **ESG 评分** | 环境、社会、治理评分 |
 | **分析师推荐** | 券商评级汇总 |
 | **目标价** | 券商目标价历史 |
 | **IPO 日历** | IPO 列表 + 详情 |
 | **经济日历** | 宏观数据发布时间表 |
 | **股票变动** | 股票拆分、分红日期等 |

 ### 2.3 定价

 | 套餐 | 价格 | 请求次数/分钟 | 说明 |
 |------|------|-------------|------|
 | **Free** | $0/月 | 60 次/分钟 | **限量数据**，部分 endpoint 不可用 |
 | **Basic** | **$49.99/月** | 150 次/分钟 | 完整财务报表 + 新闻 |
 | **Standard** | **$129.99/月** | 300 次/分钟 | 新闻情绪 + 内幕交易 |
 | **Premium** | **$199.99/月** | **900 次/分钟** | 全功能 |
 | **Enterprise** | 定制 | 定制 | |

 ### 2.4 港股覆盖

 **支持港股吗？** 支持，直接使用符号如 `AAPL`、`MSFT`、`0005.HK`

 **覆盖深度？** 全球 **60+** 交易所，港股覆盖良好

 ### 2.5 替代数据亮点

 Finnhub 最独特的能力不是财务数据，而是**替代数据 API**：

 | 数据 | 对我们项目的价值 |
 |------|----------------|
 | **新闻情绪 API** | ⭐⭐⭐⭐⭐ 可以直接得到 NLP 处理的新闻情绪打分 |
 | **内幕交易 API** | ⭐⭐⭐⭐ 高管买卖追踪 |
 | **ESG 评分** | ⭐⭐⭐ 补充 ESG 维度 |
 | **分析师推荐** | ⭐⭐⭐ 券商评级汇总（类似 akshare 的盈利预测） |
 | **IPO 日历** | ⭐⭐ 信息有用但港交所已有免费渠道 |

 ### 2.6 与我们项目的匹配度

 | 维度 | 评分 | 说明 |
 |------|------|------|
 | 财务报表 | ⭐⭐⭐ | 免费版部分可用，完整需 $29/月 |
 | 新闻情绪 | ⭐⭐⭐⭐⭐ | **独特价值**，其他免费源没有 |
 | 内幕交易 | ⭐⭐⭐⭐ | 对港美股都有用 |
 | 港股覆盖 | ⭐⭐⭐ | 覆盖但有限 |
 | 性价比 | ⭐⭐ | 免费版限制太多 |
 | **vs yfinance** | ⭐⭐ | 财务数据不如 yfinance 免费版 |

 **结论：Finnhub 的财务数据不如 yfinance。其替代数据（新闻情绪、内幕交易）有独特价值，但需要付费版 ($29-79/月)。**

 ---

 ## 3. SEC EDGAR API

 ### 3.1 是什么

 SEC EDGAR（Electronic Data Gathering, Analysis, and Retrieval）是美国证券交易委员会的上市公司文件数据库。所有在美国上市的公司都必须通过 EDGAR 提交财务报告。

 ### 3.2 关键事实

 - **100% 免费，无需 API Key**
 - **覆盖所有美股上市公司**（~10,000+）
 - **10-K（年报）、10-Q（季报）、8-K（重大事件）**
 - **历史数据：1994 年至今**
 - 需遵循 SEC 的 rate limit（10 req/sec）和 User-Agent 要求

 ### 3.3 API 能力

 **全文搜索 API：** `https://efts.sec.gov/LATEST/search-index`

 | 参数 | 说明 |
 |------|------|
 | `q` | 搜索关键词（如 "artificial intelligence"）|
 | `forms` | 文件类型（如 "10-K,10-Q,8-K"）|
 | `dateRange` | 自定义日期范围 |
 | `startdt` / `enddt` | 开始/结束日期 |

 **实测结果：** 200 OK，返回 JSON，包含公司名、文件类型、日期、文件链接

 **EDGAR 文件浏览器：** `https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no}/{filename}`
 - 返回 HTML 格式的文件内容
 - 可以从 HTML 中提取结构化财务数据
 - **注意格式：** URL 中 accession_no 需去掉连字符（如 `0000320193-25-000079` → `000032019325000079`），CIK 需去掉前导零（如 `0000320193` → `320193`）

 ### 3.4 我们已有的代码

 `src/sec_edgar_data/` 模块已完整实现：

 | 文件 | 内容 |
 |------|------|
 | `client.py` | 全文搜索 API 客户端（重试、限流、提取） |
 | `config.py` | User-Agent 配置 |
 | `models.py` | `EdgarFilingHit` 数据模型 |
 | `pipeline.py` | 关键词监控管线（关键词轮询 + 去重存储） |
 | `storage.py` | Parquet + CSV 存储 |

 **现有实现的功能：** 按关键词搜索 EDGAR 文件，提取公司名、文件类型、日期、URL，去重存储

 **尚未实现的功能：** 从 10-K/10-Q HTML 中提取结构化财务数据（需要解析 XBRL 标签）

 ### 3.5 对我们项目的价值

 | 能力 | 价值 |
 |------|------|
 | **美股覆盖** | ⭐⭐⭐⭐⭐ 最全面的美股财务数据来源 |
 | **历史深度** | ⭐⭐⭐⭐⭐ 1994 年至今（比 yfinance 的 5 年深得多！）|
 | **数据完整性** | ⭐⭐⭐⭐⭐ 上市公司官方文件，0% 丢失 |
 | **解析难度** | ⭐⭐ XBRL 标签系统复杂，不同券商格式不同 |
 | **无需 API Key** | ⭐⭐⭐⭐⭐ 100% 免费 |

 **关键差距：** EDGAR 不是结构化数据 API，而是文件搜索/下载工具。要从中提取财务数据（收入、利润、EPS 等），需要：
 1. 找到公司的 CIK 代码
 2. 搜索 10-K/10-Q 文件
 3. 下载文件 HTML（或 XBRL）
 4. 解析 XBRL 标签 → 结构化数据

 **已经有开源工具做这个：**
 - `sec-api.io` — EDGAR 的结构化数据 API（100 次终身试用，付费 $49-55/月，**商业闭源**）
 - `xbrl` / `arelle` — 行业标准 XBRL 解析库
 - `edgartools` — 简化 EDGAR 文件获取（MIT 开源）
 - `sec-parser` — SEC 文件 HTML 解析
 - `sec-edgar-downloader` — SEC 文件批量下载

 ---

 ## 4. 香港官方 API

 ### 4.1 HKMA (金管局) API

 **端点：** `api.hkma.gov.hk`

 **当前已验证可用的：**
 - **住宅按揭调查 (RMS)**：`/public/market-data-and-statistics/monthly-statistical-bulletin/banking/residential-mortgage-survey`
   - ✅ 200 OK，返回 JSON（我们已在用）
   - 数据：按揭申请量、批准量、LTV 比率、HIBOR/BLR 定价占比、逾期率
   - 频率：月频
   - 历史：多年（数据量大）

 **已验证不可用的：**
 - **HIBOR API**：搜索不到对应的公开端点
 - **外汇**：`/daily-statistics` 路径不存在
 - **vapi** 子域名已失效

 **API 发现总结：**
 - HKMA API 文档在 `apidocs.hkma.gov.hk`（WordPress 站点）
 - 实际可用 API 路径很少，**只有 RMS 一个端点被确认可工作**
 - 没有发现统一的 API 目录或 Swagger 文档
 - 大部分金融指标需要通过 **Excel 下载** 或 **PDF 报告** 获取

 ### 4.2 HKAB (香港银行公会)

 **HIBOR 利率：** `www.hkab.org.hk/en/rates/hibor`
 - ✅ 200 OK，HTML 页面
 - 包含所有期限的 HIBOR 定盘利率
 - 需要 HTML 解析（不是 JSON API）

 **没有发现统一的 JSON API。**

 ### 4.3 港交所 (HKEX)

 **HKEXnews API：** `www1.hkexnews.hk/search/titleSearchServlet.do`
 - ✅ 200 OK，返回 JSON
 - 可以搜索公告、年报、中报
 - 返回：公告标题、日期、PDF 链接
 - 不是结构化数据（需要 PDF 解析）

 **HKEX Data Marketplace：**
 - 付费服务，年费 ~HK$2,400+
 - 主要是行情数据，不是财务报表

 ### 4.4 data.gov.hk

 - 香港政府开放数据平台
 - 有金融相关数据集（银行分类、经济指标等）
 - **实测：** API 返回 404（可能是 CKAN 版本问题或 API 路径变更）
 - 需要进一步研究可用的数据集 ID

 ### 4.5 官方数据总评

 | 来源 | 数据 | 格式 | 历史 | 免费 | 价值 |
 |------|------|------|------|------|------|
 | HKMA RMS | 按揭调查 | JSON API | 多年月频 | ✅ | ⭐⭐⭐⭐ |
 | HKMA HIBOR | HIBOR 定盘 | JSON API | 日频 | ✅ | ⭐⭐⭐⭐ |
 | HKAB 网页 | HIBOR | HTML | 多年日频 | ✅ | ⭐⭐⭐⭐⭐ |
 | HKEXnews | 公告搜索 | JSON + PDF | 完整历史 | ✅ | ⭐⭐ |
 | data.gov.hk | 多种经济数据 | API | 不定 | ✅ | ⭐⭐ |

 **结论：香港官方数据源以传统 HTML/PDF 为主，几乎没有统一的结构化 API。HKAB HIBOR 的 HTML 解析是最有价值的补充。**

 ---

 ## 5. 全球数据源对比总表

 ### 5.1 财务报表

 | 来源 | 美股市 | 港股市 | A 股 | 历史深度 | 成本 | 评价 |
 |------|--------|--------|------|---------|------|------|
 | **yfinance** | ✅ | ✅ | ⚠️（有限） | **4 年年度 + 4 季度** | **$0**（有速率限制） | 🥇 性价比之王 |
 | **SEC EDGAR** | ✅ | ❌ | ❌ | **1994 年至今** | $0 | 🥇 美股最佳来源，需解析 |
 | **FMP** | ✅ | ✅ | ⚠️ | ~5 年 | $0-24/月 | 🥈 免费版不如 yfinance |
 | **Finnhub** | ✅ | ✅ | ⚠️ | ~5 年 | $0-29/月 | 🥈 特色在替代数据 |
 | **akshare** | ⚠️（有美股 EDGAR） | ✅ | ⚠️（有可持续性数据） | ⚠️（A 股完整历史，HK ~2 年） | $0 | 🥉 A 股/HK 宏观最全 |

 ### 5.2 替代数据 / 特色数据

 | 来源 | 新闻情绪 | 内幕交易 | ESG | 券商预测 | 行业对比 |
 |------|---------|---------|-----|---------|---------|
 | **Finnhub** | ✅ | ✅ | ✅ | ✅ | ❌ |
 | **SEC EDGAR** | ⚠️（关键词搜索） | ✅（13D/13G/4） | ❌ | ❌ | ❌ |
 | **akshare** | ❌ | ❌ | ❌ | ✅ | ✅ |
 | **yfinance** | ✅（新闻流） | ✅（insider_transactions） | ✅（sustainability） | ✅（recommendations） | ❌ |
 | **FMP** | ✅ | ❌ | ❌ | ❌ | ❌ |

 ### 5.3 推荐数据架构

 ```
 ┌─────────────────────────────────────────────────────────┐
 │                   分层数据架构                            │
 ├─────────────────────────────────────────────────────────┤
 │                                                         │
 │  Layer 1: yfinance (基础层 — 免费，有速率限制约 2k req/hr) │
 │  ├── 全球主要交易所（US/HK/CN/JP/EU 等）                 │
 │  ├── 三大报表：4 年年度 + 4 季度                          │
 │  ├── 分红历史：最深到 2000 年                            │
 │  ├── 实时指标：PE/PB/ROE/市值/股息率                      │
 │  └── 价格数据：日/周/月/分钟                              │
 │                                                         │
 │  Layer 2: akshare (中国市场补充)                         │
 │  ├── HIBOR 日频 + 港股估值                              │
 │  ├── 券商盈利预测 + 行业对比                             │
 │  ├── A 股财务（完整历史）+ 港股财务（~2 年）+ 估值        │
 │  └── 宏观数据（CPI/GDP/PMI/M2/LPR）                     │
 │                                                         │
 │  Layer 3: SEC EDGAR (美股深度历史 — 已有代码)            │
 │  ├── 全文搜索：关键词+公司名+文件类型                    │
 │  ├── 10-K/10-Q/8-K 文件浏览                             │
 │  └── ⚠️ 需要 XBRL 解析管道提取结构化财务数据              │
 │                                                         │
 │  Layer 4: HKAB HIBOR (香港银行公会网页)                 │
 │  ├── HIBOR 日频 HTML 解析（所有期限）                   │
 │  └── 比 akshare 的 HIBOR 更新更及时                     │
 │                                                         │
 │  Optional: Finnhub ($50-130/月)                          │
 │  ├── 新闻情绪 NLP（独特价值）                            │
 │  └── 内幕交易 + ESG（nice-to-have）                     │
 │                                                         │
 └─────────────────────────────────────────────────────────┘
 ```

 ### 5.4 实施路线图

 | Phase | 内容 | 难度 | 时间 |
 |------|------|------|------|
 | **Phase 0** ✅ | yfinance 基础模块 | 低 | 已完成研究 |
 | **Phase 1** | SEC EDGAR XBRL 解析管道 | 中 | 1-2 周 |
 | **Phase 2** | HKAB HIBOR HTML 解析 | 低 | 2-3 天 |
 | **Phase 3** | 评估 Finnhub 新闻情绪的价值 | 中 | 试用期 1 周 |
 | **Phase 4** | 整合 FMP（如果需要 DCF 或更多比率） | 低 | 按需 |

 ---

 ## 6. 英文一句话总结

 | Source | Verdict |
 |--------|---------|
 | **FMP** | Good as a paid upgrade for DCF/ratios ($24/mo), but free tier is strictly worse than yfinance |
 | **Finnhub** | Best for **alternative data** (news sentiment, insider trading), not for fundamentals; requires $50-130/mo for real value |
 | **SEC EDGAR** | **Best free source for US stocks** — covers 1994-today, but needs XBRL parsing to extract structured data. Already partially implemented in our codebase |
 | **HKMA / HKAB / HKEX** | No unified structured API for Hong Kong — RMS (JSON) + HIBOR (HTML) + news search (JSON+PDF) are the best free options available |
 | **yfinance** | Still the **best overall free source** — covers global markets, has 5 years of structured financials, dividends back to 2000, free (with IP-based rate limits ~2k req/hr) |
 | **akshare** | Best for **China/HK macro + sector comparison** — HIBOR (9yr daily), broker forecasts, industry comparison. A-share financial statements have full history (back to 1989); HK stocks limited to ~2 years |
 | **Data.gov.hk** | Has potential but API endpoints are unstable/unreliable — needs deeper investigation |

 ---

 > **最终建议：** 坚持 yfinance + akshare 的基础组合，先做好 SEC EDGAR XBRL 解析（美股深度历史），再按需添加 HKAB HIBOR HTML 解析。Finnhub 留在观察列表，等我们 pipeline 稳定后再评估是否需要新闻情绪数据。FMP 付费版的价值不足以替换 yfinance。
