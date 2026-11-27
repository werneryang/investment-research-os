---
name: method-replay
description: 在 investment-research-os 里对一张方法卡做执行实测（历史事件回放、复现或用到一家公司），写成 methodology/records/ 下的走查记录；或对已有走查记录做技术复核（事实核对和语义核对）。用户说“回放/执行/实测这张卡”“复核这份记录”时用。方法卡本身在 research-method-extraction，本 skill 只读它；改卡、登记缺口和执行条目由方法库的会话做。不用于季度财报研究的登记和发布（那是 earnings-update 和 publish-handoff）。
---

# 方法卡执行实测与技术复核

两种用法：**执行**一张卡，写一份新记录；**复核**一份已入库的记录，在记录末尾追加复核一节。两种都只写本仓库的 `methodology/records/`、`scripts/`、`tests/` 和 `HANDOFF.md`。

本仓库公开。记录里只写卡 id 和步骤号，不抄卡的正文，不写出处判定、个人判断、邮箱、本机路径和 key。

## 共同的准备

1. 读 `HANDOFF.md`、README「开发流程」、`methodology/records/README.md`（分层和入库前检查）。
2. 读 `../research-method-extraction/ai-tools.md`，按任务选工具。只读，不复制进本仓库。
3. 确认方法库已提交（`git -C ../research-method-extraction status --porcelain` 为空），记下它的短提交号，写进记录里卡 id 的后面，例如 `capex-boom-credit-transition（方法库 1c2bb95）`。
4. 读方法卡（只读），列出它的步骤、所需数据和输出格式。

## 执行

### 1. 定范围

- 事件、观察时点（T1、T2……）和每个时点的预期层级或预期结论，在取数**之前**写下来，免得看到结果再改预期。
- 用户已有的决定照着做。例如：判定只按作者的步骤做，卡里「整理时补充」的指标只作旁证（2026-11-26）。
- 卡上写的数据没有公开免费来源时，先记为缺口并告诉用户，不擅自换成别的来源。用户选了来源再补取、重跑。

### 2. 取数和计算

- 能重复用的取数和计算写成 `scripts/<名称>.py`，同时写测试 `tests/test_<名称>.py`（离线运行）。
  - 缓存放在 `data/<名称>/`，不入库。
  - 支持 `--offline`，只用缓存重算。
  - methodology 不接入研究体系，不在 `config/datasets.yaml` 登记新数据集。
- 一次性的计算可以只留在本机，但记录里要写明输入文件和它们的 SHA-256，复核时才能重跑。
- 许可不允许再分发的数据（用户手动下载的、ICE 等）只放在本机。公开输出只留百分比、比值或汇总值，记录里注明「只在本机」。

### 3. 时点

每个时点只用当时已公开的信息判断，事后的数据另列，只用来对照。每个数字都标 `availability`：

| 标注 | 含义 |
| --- | --- |
| `contemporaneous` | 当时已公开 |
| `contemporaneous_lagged` | 当时公开，但晚于该时点 |
| `post_hoc_disclosure` | 事件当时存在，后来才公开 |
| `post_hoc_estimate` | 后人汇编或估计 |
| `post_hoc_vintage` | 会修订的序列没有当日版本，用当前版本按发布滞后截断 |

会修订的序列（ALFRED 有版本的）取时点当日的版本。

### 4. 写记录

- 文件名 `<来源>-<标的或主题>-<YYYYMMDD>.yaml`，从 `methodology/records/_template.yaml` 起头，可以参照已有的回放记录。
- `method_output.steps` 里每一步写这几项：
  - `output`：照卡的输出格式写。
  - `reached`：走完、部分走完或走不下去。
  - `first_guess`：第一处要猜的地方。
  - `card_vs_added`：哪些来自卡，哪些是执行时补的。
  - `consistent_with_expected`：结论是否与预期一致。
- 另写 `point_in_time.rule`、`data_gaps` 和 `quality_notes`（口径、覆盖范围变化、OCR 出入）。
- `extraction.review` 照实写，没复核就写「未复核」。

### 5. 交给方法库

- 卡本身的问题（步骤写不清、口径缺失、两张卡冲突、某步不适用）记在 `HANDOFF.md`「给方法库」，每条一行：`- [未处理] 日期 · 卡 id（方法库 提交号）· 第几步 · 问题一句话 · 记录路径`。
- 方法库 executions 条目的草稿交给 research-method-extraction 的会话（用 SendMessage 发给正在跑的会话，或开一个在那个仓库的会话），本仓库不写。
- HANDOFF 里给这次实测记一项：记录路径、结论、缺口、要回看的日期（有前瞻登记时写）。

## 技术复核

最好在另一个会话里做，复核者不参与执行。即便如此也是同一个模型，不算独立的人员复核，记录里要这样写。

1. **不改写原记录**。在文末追加 `technical_review` 一节，写上：`reviewed_on`、`reviewer`、`human_review: "未做；可选。"`、`scope`。
2. **事实核对**（`fact_check`）：
   - 输入文件的 SHA-256 与记录一致。
   - 用同一批输入离线重算，输出与入库的汇总值逐字节相同。
   - 手工录入的数字回原文逐个找到。
   - 用了版本数据的，逐个确认没有超前。
3. **文献**：定性来源要读正文，不能只核书目。出处页码写进复核一节。
4. **语义核对**：
   - 每一步的推导确实来自卡的步骤。
   - 证据撑得住结论。
   - 没有事后信息混进时点判断。
5. 写明更正、`not_checked`（没核到的条目）和留给用户的判断（列出选项，不替用户定）。用户定了以后把结论补进同一节。
6. 把记录的 `review` 字段改成 `技术复核 <日期>（见文末 technical_review）；未经人工核对`。复核状态只能写「技术复核」，不能写成 `confirmed` 或「已确认」，那是人工签认。
7. 「给方法库」加一条，请方法库把 executions 的复核状态同步为技术复核。

## 入库以后

- 记录入库后不改写。
  - 补了数据重跑的，追加 `rerun_supplementary` 一节。
  - 后来核到的更正，追加 `technical_review_addendum` 一节。
  - 要换掉整份内容（例如图块读的归类），就新建一份记录，用 `supersedes` 指向旧记录并写上旧记录的哈希，旧记录原样保留。
- 提交按 README「开发流程」走普通改动：建分支、`merge --no-ff`、跑 `uv run pytest`、推送 `main`。推送前按公开边界再查一遍 diff。
