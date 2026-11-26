# Investment Research OS

个人使用的投资分析框架。以可获得的免费资源为基础，先建立可靠、可扩展的总体架构，再逐步细化宏观、市场、资产、证券和组合研究。

## 当前状态

- **P0 总体架构**：完成，见 [V0.3](docs/architecture.md)。
- **P1 公共契约与资源核验**：首个案例所需部分已实现——来源与数据集登记、核验状态、时间契约、质量规则、成果与运行契约。
- **P2 小规模贯通验证**：已用真实免费数据跑通「2024 年美国国债收益率曲线变化」：取得 → 原始快照 → 标准化与版本 → 公共分析 → 报告与运行记录 → 复现校验。
- **P3 研究分支扩展**：已实现利率情景与归因、主要资产长期回报，以及美国 12/49 行业和经济、历史财报、估值、指引专题；覆盖范围见各项研究设计。产业链研究的炼油段（EIA 周度统计与处理能力情景，含输入能力等级与约束引擎）与投资对照（裂解价差、利用率与 Valero、PBF 的 10-K 业绩图总收益）已在本机实现；芯片模块完成 P0 与 P3b 经营分析（NVIDIA、Micron 的分部财务，两个受限请求为 C，已登记描述用途核验；证据与映射已通过技术复核，人工复核为可选，见[芯片模块](docs/study-chips.md)）。事件研究完成第一版：NVIDIA 首席执行官离任的原文事实与时间线（[事件研究](docs/study-events.md)）。公司季度财报研究完成第一版：Alphabet 2026 年第三季度的五个季度报告口径财务数据、可比性限制与资本开支展望对照（[季度财报研究](docs/study-earnings.md)）。**P4 预测与策略评估**尚未实现。

接入已验证的来源：美国财政部日度票面收益率曲线；FRED 宏观与标普 500、纳斯达克指数日收盘值、BEA 行业增加值、BLS 行业就业/工时/工资、工业生产和 EIA WTI 现货价；ALFRED 的 CPI、失业率、非农历史版本；French 美国及国际股票因子、12/49 行业收益和样本特征；Damodaran 长期资产回报与行业估值/利润率快照；Shiller 价格、股息、盈利与 CAPE；EIA 周度炼油总投入、可运行产能与利用率，以及原油、汽油、柴油周度现货价；SEC 财报、选定公司的管理层指引原文和炼油公司 10-K 业绩图总收益。历史财报专题使用各期 SIC 样本，不等于完整股票行业。FRED API key 放在项目根目录的 `.env`（`FRED_API_KEY=...`，不入库），`iros` 启动时读取；行业研究新增来源无需新 key。详见 [实现说明](docs/implementation.md)。

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

`.github/workflows/pages.yml` 在推送到 main、每个工作日 23:30 UTC 及手动触发时运行：测试 → 取得登记的公开数据 → 运行国债曲线、利率情景、曲线归因、长期资产、`us_industry_12` / `us_industry_49` 和两项 2025 年炼油研究 → `iros verify --all` → 归档到 `archive` 分支并恢复历史 → 生成静态网站 → 发布到 GitHub Pages。依赖可选来源的研究取得失败不阻断其他研究发布；任何必需步骤失败都不发布。四层专题 `us_industry_dossier`、`company_*` 公司研究、季度财报研究 `earnings_*` 和炼油投资对照 `us_refining_investment_2016_2025` 使用本地准备的财报与指引证据（或需要 SEC 联系邮箱），网站恢复其已验证档案，不在每次 CI 下载全部原始财报。线上更新时间、工作流徽章与「已过期」提示会显示更新停滞。

网站定位为研究门户，分工回答四个问题：

