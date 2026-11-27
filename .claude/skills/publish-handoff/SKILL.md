---
name: publish-handoff
description: 接收别的会话交来的发布任务，把一项季度财报研究或一份已放行的公司报告（notes）发布到 investment-research-os 网站：公开边界检查、在干净提交上重跑并核验、单独归档这一次运行、合并推送 main、核实部署和线上页面，再回报结果。company-dossiers 的 earnings-update 第 6 步、研究流程第 7 步放行后交来的消息都用它。只在 investment-research-os 的写入会话里用；新增研究的计算和登记本身不在这里做。
---

# 接收发布交接

上游会话（通常是 company-dossiers 的 earnings-update）已经在本仓库写好了文件、跑过研究，但它不是本仓库的写入者，不提交也不推送。本 skill 是交接的接收方：核对、提交、归档、合并、推送，然后核实线上页面。

规则以 README「开发流程」和「公开边界与研究报告」、`docs/study-earnings.md` 第 8 节为准。本文件只写顺序和容易漏的地方；三者不一致时以它们为准，并在 HANDOFF 里记一条。

## 第 0 步：接手前

1. 读 `HANDOFF.md` 和 README「开发流程」。
2. 确认本仓库只有这一个写入会话。上游会话可能还开着，只要它不提交、不推送就没问题；如果另有会话在本仓库提交，就停下来问用户。
3. `git fetch`，确认 `main` 与 `origin/main` 同步。记下工作区里有哪些未提交的改动：上游留下的文件就是这次要发布的；不认识的改动不碰，问清楚是谁留的。
4. 从交接消息里列出这次的清单，缺一项就回问上游，不猜：
   - **季度研究**：走查记录路径、`config/earnings/<id>.yaml`、`config/studies/earnings_<id>.yaml`、研究 id、上游跑出的运行 id、`site/content.yaml` 与 `site/en.yaml` 是否已登记。
   - **公开报告**：报告 id、公司代码、company-dossiers 里放行这一版的**已推送提交号**。

两类可以一起交来。都有时先发季度研究，再导入报告：报告的图块要读公开走查记录，那份记录要先在 main 上。

## 第 1 步：公开边界检查

对要提交的每个文件都查一遍（`git diff` 加上未跟踪的文件）：

- 没有方法库卡的正文和出处判定，只写卡 id 和步骤号。
- 没有个人判断、持仓、论点、目标价，也没有「你的判断」或第 10 节的内容。
- 没有邮箱、本机绝对路径（`/Users/…`、`~/…`）、key 或 token（`.env` 里的值都不能出现）。
- 没有指向 company-dossiers、research-method-extraction 的链接。
- 没有第三方研报、电话会的大段原文。

可以先用 grep 粗筛，比如 `grep -nE '@[a-z0-9-]+\.[a-z]|/Users/|api[_-]?key|company-dossiers|research-method-extraction'`，命中的逐条看。有问题就退回上游去改，本会话不擅自删掉分析段落来过关。

## 第 2 步 A：季度研究

1. `uv run iros earnings check`，必须零错误。
2. 建功能分支，提交登记、研究定义、走查记录和 `site/` 的改动。改动碰到 `registry.py`、`contracts.py`、`analytics/`、`research/` 时走 PR，否则在本地合并（README「开发流程」）。
3. **在干净的已提交状态下重跑**。上游的运行通常是在未提交的工作区里跑的，manifest 的 `dirty` 为 true，不能拿来发布。
   - 依次运行 `uv run iros earnings bundle`、`uv run iros run config/studies/earnings_<id>.yaml`。
   - 确认 `runs/<run_id>/manifest.json` 里 `dirty` 为 false，提交号就是刚才那次提交。
   - `uv run iros verify <run_id>` 必须报告复现一致。
   - 重跑的结果要与上游的运行对照：结果哈希或关键指标一致。不一致就停下，回报差在哪里。
