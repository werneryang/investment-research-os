# 美国行业的经济表现、企业盈利与股票回报

实现日期：2026-10-25。目的为历史研究，不是投资组合建议。此文描述已交付的研究范围；不能把程序完成理解为所有经济问题已得到因果解释。

## 交付与运行

| 研究 | 内容 | 更新方式 |
| --- | --- | --- |
| `us_industry_12` | 12 行业长期收益、实际收益、风险、因子、经济背景 | Pages 工作流重新取得数据、重算、校验 |
| `us_industry_49` | 49 行业细分、同口径市场及风格比较 | 同上 |
| `us_industry_dossier` | 12 行业总览加能源、批零、半导体/软件/计算机服务的历史财报与估值、指引案例 | 本地证据准备后重算；发布经过校验的固定报告 |

```bash
# 取得新的 French、FRED 输入；已有版本默认复用，--refresh 可明确刷新
uv run python scripts/prepare_industry.py

# 使用已有 71 个 FSDS 原始 ZIP；不改写 E1 的 15 公司分区
uv run python scripts/build_industry_fundamentals.py --cutoff 2026-10-25
# 下载并缓存指引原文与 34 份 Damodaran 行业 XLS
uv run python scripts/prepare_industry_cases.py
uv run python scripts/prepare_industry.py --evidence

uv run iros run config/studies/us_industry_12.yaml
uv run iros run config/studies/us_industry_49.yaml
uv run iros run config/studies/us_industry_dossier.yaml
uv run iros verify <run_id>
uv run iros site --out _site
```

数据、原始公告和原始财报保存在忽略的 `data/`，报告在 `reports/`，固定输入清单在 `runs/`。每次运行冻结研究定义、输入版本、代码指纹及解释规则。证据包保存每条事实的申报号、科目、期间、原文件 SHA256 与定位；换包后旧包的删去项目不会被当作当前事实复活。准备脚本保留源文件缓存；新一轮源材料核验应使用新的缓存/版本，而不是覆盖原件。

原始 French、SEC、Damodaran 和公司公告没有启用公开数据归档。公开档案保存分析结果、少量引用与报告；财报逐公司事实及完整估值工作簿不嵌入报告。云端没有这些固定输入时，不能声称已在那里完整复算本地专题。

## 市场与宏观计算

- 月度主样本 1926-07 至 2025-12；固定比较窗 2001–2025、2010–2025、2016–2025。2026 另列未完结年度累计收益。
- 12 与 49 行业使用 French SIC 分组的总收益。早期尚不存在的 49 行业不补齐、不跨缺月拼接。图中长期比较须看相应完整覆盖。
- 几何年化收益、月度标准差乘 √12、相对市场财富、跟踪误差、月度最大回撤与恢复月。回撤的高水位包含最初的财富 1；月度观察仍会遗漏月内更深的跌幅。
- CPI-U 未季调指数做起止端点购买力调整。2025-10 缺失不插值；端点年化回报不需要中间月份完整，月度实际风险不能据此补算。
- CAPM、FF3、FF5+MOM 每个模型使用自身文件的市场和 RF；FF3 与 FF5 的市场因子历史值并非处处相等。月截距 ×12 是算术年化 alpha。HAC 使用 Bartlett 权重、6 个月滞后及有限样本乘数；95% 区间与 p 值为渐近正态近似。BH 调整只在同模型、同窗口的行业 alpha 家族内进行，属于探索性分析。
- 5、10、20 年滚动收益和每五年末的 10 年滚动 FF5+MOM 暴露保存在结构化结果。所有行业相关矩阵也保留，避免只挑某个相关性展示。
- BEA 实际增加值从 2005Q1 开始；BLS 全体雇员工时和工资始于 2006 年，端点比较统一为 2006Q2–2025Q4。月度转季度要求三个月齐全。链式美元不可直接跨行业相加；时薪为名义值，产能利用率要区分比率变化与百分点变化。
- 经济相关使用环比增长、完整季度日历和 -4 至 +4 季全部滞后，分 2005–2025、2005–2014、2015–2025 三窗。不检验因果，也不把当前修订版本当成当时信息。
- 另列互联网泡沫、金融危机、2014–2016 油价低迷、疫情初期、2022 通胀时期；固定起止点，不按最差表现反向挑选。衰退、通胀和政策利率分组为事后条件统计，月均收益 ×12 不是不连续状态的复合持有收益。

French 年度表是独立校核：月度和年度均按 0.01 个百分点四舍五入，核对传播后的舍入区间，而非任意放宽固定容差。原始 ZIP 的抽查用独立标准库读取器完成，不复用接入器解析。

## 历史盈利样本

`config/industry.yaml` 定义专题和对应限制：能源 SIC 1200–1399、2900–2999；批零 5000–5999（含餐饮）；科技 3674、7370–7379（含计算机服务）。这些不是 GICS 行业，也不复制 French 全部成分。

