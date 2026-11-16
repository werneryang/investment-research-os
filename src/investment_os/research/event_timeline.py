"""研究分支：事件事实与时间线（docs/study-events.md）。

只读取固定的事件证据包（event_evidence），不直接读登记文件：
- 时间线：登记事实按日期排列，每条带相对事件日的天数、原文摘录与出处；原文的接受时间另列为「披露」
- 披露时滞：事件日到首份披露原文接受日（美东）的日历天数
- 原文未提及：列出检查过的原文与检索词；只说明原文没有写，不说明事情不存在
- 后续日程：查阅日之后、公司已公布的日程

不判断原因、影响或市场反应；价格反应属于另一个问题子类，需要日度价格。
"""

from __future__ import annotations

from typing import Any

from ..contracts import ResultType
from ..quality import ok_rows
from ..registry import Registry, StudySpec
from .base import ResearchResult, StudyInput, input_record, register_branch

ORDER = {"context": 0, "related": 1, "event": 2, "filing": 3, "scheduled": 4}


def _records(inp: StudyInput, event_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta = inp.version.series
    bundle = meta.get("_bundle") or {}
    rows = ok_rows(inp.frame)
    values = dict(zip(rows["series_id"], rows["value"].astype(float)))
    recs = [{**m, "t": int(values[sid])} for sid, m in meta.items()
            if sid != "_bundle" and sid in values and m.get("event") == event_id]
    return recs, bundle


@register_branch("event_timeline", result_types=(ResultType.DESCRIPTIVE,))
def run(study: StudySpec, inputs: dict[str, StudyInput], registry: Registry) -> ResearchResult:
    inp = inputs["evidence"]
    event_id = study.method["event"]
    recs, bundle = _records(inp, event_id)
    check = bundle.get("check") or {}
    if check.get("errors"):
        raise ValueError("事件证据包的登记核对有错误，不能使用：" + "；".join(check["errors"][:3]))
    ev = (bundle.get("events") or {}).get(event_id)
    if not ev or not recs:
        raise ValueError(f"事件证据包中没有事件 {event_id}")

    facts = [r for r in recs if r["record"] == "fact"]
    filings = [r for r in recs if r["record"] == "filing"]
    as_of = ev["as_of"]
    timeline = sorted(
        [{"date": r["date"], "t": r["t"], "kind": r["kind"], "fact": r["fact"], "order": r["order"], "statement": r["statement"],
          "excerpt": r["excerpt"], "locator": r.get("locator"), "document": r["document"], "form": r["form"],
          "accession": r["accession"], "url": r["url"], "available_at": r["published_at"]} for r in facts]
        + [{"date": r["date"], "t": r["t"], "kind": "filing", "document": r["document"], "form": r["form"],
            "items": r.get("items") or [], "accession": r["accession"], "url": r["url"], "accepted_at": r["accepted_at"]}
           for r in filings],
        key=lambda x: (x["date"], ORDER[x["kind"]], x.get("order", 0), x["document"]))

    # 披露：事件之后、载有事件事实的第一份原文
    event_docs = {r["document"] for r in facts if r["kind"] == "event"}
    first = min((r for r in filings if r["document"] in event_docs), key=lambda r: r["accepted_at"], default=None)
    disclosure = first and {"document": first["document"], "form": first["form"], "accession": first["accession"],
                            "accepted_at": first["accepted_at"], "date": first["date"], "lag_days": first["t"],
                            "url": first["url"]}
    scheduled = [x for x in timeline if x["kind"] == "scheduled"]
    counts = {k: sum(x["kind"] == k for x in timeline) for k in ORDER}

    unsupported = [
        {"item": "离任原因与事件的影响", "kind": "scope",
         "reason": "本研究只整理原文写明的事实；原因原文没有写，影响需要另做判断，不在公开研究范围内"},
        {"item": "事件窗口的价格反应", "kind": "scope",
         "reason": "属于「事件窗口的价格反应」子类，需要日度个股价格与基准，尚未接入"},
    ]
    validation = {"evidence_check": {
        "status": "pass", "checked": sum((check.get("checked") or {}).values()),
        "reason": "证据包生成前逐份核对原文 SHA256、逐条核对摘录、逐项确认未提及的检索词不在原文中"}}
    cutoff = max((r["published_at"] for r in recs if r["date"] <= as_of), default=None)
    return ResearchResult(
        study_id=study.study_id, title=study.title, question=study.question, result_type=study.result_type,
        branch=study.branch, scope=study.scope, data_cutoff=cutoff,
        methods={
            "description": "从固定的事件证据包读取登记事实，按日期排成时间线：每条事实带原文逐字摘录与出处，"
                           "相对事件日的天数按日历日计算；原文接受时间（美东）另列为披露。原文没有写的事项列出检查过的原文与检索词，"
                           "只说明原文未提及。不推断原因、影响或市场反应。",
            "parameters": {"event": event_id},
            "bundle": {k: bundle.get(k) for k in ("built_at", "event_files")},
        },
        inputs=[input_record(inp)],
        results={"event": {"id": event_id, "entity": ev["entity"], "title": ev["title"], "event_date": ev["event_date"],
                           "as_of": as_of, "filings_checked": ev.get("filings_checked")},
                 "timeline": timeline, "disclosure": disclosure, "not_mentioned": ev.get("not_mentioned", []),
                 "scheduled": scheduled,
                 "summary": {"facts": len(facts), "filings": len(filings), "counts": counts,
                             "not_mentioned": len(ev.get("not_mentioned", [])), "scheduled": len(scheduled)}},
        coverage={"facts": len(facts), "completeness": "complete"},
        unsupported=unsupported, limitations=list(study.limitations), validation=validation,
        tables={"timeline": [{k: x.get(k) for k in ("date", "t", "kind", "fact", "document", "form", "accession")}
                             for x in timeline]},
    )
