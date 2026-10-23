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

- `index.html` 研究总览：以 `site/content.yaml` 中 `study_order` 的第一项（滚动研究）为焦点，展示关键发现、关键数字、交互图表与一行证据摘要；其余研究列在「全部研究」。
- `studies/<study_id>/` 研究页（统一模板）：研究问题 → 关键发现 → 可视化证据（图表面板、数据覆盖条）→ 方法 → 证据与限制（证据面板）→ 历史与复现（发现变化记录、历次运行）。
- **图表面板采用渐进增强**：首页与研究页的静态图（与完整报告相同）默认可见；`site/assets/charts.js` 只在 Chart.js 已加载、`chart.json` 取得、图表生成都成功后才显示交互图表并收起静态图（可再展开）。任何一步失败，静态图保持可见，并按实际情况说明原因与有没有静态图；禁用脚本时也只显示静态图。Chart.js 4.4.1 随站点托管在 `site/assets/vendor/`（来源、许可与 SHA-512 见其中 README，测试会校验），不依赖外部 CDN。样式与脚本地址带内容校验值（`?v=`），改动后访客不会用到缓存的旧文件。
- **关键发现**（`research/findings.py`）：按研究分支的固定规则从结果生成句子，每条附所依据的指标路径与数值；变化小于 5 bp 记为「基本持平」；有缺口的指标只描述已观测日期。只描述，不作预测或交易判断。**解释在运行时固定**：发现、定性状态、规则版本（`RULE_VERSIONS`）、规则指纹（规则代码的校验值，规则改动后自动变化）与阈值参数写入结果的 `interpretation`，纳入结果校验值与 `verify`；网站显示运行当时记录的发现，规则已变化时注明但不改写。没有记录解释的旧运行，网站用当前规则事后生成并标明，`verify` 也不为它们补写。**发现变化记录**比较相邻两次运行的定性状态（利差期末是否倒挂、变陡或变平、覆盖），并列出两次运行之间可以客观比较的差异：研究窗口、各输入的数据版本、代码或登记配置（`source_hash`）、解释规则；不推断变化的原因。`source_hash` 不含 `config/studies/`：研究定义完整记录在每次运行的清单中。
- **覆盖与完整性**（`research/rates_curve.py`）分开判断：`coverage_acceptable`（应已发布日期的覆盖是否达到 `min_coverage`）决定期间统计能否输出；`completeness` 为 `complete`（全部预期日期有数据且日历已核验）、`complete_to_date`（应已发布的日期都有数据，另有日期尚未到发布时间）、`gaps`（有应已发布但缺失的日期）、`unverified_calendar`（相关日期超出日历核验范围，无法证明没有缺失）、`insufficient` 或 `no_calendar`；`period_complete` 只在 `complete` 时为真。「尚未发布」按数据集的可用时间规则与运行时写入 `scope.evaluated_at` 的评估时间判断，复现使用同一时间；比规则更早出现的数据按已观测计入。每个指标在 `coverage.metrics` 中记录自己的覆盖（利差与曲率要求所需期限同一天都有值）；有缺口的指标，期间统计标为 `sample: observed`，发现与报告只描述已观测日期。
- **证据面板**逐项列出研究用途、各输入的来源与版本、日期与期限覆盖、原始快照抽查、同源一致性检查、固定输入重算、代码版本与不支持的结论，不汇总成分数。**数据覆盖条**按预期观测日显示曲线与各关键期限是否有合格值；结果中的 `coverage.missing_dates` 提供完整缺失列表（只在有缺失时写入）。
- **展示组件按研究分支注册**（`site/renderers.py`）：研究页与首页只负责共同结构（六个章节、证据面板的共同行、发现与解释、历史与复现）；每个分支提供自己的指标卡片、方法说明、覆盖或假设部分、证据行、历史列、交互图表数据（`chart.json`，`kind` 决定图表类型）、静态图与用途说明。没有注册展示组件的分支显示「暂无展示组件」，不套用其他分支的说明。
- `map.html` 研究能力地图：领域在 `site/content.yaml` 的 `domains` 中列出；数据能力、分析能力（工程）与研究验证（用途核验）由登记、研究分支声明的成果类型与最新运行自动得出，只有 `planned: true` 的领域人工维护并写明缺什么。
- `methods.html` 数据、方法与状态：来源与核验、预期日历、可靠性机制、复现方法与系统状态（`#status`）。
- 页脚显示发布时间、代码版本与工作流徽章；更新停滞超过 2 个工作日时各页顶部显示提示。
- 每次运行的 `report.html`、图表、`daily.json`、`manifest.json`、`result.json` 发布在 `runs/<run_id>/`；`latest/<study_id>/report.html` 为最新完整报告的稳定地址；旧的 `history/<study_id>.html` 转到研究页的历史部分。
- 利差显示名写明减法方向（`10Y − 2Y`）；结果文件中的键（`2Y-10Y`）保持不变。

**运行档案**（`iros archive save|restore <dir>`）：CI 把运行记录与报告保存到 `archive` 分支的工作树，只追加、不覆盖。每项研究只在实质内容（结果、覆盖、限制、核验结论；不含运行 ID 与输入版本号）变化时归档新运行；结论相同的运行在 `archive.jsonl` 中记为 skipped，以后不再考虑。数据只归档 `archive_data: true` 的数据集中被已归档运行使用的版本（目前只有 Treasury 曲线，2026-10-22 经用户确认）。

