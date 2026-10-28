# Investment Research OS

个人使用的投资分析框架。以可获得的免费资源为基础，先建立可靠、可扩展的总体架构，再逐步细化宏观、市场、资产、证券和组合研究。

## 当前状态

- **P0 总体架构**：完成，见 [V0.3](docs/architecture.md)。
- **P1 公共契约与资源核验**：首个案例所需部分已实现——来源与数据集登记、核验状态、时间契约、质量规则、成果与运行契约。
- **P2 小规模贯通验证**：已用真实免费数据跑通「2024 年美国国债收益率曲线变化」：取得 → 原始快照 → 标准化与版本 → 公共分析 → 报告与运行记录 → 复现校验。
- **P3 研究分支扩展**：已实现利率情景与归因、主要资产长期回报，以及美国 12/49 行业和经济、历史财报、估值、指引专题；覆盖范围见各项研究设计。**P4 预测与策略评估**尚未实现。

接入已验证的来源：美国财政部日度票面收益率曲线；FRED 宏观、BEA 行业增加值、BLS 行业就业/工时/工资、工业生产和 EIA WTI 现货价；ALFRED 的 CPI、失业率、非农历史版本；French 美国及国际股票因子、12/49 行业收益和样本特征；Damodaran 长期资产回报与行业估值/利润率快照；Shiller 价格、股息、盈利与 CAPE；SEC 财报和选定公司的管理层指引原文。历史财报专题使用各期 SIC 样本，不等于完整股票行业。FRED API key 放在项目根目录的 `.env`（`FRED_API_KEY=...`，不入库），`iros` 启动时读取；行业研究新增来源无需新 key。详见 [实现说明](docs/implementation.md)。

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

本机定时快照：每个工作日取得登记了 `scheduled_fetch` 的数据集（Treasury 曲线与 FRED 序列），存入本地 `data/`。Treasury 与 FRED 只提供当前修订版本，漏掉的日期补不回来。

```bash
scripts/snapshot-agent.sh install
```

定时任务最后把补不回来的数据备份到 `.env` 中 `IROS_BACKUP_DIR` 指定的文件夹（如 Google Drive），见 `scripts/backup-data.sh`。`scripts/snapshot-agent.sh status` 查看最近日志；手动取得全部定时数据集用 `uv run iros fetch --all`。

## 项目网站

线上地址：<https://werneryang.github.io/investment-research-os/>

`.github/workflows/pages.yml` 在推送到 main、每个工作日 23:30 UTC 及手动触发时运行：测试 → 取得登记的公开数据 → 运行国债曲线、利率情景、曲线归因、长期资产和 `us_industry_12` / `us_industry_49` → `iros verify --all` → 归档到 `archive` 分支并恢复历史 → 生成静态网站 → 发布到 GitHub Pages。依赖可选来源的研究取得失败不阻断其他研究发布；任何必需步骤失败都不发布。四层专题 `us_industry_dossier` 和 `company_*` 公司研究使用本地准备的财报与指引证据，网站恢复其已验证档案，不在每次 CI 下载全部原始财报。线上更新时间、工作流徽章与「已过期」提示会显示更新停滞。

网站定位为研究门户，分工回答四个问题：

- **系统研究什么、从哪里进入**：首页按研究框架（[研究框架地图](docs/research-map.md)）组织：研究分支 → 研究方向 → 研究。顶部是六个分支的总览，规划中的分支降低权重但同样可见；已有研究或数据的分支随后展开，每项研究只显示一句主要发现、数据日期、用途与需要注意的例外，细节在研究页。
- **研究发现了什么**：每项研究有固定地址的研究页 `studies/<study_id>/`，按「研究问题 → 关键发现 → 可视化证据 → 方法 → 证据与限制 → 历史与复现」组织。关键发现由固定规则从结果生成，每条可展开查看所依据的指标。
- **这些发现有多可靠**：研究页的证据面板逐项列出来源与版本、日期与期限覆盖、核验与复现结果、限制，不汇总成笼统分数；数据覆盖条按日期显示缺失。`methods.html` 说明数据来源、时间规则、日历、可靠性机制与复现方法。
- **系统能研究什么**：`map.html` 研究能力地图由登记与运行记录生成，区分工程完成与研究验证；研究框架与规划中的方向在 `site/content.yaml` 维护。系统状态放在页脚与 `methods.html#status`，只有更新停滞时才在页面顶部提示。
- **可以用哪些免费资源**：`sources.html` 数据资源目录由 `config/sources.yaml` 生成，列出已接入与候选来源的取得方式、许可、核验状态、可服务的研究方向与下一步，并按研究方向索引能力缺口。

页面顶端右侧可切换中英文：英文页面在 `en/` 下，研究发现按同一规则的英文措辞生成；完整报告只有中文。译文维护在 `site/en.yaml`。

**运行档案**（`archive` 分支，只追加）：运行清单、结果、报告，以及允许公开再分发的数据（`config/datasets.yaml` 中 `archive_data: true`，目前只有 Treasury 曲线）。只有结论实质变化时才归档新运行；内容相同的数据文件只存一份，多个版本共用。日后复现旧运行：

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

**日历与用途核验的维护**：新数据发布后，预期发布日历与用途核验需要延长才能覆盖新日期。CI 每次运行都会核对并把结论写到工作流摘要（只报告，不写入）。确认延长时在本地：

```bash
uv run iros fetch ust_par_yield_curve --start 2024
```

```bash
uv run iros calendar check --out calendar-proposal.json
```

