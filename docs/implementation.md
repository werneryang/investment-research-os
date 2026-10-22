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

iros verify <run_id>   → 用清单中的研究定义与数据版本重算，比较结果校验值
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

**预期观测日历**：`config/calendars.yaml` 登记经核验的发布日集合。`us_treasury_daily`（工作日减联邦假日与耶稣受难日）与 Treasury 2024、2025 年 CSV 的日期集合逐日一致。研究的日期覆盖对照预期日历计算，期限覆盖的分母同样是预期观测日；没有日历的数据集无法证明期间完整。

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

2026-10-22 用真实数据运行的结果：250 个交易日，关键期限覆盖 100%；与 FRED DGS10 的 250 个共同日期完全一致（两者同源，只说明接入与解析正确，不是独立验证）；12 个原始快照抽查全部一致；`iros verify` 复现结果校验值。

验证到此为止：计算正确、来源可追溯、固定输入可复现。这不代表该来源在其他期间或其他用途上已经验证，也不包含任何预测或交易含义。

## 6. 扩展方法

**新增同类数据集**：在 `config/datasets.yaml` 登记，复用已有接入器（如另一个 FRED 序列只需改 `params.series`），并在 `config/sources.yaml` 追加核验记录。

**新增来源**：在 `connectors/` 实现 `fetch` 与 `parse`（输出暂存表的 5 列），在 `connectors/__init__.py` 注册，在 `sources.yaml` 登记来源与核验状态。数值转换、时间规则、质量与版本由公共流程处理，接入器不重复实现。

**新增研究分支**：在 `research/` 中写一个接收 `(StudySpec, dict[str, StudyInput])`、返回 `ResearchResult` 的函数，用 `@register_branch("名称")` 注册，并在 `research/__init__.py` 导入。报告只读取结构化结果；目前的报告模板针对曲线类结果，其他成果类型需要增加相应的报告段落。

**结构变化**：修改 `SERIES_COLUMNS` 时递增 `SERIES_SCHEMA_VERSION`，并为旧版本提供迁移；旧版本文件不改写。

## 7. 已知限制与后续工作

- Treasury 与 FRED 图表 CSV 都不提供历史版本，本地快照只能证明「何时取得了什么」，不能恢复过去的版本。时点研究需要 ALFRED（需 key）或从现在起持续保存快照。
- CPI 的 45 天可用规则是对当前版本的保守近似，不是实际发布日期。
- ALFRED 接入器（含分页）只用离线样本测试，状态保持 `docs_verified`，直到用真实 key 取得样本。
- 预期日历只核验了 2024、2025 年；临时休市日（如国丧日）需要按证据追加。
- 2026-10-22 首次运行 `ust_curve_2024-20261022T221917Z` 的清单记录了未提交代码（`dirty=true`）和旧的输入格式，保留原样作为历史记录。修复后应在干净提交上生成新的基线运行。
- 存储为单写入者流程，没有并发锁；没有实现备份。数据规模小，DuckDB 暂未引入，需要跨数据集查询时再加。
- 报告模板目前只覆盖曲线类描述性结果；预测和策略模拟的预登记、样本外评估等（§8）尚未实现。
- 交易日历、公司行动、证券标识等市场制度对象尚未实现，这些是证券与组合研究的前置条件。

## 8. 审查修复记录（2026-10-22）

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
