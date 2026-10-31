# 实现说明（P1/P2）

**对应设计：** [架构 V0.3](architecture.md) §3、§5–§10

**更新日期：** 2026-10-22（含审查修复，见 §8）

本文说明架构契约在代码中的落地方式，以及新增来源、数据集和研究分支的方法。架构上的取舍以 V0.3 为准。

## 1. 模块与代码对应

| 架构模块 | 代码 | 职责 |
|---|---|---|
| Q 研究定义 | `registry.py`、`config/studies/*.yaml` | 读取并校验来源、数据集与研究定义 |
| D 资源接入 | `connectors/` | 只负责取得原始字节、解析为暂存表；不做数值判断 |
| S 数据与资料 | `data/store.py`、`data/ingest.py`、`data/timing.py` | 原始快照、标准化、版本与血缘、时间契约、时点视图 |
| A 公共分析 | `analytics/` | 利率曲线、收益、风险；不依赖来源或研究分支 |
| M 研究分支 | `research/` | 通过 `register_branch` 注册；当前只有 `rates_curve` |
| O 成果与档案 | `reporting/`、`runs.py` | Markdown/HTML 报告与图表，运行清单 |
| V 质量与验证 | `quality/`、`validation/`、`runs.verify_run` | 行级质量、交叉核验、原始快照抽查、复现 |
| 公共契约 | `contracts.py`、`tenor.py` | 枚举、序列结构、可用时间规则、版本对象 |

跨模块只交换 `contracts.py` 中的对象（`DatasetSpec`、`DatasetVersion`、标准化序列表、`ResearchResult`），不读取其他模块的临时文件。

## 2. 数据流

```text
iros fetch
  connector.fetch      → RawPayload（原始字节）
  store.save_raw       → data/raw/<dataset>/<时间>_<sha8>.csv + .meta.json
  connector.parse      → 暂存表（原始值保持字符串）
  normalize            → 数值化、缺失/隔离判定、published_at、available_at、vintage_id
  resolve_duplicates   → 完全重复去除，同键冲突隔离
  _merge               → 与上一版本合并：同一观测以新取得为准；供应方历史版本并存
  content_hash 未变化  → 不建新版本，只记取得日志
  store.save_version   → data/normalized/<dataset>/<version>.parquet + catalog/<dataset>.jsonl

iros run
  load_inputs          → 按研究定义加载最新或固定版本；as_of 策略下取时点视图
  research branch      → ResearchResult（结果、覆盖、不支持的结论、限制、验证）
  spot_check           → 用标准库 csv 独立读取原始快照，逐点比对
  write_report         → reports/<study>/<run>/report.{md,html} + figures/
  manifest             → runs/<run>/manifest.json（开始时即写入，失败也保留）

iros verify <run_id>   → 用清单中的研究定义与数据版本重算，比较结果校验值；
                         另比较 src/、config/ 的内容校验值判断代码是否变化（文档、测试改动不算）
```

`verify` 在重算前先检查保存产物：清单中每个输出文件的 SHA-256，以及磁盘 `result.json` 的内容校验值都必须匹配。文件缺失或被改动时拒绝复现；部分复现同样要求原产物完整。网站每次构建也重新检查，失败即停止构建并保留上一版网站，不能沿用旧的复现通过记录发布改动后的结果。研究页分别列出「保存产物完整性」与「固定输入重算」。

## 3. 契约的落地方式

**标准化序列表**（`series.v1`，见 `contracts.SERIES_COLUMNS`）：每行一个观测，含 `observation_at`、`value`、单位、频率、币种，以及 `published_at`、`available_at`、`retrieved_at`、`vintage_id`、`source_id`、`upstream_id`、`quality_status`、`reason`。数据集级的 `schema_version`、`content_hash`、原始快照引用和质量报告记录在版本目录里。

**可用时间规则**在 `config/datasets.yaml` 中逐个数据集声明：

| 规则 | 含义 | 当前使用 |
|---|---|---|
| `next_day` | 观测日次日 0 点（来源时区） | Treasury 曲线、DGS10 |
| `period_end_lag_days` | 期末后第 N 天结束时 | CPIAUCSL（45 天，保守近似） |
| `published_next_day` | 供应方发布日次日 0 点 | ALFRED 历史版本 |
| `unknown` | 留空；时点视图排除 | 人工导入示例 |

**时点资格**：可用时间规则只表达假定的发布延迟，不能证明某个修订值当时已经公布。每个数据集用 `vintages` 声明历史版本能力：

| `vintages` | 能进入时点视图的行 | 版本选择 |
|---|---|---|
| `supplier`（ALFRED） | 有供应方发布日期的历史版本，且 `available_at ≤ t` | 最新版本（含全部历史版本） |
| `none`（Treasury、FRED 图表 CSV、人工导入） | 还需 `retrieved_at ≤ t`，即本系统当时确已取得 | `t` 时本系统已有的最新版本；没有则拒绝运行 |

`data.as_of(df, t, vintages)` 按上表筛选，并为每个观测取当时最新的版本；`eligibility_as_of` 给出逐行排除原因（可用时间未知、当时尚未可用、无证据表明当时已知），运行清单会列出各类排除数。发布与可用时间都只精确到日，版本质量报告记录 `time_precision: day`。

**用途核验**：核验记录按「来源 × 数据集 × 用途」查询。说明与接入核验对数据集整体有效；`use_verified` 必须声明 `use`（`descriptive` 或 `point_in_time`），只在查询同一用途时计入。研究的用途由版本策略决定（`as_of` 为时点研究），运行清单记录该用途下的状态。

用途核验记录可以用 `valid_from`/`valid_through` 声明覆盖的观测日期（含两端，可省略一端）。`SourceSpec.use_coverage(dataset, use, start, end)` 比较研究期间与这些范围（多条记录取并集），返回在范围内、部分在范围内（列出范围外的日期区间）、范围外或未核验。运行时，用途已验证的输入在清单与结果中记录 `use_scope`；复现按原运行记录的位置固定，之后修改核验记录不影响旧运行的复现；旧运行没有该字段时保持原样。能力地图按当前登记与各研究最新运行的期间重新计算，研究页证据面板与首页证据摘要显示运行时记录的位置。

目前唯一的用途核验：`ust_par_yield_curve` 的描述性用途（2026-10-23 登记），观测日期 2024-01-01 至 2026-10-22（预期日历核验范围），名义票面曲线的期间描述，证据引用基线运行与独立审查的重算；时点研究、回报、预测与交易回测不在范围内。滚动研究的窗口每天向后延伸，超出部分显示为「部分在范围内」；扩展日历核验后，追加一条覆盖新日期的用途核验记录即可。

