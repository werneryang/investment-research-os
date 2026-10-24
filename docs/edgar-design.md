# SEC EDGAR 财报数据：设计说明（草案）

状态：待审阅，尚未实现。本文对应[架构](architecture.md) §6.1 的「财报与事件」对象，以及[研究框架地图](research-map.md) §3.4 的「公司财报」方向。实现改动公共契约（`contracts.py`、`registry.py`），按 [README 的开发流程](../README.md#开发流程)走 PR。

## 1. 目标与分期

**目标**：支持所有以 XBRL 申报财务报表的 SEC 申报主体，覆盖 2009 年起的年度与季度财报数字，可以按公司、指标、财年和行业筛选，并能回答「某一天之前已经公布了什么」。

**分期**：

| 阶段 | 范围 | 完成条件 |
|---|---|---|
| E1 | 完整管道，只对 §7 的约 15 家验证公司运行；年度数据（10-K、10-K/A） | 财年、指标别名、申报版本、分区存储与时点视图全部贯通；营收与净利润与年报原文逐一核对 |
| E2 | 全部申报主体的年度数据；按 SIC 行业汇总 | 季度数据集全量导入；行业汇总与 French 行业收益的口径差异写明 |
| E3 | 季度数据（10-Q）与推算的第四季度 | 年初至今累计数与单季数区分；第四季度 = 全年 − 前三季，并标为推算 |

架构不限制公司数量；E1 只是用少数公司把管道走通，换成全量时不改底层设计。

## 2. 来源与分工

| 来源 | 地址 | 用途 | 更新 |
|---|---|---|---|
| Financial Statement Data Sets（FSDS） | `www.sec.gov` 季度 ZIP | **历史主来源**：报表主体数字、SIC、申报与接受时间；「按申报原样」 | 每季度一个文件，约 60–120 MB；2024 年 12 月曾整体重新处理 |
| Company Facts API | `data.sec.gov/api/xbrl/companyfacts/` | 当季新申报（FSDS 尚未收录）；与 FSDS 交叉核对 | 实时，通常一分钟内 |
| Submissions API | `data.sec.gov/submissions/` | 公司名称、代码、财年结束日、SIC；申报清单 | 实时 |
| `companyfacts.zip` | `www.sec.gov` 夜间重建 | 只在需要一次性补全时使用，不做每日快照 | 每晚约 3:00 ET 重建 |

**访问条件**（已核实，2026-10-24）：`data.sec.gov` 接受当前的请求标识；`www.sec.gov` 上的文件（FSDS、批量 ZIP、代码对照表）一律返回 403。SEC 的公平访问规则要求自动程序在 User-Agent 中写明联系邮箱，每秒不超过 10 次请求。本项目将：

- 在 `.env` 中设置 `SEC_USER_AGENT`（如 `investment-research-os <邮箱>`），不入库、不写进日志；**未设置时只用 `data.sec.gov`**，FSDS 相关取得报错并说明原因。
- 串行请求，间隔不少于 0.2 秒（每秒最多 5 次）。

## 3. 数据对象与契约

财报数字不放进现有的 `series.v1`：一个期间会在多份申报中以不同数值出现，期间有起止日期且长度不一（单季、年初至今、全年、时点余额），财年也不对齐日历年。按架构 §6.1，财报是单独的对象。

### 3.1 申报（filing）

每份申报一行，来自 FSDS 的 `sub` 表或 Submissions API。

| 字段 | 含义 |
|---|---|
| `accession` | 申报编号（FSDS 的 `adsh`），唯一标识一份申报 |
| `cik` | 申报主体编号 |
| `form` | 表格类型：10-K、10-K/A、10-Q、10-Q/A、20-F 等 |
| `fiscal_year`、`fiscal_period` | 申报主体自报的财年与期间（FY、Q1–Q3） |
| `period_end` | 报告期末（资产负债表日） |
| `filed` | 申报日期 |
| `accepted_at` | EDGAR 接受时间（精确到秒，美东时间）；作为发布时间 |
| `amends` | 是否为修正申报（/A），以及后来是否被修正（FSDS 的 `prevrpt`） |
| `sic` | 申报时的行业分类 |

### 3.2 财报事实（fact）

每个「申报 × 科目 × 期间 × 单位」一行，结构版本 `fundamentals.v1`。

| 字段 | 含义 |
|---|---|
| `accession` | 来自哪份申报 |
| `cik` | 申报主体 |
| `taxonomy`、`tag` | XBRL 分类与科目（如 `us-gaap` / `NetIncomeLoss`） |
| `period_start`、`period_end` | 期间起止；时点余额只有 `period_end` |
| `duration_quarters` | 期间长度（FSDS 的 `qtrs`）：0 为时点，1 为单季，4 为全年 |
| `unit` | 单位（USD、shares、USD/shares） |
| `value` | 申报值 |
| `segments` | 分部或维度；E1 只用合并口径（空） |
| `available_at` | = `accepted_at` 的次日 0 点（美东），保守规则 |
| `retrieved_at`、`source` | 取得时间与来源（fsds / companyfacts） |
| `quality_status`、`reason` | 与现有质量规则一致 |

同一期间在后续申报中作为对比数据再次出现，或被修正申报改动，都形成新的行，旧行不改写。这与 ALFRED 的历史版本同一逻辑：**申报编号就是供应方版本，`accepted_at` 就是发布时间**。

### 3.3 指标与别名

研究用的是「指标」，不是 XBRL 科目。同一指标会换科目名，例如苹果的营收：2018 年以前为 `SalesRevenueNet`，之后为 `RevenueFromContractWithCustomerExcludingAssessedTax`（会计准则 ASC 606 改变）。新增登记文件 `config/fundamentals.yaml`：

```yaml
metrics:
  revenue:
    period: duration            # duration 或 instant
    unit: USD
    tags:                       # 按顺序取第一个出现的科目，记录实际使用了哪个
      - us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax
      - us-gaap:Revenues
      - us-gaap:SalesRevenueNet
  net_income:  {period: duration, unit: USD,  tags: [us-gaap:NetIncomeLoss]}
  eps_diluted: {period: duration, unit: USD/shares, tags: [us-gaap:EarningsPerShareDiluted]}
  # 经营现金流、总资产、股东权益、资本开支、流通股数 …
companies:                      # E1 的验证公司；E2 起改为全部申报主体
  - {cik: 320193, label: Apple}
```

银行与保险的营收科目不同（如利息收入），别名表按需要分行业补充；找不到任何别名时记为缺失，不猜测。

### 3.4 财年

不把财年硬套进日历年：期间以 `period_start`、`period_end` 表达，财年标签保留申报主体自报的 `fiscal_year`。年度数据只取约一年长的期间（`duration_quarters = 4`，或起止日相差 350–380 天，以容纳 52/53 周财年）。需要按日历年比较时，另外派生「所属日历年」字段，并写明规则（如按期末日所在年份）。

### 3.5 时点视图

「在时点 t 已知的某公司某指标」= 在所有 `available_at ≤ t` 的行中，对每个期间取最新申报的值。这复用现有 `as_of` 的思路（供应方版本以 `available_at` 为证据），但按 `(cik, metric, period_end, duration)` 分组。

## 4. 存储

现有存储每次变化都写一份完整的原始文件和一份完整的版本，适合几 MB 的序列；全市场财报（FSDS 全部历史约 5–6 GB 压缩包）不能这样做。

| 层 | 布局 | 说明 |
|---|---|---|
| 原始 | `data/edgar/raw/fsds/<YYYYqN>_<sha8>.zip`；`data/edgar/raw/companyfacts/<cik>/<时间>_<sha8>.json` | 原样保存；内容相同不另存（沿用现有去重） |
| 标准化 | `data/edgar/facts/source=fsds/quarter=<YYYYqN>/part.parquet`；`.../source=companyfacts/cik=<cik>/…` | **按季度或公司分区**；一个分区变化只重写该分区，并保留旧分区版本 |
| 目录 | `data/catalog/edgar_partitions.jsonl` | 每个分区的版本、校验值、来源文件与取得时间 |
| 查询 | DuckDB 直接读 Parquet 分区 | 新增依赖（免费）；架构原定「需要跨数据集查询时再加」 |

E1 只导入验证公司的行，FSDS 原始 ZIP 仍完整保存（约 5–6 GB，本机现有约 44 GB 可用空间）。是否完整保存原始 ZIP 是 §8 的待定事项。

## 5. 更新与快照

| 来源 | 频率 | 方式 |
|---|---|---|
| FSDS | 每月检查一次 | 新季度文件出现时取得；已有季度文件的校验值变化（如 2024-12 的整体重新处理）时，作为该季度分区的新版本保存，旧版本保留 |
| Company Facts API | 每个工作日（E1：约 15 家） | 只为验证公司取得；E2 起改为根据 Submissions 或每日索引，只取当天有新申报的公司 |
| `companyfacts.zip` | 不定期 | 只用于一次性补全，不参加定时快照 |

即使有申报编号与接受时间，仍保存原始快照：SEC 会重新处理历史文件，重新下载的聚合数据不保证与过去一致。

## 6. 核验

| 检查 | 方法 |
|---|---|
| 数值 | 验证公司的营收与净利润，与年报原文逐年核对（例：苹果 FY2024 营收 391,035 百万美元） |
| 来源一致 | 同一申报的同一事实，FSDS 与 Company Facts API 逐值比较 |
| 别名覆盖 | 每家公司每年都能取到核心指标；取不到的列出，不静默跳过 |
| 修正申报 | 特斯拉近期有 5 份 10-K/A：确认修正后的值在时点视图中只从其接受时间起生效 |
| 财年 | 52/53 周财年（强生）与非 12 月财年（苹果、微软、英伟达、沃尔玛、耐克、好市多）的期间长度与归属正确 |
| 时间 | `available_at` 不早于 `accepted_at`；时点视图中不出现未来申报 |

## 7. E1 验证公司（CIK 已于 2026-10-24 用 Submissions API 核实）

| 公司 | CIK | 财年结束 | 选择理由 |
|---|---|---|---|
| Apple | 320193 | 9 月最后一个周六前后 | 营收科目更名；52/53 周 |
| Microsoft | 789019 | 6/30 | 6 月财年 |
| NVIDIA | 1045810 | 1 月末 | 1 月财年 |
| Amazon | 1018724 | 12/31 | 日历年 |
| Alphabet | 1652044 | 12/31 | 两类股票 |
| Tesla | 1318605 | 12/31 | 有多份 10-K/A |
| JPMorgan Chase | 19617 | 12/31 | 银行报表结构 |
| Berkshire Hathaway | 1067983 | 12/31 | 保险与综合企业 |
| Exxon Mobil | 34088 | 12/31 | 能源 |
| Johnson & Johnson | 200406 | 最接近 12/31 的周日（SEC 记为 01-03） | 52/53 周财年 |
| Procter & Gamble | 80424 | 6/30 | 6 月财年 |
| Coca-Cola | 21344 | 12/31 | 必需消费 |
| Walmart | 104169 | 1/31 | 1 月财年、零售 |
| Costco | 909832 | 8 月末 | 52/53 周、零售 |
| Nike | 320187 | 5/31 | 5 月财年 |

## 8. 代码影响与待定事项

**新增**：`connectors/sec_fsds.py`、`connectors/sec_companyfacts.py`、`data/fundamentals.py`（分区存储、时点视图）、`config/fundamentals.yaml`；`contracts.py` 增加 `FUNDAMENTAL_COLUMNS`、申报与事实的结构；`registry.py` 读取指标与公司登记；网站的数据页与资源目录显示财报数据集。

**待定**（实现前需要确认）：

1. **联系邮箱**：`SEC_USER_AGENT` 用哪个地址。没有它，FSDS 与批量文件都无法取得。
2. **原始 ZIP 是否完整保存**：完整保存约 5–6 GB；或只保存校验值与取得记录，需要时重新下载（但 SEC 可能已重新处理）。
3. **DuckDB 依赖**：是否接受新增这一依赖；替代方案是只用 pyarrow 读取分区。
4. **E1 核心指标**：建议营收、净利润、稀释每股收益、经营现金流、资本开支、总资产、股东权益、流通股数，共 8 个。

FSDS 各表的字段名（`sub`、`num`、`tag`、`pre`）以 SEC 的说明文件为准，首次取得时逐一核对后再定稿 §3。
