---
id: inventory-decomposition
name_zh: 库存结构拆解
name_en: Inventory Composition Analysis
question: 基本面与经营
kind: decomposition
object: [company]
status: draft
sources:
  - type: commentary
    ref: "財女珍妮 × Ryan 对谈《為什麼AI分析股票常出錯？》2026-10-14，约 12:00–13:30"
related: [earnings-quality-checklist, peer-layer-comparison, forensic-red-flags]
---

# 库存结构拆解

## 回答什么问题
库存增加是需求转弱的信号，还是为出货备料的信号？

## 适用 / 不适用
- 适用：硬件、半导体、制造业、零售等库存占资产比重较高的公司
- 不适用：软件、服务业；以及不在附注中披露库存分类的公司

## 所需数据
| 数据 | 来源层级 | 获取方式 |
|---|---|---|
| 原材料库存 | official | XBRL（us-gaap 中原材料库存相关标签，具体标签名需在 EDGAR 公司数据中核对） |
| 在制品库存 | official | XBRL（在制品库存相关标签，同上） |
| 成品库存 | official | XBRL（成品库存相关标签，同上） |
| 营收、营业成本 | official | XBRL |
| 采购承诺 / 供应承诺 | official | 10-K/10-Q 承诺与或有事项附注（多为文本） |

注意：公司可能使用自定义标签或只在附注表格中披露，需要逐家确认。

## 步骤
1. 取最近 6–8 个季度的三类库存。
2. 计算各类的环比、同比变化，以及在总库存中的占比变化。
3. 计算库存周转天数：库存 ÷ 营业成本 × 天数，分别对总库存和成品库存计算。
4. 对照营收增速和采购承诺变化。
5. 按下表判断信号，再与同业组比较。

| 原材料 | 成品 | 营收 | 初步判断 |
|---|---|---|---|
| ↑ | ↓ | ↑ | 备料出货，需求强 |
| ↑ | ↑ | 持平/↓ | 生产超过需求，警惕 |
| ↓ | ↑ | ↓ | 需求转弱，可能有减值 |
| ↓ | ↓ | ↑ | 供给受限，可能错失收入 |

## 输出格式
```yaml
quarters: 8
raw_materials_qoq: 0.00
wip_qoq: 0.00
finished_goods_qoq: 0.00
finished_goods_days: 0
revenue_qoq: 0.00
signal: "备料出货 / 生产过剩 / 需求转弱 / 供给受限"
peer_comparison: ""
```

## 判断规则与常见误读
- 总库存上升本身不是负面信号，必须看结构。
- 产品换代期间原材料会短期激增，要结合产品周期判断。
- 库存跌价准备的变化可能扭曲各类库存的净额，需看附注。

## 推翻条件
- 原材料持续上升但营收在之后两季没有跟上，原"备料出货"判断失效。
- 出现大额库存减值或采购承诺取消费用。

## 来源案例
Ryan 以 NVIDIA 为例：半年内总库存明显增加，但原材料增加、成品减少，他解读为边做边出货。该组数字为口述，未经核实，使用前需用 NVIDIA 10-Q 复现。

## 待验证事项
- 用 EDGAR companyfacts 接口确认 NVIDIA、AMD、Micron 是否用标准标签披露三类库存。
- 用 Micron 做反向案例（周期股的库存信号是否更有效）。