**预期观测日历**：`config/calendars.yaml` 登记经核验的发布日集合。`us_treasury_daily` 为工作日减联邦假日，再减逐年核验的额外休市日（2024-03-29、2025-04-18 两个耶稣受难日；2026 年耶稣受难日照常发布，所以不能作为固定规则），与 Treasury 2024 年至 2026-10-22 的日期集合逐日一致。研究期间超出 `verified_from`/`verified_through` 时，限制中会注明该段日期按规则推定。研究的日期覆盖对照预期日历计算，期限覆盖的分母同样是预期观测日；没有日历的数据集无法证明期间完整。

**版本号**：供应方有历史版本时（ALFRED）用 `alfred:<realtime_start>`；否则为本地快照 `local:<取得时间>`。内容校验值不包含取得时间和本地快照编号，因此重复下载相同内容不会产生新版本。

**质量状态**：`ok`、`missing`（来源未给值，如假日或 `.`）、`quarantined`（无法解析、超出登记范围、同键冲突）。下游只用 `quality.ok_rows` 返回的行；不填零，不前值填补，不插值。

**研究成果**（`research.base.ResearchResult`）包含 §6.3 的公共字段：研究 ID、类型、范围、数据截止、方法、输入版本、结果、覆盖、不支持的结论、限制和验证。运行状态取 `success`、`partial`（有结论被限制或某项验证未通过）、`failed`。

## 4. 失败行为（对应 §7.2）

| 情况 | 实现 |
|---|---|
| 取得失败或限流 | 有界重试（默认 3 次，指数退避）；每次尝试先写 `started`，任何阶段（取得、快照、解析、标准化、合并、保存）失败都写 `failed` 终态与阶段，保留旧版本，不产生新的更新时间 |
| 返回内容不对（如维护页面、序列名不符） | 解析失败，原始快照仍保存供诊断 |
| 部分缺失 | 标为 `missing` 并报告缺口；低于研究的 `min_coverage` 时，依赖它的指标列入「不支持的结论」，其他结论照常输出 |
| 研究期间未能证明完整覆盖 | 对照预期日历判断；运行为 `partial`，保留首尾有效观测的对比，均值、极值、倒挂天数等期间统计不输出，并在限制中写明缺口 |
| 可选输入不可用 | 跳过相应验证并在运行清单中记录为未使用；`verify` 按原样保持未使用。必需输入缺失则运行失败，仍留下清单 |
| 版本文件被改动 | 加载时比对内容校验值，不一致即拒绝 |
| 缺少 FRED_API_KEY | ALFRED 接入器拒绝运行并提示降级路径 |
| 凭证 | key 只用于请求；快照、日志与错误消息只用不含 key 的地址，所有错误文本再经 `redact` 清洗 |
| ALFRED 分页 | 按 offset 逐页取得，总数须与 `count` 一致；截断或空页即失败，不称为全部历史版本 |
| 同一秒内多次运行 | 运行 ID 带随机后缀，运行目录排他创建，已有记录不会被覆盖 |

## 5. 首个贯通案例

`config/studies/ust_curve_2024.yaml`：2024 年美国国债名义票面收益率曲线的水平、利差（2Y–10Y、3M–10Y）与蝶式曲率（2Y/5Y/10Y）。

**当前基线运行** `ust_curve_2024-20261023T143816Z-ddeb75ae`（2026-10-23，代码 `30eeb1c`，`dirty=false`，代码内容校验值 `1b9b72bfbfe8…`）：完整性判断修正后的第一条基线。输入 `ust_par_yield_curve` 版本 `v20261022T232039Z-4a3743d9`（用途核验在范围内）、`fred_dgs10` 版本 `v20261022T232039Z-da34e249`；预期观测日 250 天，应已发布 250 天，缺失 0 天，`completeness=complete`；10Y 3.95% → 4.58%，2Y–10Y 倒挂 166 天、零利差 3 天；`iros verify` 重算结果校验值 `024e1412…` 一致。

**上一条基线**（保留为历史记录）。修正完整性判断后，结果结构新增了覆盖字段，用新代码复现它会得到不同的校验值并标为「代码已变化」，这是预期行为；它的数值结论与当前基线相同。

**原基线运行** `ust_curve_2024-20261022T225910Z-1121d74b`（2026-10-22，代码 `5c922ef`，`dirty=false`；运行清单记录的是改写提交作者前的哈希 `f66ecca`，两者文件树完全相同）：

- 输入：`ust_par_yield_curve` 版本 `v20261022T221848Z-38e40907`、`fred_dgs10` 版本 `v20261022T221852Z-1f714854`；运行前重新下载，内容与上述版本相同，未产生新版本。
- 覆盖：预期观测日 250 天（日历 `us_treasury_daily`），实际 250 天，期间完整；关键期限覆盖 100%。
- 结果：10Y 3.95% → 4.58%（+63bp，以首个有效观测 2024-01-02 为基准）；2Y–10Y 倒挂 166 天，零利差 3 天不计入。
- 验证：与 FRED DGS10 的 250 个共同日期一致（同源，只说明接入与解析正确，不是独立验证）；12 个原始快照抽查一致；`iros verify` 重算结果校验值 `9937d7eb…` 一致，代码未变化；6 个输出文件校验值一致。

验证到此为止：计算正确、来源可追溯、固定输入可复现。这不代表该来源在其他期间或其他用途上已经验证，也不包含任何预测或交易含义。

## 6. 项目网站与运行档案

`iros site --out _site [--archive <dir>]` 汇总登记、数据目录、运行记录与复现记录，生成研究门户（`src/investment_os/site/`），只读取记录、不重新计算：

输出目录只接受新目录、空目录或带 `.iros-site.json` 标记的本工具输出；标记记录生成的文件与目录，发现额外文件、符号链接或与源文件、数据、报告、档案目录重叠时拒绝清理。旧的未标记输出需先移走或换新目录。生成和完整性检查先在临时目录完成，成功后才替换原输出。

