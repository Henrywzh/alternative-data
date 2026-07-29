# ATS (Applicant Tracking System) 探索 — Workday & Lever

> 当前 pipeline 已经支持 **Greenhouse** 和 **Ashby** 的公开 API。
> 目标是扩展到更多公司（特别是金融、保险、能源），需要理解它们的 ATS 生态。

---

## 一、Lever

### API 情况

Lever 提供 **公开的 REST API**，无需认证：
```
https://api.lever.co/v0/postings/{board_token}?mode=json
```

board_token 可以在公司招聘页 URL 里找到：
- 格式通常是 `jobs.lever.co/{company}` 或 `careers.lever.co/{company}`
- 例如：`https://jobs.lever.co/nvidia` → board_token = `nvidia`

### API 返回结构

```json
{
  "data": [
    {
      "id": "abc123",
      "text": "Software Engineer",
      "categories": {
        "department": "Engineering",
        "location": "San Francisco, CA",
        "commitment": "Full-Time",
        "team": "Platform"
      },
      "country": "US",
      "workplaceType": "remote",
      "createdAt": 1700000000000,
      "hostedUrl": "https://jobs.lever.co/nvidia/abc123",
      "applyUrl": "https://jobs.lever.co/nvidia/abc123/apply",
      "state": "published"
    }
  ]
}
```

### 优点
- ✅ 免费公开 API，不需要 API key
- ✅ 结构化 JSON，容易解析
- ✅ 包含 `department`, `team`, `location`, `workplaceType` 等字段
- ✅ 支持 ETag/If-None-Match 做增量更新（304 Not Modified）

### 缺点
- ⚠️ 没有 `requisition_id`，所以无法做 dedicated（跟 Ashby 一样用 job id 替代）
- ⚠️ 部分字段不如 Greenhouse/Ashby 丰富（比如没有 employmentType 标准化）
- ⚠️ 相比 Greenhouse/Ashby，用 Lever 的大公司较少

### 适配成本：低（1-2 天）

---

## 二、Workday

### 核心问题

Workday **没有公开的统一 API**。每家公司的 Workday 实例都是独立部署的，URL 各不相同：
```
https://jpmc.wd5.myworkdayjobs.com/en-US/...
https://bankofamerica.wd1.myworkdayjobs.com/en-US/...
https://shell.wd3.myworkdayjobs.com/en-US/...
```

### 三种接入方式

#### 方式 1: Workday REST API（需要企业合作）
- Workday 提供正式的 REST API（`/api/v1/...`）
- **需要 OAuth 2.0 认证** — 需要公司 IT 部门开通
- 适合内部集成，不适合公开数据采集
- ❌ 不可行（除非有合作关系）

#### 方式 2: 公开 Job Board XML Feed
- Workday 默认每个实例有一个公开的 XML feed：
  ```
  https://{company}.wd5.myworkdayjobs.com/{instance}/jobs/feed?format=xml
  ```
- XML feed 包含所有公开职位
- **不需要认证**
- 但每个实例的 URL 结构略有不同，需手动发现

##### XML Feed 局限性
- ⚠️ 不是所有 Workday 客户都启用这个 feed
- ⚠️ URL 格式不统一（有的用 `wd1`, `wd3`, `wd5` 等）
- ⚠️ XML 解析比 JSON 麻烦
- ⚠️ 没有增量更新支持（没有 ETag）
- ⚠️ 一些字段可能缺失（department, team）

#### 方式 3: HTML Scraping
- 每个 Workday 实例都有公开的职位搜索页面
- 返回的是 HTML，需要解析 DOM
- 有些实例支持 JSON API 通过特定的 URL 参数
  ```
  https://{company}.wd5.myworkdayjobs.com/en-US/{instance}/jobs?q=...
  ```
- 需要为每家公司定制解析逻辑
- ⚠️ 反爬风险较高
- ⚠️ 维护成本高（页面结构可能变化）

### Workday 适配成本：高

---

## 三、使用 Lever/Workday 的主要公司

### 金融业 (Financial Services)

| 公司 | ATS | 可接入？ |
|---|---|---|
| **JPMorgan Chase** | Workday (wd5) | ⚠️ XML feed 可用，需定制 |
| **Goldman Sachs** | Workday (wd5) | ⚠️ 同上 |
| **Morgan Stanley** | Workday (wd1) | ⚠️ 同上 |
| **Bank of America** | Workday (wd1) | ⚠️ 同上 |
| **Citigroup** | Workday | ⚠️ 同上 |
| **Wells Fargo** | Workday | ⚠️ 同上 |
| **HSBC** | Workday | ⚠️ 同上 |
| **BlackRock** | Workday | ⚠️ 同上 |
| **Blackstone** | Workday | ⚠️ 同上 |

### 保险 (Insurance)

