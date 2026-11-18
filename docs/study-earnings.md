# 公司季度财报研究（可配置，首例 Alphabet，2026-11-17）

对应研究分类「基本面与经营 · 财务指标」与「数据可得性与口径 · 可比性」（[研究分类映射](research-classification.md)）。首例是 Alphabet 2026 年第三季度（`earnings_googl_2026q3`）；任何公司都用同一分支，公司之间的差异（季度列、分部、会计恒等式、页面行与图表、关键发现措辞）写在登记的 `profile` 里，代码不点名公司（[新增一家公司](#8-新增一家公司)）。页面结构参照年度研究 `company_alphabet`：研究问题 → 关键发现 → 可视化证据 → 方法 → 证据与限制 → 历史与复现。

## 1. 回答什么

最新一个季度的收入、利润率、分部经营、现金流与资本开支，相对去年同期和上一季度如何变化；这些变化有多大程度可以直接比较；哪些部分发行人没有披露，所以不能下结论。页面放五个季度（2025 年第三季度至 2026 年第三季度）的报告口径数据，以及资本开支展望与实际的对照、收入积压订单、恒定汇率对账和可比性说明。

不回答：有机增长（发行人没有披露并购与 TPU 系统销售的收入桥）、正常化盈利、电话会内容、股价反应、估值、预测或任何投资判断。

## 2. 为什么新增一项研究而不是扩展 `company_alphabet`

`company_alphabet` 是 15 家公司年度研究的一部分：期间是财年、证据包是 `company_sec_facts`、每家公司的 15 条指标与「同一申报内计算」的规则都按年度设计。把季度数据塞进去会改变已归档运行的实质内容和复现输入，也会让「财年」与「季度」两种期间混在一个分支里。新增一项季度研究（新分支 `earnings_quarter`、新证据包 `earnings_evidence`）不改动任何已有研究的结果，`iros verify --all` 与归档约定都沿用事件研究的先例；年度页与季度页互相链接。

## 3. 流程

```bash
uv run iros earnings fetch
```

```bash
uv run iros earnings bundle
```

```bash
uv run iros run config/studies/earnings_googl_2026q3.yaml
```

| 步骤 | 做什么 | 在哪里 |
| --- | --- | --- |
| 1 登记 | 逐期写合并利润表、分部、现金流与资产负债表数值；展望摘录；可比性说明；覆盖分类 | `config/earnings/<earnings_id>.yaml` |
| 2 取得原文 | 下载登记的 10-Q、10-K 与 8-K 附件 99.1 | `iros earnings fetch`，存于 `data/earnings/filings/`（不入库） |
| 3 核对 | 原文 SHA256 一致；每个数值出现在所引原文中；会计恒等式成立；文字摘录逐字出现在原文中 | `iros earnings check` |
| 4 证据包 | 核对零错误才生成，导入 `earnings_evidence` | `iros earnings bundle` |
| 5 研究 | 推导第四季度、算利润率与同比环比、对照展望、生成关键发现 | 分支 `earnings_quarter` |

## 4. 口径

- **报告口径。** 全部数字按 GAAP 报告，含并购并表，不是有机增长；恒定汇率只去除汇率与套期，不去除并购或产品组合影响。
- **第四季度是推导值。** 申报中没有第四季度，2025 年第四季度 = 2025 年全年（10-K）− 前三季度比较数（当前 10-Q）。与当时新闻稿的直接季度值收入相差 100 万美元，原因未确定，不补平；页面标「*」。
- **现金流。** 季度经营现金流与现金资本开支取自第三季度新闻稿（8-K 附件 99.1）的季度表；2025 年第三季度取自当时的新闻稿。自由现金流按发行人定义（经营现金流减购置固定资产的现金支出），与披露值核对一致。
- **同比与环比。** 同比对 2025 年第三季度，环比对 2026 年第二季度；基数非正时不算。利润率变化用百分点。
- **分部分解。** 分部营业利润同比变动合计等于营业利润变动，只是算术分解，不区分 TPU 销售、服务消耗、价格或规模效应。
- **示意性的税前算术。** 税前利润剔除权益证券损益；去年同期营业利润加回约 35 亿美元的欧盟相关费用。不是正常化盈利，不含税率调整，不是预测。
- **展望对照。** 点值展望没有定义容差，只列实际与点值的差；区间展望判断实际是否在区间内；2026 年全年尚未到期。「剩余额算术」是二月区间减前三季度现金资本开支，不是第四季度指引。
- **覆盖分类。** 已完成、数据不足（发行人没有披露或没有可核验数据）、需人工判断（算术之外的判断或本研究未处理的外部材料）。后两类不给结论。

## 5. 核对的强度与限制

- 「数值出现在所引原文中」是存在性检查：把数值按千分位格式在原文纯文本中搜索，不证明它取自正确的行与列。真正限制取错值的是第二项检查——会计恒等式（收入由产品线合成、分部营业利润合计等于营业利润、营业利润加其他收支等于税前利润、税前利润减所得税等于净利润、净利润减优先股股息等于普通股可得净利润；经营现金流减资本开支等于发行人披露的自由现金流）。恒等式对缩放不变，也不能发现同步取错整列的错误。
- 准备阶段（2026-11-16，走查任务 R-20261116-googl-earnings）另有一次独立的原文复算，记录在 [methodology/records/sec-googl-earnings-20261116.yaml](../methodology/records/sec-googl-earnings-20261116.yaml)；本研究的五个季度数值与该记录逐项一致（重算时核对，见第 7 节）。没有逐条人工审阅原文。
- 原文只保存在本机，CI 不重新下载；网站显示的是已归档的运行。重新核对需要先 `iros earnings fetch`（需要 `.env` 中的 `SEC_USER_AGENT`）。
- 2026 年第三季度新闻稿（8-K 附件 99.1）的 EDGAR 接受时间没有记录，登记中用发布日 2026-10-28 作为披露日。
- 业绩电话会的逐字稿使用条款未核清，没有读取；行情反应需要可展示的日度价格来源，尚未选定。

## 6. 与其他仓库的分工

本仓库只放公开 SEC 披露的事实、可复现的计算与限制。个股判断、论点与估值写到 company-dossiers；找分析方法在方法库（research-method-extraction）的会话里查。本研究的覆盖分类里「需人工判断」的项目不在本仓库处理。

## 7. 首次交付核对（2026-11-16）

- **登记核对**：`iros earnings check` 零错误：原文 11 份校验值一致，203 个登记数值出现在所引原文中，51 条会计恒等式成立（6 个利润表期间各 7 条、第四季度推导 7 条、自由现金流 2 条），14 条文字摘录逐字出现在原文中。
- **基线运行**：`earnings_googl_2026q3-20261117T015633Z-76029f21`，代码 1581dab，dirty=false，状态 partial（有数据不足与需判断的项目，按设计）；`iros verify` 以固定输入重算结果校验值一致（df9abb69…）。
- **与走查记录逐项对照**：五个季度的 9 项占比与利润率、现金流与净利润比、同比与环比的 10 项增速、3 项利润率变化、2 项现金流变化，以及示意性的剔除算术，共 82 项重算值与 [走查记录](../methodology/records/sec-googl-earnings-20261116.yaml) 中的计算值全部一致（容差 1e-9）。
- **归档**：该运行单独归档到 `archive` 分支（7959396），之后合并 main，由部署恢复。
- **测试**：`uv run pytest` 434 项通过（新增 `tests/test_earnings.py` 20 项，覆盖登记核对的拒绝情形、证据包、研究计算、页面与英文、状态与公开边界）。
- **限制**：技术复核由模型完成，与登记同一会话，不是独立复核，也不是人工签认；没有逐条人工审阅原文。

### 配置化后的核对（2026-11-17）

- **登记迁移**：`config/earnings/googl_2026q3.yaml` 增加 `profile`（取代此前写在代码里的季度列、科目、恒等式、分部与页面行）；`iros earnings check` 的计数与迁移前相同：原文 11 份、数值 203 项、恒等式 51 项、摘录 14 条。
- **与首次交付的归档运行逐字段对照**（`earnings_googl_2026q3-20261117T015633Z-76029f21` 对新运行 `…T134238Z-7a6180b9`，代码 a95bbb4，dirty=false，`iros verify` 复现一致）：`results` 里的五个季度全部指标、同比环比、分部分解、示意算术、资产负债表、积压订单、展望对照、可比性说明与覆盖分类全部相同；不同的只有重命名的键（`cash.nine_months` → `year_to_date`、`ttm` → `trailing`、`remaining_2026_arithmetic` → `remaining_arithmetic`，数值逐项相同）、新增的 `profile` 与积压订单确认期限的说明文字，以及关键发现规则 v1 → v2（六条发现的文字与证据数值相同，只有证据键名 `cloud_*` 改为 `segment_*`）。
- **旧运行不能再用新代码复现**：关键发现规则的指纹是结果校验值的一部分，规则代码改了，旧运行的校验值就不可能不变；旧证据包也没有 profile。所以 Alphabet 重新运行并归档（archive 分支），旧运行留在档案里，`iros verify --all` 对它如实报 `[error]`（无法重算）并继续。
- **页面**：中英文页面与改前逐段对照，除运行编号、规则版本、证据键名、历史表多一行，以及来源段落「发布第三季度业绩」改为「发布 2026 年第三季度业绩」外没有差别。
- **测试**：`tests/test_earnings.py` 另用一家结构不同的虚构公司（两个分部、没有 Other Bets、优先股与套期，财年止于一月下旬的 52/53 周财年，没有展望、积压订单、恒定汇率、每股收益与示意算术）跑通 check、bundle、研究计算、页面、英文、文字报告与关键发现，并覆盖 profile 的 20 种错误。

## 8. 新增一家公司

不改代码：每家公司一份登记和一份研究定义，命名 `config/earnings/<ticker>_<fy><q>.yaml`（如 `nvda_fy27q3`）与 `config/studies/earnings_<ticker>_<fy><q>.yaml`（study_id 同名，`method.earnings` 指向登记的 `earnings_id`）。分支 `earnings_quarter` 只读登记里的 `profile`，经证据包进入结果（`results.profile`），关键发现、页面、英文与文字报告都按它生成。

**步骤**

1. 在 SEC EDGAR 找到该公司的 10-Q/10-K 与业绩新闻稿（8-K 附件 99.1）。先在 `config/earnings/` 复制最接近的登记作模板，写 `documents`（accession、接受时间、URL、本地文件名；SHA256 等下载后填）、逐期 `income`（每个科目的数值；金额取绝对值能在原文中按千分位找到）、`cash_flow`、`balance`、`notes`、`coverage`，以及可选的 `issuer_fcf`、`rpo`、`fx`、`per_share`、`annual_cash_ppe` + `guidance`。
2. 写 `profile`（下表）。**会计恒等式是防止取错值的主要检查**：至少写出合成收入、营业利润、税前利润、净利润的恒等式，分部要有「分部营业利润合计 = 营业利润」。
3. `uv run iros earnings fetch`（需要 `.env` 中的 `SEC_USER_AGENT`）下载原文并核对；用 `shasum -a 256` 把 SHA256 填进登记。`iros earnings check` 零错误才往下：它会列出 profile 的结构问题、值不在原文、恒等式不成立、摘录不逐字、双语文字不全。
4. 与走查记录逐项对照（方法同 [第 7 节](#7-首次交付核对2026-11-16)：重算的占比、利润率、同比与环比、现金流转换与走查记录里的计算值全部一致）。
5. `iros earnings bundle`、`iros run config/studies/earnings_<id>.yaml`，在干净的已提交状态下运行（manifest 的 dirty 为 false），再 `iros verify <run_id>` 复现一致。
6. 研究定义的 `limitations` 写这家公司的真实限制；`site/content.yaml` 登记研究（参照 `earnings_googl_2026q3`：`label`、`home_group: 公司季度财报`、两条 routes、`entity_ids`、`study_order`），`site/en.yaml` 补该公司专有文字的英文（登记里的双语文字不需要）。
7. 放行时只归档这一次运行：从只含该运行的隔离目录执行 `iros archive save`，推送 `archive` 分支，再合并 main（部署会恢复它）。合并和部署分别核对；线上页显示新季度、首页公司卡片出现入口。
8. 个股判断、论点与估值不写在本仓库，写到 company-dossiers。

**`profile` 字段**（`iros earnings check` 校验；googl 登记是完整的示例）

| 字段 | 内容 |
| --- | --- |
| `short_name` | 页面句子里的公司简称 |
| `quarters` | 页面各季度列，从旧到新（至少 3 个）：`id`、`label`、`end`（任意日期，支持 52/53 周与非日历财年）、中英文 `name`；没有直接披露的季度写 `derive: {total, less, method, note}`（全年减前几季度，`total`/`less` 是 `income` 里的期间 id，`note` 是页面脚注） |
| `current` / `yoy_base` / `qoq_base` | 本季度、同比基数、环比基数（`quarters` 里的 id） |
| `year_to_date` / `trailing` | 可选：年初至今的现金流期间（含所含季度、中英文 `label`、`short`）与近四季度现金流期间 |
| `fcf_deduct_principal` | 可选布尔值，默认 `false`：`true` 时，FCF = `cfo − cash_ppe − cash_ppe_principal`，并要求每个现金流期间（包括年初至今与近四季）显式登记相关本金支出及其来源；购置支出和本金的中英文标签填在 `metrics.cash_ppe` 与 `metrics.cash_ppe_principal` |
| `income_metrics` | `income` 每期必须有的科目；必备 `revenue`、`cost_of_revenues`、`op_income`、`EBT`、`consolidated_NI`，其余按公司（分部收入、分部营业利润、产品线、套期、优先股……） |
| `identities` | 会计恒等式：`name`、`terms`（科目 → ±1）、`equals` |
| `ratios` | 额外比率 `key = 100 × num / den`（分部利润率、占收入比例） |
| `growth` / `margins` / `segment_ops` | 算同比环比的科目；算百分点变化的利润率键；合计应等于营业利润的分部营业利润（另需一条对应恒等式） |
| `non_operating` / `prior_year_charge` / `calibers` / `bridge_clause` | 可选的示意性税前算术：剔除的非经营项目、加回的上年同期一次性费用（取自登记说明里的 `approx` 约数）；有这两项时 `calibers.ex_items` 必填；`calibers.segment_delta` 可改写分部分解的口径说明 |
| `guidance_remaining` / `balance_note` | 可选：展望区间减年初至今资本开支的剩余额算术；资产负债表脚注 |
| `per_share` / `rpo` | 有 `per_share`、`rpo` 登记时：每股收益字段名；积压订单的数据列（`series`，第一列是合计）与中英文标签 |
| `findings` | 关键发现措辞：`revenue_caveat`（收入口径限制，必填）、可选 `segment`（焦点分部）与 `backlog_caveat` |
| `metrics` / `table` / `report` / `charts` / `segments` / `unallocated` / `share` | 页面：科目的中英文标签、主表的行（`growth: false` 的行不显示同比环比）、文字报告的行、图表（`usd_bn` 或 `pct`）、分部表（`digits` 控制利润率小数位）、未分摊行与占比行 |

没有的可选项就不写：没有展望、积压订单、恒定汇率、每股收益或示意算术时，页面对应章节只写「没有登记」，不编造；`profile.segments` 至少一个（单一分部的公司列出它）。`profile` 里的双语文字必须恰好有 `zh`、`en` 两个键（YAML 流式写法里英文含逗号时要加引号，否则会被截断，`check` 会报错）。

**购置支出与相关本金的 FCF 口径。** 默认仍为 `cfo − cash_ppe`，旧登记不用迁移。发行人的定义若同时扣除购置固定资产/无形资产的现金支出及相关本金支付，则设 `profile.fcf_deduct_principal: true`，在 `cash_flow` 每个期间分列非负有限数值 `cash_ppe` 与 `cash_ppe_principal`（无支付也须明确填 `0`，不能用缺失值代替）。本金不可并入 `cash_ppe`；未启用而出现本金字段、漏填、负数、布尔值或非有限数值均拒绝。`check` 核对本金数值出现在所引原文，`bundle` 保留独立科目，季度与近四季的 FCF 共用同一公式；`issuer_fcf` 若登记则必须按该公式勾稽。页面分列购置支出和本金，并在中英文口径说明中列出公式；资本开支/收入、经营现金流/资本开支中的资本开支只指购置支出，不含本金。这只支持发行人明确披露的相关本金扣除，不等于扣除全部债务偿还或计算可分配现金。其他发行人定义仍需单独适配，不能把未匹配的公式标作发行人 FCF。

本项支持不修改既有关键发现规则或其版本/指纹；未启用本金的旧登记，研究结果与措辞不变。新增配置仍须按上述流程与走查逐项对照、运行并归档，代码支持本身不表示任何新研究已上线。

**关键发现的规则版本与指纹。** 规则代码的指纹是结果校验值的一部分，所以改动规则代码（`research/findings.py` 的季度财报规则、`site/findings_en.py`）后，旧运行用新代码重算的校验值会不同，`iros verify` 如实报告，旧记录不改写（见 [实现说明](implementation.md)）。本次配置化把规则升到 `earnings_quarter-findings.v2`，Alphabet 的运行因此重新运行并归档；早于 profile 的旧运行仍在档案里，网站对它们只显示记录的发现与一条提示。

**下一个季度（同一家公司）。** 季度更新后在同一份登记里推进 `profile.quarters`、`current` 等并追加 `income`、`cash_flow`（或新建 `<ticker>_<fy><q>.yaml` 并新增研究定义，保留上一季度的研究与归档）；做法与上面的步骤相同，`iros earnings fetch` / `bundle` 一次处理 `config/earnings/` 下全部登记，所以每家公司的原文都要在本机。

## 9. 首页入口

首页公司卡片的「公司季度财报」一行（含直达研究的链接）由 `site/content.yaml` 中研究条目的 `home_group` 字段生成，不在代码里点名公司：任何登记了 `home_group: 公司季度财报` 且已有运行的研究都会列在该行，链接文字是公司名加「截至」数据截止日（披露日）。新增季度研究（下一季度或另一家公司）时给它同样的 `home_group`，并在 `site/en.yaml` 保留该组名的译文即可；没有 `home_group` 的研究只计入子类数量。
