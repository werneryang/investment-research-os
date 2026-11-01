"""Industry report presentation; all calculations come from pinned results."""
import re

from .common import e, num, stat
from .i18n import L
from .visuals import axis, heatmap, panel, panels, scaled, series, view
from ..reporting.industry import sections

# 累计收益图只画少数行业（与完整报告的静态图相同），其余行业看热力图与散点
WEALTH_SECTORS = {12: ["Market", "BusEq", "Enrgy", "Shops"], 49: ["Market", "Chips", "Softw", "Oil", "Rtail", "Whlsl"]}


def _windows(result):
    """时间窗口按起点排序：[(标签, 起, 止)]。"""
    return sorted((tuple(w) for w in result["results"]["windows"]), key=lambda w: w[1])


def _summary(result):
    """{(窗口, 行业): (行, 在结果中的序号)}，只取完整窗口（status 为 ok）。"""
    return {(x["window"], x["sector"]): (x, i) for i, x in enumerate(result["results"]["summary"]) if x["status"] == "ok"}


def matrix(result):
    """行业 × 时间窗口的年化收益与最大回撤热力图；按最长窗口的年化收益从高到低排列。"""
    windows, rows = _windows(result), _summary(result)
    if not rows:
        return ""
    longest = windows[0][0]
    sectors = sorted({s for _, s in rows}, key=lambda s: -(rows.get((longest, s), ({"cagr": -9}, 0))[0]["cagr"]))
    cols = [(w, w) for w, _, _ in windows]
    pct = lambda v: f"{num(v, 1)}%"  # noqa: E731

    def cell(metric):
        return lambda s, w: ((scaled(rows[(w, s)][0][metric]), f"results.summary.{rows[(w, s)][1]}")
                             if (w, s) in rows else None)
    note = L("只列完整的月度窗口；不完整窗口显示为 —，不拼接。", "Complete monthly windows only; incomplete windows show — and are not stitched.")
    return ('<h4 id="industry-matrix">' + L("各行业在不同时间窗口的年化收益", "Annualized return by industry and window") + '</h4>'
            + f'<p class="small muted">{note}</p>'
            + heatmap([(s, s) for s in sectors], cols, cell("cagr"), pct, row_head=L("行业", "Industry"),
                      legend=L("按最长窗口排序", "sorted by the longest window"))
            + '<details><summary>' + L("最大回撤（同一排列）", "Maximum drawdown (same order)") + '</summary>'
            + heatmap([(s, s) for s in sectors], cols, cell("max_drawdown"), pct, row_head=L("行业", "Industry"))
            + '</details>')


def chart(result):
    """收益与波动率散点（按窗口切换）和少数行业的累计财富。"""
    windows, rows = _windows(result), _summary(result)
    views = []
    for w, _, _ in reversed(windows):  # 默认显示最近的窗口
        pts = [{"x": scaled(x["volatility"]), "y": scaled(x["cagr"]), "label": s, "ref": f"results.summary.{i}"}
               for (win, s), (x, i) in sorted(rows.items()) if win == w and x.get("volatility") is not None]
        views.append(view(w, series(L("行业", "Industries"), pts)))
    scatter = panel("scatter", L("年化收益与波动率", "Annualized return vs volatility"),
                    axis(L("波动率", "Volatility"), "%"), axis(L("年化收益", "Annualized return"), "%"), views,
                    views_label=L("窗口", "Window"), wide=True, height=340,
                    note=L("每点一个行业；悬停查看行业名。", "One point per industry; hover for its name."))
    wealth_rows = (result.get("tables") or {}).get("wealth") or []
    names = [s for s in WEALTH_SECTORS.get(result["results"]["industry_count"], ["Market"])
             if any(x["sector"] == s for x in wealth_rows)]
    wealth = panel("line", L("部分行业的累计财富", "Cumulative wealth, selected industries"),
                   axis(L("月份", "Month")), axis(L("财富", "Wealth"), "", 2, log_toggle=True, log_default=True),
                   [view("", *[series(s, [{"x": x["month"], "y": x["wealth"]} for x in wealth_rows if x["sector"] == s], slot=i)
                               for i, s in enumerate(names)])],
                   wide=True, note=L("与完整报告的静态图选取相同的行业；Market 为全市场。",
                                     "Same industries as the static figure in the full report; Market is the whole market."))
    return panels(scatter, wealth)


