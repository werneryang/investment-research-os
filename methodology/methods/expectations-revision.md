---
id: expectations-revision
name_zh: 市场隐含预期与预期修正
name_en: Market-Implied Expectations and Revisions
question: 估值
object: [company]
status: draft
sources:
  - type: structured
    ref: "Rappaport & Mauboussin, Expectations Investing（预期投资法：由股价反推隐含预期）；Mauboussin 公开论文索引 michaelmauboussin.com"
  - type: commentary
    ref: "財女珍妮 2026/11/05 直播，约 18:24–18:41（市场要求的是增速持续提高）"
related: [valuation-by-company-type, guidance-tracking-playbook, earnings-reaction-check]
---

# 市场隐含预期与预期修正

## 回答什么问题
当前股价隐含了怎样的未来表现？实际结果比这个隐含预期好还是差？

## 适用 / 不适用
- 适用：有稳定现金流或可预测盈利的公司
- 不适用：现金流长期为负且无可靠预测的公司（反推结果对假设过度敏感）

## 所需数据
| 数据 | 来源层级 | 获取方式 |
|---|---|---|
| 市值、净负债 | official | XBRL + 行情 |
| 当前自由现金流、利润率 | official | XBRL |
| 折现率（WACC） | structured | Damodaran 行业 WACC 数据集 |
| 一致预期及其修正 | structured | 第三方，仅本地使用 |

## 步骤
1. **反推**：固定折现率和终值假设，求出让 DCF 价值等于当前企业价值的营收增速（或利润率、持续期）。
2. **合理性检查**：把隐含增速与公司历史增速、同业组基准率对比。隐含增速在历史上达到过的公司占多少？
3. **识别关键变量**：营收增速、利润率、再投资率中，哪个变化对价值影响最大（敏感性表）。
4. **跟踪修正**：每季比较实际值与隐含值；记录一致预期的上修或下修方向。
5. 把"隐含增速"登记到 guidance-tracking-playbook，作为日后检验对象。

## 输出格式
```yaml
as_of: 2026-11-05
wacc: 0.000
implied:
  revenue_cagr_10y: 0.00
  terminal_margin: 0.00
base_rate:
  share_of_peers_achieving: 0.00   # 历史上达到该增速的公司比例
sensitivity:
  most_sensitive_driver: revenue_growth
revision_direction_last_2q: "上修 / 下修 / 持平"
```

## 判断规则与常见误读
- 股价反映的是预期，好财报不等于股价上涨；关键是结果相对预期的差距。
- 市场常要求增速持续提高：增速从高位回落，即使仍然很高，也可能被视为不及预期。
- 反推结果对折现率和终值高度敏感，必须同时给出敏感性区间，不能只报一个数。

## 推翻条件
- 实际增速连续两季高于隐含增速，但股价不涨：可能是折现率（利率、风险溢价）在变化，需改用利率情景重算。

## 来源案例
直播中的说法（成长率从高位回落即被视为不及格）与预期投资法的核心一致：价格变化来自预期修正，而非绝对水平。

## 待验证事项
- 用你网站已有的 15 家公司，各做一次隐含增速反推，检验结果是否稳定。
- 引入 Mauboussin 关于企业增长基准率的论文数据，作为第 2 步的参照。
