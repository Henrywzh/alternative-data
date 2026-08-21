# Research Control Tower TODO

> Tencent T0–T3 实施期间的 Backlog。T0–T3 本身以
> \`docs/superpowers/specs/2026-08-21-research-control-tower-tencent-t0-t3-design.md\` 与
> \`docs/superpowers/plans/2026-08-21-tencent-control-tower-t0-t3.md\` 为准。

## After T3（不阻塞 T0–T3 完成）

- [ ] T4.1 Automated NPPA game-approval ingestion（基于 WS-D 探针证据，爬虫稳定后）
- [ ] T4.2 WeChat ecosystem public signals（搜索指数、小程序目录等已验证公开源）
- [ ] T4.3 Listed SOTP portfolio value tracker（Meituan/Kuaishou/Sea 等上市持仓市值跟踪）
- [ ] T4.4 Southbound Stock Connect net inflows for 0700.HK（HKEX Stock Connect）
- [ ] T4.5 Commercial app-intelligence diligence（SensorTower/Data.ai 授权与预算评估）
- [ ] Batch 8：alternative-data signals / thesis checkpoints 接入 Tencent 页
- [ ] 每日调度：quote / consensus / filings 定时采集（batch7 OPS 项）
- [ ] 新闻层接线：Finnhub/Marketaux/FMP key 就绪后启用（Batch 5 代码已合）
- [ ] Stage 1.5（Cathay/MTR/SHKP/Midland）复用同一管线解锁
- [ ] 部署前 licensing/privacy 审计 + Streamlit Cloud 灰度
- [ ] 文档同步：PROJECT_STATUS / DATA_CATALOG / REPO_BRIDGE 更新

## Known debt（实现过程中顺手修）

- [ ] quote_snapshots SLA 应感知 latency_class（delayed 不适用 5 分钟阈值）
- [ ] price_bars 5y vendor replay 的 pit_class 语义（建议 vendor_historical_replay）
- [ ] PROJECT_STATUS RCT 段已过时（仍写 08-14 generation、consensus typed-empty）