- **系统研究什么、从哪里进入**：首页列出有研究的对象卡片（大类资产、行业与产业链、公司）及其子类数量，另有搜索框和按问题的入口；点对象进入对象页，按子类、再按研究问题列出研究标题、一句结论与数据截止日，一项研究只在主归属处完整列出，其他子类用「另见」链接到对应章节。组合筛选在全部研究页（research.html），与首页共用一份[研究分类目录](docs/research-classification.md)：7 类对象、11 类问题可组合筛选，配对入口直接链接到当前结果章节或完整报告；每项研究只列一次。公司财报采用紧凑表格，数据能力、规划与参照单独显示，空查询明确说明尚无已发布匹配研究。搜索框里的多个词按词分别匹配；没有对应登记内容的词会列出并忽略。具体公司可按名称、中文名或别名查找，已登记关键人物的公司也可按人名查找（人名只作检索入口，职务以登记的出处日期为准）；选择主体后，可进入共用的业务与关系参照视图，筛选、对照并查看证据。
- **研究发现了什么**：每项研究有固定地址的研究页 `studies/<study_id>/`，按「研究问题 → 关键发现 → 可视化证据 → 方法 → 证据与限制 → 历史与复现」组织。关键发现由固定规则从结果生成，每条可展开查看所依据的指标。
- **这些发现有多可靠**：研究页的证据面板逐项列出来源与版本、日期与期限覆盖、核验与复现结果、限制，不汇总成笼统分数；数据覆盖条按日期显示缺失。`methods.html` 说明数据来源、时间规则、日历、可靠性机制与复现方法。
- **系统能研究什么**：`map.html` 研究能力地图由登记与运行记录生成，区分工程完成与研究验证；研究框架与规划中的方向在 `site/content.yaml` 维护。系统状态放在页脚与 `methods.html#status`，只有更新停滞时才在页面顶部提示。
- **研究依赖什么**：`lineage.html` 研究依赖图（只有中文，从「数据、方法与状态」页进入）从每项研究反向追溯到计算模块、数据集、取数模块与来源，列出来源出错会波及的研究、没有研究用到的模块与断链；每次构建由 `src/investment_os/lineage.py` 从研究定义、数据集登记与源码 import 静态读出，经本地中间文件的环节在 `config/lineage.yaml` 声明。
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

产业链登记：`iros chain naics`（导入 NAICS 2022）、`iros chain segments`（从已保存的 FSDS 提取分部事实）、`iros chain check`（核对 `config/supply_chain/` 的引用与证据）、`iros chain bundle`（生成并导入芯片证据包）、`iros chain relations`（生成并导入关系链证据包）；研究 `config/studies/chip_operations_p3b.yaml`、`config/studies/chip_relation_chain_nvda.yaml`、`config/studies/chip_relation_chain_intc.yaml`。

事件研究：`iros event fetch`（下载登记的申报原文）、`iros event check`（核对原文校验值、摘录与未提及检索词）、`iros event bundle`（生成并导入事件证据包）；研究 `config/studies/event_nvda_ceo_transition_2026.yaml`，见[事件研究设计](docs/study-events.md)。

季度财报研究：`iros earnings fetch`（下载登记的申报原文）、`iros earnings check`（核对原文校验值、数值出现在原文中、会计恒等式与摘录）、`iros earnings bundle`（生成并导入财报证据包）；研究 `config/studies/earnings_googl_2026q3.yaml`；每家公司的差异写在登记的 `profile`，新增公司的步骤见[季度财报研究设计](docs/study-earnings.md)。

研究依赖图：`iros lineage`（研究、模块、未使用与断链计数；`--study <id>` 打印一项研究的依赖链，`--md docs/lineage.md` 重写清单，`--check` 有断链时以状态 1 退出）。新增研究、数据集或模块后重写清单。

其他命令：`iros fetch --all`（全部定时数据集）、`iros sources`（已接入与候选来源及核验状态）、`iros datasets`（版本与质量概况）、`iros runs`、`iros import <dataset> <file> --declared-source "..."`（人工导入）。

```bash
uv run pytest
```

测试全部离线运行。

## 开发流程

本节是本项目的共享开发规则，Codex 与 Claude Code 都以此为准；各自的入口文件只引用这里，不另维护一套流程。

开始任务时，如有 `HANDOFF.md`，先读取；结束时如有待接手事项，更新该文件。执行方法卡时碰到方法本身的问题，记在该文件的「给方法库」一节。

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

