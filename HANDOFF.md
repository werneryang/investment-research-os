# 待接手事项

按 README「开发流程」约定：开始任务时先读本文件，结束时如有待接手事项再更新。已完成的条目保留结论，方便核对。

更新于 2026-11-26。

## 1. FRED 当前版本序列改走官方 API（已完成）

- 改动：提交 eb0c700，合并 073b3ca。新增接入器 `fred_api_current`，35 个数据集从 `fred_graph` 改为 `fred_api`。迁移时与图表导出的最后一版逐值比对，核验记录在 `config/sources.yaml` 的 `fred_api` 下。
- 原因：fred.stlouisfed.org 的图表导出自 2026-11-06 起不再响应本项目的请求标识。
- 运行 073b3ca 时仓库还没有 `FRED_API_KEY` secret，35 个数据集全部立即失败，属预期。
- 验证：secret 添加后，手动触发的网站运行 [43719949268](https://github.com/werneryang/investment-research-os/actions/runs/43719949268) 成功，35 个 FRED 数据集全部创建了新版本，0 个失败。

## 2. CI 取数时限与同一来源不响应跳过（已上线，供参考）

- 网站工作流的取数步骤设了 8 分钟时限，见提交 157f874。
- `iros fetch --all` 遇到同一来源连续 2 个数据集超时，就跳过该来源的其余数据集。阈值在 eb0c700 中由 3 改为 2。
- 2026-11-15 起连接被重置（`Connection reset by peer`）也计入这条规则（`cli.UNRESPONSIVE_SKIP_AFTER`）。404、解析失败等只关乎单个数据集的错误不计入。

## 3. Ken French 数据库连接被重置（未处理）

- 现象：mba.tuck.dartmouth.edu 自 2026-11-15 起在 CI 和本机都被重置连接（`Connection reset by peer`），22 个 `french_*` 数据集取不到。本机定时快照到 2026-11-14 都还正常。运行 43719949268 中，这 22 个数据集各重试 3 次后全部失败，取数步骤用了 2 分 37 秒。现在连接重置已计入第 2 项的跳过规则：只尝试 2 个，其余 20 个标为 skipped。
- 影响（CI 中取得的数据随运行环境丢弃，每次运行都要现取）：
  - `us_industry_12`、`us_industry_49`：在 CI 中运行失败（缺 `french_ind12_vw` / `french_ind49_vw`）。网站恢复的是档案里的旧运行，两项最近一次运行都是 2026-11-06（当时因 FRED 失败停在这里），FRED 恢复后仍无法刷新。
  - `us_asset_history`、`us_asset_history_last_25y`：仍会运行成功，但缺少可选输入 `french_ff3`，股票的月度波动与最大回撤，以及与 French CRSP 市场年度收益的交叉核验，都会缺失。
  - `us_industry_dossier`：CI 不运行，网站用已核验的档案，不受影响。
  - 地区因子（`french_developed3` 等 7 个）只登记在网站能力地图的「跨市场比较」中，没有研究使用，只是不再更新。
  - 本机：`data/normalized/` 里保留着 2026-10-26/27 取得的最新版本，此后快照内容未变。本机运行行业研究不受影响，只是停在 French 最近一次发布的数据。
- 排查结论（2026-11-15）：故障在服务器一侧，对所有访问者都一样，不是针对本项目，跟请求标识无关。
  - TCP 能连上 129.170.225.178 的 443 和 80 端口。但 HTTPS 在 TLS 握手发出 Client Hello 后立即被重置，这时还没有发送任何 HTTP 头，请求标识根本到不了服务器。HTTP 请求发出后同样被重置。
  - 本项目的标识、Python 默认标识、curl 默认标识、浏览器标识四种都失败；数据库首页、数据文件、直接用 IP 访问也都失败。
  - 第三方多地检测（美国、瑞士、香港、新加坡等 8 个节点）全部返回 `Connection reset by peer`。同一域名下的 www.tuck.dartmouth.edu 解析到另一台机器，能正常响应。
  - 公开网络上没找到停机或迁址公告。
- 待办：等服务器恢复，期间不要改代码去绕。恢复后确认 22 个数据集重新取得成功，`us_industry_12` / `us_industry_49` 在 CI 中产生新运行。

## 4. 用户待办

- [已完成 2026-11-15] 给编排仓库加共享权限配置（本机配置，不进任何仓库）。

## 5. 网站搜索与主体识别（已上线，留两项未做）

- 已做：搜索框里的多个词按词分别匹配，没有对应登记内容的词列出并忽略（提交 4190088）。关键人物登记在 `site/content.yaml` 的 `entity_people`，人名只作检索入口，指向已登记主体。
- 事件类问题：研究分类增加第 11 类「事件与反应」（事件事实与时间线、事件窗口的价格反应、同类事件的历史比较），登记了两条规划，没有研究。搜索里的“事件”“辞职”“离任”指向这一类。
- 第一项事件研究已上线：`event_nvda_ceo_transition_2026`（事实与时间线，设计见 docs/study-events.md）。
- 基准已接入：FRED 的标普 500（只有最近 10 年）、纳斯达克综合与纳斯达克 100 日收盘值（`fred_sp500`、`fred_nasdaqcom`、`fred_nasdaq100`，价格指数，不含股息，只在本机使用）。
- 未做：「事件窗口的价格反应」还缺日度个股价格。免费来源都要注册：Stooq 的下载加了浏览器验证，不能用脚本绕过；Tiingo 免费版限「仅内部使用、不得展示或分享数据」；Alpha Vantage 免费版每天 25 次请求。选定来源、由用户注册并把 key 放进 `.env` 之后再接入。方法用方法库的 event-study-abnormal-return 卡（MacKinlay 1997，缺口 G07 部分关闭）：卡里仍没有依据的三点是事件公司占基准指数大权重时怎么办、开盘前发布的第 0 天规则（本例 8-K 在开盘前接受）、单次事件的检验，研究里要按卡标明这些是整理时补充。关键人物目前只登记了 NVIDIA 一人。中文没有分词，只在分类词处拆开，“英伟达黄仁勋辞职”里的公司名和人名连在一起时认不出。
- 维护：职务是 `as_of` 当日出处所载。公司披露人事变动后，给条目补 `until` 和出处，不删除条目，旧人名仍要能找到主体。
- 本仓库没有对应研究时怎么查方法库：网站只回答本仓库登记了什么，不读方法库（方法库私有）。要找方法，在方法库的会话里按它的查库测试流程做，结果留在方法库；查到的方法要执行时再回到本仓库。

## 6. NVIDIA 首席执行官离任的事件研究（2026-11-26 已更新：回任）

- 登记在 `config/events/nvda_ceo_transition_2026.yaml`，查阅日 2026-11-15。原文和证据包只在本机（`data/events/`），网站显示的是存档里的运行。
- 11 月 17 日 2027 财年第三季度业绩公布后：查 EDGAR 有没有新的 8-K 或 10-Q 提到离任或继任，把新事实加进登记，日程项按实际发生的情况改写，`as_of` 改为新的查阅日，然后 `iros event fetch`、`iros event bundle`、重跑研究并存档。
- 继任者任命后同样补登记。关键人物登记（`site/content.yaml` 的 `entity_people`）要给新任者加条目。
- [已完成 2026-11-26] 查阅 EDGAR 到 2026-11-26：11-23 开盘前接受的 8-K（0001045810-26-000090，第 5.02 项）登记回任，附件 99.1 登记 Jones 留任主席、调查继续、新设国家安全与出口管制委员会、招聘首席合规官；11-17 的 8-K 第 2.02 项把原登记日程改为已发生。`as_of` 改为 2026-11-26，标题改为「离任与回任」，研究重跑并单独归档。回任没有新的继任者，`entity_people` 不用加人。
- 待办：调查委员会有结论、或 10-Q 提到这次变动时再补登记。

## 7. 季度财报研究（Alphabet Q3'26 已上线；分支已配置化，可新增任意公司）

- 新增研究 `earnings_googl_2026q3`（分支 `earnings_quarter`、证据包 `earnings_evidence`、登记 `config/earnings/googl_2026q3.yaml`），设计与核对见 [docs/study-earnings.md](docs/study-earnings.md)。页面 `studies/earnings_googl_2026q3/`，与年度研究 `company_alphabet` 互相链接。
- 原因：网站上 Alphabet 只有 2025 财年的年度数据，Q3'26 的走查记录（`methodology/records/sec-googl-earnings-20261116.yaml`）网站生成器不读。
- 原文只在本机 `data/earnings/filings/`（不入库）；CI 不重算，网站显示归档的运行（archive 分支）。
- 未覆盖：TPU 与并购的收入桥（发行人未披露）、电话会（逐字稿使用条款未核清，未读取）、行情反应（需选定可展示的日度价格来源）、估值与预期。
- 2026-11-17 配置化：分支 `earnings_quarter`、关键发现、页面与英文按登记里的 `profile` 生成（季度列含非日历财年与 52/53 周、分部、会计恒等式、比率、页面行与图表、措辞），不再写死 Alphabet；展望、积压订单、恒定汇率、每股收益、示意算术都是可选项。Alphabet 的登记已迁移，重算结果与此前归档的运行逐字段一致（只有重命名的键、新增的 profile 与规则版本不同）；关键发现规则升到 `earnings_quarter-findings.v2`，指纹变化使旧运行用新代码重算的校验值不同，因此 Alphabet 重新运行并归档（旧运行留在档案里，网站只显示其记录的发现并注明）。`iros verify --all` 遇到无法重算的运行（如早于 profile 的证据包）现在逐条报 `[error]` 并继续，不再中止。
- 新增公司的步骤清单：[docs/study-earnings.md](docs/study-earnings.md) 第 8 节（`config/earnings/<ticker>_<fy><q>.yaml` + `config/studies/earnings_<ticker>_<fy><q>.yaml`，`fetch`/`check`/`bundle`/`run`/`verify`，与走查记录逐项对照，放行时单独归档再合并）；首页入口用研究条目的 `home_group`（第 9 节）。
- 注意：`iros earnings fetch/check/bundle` 一次处理 `config/earnings/` 下全部登记，所以每家公司的原文都要在本机；证据包随登记变动换版本，已归档的运行不受影响。
- 未覆盖：TPU 与并购的收入桥（发行人未披露）、电话会（逐字稿使用条款未核清，未读取）、行情反应（需选定可展示的日度价格来源）、估值与预期。
- 待办：（1）每家公司的下一个季度公布后更新（新建下一季度的登记与研究，保留上一季度的归档）；（2）2026 年第三季度新闻稿的 EDGAR 接受时间没有记录，登记用发布日；（3）第二家公司上线前，用它的真实申报走一遍 `profile`，看有没有科目是现有字段表达不了的（例如银行、保险没有营业成本），需要时再放宽必备科目。

## 给方法库

本仓库的会话执行方法卡时，如果碰到方法本身的问题（卡里步骤写不清、取数口径缺失、两张卡互相冲突、某步在本公司不适用），就记在这里。方法库会话（research-method-extraction）开始工作时会来读，登记进它的缺口台账；之后请本仓库的会话把对应条目标为「已处理」。

格式每条一行：`- [未处理] 日期 · 卡 id · 第几步 · 问题一句话 · 出处（研究或走查记录路径）`。处理后把 `[未处理]` 改成 `[已处理 日期]`。

本仓库公开：只写卡 id、步骤号和问题，不抄方法卡正文，不写出处判定、个股判断、邮箱、本机路径或 key。

- [已处理 2026-11-15] 2026-11-15 · 词表（不是某张卡）· — · 本仓库的研究问题词表增加了第 11 类「事件与反应」，方法卡的 question 字段沿用这份词表，请决定是否同步 · docs/research-classification.md §2.2
- [已处理 2026-11-16] 2026-11-15 · event-study-abnormal-return · 所需数据 · 卡写日收益取自「公开行情，复权」，但没写怎样取得、许可有什么限制：准备执行时没找到免注册的免费复权日价（有的来源对脚本下载加了浏览器验证，有的要注册、免费版限个人内部使用），市场指数在 FRED 只有不含股息的价格指数、标普 500 只有最近 10 年；请补「取得方式与许可」或列为执行前提 · HANDOFF.md 第 6 项、config/sources.yaml 的 fred_sp500 核验记录 · 处理结果：已列为执行前提，来源由本仓库定
- [已处理 2026-11-19] 2026-11-19 · 模版（不是某张卡）· 报告的图 · 方法库 templates/README.md「报告的图」表中标「待实现」的图型已可用，请方法库把替代说明去掉 · docs/note-figures.md §3 · 处理结果：方法库提交 c4e0b27 已去掉替代说明，直接写新图型
- [已处理 2026-11-26] 2026-11-26 · market-drawdown-layer-diagnosis · 第 3 步 · 只按利率方向分层：2020-03-18 联储降到零利率后国债收益率一周 +36bp（实质 +69bp），照字面是第 1 层的“利率上升一起重估”，实际是国债被抢着卖成现金（第 3 层）；需要写怎样区分利率预期变化和被迫抛售国债 · methodology/records/fred-us-market-drawdown-2020-20261126.yaml · 处理结果：方法库提交 7978834 登记为 G28、G30
- [已处理 2026-11-26] 2026-11-26 · market-drawdown-layer-diagnosis · 第 3、4 步 · 第 2、3 层分不开（G02）：2024-08-05 利率降而比特币急跌，照第 3 步是第 3 层，但美元没走强、日元（融资货币）急升，更像第 2 层的套息去杠杆；卡的汇率只讲本币贬值和美元走强，没讲融资货币升值 · methodology/records/fred-us-market-drawdown-2024-20261126.yaml · 处理结果：方法库提交 7978834 登记为 G28、G30
- [已处理 2026-11-26] 2026-11-26 · market-drawdown-layer-diagnosis · 第 2 步 · 没说“防御股”选哪些：利率驱动的下跌里公用事业这类利率敏感板块本身会跌（2022-09 跌得比市场多），按它判“撑不住”会误判出第 2 层 · methodology/records/fred-us-market-drawdown-2022-20261126.yaml · 处理结果：方法库提交 7978834 登记为 G29
- [已处理 2026-11-26] 2026-11-26 · market-drawdown-layer-diagnosis · 第 1 步 · 起点在信用层时怎样走：2008 年的基金冻结（2007-08）早于股市见顶，按第 1 步是起点不是加速器，但卡的叙述从第 1 层起跌（卡的方法失效条件已提到这一疑问） · methodology/records/fred-us-market-drawdown-2008-20261126.yaml · 处理结果：方法库提交 7978834 登记为 G31
- [已处理 2026-11-26] 2026-11-26 · market-drawdown-layer-diagnosis · 所需数据 · 美国执行时卡里多项数据无公开免费历史：黄金（FRED 已无 LBMA 金价）、板块 ETF 日价、HYG、FINRA 保证金债务、单一公司 CDS 和 ABS 利差、一致预期盈利修正；ICE 高收益债利差在 FRED 只留 3 年且许可受限。卡的“整理时补充”可考虑写替代指标（Baa 利差、TED 利差、NFCI 分项、VIX/VIX3M、实质利率一周变化）或列为执行前提 · 四份回放记录的 data_gaps · 处理结果：方法库提交 7978834 已登记回放结果；本条没有单列缺口编号，按主题分别归入 G28（黄金）、G29（防御股日价）、G30（保证金债务）
- [已处理 2026-11-26] 2026-11-26 · market-drawdown-layer-diagnosis · 第 4 步 · 补上 FINRA 保证金债务后：月度且滞后一个多月，2020-03 和 2024-08 两次下跌期间一个新数都看不到；2022 年九个月降 25%（价格降 13%），照字面是第 2 层，2008 年反而与价格同步。需要写“大减”的口径（相对价格、速度）和快速事件该看什么 · methodology/records/fred-us-market-drawdown-2024-20261126.yaml、-2022- · 处理结果：方法库提交 7978834 登记为 G30
- [已处理 2026-11-26] 2026-11-26 · market-drawdown-layer-diagnosis · 第 2 步 · 补上日度 ETF 净值后：“撑没撑住”用累计相对表现还是下跌日的跟跌程度，结论不同（2022-10-12 累计撑住，XLU 下跌日比值 1.56）；2024-08-05 防御股撑住，照卡只能判第 1 层，判不出套息平仓的第 2 层 · methodology/records/fred-us-market-drawdown-2022-20261126.yaml、-2024- · 处理结果：方法库提交 7978834 登记为 G29、G30
- [已处理 2026-11-26] 2026-11-26 · market-drawdown-layer-diagnosis · 第 3 步 · 补上黄金后：2008-10 抢美元时黄金在涨（一周 +8.8%），卡的第 3 层只写了黄金跟跌这一种样子；2020-03-23 黄金止跌回升，卡的推翻条件可读出抢现金结束，这条有用 · methodology/records/fred-us-market-drawdown-2008-20261126.yaml、-2020- · 处理结果：方法库提交 7978834 登记为 G28
- [已处理 2026-11-26] 2026-11-26 · market-drawdown-layer-diagnosis · 第 2、3 步 · 两步给出不同的层时以哪步为准：2026-11-20 防御股撑住（第 2 步判第 1 层），同时利率下降而黄金比特币大跌（第 3 步判第 3 层） · methodology/records/fred-us-market-drawdown-2026-20261126.yaml · 处理结果：方法库提交 1c2bb95 登记为 G32
- [已处理 2026-11-26] 2026-11-26 · capex-boom-credit-transition（方法库 1c2bb95）· 第 2 步 · 没有现金流量表时怎样量“内部资金够不够”：1873 年回放只能用资本加债务账户的变化代替资本开支（混着覆盖范围扩大和注水股本），用净收益扣分红对债务的比率代替自由现金流；卡没写替代口径，第一处要猜就在这里 · methodology/records/hist-us-railroad-capex-1873-20261126.yaml · 处理结果：方法库登记为 G33
- [已处理 2026-11-26] 2026-11-26 · capex-boom-credit-transition（方法库 1c2bb95）· 第 3 步 · 卡列的表外承诺都是现代会计项目，历史或没有附注时该找哪些对应物没写；1873 年回放用了租入线路时承担的债息（北太平洋约为自身年息的 19%）、他路或州的担保、地方援建，担保的或有性还取决于付款货币等条款 · methodology/records/hist-us-railroad-capex-1873-20261126.yaml · 处理结果：方法库登记为 G34
- [已处理 2026-11-26] 2026-11-26 · capex-boom-credit-transition（方法库 1c2bb95）· 第 4 步 · 卡的两种循环形式在 1873 年都不是主形式；主形式是承销商以发行人未售出的债券作抵押向它垫款（上限 50 万被突破到 177.5 万，倒闭时对北太平洋贷款占承销商负债 70%），承销商还兼任债券受托人；请决定是否补这一形式 · methodology/records/hist-us-railroad-capex-1873-20261126.yaml · 处理结果：方法库登记为 G35
- [已处理 2026-11-26] 2026-11-26 · capex-boom-credit-transition（方法库 1c2bb95）· 第 5 步 · “被最终需求替代”看量还是看收入：1873-09 至 1876-06 货运吨英里 +13.6%，同期行业总收入下降、运价下降，单看量会判成已被替代 · methodology/records/hist-us-railroad-capex-1873-20261126.yaml · 处理结果：方法库登记为 G36
- [已处理 2026-11-26] 2026-11-26 · capex-boom-credit-transition（方法库 1c2bb95）· 第 6 步 · 只在发行人一层比较债务期限和资产寿命，1873 年得出“没有错配”（30 年期债对长寿命线路），但短期资金在承销商（存款支撑的垫款）和银行（纽约国民银行贷款对个人存款 1873-02 达 203%）；卡没写要不要往融资链上查 · methodology/records/hist-us-railroad-capex-1873-20261126.yaml · 处理结果：方法库登记为 G37
- [已处理 2026-11-26] 2026-11-26 · capex-boom-credit-transition（方法库 1c2bb95）· 第 7、8 步 · 卡的杠杆指标没有历史对应序列（回放改用通知贷款利率、银行贷存比、外国持有比例）；另外高等级铁路债收益率在危机中几乎不动（1873-08 6.06%、10 月 6.49%），损失集中在新线和低等级债，按整体利差看会漏掉信用层 · methodology/records/hist-us-railroad-capex-1873-20261126.yaml · 处理结果：方法库登记为 G38

## 8. NVIDIA FY27 Q3 季度研究：FCF 口径适配与网站待办

- 任务 R-20261117-nvda-earnings，证据见 `methodology/records/sec-nvda-earnings-20261117.yaml` 的 `site_study`。SEC 8-K 的 99.1/99.3 HTML 已有当季报表；缺 Q3 10-Q 不是当前配置的主要阻碍。
- NVIDIA 发行人 FCF 从 CFO 同时扣现金购置固定资产/无形资产及相关本金支付。现有 `earnings/__init__.py` 的 CASH_METRICS、核对和导入，以及 `research/earnings_quarter.py` 的季度公式，只支持 CFO−cash_ppe；页面/发现仍标发行人定义。独立实测会多报本金支付部分，不能直接套用。
- 未创建无效 earnings/study 配置，未执行 fetch/check/bundle/run/verify，未发布研究页。不要把本金混进 cash_ppe，或省略 issuer_fcf 核对后沿用错误标签。
- 原限定范围：增加本金支付科目、FCF 公式与核对/标签支持，补真实科目差异的测试，再按 README 的研究计算/公共契约 PR 流程处理，之后构建并逐字段对照走查。本任务的私有财报结果不因该 site 阻碍而被视为已发布网站研究。
- 后续适配：`profile.fcf_deduct_principal: true` 显式启用独立 `cash_ppe_principal`，核对、证据包、季度/近四季计算与中英页面共用 CFO−购置支出−相关本金的定义，详见 `docs/study-earnings.md`。专项测试 70 项、完整测试 486 项通过；独立只读复核确认 Q3 43,777、Q2 21,341（百万美元），并将现有 Alphabet 登记的季度行、现金转换与中英文现金表同旧实现逐项比较，一致；已归档 Alphabet 运行也复现相同结果校验值。
- 网站仍待办：本次只修代码契约，未新增 NVIDIA 登记、研究配置、运行或页面，也未改写已发布走查记录。下一步从允许使用的同一批 SEC 披露准备登记，逐字段对照、运行/复现、单独归档并验证中英页面与检索后，才可报告 site 已发布。

### NVIDIA site continuation（已上线）

- 已登记 `config/earnings/nvda_fy27q3.yaml` 与 `config/studies/earnings_nvda_fy27q3.yaml`，研究 id `earnings_nvda_fy27q3`。仅直接比较 FY26 Q3、FY27 Q2、FY27 Q3；缺失的分部利润明确列出，不将合并利润伪装为分部。rounded 分部/平台收入保留原精度和出处。
- 新登记使用 `release.disclosure_form` / `disclosure_date`，不将 8-K 日期写成 10-Q 日期。网页仍需最终干净运行、独立对照、单独归档及部署后中英页面/搜索核验，当前不能报告已发布。原走查记录字节保持不变。
- 配置及适配验证：493 项完整测试通过（173.38s），财报专项 77 项通过；当前全体登记 check 为 15 文档、255 数值、63 恒等式、25 摘录。此前初轮的主体 id 与研究清单/数量测试失败已修复并完整重跑通过。独立只读复核确认数值和披露元数据，不代表人工审计。
- 正式本地交付已完成：干净 commit `f0623d4bad69951a999e734d3c30f25e51a7963a` 的 run `earnings_nvda_fy27q3-20261118T004852Z-78b63678`，`dirty=false`、verify reproduced，结果哈希 `8821577900879784564de2b8dc91bc6838ff8354c77e0403ba9af319df588dcd`。85 项走查对照及独立 97 项数值核验零差异；中英当前结果链接指向正式 run。只归档该运行到 archive commit `26243a164e6db748f2f2b9887d5d357a92df624f`，未归档原始文件或未获登记许可的数据集。验证记录见 `methodology/records/sec-nvda-site-20261117.yaml`；最终部署/页面/检索证据随对应 main Actions 回报核对，不以本地构建冒充上线。

- 上线核验完成：main merge `1e42dd8a61190729cc1f34451858c63a40714b3b`，[Actions 44211554003](https://github.com/werneryang/investment-research-os/actions/runs/44211554003) success。中英 NVDA study 实页及 NVDA/NVIDIA 实际搜索均已核对；正式 run 是唯一线上当前结果，原走查字节未改。

## 9. 公开研究报告（notes，已上线）

- 站点从 `notes/companies/` 读取通过导入门槛的可读 Markdown 报告；不复制 results。报告与 study 分开建模/计数，接入公司、关键词及报告日期筛选，中文页 noindex、入口 nofollow，以页面 meta noindex 请求不索引（已移除无效项目 robots）；这不是保密或索引移除保证（README 有主机根限制）。
- 导入先检查真实 reports 路径、公司与日期；仅对已验证公开 record 指针和私有结果 ID 做确定性清洗，拒绝未知路径、邮箱/key、用户专属标记、未核验代码仓库链接、原始 HTML/图片和超阈值引用。构建逐份重检，坏副本不进入页面/目录，但不得将坏源稿提交到公开 git。
- 已从原 owner 已推送提交固定字节导入 AAPL-20261117-value-chain 与 GOOGL-20261116-q3-26，两份通过公开边界；不取 AAPL 未提交的工作树改动。NVDA 初因作者元数据的 blockquote 样式触发保守引文门槛；原 owner 已将自写元信息改为普通段落并推送，固定字节重新导入后也通过。没有删除信息、修改数字或放宽引用门槛，也未断言第三方侵权。
- 代码完整测试 553 项通过（184.90s），新报告专项 60 项通过；独立边界复核发现的编码/格式化/跨行标记、长引用、标题分隔与未知仓库问题已补回归。正式 PR 与 live 报告页面核验尚未完成，不能把本地构建当上线。
- 三份副本现均已通过：AAPL、GOOGL 来自此前已推送版本；NVDA 使用 owner 后续已推送的元信息排版修正版。复制时只读固定 Git blob，不改私有仓库或任何原 NVDA 记录。正式部署后须逐页检查 noindex、目录与实际公司/日期查询，再报告上线。
- 合并前最终复核：三份复制正文全部通过独立边界及隔离渲染核验；加入报告 ticker/id/date 元数据搜索后，553 项完整测试再次通过（171.66s），报告/导航专项 83 项通过。待本 PR 部署及逐页 live/noindex/查询核验，部署完成信息随回报记录。

- notes 上线完成：PR #29 merge `5ce1627f6f3a3aff7eb6d801541acbb7e53d4210`，[Actions 44218144615](https://github.com/werneryang/investment-research-os/actions/runs/44218144615) success。三份报告、公司/日期目录 noindex 及实际 ticker/公司/日期查询已核验。项目 robots 不等于域名根策略，移除无效文件/文档澄清已另排在 TSLA 与 AAPL 补证之后；不向域名根新增 Disallow。

- 2026-11-19 报告间引用：company-dossiers 结果新增 `builds_on`/`see_also` 后，报告里会有指向其他报告或结果的相对链接。`clean_report` 现在把已发布报告的链接换成站内页 `../../../<代码>/<日期>/<id>/`，未发布报告、结果文件和其他私有文件只留「（见 <id>，未公开）」纯文本，走查记录链接保留为公开 GitHub 链接；构建时站内链接目标不在本次发布中的报告记 `unresolved_note_link` 不发布。网站工作流构建后加了 `iros notes check --site _site`，任何页面链接私有仓库或本机路径即停止发布。规则见 README「公开边界与研究报告」。已发布的三份报告检查过，没有违规链接，未改动。
- 待办：被引用的报告晚于引用方发布时，引用方里只有纯文本 id；那时重新导入引用方（固定 owner 已推送字节）才会换成链接，目前没有自动重导。

## 10. TSLA 2026 Q3 site backfill（进行中）

- 使用已发布 `methodology/records/sec-tsla-earnings-20261116.yaml` 同批 SEC HTML，不改该记录（SHA256 `a7ff27c03a131763d215d39cf05ad7048766238e75c338a077499956815647f0`）。原结果与走查已完成；本项仅补季度研究。
- 已识别适配点：单季 CFO/现金 PPE 由累计期间相减；现有现金流入口只支持直接数值存在性，必须保留累计输入/减算式与源日期，不能拿派生值冒称原表直接披露。Tesla 正式分部以毛利润披露，不可套成分部营业利润或 EBIT。先核同批原件，再作必要代码/契约 PR。
- 适配与准备核验：累计现金流双来源/期间校验、分部毛利润标签和显式机械现金差额均已实现；独立源表230项及配置/preview454项零差异，父走查对照193项一致。原四份文件无发行人 FCF 定义，不冒用该标签；旧 GOOGL/NVDA 正式固定输入仍可复现原结果。正式 clean run、归档与部署尚待最终核验。
- 正式运行 `earnings_tsla_2026q3-20261118T022512Z-67f3da6c` 来自 clean commit `539fde371b4a5e6f0be786712f375341ab2fcb36`，dirty=false、verify reproduced，结果哈希 `8c99a7540605b4c3784a47cbee81f3e0e3e03f9b329945ab56a9f196e03f45e4`；完整测试586项通过（174.05s）。单独归档6路径至 archive `50ffd961f017aa576b24e56cd9e8c32deaea2e26`，不归档原件或未授权输入数据。当前 PR 合并和 Actions/中英实页/Tesla/TSLA 搜索仍是独立待核步骤，验证记录 `methodology/records/sec-tsla-site-20261117.yaml`。

### TSLA 部署核验完成与 robots 清理

- TSLA PR #30 merge `a3b3bff8ee591c6b6f12c3455be21574206f1a11`，[Actions 44223350617](https://github.com/werneryang/investment-research-os/actions/runs/44223350617) success。中英文 live study 均 HTTP 200、指向正式 run；实际中文 Tesla/TSLA 与英文 TSLA 搜索及点击季度研究通过，study `earnings_tsla_2026q3` 状态 published。原走查及验证 checkpoint 不改写。
- AAPL 供应商新补证已独立复核并回传 lead，原走查不改；新记录在任务 ledger 中，未提交待 main 重新放行。
- 队尾清理：不再生成项目子路径 robots.txt；报告/目录继续 meta noindex，入口 nofollow，不向域名根添加 notes Disallow。部署及 live 文件移除仍待本次 main 推送后的 Actions 核验。

## 11. 研究报告图块（NVDA、AAPL、GOOGL 已实现；14 种图型）

- 新增 `config/note_figures/<报告 id>.yaml`，由 `site/note_figures.py` 从公开走查记录取数，画成不依赖脚本的 SVG，插入报告页。规则与写法见 [docs/note-figures.md](docs/note-figures.md)。报告正文不改；正文中的【事实】等标签渲染成带颜色的标签（对全部报告生效）。
- NVDA FY27 Q3：数字条、五季营收加 Q4 指引虚框、利润率与 CFO/净利润小图、承诺分行不相加，共 4 个图块。
- AAPL 产业链（2026-11-19）：数字条、收入结构条（`stack`）、层次 × 时态矩阵（`matrix`）、供应商依赖斜率图（`slope`）。图块可以挂在三级标题下。矩阵的归类写在新增的补充记录 `methodology/records/sec-aapl-value-chain-layout-20261119.yaml`（原走查记录未改，哈希写在补充记录里，原记录一变图块即失效）。
- NVDA 指引对比上季区间（2026-11-19，`range` 图型）：Q3 实际营收与毛利率都在 8 月指引区间之外，Q4 为本次指引区间；共 5 个图块。
- GOOGL Q3'26：数字条、Cloud 收入与利润率小图、CFO 对资本开支折线、RPO 三季柱，共 4 个图块；2025Q4 的 Cloud 收入取记录里的推得值，图下已说明。
- 待办：（1）**归类待原作者确认**：矩阵的层次与时态归类是 AI 辅助整理（依据走查记录的 `temporal_status` 与 `limits`），图上标「推断」；原作者（research-os 会话）确认或更正后，在补充记录里改 `status`，需要改动时新增一条更正，不改已入库内容。（2）[已完成 2026-11-19] 产业链的「待兑现事项时间线」：`timeline` 图型已实现，见下一条。（3）[方法库已完成 2026-11-19] 方法库的分析结果模版已写「每节首选图」。
- 第三批图型（2026-11-19）：`waterfall` 增长归因瀑布、`funnel` 客户转化阶段条、`tree` 层级树、`timeline` 时间线、`scenario` 情景区间与敏感性条（龙卷风式），5 种都已完整实现，各自带校验（瀑布对不上终点、阶段单位不同或后一阶段变大、树的 id 重复或关系指向不存在、日期不合法或区间倒置、情景区间倒置或超出坐标等都报错），没有只做一部分的。`docs/note-figures.md` 第 3 节的首选图表扩到六类结果（财报后更新、产业链、从头研究其余部分、估值检查、突发事件、持仓复核）。现有报告都还用不到这 5 种，没有给已发布报告加图；测试用夹具（`tests/test_note_figures.py`）。
- 待办：（4）第一份用到这些图型的报告放行后，按记录里的结构化字段写图块；`tree`、`timeline` 需要记录里有节点/关系、事件列表这类结构化字段，走查记录没有时用补充记录（同 AAPL 归类的做法）。

## 12. 市场下跌层级诊断的历史事件回放（执行实测，待用户复核）

- 方法卡 market-drawdown-layer-diagnosis（方法库，draft）的执行实测：四个事件 E1 2022、E2 2008、E3 2020-03、E4 2024-08，每个 3 个观察时点，按卡的第 1–8 步和输出格式填写。记录在 `methodology/records/fred-us-market-drawdown-{2022,2008,2020,2024}-20261126.yaml`，汇总值 `methodology/records/market-drawdown-replay-metrics.json`。四个事件的诊断都与预期层级一致；E3 的“被政策截断”在观察时点内不可验证。复核结论都是 `pending`。
- 取数与计算：`scripts/market_drawdown_replay.py`（直接调 FRED/ALFRED API，用 `.env` 的 key；缓存在 `data/drawdown_replay/`，不入库），测试 `tests/test_market_drawdown_replay.py`。`--offline` 只用缓存重算。没有在 `config/datasets.yaml` 登记新数据集（methodology 不接入研究体系）；NFCI 及分项、STLFSI4、VXVCLS、TEDRATE、CBBTCUSD、DEXJPUS 是脚本直接取的。
- 时点规则：日度收盘值取观测日 ≤ 时点；周度或会修订的序列在 ALFRED 有版本时取当日版本，没有时用当前版本按发布滞后截断并标 `post_hoc_vintage`（2008 年的全部周度指数、2022 年以前的 STLFSI4）。French 12 行业月度收益当时未公布，只作事后对照，原始值不入库。
- 复核日度序列不修订的假设：DGS10、DFII10、BAA10Y、VIXCLS 在有 ALFRED 版本的 38 个时点上，当前值与时点后 3 天的版本逐值相同（0 处不同）；2008 年这些序列没有版本，无法复核。
- 公开输出只含汇总值：标普 500、纳斯达克、比特币只留百分比变化；不取 ICE 高收益债利差。
- 缺口：黄金、板块 ETF 日价、HYG、FINRA 保证金债务都没有接入约定，按默认做法记为缺口并已向发起会话说明；如用户选定来源，补取后重跑。四份定性文献只核实了书目，没有逐页核对正文。
- 写回方法库：`executions` 条目草稿交给 research-method-extraction 的会话，本仓库不写。方法问题见「给方法库」2026-11-26 的八条。
- 2026-11-26 复现与前瞻登记（E5）：用同一段 2026 年 10–11 月行情复现这张卡，记录 `methodology/records/fred-us-market-drawdown-2026-20261126.yaml`（来源偏差最强，只算复现）。前瞻登记 `methodology/playbooks/market-drawdown-us-20261126.yaml`，登记于 2026-11-26，提交后不改；**2026-12-10 前后回看 C1–C5**（作证、议息、抢现金是否结束、第 4 层、反弹可信度），**2027-02-10 前后回看 C6–C8**（台积电法说会、四家资本开支、两个底）。回看另写记录。ICE 利差只在本机（`data/drawdown_replay/ice_local_E5.json`）。台股外资与融资、韩国 KRX 买卖超：用户 2026-11-26 决定这次跳过，台韩只用了汇率。NVIDIA 离任、回任两个事件窗口已在同一记录里算（用户下载的纳斯达克日收盘价，只在本机），只用于检查卡的“第 2、3 层时个股反应被污染”这条提醒，不是网站上的事件反应研究。
- [已完成 2026-11-26] 方法库提交 7978834 已登记四条执行记录（复核均为 pending）和缺口 G28–G31：G28 第 3 层怎样认，G29 防御股的量法，G30 第 2 层指标的频率和口径，G31 起点在信用层。「给方法库」八条已标为已处理。待办：用户复核四条执行记录。
- 重跑（2026-11-26，补充数据）：用户手动下载黄金（World Gold Council）、SPY/XLU/XLP/XLV/XLF/HYG 发行商每股净值和 FINRA 保证金债务 Excel，放在 `data/drawdown_replay/manual/`（不入库，公开输出只留百分比和比值）。脚本读到就加算第 2–5 步的补充指标；没有这些文件时 `manual` 块不生成。四份记录各追加 `rerun_supplementary` 一节，第一次执行的内容不改写，四个字段以重跑为准。结论变化：E2 2008-10 不再列第 3 层（黄金在涨）；E3 3-09 照卡判得出不是第 3 层，3-23 黄金止跌触发卡的推翻条件；E4 照卡只能判第 1 层，从“一致”改为“部分一致”；E1 仍是第 1 层，但第 4 步照字面有第 2 层信号。净值不是市价：2020-03 HYG 的市价折价看不到。

## 13. 研究依赖图（已上线，2026-11-26）

- 脚本 `src/investment_os/lineage.py`（ast 与 PyYAML，只读静态信号），命令 `iros lineage`，网站页面 `lineage.html`（只有中文，从「数据、方法与状态」页链接，每次构建重新生成），清单 `docs/lineage.md`（`iros lineage --md docs/lineage.md` 生成，不会自动更新）。
- 信号：研究定义的 `branch` / `data` / `method`（earnings、event、units、root、downstream_notes），`@register_branch`，源码 import（只沿计算与取数模块传递，不穿过基础设施），`runs.py` 导入的框架模块，数据集的 `connector` / `source_id`，证据包的 `DATASET_ID` 与导入脚本。行业证据包经 `data/industry/*.json` 的生成脚本读不出，在 `config/lineage.yaml` 声明。四种信号覆盖全部 36 项研究，不需要给研究补元数据字段。
- 2026-11-26 结果：研究 36、模块 48（计算 31、取数 11、脚本 6）、数据集 87；没有研究用到的模块、接入器与脚本 7 个（`analytics/returns.py`、`analytics/risk.py` 只被测试用；`connectors/manual.py`；接入器 `fred_graph_csv` 无数据集、`fred_api_vintages` 的 4 个 ALFRED 数据集无研究用；两个脚本不属于研究），另有 30 个数据集没有研究用（多为定时取数的汇率、利差、指数与 French 地区因子）；断链 0。
- 反测：`tests/test_lineage.py`（阳性 `ust_curve_2024` 一直追到 Treasury 与 FRED 来源；阴性 `analytics/returns.py` 经 grep 手工确认只被测试导入；构造小仓库测 6 类断链）。
- 局限：只读静态写明的引用，函数里按字符串拼出的数据集或文件读不出；基础设施模块（契约、登记、存储、报告、网站）不判断是否被用。删不删未使用的模块没有决定，页面只列出研究之外的引用供判断。
- 待办：新增研究、数据集或模块后跑 `iros lineage --md docs/lineage.md --check` 重写清单（网站页面自动更新）。

## 14. 资本开支融资转向检验的 1873 年铁路回放（执行实测，待用户复核）

- 方法卡 capex-boom-credit-transition（方法库提交 1c2bb95）第 1–8 步，四个时点 T1 1869-05、T2 1872-12、T3 1873-09、T4 约 1876。记录在 `methodology/records/hist-us-railroad-capex-1873-20261126.yaml`，复核 `pending`。
- 第 1、8 步走完，第 2–7 步部分走到。第一处要猜在第 2 步（没有现金流量表），早于题目预期的第 3 步。卡的问题六条见「给方法库」2026-11-26 capex-boom-credit-transition 各条。
- 执行会话按方法库 tests/README 的约定没有提交；2026-11-26 用户要求提交推送。数值用的一次性脚本不在仓库内，输入文件哈希写在记录里。
- 待补：Poor's 1872-73 版（T2 可得的版本）、Sprague（1910）纽约清算所周度数据、CFC 1876 汇总的页面图核对（OCR 有两处数字读不清）。
