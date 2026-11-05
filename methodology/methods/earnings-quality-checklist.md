---
id: earnings-quality-checklist
name_zh: 财报质量检查清单
name_en: Earnings Quality Checklist
question: 基本面与经营
kind: checklist
object: [company]
status: draft
sources:
  - type: commentary
    ref: "財女珍妮 2026/11/05 直播，Eaton 约 20:39–26:07，Arista 约 28:05–33:30"
related: [peer-layer-comparison, valuation-by-company-type, inventory-decomposition, guidance-tracking-playbook]
---

# 财报质量检查清单

## 回答什么问题
这一季的增长是否健康、可持续，并且能支撑当前估值？

## 适用 / 不适用
- 适用：有稳定季度披露的运营公司
- 不适用：银行、保险（需专用指标）；尚无营收的早期公司

## 所需数据
| 数据 | 来源层级 | 获取方式 |
|---|---|---|
| 营收、EPS、毛利率、分部数据 | official | 10-Q/10-K、XBRL |
| 有机增长（剔除收购与汇率） | official | 8-K 业绩新闻稿附表（非 GAAP，需注明口径） |
| 管理层指引 | official | 8-K 业绩新闻稿、电话会 |
| 订单与积压订单 | official | 10-Q 剩余履约义务（RPO）附注或新闻稿 |
| 市场一致预期 | structured | 第三方数据，标注来源，不公开转发 |

## 步骤
按顺序检查，每项给出"是 / 否 / 不适用"和依据：
1. **增长来源**：总营收增长中，有机增长占多少？收购贡献占多少？
2. **超预期程度**：营收、调整后 EPS 是否高于一致预期？
3. **指引方向**：本年度第几次上调或下调指引？
4. **领先指标**：订单、积压订单、RPO 是否同步增长？
5. **利润率趋势**：毛利率、营业利润率最近 5 季的方向；同比变化的原因（产品组合、成本、定价）。
6. **收入多元化**：最大终端市场占比多少？单一市场受冲击时影响多大？
7. **现金转换**：经营现金流 ÷ 净利润，是否持续低于 1？
8. **估值对照**：远期本益比与预期增速的关系，转入 valuation-by-company-type。

## 输出格式
```yaml
period: 2026Q3
checks:
  organic_growth: {result: "是", value: 0.00, note: "剔除收购后"}
  beat_consensus: {result: "", note: ""}
  guidance_change: {result: "上调", count_this_year: 0}
  backlog_trend: {result: "", note: ""}
  margin_trend_5q: {result: "", yoy_driver: ""}
  diversification: {largest_end_market_share: 0.00}
  cash_conversion: {ratio: 0.00}
weak_points: []
falsifiable_question: "例：毛利率能否在两季内回到去年同期水平？"
```

## 判断规则与常见误读
- 营收高增长 + 毛利率同比下滑：增长可能靠让利换来，获利能力上修缺乏依据。
- 指引多次上调说明管理层能见度高，但也要看每次上调幅度是否递减。
- 一致预期数据来自第三方，只用于本地判断，不在公开页面展示原始数值。

## 推翻条件
- 下一季毛利率继续同比下滑且管理层没有给出可验证的原因。
- 积压订单下降而营收仍增长，说明在消耗存量订单。

## 来源案例
- Eaton：有机增长和指引上调支撑"稳健成长"的判断；多元终端市场降低了单一政策冲击的影响。
- Arista：营收增长强劲，但调整后毛利率同比下降，讲者因此认为获利上修证据不足、估值偏高。这个"毛利率能否回升"正是可登记到 playbook 的检验问题。

具体数字为讲者口述，未核实。

## 待验证事项
- 用 Eaton、Arista 的 10-Q 和 8-K 复现第 1、4、5、7 项。
- 确认 RPO 在 XBRL 中的标签，以便自动化第 4 项。