- `index.html` 研究总览：顶部「研究焦点」由 `site/content.yaml` 的 `featured` 显式指定（最多 4 项，检查失败的研究不显示），与目录顺序分开。随后是六个研究分支的总览（研究问题与具体覆盖，规划中的分支链接到能力地图）和每项研究的形成过程，再按研究框架 `branches` 的顺序列出研究目录（见[研究框架地图](research-map.md)）。选什么、归在哪里、提示什么由 `site/catalog.py` 决定（含主方向、集合与各方向的条目），`home.py` 把它排成页面：一项研究可属于多个方向，但只在主方向（默认框架顺序中第一个列出它的方向，可用 `studies.<id>.primary_direction` 指定）列出完整条目，其他方向给出「另见」；`collections` 把同一主方向下的同类研究（如 15 家公司年度财报）收成一个入口，可展开逐项表格，入口汇总成员的检查失败与覆盖或数据限制，表格逐行列出；尚无研究的方向每个分支合并为一行，「已有数据」与「数据已登记、本次构建未取得」分开表述。每项研究显示一句主要发现（没有规则化发现时，用研究组件由已有结果字段格式化的摘要，再退到研究问题）、数据截止、检查状态与证据提示。检查状态只陈述已执行的检查通过几项，并写明部分执行与未执行的检查，不把没有记录说成通过。证据提示分三级：已执行检查失败（红）；用途核验缺口在研究期间前段或中段、研究期间在核验范围外、只缺尾端但核验最晚日期到数据截止日的滞后超过维护周期（按数据集频率，日度与周度 31 天、月度 62 天、季度 123 天、年度 366 天；频率不明也算），以及因数据或输入不足未输出的结论（黄，列出结论）；维护周期内的尾端滞后与研究设计不回答的问题（灰色说明）；数据截止日之后的期间不提示。未输出的结论由研究组件在结果中标 `kind`：`data` 为数据或输入不足，`scope` 为研究设计不回答、方法或情景不适用；没有 `kind` 的旧结果只说「未输出，原因见研究页」，复现旧运行时也不补写 `kind`。首页按运行时冻结的核验范围判断，能力地图按当前登记判断。指标卡片、图表、完整发现与证据只在研究页。没有归入任何方向的研究单独列出，提示补登记。
- `studies/<study_id>/` 研究页（统一模板）：研究问题 → 关键发现 → 可视化证据（图表面板、数据覆盖条）→ 方法 → 证据与限制（证据面板）→ 历史与复现（发现变化记录、历次运行）。
- **图表面板采用渐进增强**：研究页的静态图（与完整报告相同）默认可见；`site/assets/charts.js` 只在 Chart.js 已加载、`chart.json` 取得、图表生成都成功后才显示交互图表并收起静态图（可再展开）。任何一步失败，静态图保持可见，并按实际情况说明原因与有没有静态图；禁用脚本时也只显示静态图。Chart.js 4.4.1 随站点托管在 `site/assets/vendor/`（来源、许可与 SHA-512 见其中 README，测试会校验），不依赖外部 CDN。样式与脚本地址带内容校验值（`?v=`），改动后访客不会用到缓存的旧文件。
- **关键发现**（`research/findings.py`）：按研究分支的固定规则从结果生成句子，每条附所依据的指标路径与数值；变化小于 5 bp 记为「基本持平」；有缺口的指标只描述已观测日期。只描述，不作预测或交易判断。**解释在运行时固定**：发现、定性状态、规则版本（`RULE_VERSIONS`）、规则指纹（规则代码的校验值，规则改动后自动变化）与阈值参数写入结果的 `interpretation`，纳入结果校验值与 `verify`；网站显示运行当时记录的发现，规则已变化时注明但不改写。没有记录解释的旧运行，网站用当前规则事后生成并标明，`verify` 也不为它们补写。**发现变化记录**比较相邻两次运行的定性状态（利差期末是否倒挂、变陡或变平、覆盖），并列出两次运行之间可以客观比较的差异：研究窗口、各输入的数据版本、代码或登记配置（`source_hash`）、解释规则；不推断变化的原因。`source_hash` 不含 `config/studies/`：研究定义完整记录在每次运行的清单中。
- **覆盖与完整性**（`research/rates_curve.py`）分开判断：`coverage_acceptable`（应已发布日期的覆盖是否达到 `min_coverage`）决定期间统计能否输出；`completeness` 为 `complete`（全部预期日期有数据且日历已核验）、`complete_to_date`（应已发布的日期都有数据，另有日期尚未到发布时间）、`gaps`（有应已发布但缺失的日期）、`unverified_calendar`（相关日期超出日历核验范围，无法证明没有缺失）、`insufficient` 或 `no_calendar`；`period_complete` 只在 `complete` 时为真。数据下载时尚未到保守可用时点（数据集的 `availability` 规则）的日期记为「未取得」，不计入分母；判断以数据的下载时间为准——数据版本的 `retrieved_at` 与运行时写入 `scope.data_checked_at` 的最近一次成功下载（含内容未变、未产生新版本的下载）中较晚者——而不是评估时间，复现使用同一时间。保守可用时点不是实际发布时间，「未取得」不代表已确认尚未发布；比规则更早出现的数据按已观测计入。每个指标在 `coverage.metrics` 中记录自己的覆盖（利差与曲率要求所需期限同一天都有值）；有缺口的指标，期间统计标为 `sample: observed`，发现与报告只描述已观测日期。
- **证据面板**逐项列出研究用途、各输入的来源与版本、日期与期限覆盖、原始快照抽查、同源一致性检查、固定输入重算、代码版本与不支持的结论，不汇总成分数。**数据覆盖条**按预期观测日显示曲线与各关键期限是否有合格值；结果中的 `coverage.missing_dates` 提供完整缺失列表（只在有缺失时写入）。
- **展示组件按研究分支注册**（`site/renderers.py`）：研究页只负责共同结构（六个章节、证据面板的共同行、发现与解释、历史与复现）；每个分支提供自己的指标卡片、方法说明、覆盖或假设部分、证据行、历史列、交互图表数据（`chart.json`，`kind` 决定图表类型）、静态图与用途说明。没有注册展示组件的分支显示「暂无展示组件」，不套用其他分支的说明。
- `map.html` 研究能力地图：按 `branches` 逐个分支列出研究方向；每个方向的数据能力、分析能力（工程）与研究验证（用途核验）由登记、研究分支声明的成果类型与最新运行自动得出，只有 `planned: true` 的方向人工维护并写明缺什么。分支状态取其方向中最好的一项（已有研究 → 已有数据 → 数据已登记 → 规划中）。
- `sources.html` 数据资源目录（`site/sources.py`）：`config/sources.yaml` 中全部来源（已接入与候选）的卡片，按类别分组，另有按研究方向的索引与能力缺口。卡片显示来源达到的最高核验状态，逐个列出已登记数据集的状态与已验证用途；候选来源的取得方式等字段标为初步判断。研究方向链接到能力地图的分支。目录同时写入 `summary.json` 的 `sources`。
- `methods.html` 数据、方法与状态：来源与核验、预期日历、可靠性机制、复现方法与系统状态（`#status`）。
- **中英文切换**（`site/i18n.py`）：页面顶端右侧可切换语言。中文页面在根目录，英文页面是同一套模板在 `en/` 下的镜像（首页、能力地图、数据资源目录、方法页与研究页），两种语言共用 `assets/`、`runs/` 与 `latest/`；完整报告 `report.html` 与静态图只有中文。模板中的固定文字写成 `L("中文", "English")`；登记、研究定义与运行记录中的文字不改动原记录，译文在 `site/en.yaml`：`phrases` 逐句对照，`patterns` 处理运行时带日期与数字生成的句子。关键发现以中文记录、不改写，英文页面由 `site/findings_en.py` 按同一规则的英文措辞从同一份结构化结果生成，按发现 id 对应。没有译文的文字在英文页面保留原文并标为 `lang="zh-CN"`，`iros site` 列出它们，`summary.json` 的 `untranslated` 也记录。修改 `site/content.yaml` 时同步补译文（有测试检查）。读者在中文页面选过英文后，下次打开中文地址会转到对应的英文页面（`localStorage`，`?lang=zh` 可强制中文）。
- 页脚显示发布时间、代码版本与工作流徽章；更新停滞超过 2 个工作日时各页顶部显示提示。
- 每次运行的 `report.html`、图表、`daily.json`、`manifest.json`、`result.json` 发布在 `runs/<run_id>/`；`latest/<study_id>/report.html` 为最新完整报告的稳定地址；旧的 `history/<study_id>.html` 转到研究页的历史部分。
- 利差显示名写明减法方向（`10Y − 2Y`）；结果文件中的键（`2Y-10Y`）保持不变。

