---
id: valuation-by-company-type
name_zh: 按公司属性选择估值指标
name_en: Valuation Metric Selection by Company Type
question: 估值
object: [company]
status: draft
sources:
  - type: commentary
    ref: "財女珍妮 2026/11/05 直播，约 16:11–18:57（成长股与周期股的估值差异）"
  - type: structured
    ref: "Damodaran 公开估值资料与行业数据集（按公司生命周期调整估值方法），pages.stern.nyu.edu/~adamodar"
related: [peer-layer-comparison, expectations-revision, earnings-quality-checklist]
---

# 按公司属性选择估值指标

## 回答什么问题
这家公司"便宜"还是"贵"，应该用什么指标判断？

## 适用 / 不适用
- 适用：所有需要判断估值水平的场景
- 不适用：无法归类的特殊情况（并购套利、破产重整），需单独处理

## 所需数据
| 数据 | 来源层级 | 获取方式 |
|---|---|---|
| 股价、市值 | official / structured | 公开行情 |
| EPS、净资产、自由现金流 | official | XBRL |
| 远期 EPS、预期增速 | structured | 第三方一致预期，仅本地使用 |
| 行业历史估值区间 | structured | Damodaran 行业数据集 |

## 步骤
1. **先判断公司属性**（可多选，以主业为准）：

| 属性 | 判断依据 | 主要指标 | 辅助指标 |
|---|---|---|---|
| 成长股 | 营收持续高增长，产品差异化 | 远期 PE ÷ 预期增速 | EV/Sales、DCF |
| 周期股 | 营收与产能、价格周期高度相关，产品标准化 | 股价净值比（P/B） | 周期平均 EPS 的 PE |
| 稳健成长/类公用事业 | 增长中等，现金流稳定 | 远期 PE、股息率 | 与利率的相对关系 |
| 资产型 | 价值主要来自资产 | P/B、NAV | — |

2. 用主要指标与同业组（peer-layer-comparison）和公司自身历史区间比较。
3. 写明当前倍数隐含了什么假设，转入 expectations-revision。

## 输出格式
```yaml
company_type: cyclical      # growth / cyclical / steady / asset
type_basis: "产品标准化，营收与存储价格相关"
primary_metric: {name: P/B, value: 0.0, peer_median: 0.0, own_5y_range: [0.0, 0.0]}
secondary_metric: {name: "", value: 0.0}
verdict: "低于 / 处于 / 高于 合理区间"
implied_assumption: ""
```

## 判断规则与常见误读
- **周期股低本益比陷阱**：周期高点时盈利最高、PE 最低，低 PE 往往反映市场预期未来产能释放、价格下跌。
- 结构性需求（例如 AI）可能延长周期，但通常不会消除周期性；不要因为一个新需求就把周期股改按成长股估值。
- 成长股：PE 低于预期增速，只在增速预期可信时才算便宜。

## 推翻条件
- 公司产品从标准化转向长期合约定价，营收波动显著降低，可重新归类。
- 成长股的预期增速连续下修，"便宜"的判断失效。

## 来源案例
讲者区分了设计类公司（产品差异化、成长溢价）与存储类公司（景气循环股），认为后者过去用 P/B 而非 PE 估值，低 PE 反映的是对未来供需平衡和定价能力下滑的预期。

## 待验证事项
- 用存储类公司过去两个周期的数据检验：低 PE 时点的后续回报是否显著差于低 P/B 时点。
- 与 Damodaran 的生命周期估值框架对照，统一分类定义。
