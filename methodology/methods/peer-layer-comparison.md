---
id: peer-layer-comparison
name_zh: 供应链分层与同业比较
name_en: Supply Chain Layering and Peer Comparison
question: 结构与关联
kind: routing
object: [industry, company]
status: draft
sources:
  - type: commentary
    ref: "財女珍妮 × Ryan 对谈 2026-10-14，约 11:00–12:30、19:00–22:30（AI 供应链 12 层）"
related: [earnings-quality-checklist, valuation-by-company-type, event-value-chain-exposure]
---

# 供应链分层与同业比较

## 回答什么问题
这家公司应该和谁比较？它的钱来自谁？

## 适用 / 不适用
- 适用：所有需要做毛利率、估值、增速横向比较的分析；本库所有比较类方法都依赖本方法
- 不适用：业务高度多元、无法归入单一层级的集团公司（应先按分部拆分）

## 所需数据
| 数据 | 来源层级 | 获取方式 |
|---|---|---|
| 分部收入、主要客户集中度 | official | 10-K 分部附注、客户集中度披露 |
| 行业分类 | structured | GICS / SIC（EDGAR 中有 SIC 代码）作为起点 |
| 产业链上下游关系 | structured | 10-K 中的供应商与客户描述、行业协会分类 |

## 步骤
1. 从官方分类起步（SIC 代码或 GICS 子行业），只作为粗分。
2. 按"收入来自谁"重新分层：同一层的公司，客户相同、成本结构相近。
3. 每层写明分层依据和代表公司，存为 `peers/<chain>.yaml`。
4. 比较只在同一层内进行：毛利率、营业利润率、ROIC、估值倍数。
5. 跨层只比较"增速是否同步"，用来判断产业链是否整体扩张。
6. 每年复核一次分层，记录调整原因。

## 输出格式
```yaml
# peers/ai-supply-chain.yaml
chain: ai-supply-chain
version: 2026-11
layers:
  - id: semi-materials
    name_zh: 半导体材料与化学品
    revenue_from: 晶圆厂
    basis: "客户均为晶圆制造商，成本以化工原料为主"
    members: []
  - id: foundry
    name_zh: 晶圆代工
    revenue_from: 芯片设计公司
    basis: ""
    members: []
```

## 判断规则与常见误读
- 官方分类太粗：例如材料公司和晶圆代工可能同属"半导体"大类，但毛利率和估值不可比。
- 分层过细会导致每层只剩一两家公司，失去比较意义；每层建议至少 3 家。
- 跨国比较时注意会计准则差异（US GAAP 与 IFRS）。

## 推翻条件
- 某公司的主要收入来源转移到另一层（例如分部收入占比变化超过一半），应重新归类。

## 来源案例
Ryan 的理由：如果把化学材料公司和晶圆代工放在同一组，毛利率和估值无法直接比较；把同类材料公司放在一起才可比。他提到不同机构的分法不同（例如美国半导体行业协会的分段、GICS 的子类），分层取决于投资者视角。

## 待验证事项
- 先为项目已有的「芯片」「炼油」两个行业建立分层文件。
- 检验分层后，同层公司毛利率的离散度是否明显低于按 SIC 分组。
