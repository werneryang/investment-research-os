"""Readable tables and figures for the four-layer industry dossier."""
from __future__ import annotations

from pathlib import Path
import pandas as pd


def pc(value):
    return "—" if value is None else f"{value*100:.2f}%"


def number(value):
    return "—" if value is None else f"{value:,.2f}"


def sections(result):
    r, t = result["results"], result["tables"]
    body = ["市场回报、美国境内行业产出、全球合并财报和管理层指引分别衡量不同对象。下列对应关系用于研究背景，不能据此建立会计恒等式或因果归因。"]
    if r["industry_count"] == 12:
        body.append("行业代码：NoDur 非耐用品；Durbl 耐用品；Manuf 机械等制造；Enrgy 能源；Chems 化工；BusEq 商用设备（含计算机、软件、电子）；Telcm 通信；Utils 公用事业；Shops 批零及部分服务；Hlth 医疗；Money 金融；Other 其他。分类不能直接替换为现代 GICS 板块。")
    else:
        body.append("本页使用 French 原行业代码。重点细分：Chips 半导体、Softw 软件、Hardw 硬件、Oil 油气、Coal 煤炭、Whlsl 批发、Rtail 零售、Meals 餐饮住宿、Banks 银行、Insur 保险、RlEst 房地产、Fin 其他金融。详细 SIC 定义见来源链接。")
    if t["fundamentals"]:
        for topic, sector, explanation in (
            ("energy","Enrgy","能源应同时看产量、商品价格与成本，实物产出增长不会自动转化为股东回报。2015 和 2020 年的样本利润率与现金流有助于识别这种周期性；相关数据不能单独把变化归因于油价。"),
            ("trade","Shops","批零通常利润率较薄；规模增长、成本控制、库存和资本周转都会影响利润。样本的全球营收、美国零售增加值和股票 Shops 是不同集合，不能互相替代。"),
            ("technology","BusEq","半导体和软件的经营增长可以为回报提供背景，但 BusEq 还包含其他硬件；高回报同时涉及估值、风格与样本变化。49 行业页把 Chips 与 Softw 分开，避免把整个技术产业解释成单一周期。")):
            market=next(x for x in r["summary"] if x["sector"]==sector and x["window"]=="2010–2025")
            company=next(x for x in t["fundamentals"] if x["topic"]==topic and x["year"]==2025)
            sales=company["metrics"]["revenue"]
            body.append(f"专题解读 · {topic}：2010–2025 {sector} 股票年化总收益 {pc(market.get('cagr'))}，月度最大回撤 {pc(market.get('max_drawdown'))}。2025 财年末所在年的 {sales['matched_count']} 家可比样本公司营收同比 {pc(sales['matched_growth'])}。长期股票收益与最近一年经营变化不是同一比较期间。{explanation}")
            history = [next(x for x in t["fundamentals"] if x["topic"]==topic and x["year"]==year) for year in (2015,2020,2025)]
            margins = "、".join(f"{x['year']} 年 {pc(x['ratios']['net_margin']['value'])}（{x['ratios']['net_margin']['count']} 家）" for x in history)
            body.append(f"经营路径 · {topic}：配对样本净利率为{margins}。这里每个年份的分子分母同口径，但跨年公司集合会变化，因此利润率路径同时包含经营与样本构成变化，不能全部解释为固定一批公司的效率改善。")
            fit = next(x for x in t["regressions"] if x["sector"]==sector and x["window"]=="2010–2025" and x["model"]=="FF5+MOM" and x["status"]=="ok")
            alpha = fit["coefficients"]["alpha"]
            overlap = alpha["ci_low"] <= 0 <= alpha["ci_high"]
            body.append(f"风险与定价 · {sector}：同期五因子加动量模型的市场 beta 为 {number(fit['coefficients']['Mkt-RF']['estimate'])}，R² 为 {number(fit['r_squared'])}；算术年化 alpha 为 {pc(fit['alpha_annual_arithmetic'])}，95% 区间 {pc(alpha['ci_low']*12)} 至 {pc(alpha['ci_high']*12)}，BH q={number(fit['alpha_bh_q'])}。" + ("区间包含零，不能把高原始回报直接称为稳定的风险调整超额回报。" if overlap else "该结果依赖模型与期间，不能外推为稳定的未来超额回报。") + "R² 描述月度共同波动，不是长期收益中被经济原因解释的比例。")
    if r.get("oil_price"):
        body.append("能源价格背景：EIA WTI 现货价的有效交易日年均值与最低值；每年要求至少 200 个观测。它不是原油期货投资回报，也不是所有能源公司实现的销售价格。")
        body.append(("table",["年","有效日数","均价（美元/桶）","最低"],[[x["year"],x["observations"],number(x["mean_usd_per_barrel"]),number(x["minimum"])] for x in r["oil_price"]]))
    for window, _, _ in r["windows"]:
        body.append(f"市场表现：{window}。收益含分红，风险按月度计算；实际年化收益用 CPI 起止端点扣除通胀，未插值缺月。")
        rows = [x for x in r["summary"] if x["window"]==window]
        rows.sort(key=lambda x: x.get("cagr", -100), reverse=True)
        body.append(("table", ["行业", "月数", "名义年化", "实际年化", "波动", "最大回撤", "峰值→谷底", "恢复月"],
                     [[x["sector"], str(x.get("months", x.get("valid_months")))+ ("（不完整）" if x["status"]!="ok" else ""),
                       pc(x.get("cagr")), pc(x.get("real_cagr")), pc(x.get("volatility")), pc(x.get("max_drawdown")),
                       f"{x.get('peak','—')}→{x.get('trough','—')}", (x.get("recovery") or "截至期末未恢复") if x["status"]=="ok" else "未计算"] for x in rows]))
    body.append("因子暴露（2001–2025）：alpha 为月截距乘 12，不是可交易收益预测。95% 区间使用 Bartlett/Newey–West HAC（6 月滞后），p 值为渐近正态近似；BH q 值在同一模型、同一窗口的行业 alpha 间调整，仍是探索性比较。")
    fits = [x for x in t["regressions"] if x["window"]=="2001–2025" and x["status"]=="ok"]
    body.append(("table", ["行业", "模型", "市场 beta", "年化 alpha", "alpha 95%区间", "BH q", "R²"],
                 [[x["sector"],x["model"],number(x["coefficients"]["Mkt-RF"]["estimate"]),pc(x["alpha_annual_arithmetic"]),
                   pc(x["coefficients"]["alpha"]["ci_low"]*12)+" ~ "+pc(x["coefficients"]["alpha"]["ci_high"]*12),
                   number(x["alpha_bh_q"]),number(x["r_squared"])] for x in fits]))
    body.append("估值与样本背景：BE/ME 使用 French 的年度源标签，不当作 12 月末市盈率。公司数量与平均市值不能确定行业成分集中度；等权—市值加权差异包含规模与再平衡效应。")
    lookup = {(x["sector"],x["metric"]): x["value"] for x in r["characteristics"]}
    body.append(("table", ["行业", "2025-12 公司数", "平均市值（百万美元）", "2025 BE/ME", "等权年化", "市值加权年化"],
                 [[x["sector"],number(lookup.get((x["sector"],"firms"))),number(lookup.get((x["sector"],"size"))),
                   number(lookup.get((x["sector"],"bm"))),pc(x["ew_cagr"]),pc(x["vw_cagr"])] for x in r["weight_effect"]]))
    if r["economy"]:
        body.append("实体行业：2006Q2–2025Q4 同期端点变化。增加值为链式实际美元；就业、工时、时薪为各季度有效月份均值，缺一月即不生成季度。时薪为名义值；产能利用率的百分比变化不能误读为百分点变化。不同产业的链式美元不直接相加。")
        body.append(("table", ["专题", "指标", "FRED代码", "起值", "终值", "累计变化", "有效季度"],
                     [[x["topic"],x["measure"],x["series"],number(x["start_value"]),number(x["end_value"]),pc(x["change"]),x["quarters"]] for x in r["economy"]]))
        body.extend(f"{name} 对应限制：{v['reason']}" for name,v in r["mapping"].items())
        body.append("领先/滞后相关：corr(行业股票收益[t], 实际增加值或产出环比增长[t+k])。k>0 表示股票领先；对所有 -4 至 +4 季结果同时报告，不挑选最好的一项。它是当前修订值的事后相关，未作显著性或因果结论。")
        body.append(("table",["专题/序列", "时期", "滞后k", "配对季度", "相关系数"],
                     [[f"{x['topic']}/{x['series']}",x["period"],x["lag_quarters"],x["pairs"],number(x["correlation"])] for x in t["lag_correlations"]]))
    body.append("宏观环境分组（2001–2025）：衰退按 NBER 事后日期；通胀按 CPI 同比的当月升降；政策利率按月均值六个月变化超过 ±0.25 个百分点分组。下表是组内月均收益 ×12，不是连续持有年化收益，也不能作为当时可得的择时信号。")
    body.append(("table",["变量","状态","行业","月数","月均收益×12","月标准差×√12"],
                 [[x["variable"],x["regime"],x["sector"],x["months"],pc(x["monthly_mean_times_12"]),pc(x["monthly_std_times_sqrt12"])] for x in t.get("regimes",[])]))
    body.append("固定压力时期的累计总收益：窗口是事件比较，不是事后搜索的最差起止点。")
    body.append(("table",["事件","起止月","行业","累计收益"],[[x["episode"],x["first"]+"→"+x["last"],x["sector"],pc(x["total_return"])] for x in t.get("stress",[])]))
    if t["fundamentals"]:
        cov=r["fundamental_coverage"]
        body.append(f"财报样本：{cov['selected_companies']} 家历史申报主体（其中 {cov['companies_with_facts']} 家有已解析事实），{cov['facts']} 个年度指标事实。按各期 SIC 选样，不等于上市普通股成分。按财年结束的日历年归档；2010 年附近的 XBRL 分阶段覆盖尤其不完整。进入/退出只表示本研究样本变化，不能解释为 IPO/退市。")
        body.append("利润率采用同一批同时有利润与营收的公司的合计比率。增长只用连续两年都有该指标的公司；零或负的合计基期不输出增长率。不同指标覆盖不同，不能混合它们的总额。后续年度比较列的重述不纳入，本表只纳入当年申报及修正申报。")
        for topic in ("energy", "trade", "technology"):
            series=[x for x in t["fundamentals"] if x["topic"]==topic]
            body.append(f"{topic}：年度经营表现与样本覆盖。营收为十亿美元，增长为同公司同比。")
            body.append(("table",["财年末所在年","公司/新增/退出","营收覆盖","营收合计","同公司增长/数量","净利率/数量","经营利率/数量","FCF/数量"],
                         [[x["year"],f"{x['companies']}/{x['entrants']}/{x['exits']}",x["metrics"]["revenue"]["count"],
                           number(x["metrics"]["revenue"]["sum"]/1e9) if x["metrics"]["revenue"]["sum"] is not None else "—",
                           pc(x["metrics"]["revenue"]["matched_growth"])+f" / {x['metrics']['revenue']['matched_count']}",
                           pc(x["ratios"].get("net_margin",{}).get("value"))+f" / {x['ratios'].get('net_margin',{}).get('count',0)}",
                           pc(x["ratios"].get("operating_margin",{}).get("value"))+f" / {x['ratios'].get('operating_margin',{}).get('count',0)}",
                           (number(x["free_cash_flow"]["sum"]/1e9)+f" / {x['free_cash_flow']['count']}") if x["free_cash_flow"]["sum"] is not None else "—"] for x in series]))
        body.append("资本配置（2025 财年末所在年）：资本开支、股息、回购均为有配对数据公司的金额/营收。回购是现金流指标，不是在每股收益增长之外再次累加的回报来源。表内集中度仅为此财报样本营收前五名份额，不是行业市场份额或股票权重。")
        body.append(("table",["专题","资本开支/营收（数量）","分红/营收（数量）","回购/营收（数量）","营收前五占比"],
                     [[x["topic"],*[pc(x["ratios"].get(key,{}).get("value"))+f" ({x['ratios'].get(key,{}).get('count',0)})" for key in ("capex_to_sales","dividends_to_sales","repurchases_to_sales")],
                       pc(x["sample_top5_revenue_share"])] for x in t["fundamentals"] if x["year"]==2025]))
        body.append("余额（2025 财年末所在年，十亿美元/有效公司数）：每个单元格是其自身有效样本，不能把不同覆盖的列相减算净债务；长期债务两部分也不能冒充全部借款。")
        body.append(("table",["专题","资产","权益","现金","长期债务当前部分","长期债务非当前部分"],
                     [[x["topic"],*[number(x["metrics"][key]["sum"]/1e9)+f" / {x['metrics'][key]['count']}" if x["metrics"][key]["sum"] is not None else "—"
                                  for key in ("total_assets","equity","cash","debt_current","debt_noncurrent")]] for x in t["fundamentals"] if x["year"]==2025]))
    if t["valuation"]:
        body.append("Damodaran 独立行业快照：按官网归档链接的日期命名（例如 pedata24.xls 是 2025 年 1 月）。分类和供应商历年有变化；仅按原始同名行业列示选定时点，不映射成 French 行业。Trailing PE 的聚合定义与亏损公司处理会影响比较，不能视为可直接交易的指数市盈率。完整原表仅保留本地。")
        body.append(("table",["原始行业名称","快照年1月","指标","值","原表定位"],
                     [[x["industry"],x["snapshot_year"],x["metric"],pc(x["value"]) if x["metric"]=="net_margin" else number(x["value"]),
                       f"[{x['locator']}]({x['source_url']})"] for x in t["valuation"]]))
    if t["guidance"]:
        body.append("管理层指引：6 家公司、2020–2025 年选择性目标期案例，另含 Intel 同一全年目标的修订。此样本不能衡量全市场超预期概率；不是分析师一致预期。金额为十亿美元；目标期、GAAP 口径与结果公布前的指引逐项匹配。")
        body.append(("table",["公司/目标","预测日→结果日","区间","首次实际","偏离中点","结果","原公告"],
                     [[x["company"]+"/"+x["forecast_target"],x["forecast_date"]+"→"+x["actual_date"],
                       f"{x['low']/1e9:g}–{x['high']/1e9:g}",number(x["value"]/1e9),pc(x["vs_midpoint"]),
                       x["outcome"],f"[指引]({x['evidence']['forecast']['url']}) / [实际]({x['evidence']['actual']['url']})"] for x in t["guidance"]]))
        body.extend(x["precision_note"] for x in t["guidance"] if x.get("precision_note"))
        body.extend(f"{x['company']} {x['forecast_target']}：{x['forecast_date']} 相对 {x['revises']} 的指引中点修订为 {pc(x['revision_midpoint_change'])}。这是同一目标的修订，不是不同季度间的增长。"
                    for x in t["guidance"] if x.get("revision_midpoint_change") is not None)
    detail=["完整数值与方法参数保存在结构化 result.json；固定版本重算见运行验证。",
            "滚动收益覆盖 5、10、20 年；滚动五因子+动量暴露使用 10 年窗口、每五年末报告。相关矩阵和所有回归保存在结构化结果。",
            "2026 年尚未完结，只列累计更新："]
    detail.append(("table",["行业","截至","月份","累计总收益"],[[x["sector"],x["through"],x["months"],pc(x["total_return"])] for x in r["updates"]]))
    def stringify(items):
        return [(item[0], item[1], [[str(cell) for cell in row] for row in item[2]]) if isinstance(item, tuple) else item for item in items]
    return stringify(body), "证据范围与未完结年度", stringify(detail)