```bash
uv run iros calendar apply calendar-proposal.json
```

预览无误后加 `--confirm` 写入，再提交 `config/` 的改动。规则预期与实际发布日期不一致（例如临时休市）时，工具只列出异常、延长停在异常前一天，需要人工判断后修改日历。

本地生成与预览：

```bash
uv run iros site --out _site
```

输出目录必须是新目录、空目录，或由本工具标记且没有额外文件的网站目录。已有但未标记的旧 `_site` 请先移走，或改用新的输出目录；项目源文件、数据、报告及档案目录不能作为网站输出。构建失败会保留上一版网站。

```bash
python3 -m http.server 8765 --directory _site
```

页面说明性内容在 `site/content.yaml`，样式与图表脚本在 `site/assets/`；研究结果、数据与核验状态从运行记录和登记中生成。

SEC 财报（设计与实现见 [EDGAR 设计说明](docs/edgar-design.md)；`.env` 中需要 `SEC_USER_AGENT=项目名 联系邮箱`）：

```bash
uv run iros edgar sync
```

```bash
uv run iros edgar annual apple revenue --as-of 2024-01-01
```

其他命令：`iros fetch --all`（全部定时数据集）、`iros sources`（已接入与候选来源及核验状态）、`iros datasets`（版本与质量概况）、`iros runs`、`iros import <dataset> <file> --declared-source "..."`（人工导入）。

```bash
uv run pytest
```

测试全部离线运行。

## 开发流程

本节是本项目的共享开发规则，Codex 与 Claude Code 都以此为准；各自的入口文件只引用这里，不另维护一套流程。

**持续授权（仅限本项目）：如果任务需要 commit，自动完成 push；如果需要 PR 或 merge，也一并完成。** 在任务已授权的改动范围内，完成必要验证后将改动落实到远端 `main`，不在提交、推送、创建 PR 或等待合并处停下要求重复确认。推送 `main` 会触发下述网站发布工作流，也在本项目的这项授权范围内。

- **普通改动**：默认不开 PR。在功能分支上完成、验证、提交并推送，再在本地合并进 `main`（`git merge --no-ff`），运行 `uv run pytest`，通过后推送 `main`。
- **公共契约或研究计算改动**：涉及 `registry.py`、`contracts.py`、`analytics/`、`research/` 时，提交并推送分支，创建或更新 PR，检查最终差异与必要验证；没有未解决问题且满足平台要求后，以 merge commit 合并 PR，更新本地 `main` 并确认与远端同步。PR 是合并前的审查载体，不额外要求用户逐次批准；模型检查不冒充人工审查。
- **遇到阻断**：测试失败、合并冲突、远端变化或权限问题时，先在授权范围内处理可恢复原因；确需介入时说明具体阻断。不得通过强推、跳过必要检查或绕过平台限制完成合并。
- **完成核对**：报告提交、推送、PR、合并的实际状态；合并成功与网站部署成功分别核实。本地 `.claude/` 预览配置和工作树不纳入提交。

这样做的依据：

- `main` 没有分支保护。
- 网站工作流只在推送到 `main`、定时与手动触发时运行，开 PR 不会触发测试。
- 推送后任何必需步骤失败都不发布，线上保留上一版页面。

想让 PR 在合并前就跑测试，可以给工作流加上只测试、不发布的 `pull_request` 触发。

## 设计要点

- 研究核心独立运行，支持描述分析、解释与归因、预测、策略模拟等不同成果。
- 必要运行链路使用免费数据与软件，支持本地运行、官方文件下载和人工导入；付费 AI、云服务和限时试用不作为必要依赖。
- 来源、口径、历史可用时间、质量和结果版本贯穿全程；数据不足时限制相应分析。
- 全球、美国、中国及其他市场保留扩展位置，具体接入范围由免费资源核验和研究需要决定。
- 个人资金规模、税务身份与券商账户不是架构设计或公开数据研究的前提；账户、税务与实施分析为可选扩展。

## 文档目录

- [产业链研究完善方案](docs/supply-chain-research-design.md)：行业分类 → 细分业务 → 公司业务与财务 → 产业关系；包含免费数据门槛、行业模型适配、炼油与芯片对照及验收标准（**规划中，未宣称新能力已接入或实现**）。
- [当前架构与实施路线](docs/architecture.md)：设计基线（V0.3）
- [实现说明](docs/implementation.md)：代码结构、契约落地方式、如何扩展、已知限制
- [研究设计：美国主要资产的长期回报与风险](docs/study-long-run-assets.md)：1928 年以来七类资产的名义与实际回报、风险与相关性（已实现）
- [美国行业的经济、盈利与股票回报](docs/study-industries.md)：12/49 行业、历史 SIC 财报专题、估值与指引案例（已实现范围及明确的数据边界）
- [研究设计：国债曲线变化的分解](docs/study-curve-attribution.md)：第一项解释与归因研究，用会计恒等式拆分实际利率、通胀补偿与政策利率（已实现）
- [15 家公司年度财报研究](docs/study-companies.md)：现有样本的营收、利润率、现金流、资本开支、可比性及申报版本（已实现）
- [SEC EDGAR 财报数据设计](docs/edgar-design.md)：全部申报主体的财报事实、财年与申报版本、分区存储（草案，待审阅）
- [历史方案索引](docs/archive/README.md)：保留 A、B、C 原始文档及 V0.2，追溯设计来源与定位变化。

历史方案与当前框架有差异时，以当前框架为准。当前文档的修订说明记录本次取舍，Git 用于保存后续版本历史。
