# Research Control Tower TODO

> Tencent T0–T3 实施期间的 Backlog。T0–T3 本身以
> `docs/superpowers/specs/2026-08-21-research-control-tower-tencent-t0-t3-design.md` 与
> `docs/superpowers/plans/2026-08-21-tencent-control-tower-t0-t3.md` 为准。
> 计划状态：T0–T3 已实施并完成 integrity review；当前 `CURRENT` 指向完整
> 的 Tencent vertical-slice generation。

## T0–T3 已完成

- [x] T0–T3 vertical slice、统一 source wiring 与 fail-closed publication contract 已实施并审查。
- [x] Macro vintage/capture identity、SEC physical-document identity、bounded consensus prior FK 已加入 focused tests。
- [x] `PROJECT_STATUS.md`、`DATA_CATALOG.md` 与当前 generation/counts 已同步。

## T4+（不阻塞 T0–T3 完成）

- [ ] T4.1 自动 NPPA 游戏审批抓取（根据可行性探针证据，爬虫稳定后）
- [ ] T4.2 WeChat 生态公开信号（搜索指数、小程序目录等已验证公开源）
- [ ] T4.3 上市 SOTP 持仓市值跟踪（Meituan/Kuaishou/Sea 等）
- [ ] T4.4 0700.HK 南向 Stock Connect 净流入（HKEX Stock Connect）
- [ ] T4.5 商业 app 情报尽职调查（SensorTower/Data.ai 授权与预算评估）
- [ ] Batch 8：alternative-data signals / thesis checkpoints 接入 Tencent 页（OpenRouter Hy3/Hunyuan 用量、已验证的仓位/股东结构 feed；App 榜单绝不作为无条件信号，必须先验证数据契约与授权）
- [ ] 全局宏观 upcoming-calendar wiring（US/CN/HK release events 进 events.parquet，统一管线，无需 key）
- [ ] 每日调度：quote / consensus / filings 定时采集（batch7 OPS 项）
- [ ] 新闻层接线：Finnhub/Marketaux/FMP key 就绪后启用（Batch 5 代码已合）
- [ ] Stage 1.5（Cathay/MTR/SHKP/Midland）复用同一管线解锁
- [ ] 部署前 licensing/privacy 审计 + Streamlit Cloud 灰度

## Known debt（实现过程中顺手修）

- [ ] quote_snapshots SLA 应感知 latency_class（delayed 不适用 5 分钟阈值）
- [ ] price_bars 5y vendor replay 的 pit_class 语义（建议 vendor_historical_replay）