- [芯片模块 P0](docs/study-chips.md)：分类、活动清单、分部事实、L3/L4 证据与研究单元盘点。
- [产业链研究完善方案](docs/supply-chain-research-design.md)：行业分类 → 细分业务 → 公司业务与财务 → 产业关系；包含免费数据门槛、行业模型适配、炼油与芯片对照及验收标准（**炼油段与投资对照已实现，芯片完成 P0 与 P3b，其余规划中**）。
- [当前架构与实施路线](docs/architecture.md)：设计基线（V0.3）
- [研究分类映射](docs/research-classification.md)：按研究对象 × 研究问题查找研究的分类原则、词表与现有研究映射（讨论草稿，尚未采用）
- [关系链研究设计](docs/relation-chain-design.md)：从已登记的直接关系逐层展开供应链、标注断点与敞口状态，首例为 NVIDIA 的上游与下游，第二例为 Intel（第一版已实现）
- [实现说明](docs/implementation.md)：代码结构、契约落地方式、如何扩展、已知限制
- [研究设计：美国主要资产的长期回报与风险](docs/study-long-run-assets.md)：1928 年以来七类资产的名义与实际回报、风险与相关性（已实现）
- [美国行业的经济、盈利与股票回报](docs/study-industries.md)：12/49 行业、历史 SIC 财报专题、估值与指引案例（已实现范围及明确的数据边界）
- [研究设计：国债曲线变化的分解](docs/study-curve-attribution.md)：第一项解释与归因研究，用会计恒等式拆分实际利率、通胀补偿与政策利率（已实现）
- [15 家公司年度财报研究](docs/study-companies.md)：现有样本的营收、利润率、现金流、资本开支、可比性及申报版本（已实现）
- [SEC EDGAR 财报数据设计](docs/edgar-design.md)：全部申报主体的财报事实、财年与申报版本、分区存储（草案，待审阅）
- [券商研报：私有原文与公开元数据分层方案](docs/research-report-private-view.md)：研报原文只放私有层，公开站点只引用元数据与自己的结论；含启动条件、分阶段计划与来源核对（规划，暂不实现）
- [事件研究：事件事实与时间线](docs/study-events.md)：登记事件的原文事实、披露时间与原文未提及的事项，首例为 NVIDIA 首席执行官离任（第一版已实现）
- [季度财报研究：Alphabet 2026 年第三季度](docs/study-earnings.md)：五个季度的报告口径收入、利润率、分部与现金流，可比性限制、资本开支展望对照与未覆盖项，首例为 Alphabet；按登记的 profile 配置，可新增任意公司（已实现）
- [研究报告图块：风格与写法](docs/note-figures.md)：给网站中文报告加图，数字只引用公开走查记录字段；结论式标题、证据级别标签、展望值虚框、不画双轴与不相加量的堆叠，另有产业链图型：收入结构条、层次 × 时态矩阵、供应商依赖斜率图（NVDA FY27 Q3、AAPL 产业链、GOOGL Q3'26 已实现）
- [股票群组研究：新股与热门股](docs/study-stock-cohorts.md)：按规则筛出的股票群组在不同市场状态下的后续表现；分类位置、共用的市场状态定义（事前与事后分开）、数据可得性与幸存者偏差、分阶段计划（设计草案，个股日价来源未选定，未实现）
- [研究方法提取模块](methodology/README.md)：从公开研究中提取可复用分析方法的独立实验区，不接入研究体系与网站（初版，只有文档）
- [研究依赖清单](docs/lineage.md)：每项研究的依赖链、模块被多少研究用到、来源出错波及的研究、没有研究用到的模块与断链（`iros lineage --md` 生成）
- [历史方案索引](docs/archive/README.md)：保留 A、B、C 原始文档及 V0.2，追溯设计来源与定位变化。

历史方案与当前框架有差异时，以当前框架为准。当前文档的修订说明记录本次取舍，Git 用于保存后续版本历史。

## 公开边界与研究报告

