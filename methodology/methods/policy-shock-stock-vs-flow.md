---
id: policy-shock-stock-vs-flow
name_zh: 政策冲击：存量与增量、时间分层
name_en: Policy Shock — Stock vs Flow, Time Layering
question: 情景与敏感性
object: [industry, company]
status: draft
sources:
  - type: commentary
    ref: "財女珍妮 2026/11/05 直播，约 8:34–11:10（已建/在建与规划中数据中心的区分）"
related: [event-value-chain-exposure, expectations-revision]
---

# 政策冲击：存量与增量、时间分层

## 回答什么问题
一项新的监管或限制，从哪一年开始真正影响供给和业绩？谁反而受益？

## 适用 / 不适用
- 适用：审批制或许可制行业（能源、数据中心、矿业、医药、电信频谱）
- 不适用：立即生效、不区分新旧的政策（例如普遍加税）

## 所需数据
| 数据 | 来源层级 | 获取方式 |
|---|---|---|
| 项目清单：已运营 / 在建 / 规划 | official / structured | 政府审批数据（例如 EIA 发电机组清单、州监管文件）、公司 10-K 项目披露 |
| 各年预计投产量 | structured | 行业统计，标注来源和日期 |
| 政策条款与生效时间 | official | 法案或行政命令原文 |

## 步骤
1. 读政策原文，确定适用对象：只限新申请？还是包括在建？
2. 把供给分成三类：已运营、在建（已获批）、规划中（未获批）。
3. 按年份排列各类的预计投产量，算出每年"受政策影响的比例"。
4. 判断冲击生效年份：受影响比例开始明显上升的那一年。
5. 推导二阶效应：增量受限时，存量资产的稀缺性和定价权是否上升？
6. 写成情景：政策维持 / 放宽 / 加严，分别对各年供给的影响。

## 输出格式
```yaml
policy: ""
applies_to: "仅新申请"
supply_by_year:
  - year: 2027
    operating_or_under_construction_share: 0.00
    affected_share: 0.00
  - year: 2028
    operating_or_under_construction_share: 0.00
    affected_share: 0.00
effective_year: 2028
second_order: "存量资产定价权上升"
scenarios: {maintain: "", relax: "", tighten: ""}
```

## 判断规则与常见误读
- 市场常在政策公布当天对所有相关公司同等反应，但短期供给通常已经锁定，影响集中在远期。
- 越远的年份，规划项目占比越高，不确定性越大，应给更宽的情景区间。
- 存量资产的受益前提是需求不变；如果需求同时下降，二阶效应不成立。

## 推翻条件
- 政策原文显示也适用于在建项目。
- 需求侧同时出现下修（例如主要客户下调资本支出指引）。

## 来源案例
讲者引用的结构：近一年的新增容量大部分已在建，短期供给基本确定；两年后的新增容量多数尚未动工，政策影响主要体现在那时。讲者引用的容量数据和占比未标出处，需另找官方或行业数据核实。

## 待验证事项
- 找到可公开获取的数据中心或发电项目清单（例如 EIA 的发电机组数据），验证这一方法能用官方数据完成。
