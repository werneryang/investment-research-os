---
id: forensic-red-flags
name_zh: 财务异常排查
name_en: Forensic Accounting Red Flags
question: 数据可得性与口径
object: [company]
status: draft
sources:
  - type: structured
    ref: "做空研究机构公开报告（Muddy Waters、Spruce Point、Kerrisdale 等）；报告方通常持有相关仓位，指控需独立核实"
related: [earnings-quality-checklist, inventory-decomposition, activist-proxy-contest]
---

# 财务异常排查

## 回答什么问题
公司披露的数字之间是否存在矛盾，提示会计处理激进或经营实况与报表不符？

## 适用 / 不适用
- 适用：所有上市公司，尤其是连续收购整合的公司、大量使用非 GAAP 指标的公司
- 不适用：作为单独的投资结论来源（本方法只产生"需要追问的问题"，不产生结论）

## 所需数据
| 数据 | 来源层级 | 获取方式 |
|---|---|---|
| 三张报表与附注 | official | XBRL、10-K/10-Q |
| 非 GAAP 调节表 | official | 8-K 业绩新闻稿 |
| 披露变化 | official | 不同年度 10-K 的同一附注对比 |
| 管理层背景 | official | DEF 14A 高管简历 |

## 步骤
逐项检查，每项记录"正常 / 需追问"和依据：
1. **现金与利润背离**：经营现金流 ÷ 净利润连续多期低于 1，且差距扩大。
2. **应收增速快于营收**：应收账款周转天数持续上升。
3. **库存异常**：转入 inventory-decomposition。
4. **非 GAAP 调整扩大**：调整项占 GAAP 利润的比例逐年上升，或调整项名目经常变化。
5. **有机增长可疑**：收购型公司的"有机增长"能否从分部或收购附注中重算出来。
6. **披露减少**：某项过去披露的明细在新年报中消失（例如租赁、分部明细）。
7. **资本化激进**：资本化的费用（软件开发、合同成本）占比上升。
8. **治理与人员**：财务负责人频繁更换、审计师变更、关联交易。

## 输出格式
```yaml
period_range: 2022FY-2025FY
flags:
  - item: cash_vs_earnings
    status: 需追问
    evidence: {metric: ocf_to_net_income, values: [], source: "XBRL"}
  - item: disclosure_removed
    status: 正常
    evidence: {}
questions_for_followup: []
```

## 判断规则与常见误读
- 单个红旗不说明问题，多个红旗同时出现才需要深入追查。
- 做空报告的价值在于提供排查思路和可核对的线索；其中的结论和估值目标不能直接采用。
- 所有指控类内容在公开页面上只能表述为"数据显示的矛盾"，不能表述为对公司的定性。

## 推翻条件
- 追问的事项在后续披露中得到合理解释（例如季节性、会计准则变化），对应红旗撤销。

## 来源案例
做空报告中常见的排查角度包括：现金流与利润背离、有机增长被高估（例如增长主要来自价格传导而非销量）、披露明细减少、非 GAAP 指标与同业口径不一致。具体指控需逐条用 10-K 核实后才能作为案例引用。

## 待验证事项
- 选 2 份已被后续事件证实、2 份未被证实的做空报告，检验本清单能否从公开报表中独立发现相同问题。
