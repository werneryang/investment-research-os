# 券商研报：私有原文与公开元数据分层方案

> 状态：**规划（2026-11-02），暂不实现**；待研报积累到启动条件后再按阶段推进。
> 范围：券商与第三方研究机构的研报原文管理，以及公开站点可引用的结论。
> 相关文档：[架构](architecture.md) · [实现说明](implementation.md)。

## 目标

研报原文只在本机可见；公开站点只展示元数据和自己写的结论。两条链路互不相通。

## 为什么要分层

多数券商和研究机构（如 Morningstar、Argus、CFRA）的使用条款只允许个人阅读，禁止再分发，部分还禁止自动化抓取或 AI 处理。把原文放进 Google Drive 并不改变许可范围：私人存放通常属个人使用，共享链接或经项目间接展示则属再分发。本方案不构成法律意见；若项目对外发布或商业化，应重新核对各家条款。

## 三层结构

| 层 | 内容 | 位置 | 可上公开站 |
| --- | --- | --- | --- |
| 私有层 | 研报原文 PDF 与截图 | 私人 Drive 或本地目录，不进 git | 否 |
| 本地层 | 私有网页：打开原文、查看笔记 | 本地生成，输出到仓库外，只绑 `127.0.0.1` | 否 |
| 公开层 | 券商、日期、标的、评级、目标价、自己写的摘要、文件哈希 | `config/` 登记，经现有站点与 `archive` 流程发布 | 是 |

## 启动条件

满足任意一条即开工，不必等到"很多"：

- 积累十来份以上研报，开始需要在原文与结论之间来回查。
- 同一标的有两家以上券商的报告，需要并排比较。
- 研究开始引用研报结论，需要可追溯的出处。

## 阶段

**阶段 0：现在就做（零代码）**

- 原文放私人 Drive 或本地目录，不共享。
- 文件名统一为 `券商_标的_日期_类型.pdf`，便于日后导入。
- 每份报告记一行：券商、日期、标的、评级、目标价、一句话摘要；先用表格或 YAML。

**阶段 1：定约定**

- 元数据字段白名单：券商、日期、标的、评级、目标价、摘要（自己写）、文件路径加哈希。
- 原文目录放在仓库外，或加入 `.gitignore`。
- 写明哪些字段可进公开层，哪些不可。

**阶段 2：公开层**

- 元数据登记进 `config/`，研究文档可引用"某券商某日评级"。
- 只取白名单字段，显式拒绝其他字段。
- 若改动 `registry.py` 或 `contracts.py`，按 README「开发流程」走 PR 审查。

**阶段 3：私有本地视图**

- 独立脚本，读元数据与私有目录，生成只给自己看的页面；不并入 `iros site`，避免触碰公共契约，也避免配置失误被部署。
- 输出到仓库外，绑 `127.0.0.1`，不进 CI，不进 `archive` 分支，不参与 Pages 部署。
- 页面可点开原文，按标的与券商筛选。

**阶段 4：校验（可选）**

- 公开层引用的哈希都能在私有目录找到。
- 公开产物中不出现私有路径或原文片段。

## 不做的事

- 不抓取、不批量导入研报全文。
- 不用 Drive 共享链接分发。
- 不把私有视图并进现有站点生成器。

## 研报来源核对（截至 2026-11-02，网搜核对，部分来自评测站）

| 券商 | 可确认 | 存疑或需更正 |
| --- | --- | --- |
| Fidelity | LSEG（原 Refinitiv：I/B/E/S、StarMine）；Argus、Zacks 有较弱来源 | MSCI 多为 ESG 数据而非研报，未确认 |
| Schwab | Morningstar、Argus、CFRA；自家 Schwab Equity Ratings | Credit Suisse 无来源支持，且已于 2023 年被 UBS 收购 |
| E*Trade | Morgan Stanley 研究；评测站提到 Argus、TipRanks 等 | — |
| WellsTrade | Wells Fargo Investment Institute、Morningstar | Wells Fargo Securities 研报为机构侧；年费 $30 仅第三方提及，官方页未见 |
| Merrill Edge | BofA Global Research、CFRA、Morningstar | — |
| Ally Invest | — | Morningstar、CFRA 未找到来源 |
| Citi Self Invest / JPM Self-Directed | — | 研究内容、开户条件均未核实；JPM 完整研报在 J.P. Morgan Markets，零售自助账户是否可见未确认 |
| IBKR | 以订阅制第三方研究为主（CFRA 合作为 2019 年报道） | 现状未确认 |

开户前以各券商官网的研究提供方页面和费用表为准。

## 其他获取路径

- 图书馆与学校：公共图书馆数据库（Morningstar、Value Line、Capital IQ）、大学或校友账号（Bloomberg、FactSet、LSEG Workspace）、Investext 类聚合库。
- 直接订阅：Morningstar Investor、Argus、CFRA、Value Line、Seeking Alpha。
- 发行人付费研究：Zacks SCR、Edison 等（存在利益冲突，引用须标明）。
- 免费聚合与一手资料：Yahoo Finance、TipRanks、MarketBeat、Finviz、公司 IR 页面、SEC 文件、财报电话会议记录。
- 机构与专业平台（付费）：AlphaSense、Smartkarma、Visible Alpha。