**本机定时快照**：Treasury 与 FRED 只提供当前修订版本，时点研究只能依靠当时已取得的快照，而 CI 取得的数据随运行环境丢弃。因此快照在本机积累：`scripts/snapshot-agent.sh install` 安装 launchd 任务（`com.investment-research-os.snapshots`），每个工作日 19:45（本机时间）运行 `iros fetch --all`，取得 `config/datasets.yaml` 中登记了 `scheduled_fetch` 的数据集，存入本地 `data/`。内容未变时只记录取得、不建新版本，取得记录本身证明「当时已知道什么」。原始文件也按内容去重（2026-10-23 起）：同一数据集已有完全相同的原始字节时不另存，取得记录引用已有文件（`reused: true`），并保留本次取得的时间与请求；此前已存的重复文件保持原样，因为版本目录与取得记录引用了它们的路径。电脑睡眠时错过的运行在唤醒后补跑；关机时错过的运行不补，那些日期的快照永久缺失。日志在 `~/Library/Logs/investment-research-os/snapshots.log`；`status`、`run`、`uninstall` 用于查看、立即运行与移除。`data/` 不入库。**每日备份**（2026-10-25 起）：定时任务最后运行 `scripts/backup-data.sh`，把 `data/` 中补不回来的部分（快照、取得记录、标准化版本、SEC 财报分区与目录）复制到 `.env` 中 `IROS_BACKUP_DIR` 指定的文件夹，目前是 Google Drive 桌面版同步的文件夹，由它上传到云端。SEC 季度数据集原始 ZIP（约 5 GB）可重新下载，不备份。只增加和更新、不删除目标中的文件；目标不可用时跳过并写入日志，不影响当天取得。

**运行档案**（`iros archive save|restore <dir>`）：CI 把运行记录与报告保存到 `archive` 分支的工作树，只追加、不覆盖。每项研究只在实质内容（结果、覆盖、限制、核验结论，以及运行时记录的解释；不含运行 ID、输入版本号、评估与下载时间）变化时归档新运行，比较对象是上一次归档运行的结果按当前算法重新计算的校验值；只有解释变化时原因记为「解释变化（结果不变）」；结论相同的运行在 `archive.jsonl` 中记为 skipped，以后不再考虑。数据只归档 `archive_data: true` 的数据集中被已归档运行使用的版本（目前只有 Treasury 曲线，2026-10-22 经用户确认）。

复现档案中的运行：`iros archive restore <dir> --with-data` 恢复记录与数据（目录按创建时间重排），再 `iros verify <run_id>`。固定版本不在本地的**可选**输入（FRED 交叉核验）不重算，比较去掉该输入及其核验项后的结果，记为部分复现；必需输入缺失则报错。

`.github/workflows/pages.yml`：测试 → 取得 → 运行 → `verify --all` → 归档并恢复历史 → 生成网站 → 推送档案 → 发布。CI 每次从零开始，展示的是当次运行，不是本地基线运行。滚动研究的 `today-1y`/`today` 在运行时换算为具体日期写入清单。

### 日历与用途核验的维护

研究中出现预期日历之外的有效观测时，完整性标为 `calendar_conflict`、运行为 `partial`。异常日期完整记录在 `coverage.unexpected_days`，原数据保持不变；这些日期从研究统计、覆盖率、首末快照和图表中隔离，核对来源和日历后再决定是否纳入。覆盖达标的剩余数据可提供已观测样本统计，不称为完整期间。中英文页面均显示日历冲突。

新增冲突说明会更新曲线研究的解释规则指纹，因此旧曲线运行即使数值未变，用新代码重算的整体结果哈希也会不同；`verify` 如实报告不一致，旧记录不改写。需要严格复现旧运行时使用其记录的代码与配置版本；新运行使用新规则并形成独立记录。

日历检查优先报告已核验范围内的回归，即使没有可延长的新日期也返回 `regression`，CLI 退出码为 1。

`iros calendar check`（`maintenance.py`）用数据集最新版本逐日比对预期发布日历：已核验范围内重新比对（发现回归），待核验的新日期只查到最后一个有数据的日期。规则预期发布但没有数据、或规则判为休市却有数据，都记为异常，延长停在第一个异常的前一天；已核验范围内出现回归时不提出延长。建议包含一条日历核验条目（数据版本、内容校验值、比对范围）和与日历范围相接的用途核验的新记录（覆盖新增日期，原记录不改写，证据附最近一次使用该数据与用途的成功运行的核验结论）。

`iros calendar apply <建议> [--confirm]`：不加 `--confirm` 只显示改动；确认后写入 `config/calendars.yaml`（更新 `verified_through`，追加 `checks` 条目）与 `config/sources.yaml`（追加记录），重新加载登记核对，失败即还原；建议基于的核验范围与当前不符时拒绝。CI 每次运行只把核对结论写入工作流摘要；`methods.html` 的日历表显示本次构建的核对结论。

### 第二类研究：假设平价债券的利率敏感性情景

`config/studies/ust_par_bond_rate_risk.yaml`（分支 `par_bond_scenarios`，成果类型 `simulation`，用途 `scenario`）：在最近两周窗口内取所有所需期限（2Y、5Y、10Y、30Y）同时有值的最后一个曲线日为基准日，以各期限票面收益率为票息与到期收益率构造假设平价债券（每年 2 次付息、估值日为付息日），用 `analytics/bonds.py` 计算麦考利久期、修正久期、凸性与 DV01，并对每只债券自身的收益率施加 ±25～±200 bp 平移，比较完整重新定价与久期、久期 + 凸性近似。

- 独立核对（`validation.closed_form_checks`）：平价价格 = 面值；解析修正久期 = 平价债券封闭解 (1 − (1 + y/f)^(−n)) / y；解析久期与凸性 ≈ ±1 bp 有限差分完整重新定价。任一核对失败，运行标为部分受限。
- 用途为 `scenario`：Treasury 曲线现有的「描述性」用途核验不适用于这项研究，能力地图如实显示「未登记用途核验」。
- 不做票面曲线到零息曲线的换算；结果是假设现金流的数学性质，不是任何真实国债或基金（如 TLT）的风险，冲击幅度不代表概率。
- 关键发现规则 `par_bond-findings.v1`：只陈述计算结果与可验证的关系（如「期限越长，误差越大」只在数据确实单调时写出）。