从各期 `sub.txt` 选 10-K/10-K/A、美国营业地址和当时 SIC；不使用今天的股票名单。选取当年财年末的、USD、US GAAP、合并口径事实。期间额必须 4 个季度，余额必须 0 个季度；排除 co-registrant 和分部数据。不将相同 CIK 的多个财年末重复计入同一日历年，披露被压缩的财年变更记录。

首次有资格申报决定当期成员分类；指标在同一申报内按明确别名优先级选择。只纳入当年报告及修正报告，保留首次值和最新修正值，不混入以后年度比较列的重述。存在同申报、同标签的矛盾值时排除而非任选。原始 FSDS 的期末日期精确到月末，不冒充公司的实际财年日。

指标包括营收、母公司净利润、经营利润、经营现金流、购建固定资产现金支出、资产、权益、现金、长期债务当前及非当前部分、分红、回购与股份薪酬。两个债务部分不被某一个别名冒充为“总债务”。缺失不是零；公司自定义科目、外国会计准则及分部口径未强行补入。

每年披露全部有资格公司、进入/退出、各指标有效与缺失数量。增长只在前后两年同指标的共同公司上计算；利润率只在同时具备分子分母的公司上聚合。现金流减资本开支只是本研究的简化自由现金流，不是严格 FCFF。回购不在每股增长之外重复加成回报。收入前五名占比是此申报样本的收入集中度，不是股票权重或美国国内市场份额。

主要限制：2009–2012 的 XBRL 分阶段覆盖；SIC 粗分；不同财年和全球业务；发行人可能含母子申报主体，未建立控制关系消除重复；上市普通股资格、历史市值权重和退市回报尚未验证。因此可研究样本经营的变化，不能把这些合计称为完整上市行业利润。

## 估值与前瞻证据

French BE/ME 使用源年度标签，主要作为长期估值背景，不等于年末 PE。公司数、平均市值与等权/市值加权差异不能推出股票集中度。

Damodaran PE 和利润率共 34 份 2010–2026 年 1 月 XLS 已接入，保留原始行业名称、公司数量、列头、单元格、缺失和 SHA256。按归档页链接标签取日期，特别是 `pedata24.xls` 对应 2025 年 1 月。供应商、行业分类与聚合公式随时间可能变化；公开报告只选 6 个同名行业、4 个时点的 PE/净利率作为背景，不把它们拼成 French 回报分解。前瞻 PE 也不被当作已核验的历史分析师一致预期。

管理层指引包含 AMD、Amazon、Intel、Adobe、NVIDIA、Salesforce 六家公司，选定目标跨 2020–2025，另加 Intel 2022 全年同目标修订，共八条预测。数值、预测发布日期、目标期、结果日、会计口径、原文定位及文件校验值分别存储；先检验预测严格早于结果，再比对区间/中点。Intel 的不同目标不混做修订。Salesforce 使用公告四舍五入的 98 亿美元，偏差明确标为近似。原文锚点机器核对不是人工验收，记录 `human_status=unreviewed`。

这是选择性案例研究，不是完整季度覆盖，不计算全行业“超预期率”。管理层指引和分析师一致预期始终分开。

## 数据足够与不足的边界

当前免费资源足够完成上述三项研究，不需要付费 API 或新账户。已实现收益、经济背景、历史专题盈利、独立估值快照和可核验指引案例。

以下功能未以替代数据冒充实现：完整历史普通股成分/权重、严格盈利—估值—分配回报恒等分解、全市场历史分析师一致预期、日度公告事件研究、季度 TTM 和可比季度盈利、全球分部经营、1997 起全套经济延长。它们是后续扩展，需要各自验证；年度事实准备不能自动证明季度推算可靠。EIA WTI 现货价已通过 FRED 接入；QFR、EIA 产量/产能、BLS 生产率和更细 PPI 可按下一项具体研究问题接入，当前不形成新的必要依赖。

## 依据

- [French 行业定义](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library/det_12_ind_port.html)、[49 行业](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library/det_49_ind_port.html)
- [SEC FSDS](https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets)、[SEC API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [BEA 行业 GDP](https://www.bea.gov/data/gdp/gdp-industry)、[BLS CES](https://www.bls.gov/ces/data/)
- [Damodaran 归档与分类变更说明](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/dataarchived.html)
- [FRED 制造业增加值](https://fred.stlouisfed.org/series/RVAMA)、[矿业](https://fred.stlouisfed.org/series/RVAM)、[信息业](https://fred.stlouisfed.org/series/RVAI)、[批发](https://fred.stlouisfed.org/series/RVAW)、[零售](https://fred.stlouisfed.org/series/RVAR)

具体指引的原始公告链接列于报告与 `config/industry-guidance.yaml`。技术验证记录见固定研究运行；人工作出的产业解释仍应检查分类、样本和口径。
