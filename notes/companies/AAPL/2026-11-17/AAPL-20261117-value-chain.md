---
schema_version: research-notes.v1
id: AAPL-20261117-value-chain
company: AAPL
company_name: Apple
cik: 320193
date: '2026-11-17'
title: Apple 产业链与业务结构｜2026-11-17
source_report_id: AAPL-20261117-value-chain
source_sha256: 9bad815815116fc4089e002c341d8bf9c63b6ce8abee8ffb49d016dba9041175
rewrites: 0
language: zh
robots: noindex
---

# Apple 产业链与业务结构｜2026-11-17

**R（公开走查）**：[sec-aapl-value-chain-20261117.yaml](https://github.com/werneryang/investment-research-os/blob/main/methodology/records/sec-aapl-value-chain-20261117.yaml)。数据截止：2026-11-17 16:26 EST；网页检索可晚于截止，但只取截止前已发布的材料。此表列有一手证据的**代表关系**，不是全量或按规模排列。

## 一句话结论

【事实】Apple FY2026 10-K 的产品/服务范围横跨智能手机、个人电脑、平板、可穿戴与家居，以及广告、云、内容、支持和支付；法定报告分部按地区，不是这些“子行业”。【推断】其价值链是组件/制造、设备/渠道及服务/生态多层网络；只有具名一手披露能把具体公司放进某条边。

## 发生了什么

### 业务体量与渠道（FY2026；USD 百万）

| 披露或计算 | 数值 | 记录字段 |
| --- | ---: | --- |
| 总净销售额 | 478,834 | `R.financial_context.reported_total` |
| iPhone（智能手机） | 254,098；53.07% | `R.financial_context.categories.iPhone.reported_revenue/computed_share_percent` |
| Mac（个人电脑） | 37,929；7.92% | `R.financial_context.categories.Mac.reported_revenue/computed_share_percent` |
| iPad（平板） | 27,929；5.83% | `R.financial_context.categories.iPad.reported_revenue/computed_share_percent` |
| 穿戴、家居及配件 | 35,577；7.43% | `R.financial_context.categories.Wearables_Home_Accessories.reported_revenue/computed_share_percent` |
| Services（服务） | 123,301；25.75% | `R.financial_context.categories.Services.reported_revenue/computed_share_percent` |
| 间接渠道占总净销售额 | 约 60% | `R.financial_context.reported_indirect_channel_share.approx_percent`（10-K 披露，不是具名运营商份额） |

【计算】五类合计 478,834；占比按各类收入除以总额，逐项显示值四舍五入后合计为 100.00%。这是 Apple 产品/服务收入结构，不是五个法定分部，也不能外推为供应商采购或渠道份额。法定分部按地区，见 `R.business_mapping.geographic_reportable_segments`。

**类别与关系边界：**iPhone 有 TSMC、Qualcomm、Corning、Coherent、Perryman、Qnity 等明确的产品/技术线索，AT&T、T-Mobile、Verizon 有当年设备销售渠道证据；iPad 有 TSMC 与 Coherent 的明确用途线索；Watch 仅有 TSMC 芯片的明确用途线索，Corning 的 Watch 玻璃集中生产是目标。Mac 暂无这 32 条关系中可直接归到该类的具名部件边。United Airlines 是历史 iPhone/iPad 企业使用，CDW 为跨设备部署渠道；Apple Card/Mastercard、Google/OpenAI 是支付或软件生态，不能直接对应 Services 收入类别中的具名金额。其他半导体、晶圆、设备及历史装配边只标 Apple 产品/多品类或未指明品类，不强行分配到上述五类。各关系的范围和时态以 `R.relationships` 为准。

### 一手具名关系（期别、类型与确定性）

| 层次 | 公司 | 关系与时态 | 确定性 | 一手来源/走查定位 |
| --- | --- | --- | --- | --- |
| 晶圆代工 | TSMC | 亚利桑那厂正生产用于 iPhone、iPad、Watch 的先进芯片；年度产量目标不当已实现 | 一手具名；不证份额 | [2026-10-20](https://www.apple.com/newsroom/2026/10/apple-announces-american-manufacturing-program-partners-for-latest-iphone-lineup/)；`R.relationships[id=u_tsmc]` |
| 射频/连接 | Broadcom | 为 Apple 产品生产射频组件；扩产另属计划 | 一手具名；不证份额 | [2026-10-20](https://www.apple.com/newsroom/2026/10/apple-announces-american-manufacturing-program-partners-for-latest-iphone-lineup/)；`R.relationships[id=u_broadcom_rf]` |
| 调制解调/射频协议 | Qualcomm Technologies | 已签调制解调/射频系统供应协议，覆盖 2024–2026 新机；不证明每款手机实际采用 | 一手具名；不证份额 | [2023-09-11](https://www.qualcomm.com/news/releases/2023/09/qualcomm-announces-agreement-with-apple-for-chip-supply)；`R.relationships[id=u_qualcomm]` |
| 盖板玻璃 | Corning | 现有特种玻璃/Ceramic Shield 供应；全球盖板玻璃集中到某厂是后续目标 | 一手具名；不证份额 | [2026-10-20](https://www.apple.com/newsroom/2026/10/apple-announces-american-manufacturing-program-partners-for-latest-iphone-lineup/)；`R.relationships[id=u_corning]` |
| 光学/VCSEL | Coherent | 多年度 VCSEL 组件供应关系；不推采购额 | 一手具名；不证份额 | [2026-10-20](https://www.apple.com/newsroom/2026/10/apple-announces-american-manufacturing-program-partners-for-latest-iphone-lineup/)；`R.relationships[id=u_coherent]` |
| 钛材 | Perryman Company | 公告描述现有 iPhone Duo 钛材采购；多年承诺后续交付未核 | 现有采购具名、未来交付未核；无份额 | [2026-10-20](https://www.apple.com/newsroom/2026/10/apple-announces-american-manufacturing-program-partners-for-latest-iphone-lineup/)；`R.relationships[id=u_perryman]` |
| 相机薄膜 | Qnity Electronics | 相机薄膜/材料合作扩展；具体新机项目为将来生产语态 | 一手具名；不证份额 | [2026-10-20](https://www.apple.com/newsroom/2026/10/apple-announces-american-manufacturing-program-partners-for-latest-iphone-lineup/)；`R.relationships[id=u_qnity]` |
| 芯片封装 | Amkor Technology | 已有芯片封装合作；不等同 Peoria 新厂已供货 | 历史实例 | [2023-11-30](https://www.apple.com/newsroom/2023/11/apple-announces-expanded-partnership-with-amkor-for-silicon-packaging/)；`R.relationships[id=u_amkor_existing]` |
| 未来封测厂 | Amkor Technology Peoria facility | Apple 将成为 Peoria 新封测厂首批客户；该厂尚未证实量产供货 | 拟议客户，未投产供货 | [2026-10-20](https://www.apple.com/newsroom/2026/10/apple-announces-american-manufacturing-program-partners-for-latest-iphone-lineup/)；`R.relationships[id=u_amkor_future]` |
| 稀土磁体 | MP Materials | 稀土磁体合作/承诺；不等于全部交付已实现 | 已公告、未实现 | [2025-07-18](https://www.sec.gov/Archives/edgar/data/1801368/000119312525160635/d923027d424b5.htm)；`R.relationships[id=u_mp]` |
| 定制芯片协议 | Broadcom | 多代 Apple 产品的 ASIC 协议至 2031 年；签约不等于逐代交付 | 已签、未来交付未核；无份额 | [2026-07-06 SEC 8-K](https://www.sec.gov/Archives/edgar/data/1730168/000119312526295589/d84378d8k.htm)；`R.relationships[id=u_broadcom_asic]` |
| 半导体制造 | Samsung | Austin 新制程合作，面向 Apple 产品；不等于当期芯片已供货 | 2025-08 公告、未来计划；无份额 | [Apple 2025-08-06](https://www.apple.com/newsroom/2025/08/apple-increases-us-commitment-to-600-billion-usd-announces-ambitious-program/)；`R.relationships[id=u_samsung]` |
| 半导体产能 | Texas Instruments | Lehi/Sherman 制造及未来产品合作；不确认当期产量 | 2025-08 扩展合作、产能计划；无份额 | [Apple 2025-08-06](https://www.apple.com/newsroom/2025/08/apple-increases-us-commitment-to-600-billion-usd-announces-ambitious-program/)；`R.relationships[id=u_ti]` |
| 晶圆代工/开发 | GlobalFoundries | 无线/电源管理及 Cirrus/Broadcom 相关开发项目；不作已量产推断 | 2025-08、2026-03 已公告合作；无份额 | [Apple 2025-08-06](https://www.apple.com/newsroom/2025/08/apple-increases-us-commitment-to-600-billion-usd-announces-ambitious-program/)、[2026-03-26](https://www.apple.com/newsroom/2026/03/apple-adds-new-partners-to-its-american-manufacturing-program/)；`R.relationships[id=u_gf]` |
| 传感器 | TDK | 既有全球传感器关系；美国 TMR/相机稳定传感器生产为未来计划 | 2026-03 公告、美国供货未证；无份额 | [Apple 2026-03-26](https://www.apple.com/newsroom/2026/03/apple-adds-new-partners-to-its-american-manufacturing-program/)；`R.relationships[id=u_tdk]` |
| 传感硬件 | Bosch | 与 Apple/TSMC 的华盛顿州传感 IC 合作 | 2026-03 公告、未来合作；无份额 | [Apple 2026-03-26](https://www.apple.com/newsroom/2026/03/apple-adds-new-partners-to-its-american-manufacturing-program/)；`R.relationships[id=u_bosch]` |
| 混合信号 IC | Cirrus Logic | 与 Apple/GF 的制程开发，含 Face ID 相关 IC；不等于量产供货 | 2026-03 新开发项目；无份额 | [Apple 2026-03-26](https://www.apple.com/newsroom/2026/03/apple-adds-new-partners-to-its-american-manufacturing-program/)；`R.relationships[id=u_cirrus]` |
| 上上游晶圆 | GlobalWafers America | 计划向美国晶圆厂供应先进晶圆，间接服务 Apple 产品链 | 2025-08 公告、未来中间环节；非直接 Apple 部件采购 | [Apple 2025-08-06](https://www.apple.com/newsroom/2025/08/apple-increases-us-commitment-to-600-billion-usd-announces-ambitious-program/)；`R.relationships[id=t_gwa]` |
| 上上游设备 | Applied Materials | 美国半导体厂设备链，TI 厂为具名使用方；不等于 Apple 直接采购设备 | 2025-08 公告、赋能链；非直接 Apple 部件采购 | [Apple 2025-08-06](https://www.apple.com/newsroom/2025/08/apple-increases-us-commitment-to-600-billion-usd-announces-ambitious-program/)；`R.relationships[id=t_amat]` |
| 历史工厂审核 | Quanta Computer | Apple 2012 年拟审其设施；不证明 FY2026 装配分工 | 2012-02 历史审核语境；非当期供应确认 | [Apple 2012-02-13](https://www.apple.com/newsroom/2012/02/13Fair-Labor-Association-Begins-Inspections-of-Foxconn/)；`R.relationships[id=h_quanta]` |
| 历史工厂审核 | Pegatron | Apple 2012 年拟审其设施；不证明 FY2026 装配分工 | 2012-02 历史审核语境；非当期供应确认 | [Apple 2012-02-13](https://www.apple.com/newsroom/2012/02/13Fair-Labor-Association-Begins-Inspections-of-Foxconn/)；`R.relationships[id=h_pegatron]` |
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

**32 条关系逐 ID 审计：**上表纳入 31 条，只有 `h_foxconn` 排除表格：Apple [2012-02-13 历史公告](https://www.apple.com/newsroom/2012/02/13Fair-Labor-Association-Begins-Inspections-of-Foxconn/) 确曾直接点名 Foxconn 为当时总装供应商，但该证据不支持 FY2026 全球/具体产品总装分工；因此仅保留在下方历史风险说明，不列为当期“主要”关系。`h_quanta`、`h_pegatron` 列入表格也只作同一历史审核语境，不升级为当前供应。纳入/排除按 `R.relationships[*].id` 集合核对，未将 `R.supplier_list` 的未核 PDF 名单变成关系边。

### 供应商收入对 Apple 的依赖（各供应商财年；占各自收入）

**S（补充走查）**：[公开记录](https://github.com/werneryang/investment-research-os/blob/13ce8143dd7d02f9ba5c2349ab713fadf0907fc7/methodology/records/sec-aapl-supplier-concentration-20261117.yaml)。以下是供应商自己的收入集中度，财年按各供应商日历，**不是 Apple 的采购份额、供应商排名或独家性**；经合同制造商/分销商的最终客户归因也不等于 Apple 直接付款。

| 供应商 | FY2026 / FY2025 / FY2024 | 口径及边界 | 记录字段 |
| --- | --- | --- | --- |
| Cirrus Logic | 约 91% / 89% / 87% | Apple 最终客户；占 Cirrus 总净销售额，经多个合同制造商 | `S.findings.cirrus.periods/percent_supplier_revenue/denominator/channel` |
| Skyworks | 61% / 67% / 69% | Apple 最终客户；占 Skyworks 净收入，经多个分销商及合同制造商 | `S.findings.skyworks.periods/percent_supplier_revenue/denominator/channel` |
| Qorvo | 约 50% / 47% / 46% | Apple 最终客户；占 Qorvo 总收入，经多个合同制造商 | `S.findings.qorvo.periods/percent_supplier_revenue/denominator/channel` |
| Qualcomm | FY2026：至少 10%；其余期别未作 Apple 具名比例归属 | 占 Qualcomm 合并客户/被许可人收入，含 QCT/QTL；匿名 x/y/z 表不能映射到 Apple | `S.findings.qualcomm.period/apple_percent_lower_bound/denominator/identity_limit` |
| Broadcom | 无可归于 Apple 的具名比例；最新合资格年报为 FY2025 | 匿名客户 FY2025/24/23 占 Broadcom 净收入 32%/28%/21%，身份未披露；不能认作 Apple，也不否定上表具名业务关系 | `S.findings.broadcom.anonymous_customer_percent/denominator/identity_limit/latest_annual_limit` |

【事实】S 选取截至原截止时间前已被 SEC 接收的五家公司原始年报；技术取件晚于截止，原始申报 URL、期末、接收时间及哈希见 `S.sources`。补证的独立只读复核逐字段对照 62 项、零差异，见 `S.verification.independent_review`。该五家为本次指定样本，不是供应商全集；跨公司比例的分母不同，不相加、不据此推算 Apple 采购额。

## 质量与可持续性

【事实】Apple 自己披露直接零售/线上/销售团队与运营商、其他转售商等间接渠道并行；上述约 60% 是整体间接渠道比例。苹果公布的组件伙伴关系给出了部分产品/技术层面的直接证据，而不是采购权重、独家性或盈利贡献。【推断】跨硬件与服务的互补性值得后续研究，但本次不据此判定护城河强度或财务回报。

## 指引与待验证的判断

【事实】部分公告含未来交付或扩产表述；`R.relationships[id=u_amkor_future]` 仅证实 Apple **将成为** Peoria 厂首批客户之一，非该厂已经量产/发货。【推断】后续用 Apple/Amkor 官方更新检验是否转为实际关系。另按原公告分别核 Chase 是否接手 Apple Card（约 24 个月为预计而非既成事实）、Gemini 合作功能是否上线、TDK 美国传感器供货和 Perryman 多年钛材承诺是否兑现；结果第 7–8 节登记核验节点，未披露则记无法核对，不将计划算成已交付或业绩预测。

## 主要风险与不确定性

- 【事实】Supplier List 的当前原件/覆盖期未核，且该名单即使列厂址也不证实产品型号或组件；本表的任何产品级边均非由名单单独推出。见 `R.supplier_list`。
- 【事实】全球现行具名总装分配无截止前可核的一手证据；Foxconn/Quanta/Pegatron 的 Apple 直接提及只属历史证据，不能写成 FY2026 某型号的主要装配份额。见 `R.relationships[id=h_foxconn]` 及 `R.limitations_and_failures`。
- 【事实】美国 AMP 官方公告偏美国项目；不能代表全球供应链。企业使用、运营商渠道、AI/支付生态不能互换为直接客户/供应商。

## 未覆盖与可选补充

- **已处理 A：**对 FY2026 10-K、Apple/合作方一手网页和具名关系完成单轮补证；另按五家供应商截至原截止时间前的原始年报核其自身 Apple 收入集中度，并独立复核 62 字段零差异。仍未证实 Apple 的采购份额/供应商排序、全球具名装配或具名渠道销售权重，保留为数据不足。
- **可选 B：**如用户另行同意指定 Apple Supplier List PDF 原件（具体文件名/大小以取得时核），可核清当前版本、实体与厂址；仍不能仅凭名单证明具体供货。
- **方法缺口 D：**G18、G23–G25 已反馈方法库，开放未关闭；产品级证据门槛、跨层角色与“主要”筛选尚无完整专用卡。

## 出处

- [Apple FY2026 Form 10-K（SEC，2026-11-03）](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm)。
- Apple 与交易对手一手公告的逐条 URL、日期、定位、检索与可复现计算：[公开走查记录](https://github.com/werneryang/investment-research-os/blob/main/methodology/records/sec-aapl-value-chain-20261117.yaml)，字段 `sources`、`relationships`、`financial_context`、`verification`。对应结果 ID：`AAPL-20261117-value-chain`。
- 五家供应商原始 SEC 年报、收入集中度口径与独立复核：[公开记录](https://github.com/werneryang/investment-research-os/blob/13ce8143dd7d02f9ba5c2349ab713fadf0907fc7/methodology/records/sec-aapl-supplier-concentration-20261117.yaml)，字段 `sources`、`findings`、`verification`（待同任务重新放行发布）。
