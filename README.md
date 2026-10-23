# Investment Research OS

个人使用的投资分析框架。以可获得的免费资源为基础，先建立可靠、可扩展的总体架构，再逐步细化宏观、市场、资产、证券和组合研究。

## 当前状态

- **P0 总体架构**：完成，见 [V0.3](docs/architecture.md)。
- **P1 公共契约与资源核验**：首个案例所需部分已实现——来源与数据集登记、核验状态、时间契约、质量规则、成果与运行契约。
- **P2 小规模贯通验证**：已用真实免费数据跑通「2024 年美国国债收益率曲线变化」：取得 → 原始快照 → 标准化与版本 → 公共分析 → 报告与运行记录 → 复现校验。
- **P3/P4**：未开始。宏观、行业、证券、组合等研究分支只有公共计算组件（收益、风险、利率曲线），尚无对应研究模块。

接入已验证的来源：美国财政部日度票面收益率曲线、FRED 图表 CSV（DGS10、CPIAUCSL）。FRED API（ALFRED 历史版本）已实现接入器并用离线样本测试，尚未用真实 key 验证。详见 [实现说明](docs/implementation.md)。

## 快速开始

需要 [uv](https://docs.astral.sh/uv/)；依赖版本由 `uv.lock` 锁定，Python 3.12。

```bash
uv sync
```

```bash
uv run iros fetch ust_par_yield_curve --start 2024 --end 2024
```

```bash
uv run iros fetch fred_dgs10 --start 2024-01-01 --end 2024-12-31
```

```bash
uv run iros run config/studies/ust_curve_2024.yaml
```

报告写在 `reports/<study_id>/<run_id>/report.html`（图表内嵌，可离线打开），运行清单在 `runs/<run_id>/manifest.json`。

```bash
uv run iros verify <run_id>
```

## 项目网站

线上地址：<https://werneryang.github.io/investment-research-os/>

`.github/workflows/pages.yml` 在推送到 main、每个工作日 23:30 UTC 及手动触发时运行：测试 → 重新取得 Treasury 与 FRED 数据 → 运行 `ust_curve_2024` 与滚动的 `ust_curve_last_year` → `iros verify --all` → 归档到 `archive` 分支 → 生成静态网站 → 发布到 GitHub Pages。任何必需步骤失败都不发布，线上保留上一版，页面顶部的更新时间、工作流徽章与「已过期」提示会显示更新停滞。

网站内容：每项研究的最新结果（交互图表：走势、区间、序列开关、任意两日曲线对比）、稳定的最新报告地址 `latest/<study_id>/report.html`、历史记录页 `history/<study_id>.html`、数据来源与核验状态、可靠性机制。

**运行档案**（`archive` 分支，只追加）：运行清单、结果、报告，以及允许公开再分发的数据（`config/datasets.yaml` 中 `archive_data: true`，目前只有 Treasury 曲线）。只有结论实质变化时才归档新运行。日后复现旧运行：

```bash
git worktree add _archive origin/archive
```

```bash
uv run iros archive restore _archive --with-data
```

```bash
uv run iros verify <run_id>
```

FRED 交叉核验数据未归档，复现时该部分不重算，结果标为「部分复现」。

本地生成与预览：

```bash
uv run iros site --out _site
```

```bash
python3 -m http.server 8765 --directory _site
```

页面说明性内容在 `site/content.yaml`，样式与图表脚本在 `site/assets/`；研究结果、数据与核验状态从运行记录和登记中生成。

其他命令：`iros sources`（来源与核验状态）、`iros datasets`（版本与质量概况）、`iros runs`、`iros import <dataset> <file> --declared-source "..."`（人工导入）。

```bash
uv run pytest
```

测试全部离线运行。

## 设计要点

- 研究核心独立运行，支持描述分析、解释与归因、预测、策略模拟等不同成果。
- 必要运行链路使用免费数据与软件，支持本地运行、官方文件下载和人工导入；付费 AI、云服务和限时试用不作为必要依赖。
- 来源、口径、历史可用时间、质量和结果版本贯穿全程；数据不足时限制相应分析。
- 全球、美国、中国及其他市场保留扩展位置，具体接入范围由免费资源核验和研究需要决定。
- 个人资金规模、税务身份与券商账户不是架构设计或公开数据研究的前提；账户、税务与实施分析为可选扩展。

## 文档目录

- [当前架构与实施路线](docs/architecture.md)：设计基线（V0.3）
- [实现说明](docs/implementation.md)：代码结构、契约落地方式、如何扩展、已知限制
- [历史方案索引](docs/archive/README.md)：保留 A、B、C 原始文档及 V0.2，追溯设计来源与定位变化。

历史方案与当前框架有差异时，以当前框架为准。当前文档的修订说明记录本次取舍，Git 用于保存后续版本历史。
