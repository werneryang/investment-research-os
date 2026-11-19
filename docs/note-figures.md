# 研究报告图块：风格与写法

网站上的中文研究报告（`notes/companies/`）原本只有文字和表格。图块给报告加上图表，规则只有一套，每份报告都按这套来。首例是 NVDA FY2027 Q3（`config/note_figures/NVDA-20261117-q3-fy27.yaml`）。

## 1. 为什么图块不写进报告正文

- 报告正文是从 company-dossiers 原样复制过来的，导入后不改动（`source_sha256` 固定）。
- 图上的每个数字都引用公开走查记录（`methodology/records/*.yaml`）里的字段，不手填。这样数字只有一份，图和记录不会对不上。
- 图块文件放在本仓库 `config/note_figures/<报告 id>.yaml`，按报告的二级标题插入。没有图块文件的报告照常显示。

## 2. 风格规则

| 规则 | 做法 |
| --- | --- |
| 标题写结论 | 一句话说这张图证明了什么，例如「营收连续五季增长，Q4 指引中点比 Q3 再高 12.2%」，不写「营收」这种名词标题。标题里的数字用 `{R:路径:格式}` 代入。 |
| 副标题写口径 | 单位、期间、口径边界，例如「GAAP 营收，十亿美元；Q4 为指引中点 ±3%，含额外一周」。 |
| 出处行 | 每张图底部都有一行：来源文件，加上公开记录的链接。用到的字段由程序自动列在「数据表与字段」里，不用手写。 |
| 证据级别 | 分四种：事实、计算、推断、展望，用 `evidence: fact / calc / infer / fwd` 标注。正文里的【事实】【计算】【推断】【展望】也会渲染成同样颜色的标签。 |
| 展望值 | 画成浅色填充的虚线框，区间用须线标出，不画成实心柱。 |
| 一张图一个纵轴 | 单位不同的量（营收和毛利率）用 `group` 分成两张小图并排，不画双轴。 |
| 不可相加的量 | 用 `hbar` 每项一行，标出性质；或有、最高额类用第 4 色，不画成堆叠柱。 |
| 颜色 | 只用 style.css 的 `--c1…--c8`，按固定顺序。第 2 色用来突出例外（如 Q2 低点）。`--c3`、`--c4` 对白底对比度不足，图上必须直接标数值。 |
| 直接标注 | 只标最后一期、指引和突出项，不在每根柱上标数。完整数值放在可展开的数据表里，鼠标悬停也能看到。 |
| 手机 | 宽图保持最小宽度，在图内横向滚动，页面本身不横向滚动。 |

## 3. 每节首选图形

| 报告节 | 季度财报 | 产业链 / 结构 |
| --- | --- | --- |
| 一句话结论（节末） | `kpi` 3–4 个数字，带证据标签 | `kpi`：关系数、当期占比、最大收入类别 |
| 发生了什么 | `bar` 五季加指引虚框 | 收入结构条、层次 × 时态矩阵（待实现） |
| 质量与可持续性 | `group`：利润率 `line` 加 CFO/净利润 `bar` | 供应商依赖斜率图（待实现） |
| 指引与待验证 | 指引对比上季区间（待实现） | 待兑现事项时间线（待实现） |
| 主要风险 | `hbar` 承诺分行，不相加 | 不画 |

没有数据支撑的节不硬画图。

## 4. 写法

```yaml
schema_version: note-figures.v1
note: NVDA-20261117-q3-fy27            # 与报告 id 相同，文件名也是它
records:
  R: methodology/records/sec-nvda-earnings-20261117.yaml   # 报告正文必须已链接这份记录
figures:
  - id: revenue-5q
    section: 发生了什么                  # 二级标题的开头，必须恰好匹配一处
    position: start                     # start = 标题后；end = 下一个二级标题前
    type: bar                           # kpi / bar / line / hbar / group
    title: "营收连续五季增长，Q4 指引中点比 Q3 再高 {R:guidance.computed_midpoint_vs_current_pct:.1f}%"
    subtitle: GAAP 营收，十亿美元；…
    x: [FY26Q3, FY26Q4, FY27Q1, FY27Q2, FY27Q3]
    value: {ref: "R:quarter_inputs.{x}.revenue", scale: 0.001}
    guide: {label: FY27Q4E, mid: "R:guidance.revenue_midpoint", low: "R:guidance.computed_revenue_low", high: "R:guidance.computed_revenue_high"}
    source: SEC 8-K 0001045810-26-000088
    evidence: fact
```

- 数值写成 `"R:路径"`、`{ref, scale}` 或 `{sum: [...], scale}`。路径里可以用 `{x}` 代入期间，也可以用 `[0]` 取列表元素。写死的数字（如 `value: 115.8`）会被拒绝。
- 文字里的 `{R:路径*0.001:.1f}` 先乘系数，再按格式代入。
- 只有版式参数可以写常数：`y_min`/`y_max`（折线坐标范围，数据超出会报错）、`ref_line`、`width`、`height`。
- 引用不成立就报错，网站构建也会失败，不会静默跳过：字段不存在、不是数值、记录不在 `methodology/records/`、正文没链接这份记录、节标题匹配不到或匹配到多处，都算不成立。`tests/test_note_figures.py` 会把每份图块和对应报告都渲染一遍。
- 图块文件同样要过公开边界检查（本机路径、邮箱、key 等）。

各类型的参数见 `src/investment_os/site/note_figures.py`。

## 5. 分工

- 本仓库：维护渲染器、样式和每份报告的图块文件。新报告放行导入后，在这里补图块。
- research-method-extraction：分析结果模版写明「每节首选图」，并要求报告里要上图的数字都能对应到公开记录的字段。
- company-dossiers：写报告时，结论和数字落在记录字段上。报告正文不需要改。
