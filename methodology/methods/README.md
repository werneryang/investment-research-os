# 研究方法库（Research Method Library）

每个文件描述一种**可复用的分析方法**，与具体公司无关。单份报告的提取记录放在 [`../records/`](../records/README.md)，可检验判断放在 [`../playbooks/`](../playbooks/README.md)。模块边界见 [methodology/README.md](../README.md)。

## 状态等级

| 状态 | 含义 | 升级条件 |
|---|---|---|
| `draft` | 方法来自评论、视频或单一案例，尚未用数据验证 | 至少 2 个独立案例 + 用 EDGAR/FRED 数据复现一次 |
| `validated` | 已有多个案例，步骤可用公开数据复现 | 有历史检验记录（见 guidance-tracking-playbook） |
| `retired` | 发现方法有系统性缺陷 | — |

## 来源可信度标记

- `official`：SEC、BLS、FRED 等官方一手数据
- `structured`：CFA 获奖报告、DFAN14A 文件、Damodaran 公开模型等有完整论证的公开资料
- `commentary`：视频、博客、社群评论；只能提供思路，不能作为证据

## 方法清单

| 文件 | 方法 | 问题分类 | 主要来源 |
|---|---|---|---|
| [unit-economics-take-rate.md](unit-economics-take-rate.md) | 交易平台单位经济拆解 | 分解与归因 | Toast、Block SEC 申报（official）；CFA 2026 LSPD 报告（structured） |
| [inventory-decomposition.md](inventory-decomposition.md) | 库存结构拆解 | 基本面与经营 | Ryan 对谈（commentary） |
| [peer-layer-comparison.md](peer-layer-comparison.md) | 供应链分层与同业比较 | 结构与关联 | Ryan 对谈（commentary） |
| [earnings-quality-checklist.md](earnings-quality-checklist.md) | 财报质量检查清单 | 基本面与经营 | 財女珍妮 11/05 直播（commentary） |
| [valuation-by-company-type.md](valuation-by-company-type.md) | 按公司属性选择估值指标 | 估值 | 財女珍妮 11/05 直播（commentary） |
| [expectations-revision.md](expectations-revision.md) | 市场隐含预期与预期修正 | 估值 | Mauboussin 预期投资法 + 直播 |
| [event-value-chain-exposure.md](event-value-chain-exposure.md) | 事件对产业链的暴露映射 | 暴露与关联 | 財女珍妮 11/05 直播（commentary） |
| [policy-shock-stock-vs-flow.md](policy-shock-stock-vs-flow.md) | 政策冲击：存量与增量、时间分层 | 情景与敏感性 | 財女珍妮 11/05 直播（commentary） |
| [earnings-reaction-check.md](earnings-reaction-check.md) | 财报发布后的市场反应检验 | 价格、收益率与价差 | Ryan 对谈（commentary） |
| [guidance-tracking-playbook.md](guidance-tracking-playbook.md) | 管理层指引与论点追踪 | 数据可得性与口径 | Ryan 对谈（commentary） |
| [activist-proxy-contest.md](activist-proxy-contest.md) | 代理权争夺的正反论证对照 | 结构与关联 | SEC DFAN14A（official） |
| [forensic-red-flags.md](forensic-red-flags.md) | 财务异常排查 | 数据可得性与口径 | 做空研究报告（structured，需独立核实） |

## 方法之间的关系

```
peer-layer-comparison ──► 为所有比较类方法提供同业分组
        │
        ├─► earnings-quality-checklist ──► valuation-by-company-type ──► expectations-revision
        │            │
        │            ├─► inventory-decomposition
        │            ├─► unit-economics-take-rate
        │            └─► forensic-red-flags
        │
event-value-chain-exposure ◄── policy-shock-stock-vs-flow
        │
earnings-reaction-check ──► guidance-tracking-playbook ◄── 所有方法的结论都在这里登记、日后检验
```

## 新增方法

复制 [_template.md](_template.md)，状态设为 `draft`，至少填写「推翻条件」和「来源」两节。
