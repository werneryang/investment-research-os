---
id: unit-economics-take-rate
name_zh: 交易平台单位经济拆解
name_en: Transaction Platform Unit Economics
question: 分解与归因
object: [company, industry]
status: draft
sources:
  - type: structured
    ref: "CFA Institute Research Challenge 2026 全球冠军报告，University of Waterloo，Lightspeed Commerce（LSPD），支付成本相关章节（页码待核对）"
related: [peer-layer-comparison, earnings-quality-checklist]
---

# 交易平台单位经济拆解

## 回答什么问题
交易量增长是否真的带来利润增长，还是被成本同步吃掉？

## 适用 / 不适用
- 适用：支付处理商、POS 软件、电商平台、市场撮合类平台、金融科技公司
- 不适用：以订阅收入为主、交易抽成占比很小的软件公司

## 所需数据
| 数据 | 来源层级 | 获取方式 |
|---|---|---|
| 总交易额（GTV/GMV/GPV） | official | 10-K/10-Q 的 MD&A 或关键运营指标（多为非 XBRL 披露，需从文本提取） |
| 交易相关收入 | official | 10-K 分部或收入分解附注 |
| 交易处理成本 | official | 营业成本附注；常不单独披露，需注明为估算 |
| 同业的同类指标 | official | 同一同业组公司的 10-K |

## 步骤
1. 把收入拆成：交易笔数 × 平均交易金额 × 抽成率（take rate）。
2. 把成本拆成：第三方处理费 + 自有处理成本 + 风控损失。
3. 计算单位贡献：每 1 美元交易额的毛利（bps）。
4. 拆分增长来源：交易额增长、抽成率变化、成本率变化各自贡献多少。
5. 与同业组比较抽成率和处理成本率，标出差距最大的一项。
6. 检查差距是否结构性：自有处理比例、客户组合（大客户议价能力强）、地区组合。

## 输出格式
```yaml
period: 2025FY
gtv_growth: 0.00
take_rate_bps: 0
processing_cost_bps: 0       # 若为估算，注明 estimate: true
unit_contribution_bps: 0
growth_attribution:
  volume: 0.00
  take_rate: 0.00
  cost_rate: 0.00
peer_gap:
  metric: processing_cost_bps
  gap_bps: 0
  structural_reason: ""
```

## 判断规则与常见误读
- 收入增速高不代表单位经济改善；要看每单位交易额的毛利是否上升。
- 抽成率上升可能来自产品组合变化（例如加了高抽成的金融服务），不一定是定价权。
- 公司常只披露"交易相关收入"，成本需要估算，估算值必须标记，不能和披露值混用。

## 推翻条件
- 公司提高自有处理比例，处理成本率连续两季下降。
- 客户组合改善（小商户占比上升）带动抽成率上升，且没有被成本抵消。

## 来源案例
LSPD 报告的推理链（结构，非数字）：依赖第三方处理 → 交易量增长时处理费同步增长 → 单位经济承压 → 现金流预测下调。报告给出的成本差异区间需回原文核对页码后再引用。

## 待验证事项
- 找第二个案例（例如 Toast 或 Block 的 10-K），验证拆解步骤能用公开披露完成。
- 确认哪些指标有 XBRL 标签，哪些只能从文本提取。
