"""季度财报研究的报告段落。"""
from typing import Any


def _bn(v: float | None) -> str:
    return "—" if v is None else f"{v / 1e3:,.2f}".replace("-", "−")


def _pct(v: float | None, signed: bool = False) -> str:
    return "—" if v is None else (f"{v:+.1f}%" if signed else f"{v:.1f}%").replace("-", "−")


def sections(r: dict[str, Any]) -> tuple[list[Any], str, list[Any]]:
    res = r["results"]
    rows = res["quarters"]
    heads = ["指标（十亿美元，利润率为 %）"] + [q["label"] + ("*" if q["derived"] else "") for q in rows]
    spec = [("收入", "revenue", _bn), ("Google Services 收入", "Services_revenue", _bn), ("Google Cloud 收入", "Cloud_revenue", _bn),
            ("营业利润", "op_income", _bn), ("营业利润率", "op_margin", _pct), ("Google Cloud 利润率", "Cloud_margin", _pct),
            ("合并净利润", "consolidated_NI", _bn), ("权益证券净损益", "equity_security_gain_loss", _bn),
            ("经营活动现金流", "cfo", _bn), ("现金资本开支", "cash_ppe", _bn), ("自由现金流（发行人定义）", "free_cash_flow", _bn)]
    body: list[Any] = [f"最新季度 {res['latest_period']['label']}（{res['latest_period']['start']} 至 {res['latest_period']['end']}），"
                       f"10-Q 于 {res['release']['form_10q_filed']} 申报。全部为报告口径，不是有机增长。* 为全年减前三季度的推导值。",
                       ("table", heads, [[label] + [fmt(q[key]) for q in rows] for label, key, fmt in spec])]
    yoy, qoq = res["comparison"]["yoy"], res["comparison"]["qoq"]
    body.append(("table", ["比较", "收入", "Google Cloud 收入", "营业利润", "营业利润率（百分点）"],
                 [[f"同比（对 {yoy['base']}）", _pct(yoy["pct"]["revenue"], True), _pct(yoy["pct"]["Cloud_revenue"], True),
                   _pct(yoy["pct"]["op_income"], True), f"{yoy['margin_pp']['op_margin']:+.1f}"],
                  [f"环比（对 {qoq['base']}）", _pct(qoq["pct"]["revenue"], True), _pct(qoq["pct"]["Cloud_revenue"], True),
                   _pct(qoq["pct"]["op_income"], True), f"{qoq['margin_pp']['op_margin']:+.1f}"]]))
    notes = ("table", ["可比性事项", "限制"], [[n["title"]["zh"], n["limit"]["zh"]] for n in res["notes"]])
    cov = ("table", ["类别", "内容"], [[{"done": "已完成", "data_gap": "数据不足", "judgment": "需人工判断"}[c["status"]], c["item"]["zh"]]
                                      for c in res["coverage"]])
    return body, "可比性与未覆盖项", [notes, cov, *r["limitations"]]
