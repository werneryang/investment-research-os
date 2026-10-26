"""Industry report presentation; all calculations come from pinned results."""
import re

from .common import e, stat
from .i18n import L
from ..reporting.industry import sections


def inline(value):
    value = str(value)
    escaped = e(value)
    return re.sub(r"\[([^\]]+)\]\((https://[^\s)]+)\)", r'<a href="\2">\1</a>', escaped)


def details(result):
    body, title, extra = sections(result)
    parts = ['<p class="muted">'+L("表格口径与详细解释见下文；该专题的完整报告使用中文。", "Detailed tables and the full dossier are in Chinese; English labels are used in the figures.")+"</p>"]
    for item in [*body, title, *extra]:
        if isinstance(item, tuple):
            _, headers, rows = item
            parts.append('<details><summary>'+L("展开数据表", "Open data table")+f' · {len(rows)}</summary><div class="table-wrap"><table><thead><tr>'
                         +''.join('<th>'+e(h)+'</th>' for h in headers)+'</tr></thead><tbody>'
                         +''.join('<tr>'+''.join('<td>'+inline(c)+'</td>' for c in row)+'</tr>' for row in rows)
                         +'</tbody></table></div></details>')
        else:
            parts.append('<p>'+inline(item)+'</p>')
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
        chart_data=lambda r:None,
        figures_t=(("industry_risk.png",("收益与最大回撤","Returns and maximum drawdown")),
                   ("industry_wealth.png",("专题累计收益","Selected industry wealth")),
                   ("industry_rolling.png",("滚动十年收益","Rolling ten-year returns")),
                   ("industry_economy.png",("实体行业变化","Domestic real value added")),
                   ("industry_fundamentals.png",("利润率与样本覆盖","Margins and sample coverage"))),
        use_note_t=("事后描述研究；分类与样本边界见各层说明", "Retrospective description; classification and sample boundaries apply"),
        state_description_t=("行业数和指引案例数", "industry and guidance case counts"))
