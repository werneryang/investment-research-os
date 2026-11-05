---
id: activist-proxy-contest
name_zh: 代理权争夺的正反论证对照
name_en: Activist Proxy Contest — Bull/Bear Argument Comparison
question: 结构与关联
kind: argument
object: [company]
status: draft
sources:
  - type: official
    ref: "SEC EDGAR 表格 DFAN14A（非管理层提交的代理征集材料），例如 Pershing Square 2017 年针对 ADP 的演示材料"
related: [earnings-quality-checklist, guidance-tracking-playbook, forensic-red-flags]
---

# 代理权争夺的正反论证对照

## 回答什么问题
对同一家公司，维权投资者和管理层各自如何论证？双方争议的事实和假设分别是什么？

## 适用 / 不适用
- 适用：有公开代理权争夺的公司（维权方与公司方都向 SEC 提交了材料）
- 不适用：私下和解、没有公开材料的维权案例

## 所需数据
| 数据 | 来源层级 | 获取方式 |
|---|---|---|
| 维权方演示材料 | official | EDGAR 表格 DFAN14A，附件中的 Investor Presentation |
| 公司方回应 | official | EDGAR 表格 DEFA14A 或 DEF 14A |
| 争议期间的财务数据 | official | 同期 10-Q/10-K |
| 结果 | official | 股东大会投票结果 8-K（Item 5.07） |

## 步骤
1. 用 EDGAR 全文检索按表格类型 DFAN14A 筛选，挑选双方都有完整材料的案例。
2. 分别提取双方的论点清单：每条论点拆成 事实 / 解读 / 主张。
3. 对照：哪些事实双方都认可？哪些事实有争议？争议的是事实还是解读？
4. 用同期 10-K/10-Q 核对有争议的事实。
5. 归纳维权方使用的分析方法（例如分部估值、同业利润率差距、资本配置回报），对应到本库已有方法。
6. 把维权方的可检验主张（例如利润率目标）登记到 guidance-tracking-playbook。

## 输出格式
```yaml
case: "XXX 2026 代理权争夺"
filings:
  activist: {form: DFAN14A, accession: "", date: ""}
  company: {form: DEFA14A, accession: "", date: ""}
arguments:
  - topic: 利润率差距
    activist: {fact: "", interpretation: "", claim: ""}
    company: {fact: "", interpretation: "", claim: ""}
    dispute_type: interpretation   # fact / interpretation / none
    verified_against: "10-K FY2025 分部附注"
methods_used: [peer-layer-comparison, earnings-quality-checklist]
outcome: {vote_result_8k: "", date: ""}
```

## 判断规则与常见误读
- 双方都有立场：维权方持有仓位，公司方要保住管理层；两边材料都只能作为"论证样本"，不能作为中立事实。
- 最有价值的是"事实相同、解读不同"的部分，它揭示了分析框架的差异。
- 投票结果不代表谁对，只代表股东当时的判断；论点是否成立要用后续经营数据检验。

## 推翻条件
- 本方法是论证提取工具。若某案例中一方的关键事实被 10-K 证明不实，该方的论证不应作为方法样本。

## 来源案例
Pershing Square 针对 ADP 的演示材料（2017 年，DFAN14A）：典型的维权方论证结构，适合作为第一个提取样本。

## 待验证事项
- 选 3–5 个双方材料齐全的案例，测试提取步骤的一致性。