### 第三类研究：国债曲线变化的会计分解

`config/studies/ust_curve_attribution_last_year.yaml`、`ust_curve_attribution_2024.yaml`（分支 `curve_attribution`，成果类型 `explanatory`，用途 `descriptive`；设计见[研究设计](study-curve-attribution.md)）：用恒等式把 Δ10Y 拆为 Δ实际收益率（`fred_dfii10`）与 Δ盈亏平衡通胀（`fred_t10yie`），把 Δ2Y 拆为 Δ联邦基金有效利率（`fred_dff`）与 Δ(2Y − 联邦基金利率)，斜率变化由这四项组成。

- 只用所有输入都有观测值的共同日期（联邦基金利率含周末，只取共同日期），不插值、不前值填充。
- 独立核对（`validation.identity_check`）：每个共同日期 |10Y − 实际 − 盈亏平衡| ≤ 0.5 bp；不通过时撤回长端分解并列为不支持的结论。
- 占比只在名义变化不小于 10 bp 时给出；期初、期末各前后移动 5 个共同日期，占比范围超过 15 个百分点时只描述方向（`results.sensitivity`）。
- CPI 同比与美联储总资产只作背景（`results.background`），不参与分解。
- 发现规则 `curve_attribution-findings.v1`；研究页展示组件 `ATTRIBUTION`（分解明细、恒等式核对、端点敏感性、两张静态图），暂无交互图表。
- CI 中这两项研究单独一步运行，FRED 取得失败时不阻断发布。FRED 序列不进公开存档，日后完整复现档案中的运行需要重新取得相同版本。

### 第四类研究：美国主要资产的长期回报与风险

`config/studies/us_asset_history.yaml`（1928–2025 全期）、`us_asset_history_last_25y.yaml`（最近 25 个完整年度，`last_n_years: 25`）（分支 `asset_history`，成果类型 `descriptive`；设计见[研究设计](study-long-run-assets.md)）：由 Damodaran 年度回报计算七类资产的算术与几何平均、波动率、最差与最好年份、亏损年数、年度最大回撤；用 FRED CPI 12 月对 12 月的通胀计算 1948 年起的实际回报；股票风险溢价为几何平均差。

- 只用所有资产都有数值的完整年度。相关矩阵给全期与事先固定的三个时期（1928–1969、1970–1999、2000–2025，少于 10 年的时期不计算）；时期边界前后移动 5 年时报告股债相关系数的范围与符号是否不变（`results.period_sensitivity`）。
- 20 年滚动几何平均回报（标普 500）只在样本不短于窗口时给出。
- 核对（`validation`）：标普 500 与 French 市场总收益（Mkt-RF + RF）年度复利的相关 ≥ 0.98；French 月度回撤应深于年度回撤；国库券与 FRED DTB3 年均值差 ≤ 0.5 个百分点；实际回报与 Shiller 实际总收益指数 12 月对 12 月变化同向的年份 ≥ 80%。可选输入缺失时不做该项核对，不冒充通过。
- 发现规则 `asset_history-findings.v1`：只描述历史数字，不用「预期」「将会」等措辞；研究页展示组件 `ASSETS`（统计表、相关矩阵、敏感性、四张静态图）。
- CI 中两项研究单独一步运行，Damodaran、French、Shiller 或 FRED 取得失败时不阻断发布。

### 第五类研究：美国炼油周度统计与处理能力情景（产业链 P0–P3a）

`config/studies/us_refining_utilization_2025.yaml`（`descriptive`）与 `us_refining_throughput_scenarios_2025.yaml`（`simulation`），分支 `refining_throughput`；设计见[产业链研究完善方案](supply-chain-research-design.md) §4、§5。

- 输入为 EIA 同一周度文件的三个数据集：总投入 `eia_refinery_gross_inputs`（WGIRIUS2，千桶/日）、可运行产能 `eia_refinery_operable_capacity`（WOCLEUS2，千桶/日历日）、官方利用率 `eia_refinery_utilization`（WPULEUS3，%）。单位不同，所以分为三个数据集；分支按角色核对序列代码、单位与公布精度，不符为硬错误。
- 模型适用范围写在分支的 `MODEL` 中（`activity: petroleum_refining`、`market: US`、`frequency: weekly`）；研究定义的 `scope` 不一致时拒绝运行，描述研究也不能夹带情景。
- 齐全性：窗口内的预期周结束日（周五）逐周要求三个数值都有效；缺失周不插值，列为「完整期间结论」不支持；晚于数据最后观测的周只说明覆盖到该日。观测日期不是周五时报硬错误。
- 复算（`validation.ratio_check`）：`analytics/rounding.py` 按 G、K 整数与 U 一位小数传播舍入区间，复算区间与 U ± 0.05 相交即相容，不设经验容差。2025 年复算与公布值的最大差为 0.053 个百分点，超过 0.05 但仍相容，说明固定容差会误判。
- 输入能力（`research/feasibility.py`，`feasibility.v1`）：每个研究单元单独定级并写入 `results.feasibility`。来源未达到 `access_verified` 为未评估；硬错误、复算不相容、假设参数不在 `method.allowed_assumptions` 或超出范围、依赖单元不可计算为 C；使用允许假设为 B；其余为 A。C 与未评估的单元不生成数值。硬错误不能靠改用假设降为 B。
- 情景：D = (1 + g) × G，Q_cap = kappa × K，经 `analytics/constraints.py` 的固定系数约束引擎求可处理量与缺口。g 是外生情景定义，kappa 是允许假设（0.90–1.00）；基准 G 已超过 Q_cap 的周标为不自洽，不抬高上限、不计入缺口。`validation.baseline_check` 核对 kappa = 1、g = 0 时可处理量逐周等于实际总投入。研究定义中 kappa = 1.05 的情景是有意保留的失败示例，结果为 C。
- `method.reference_window` 内官方利用率的分布作为假设参照写入 `results.assumption_reference`，不进入计算。参照窗口相对用途核验范围的位置与研究期间分开判断（`runs._reference_scope`），作为输入的 `reference_scope` 写入运行清单并在复现时固定，同时写入 `assumption_reference.use_scope`；不全在范围内时追加限制，报告列出状态与未覆盖期间（2026-10-29 起：2015–2025 参照窗口为 partial，未覆盖 2015-01-01—2024-12-31）。旧运行的清单没有该记录，复现时保持原结果结构。
- 约束引擎（P2）只做数学：缺值、单位不一致、回路、非正系数、多给或少给资源都报错。设计文档 §9 的虚构 GPU 算例与拒绝路径在 `tests/test_refining.py` 中独立验证；它不产生真实产业结论。
- 原始快照抽查（`raw_spot_check`）只支持 CSV，这两项研究的状态为「跳过」；与 EIA 网页历史表逐值核对 42 个值是另行完成的人工检查，不是自动抽查。
- 用途核验（2026-10-29）：三个数据集各登记 `descriptive` 与 `scenario` 两条 `use_verified`，覆盖观测 2025-01-01 至 2025-12-31，依据为两项基线运行的复现与网页历史表抽查；情景用途只确认基准输入可用，不验证 g、kappa 取值，参照期 2015–2024 不在范围内。
- CI 与网站（2026-10-30 起）：三个数据集登记 `scheduled_fetch`，CI 由 `fetch --all` 取得并在「Run refining studies」一步运行两项研究，取得或运行失败不阻断发布；本机定时快照同样保存它们（EIA 不提供历史版本）。研究页展示组件在 `site/refining.py`，英文译文在 `site/en.yaml`；发现规则未注册。EIA 允许再分发，但 `archive_data` 暂为 false，档案只保存运行记录与报告。
- 修复（2026-10-30）：情景研究的参照窗口不全在核验范围时，`gaps` 变量被未覆盖期间的文字覆盖，`coverage.missing_weeks` 误写为该文字。受影响的只有本机运行 `us_refining_throughput_scenarios_2025-20261029T184224Z-982402aa`，修复后复现为不一致；用途核验所依据的基线 `…20261028T020015Z-54e7b0bd` 不受影响。
- NAICS 分类表未接入：炼油两项研究不使用分类代码计算，分类导入留到需要 L1↔L2 映射的芯片模块（P3b）。

