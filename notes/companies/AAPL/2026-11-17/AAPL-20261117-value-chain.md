---
schema_version: research-notes.v1
id: AAPL-20261117-value-chain
company: AAPL
company_name: Apple
cik: 320193
date: '2026-11-17'
title: Apple 产业链与业务结构｜2026-11-17
source_report_id: AAPL-20261117-value-chain
source_sha256: 514ca10a5bee8a5ef7839786271b9de49dcc732de5dac28da656821988033e8e
rewrites: 3
language: zh
robots: noindex
---

# Apple 产业链与业务结构｜2026-11-17

**R（公开走查）**：[公开记录](https://github.com/werneryang/investment-research-os/blob/1e42dd8a61190729cc1f34451858c63a40714b3b/methodology/records/sec-aapl-value-chain-20261117.yaml)。数据截止：2026-11-17 16:26 EST；网页检索可晚于截止，但只取截止前已发布的材料。此表列有一手证据的**代表关系**，不是全量或按规模排列。

## 一句话结论

【事实】Apple FY2026 10-K 的产品/服务范围横跨智能手机、个人电脑、平板、可穿戴与家居，以及广告、云、内容、支持和支付；法定报告分部按地区，不是这些“子行业”。【推断】其价值链是组件/制造、设备/渠道及服务/生态多层网络；只有具名一手披露能把具体公司放进某条边。

## 发生了什么

### 业务体量与渠道（FY2026；USD 百万）

| 披露或计算 | 数值 | 记录字段 |
| --- | ---: | --- |
| 总净销售额 | 478,834 | `R.financial_context.reported_total` |
| iPhone 净销售额 | 254,098 | `R.financial_context.categories.iPhone.reported_revenue` |
| Services 净销售额 | 123,301 | `R.financial_context.categories.Services.reported_revenue` |
| 间接渠道占总净销售额 | 约 60% | `R.financial_context.reported_indirect_channel_share.approx_percent`（10-K 披露，不是具名运营商份额） |

【计算】以上产品/服务类别合计与总额一致；iPhone/Services 的 FY2026 结构份额在 `R.financial_context.categories.*.computed_share_percent`，不能外推为供应商采购份额。10-K 的地理法定分部见 `R.business_mapping.geographic_reportable_segments`。

### 一手具名关系（期别、类型与确定性）

| 层次 | 公司 | 关系与时态 | 确定性 | 一手来源/走查定位 |
| --- | --- | --- | --- | --- |
| 晶圆代工 | TSMC | 亚利桑那厂正生产用于 iPhone、iPad、Watch 的先进芯片；年度产量目标不当已实现 | 一手具名；不证份额 | [2026-10-20](https://www.apple.com/newsroom/2026/10/apple-announces-american-manufacturing-program-partners-for-latest-iphone-lineup/)；`R.relationships[id=u_tsmc]` |
| 射频/连接 | Broadcom | 为 Apple 产品生产射频组件；扩产另属计划 | 一手具名；不证份额 | [2026-10-20](https://www.apple.com/newsroom/2026/10/apple-announces-american-manufacturing-program-partners-for-latest-iphone-lineup/)；`R.relationships[id=u_broadcom_rf]` |
| 调制解调/射频协议 | Qualcomm Technologies | 已签调制解调/射频系统供应协议，覆盖 2024–2026 新机；不证明每款手机实际采用 | 一手具名；不证份额 | [2023-09-11](https://www.qualcomm.com/news/releases/2023/09/qualcomm-announces-agreement-with-apple-for-chip-supply)；`R.relationships[id=u_qualcomm]` |
| 盖板玻璃 | Corning | 现有特种玻璃/Ceramic Shield 供应；全球盖板玻璃集中到某厂是后续目标 | 一手具名；不证份额 | [2026-10-20](https://www.apple.com/newsroom/2026/10/apple-announces-american-manufacturing-program-partners-for-latest-iphone-lineup/)；`R.relationships[id=u_corning]` |
| 光学/VCSEL | Coherent | 多年度 VCSEL 组件供应关系；不推采购额 | 一手具名；不证份额 | [2026-10-20](https://www.apple.com/newsroom/2026/10/apple-announces-american-manufacturing-program-partners-for-latest-iphone-lineup/)；`R.relationships[id=u_coherent]` |
| 钛材 | Perryman Company | 已公布钛材供货合作；长期承诺尚待兑现 | 已公告、未实现 | [2026-10-20](https://www.apple.com/newsroom/2026/10/apple-announces-american-manufacturing-program-partners-for-latest-iphone-lineup/)；`R.relationships[id=u_perryman]` |
| 相机薄膜 | Qnity Electronics | 相机薄膜/材料合作扩展；具体新机项目为将来生产语态 | 一手具名；不证份额 | [2026-10-20](https://www.apple.com/newsroom/2026/10/apple-announces-american-manufacturing-program-partners-for-latest-iphone-lineup/)；`R.relationships[id=u_qnity]` |
| 芯片封装 | Amkor Technology | 已有芯片封装合作；不等同 Peoria 新厂已供货 | 历史实例 | [2023-11-30](https://www.apple.com/newsroom/2023/11/apple-announces-expanded-partnership-with-amkor-for-silicon-packaging/)；`R.relationships[id=u_amkor_existing]` |
| 未来封测厂 | Amkor Technology Peoria facility | Apple 将成为 Peoria 新封测厂首批客户；该厂尚未证实量产供货 | 拟议客户，未投产供货 | [2026-10-20](https://www.apple.com/newsroom/2026/10/apple-announces-american-manufacturing-program-partners-for-latest-iphone-lineup/)；`R.relationships[id=u_amkor_future]` |
| 稀土磁体 | MP Materials | 稀土磁体合作/承诺；不等于全部交付已实现 | 已公告、未实现 | [2025-07-18](https://www.sec.gov/Archives/edgar/data/1801368/000119312525160635/d923027d424b5.htm)；`R.relationships[id=u_mp]` |
| 运营商/转售 | AT&T | 官方发布当年 iPhone 运营商销售/网络方案；无该渠道份额 | 一手具名；不证份额 | [2026-09-10](https://about.att.com/story/2026/iphone-18-lineup.html)；`R.relationships[id=d_att]` |
| 运营商/转售 | T-Mobile US (including Metro brand) | 官方发布当年 iPhone 运营商销售/网络方案；无该渠道份额 | 一手具名；不证份额 | [2026-09-10](https://www.t-mobile.com/news/devices/iphone-18-pro-iphone-duo-apple-watch-release)；`R.relationships[id=d_tmobile]` |
| 运营商/转售 | Verizon Wireless | 官方发布当年 iPhone 运营商销售/网络方案；无该渠道份额 | 一手具名；不证份额 | [2026-10-16](https://www.verizon.com/about/news/iphone-duo-verizon-offers)；`R.relationships[id=d_verizon]` |
| 企业转售/部署 | CDW | Apple 列名的企业转售/部署伙伴；无采购金额或最终客户结构 | 一手具名；不证份额 | [2026-06-02](https://support.apple.com/en-us/118208)；`R.relationships[id=d_cdw]` |
| 企业终端使用 | United Airlines | 历史企业设备/应用部署实例；不证当年直接大客户 | 历史实例 | [2023-10-12](https://united.mediaroom.com/2023-10-12-United-Promotes-Benefits-of-Bluetooth-Enabled-Planes)；`R.relationships[id=d_united]` |
| AI 集成 | OpenAI | ChatGPT 与 Apple 系统功能集成；不是硬件供货 | 一手具名；不证份额 | [2024-06-10](https://openai.com/index/openai-and-apple-announce-partnership/)；`R.relationships[id=e_openai]` |
| AI 模型协作 | Google | 已签 Gemini/Apple 模型合作；未来功能不能当全面上线 | 已公告、未实现 | [2026-01-12](https://blog.google/company-news/inside-google/company-announcements/joint-statement-google-apple/)；`R.relationships[id=e_google]` |
| 公告时发卡行 | Goldman Sachs | 2026-01 公告时发卡行；截至本次截止日转移是否完成未核 | 一手具名；不证份额 | [2026-01-07](https://www.goldmansachs.com/pressroom/press-releases/2026/goldman-sachs-announces-agreement-to-transition-apple-card-program-to-chase)；`R.relationships[id=e_goldman]` |
| 拟接替发卡行 | Chase / JPMorganChase | 2026-01 公告拟接替 Apple Card 发卡行；截止日是否完成交接未核 | 已公告，完成未核 | [2026-01-07](https://www.apple.com/newsroom/2026/01/chase-to-become-new-issuer-of-apple-card/)；`R.relationships[id=e_chase]` |
| 支付网络 | Mastercard | Apple Card 现有且继续使用的支付网络，不是发卡行 | 一手具名；不证份额 | [2026-01-07](https://www.apple.com/newsroom/2026/01/chase-to-become-new-issuer-of-apple-card/)；`R.relationships[id=e_mastercard]` |

【事实】每条关系的源 URL、披露日期、关系方向、`tier`、`evidence_certainty`、`limits` 均在 `R.relationships`。特别地，Amkor 的现有封装与 **Peoria 厂将成为客户**是两条不同关系；2026-01 公告所述 Goldman Sachs 发卡与 Chase 拟接替也不应合并，截止日交接是否完成未核。United Airlines 是历史企业部署案例，不等于 Apple 公布其为主要直接采购客户。

## 质量与可持续性

【事实】Apple 自己披露直接零售/线上/销售团队与运营商、其他转售商等间接渠道并行；上述约 60% 是整体间接渠道比例。苹果公布的组件伙伴关系给出了部分产品/技术层面的直接证据，而不是采购权重、独家性或盈利贡献。【推断】跨硬件与服务的互补性值得后续研究，但本次不据此判定护城河强度或财务回报。

## 指引与待验证的判断

【事实】部分公告含未来交付或扩产表述；`R.relationships[id=u_amkor_future]` 仅证实 Apple **将成为** Peoria 厂首批客户之一，非该厂已经量产/发货。【推断】下一次可用 Apple/Amkor 官方更新检验是否转为实际关系；结果第 7–8 节登记检验节点，无业绩预测。

## 主要风险与不确定性

- 【事实】Supplier List 的当前原件/覆盖期未核，且该名单即使列厂址也不证实产品型号或组件；本表的任何产品级边均非由名单单独推出。见 `R.supplier_list`。
- 【事实】全球现行具名总装分配无截止前可核的一手证据；Foxconn/Quanta/Pegatron 的 Apple 直接提及只属历史证据，不能写成 FY2026 某型号的主要装配份额。见 `R.relationships[id=h_foxconn]` 及 `R.limitations_and_failures`。
- 【事实】美国 AMP 官方公告偏美国项目；不能代表全球供应链。企业使用、运营商渠道、AI/支付生态不能互换为直接客户/供应商。

## 未覆盖与可选补充

- **已处理 A：**对 FY2026 10-K、Apple/合作方一手网页和具名关系完成单轮补证；独立复核数值与几条关键关系，未有重大差异。仍未证实的全球具名装配与采购/销售权重保留为数据不足。
- **可选 B：**如用户另行同意指定 Apple Supplier List PDF 原件（具体文件名/大小以取得时核），可核清当前版本、实体与厂址；仍不能仅凭名单证明具体供货。
- **方法缺口 D：**G18、G23–G25 已反馈方法库，开放未关闭；产品级证据门槛、跨层角色与“主要”筛选尚无完整专用卡。

## 出处

- [Apple FY2026 Form 10-K（SEC，2026-11-03）](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm)。
- Apple 与交易对手一手公告的逐条 URL、日期、定位、检索与可复现计算：[公开记录](https://github.com/werneryang/investment-research-os/blob/1e42dd8a61190729cc1f34451858c63a40714b3b/methodology/records/sec-aapl-value-chain-20261117.yaml)，字段 `sources`、`relationships`、`financial_context`、`verification`。
- 私有分析结果：`AAPL-20261117-value-chain`。