def figures(result, out_dir: Path):
    import matplotlib.pyplot as plt
    from .report import _save, _style
    _style()
    out_dir.mkdir(parents=True,exist_ok=True)
    figs=[]
    r,t=result["results"],result["tables"]
    rows=sorted([x for x in r["summary"] if x["window"]=="2001–2025" and x["status"]=="ok"],key=lambda x:x["cagr"])
    fig,axes=plt.subplots(1,2,figsize=(10,max(4,len(rows)*.19)))
    axes[0].barh([x["sector"] for x in rows],[x["cagr"]*100 for x in rows],color="#286d8a")
    axes[1].barh([x["sector"] for x in rows],[x["max_drawdown"]*100 for x in rows],color="#ba6345")
    axes[0].set_title("CAGR (%) | 2001–2025"); axes[1].set_title("Maximum monthly drawdown (%)")
    figs.append(("行业收益与回撤",_save(fig,out_dir/"industry_risk.png")))
    fig,ax=plt.subplots(figsize=(9,4))
    names={"BusEq","Enrgy","Shops","Market"} if r["industry_count"]==12 else {"Chips","Softw","Oil","Rtail","Whlsl","Market"}
    for sector in sorted(names):
        s=[x for x in t["wealth"] if x["sector"]==sector]
        if s: ax.plot([2000]+[int(x["month"][:4]) for x in s],[1]+[x["wealth"] for x in s],label=sector)
    ax.set_yscale("log"); ax.set_title("Total-return wealth: selected industries | Dec 2000 = 1");ax.legend(ncol=3)
    figs.append(("专题行业累计总收益",_save(fig,out_dir/"industry_wealth.png")))
    fig,ax=plt.subplots(figsize=(9,4))
    for sector in sorted(names-{"Market"}):
        s=[x for x in t["rolling"] if x["sector"]==sector and x["years"]==10]
        if s: ax.plot([x["end_year"] for x in s],[x["cagr"]*100 for x in s],label=sector)
    ax.axhline(0,color="black",lw=.5); ax.set_title("Rolling 10-year CAGR (%) | complete January–December windows"); ax.legend(ncol=3)
    figs.append(("十年滚动收益",_save(fig,out_dir/"industry_rolling.png")))
    if t["economy_paths"]:
        fig,ax=plt.subplots(figsize=(9,4))
        for topic in r["mapping"]:
            s=[x for x in t["economy_paths"] if x["topic"]==topic and x["measure"]=="rva"]
            if s:
                ax.plot([pd.Period(x["quarter"]).to_timestamp() for x in s],[x["value"]/s[0]["value"]*100 for x in s],label=topic)
        ax.set_title("US domestic real value added | 2005Q1 = 100 | contextual mappings");ax.legend()
        figs.append(("实体行业实际增加值",_save(fig,out_dir/"industry_economy.png")))
    if t["fundamentals"]:
        fig,axes=plt.subplots(1,2,figsize=(10,4))
        for topic in ("energy","trade","technology"):
            s=[x for x in t["fundamentals"] if x["topic"]==topic]
            axes[0].plot([x["year"] for x in s],[x["ratios"]["net_margin"]["value"]*100 if x["ratios"].get("net_margin",{}).get("value") is not None else float("nan") for x in s],label=topic)
            axes[1].plot([x["year"] for x in s],[x["metrics"]["revenue"]["count"] for x in s],label=topic)
        axes[0].set_title("Net margin (%) | paired sample");axes[1].set_title("Issuers with usable revenue | not full industry")
        axes[0].legend();axes[1].legend()
        figs.append(("专题盈利与样本覆盖",_save(fig,out_dir/"industry_fundamentals.png")))
    return figs
