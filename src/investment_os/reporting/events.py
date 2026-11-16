"""事件时间线研究的报告段落。"""
from typing import Any

KIND = {"context": "事件前", "related": "同期其他高管变动", "event": "事件", "filing": "披露", "scheduled": "已公布的日程"}


def sections(r: dict[str, Any]) -> tuple[list[Any], str, list[Any]]:
    res = r["results"]
    d = res.get("disclosure") or {}
    body: list[Any] = [f"事件日 {res['event']['event_date']}；首份披露 {d.get('form', '—')}（{d.get('accession', '—')}）"
                       f"于 {d.get('accepted_at', '—')} 在 EDGAR 接受，事件后 {d.get('lag_days', '—')} 个日历日。"]
    rows = []
    for x in res["timeline"]:
        what = (f"原文在 EDGAR 接受：{x['accepted_at']}" if x["kind"] == "filing"
                else f"{x['statement']['zh']}（原文：{x['excerpt']}）")
        rows.append([x["date"], f"{x['t']:+d}" if x["t"] else "0", KIND[x["kind"]], what, f"{x['form']} {x.get('locator') or ''}".strip()])
    body.append(("table", ["日期", "相对事件日", "类别", "事实", "出处"], rows))
    nm = ("table", ["原文没有写明的事项", "检查过的原文", "检索词（均未出现）"],
          [[n["item"]["zh"], "、".join(n["documents"]), "、".join(n["terms"])] for n in res["not_mentioned"]])
    return body, "原文没有写明的事项与限制", [nm, *r["limitations"]]