| 公司 | ATS | 可接入？ |
|---|---|---|
| **Berkshire Hathaway** | 分散管理 | ❌ 无统一 ATS |
| **UnitedHealth** | Workday | ⚠️ 需定制 |
| **AIA Group (1299.HK)** | Workday? | 需确认 |
| **Ping An (2318.HK)** | 自家系统 | ❌ |
| **AXA** | Workday | ⚠️ 需定制 |
| **MetLife** | Workday | ⚠️ 需定制 |
| **Prudential** | Workday | ⚠️ 需定制 |
| **Aflac** | Workday | ⚠️ 需定制 |
| **Manulife (945.HK)** | Workday | ⚠️ 需定制 |

### 能源 (Energy)

| 公司 | ATS | 可接入？ |
|---|---|---|
| **ExxonMobil** | Workday | ⚠️ 需定制 |
| **Shell** | Workday (wd3) | ⚠️ 需定制 |
| **Chevron** | Taleo | ❌ HTML 解析 |
| **BP** | Workday | ⚠️ 需定制 |
| **TotalEnergies** | Workday | ⚠️ 需定制 |
| **ConocoPhillips** | Workday | ⚠️ 需定制 |

### 使用 Lever 的知名公司

| 公司 | 行业 | 可接入？ |
|---|---|---|
| **NVIDIA** | AI/Semi | ✅ Lever API |
| **Netflix** | Media/Streaming | ✅ Lever API |
| **Spotify** | Media | ✅ Lever API |
| **Uber** | Transportation | ✅ Lever API |
| **Shopify** | E-commerce | ✅ Lever API |
| **Square (Block)** | Fintech | ✅ Lever API |
| **Palantir** | Data Analytics | ✅ Lever API |
| **Walmart** | Retail | ✅ Lever API |
| **Klaviyo** | Marketing | ✅ Lever API |
| **HubSpot** | CRM/Marketing | ✅ Lever API |

> 注：Lever 用户以 tech 为主，金融/保险/能源很少用 Lever。

### 其他 ATS（目前未支持）

| ATS | 代表用户 | 接入难度 |
|---|---|---|
| **SmartRecruiters** | Slack (部分), Atlassian, 很多中大型企业 | 中 — 有公开 API |
| **iCIMS** | Verizon, CVS, 很多大型企业 | 高 — 需要合作 |
| **Taleo (Oracle)** | Chevron, 很多传统企业 | 高 — 无公开 API，需 HTML 爬取 |
| **SAP SuccessFactors** | 大型欧洲企业 | 高 — 需认证 |
| **JazzHR** | 很多中小企业 | 低 — 有简单 API |
| **Breezy HR** | 中小企业 | 低 — 有 API |
| **Bullhorn** | Staffing/Recruiting | 中 — 有 API |

---

## 四、建议路线

### 优先（低 hanging fruit）

1. **Lever** — 接入成本低，能覆盖 NVIDIA/Netflix/Uber/Spotify 等知名公司
2. **Lever API 发现** — 可以写一个自动检测脚本，检查某域名是否使用 Lever

### 试探性（中等成本）

3. **Workday XML Feed** — 选择 3-5 家重要公司（JP Morgan, Goldman Sachs, Shell, UnitedHealth, AIA），手动找出它们的 Workday 实例 URL，看看 XML feed 是否可用
4. 写一个通用的 Workday XML feed 解析器，然后按公司配置 URL

### 不推荐现在做

5. **Taleo/SuccessFactors** — 没有标准公开 API，投入产出比太低
6. **Workday HTML scraping** — 维护成本高，容易被反爬

### 关于信号价值的提醒

即使接入了 Workday/Lever，非 tech 行业的 hiring data 更新频率低、噪音大的问题仍然存在：
- 金融公司可能在奖金季后集中更新，然后几个月不变
- 保险/能源公司的岗位 turnover 低，信号变化缓慢
- 可能需要更长的观察窗口（月/季度级别）才有意义

---

## 五、接入 Lever 的快速方案

在 `config.py` 添加一个新函数：

```python
def _lever(company_id: str, name: str, token: str, segment: str) -> SourceSpec:
    return SourceSpec(
        source_id=f"lever_{company_id}",
        source_kind="job_board",
        source_url=f"https://api.lever.co/v0/postings/{token}?mode=json",
        company_id=company_id,
        company_name=name,
        company_segment=segment,
        source_platform="lever",
        board_token=token,
        careers_url=f"https://jobs.lever.co/{token}",
    )
```

然后在 `extract.py` 添加 `_lever_jobs()` 解析函数。

---

## 六、Workday 快速定位脚本思路

写一个 `scripts/find_workday_instances.py`：

1. 输入：公司招聘页 URL
2. 检测是否跳转到 wd1/wd3/wd5.myworkdayjobs.com
3. 尝试常见的 XML feed URL 模式
4. 输出 Workday 实例 ID 和可用 feed 地址

这样可以半自动化发现新公司的 Workday 接入配置。
