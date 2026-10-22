# 实现说明（P1/P2）

**对应设计：** [架构 V0.3](architecture.md) §3、§5–§10

**更新日期：** 2026-10-22

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

`data.as_of(df, t)` 只返回 `available_at ≤ t` 的行，并为每个观测取当时最新的版本。`available_at` 未知的行一律排除。

**版本号**：供应方有历史版本时（ALFRED）用 `alfred:<realtime_start>`；否则为本地快照 `local:<取得时间>`。内容校验值不包含取得时间和本地快照编号，因此重复下载相同内容不会产生新版本。

**质量状态**：`ok`、`missing`（来源未给值，如假日或 `.`）、`quarantined`（无法解析、超出登记范围、同键冲突）。下游只用 `quality.ok_rows` 返回的行；不填零，不前值填补，不插值。

**研究成果**（`research.base.ResearchResult`）包含 §6.3 的公共字段：研究 ID、类型、范围、数据截止、方法、输入版本、结果、覆盖、不支持的结论、限制和验证。运行状态取 `success`、`partial`（有结论被限制或某项验证未通过）、`failed`。

## 4. 失败行为（对应 §7.2）

| 情况 | 实现 |
|---|---|
| 取得失败或限流 | 有界重试（默认 3 次，指数退避）；失败写入 `fetch_log.jsonl`，保留旧版本，不产生新的更新时间 |
| 返回内容不对（如维护页面、序列名不符） | 解析失败，原始快照仍保存供诊断 |
| 部分缺失 | 标为 `missing` 并报告缺口；低于研究的 `min_coverage` 时，依赖它的指标列入「不支持的结论」，其他结论照常输出 |
| 研究期间未被数据完整覆盖 | 运行为 `partial`，限制中写明实际覆盖范围 |
| 可选输入不可用 | 跳过相应验证并在运行清单中警告；必需输入缺失则运行失败，仍留下清单 |
| 版本文件被改动 | 加载时比对内容校验值，不一致即拒绝 |
| 缺少 FRED_API_KEY | ALFRED 接入器拒绝运行并提示降级路径，key 不写入快照或日志 |

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
- ALFRED 接入器只用离线样本测试，状态保持 `docs_verified`，直到用真实 key 取得样本。
- 存储为单写入者流程，没有并发锁；没有实现备份。数据规模小，DuckDB 暂未引入，需要跨数据集查询时再加。
- 报告模板目前只覆盖曲线类描述性结果；预测和策略模拟的预登记、样本外评估等（§8）尚未实现。
- 交易日历、公司行动、证券标识等市场制度对象尚未实现，这些是证券与组合研究的前置条件。
