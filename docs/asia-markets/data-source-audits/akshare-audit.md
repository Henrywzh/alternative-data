# Akshare 功能审计与稳定性报告

 > 审计日期：2026-07-25
 > akshare 版本：1.18.78
 > 总函数数：1,133 个

 ---

 ## 目录

 1. [总览](#1-总览)
 2. [港股 (HK) 功能](#2-港股-hk-功能)
 3. [A 股功能](#3-a-股功能)
 4. [宏观经济数据](#4-宏观经济数据)
 5. [指数/ETF/基金](#5-指数etf基金)
 6. [期货/商品/能源](#6-期货商品能源)
 7. [债券/外汇](#7-债券外汇)
 8. [沪深港通/资金流](#8-沪深港通资金流)
 9. [百度系数据](#9-百度系数据)
 10. [与我们 codebase 的关系](#10-与我们-codebase-的关系)
 11. [稳定性总结](#11-稳定性总结)
 12. [推荐优先级](#12-推荐优先级)

 ---

 ## 1. 总览

 akshare 是目前中文世界最全的免费金融数据接口库，覆盖 1,133 个函数。按类别分布：

 | 类别 | 函数数量 | 说明 |
 |------|---------|------|
 | 中国宏观经济 (macro_china) | 85 | GDP/CPI/PPI/PMI/M2/LPR 等 |
 | A 股 (stock_zh) | 44 | 行情/财务/资金流/龙虎榜等 |
 | 美国宏观 (macro_usa) | 49 | 美联储/CPI/非农等 |
 | 港股 (stock_hk) | 28 | 行情/财务/估值/分红等 |
 | 板块/概念 (stock_board) | 19 | 行业板块行情 |
 | 欧洲宏观 (macro_euro) | 16 | 欧央行/欧元区数据 |
 | 财务报表 (stock_financial) | 16 | 三大报表/分析指标 |
 | 期货 (futures) | ~60 | 国内外期货 |
 | 基金 (fund) | ~50 | ETF/LOF/货币基金 |
 | 债券 (bond) | ~30 | 国债/信用债/可转债 |
 | 其他 | ~700+ | 外汇/期权/电影票房/汽车销量等 |

 **核心特点：**

 - 所有函数免费、无需 API key
 - 数据源主要是东方财富、同花顺、新浪财经、百度股市通
 - 稳定性参差不齐：东方财富源最稳定，百度/同花顺源经常变
 - 部分函数需要 cookie/token（如百度外汇）

 ---

 ## 2. 港股 (HK) 功能

 ### 2.1 行情数据

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `stock_hk_spot_em` | 港股实时行情 | ❌ 不稳定 | 连接被远程关闭（eastmoney 反爬） |
 | `stock_hk_main_board_spot_em` | 港股主板实时行情 | ❌ 不稳定 | 同上 |
 | `stock_hk_spot` | 港股实时行情（新浪源） | ❌ 不稳定 | 新浪源也不稳定 |
 | `stock_hk_hist` | 港股日/周/月 K 线 | ❌ 不稳定 | 连接被远程关闭 |
 | `stock_hk_daily` | 港股历史数据（新浪源） | ⚠️ 未测试 | |
 | `stock_hk_hist_min_em` | 港股分时数据 | ⚠️ 未测试 | |
 | `stock_hk_famous_spot_em` | 知名港股行情 | ⚠️ 未测试 | |

 **⚠️ 重要发现：** 港股行情类函数（来自东方财富）在海外 IP 下**极不稳定**，频繁出现 `RemoteDisconnected` 错误。这与我们 `hk_reit` 模块使用 `stock_hk_hist` 时遇到的问题一致。

 ### 2.2 基本面/财务数据

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `stock_hk_valuation_baidu` | 港股估值（市值/PE/PB/PCF） | ✅ 稳定 | 365 天日频，百度股市通源 |
 | `stock_hk_financial_indicator_em` | 港股最新财务指标 | ✅ 稳定 | EPS/每股净资产/股息等 |
 | `stock_financial_hk_analysis_indicator_em` | 港股财务分析主要指标 | ✅ 稳定 | ROE/毛利率/净利率等 |
 | `stock_financial_hk_report_em` | 港股三大报表 | ✅ 稳定 | 资产负债表/利润表/现金流量表 |
 | `stock_hk_dividend_payout_em` | 港股分红派息 | ✅ 稳定 | 历史分红方案/除净日 |
 | `stock_hk_profit_forecast_et` | 港股盈利预测 | ✅ 稳定 | 经济通券商预测，51 条记录 |
 | `stock_hk_company_profile_em` | 公司资料 | ✅ 稳定 | 注册地/成立日期等 |
 | `stock_hk_security_profile_em` | 证券资料 | ✅ 稳定 | 上市日期/发行价等 |
 | `stock_hk_fhpx_detail_ths` | 分红派息详情（同花顺） | ❌ 不稳定 | "No tables found" |
 | `stock_hk_indicator_eniu` | 亿牛网港股指标 | ❌ 不稳定 | JSON 解析失败 |

 ### 2.3 行业对比

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `stock_hk_valuation_comparison_em` | 行业估值对比 | ✅ 稳定 | PE/PB/PS 排名 |
 | `stock_hk_growth_comparison_em` | 行业成长性对比 | ✅ 稳定 | EPS 增长/营收增长排名 |
 | `stock_hk_scale_comparison_em` | 行业规模对比 | ✅ 稳定 | 总市值/流通市值排名 |

 ### 2.4 人气/热度

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `stock_hk_hot_rank_em` | 港股人气榜 Top 100 | ✅ 稳定 | 东方财富人气排名 |
 | `stock_hk_hot_rank_detail_em` | 个股人气历史趋势 | ⚠️ 未测试 | |
 | `stock_hk_hot_rank_detail_realtime_em` | 个股实时人气变动 | ⚠️ 未测试 | |
 | `stock_hk_hot_rank_latest_em` | 最新排名 | ⚠️ 未测试 | |

 ### 2.5 指数数据

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `stock_hk_index_daily_em` | 港股指数日线 | ❌ 不稳定 | 连接被关闭 |
 | `stock_hk_index_daily_sina` | 港股指数日线（新浪） | ⚠️ 未测试 | |
 | `stock_hk_index_spot_em` | 港股指数实时 | ⚠️ 未测试 | |
 | `stock_hk_index_spot_sina` | 港股指数实时（新浪） | ⚠️ 未测试 | |
 | `stock_hk_gxl_lg` | 恒生指数股息率 | ✅ 稳定 | 638 天历史数据 |

 ### 2.6 港股通/资金流

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `stock_hsgt_sh_hk_spot_em` | 沪港通(沪>港)股票 | ❌ 不稳定 | 502 Bad Gateway |
 | `stock_hk_ggt_components_em` | 港股通成份股 | ⚠️ 未测试 | |

 ### 2.7 IPO

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `stock_ipo_hk_ths` | 港股 IPO 申购与中签 | ❌ 不稳定 | 同花顺源，已确认 broken |

 ---

 ## 3. A 股功能

 ### 3.1 行情数据

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `stock_zh_a_spot_em` | A 股实时行情 | ❌ 不稳定 | 连接被关闭 |
 | `stock_zh_a_hist` | A 股日/周/月 K 线 | ✅ 稳定 | 东方财富源，已测试通过 |
 | `stock_zh_a_hist_min_em` | A 股分时数据 | ❌ 不稳定 | 连接被关闭 |

 ### 3.2 财务/基本面

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `stock_zh_valuation_baidu` | A 股估值（百度） | ✅ 稳定 | 365 天日频 |
 | `stock_financial_analysis_indicator` | A 股财务分析指标 | ✅ 稳定 | 返回 0 行（可能参数问题） |
 | `stock_zh_vote_baidu` | 百度股市通投票 | ❌ 不稳定 | API 返回空 |

 ### 3.3 板块/概念

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `stock_board_*` (19 个) | 行业/概念板块行情 | ⚠️ 大部分未测试 | 东方财富源 |

 ---

 ## 4. 宏观经济数据

 ### 4.1 中国宏观

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `macro_china_gdp` | 中国 GDP | ✅ 稳定 | 82 条，季度频 |
 | `macro_china_cpi` | 中国 CPI | ✅ 稳定 | 222 条，月频 |
 | `macro_china_ppi` | 中国 PPI | ✅ 稳定 | 246 条，月频 |
 | `macro_china_pmi` | 中国 PMI | ✅ 稳定 | 222 条，月频 |
 | `macro_china_lpr` | 中国 LPR | ✅ 稳定 | 1,574 条，日频 |
 | `macro_china_money_supply` | 中国 M2 货币供应 | ✅ 稳定 | 222 条，月频 |
 | `macro_china_supply_of_money` | 中国货币供应 v2 | ✅ 稳定 | 582 条 |
 | `macro_china_trade_balance` | 中国贸易差额 | ✅ 稳定 | 565 条 |
 | `macro_china_new_house_price` | 中国新房价格 | ✅ 稳定 | 372 条，按城市 |
 | `macro_china_cpi_yearly` | 中国 CPI 年率 | ✅ 稳定 | 477 条 |
 | `macro_china_m2` | M2（旧接口） | ❌ 不存在 | 已重命名 |
 | `macro_china_shibor` | SHIBOR（旧接口） | ❌ 不存在 | 已重命名 |
 | `macro_china_fx_reserves` | 外汇储备 | ❌ 不存在 | 已重命名 |
 | `macro_china_consumer_confidence` | 消费者信心指数 | ❌ 不存在 | 已重命名 |

 ### 4.2 香港宏观

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `macro_china_hk_cpi` | 香港 CPI | ✅ 稳定 | 172 条 |
 | `macro_china_hk_gbp` | 香港 GDP | ✅ 稳定 | 74 条 |
 | `macro_china_hk_building_amount` | 香港楼宇买卖金额 | ✅ 稳定 | 223 条 |
 | `macro_china_hk_building_volume` | 香港楼宇买卖数量 | ✅ 稳定 | 223 条 |
 | `macro_china_hk_rate_of_unemployment` | 香港失业率 | ✅ 稳定 | 223 条 |
 | `macro_china_hk_market_info` | 香港 HIBOR | ✅ 稳定 | **2,294 条！** 日频，2017 年至今 |
 | `macro_china_hk_ppi` | 香港 PPI | ⚠️ 未测试 | |
 | `macro_china_hk_cpi_ratio` | 香港 CPI 年率 | ⚠️ 未测试 | |
 | `macro_china_hk_gbp_ratio` | 香港 GDP 同比 | ⚠️ 未测试 | |
 | `macro_china_hk_trade_diff_ratio` | 香港贸易差额年率 | ⚠️ 未测试 | |

 **⚠️ 重大发现：`macro_china_hk_market_info` 提供 HIBOR 日频数据！** 这与我们之前说的"HIBOR 需要从 HKAB 官网 scrape"不同。akshare 已经有这个数据，2,294 条记录，从 2017 年至今，覆盖 1W/2W/1M/2M/3M/6M/12M 所有期限。

 ### 4.3 美国宏观

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `macro_usa_cpi_monthly` | 美国 CPI | ✅ 稳定 | 669 条 |
 | `macro_usa_interest_rate` | 美联储利率 | ❌ 不存在 | 已重命名 |

 ### 4.4 其他宏观

 | 函数类别 | 数量 | 稳定性 | 说明 |
 |---------|------|--------|------|
 | 欧洲 (macro_euro) | 16 | ⚠️ 大部分未测试 | 欧央行/欧元区 |
 | 英国 (macro_uk) | 15 | ⚠️ 大部分未测试 | |
 | 加拿大 (macro_canada) | 10 | ⚠️ 大部分未测试 | |
 | 德国 (macro_germany) | 8 | ⚠️ 大部分未测试 | |
 | 澳大利亚 (macro_australia) | 7 | ⚠️ 大部分未测试 | |
 | 日本 (macro_japan) | 5 | ⚠️ 大部分未测试 | |
 | 瑞士 (macro_swiss) | 6 | ⚠️ 大部分未测试 | |
 | 央行 (macro_bank) | 11 | ⚠️ 大部分未测试 | |

 ---

 ## 5. 指数/ETF/基金

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `fund_etf_spot_em` | ETF 实时行情 | ✅ 稳定 | 1,555 条 |
 | `fund_hk_fund_hist_em` | 香港基金历史净值 | ⚠️ 未测试 | |
 | `fund_hk_rank_em` | 香港基金排行 | ⚠️ 未测试 | |
 | `index_zh_a_hist` | A 股指数历史 | ❌ 不稳定 | 连接被关闭 |
 | `index_zh_a_hist_min_em` | A 股指数分时 | ❌ 不稳定 | 连接被关闭 |
 | `reits_hist_em` | REITs 历史数据 | ❌ 不稳定 | 连接被关闭 |

 ---

 ## 6. 期货/商品/能源

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `energy_oil_hist` | 国内油价历史 | ✅ 稳定 | 325 条 |
 | `energy_carbon_domestic` | 碳市场数据 | ✅ 稳定 | 1,852 条 |
 | `futures_*` (~60 个) | 国内外期货 | ⚠️ 大部分未测试 | 覆盖 SHFE/DCE/CZCE/CFFEX/GFEX |
 | `spot_golden_benchmark_sge` | 上海金基准价 | ✅ 稳定 | 2,494 条，我们已在用 |
 | `spot_*` | 现货价格 | ⚠️ 大部分未测试 | 黄金/白银/铜/大豆等 |

 ---

 ## 7. 债券/外汇

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `bond_china_close_return` | 中国债券收盘收益率 | ❌ 不稳定 | 'newDateValue' 错误 |
 | `bond_*` (~30 个) | 国债/信用债/可转债 | ⚠️ 大部分未测试 | |
 | `fx_quote_baidu` | 百度外汇行情 | ⚠️ 需要 token | 从百度页面手动复制 |
 | `currency_*` | 外汇数据 | ⚠️ 未测试 | |

 ---

 ## 8. 沪深港通/资金流

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `stock_hsgt_fund_flow_summary_em` | 沪深港通资金流汇总 | ✅ 稳定 | 4 条（当日汇总） |
 | `stock_hsgt_sh_hk_spot_em` | 港股通(沪>港)个股 | ❌ 不稳定 | 502 Bad Gateway |
 | `stock_hsgt_*` (10 个) | 沪深港通各种数据 | ⚠️ 大部分未测试 | |
 | `stock_sgt_*` (4 个) | 深股通数据 | ⚠️ 未测试 | |

 ---

 ## 9. 百度系数据

 | 函数 | 数据 | 稳定性 | 备注 |
 |------|------|--------|------|
 | `stock_hk_valuation_baidu` | 港股估值（百度） | ✅ 稳定 | 365 天日频 |
 | `stock_zh_valuation_baidu` | A 股估值（百度） | ✅ 稳定 | 365 天日频 |
 | `stock_us_valuation_baidu` | 美股估值（百度） | ⚠️ 未测试 | |
 | `stock_hot_search_baidu` | 百度热搜股票 | ❌ 不稳定 | API 返回 403 |
 | `stock_zh_vote_baidu` | 百度股市通投票 | ❌ 不稳定 | JSON 解析失败 |
 | `news_economic_baidu` | 百度经济日历 | ❌ 不稳定 | 参数变了 |
 | `fx_quote_baidu` | 百度外汇行情 | ⚠️ 需要 token | |
 | `migration_scale_baidu` | 百度迁徙规模 | ✅ 稳定 | 1,064 条，已有脚本 |
 | `migration_area_baidu` | 百度迁徙详情 | ❌ 不稳定 | 'value' 错误 |

 ---

 ## 10. 与我们 codebase 的关系

 ### 10.1 当前已使用的 akshare 函数

 | 函数 | 使用位置 | 用途 | 稳定性 |
 |------|---------|------|--------|
 | `stock_hk_spot_em` | `minerals_signal_data/market_data.py` | 港股实时行情 | ❌ 不稳定 |
 | `stock_zh_a_spot_em` | `minerals_signal_data/market_data.py` | A 股实时行情 | ❌ 不稳定 |
 | `stock_hk_spot_em` | `hk_reit/sources/reit_price.py` | REIT 价格获取 | ❌ 不稳定 |
 | `stock_hk_hist` | `hk_reit/sources/reit_price.py` | REIT 历史价格 | ❌ 不稳定 |
 | `spot_golden_benchmark_sge` | `hk_local_consumer/sources/sge_gold.py` | 上海金基准价 | ✅ 稳定 |
 | `stock_hk_valuation_baidu` | `hk_local_consumer/sources/hk_valuation.py` | 港股估值数据 | ✅ 稳定 |

 **⚠️ 关键问题：** 我们 codebase 中使用的 3 个最核心函数（`stock_hk_spot_em`、`stock_zh_a_spot_em`、`stock_hk_hist`）在海外 IP 下**都不稳定**。这是 akshare 在我们项目中最大的痛点。

 ### 10.2 已有但未使用的函数（值得添加）

 | 函数 | 数据 | 对我们的价值 | 所属板块 |
 |------|------|-------------|---------|
 | `macro_china_hk_market_info` | HIBOR 日频 | ⭐⭐⭐⭐⭐ 银行板块核心数据 | 金融银行 |
 | `stock_hk_hot_rank_em` | 港股人气榜 | ⭐⭐⭐⭐ 散户情绪 proxy | 所有板块 |
 | `stock_financial_hk_analysis_indicator_em` | 财务分析指标 | ⭐⭐⭐⭐ 基本面数据 | 所有板块 |
 | `stock_hk_dividend_payout_em` | 分红派息 | ⭐⭐⭐⭐ REIT/高息股 | REIT/银行 |
 | `stock_hk_profit_forecast_et` | 券商盈利预测 | ⭐⭐⭐⭐ 前瞻数据 | 所有板块 |
 | `stock_hk_valuation_comparison_em` | 行业估值对比 | ⭐⭐⭐ 行业比较 | 所有板块 |
 | `stock_hk_growth_comparison_em` | 行业成长对比 | ⭐⭐⭐ 行业比较 | 所有板块 |
 | `stock_hk_gxl_lg` | 恒生指数股息率 | ⭐⭐⭐ 宏观情绪 | 宏观 |
 | `energy_carbon_domestic` | 碳市场数据 | ⭐⭐⭐ ESG/能源 | 能源原材料 |
 | `energy_oil_hist` | 国内油价 | ⭐⭐⭐ 能源成本 | 能源原材料 |
 | `stock_hsgt_fund_flow_summary_em` | 沪深港通资金流 | ⭐⭐⭐ 资金流向 | 宏观 |
 | `macro_china_lpr` | 中国 LPR | ⭐⭐⭐ 利率环境 | 银行 |
 | `macro_china_pmi` | 中国 PMI | ⭐⭐⭐ 经济景气度 | 宏观 |
 | `macro_china_money_supply` | M2 货币供应 | ⭐⭐⭐ 流动性 | 宏观 |
 | `fund_etf_spot_em` | ETF 行情 | ⭐⭐ 产品覆盖 | 基金 |

 ---

 ## 11. 稳定性总结

 ### 按数据源分类

 | 数据源 | 稳定性 | 典型函数 | 说明 |
 |--------|--------|---------|------|
 | **东方财富 (eastmoney)** | ⚠️ 两极分化 | | |
 | → 宏观经济类 | ✅ 稳定 | `macro_china_*` | 数据更新及时，连接稳定 |
 | → 港股行情类 | ❌ 不稳定 | `stock_hk_spot_em`, `stock_hk_hist` | 海外 IP 频繁被封 |
 | → A 股行情类 | ⚠️ 部分稳定 | `stock_zh_a_hist` ✅, `stock_zh_a_spot_em` ❌ | 日线稳定，实时不稳定 |
 | **百度股市通** | ⚠️ 部分稳定 | | |
 | → 估值数据 | ✅ 稳定 | `stock_hk_valuation_baidu` | 365 天日频 |
 | → 热搜/投票 | ❌ 不稳定 | `stock_hot_search_baidu` | API 变更/403 |
 | **新浪财经** | ❌ 不稳定 | `stock_hk_spot`, `stock_hk_daily` | 连接不稳定 |
 | **同花顺** | ❌ 不稳定 | `stock_ipo_hk_ths`, `stock_hk_fhpx_detail_ths` | 经常 broken |
 | **乐咕乐股** | ✅ 稳定 | `stock_hk_gxl_lg` | 数据干净 |
 | **经济通** | ✅ 稳定 | `stock_hk_profit_forecast_et` | 盈利预测数据 |
 | **上海黄金交易所** | ✅ 稳定 | `spot_golden_benchmark_sge` | 我们已在用 |

 ### 按功能分类

 | 功能类别 | 整体稳定性 | 最佳函数 |
 |---------|-----------|---------|
 | 宏观经济 | ✅ **高** | `macro_china_*` 系列 |
 | 港股财务/估值 | ✅ **高** | `stock_hk_valuation_baidu`, `stock_hk_financial_indicator_em` |
 | 港股行情 | ❌ **低** | `stock_hk_hist`（不稳定） |
 | A 股日线 | ✅ **中高** | `stock_zh_a_hist` |
 | A 股实时 | ❌ **低** | `stock_zh_a_spot_em`（不稳定） |
 | 行业对比 | ✅ **高** | `stock_hk_*_comparison_em` |
 | 人气/热度 | ✅ **高** | `stock_hk_hot_rank_em` |
 | 期货/商品 | ⚠️ **中** | 部分可用 |
 | 债券 | ❌ **低** | 大部分 broken |

 ---

 ## 12. 推荐优先级

 ### 🔴 立即可用（稳定性高 + 价值高）

 1. **`macro_china_hk_market_info`** — HIBOR 日频数据
    - 2,294 条记录，2017 年至今
    - 银行板块核心数据（NIM 驱动）
    - **比我们之前计划从 HKAB scrape 简单得多**

 2. **`stock_hk_hot_rank_em`** — 港股人气榜
    - Top 100 热门股票排名
    - 散户情绪 proxy
    - 每日更新

 3. **`stock_financial_hk_analysis_indicator_em`** — 港股财务分析
    - ROE/毛利率/净利率等核心指标
    - 按年度/按季度

 4. **`stock_hk_profit_forecast_et`** — 券商盈利预测
    - 51 条券商预测记录
    - 前瞻数据，对 equities research 直接有用

 5. **`stock_hk_dividend_payout_em`** — 分红派息历史
    - REIT/高息股分析必备

 ### 🟡 可以添加（稳定性中等 + 价值中等）

 6. **`stock_hk_valuation_comparison_em`** — 行业估值对比
 7. **`stock_hk_growth_comparison_em`** — 行业成长对比
 8. **`stock_hk_scale_comparison_em`** — 行业规模对比
 9. **`energy_carbon_domestic`** — 碳市场数据
 10. **`energy_oil_hist`** — 国内油价历史
 11. **`macro_china_pmi`** — 中国 PMI
 12. **`macro_china_lpr`** — 中国 LPR

 ### 🔵 慎用（稳定性低 + 需要替代方案）

 13. **`stock_hk_spot_em` / `stock_hk_hist`** — 港股行情
     - 海外 IP 下极不稳定
     - 建议：用 yfinance 作为主数据源，akshare 作为备用

 14. **`stock_hot_search_baidu`** — 百度热搜
     - API 已返回 403
     - 建议：放弃，用 Google Trends 替代

 ### 总结

 akshare 对我们项目的价值主要在**宏观数据 + 财务数据 + 行业对比**三个方面，这些函数稳定性高、数据质量好。**行情数据（实时报价、K 线）是最大的短板**，在海外 IP 下频繁被封，需要用 yfinance 或其他数据源替代。

 **最佳策略：** akshare 用于宏观/财务/行业数据，yfinance 用于行情数据，两者互补。

 ---

 > **下一步：** 可以开始将上述"立即可用"的函数集成到我们的 pipeline 中，特别是 `macro_china_hk_market_info`（HIBOR）和 `stock_hk_hot_rank_em`（人气榜）。
