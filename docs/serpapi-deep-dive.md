 SerpAPI Deep Dive: Google Trends / Google Flights / Google Patents
 ================================================================

 > 此文档详细分析 SerpAPI 的三大 Google 数据源，结合项目需求（港股/亚洲股票 alternative data）评估每个数据源的能力、限制和实战价值。
 > 最后更新：2026-07-27

 ---

 ## 目录

 1. [SerpAPI 总览与定价](#1-serpapi-总览与定价)
 2. [Google Trends via SerpAPI](#2-google-trends-via-serpapi)
 3. [Google Flights via SerpAPI](#3-google-flights-via-serpapi)
 4. [Google Patents via SerpAPI](#4-google-patents-via-serpapi)
 5. [与现有代码库的关系](#5-与现有代码库的关系)
 6. [Equities Alt Data 适用性评估](#6-equities-alt-data-适用性评估)
 7. [实施建议](#7-实施建议)

 ---

 ## 1. SerpAPI 总览与定价

 ### 1.1 什么是 SerpAPI

 SerpAPI 是一个搜索引擎结果页 (SERP) 的 API 代理服务。它通过模拟真实搜索行为，返回结构化的 Google 搜索结果 JSON。核心能力是**绕过 Google 的反爬虫机制**，提供稳定的搜索结果 API。

 ### 1.2 支持的 Google 搜索类型

 | 搜索类型 | API 端点 | 描述 |
 |---------|---------|------|
 | Google Search | `google` | 标准网页搜索结果 |
 | Google Trends | `google_trends` | 搜索趋势数据（时间序列 + 地图 + 相关查询） |
 | Google Flights | `google_flights` | 航班搜索结果（价格、时间、航空公司） |
 | Google Patents | `google_patents` | 专利搜索结果 |
 | Google Images | `google_images` | 图片搜索 |
 | Google News | `google_news` | 新闻搜索 |
 | Google Shopping | `google_shopping` | 购物搜索结果 |
 | Google Maps | `google_maps` | 地图/本地搜索 |
 | YouTube | `youtube` | YouTube 搜索和视频 |
 | Google Scholar | `google_scholar` | 学术论文搜索 |
 | Google Books | `google_books` | 图书搜索 |

 ### 1.3 定价与配额

 | 套餐 | 价格 | 月搜索次数 | 平均每次搜索成本 |
 |------|------|-----------|----------------|
 | **Free** | $0/月 | **250 次** | $0 |
 | **Starter** | $25/月 | 1,000 次 | ~$0.025 |
 | **Developer** | $75/月 | 5,000 次 | ~$0.015 |
 | **Production** | $150/月 | 15,000 次 | ~$0.01 |
 | **Big Data** | $275/月 | 30,000 次 | ~$0.009 |
 | **Enterprise** | 定制 | 定制 | 定制 |

 **⚠️ 关键限制：** 免费套餐每月 250 次搜索；当前官方定价页的第一个付费套餐是 Starter（$25/月，1,000 次）。对于日频 pipeline，即使只跟踪 10 个关键词，一个月就需要 ~300 次请求，免费套餐不够用。

 **另外：** 每个搜索类型（Trends、Flights、Patents）各自消耗搜索配额，不共享。即一次 Google Trends 请求 = 1 次搜索配额，一次 Google Flights 请求 = 1 次搜索配额。

 ### 1.4 API 通用参数

 - `engine`: 必填，指定搜索引擎类型（`google_trends`、`google_flights`、`google_patents`）
 - `api_key`: 必填，SerpAPI 密钥
 - `output`: 返回格式，`json`（默认）或 `protobuf`
 - `hl`: 搜索界面语言（如 `en`、`zh-CN`、`zh-TW`）
 - `gl`: 国家/地区偏好（如 `hk`、`us`、`cn`）
 - `no_cache`: 是否绕过缓存（`true`/`false`，默认 `false`）
 - `async`: 异步模式（`true`/`false`），适用于长时间运行的查询

 ---

 ## 2. Google Trends via SerpAPI

 ### 2.1 API 端点与参数

 **端点：** `google` engine with `tbm=trends` 或直接用 `google_trends` engine

 **核心参数：**

 | 参数 | 类型 | 必填 | 描述 |
 |------|------|------|------|
 | `engine` | string | ✅ | `google_trends` |
 | `q` | string | ✅ | 搜索关键词（最多 **5 个**逗号分隔） |
 | `geo` | string | ❌ | 地理位置，如 `US`、`HK`、`CN-GD`（广东） |
 | `timeframe` | string | ❌ | 时间范围（见下方详解） |
 | `date` | string | ❌ | 自定义日期范围，格式 `YYYY-MM-DD YYYY-MM-DD` |
 | `hl` | string | ❌ | 语言，如 `en-US`、`zh-CN` |
 | `tz` | int | ❌ | 时区偏移（分钟），如 HK = `-480` |
 | `category` | int | ❌ | Google Trends 分类 ID |
 | `property` | string | ❌ | `images`、`news`、`youtube` 或 `froogle` |
 | `data_type` | string | ❌ | 返回数据类型（见下方） |

 ### 2.2 `data_type` 数据类型详解

 | data_type | 返回内容 | 数据结构 | 有用字段 |
 |-----------|---------|---------|---------|
 | `TIMESERIES` | 时间序列 | `timeline_data[]` | `date`, `values[].extracted_value`, `values[].has_data`, `values[].formatted_value` |
 | `GEO_MAP` | 地理分布 | `geo_map_data` | `coordinates`, `value`, `formatted_value`, `location_code` |
 | `RELATED_QUERIES` | 相关搜索 | `related_queries` | `query`, `value`, `type`（rising/top） |
 | `RELATED_TOPICS` | 相关主题 | `related_topics` | `topic`, `title`, `type`（rising/top） |
 | `INTEREST_BY_SUBREGION` | 子区域兴趣 | `interest_by_subregion[]` | `location`, `value`, `coordinates` |
 | `INTEREST_BY_CITY` | 城市级兴趣 | `interest_by_city[]` | `location`, `value` |
 | `INTEREST_BY_DMA` | DMA 区域兴趣 | `interest_by_dma[]` | `location`, `value` |
 | `TRENDING_SEARCHES` | 热门搜索 | `trending_searches[]` | `query`, `explore_link` |
 | `REALTIME_TRENDING_SEARCHES` | 实时热门 | `trending_searches[]` | `title`, `entityNames` |
 | `GOOGLE_NEWS` | 新闻 | `news_results[]` | `title`, `link`, `snippet`, `date`, `source` |
 | `YOUTUBE` | YouTube 视频 | `video_results[]` | `title`, `link`, `views`, `channel` |
 | `SERP_API_DATA` | API 元数据 | 请求信息 | 请求消耗、配额等 |

 ### 2.3 时间范围 (timeframe) 详解

 | timeframe 值 | 含义 | 数据粒度 | 可用历史 |
 |--------------|------|---------|---------|
 | `now 1-H` | 过去 1 小时 | 分钟 | ~1 小时 |
 | `now 4-H` | 过去 4 小时 | 分钟 | ~4 小时 |
 | `now 1-d` | 过去 1 天 | 分钟 | ~1 天 |
 | `now 7-d` | 过去 7 天 | 日 | ~7 天 |
 | `today 1-m` | 过去 1 个月 | 日 | ~1 个月 |
 | `today 3-m` | 过去 3 个月 | 周 | ~3 个月 |
 | `today 12-m` | 过去 12 个月 | 周 | ~12 个月 |
 | `today 5-y` | 过去 5 年 | 周 | ~5 年 |
 | `today 10-y` | 过去 10 年 | 周 | ~10 年 |
 | `2004-01-01 2026-07-25` | 自定义范围 | 自定义 | **2004 年至今**（Google Trends 最早数据） |

 **⚠️ 注意：** 自定义日期范围格式为 `YYYY-MM-DD YYYY-MM-DD`（空格分隔，不是连字符）。

 **⚠️ 历史深度限制：**

 - **2004-2008：** 数据稀疏，很多关键词无数据
 - **2008-2012：** 数据逐渐完整，但粒度较粗
 - **2012-2016：** 数据质量良好，周粒度
 - **2016-至今：** 数据最完整，日粒度（短期范围内）

 ### 2.4 地理范围 (geo) 详解

 Google Trends 的地理范围极其精细：

 | 地理级别 | 格式示例 | 描述 |
 |---------|---------|------|
 | 全球 | `""` 或不填 | 全球搜索量 |
 | 国家 | `US`、`HK`、`CN`、`JP` | 国家级别 |
 | 美国州 | `US-CA`（加州） | 州级别 |
 + | 美国 DMA | `US-DM-501` | 设计市场区域（电视市场） |
 | 美国地铁 | `US-DM-501` | 大都市统计区 |
 | 中国省 | `CN-GD`（广东） | 省级（Google Trends 支持中国省份！） |
 | 中国城市 | `CN-GD-101` | 城市级（部分城市） |
 | 香港 | `HK` | 香港特别行政区 |
 | 台湾 | `TW` | 台湾地区 |
 | 英国郡 | `GB-ENG` | 英格兰 |

 **⚠️ 关于中国数据的特殊说明：**

 - Google Trends 支持中国省份/城市级别搜索量数据
 - 但 Google 在中国大陆被屏蔽，所以数据反映的是**使用 VPN/海外访问 Google 的中国用户**
 - 对于覆盖大陆用户的关键词，**百度指数是更好的选择**（覆盖 100% 中国搜索市场）
 - Google Trends 的中国数据更适合覆盖**海外华人 / 港台用户**的搜索行为

 ### 2.5 与现有代码库的关系

 **现有 pipeline：** `src/google_trends_data/`

 - 使用 **trendspyg** 库（免费，直接调用 Google Trends）
 - `fetcher.py` → `download_google_trends_interest_over_time()` → 返回 DataFrame
 - 支持 `keyword`、`geo`、`timeframe` 参数
 - 只获取 `TIMESERIES`（时间序列）数据

 **SerpAPI Google Trends 能力增量：**

 | 能力 | trendspyg（现有） | SerpAPI（新增） |
 |------|-----------------|----------------|
 | 时间序列 (TIMESERIES) | ✅ 已有 | ✅ |
 | 地理分布 (GEO_MAP) | ❌ | ✅ **新增** |
 | 子区域兴趣 (INTEREST_BY_SUBREGION) | ❌ | ✅ **新增** |
 | 城市级兴趣 (INTEREST_BY_CITY) | ❌ | ✅ **新增** |
 | DMA 区域兴趣 | ❌ | ✅ **新增** |
 | 相关查询 (RELATED_QUERIES) | ❌ | ✅ **新增** |
 | 相关主题 (RELATED_TOPICS) | ❌ | ✅ **新增** |
 | 趋势搜索 (TRENDING_SEARCHES) | ❌ | ✅ **新增** |
 | YouTube 搜索趋势 | ❌ | ✅ **新增** |
 | 价格 | 免费 | $75+/月 |
 | 稳定性 | 有时被 Google 封锁 | 非常稳定 |
 | 历史深度 | 2004+ | 2004+ |

 **结论：** trendspyg 能获取时间序列，SerpAPI 增加了**地理分布 + 相关查询 + 趋势搜索**三个关键维度。对于我们的 equities alt data，最有价值的增量是：

 1. **INTEREST_BY_SUBREGION/CITY** → 看某个品牌在不同城市/地区的热度分布
 2. **RELATED_QUERIES** → 发现新的搜索关键词（"rising" 类型的查询可能是未被覆盖的信号）
 3. **REALTIME_TRENDING_SEARCHES** → 捕捉突发新闻事件

 ### 2.7 2026-07-27 SerpAPI 时间序列验证

 对现有项目的历史验证目标 `Pop Mart`（Worldwide，`today 5-y`）执行了一次 SerpAPI `TIMESERIES` 请求。结果：

 - 返回 `262` 个唯一周度时间点，时间戳单调递增、间隔均为 7 天，无缺失值，数值范围为 `1–100`。
 - 最新周为 `2026-07-26`，并标记为 partial；现有仓库数据最新周为 `2026-07-19`。
 - 与现有 `data/raw/google_trends/pop_mart_worldwide_trends.parquet` 的 `261` 周重叠区间中，`170` 个值完全相同。
 - SerpAPI 与现有序列的 Pearson 相关系数为 `0.9992`，平均绝对差为 `1.6`，最大差为 `5`。

 **结论：** SerpAPI 返回的数据结构完整、与现有信号高度可比，适合继续验证和迁移；但由于滚动五年窗口及 Google Trends 历史归一化/修订，不能把它视为旧序列的逐值复制。迁移时应记录数据源变更，不应静默覆盖旧数据。

 ### 2.8 当前 Google Trends 月度请求预算

 为保持现有每个 keyword/geo 序列的归一化含义，初始迁移按每个 keyword/geo pair 使用 1 次 SerpAPI 请求；虽然 API 单次最多接受 5 个 query，但不同 `geo` 不能放在同一次请求中，且批量比较可能改变相对归一化。

 当前 watchlist 已暂停 `BKNG` 和 `III.L`，只启用 Pop Mart 的 5 个 keyword/geo pairs：

 | 运行频率 | 计算 | 预计请求/月 |
 |---------|------|------------|
 | 每周 | `5 × 52 ÷ 12` | **约 22** |
 | 每周 + 1 次验证 | `5 × 52 ÷ 12 + 1` | **约 23** |

 如果恢复全部 18 个 pairs：

 | 运行频率 | 计算 | 预计请求/月 |
 |---------|------|------------|
 | 每周 | `18 × 52 ÷ 12` | **约 78** |
 | 每周 + 1 次验证 | `18 × 52 ÷ 12 + 1` | **约 79** |
 | 每日 | `18 × 30` | **约 540** |

 因此，当前每周 Pop Mart 刷新只占免费套餐约 `9%`；完整每周 watchlist 约占 `31%`，仍在 250 次免费额度内；完整日频刷新则需要付费套餐。SerpAPI 的精确参数缓存命中不计入额度，但预算应按未命中、成功请求计算。

 ### 2.6 Equities Alt Data 应用场景

 | 场景 | 数据类型 | 股票示例 | 预期信号 |
 |------|---------|---------|---------|
 | 新品发布热度 | TIMESERIES + GEO_MAP | AAPL（iPhone）、NTDOY（Switch 2） | 发布前搜索量激增 → 需求预期 |
 | 品牌区域分布 | INTEREST_BY_CITY | NKE、ADS.DE（区域热度差异） | 特定市场增长/衰退 |
 | 保险/金融搜索趋势 | TIMESERIES | 1299.HK（AIA）、2318.HK（平安） | 购买意愿领先指标 |
 | 竞品发现 | RELATED_QUERIES | 所有公司 | 发现新兴竞争者 |
 | 旅游/消费意愿 | TIMESERIES | BKNG、ABNB、0297.HK（Cathay） | 预订量领先指标 |
 | 药品需求 | TIMESERIES | NVO、LLY | 处方量 proxy |
 | 电子产品需求 | TIMESERIES + RELATED | AAPL、三星 | 产品代际更新周期 |

 ---

 ## 3. Google Flights via SerpAPI

 ### 3.1 API 端点与参数

 **端点：** `google_flights` engine

 **核心参数：**

 | 参数 | 类型 | 必填 | 描述 |
 |------|------|------|------|
 | `engine` | string | ✅ | `google_flights` |
 | `departure_id` | string | ✅ | 出发地机场 IATA 代码（如 `HKG`、`NRT`、`LAX`） |
 | `arrival_id` | string | ✅ | 目的地机场 IATA 代码（如 `LAX`、`HKG`、`NRT`） |
 | `outbound_date` | string | ✅ | 出发日期 `YYYY-MM-DD` |
 | `return_date` | string | ❌ | 返回日期 `YYYY-MM-DD`（单程则不填） |
 | `type` | string | ❌ | `2`（往返，默认）或 `1`（单程） |
 | `travel_class` | string | ❌ | `1`（经济）、`2`（高级经济）、`3`（商务）、`4`（头等） |
 | `adults` | int | ❌ | 成人数量（默认 1） |
 | `currency` | string | ❌ | 货币代码（如 `HKD`、`USD`） |
 | `hl` | string | ❌ | 界面语言 |
 | `gl` | string | ❌ | 国家偏好 |
 | `show_hidden` | string | ❌ | 显示隐藏航班（`true`/`false`） |
 | `departure_token` | string | ❌ | 用于翻页的 token |
 | `nearby_airports` | string | ❌ | 是否搜索附近机场（`true`/`false`） |
 | `layovers` | string | ❌ | 中转机场代码，逗号分隔 |
 | `max_stops` | int | ❌ | 最大中转次数（`0` = 直飞） |
 | `outbound_date` | string | ❌ | 延伸搜索的开始日期 |
 | `return_date延伸` | string | ❌ | 延伸搜索的结束日期 |

 ### 3.2 返回数据结构

 #### Best Flights（最佳航班）

 ```json
 {
   "search_metadata": { ... },
   "best_flights": [
     {
       "flights": [
         {
           "departure_airport": "HKG",
           "arrival_airport": "NRT",
           "departure_time": "2026-08-01 09:30",
           "arrival_time": "2026-08-01 14:15",
           "duration": 285,
           "airline": "Cathay Pacific",
           "airline_logo": "https://...",
           "travel_class": "Economy",
           "aircraft": "Boeing 777-300ER",
           "winglet": false,
           "extra_legroom": false,
           "carbon_emissions": { "this_flight": 291000, "typical_for_this_route": 370000, "difference": "-22%", "confidence": 100 },
           "extensions": ["Wi-Fi", "USB Outlet", "Live TV"]
         }
       ],
       "price": 4850,
       "type": "One way",
       "airline_logo": "https://...",
       "departure_token": "...",
       "booking_token": "..."
     }
   ],
   "other_flights": [ ... ],
   "price_insights": {
     "lowest_price": 4850,
     "price_level": "Low",
     "typical_price_range": { "low": 4200, "high": 6100 }
   },
   "flight_standing": { "status": "Flight price is Standing", "carbon_difference": "-22%" }
 }
 ```

 #### Date Grid / Price Grid（日期网格 / 价格网格）

 通过 `departure_token` 可以获取：

 - `outbound_dates`：不同出发日期的价格矩阵
 - `return_dates`：不同返回日期的价格矩阵

 这是**价格日历**功能，显示一个月内每天的最低票价。

 #### Nearby Airports（附近机场）

 - 自动推荐出发地/目的地的备选机场

 ### 3.3 数据范围与限制

 | 维度 | 能力 | 限制 |
 |------|------|------|
 | **历史数据** | ❌ **无历史数据** | 只能搜索当前和未来的航班 |
 | **价格历史** | ❌ **无历史价格** | 无法查看过去的价格 |
 | **实时价格** | ✅ 实时 Google Flights 价格 | 数据即时，反映当前市场 |
 | **日期范围** | 约 11 个月内的航班 | 超过 11 个月无法搜索 |
 | **机场覆盖** | 全球主要机场 | 小型/支线机场可能不完整 |
 | **航司覆盖** | 全球大部分航司 | 部分廉航可能不在 Google Flights 中 |
 | **搜索频率** | 无明确限制 | 但高频率可能触发限流 |

 **⚠️ 关键限制：Google Flights API 没有历史数据。** 这意味着：

 - 无法回测"如果当时有这个信号会怎样"
 - 只能从今天开始累积数据
 - 对于 equities research，这是一个**前瞻性信号**，需要持续采集才有价值

 ### 3.4 Equities Alt Data 应用场景

 | 场景 | 数据维度 | 股票 | 信号含义 |
 |------|---------|------|---------|
 | **Cathay Pacific 座位需求** | 航班价格 + 可用座位 | 0297.HK | 商务舱价格↑ = 需求强劲 → 收入预期↑ |
 | **航线容量变化** | 航班频率 + 直飞 vs 中转 | 0297.HK | 新开航线 = 扩张信号 |
 | **旅游需求趋势** | 出发地→目的地价格 | BKNG、ABNB | 价格↑ = 需求↑ = 预订收入↑ |
 | **商务旅行活跃度** | 商务舱价格 + 航班频率 | HSBC、0005.HK | 商务舱需求反映商业活动 |
 | **碳排放追踪** | `carbon_emissions` 字段 | ESG 投资 | 航空公司碳效率对比 |
 | **廉航竞争格局** | 价格差异 + 航班频率 | LCC 股票 | 价格战 / 市场份额变化 |
 | **跨境流动（港-内地）** | HKG↔PEK/PVG 价格 | 中银香港、AIA | 价格↑ = 旅行需求↑ = 跨境业务活跃 |

 ### 3.5 具体搜索示例

 ```
 # Cathay Pacific 香港→东京 商务舱
 GET /search?engine=google_flights&departure_id=HKG&arrival_id=NRT
   &outbound_date=2026-08-01&type=1&travel_class=3&currency=HKD

 # 港→深 高铁/航班 价格对比
 GET /search?engine=google_flights&departure_id=HKG&arrival_id=SZX
   &outbound_date=2026-08-01&type=1&currency=HKD

 # 价格日历（HKG→LAX 2026年8月）
 GET /search?engine=google_flights&departure_id=HKG&arrival_id=LAX
   &outbound_date=2026-08-01&type=1
   # 然后用 outbound_token 获取 date grid
 ```

 ### 3.6 对我们的价值评估

 **优势：**

 - 实时价格数据，反映真实市场供需
 - 碳排放数据（独特 alt data）
 - 商务舱/头等舱价格是经济活动的敏感指标
 - 免费额度内可以做少量定期采集

 **劣势：**

 - **没有历史数据** → 无法回测，需要从零开始积累
 - 每次搜索消耗 1 次配额 → 250 次/月只能覆盖少量航线
 - 价格波动可能受燃油附加费、汇率等非需求因素影响
 - 数据更新频率受限于 API 调用频率

 **建议用途：**

 1. **Cathay Pacific (0297.HK)** → 每周采集 HKG→主要目的地的商务舱/经济舱价格
 2. **旅游股（BKNG、ABNB）** → 月度采集热门航线价格趋势
 3. **跨境流动** → 定期采集 HKG↔内地航线价格

 ---

 ## 4. Google Patents via SerpAPI

 ### 4.1 API 端点与参数

 **端点：** `google_patents` engine

 **核心参数：**

 | 参数 | 类型 | 必填 | 描述 |
 |------|------|------|------|
 | `engine` | string | ✅ | `google_patents` |
 | `q` | string | ✅ | 搜索关键词（支持全文搜索语法） |
 | `assignee` | string | ❌ | 受让人/公司名称（如 `TSMC`、`Samsung`） |
 | `inventor` | string | ❌ | 发明人姓名 |
 | `type` | string | ❌ | `patent`（专利）或 `application`（申请） |
 | `status` | string | ❌ | `GRANT`（已授权）或 `APPLICATION`（申请中） |
 | `country` | string | ❌ | 国家代码（如 `US`、`CN`、`HK`） |
 | `before` | string | ❌ | 在此日期之前（`YYYYMMDD` 格式） |
 | `after` | string | ❌ | 在此日期之后（`YYYYMMDD` 格式） |
 | `priority` | string | ❌ | 优先权日期范围 |
 | `filing` | string | ❌ | 申请日期范围 |
 | `publication` | string | ❌ | 公开日期范围 |
 | `cpc` | string | ❌ | CPC 分类代码（如 `H01L` = 半导体） |
 | `page` | int | ❌ | 分页（每页 10 条结果） |

 ### 4.2 返回数据结构

 ```json
 {
   "search_metadata": { ... },
   "search_information": {
     "total_results": 12345,
     "page": 1,
     "pages": 1235
   },
   "organic_results": [
     {
       "title": "Semiconductor device and manufacturing method thereof",
       "patent_id": "US11234567B2",
       "patent_status": "GRANT",
       "publication_number": "US2023012345A1",
       "application_number": "US17/123456",
       "assignee": "Taiwan Semiconductor Manufacturing Company Ltd.",
       "inventors": ["John Doe", "Jane Smith"],
       "publication_date": "2023-06-15",
       "filing_date": "2021-09-30",
       "priority_date": "2020-10-01",
       "grant_date": "2023-03-14",
       "abstract": "A semiconductor device comprising...",
       "claims": ["1. A semiconductor device comprising...", ...],
       "cpc_codes": ["H01L 23/00", "H01L 21/00"],
       "ipc_codes": ["H01L 23/00"],
       "url": "https://patents.google.com/patent/US11234567B2/en",
       "pdf_url": "https://patentimages.storage.googleapis.com/...",
       "similar_patents": [ ... ],
       "family_size": 12,
       "cited_by_count": 5,
       "citations": [ ... ],
       "legal_events": [ ... ]
     }
   ],
   "filters": {
     "patents_by_status": { ... },
     "patents_by_type": { ... },
     "patents_by_country": { ... },
     "patents_by_cpc_code": { ... }
   },
   "graph": {
     "citations": { ... },
     "family": { ... }
   }
 }
 ```

 ### 4.3 历史深度与覆盖范围

 | 维度 | 能力 | 说明 |
 |------|------|------|
 | **历史深度** | **1790 年至今** | 美国专利从 1790 年开始数字化 |
 | | | 中国专利从 ~1985 年开始 |
 | | | 欧洲专利从 ~1978 年开始 |
 | | | 日本专利从 ~1970 年代开始 |
 | **专利类型** | 发明专利 + 实用新型 | 外观设计也可搜索 |
 | **国家覆盖** | 100+ 个国家/地区 | US、CN、EP、JP、KR、TW、HK 等 |
 | **数据来源** | Google Patents（基于 Lens.org 数据） | 专利 + 商标 + 域名 |
 | **更新频率** | 每周 | 专利局公开后通常 1-2 周内上线 |

 ### 4.4 CPC 分类代码（对我们的用途）

 | CPC 代码 | 领域 | 相关股票 |
 |----------|------|---------|
 | `H01L` | 半导体器件 | TSMC、Samsung、SK Hynix、中芯国际 |
 | `H04W` | 无线通信 | 华为、Qualcomm、MediaTek |
 | `G06F` | 电数字数据处理 | NVIDIA、AMD、Intel |
 | `G06N` | AI/机器学习 | NVIDIA、Google、百度、商汤 |
 | `H04N` | 图像通信 | Sony、Samsung |
 | `B60L` | 电动汽车 | BYD、Tesla、宁德时代 |
 | `B25J` | 工业机器人 | Fanuc、ABB、大疆 |
 | `C07K` | 生物技术/抗体 | 信达生物、百济神州 |
 | `A61K` | 医药制剂 | 恒瑞医药、药明生物 |
 | `H02J` | 储能/电力 | 宁德时代、比亚迪储能 |

 ### 4.5 搜索语法详解

 Google Patents 支持强大的搜索语法：

 ```
 # 全文搜索
 q="lithium battery" OR "solid state battery"

 # 按公司（受让人）
 assignee="CATL" OR assignee="宁德时代"

 # 按 CPC 分类
 cpc="H01L 23/00"

 # 按日期范围
 after="20200101" before="20260101"

 # 组合搜索
 q="AI chip" assignee="TSMC" cpc="G06N" after="20230101"

 # 中国专利
 q="半导体" country="CN" type="patent" after="20230101"

 # 港专利
 q="fintech" country="HK" type="patent"
 ```

 ### 4.6 Equities Alt Data 应用场景

 | 场景 | 搜索策略 | 股票 | 信号含义 |
 |------|---------|------|---------|
 | **半导体技术周期** | CPC=H01L + 关键词 + 日期范围 | TSMC、三星、SK Hynix | 专利申请量领先技术周期 2-3 年 |
 | **AI 芯片竞争** | `AI chip` OR `neural processing` + 公司名 | NVIDIA、AMD、Intel | 专利布局反映技术路线 |
 | **新能源技术** | CPC=B60L/B25J + 固态电池/钠离子 | BYD、宁德时代 | 技术护城河评估 |
 | **生物制药管线** | CPC=C07K/A61K + 公司名 | 信达、百济、药明 | 专利 = 管线价值 |
 | **5G/6G 技术** | CPC=H04W + 关键词 | 华为、中兴 | 标准必要专利 (SEP) 数量 |
 | **碳捕捉/ESG 技术** | CPC=B01D/C02F + 关键词 | ESG 相关股票 | 绿色技术专利竞赛 |
 | **技术侵权风险** | 引用分析 + 诉讼趋势 | 所有公司 | 专利诉讼风险评估 |

 ### 4.7 专利数据的独特价值

 专利数据在 equities research 中有**不可替代的价值**：

 1. **领先指标**：专利申请到公开有 18 个月延迟，但公开到产品上市还有 2-5 年 → 专利公开是技术方向的最早信号

 2. **护城河量化**：专利数量 + 引用次数 + 家族规模 = 可量化的技术护城河

 3. **竞争情报**：通过 assignee 搜索，可以看到竞争对手的技术布局

 4. **行业趋势**：CPC 分类的专利申请量变化 = 行业技术热度

 5. **并购信号**：小公司的专利组合突然被大公司引用 → 可能是收购前兆

 ---

 ## 5. 与现有代码库的关系

 ### 5.1 已有 Google Trends Pipeline（src/google_trends_data/）

 | 组件 | 文件 | 功能 | SerpAPI 增量 |
 |------|------|------|-------------|
 | 获取器 | `fetcher.py` | trendspyg 时间序列 | 可增加 SerpAPI 获取器用于地理/相关查询 |
 | 信号合成 | `signal.py` | 周频 + 股价对齐 | 无需改动 |
 | 存储 | `storage.py` | Parquet 读写 | 可扩展支持地理数据 |
 | 监控列表 | `watchlist.json` | 17 只股票 × 关键词 | 可增加保险/银行/能源关键词 |
 | 自动化 | `automation.py` | watchlist 刷新 | 可增加 SerpAPI 地理数据刷新 |
 | CLI | `cli.py` / `batch_cli.py` | 命令行入口 | 可增加 SerpAPI 子命令 |

 ### 5.2 需要新建的模块

 | 模块 | 用途 | 优先级 |
 |------|------|--------|
 | `src/serpapi_flights/` | Google Flights 数据采集 | 中（Cathay 航线监控） |
 | `src/serpapi_patents/` | Google Patents 数据采集 | 高（半导体/生物制药） |
 | `src/serpapi_trends_geo/` | Google Trends 地理数据 | 低（已有 trendspyg 覆盖时间序列） |

 ### 5.3 GitHub Actions 集成

 每个新模块需要对应的 GitHub Actions workflow：

 ```yaml
 # .github/workflows/serpapi-flights-daily.yml
 name: SerpAPI Flights Daily
 on:
   schedule:
     - cron: '0 6 * * *'  # 每天 UTC 06:00（HKT 14:00）
   workflow_dispatch:

 env:
   SERPAPI_KEY: ${{ secrets.SERPAPI_KEY }}

 jobs:
   fetch:
     runs-on: ubuntu-latest
     steps:
       - uses: actions/checkout@v4
       - uses: actions/setup-python@v5
         with:
           python-version: '3.12'
       - run: pip install -r requirements.txt
       - run: python -m src.serpapi_flights.cli
 ```

 ---

 ## 6. Equities Alt Data 适用性评估

 ### 6.1 综合评分

 | 数据源 | 历史深度 | 地理覆盖 | 数据质量 | 实施难度 | 成本 | Equities 价值 | 总评 |
 |--------|---------|---------|---------|---------|------|-------------|------|
 | **Google Trends (trendspyg)** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | **A** |
 | **Google Trends (SerpAPI)** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | **B+** |
 | **Google Flights** | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | **B-** |
 | **Google Patents** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | **A+** |

 ### 6.2 推荐优先级

 1. **🥇 Google Patents** — 最高价值
    - 历史深度最长（1790+），覆盖全球
    - 专利数据是 equities research 的**不可替代信号**
    - 对半导体（TSMC/Samsung）和生物制药（信达/百济）特别有用
    - 免费额度足够月度采集
    - 建议：每周采集目标公司的新公开专利

 2. **🥈 Google Trends (trendspyg + SerpAPI 增量)** — 高价值，低成本
    - 已有免费 pipeline 在运行
    - SerpAPI 增加地理分布 + 相关查询维度
    - 建议：保持 trendspyg 作为主数据源，SerpAPI 用于补充地理数据
    - 保险/银行/能源关键词待添加

 3. **🥉 Google Flights** — 中等价值，需要积累
    - 没有历史数据，需要从今天开始积累
    - 对 Cathay Pacific 有直接价值
    - 建议：每周采集 5-10 条核心航线，积累 3 个月后才有意义

 ### 6.3 配额分配建议（250 次/月）

 | 用途 | 每月请求次数 | 说明 |
 |------|------------|------|
 | Google Patents（5 家公司） | ~20 次 | 每周 5 次（每公司 1 次） |
 | Google Trends 地理数据（3 个关键词） | ~30 次 | 每周 ~8 次 |
 | Google Flights（2 条航线） | ~8 次 | 每周 2 次 |
 | 趋势搜索（监控） | ~30 次 | 每天 1 次 |
 | 相关查询（关键词扩展） | ~20 次 | 每周 5 次 |
 | **总计** | **~108 次** | 占 250 次配额的 43% |

 **结论：** 250 次/月的免费套餐可以支撑一个最小化的月度采集 pipeline，但日频采集需要付费套餐（$75/月 Solo）。

 ---

 ## 7. 实施建议

 ### 7.1 Phase 1：Google Patents（最高 ROI）

 **目标：** 建立半导体和生物制药的专利监控

 **步骤：**

 1. 新建 `src/serpapi_patents/` 模块
 2. 实现 `fetcher.py`（搜索 + 分页）
 3. 实现 `storage.py`（Parquet 存储）
 4. 添加 watchlist（目标公司 + CPC 分类）
 5. GitHub Actions 定时采集
 6. 在 dashboard 中展示专利趋势

 **目标公司（第一批）：**

 - TSMC（2330.TW / TSM）— CPC: H01L
 - Samsung（005930.KS）— CPC: H01L
 - NVIDIA（NVDA）— CPC: G06N
 - 信达生物（1801.HK）— CPC: C07K
 - 百济神州（6160.HK / BGNE）— CPC: A61K

 ### 7.2 Phase 2：Google Trends 增量

 **目标：** 用 SerpAPI 补充地理分布和相关查询

 **步骤：**

 1. 在 `src/google_trends_data/` 中添加 SerpAPI 获取器
 2. 添加保险/银行/能源关键词到 watchlist
 3. 实现 `INTEREST_BY_CITY` 和 `RELATED_QUERIES` 采集
 4. 将地理数据存入 Parquet

 ### 7.3 Phase 3：Google Flights（Cathay 监控）

 **目标：** 追踪 Cathay Pacific 核心航线价格

 **步骤：**

 1. 新建 `src/serpapi_flights/` 模块
 2. 定义核心航线（HKG→NRT/HND/LAX/SIN/BKK）
 3. 每周采集商务舱/经济舱价格
 4. 与 Cathay 股价做相关性分析
 5. 3 个月后评估信号质量

 ### 7.4 注意事项

 1. **配额管理**：250 次/月极其有限，需要严格控制请求频率
 2. **缓存策略**：SerpAPI 有内置缓存（同参数 24 小时内返回缓存结果，不消耗配额）
 3. **错误处理**：API 可能返回错误（超时、限流等），需要重试逻辑
 4. **数据质量**：SerpAPI 返回的数据可能有字段缺失，需要验证
 5. **成本控制**：如果需要日频采集，预算 $75-150/月
 6. **合规性**：确认 SerpAPI 的使用条款允许商业用途

 ---

 ## 附录 A：SerpAPI Google Trends 返回示例

 ```json
 {
   "search_metadata": {
     "id": "...",
     "status": "Success",
     "json_endpoint": "https://serpapi.com/searches/.../.json",
     "created_at": "2026-07-25 12:00:00 UTC",
     "processed_at": "2026-07-25 12:00:01 UTC",
     "total_time_taken": 1.23
   },
   "interest_over_time": {
     "timeline_data": [
       {
         "date": "Jul 20, 2026",
         "values": [
           {
             "query": "AIA insurance",
             "value": 75,
             "extracted_value": 75,
             "has_data": true,
             "formatted_value": "75",
             "content_as_percentage": "75%"
           }
         ]
       }
     ],
     "averages": [{ "query": "AIA insurance", "value": 65 }]
   },
   "interest_by_region": {
     "avg": [
       {
         "location": "Hong Kong",
         "value": 100,
         "coordinates": { "lat": 22.3193, "lng": 114.1694 },
         "formatted_value": "100"
       },
       {
         "location": "Guangdong",
         "value": 45,
         "coordinates": { "lat": 23.1291, "lng": 113.2644 },
         "formatted_value": "45"
       }
     ]
   },
   "related_queries": {
     "AIA insurance": {
       "top": [
         { "query": "aia insurance hong kong", "value": 100 },
         { "query": "aia china", "value": 45 },
         { "query": "友邦保险", "value": 38 }
       ],
       "rising": [
         { "query": "aia critical illness", "value": 850, "extracted_value": 850 }
       ]
     }
   }
 }
 ```

 ## 附录 B：SerpAPI Google Flights 返回示例

 ```json
 {
   "search_metadata": { ... },
   "best_flights": [
     {
       "flights": [
         {
           "departure_airport": "HKG",
           "arrival_airport": "NRT",
           "departure_time": "2026-08-01 09:30",
           "arrival_time": "2026-08-01 14:15",
           "duration": 285,
           "airline": "Cathay Pacific",
           "travel_class": "Business",
           "aircraft": "Boeing 777-300ER",
           "carbon_emissions": {
             "this_flight": 582000,
             "typical_for_this_route": 740000,
             "difference": "-21%"
           }
         }
       ],
       "price": 18500,
       "type": "Round trip"
     }
   ],
   "price_insights": {
     "lowest_price": 18500,
     "price_level": "Medium",
     "typical_price_range": { "low": 15000, "high": 24000 }
   }
 }
 ```

 ## 附录 C：SerpAPI Google Patents 返回示例

 ```json
 {
   "search_metadata": { ... },
   "search_information": {
     "total_results": 12345,
     "page": 1,
     "pages": 1235
   },
   "organic_results": [
     {
       "title": "Advanced semiconductor packaging with integrated heat dissipation",
       "patent_id": "US11876543B2",
       "patent_status": "GRANT",
       "assignee": "Taiwan Semiconductor Manufacturing Company Ltd.",
       "inventors": ["Wei-Lin Chang", "Chia-Wen Li"],
       "publication_date": "2026-03-10",
       "filing_date": "2024-06-15",
       "priority_date": "2023-06-20",
       "abstract": "A semiconductor package comprising a thermal interface material...",
       "cpc_codes": ["H01L 23/00", "H01L 21/00"],
       "family_size": 8,
       "cited_by_count": 3,
       "url": "https://patents.google.com/patent/US11876543B2/en"
     }
   ],
   "filters": {
     "patents_by_status": {
       "GRANT": 8000,
       "APPLICATION": 4345
     },
     "patents_by_country": {
       "US": 7500,
       "CN": 3000,
       "EP": 1845
     }
   }
 }
 ```

 ---

 > **总结：** SerpAPI 为我们的 alt data pipeline 提供了三个独特的 Google 数据源。其中 Google Patents 价值最高（历史最长、信号最独特），Google Trends 增量次之（地理分布 + 相关查询），Google Flights 最弱（无历史数据但对 Cathay 有直接价值）。建议按 Patents → Trends 增量 → Flights 的顺序实施。
