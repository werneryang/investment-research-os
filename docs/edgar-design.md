# SEC EDGAR 财报数据：设计说明（草案）

状态：E1 已实现（2026-10-24），并已接入网站的数据页、能力地图与资源目录；E2、E3 未开始。实现与本文的差异记在 §9。本文对应[架构](architecture.md) §6.1 的「财报与事件」对象，以及[研究框架地图](research-map.md) §3.4 的「公司财报」方向。实现改动公共契约（`contracts.py`、`registry.py`），按 [README 的开发流程](../README.md#开发流程)走 PR。

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

- 在 `.env` 中设置 `SEC_USER_AGENT`（如 `investment-research-os <邮箱>`），不入库、不写进日志；**未设置时只用 `data.sec.gov`**，FSDS 相关取得报错并说明原因。2026-10-24 已设置，`www.sec.gov` 上的 FSDS 文件随即可以访问（返回 200）。
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
| FSDS | 每月检查一次 | 对全部季度文件发 HEAD 请求（约 70 次，只取大小与 Last-Modified，不下载）；只下载新出现的季度，以及大小或修改时间变化的旧季度。下载后按内容校验值去重，内容未变不另存；内容变化时作为该季度分区的新版本保存，旧版本保留 |
| Company Facts API | 每个工作日（E1：约 15 家） | 只为验证公司取得；E2 起改为根据 Submissions 或每日索引，只取当天有新申报的公司 |
| `companyfacts.zip` | 不定期 | 只用于一次性补全，不参加定时快照 |

**FSDS 的实际更新规律**（2026-10-24 用 HEAD 请求核实各文件的 Last-Modified）：

- 每季度新增一个文件，在季度结束后约一周发布：2026Q3 为 2026-10-07，2025Q1 为 2025-04-10。
- 过去的季度文件通常不变，但会被整体替换：2009Q2、2012Q1、2018Q1 等历史文件的修改时间都是 2024-12-27，即那次重新处理。
- 2026Q2 的修改时间是 2026-08-19，比季度结束晚约七周；从文件头无法区分是首次发布较晚，还是发布后又被替换过。

因此首次完整下载（约 70 个文件，5–6 GB）之后，平时每季度只需下载一个新文件（约 60–130 MB），外加偶尔被替换的旧文件；当季度新申报在 FSDS 收录之前由 Company Facts API 补上。

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

1. ~~**联系邮箱**~~：已于 2026-10-24 在 `.env` 设置 `SEC_USER_AGENT`。
2. **原始 ZIP 是否完整保存**：完整保存约 5–6 GB；或只保存校验值与取得记录，需要时重新下载（但 SEC 可能已重新处理）。
3. **DuckDB 依赖**：是否接受新增这一依赖；替代方案是只用 pyarrow 读取分区。
4. **E1 核心指标**：营收、净利润、稀释每股收益、经营现金流、资本开支、总资产、股东权益、稀释加权平均股数，共 8 个（「流通股数」的替换见 §9）。

FSDS 各表的字段名（`sub`、`num`、`tag`、`pre`）以 SEC 的说明文件为准，首次取得时逐一核对后再定稿 §3。

## 9. E1 实现记录（2026-10-24）

- **字段核对**：用 2026Q3 的真实文件核对，`sub` 与 `num` 的字段与 §3 一致；`num` 每季度约 875 MB（解压后），逐行流式过滤，只保留登记公司的定期报告与合并口径数字（无分部、无共同申报人），一个季度约 9 秒。
- **排除的表格**：11-K（员工持股计划）等非定期报告的数字不是公司财报，解析时排除。
- **封面数据**：FSDS 不含 `dei` 封面数据（如 `EntityCommonStockSharesOutstanding`），流通股数主要来自 Company Facts API，资产负债表的 `CommonStockSharesOutstanding` 作为后备。
- **期间起点**：FSDS 只给期末与季度数，`period_start` 只有 Company Facts 提供；年度指标按 `duration_quarters = 4` 识别，API 的季度数由起止天数换算（52/53 周财年也落在 4）。
- **可用时间**：FSDS 用接受时间的次日 0 点（美东）；API 只有申报日期，用申报日期的次日 0 点。两处都有同一事实时取 FSDS。
- **HEAD 的局限**：只能发现大小或修改时间的变化；`iros edgar sync --refresh` 不论文件头都重新下载（内容相同时去重），用于偶尔的全面复核。
- **期末日取整**：FSDS 把期末日取整到最近的月末（苹果 FY2024 为 2024-09-30，实际为 2024-09-28），两个来源按取整后的期末对应同一期间，显示时用 API 的实际日期；未做这一步时，期末日不在月末的公司每年被算成两个财年。
- **核验结果**：FSDS 与 Company Facts 的 20920 个共同事实全部一致；营收与年报原文核对一致（苹果、微软、亚马逊、沃尔玛）；微软 FY2017 营收按 ASC 606 重述（89,950 → 96,571 百万美元），时点视图在重述前后分别给出两者；强生的 52/53 周财年显示实际期末日。
- **别名调整**：
  - 营收把 `Revenues`（US-GAAP 的总营收科目）放在第一位。沃尔玛同一份申报中两者都有，`RevenueFromContract…` 只是净销售额；埃克森美孚的 `Revenues` 是「总收入与其他收益」，各年一致。
  - 强生、可口可乐 2007–2017 年用 `SalesRevenueGoodsNet` 报告营收，已加入别名。
  - 稀释每股收益加入 `EarningsPerShareBasicAndDiluted`（基本与稀释相同时只报这一项）。
  - 原计划的「流通股数」改为**稀释加权平均股数**：封面上的流通股数是申报日前后的时点数，不是财年末，FSDS 也不含封面数据。
- **修订与口径切换**：首次公布值只在同一科目内比较；不同申报换了科目时数值差异来自口径，标为「用了几个不同科目」，不报告为重述。
- **仍有的缺口**（不猜测，记为缺失）：摩根大通没有资本开支科目（银行报表结构）；伯克希尔没有稀释每股收益与稀释股数（按 A 类股当量报告）；强生、宝洁只报告含少数股东权益的股东权益；英伟达 2013–2021 年的资本开支用公司自定义科目；埃克森美孚 2014 年后只报告基本加权股数；Alphabet 的股数按股份类别报告，2022 年前没有合并数；Alphabet 2015 年之前的数据在前身 Google（另一个 CIK）名下。
- **网站**（2026-10-24）：财报不在 `datasets.yaml` 中，网站另行生成两行 `edgar_fsds`、`edgar_companyfacts`（`site/collect.py` 的 `fundamentals_datasets`），id 与来源登记中的核验记录一致；行数、申报数与最近一次同步读自 `data/edgar/catalog/`。「公司财报」方向登记这两个数据集。线上网站由 CI 生成，CI 没有联系邮箱、不取得财报，所以线上显示「数据已登记」并写明「需要联系邮箱（SEC_USER_AGENT），只在本机取得」；本机预览显示「已有数据」。
- **代码**：`connectors/sec.py`（请求与解析）、`data/fundamentals.py`（分区存储、同步、年度指标与时点视图）、`config/fundamentals.yaml`、`iros edgar sync|annual|check`；本机定时任务在 `iros fetch --all` 之后运行 `iros edgar sync`。
