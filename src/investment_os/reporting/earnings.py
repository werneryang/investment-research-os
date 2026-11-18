"""季度财报研究的报告段落；行与标签来自结果里的 profile。"""
from typing import Any

from ..earnings import disclosure_info


def _bn(v: float | None) -> str:
    return "—" if v is None else f"{v / 1e3:,.2f}".replace("-", "−")


def _pct(v: float | None, signed: bool = False) -> str:
    return "—" if v is None else (f"{v:+.1f}%" if signed else f"{v:.1f}%").replace("-", "−")


def sections(r: dict[str, Any]) -> tuple[list[Any], str, list[Any]]:
    res = r["results"]
    if "profile" not in res:
        return [r["methods"]["description"]], "可比性与未覆盖项", [*r["limitations"]]
    p = res["profile"]
    rows = res["quarters"]
    pct_keys = {x["key"] for x in p.get("ratios") or []} | {"gross_margin", "op_margin"}
    heads = ["指标（十亿美元，利润率为 %）"] + [q["label"] + ("*" if q["derived"] else "") for q in rows]
    keys = p.get("report") or [t if isinstance(t, str) else t["key"] for t in p["table"]]
    spec = [(p["metrics"][k]["zh"], k, _pct if k in pct_keys else _bn) for k in keys]
    cur = res["latest_period"]
    form, disclosed = disclosure_info(res["release"])
    body: list[Any] = [f"最新季度 {cur['label']}（{cur['start']} 至 {cur['end']}），"
                       f"{form} 于 {disclosed} 申报。全部为报告口径，不是有机增长。"
                       "* 为全年减前几季度的推导值。",
                       ("table", heads, [[label] + [fmt(q[key]) for q in rows] for label, key, fmt in spec])]
    yoy, qoq = res["comparison"]["yoy"], res["comparison"]["qoq"]
    seg = (p["findings"].get("segment") or {}).get("revenue")
    cols = [("收入", "revenue")] + ([(f"{p['metrics'][seg]['zh']} 收入", seg)] if seg else []) + [("营业利润", "op_income")]
    body.append(("table", ["比较"] + [c for c, _ in cols] + ["营业利润率（百分点）"],
                 [[f"{name}（对 {c['base']}）"] + [_pct(c["pct"][k], True) for _, k in cols] + [f"{c['margin_pp']['op_margin']:+.1f}"]
                  for name, c in (("同比", yoy), ("环比", qoq))]))
    notes = ("table", ["可比性事项", "限制"], [[n["title"]["zh"], n["limit"]["zh"]] for n in res["notes"]])
    cov = ("table", ["类别", "内容"], [[{"done": "已完成", "data_gap": "数据不足", "judgment": "需人工判断"}[c["status"]], c["item"]["zh"]]
                                      for c in res["coverage"]])
    return body, "可比性与未覆盖项", [notes, cov, *r["limitations"]]