复现档案中的运行：`iros archive restore <dir> --with-data` 恢复记录与数据（目录按创建时间重排），再 `iros verify <run_id>`。固定版本不在本地的**可选**输入（FRED 交叉核验）不重算，比较去掉该输入及其核验项后的结果，记为部分复现；必需输入缺失则报错。

`.github/workflows/pages.yml`：测试 → 取得 → 运行 → `verify --all` → 归档并恢复历史 → 生成网站 → 推送档案 → 发布。CI 每次从零开始，展示的是当次运行，不是本地基线运行。滚动研究的 `today-1y`/`today` 在运行时换算为具体日期写入清单。

### 日历与用途核验的维护

`iros calendar check`（`maintenance.py`）用数据集最新版本逐日比对预期发布日历：已核验范围内重新比对（发现回归），待核验的新日期只查到最后一个有数据的日期。规则预期发布但没有数据、或规则判为休市却有数据，都记为异常，延长停在第一个异常的前一天；已核验范围内出现回归时不提出延长。建议包含一条日历核验条目（数据版本、内容校验值、比对范围）和与日历范围相接的用途核验的新记录（覆盖新增日期，原记录不改写，证据附最近一次使用该数据与用途的成功运行的核验结论）。

`iros calendar apply <建议> [--confirm]`：不加 `--confirm` 只显示改动；确认后写入 `config/calendars.yaml`（更新 `verified_through`，追加 `checks` 条目）与 `config/sources.yaml`（追加记录），重新加载登记核对，失败即还原；建议基于的核验范围与当前不符时拒绝。CI 每次运行只把核对结论写入工作流摘要；`methods.html` 的日历表显示本次构建的核对结论。

### 第二类研究：假设平价债券的利率敏感性情景

`config/studies/ust_par_bond_rate_risk.yaml`（分支 `par_bond_scenarios`，成果类型 `simulation`，用途 `scenario`）：在最近两周窗口内取所有所需期限（2Y、5Y、10Y、30Y）同时有值的最后一个曲线日为基准日，以各期限票面收益率为票息与到期收益率构造假设平价债券（每年 2 次付息、估值日为付息日），用 `analytics/bonds.py` 计算麦考利久期、修正久期、凸性与 DV01，并对每只债券自身的收益率施加 ±25～±200 bp 平移，比较完整重新定价与久期、久期 + 凸性近似。

- 独立核对（`validation.closed_form_checks`）：平价价格 = 面值；解析修正久期 = 平价债券封闭解 (1 − (1 + y/f)^(−n)) / y；解析久期与凸性 ≈ ±1 bp 有限差分完整重新定价。任一核对失败，运行标为部分受限。
- 用途为 `scenario`：Treasury 曲线现有的「描述性」用途核验不适用于这项研究，能力地图如实显示「未登记用途核验」。
- 不做票面曲线到零息曲线的换算；结果是假设现金流的数学性质，不是任何真实国债或基金（如 TLT）的风险，冲击幅度不代表概率。
- 关键发现规则 `par_bond-findings.v1`：只陈述计算结果与可验证的关系（如「期限越长，误差越大」只在数据确实单调时写出）。

## 7. 扩展方法

**新增同类数据集**：在 `config/datasets.yaml` 登记，复用已有接入器（如另一个 FRED 序列只需改 `params.series`），并在 `config/sources.yaml` 追加核验记录。

**新增来源**：在 `connectors/` 实现 `fetch` 与 `parse`（输出暂存表的 5 列），在 `connectors/__init__.py` 注册，在 `sources.yaml` 登记来源与核验状态。数值转换、时间规则、质量与版本由公共流程处理，接入器不重复实现。

**新增研究分支**：在 `research/` 中写一个接收 `(StudySpec, dict[str, StudyInput])`、返回 `ResearchResult` 的函数，用 `@register_branch("名称")` 注册，并在 `research/__init__.py` 导入。报告只读取结构化结果；目前的报告模板针对曲线类结果，其他成果类型需要增加相应的报告段落。

**结构变化**：修改 `SERIES_COLUMNS` 时递增 `SERIES_SCHEMA_VERSION`，并为旧版本提供迁移；旧版本文件不改写。

## 8. 已知限制与后续工作

- Treasury 与 FRED 图表 CSV 都不提供历史版本，本地快照只能证明「何时取得了什么」，不能恢复过去的版本。时点研究需要 ALFRED（需 key）或从现在起持续保存快照。
- CPI 的 45 天可用规则是对当前版本的保守近似，不是实际发布日期。
- ALFRED 接入器（含分页）只用离线样本测试，状态保持 `docs_verified`，直到用真实 key 取得样本。
- 预期日历核验到 2026-10-22；之后的额外休市或发布日（如耶稣受难日、临时国丧日）需要逐年核验并追加。
- 2026-10-22 首次运行 `ust_curve_2024-20261022T221917Z` 的清单记录了未提交代码（`dirty=true`）和旧的输入格式，保留原样作为历史记录；以上方基线运行为准。
- 存储为单写入者流程，没有并发锁；没有实现备份。数据规模小，DuckDB 暂未引入，需要跨数据集查询时再加。
- 报告模板目前只覆盖曲线类描述性结果；预测和策略模拟的预登记、样本外评估等（§8）尚未实现。
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