#### 炼油投资对照（§5.4）

`config/studies/us_refining_investment_2016_2025.yaml`（`descriptive`），分支 `refining_investment`；设计见[产业链研究完善方案](supply-chain-research-design.md) §5.4。

- 价格输入：EIA 周度现货文件 `PET_PRI_SPT_S1_W.xls` 的三个数据集，复用 `eia_pet_xls`：`eia_spot_wti_cushing`（RWTC，美元/桶）、`eia_spot_gasoline_gulf`（墨西哥湾沿岸常规汽油，美元/加仑）、`eia_spot_ulsd_gulf`（墨西哥湾沿岸超低硫柴油，美元/加仑，2006-06 起）。周值是 EIA 对日度收盘价的不加权平均；用日度文件复算，2016–2025 年多数周与周值一致，少数差异未查明。日度价格来自 Refinitiv（LSEG），只在本地使用。
- 股票输入：新接入器 `connectors/sec_graph.py`（`sec_performance_graph`）取得登记的 10-K 原文，按 `params.filings` 中逐字登记的表头与行标签定位 Item 5 业绩图数值表，数值个数、基期 100、表头唯一性不符即报错，不按位置猜测。序列 ID 为「company|申报编号」「sp500|申报编号」，因为各申报的基期不同。数据集 `sec_tsr_valero`、`sec_tsr_pbf` 各登记 FY2020、FY2022、FY2025 三份申报，可用时间为 EDGAR 接受日次日。
- 裂解价差：`method.crack_spread` 声明桶数，产品桶数之和须等于原油桶数；3-2-1 价差 = (2 × 42 × 汽油 + 42 × 柴油 − 3 × 原油) ÷ 3（美元/桶）。缺任一成分的周不计算、不插值，缺周年份不给年度汇总。
- 日历年总收益：每年取 `primary` 中第一份同时含两个年末的申报，r = V_t ÷ V_(t-1) − 1。其他已登记申报与主申报重叠的年份按指数两位小数的舍入区间核对（`validation.overlap_check:<公司>`），两家公司申报中的标普 500 年度收益互相核对（`validation.sp500_cross_issuer`）；任一不一致时相关公司的总收益单元为 C。
- 研究单元：`crack_spread`、`utilization_crack`、每家公司的 `tsr:<id>` 与 `comparison:<id>`。对照为年度超额收益（公司 − 标普 500）与年均价差、价差变化、年均利用率的 Spearman 相关，用平均秩的 Pearson 相关计算（不依赖 scipy），少于 3 年不给数值。`method.not_covered` 的公司写入限制，不算受限结论。
- 基线运行 `us_refining_investment_2016_2025-20261030T232029Z-94aa6116`（代码 1f21cdb，dirty=false，结果校验值 4debaa0f…）：六个单元均为 A；522 周四项齐全；Valero 与 PBF 各 5 个重叠年份（公司与标普 500 共 10 项）和两家公司之间 10 个标普 500 年度收益全部一致。周度利用率与价差的水平相关 Pearson 0.30、Spearman 0.26，逐年 Pearson 相关在 −0.59 至 0.44 之间变化；年度超额收益与价差变化的 Spearman 为 0.92（Valero）、0.90（PBF），只有 9 年。
- 用途核验（2026-10-30）：`eia_refinery_utilization` 追加一条、三个现货价与两个总收益数据集各一条 `descriptive` 的 `use_verified`，覆盖 2016–2025。依据为基线复现、与 EIA 网页历史表逐值核对 522 周 × 4 个序列（2,088 个值全部一致），以及总收益的重叠申报核对与跨公司核对；标普 500 年度收益与 Damodaran 同号、相差 0.07–0.38 个百分点（股息口径不同）。公司收益本身没有独立价格来源可核对。经模型技术复核登记，未人工签认。
- 发布：SEC 要求联系邮箱（`SEC_USER_AGENT`），CI 没有，所以本研究只在本机运行；已验证的运行归档到 `archive` 分支，网站恢复后发布研究页（与 `company_*` 研究相同）。公开档案的结果只含利用率与价差：研究定义的 `method.weekly_columns` 去掉周度表中的三个现货价（来自 Refinitiv），年度总收益与 10-K 业绩图数值一起公开。展示组件在 `site/refining.py`，英文译文在 `site/en.yaml`；发现规则未注册。

## 7. 扩展方法

**美国行业研究**：`research/industry.py` 实现 12/49 行业收益风险、HAC 因子暴露、实际增加值与宏观分组，以及历史 SIC 财报、独立估值快照和指引案例。`evidence_bundle` 接入器保存本地证据包及逐条定位，使用完整快照替换当前数据，同时保留旧版本。财报逐公司事实不进入公开结果。实现范围、准备命令和口径见 [行业研究](study-industries.md)。

**新增候选来源**：在 `config/sources.yaml` 登记 `id`、`publisher`、`url`、`category`，以及能写的索引字段（`directions`、`access`、`signup`、`redistribution`、`offers`、`notes`、`next_step` 等，见文件开头的说明）。读过官方说明后追加不指明数据集的 `docs_verified` 记录。资源目录与 `iros sources` 自动更新。

**新增同类数据集**：在 `config/datasets.yaml` 登记，复用已有接入器（如另一个 FRED 序列只需改 `params.series`），写明保守的 `availability`；需要积累快照时加上 `scheduled_fetch`。用 `iros fetch` 取得样本后在 `config/sources.yaml` 追加 `access_verified` 记录，并在 `site/content.yaml` 把数据集挂到研究方向（方向原为 `planned: true` 时去掉）。