本仓库及站点公开。`notes/companies/` 只收已放行的**可读报告**副本，不收私有 results、原件、个人持仓、用户专属判断或动作。公开公司数字、计算及标注的【推断】允许出现在报告中；它们不因此获得 study 的固定输入复现或审计徽章。方法卡正文、私人资料、凭证、邮箱及本机绝对路径仍不得进入提交。

```bash
uv run iros notes import REPORT.md
uv run iros notes check
```

输入必须是 `companies/<TICKER>/reports/<report-id>.md`，公司在 `config/notes.yaml` 登记。不得用 results 冒充报告或通过符号链接导入；先与原 owner 确认已放行、已推送的修正版。工具只做确定性清洗：已知 research-os 记录路径转成与公开跟踪分支字节一致的 GitHub 链接；私有 result 指针转成纯结果 ID；报告间引用按下面的规则换链接。未知路径、私有仓库链接、未核验的其他 GitHub/GitLab 等代码仓库链接、邮箱、key、用户专属字样（含第十节）或危险/不支持的内容残留时拒绝写入，不擅自删除分析段落来过关。拒绝诊断仅给类别与行号，不回显敏感片段。

**报告间引用。** company-dossiers 的结果有 `builds_on`（依赖另一份结果）和 `see_also`（相关）两种引用，报告里因此会出现指向其他报告或结果的相对链接（例如 `../../INTC/reports/<结果 id>.md`），可以跨公司。导入时逐个处理：

- 被引用的报告**已发布**（`notes/companies/<代码>/<日期>/<id>.md` 已在本仓库）：改成站内相对链接 `../../../<代码>/<日期>/<id>/`，即网站上那份报告页；锚点去掉。
- 被引用的报告**未发布**，或指向结果文件（`results/`）、公司索引等其他私有文件：去掉链接，只留纯文本，如 `INTC Q3（见 INTC-20261114-q3-26，未公开）`；没有结果 id 的写成 `链接文字（未公开）`。
- 指向本仓库走查记录（`methodology/records/`）的链接本来公开，转成固定提交的 GitHub 链接保留。

指向私有仓库的网址不改写，留给边界检查拒绝。站内报告链接在构建时还要核对目标报告确在本次发布中，否则引用方记作 `unresolved_note_link` 不发布。所以先导入被引用的报告，再导入引用它的；被引用的报告后来才发布时，重新导入引用方即可换成链接。

报告保存在公司/日期目录，渲染 Markdown 标题、表格、列表与引用；原始 HTML 和图片不接受。图表不写进正文，由本仓库 `config/note_figures/<报告 id>.yaml` 引用公开走查记录字段生成，见 [docs/note-figures.md](docs/note-figures.md)。自动引文门槛为累计 25 个英文词或 100 个汉字，超过即标作 `long_quote_review`、拒绝自动发布，需原 owner 改为摘要或另外完成有依据的人工版权审阅；没有自动绕过开关。此保守检查不能替代出处、许可与完整内容审阅。

报告页及公司/日期目录页为中文，设置 `<meta name="robots" content="noindex">`，不会因记住英文语言而重定向到不存在的译页。全部研究、公司页、公司/关键词/报告日期筛选可找到报告（报告入口使用 nofollow），但报告数量与可复现 study 数量分开。构建时逐份重新检查：失败副本不进入页面或目录，其他已放行内容照常发布；失败原稿也不得加入 git 提交。提交前仍须检查完整 diff 并运行 `iros notes check`。发布页面中不得有指向 company-dossiers 或 research-method-extraction 的链接或本机路径：网站工作流构建后运行 `iros notes check --site _site`，扫描所有页面的链接属性与报告页正文，命中即停止发布；本地构建后也可同样运行。

**不主动索引不是保密。** 报告与公司/日期目录以页面 `<meta name="robots" content="noindex">` 请求搜索引擎不索引；入口 nofollow 仅为补充，不是访问控制。GitHub 项目子路径的 `robots.txt` 不在域名根，不能作为有效爬虫策略，因此不再生成。不要在域名根为 notes 添加 Disallow，以免阻止爬虫读取页面 noindex。链接与 GitHub 中的 Markdown 仍可公开访问，noindex 不能保证搜索引擎绝不列出，也不能阻止他人保存、分享链接。
