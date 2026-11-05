---
id: guidance-tracking-playbook
name_zh: 管理层指引与论点追踪
name_en: Guidance and Thesis Tracking Playbook
question: 基本面与经营
kind: tracking
object: [company, industry, macro]
status: draft
sources:
  - type: commentary
    ref: "財女珍妮 × Ryan 对谈 2026-10-14，约 14:50–17:00（PLBook：记录管理层说法以便日后对照）"
related: [expectations-revision, earnings-quality-checklist, earnings-reaction-check]
---

# 管理层指引与论点追踪

## 回答什么问题
管理层的指引、分析师的论点、我们自己的判断，事后有多少兑现了？

这是整个方法库的**检验层**：其他方法得出的可检验判断，都登记在这里。

## 适用 / 不适用
- 适用：任何带有明确数值或方向、且有检查日期的说法
- 不适用：无法量化或无检查时间的说法（例如"长期前景很好"），这类说法应改写成可检验的形式，改写不了就不登记

## 所需数据
| 数据 | 来源层级 | 获取方式 |
|---|---|---|
| 说法原文出处 | official / structured / commentary | 8-K、电话会、研报、视频，记录位置（页码或时间戳） |
| 实际结果 | official | 后续 10-Q/10-K、XBRL、FRED |

## 步骤
1. **登记**：每条说法写成"谁、何时、说了什么数值、对应哪个指标、何时检查"。
2. **口径确认**：指标定义必须能用官方数据核对（例如"有机营收增长"要写明剔除收购的口径）。
3. **到期核对**：检查日到期后，从官方数据取实际值，标记 达成 / 未达成 / 无法核对。
4. **统计**：按来源（管理层、分析师、评论者、本站自己）统计兑现率。
5. **反馈**：兑现率长期偏低的来源，在方法库中降低其可信度权重。

## 输出格式
```yaml
# playbooks/<ticker>.yaml
ticker: XXX
claims:
  - id: XXX-2026Q3-01
    made_by: management        # management / analyst / commentator / self
    made_on: 2026-00-00
    source: {type: official, ref: "8-K Exhibit 99.1，第 2 页"}
    metric: organic_revenue_growth_fy2026
    claim: {low: 0.13, high: 0.15}
    check_on: 2027-02-15
    check_source: "FY2026 10-K"
    result: null               # met / missed / unverifiable
    actual: null
    note: ""
```

## 判断规则与常见误读
- 只登记可检验的说法；模糊说法要么改写成数值，要么放弃。
- 管理层会多次修改指引，每次修改单独登记，方便看修正方向。
- 自己的判断也要登记（made_by: self），否则只会记住说对的。

## 推翻条件
- 本方法是检验工具。若某类指标长期"无法核对"（口径不公开），说明该指标不应作为方法库的检验对象。

## 来源案例
Ryan 的理由：管理层给出增长指引，一年后很少有人记得；他用一个 Playbook 文件让 AI 记录，宏观数据（例如每月 CPI）也可以这样延续追踪。这个想法可以直接替代"用少量研报检验目标价准确率"的做法，样本量更大，也能用官方数据核对。

## 待验证事项
- 先为项目已有的 15 家公司，登记最近一季的管理层年度指引，到期自动核对。
- 在 CI 中加入检查：到期未核对的条目报警。