**French 数据库接入器**（`connectors/french.py`，`french_csv`）：每个文件是一个 zip 内的多段 CSV。数据集用 `params.file` 指明文件，`params.section` 指明表格标题（不写为第一段），`params.columns` 与表头逐一核对，版式变化时报错而不是读错表。月度表的日期必须是 `YYYYMM`。缺失值 `-99.99`、`-999` 转为空值，不能交给取值范围判断（`-99.99` 看起来是合法收益）。文件头的 CRSP 数据库月份记在序列元数据中。

**Damodaran 接入器**（`connectors/damodaran.py`，`damodaran_xls`）：读取旧版 Excel（`.xls`，依赖 xlrd）。`params.sheet` 指明工作表，以首列为 `Year` 的行作为表头，`params.columns` 把序列代码对应到表头文字逐字核对；同名表头重复出现时取第一个（年度回报在左，「$100 价值」在右）。从表头下逐行读取，首列不再是年份即停止，汇总行不读入。表中自带的「更新日期」单元格已过时，不作依据。

**Shiller 接入器**（`connectors/shiller.py`，`shiller_xls`）：下载地址带版本号、随更新变化，每次先读 shillerdata.com 页面找 `ie_data.xls` 链接，页面上必须恰好一个。工作表 `Data` 的短名称在首列为 `Date` 的那一行（第 8 行），同名列重复出现，所以 `params.columns` 按列位置登记并逐字核对短名称。日期是小数「年.月」（`2026.1` 为 10 月），按 `round((x − 年) × 100)` 取月份，再与 Date Fraction 列逐行核对并要求月份连续。`NA` 与空单元格为缺失。四个数据集按单位与发布滞后拆分：价格、股息与盈利（滞后约四个月，可用时间取 180 天）、CAPE、实际价格与实际总收益。

**EIA 石油数据接入器**（`connectors/eia.py`，`eia_pet_xls`）：从 `www.eia.gov/dnav/pet/xls/` 下载 `.xls`，无需 key。工作表第 2 行为 `Sourcekey`、第 3 行为 `Date` 表头；`params.series` 把序列代码对应到列标题，按代码定位列并逐字核对标题（空白折叠，标题含单位），不一致即报错。日期为 Excel 日期序号，非日期单元格报错。观测日期是周结束日而不是期间起点，与 `fred_walcl` 相同按周度处理，可用时间为观测日后第 7 天 0 点（美东），偏保守。

**产业链登记与分部事实**（芯片 P0，2026-10-29；盘点见[芯片模块 P0](study-chips.md)）：

- `iros chain naics`：`supply_chain/classification.py` 下载或导入 Census 的 NAICS 2022 结构表，按 `classification.v1`（`contracts.CLASSIFICATION_COLUMNS`）保存代码、名称、层级、上级与三国共同代码标记；表头、层级或上级不符即报错。
- `iros chain segments`：`data/fundamentals.extract_segments` 用各季度当前 facts 分区所用的同一份 FSDS 原始文件，解析登记公司（`config/supply_chain/entities.yaml` 中有 CIK 的公司）的分部与维度事实，写入 `segment_facts` 表（`contracts.SEGMENT_FACT_COLUMNS`，分区布局 `segment_facts.v2`）。`period_end` 与 `filing_period_month_end` 都是 FSDS 的月末口径，`document_period_end`（精确期末）FSDS 不提供，留空；跨来源按期间匹配前须先取得精确期末。没有分部事实的季度也写出带类型的空分区。只保留业务分部、产品、地区、合并项与主要客户维度，`segments` 保留 FSDS 原文。E1 的合并口径事实表不变。
- `iros chain check`：`supply_chain/catalog.py` 读取 `config/supply_chain/` 的活动、主体、映射、关系、证据与研究单元（`supply_chain.v1`），检查以下各项：
  - 未知字段一律报错，以拦截 YAML 中未加引号的逗号拆出的键。
  - 引用必须存在。
  - 方向约定：有向关系为 provider → recipient，无向关系的 parties 排序后只存一次，竞争关系必须写 market。
  - 同一关系不重复记录。
  - 证据须来自相关公司的申报；XBRL 证据须写明数值与单位，单位参与匹配，缺数值或单位时为未核对；分部别名须属于上级公司（按 CIK）的申报，且在业务分部维度中。
  - 原文登记的精确期末（年报封面的 fiscal year ended …）须在原文中出现，且与 FSDS 月末相差不超过半个月。
  - 被否定、撤回或技术复核未通过的证据不能支撑映射或关系。三种核对分开记录：机器核对（`claim_checks`）；技术复核（`config/supply_chain/reviews.yaml`，事实核对与语义复核，可由模型完成，每项记录内容指纹 `catalog.fingerprint`，内容改变后失效并报未核对）；可选的人工复核（`review_status`，confirmed 只表示人工签认，confirmed、rejected、retracted 须写明复核人与日期）。映射与关系各有自己的复核，复核数值或摘录不等于复核业务归属。状态：自身有任何错误为 invalid（引用的任一证据机器核对失败或技术复核未通过、归属或别名不符都算）；人工否定或撤回为 rejected / retracted；人工确认为 confirmed，技术复核通过为 reviewed，两者都要求引用的每条证据已复核（机器核对通过，且经技术复核或人工确认），否则报错；证据因本地缺数据未能核对或复核记录失效时降为 candidate；其余为 candidate。技术复核通过即可用于声明范围内的研究。
  - NAICS 代码必须在导入表中。
  - XBRL 成员与事实数值必须能在分部事实中找到。
  - 摘录必须逐字出现在本地原文中，原文 SHA256 必须一致。

  本地缺少原文或数据时，相应项目记为未核对。

**芯片经营分析**（P3b，2026-10-29；见[芯片模块 P0](study-chips.md) §7）：`iros chain bundle`（`supply_chain/bundle.py`）把分部事实与登记状态打包为 `industry-evidence.v1` 证据包，经 `evidence_bundle` 接入器导入 `chip_segment_evidence`；登记核对有错误或未核对项时拒绝生成。分支 `chip_operations`（`research/chip.py`）按 `config/supply_chain/units.yaml` 的研究单元（随证据包固定）逐一评估：
- 每个单元的全部数字取自同一份最新的、覆盖所需分部 × 指标 × 财年且无冲突的年度申报。
- 所需指标没有观测时为 C。
- 分部营收合计与合并营收、分部毛利与营收减销售成本分别核对，不一致为 C；没有合并营收时跳过。
- 活动归属另列为 `attribution_status`（confirmed / reviewed / candidate / unmapped）：只计入指向本单元活动、状态为 confirmed、reviewed 或 candidate 的映射；reviewed 不等于人工签认。证据包带技术复核记录时，结果另列各映射的匹配程度、有效期与结论边界，partial 与未登记有效期作为限制保留；旧证据包保持原结果结构。