def inline(value):
    value = str(value)
    escaped = e(value)
    return re.sub(r"\[([^\]]+)\]\((https://[^\s)]+)\)", r'<a href="\2">\1</a>', escaped)


def details(result):
    body, title, extra = sections(result)
    parts = [matrix(result), '<p class="muted">'+L("表格口径与详细解释见下文；该专题的完整报告使用中文。", "Detailed tables and the full dossier are in Chinese; English labels are used in the figures.")+"</p>"]
    anchors = {"市场表现：": "industry-market", "因子暴露（": "industry-factors",
               "估值与样本背景：": "industry-background", "实体行业：": "industry-economy",
               "领先/滞后相关：": "industry-lags", "宏观环境分组（": "industry-regimes",
               "固定压力时期的累计总收益：": "industry-stress", "财报样本：": "industry-financials",
               "Damodaran 独立行业快照：": "industry-valuation", "管理层指引：": "industry-guidance"}
    seen = set()
    for item in [*body, title, *extra]:
        if isinstance(item, tuple):
            _, headers, rows = item
            parts.append('<details><summary>'+L("展开数据表", "Open data table")+f' · {len(rows)}</summary><div class="table-wrap"><table><thead><tr>'
                         +''.join('<th>'+e(h)+'</th>' for h in headers)+'</tr></thead><tbody>'
                         +''.join('<tr>'+''.join('<td>'+inline(c)+'</td>' for c in row)+'</tr>' for row in rows)
                         +'</tbody></table></div></details>')
        else:
            key = next((key for prefix, key in anchors.items() if item.startswith(prefix)), None)
            attr = f' id="{key}"' if key and key not in seen else ''
            if key:
                seen.add(key)
            # Source report paragraphs remain Chinese in either language, explicitly marked.
            parts.append('<p' + attr + ' lang="zh-CN">'+inline(item)+'</p>')
    return ''.join(parts)


def make_renderer(Renderer):
    return Renderer(
        key_stats=lambda r: '<div class="stats">'+stat(L("行业", "Industries"),str(r["results"]["industry_count"]),"1926–2025")
            +stat(L("研究层次", "Research layers"),"4" if r["tables"]["fundamentals"] else "2",L("市场 / 经营 / 预期 / 经济", "Markets / business / expectations / economy"))
            +stat(L("指引案例", "Guidance cases"),str(r["results"]["guidance_events"]),L("独立于分析师预期", "Separate from analyst consensus"))+'</div>',
        method_items=lambda r: ["<li>"+L("完整月度收益；缺失窗口不拼接；月度峰值包含起点财富 1。", "Complete monthly returns; no stitching over gaps; drawdowns include initial wealth of 1.")+"</li>",
                                "<li>"+L("CAPM / FF3 / FF5+MOM，HAC 区间与模型内 BH 多重比较。", "CAPM / FF3 / FF5+MOM with HAC intervals and within-model BH adjustment.")+"</li>",
                                "<li>"+L("各期 SEC SIC 样本；配对公司增长和利润率；原始指引日期与目标期核对。", "Historical SEC SIC samples; matched-company growth and margins; guidance dates and targets checked.")+"</li>"],
        coverage_title_t=("四层证据与结果", "Four layers of evidence and results"), coverage_section=details,
        evidence_rows=lambda r: [(L("年度复利核对", "Annual compounding check"), e(str(r["validation"]["annual_compounding"]))),
                                 (L("映射版本", "Mapping version"), e(r["methods"]["mapping_version"]))],
        evidence_summary=lambda r: [L("固定输入可重算；原始数据仅本地保存", "Recomputed from pinned inputs; raw data stay local")],
        history_columns_t=((("行业数", "Industries"),lambda r:str(r["results"]["industry_count"])),),
        chart_data=chart,
        figures_t=(("industry_risk.png",("收益与最大回撤","Returns and maximum drawdown")),
                   ("industry_wealth.png",("专题累计收益","Selected industry wealth")),
                   ("industry_rolling.png",("滚动十年收益","Rolling ten-year returns")),
                   ("industry_economy.png",("实体行业变化","Domestic real value added")),
                   ("industry_fundamentals.png",("利润率与样本覆盖","Margins and sample coverage"))),
        use_note_t=("事后描述研究；分类与样本边界见各层说明", "Retrospective description; classification and sample boundaries apply"),
        state_description_t=("行业数和指引案例数", "industry and guidance case counts"))