4. **只归档这一次运行**。`iros archive save` 不能按研究筛选，会把本机所有没归档的运行一起带上，所以要从隔离目录里归档：
   - `git worktree add <临时目录>/archive origin/archive`。
   - 另建一个临时根目录，只复制 `config/`、`runs/<run_id>/` 和 `reports/<study_id>/<run_id>/` 进去。
   - `uv run python -c "from pathlib import Path; from investment_os.archive import save; print(save(Path('<临时根目录>'), Path('<临时目录>/archive')))"`，返回的记录必须只有这一个运行。
   - 在 archive 工作树里提交，再 `git push origin HEAD:archive`，记下 archive 的提交号。
   - 临时目录放在 scratchpad 里，用完删掉 worktree（`git worktree remove`）。
   - **先归档，再合并 main**：合并触发的部署会把档案恢复出来。顺序反了，这次部署就看不到新运行。
5. 合并：`git switch main`，`git merge --no-ff <分支>`，`uv run pytest`（约 3 分钟，放后台跑）。通过后推送 `main`。走 PR 的，用 `gh pr merge --merge` 合并，再更新本地 `main`。

## 第 2 步 B：公开报告（notes）

1. **只导入原 owner 已推送的那一版**，不读 company-dossiers 的工作区。把固定版本导出到临时目录，并保留目录结构，因为导入工具要求路径是 `companies/<代码>/reports/<id>.md`：
   `git -C ../company-dossiers show <提交号>:companies/<代码>/reports/<id>.md > <临时根目录>/companies/<代码>/reports/<id>.md`
2. 新公司要先在 `config/notes.yaml` 登记代码、CIK 和名称。
3. 报告引用了别的报告时，先导入被引用的那份（README「报告间引用」）。被引用的报告还没发布就保持纯文本，等它发布后再重新导入引用方。
4. `uv run iros notes import <临时路径>`，再运行 `uv run iros notes check`。
   - 被拒绝时按诊断类别退回原 owner 去改。没有绕过的开关。
   - 标了 `long_quote_review` 的（引文超过 25 个英文词或 100 个汉字），要原 owner 改成摘要。
5. 需要图块时写 `config/note_figures/<报告 id>.yaml`，只引用公开走查记录的字段，写法见 `docs/note-figures.md`。
6. 本地构建到一个新目录，再扫描私有链接：
   - `uv run iros site --out <临时目录>/site`
   - `uv run iros notes check --site <临时目录>/site`
7. 按普通改动合并：建分支、提交、`merge --no-ff`、跑 `pytest`、推送 `main`。

## 第 3 步：核实上线

推送成功不等于发布成功，下面每一项分别核实：

1. 找到这次推送触发的那次运行，等它结束：先 `gh run list --workflow pages.yml --branch main -L 1`，再在后台运行 `gh run watch <id> --exit-status`。失败就读日志，在授权范围内修复；修不了就回报卡在哪一步。
2. 打开线上页面（用内置浏览器）：
   - **季度研究**：中文页 `https://werneryang.github.io/investment-research-os/studies/<研究 id>/` 和英文页 `…/en/studies/<研究 id>/` 都能打开，指向这次的运行，显示新季度；首页公司卡片的「公司季度财报」一行出现这家公司；按公司名和代码都能搜到。
   - **报告**：报告页和公司/日期目录页能打开，带 `noindex`；按代码、公司名、日期能筛选到；页面里没有指向私有仓库的链接。

## 第 4 步：回报

- 回报给交接方：有会话就用 SendMessage 发给它，否则写在回复里。要写清：
  - main 的合并提交号、archive 的提交号（季度研究才有）、Actions 运行链接、页面链接。
  - 或者卡在哪一步、为什么。
- 发布状态有需要别人接手的事，就在 `HANDOFF.md` 对应的条目下记结论，并随这次的改动一起提交。
- 技术复核写「技术复核，未经人工」，不写成已确认。