报告段落与图表在 `reporting/chip.py`。只在本机运行，未加入 CI。

**本机与 CI 的分工**（2026-10-24 确认）：接入核验（取样本、查质量、交叉核对、记 `access_verified`）与定时快照都在本机完成。CI 只取得无需凭证、登记了 `scheduled_fetch` 的数据集，用于生成网站与运行研究，同时每天在另一环境复查这些来源仍可取得。需要凭证（如 FRED API key）或人工导入的数据集默认只在本机；只有当 CI 中的研究必须用到时，才给 CI 配置凭证。网站对 CI 中有意不取得的数据集写明原因（需要 API key、人工导入、未登记定时取得，由登记推出，见 `site/collect.py` 的 `skip_reason`）；只有应当取得却没取得时才显示「本次构建未取得」。

**SEC EDGAR 财报**（E1，设计见 [EDGAR 设计说明](edgar-design.md)；网站上的两行数据集 `edgar_fsds`、`edgar_companyfacts` 由 `site/collect.py` 的 `fundamentals_datasets` 生成，CI 中没有财报数据时写明只在本机取得的原因）：财报不进入 `series.v1`，另有 `fundamentals.v1` 的申报表与事实表（`contracts.FILING_COLUMNS`、`FACT_COLUMNS`），按季度（FSDS）或公司（Company Facts）分区存放在 `data/edgar/`，DuckDB 读取当前分区；分区变化时旧版本移到 `superseded/`。`iros edgar sync` 同步（FSDS 先 HEAD 再按需下载），`iros edgar annual <公司> <指标> [--as-of 日期]` 给出年度指标及当时已公布的值，`iros edgar check` 报告覆盖与两个来源的一致性。指标与公司登记在 `config/fundamentals.yaml`。

**新增来源**：在 `connectors/` 实现 `fetch` 与 `parse`（输出暂存表的 5 列），在 `connectors/__init__.py` 注册，在 `sources.yaml` 补齐来源的 §5.1 字段与核验状态（候选来源缺这些字段时，登记数据集会报错）。数值转换、时间规则、质量与版本由公共流程处理，接入器不重复实现。

**新增研究分支**：在 `research/` 中写一个接收 `(StudySpec, dict[str, StudyInput])`、返回 `ResearchResult` 的函数，用 `@register_branch("名称")` 注册，并在 `research/__init__.py` 导入。报告只读取结构化结果；新增分支需同时注册报告段落、网站展示与发现规则。

**结构变化**：修改 `SERIES_COLUMNS` 时递增 `SERIES_SCHEMA_VERSION`，并为旧版本提供迁移；旧版本文件不改写。

## 8. 已知限制与后续工作

- Treasury 与 FRED 图表 CSV 都不提供历史版本，本地快照只能证明「何时取得了什么」，不能恢复过去的版本。时点研究需要 ALFRED（需 key）或本机定时快照（2026-10-23 起；只覆盖登记了 `scheduled_fetch` 的数据集，依赖本机开机，没有备份）。
- `fred_dgs10` 的可用时间规则原为 `next_day`，早于 FRED 上的实际可得时间；2026-10-23 改为与其他 H.15 日度序列相同的 `period_end_lag_days: 4`。此前的版本仍按旧规则记录可用时间，固定这些版本的旧运行不受影响。
- CPI 的 45 天可用规则是对当前版本的保守近似，不是实际发布日期。
- ALFRED 已于 2026-10-23 用真实 key 接入 CPIAUCSL、UNRATE、PAYEMS 的全部历史版本（`access_verified`）。key 放在项目根目录的 `.env`，CLI 启动时读取（只设置环境中尚未设置的变量），launchd 定时任务也因此能读到；GitHub CI 未配置 key，不取得 ALFRED。ALFRED 由供应方保留全部历史版本，所以不参加本机定时快照。
- 预期日历核验到 2026-10-22；之后的额外休市或发布日（如耶稣受难日、临时国丧日）需要逐年核验并追加。
- 2026-10-22 首次运行 `ust_curve_2024-20261022T221917Z` 的清单记录了未提交代码（`dirty=true`）和旧的输入格式，保留原样作为历史记录；以上方基线运行为准。
- 存储为单写入者流程，没有并发锁；没有实现备份。数据规模小，DuckDB 暂未引入，需要跨数据集查询时再加。
- 报告已覆盖曲线、利率情景、归因、长期资产和行业描述研究；预测和策略模拟的预登记、样本外评估尚未实现。
- 交易日历、公司行动、证券标识等市场制度对象尚未实现，这些是证券与组合研究的前置条件。

## 9. 审查修复记录（2026-10-22）

依据 `reports/reviews/2026-10-22-p1-p2-review.md` 的复现结果修复，每项都有对应的反例测试：

| 问题 | 修复 | 测试 |
|---|---|---|
| F1 当前修订值可进入过去的时点视图 | `vintages` 声明 + 行级「当时已知」证据 + 按时点选择版本 | `test_current_revision_cannot_enter_past_point_in_time_view`、`test_as_of_rejects_current_revision_not_held_at_the_time`、`test_as_of_replays_snapshot_held_at_the_time` |
| F2 全年两日仍为完整、成功 | 对照预期日历的日期覆盖；期间不完整时不输出期间统计 | `test_two_observations_in_a_year_is_not_complete`、`test_incomplete_period_keeps_endpoints_but_withholds_period_stats` |
| F3 失败路径泄露 API key | 安全展示地址 + 错误文本清洗 | `test_fred_api_failure_does_not_leak_key` |
| F4 同一秒运行覆盖记录 | 随机后缀运行 ID + 排他创建目录 | `test_same_second_runs_do_not_overwrite` |
| F5 复现引入原运行没有的可选输入 | 清单记录完整角色集合（含未使用）与当时的核验状态 | `test_verify_keeps_originally_missing_optional_input_missing` |
| F6 未知分红填零 | 显式未知保持未知；稀疏事件表需声明 `events_complete` | `test_unknown_distribution_is_not_zero` |
| F7 标准化等阶段失败无记录 | 开始/终态成对记录，覆盖全部阶段；登记时拒绝不支持的频率 | `test_normalize_stage_failure_is_logged`、`test_dataset_rejects_unsupported_frequency` |
| F8 ALFRED 忽略分页 | 逐页取得并核对 `count` | `test_alfred_fetches_all_pages`、`test_alfred_truncated_result_fails` |
| F9 用途核验未落实 | `status_for(dataset, use)`；`use_verified` 必须声明用途 | `test_use_verification_only_counts_for_that_use`、`test_use_verified_requires_use` |

另外：倒挂定义为利差严格小于 0，零利差日单独计数并在报告中列出；报告主要结果表注明以首个有效观测为基准。
