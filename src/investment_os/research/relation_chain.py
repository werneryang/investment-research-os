"""研究分支：关系链（docs/relation-chain-design.md）。

只读取固定的关系链证据包（relation_chain_evidence），不直接读登记文件：
- Q1：从起点按登记的有向关系向上游、下游逐层展开（supply_chain.chain.expand），记录每条边的类型、业务、复核状态、
  证据级别、披露方与占比，以及每个停止展开处的断点原因；竞争等无向关系只作旁注
- 下游另列反向检索：查过哪些公司的年报、是否点名起点公司
- Q2a：链上供应方与起点公司在各自年报中三个财年的营收与同比（同一申报、同一币种，不换算、不拼接、不计算相关系数）
- Q2b：只对下游链上有原文点名的公司对照资本开支；没有这样的公司时不输出，记入未输出的结论

不计算任何敞口：边上的占比原样列出，不相乘、不推算间接影响。
"""

from __future__ import annotations

from typing import Any

from ..contracts import ResultType
from ..quality import ok_rows
from ..registry import Registry, StudySpec
from ..supply_chain.chain import expand
from .base import ResearchResult, StudyInput, input_record, register_branch

TOL = 1.0  # 同一申报内分部合计核对的容差（原文单位）


def _records(inp: StudyInput) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta = inp.version.series
    bundle = meta.get("_bundle") or {}
    rows = ok_rows(inp.frame)
    values = dict(zip(rows["series_id"], rows["value"].astype(float)))
    return [{**m, "value": values[sid]} for sid, m in meta.items() if sid != "_bundle" and sid in values], bundle


def _name(snap: dict[str, Any], entity: str | None) -> str:
    return (snap["entities"].get(entity or "") or {}).get("name", entity or "")


def _activity(snap: dict[str, Any], activity: str | None) -> str | None:
    return (snap["activities"].get(activity or "") or {}).get("name") if activity else None


def _chain(snap: dict[str, Any], root: str, direction: str, depth: int, as_of: str) -> dict[str, Any]:
    c = expand(snap, root, direction, depth=depth, as_of=as_of)
    for layer in c["layers"]:
        for e in layer:
            e.update({"from_name": _name(snap, e["from"]), "to_name": _name(snap, e["to"]),
                      "activity_name": _activity(snap, e["activity"]),
                      "recipient_activity_name": _activity(snap, e["recipient_activity"]),
                      "disclosed_by_names": [_name(snap, x) for x in e["disclosed_by"]],
                      "evidence": [{"claim": cid, **{k: snap["claims"][cid].get(k) for k in
                                                       ("locator", "excerpt", "url", "form", "summary", "publisher",
                                                        "title", "published_at", "display")}}
                                   for cid in snap["relations"][e["relation"]]["claims"]]})
    for b in c["breakpoints"]:
        b["node_name"] = _name(snap, b["node"])
        if b["reason"] == "searched_not_disclosed":
            b["searches"] = [{"id": q, "note": snap["searches"][q].get("note"),
                              "url": snap["documents"][snap["searches"][q]["document"]]["url"]}
                             for q in b["detail"].split("；") if q in snap["searches"]]
    for s in c["side_relations"]:
        s["party_names"] = [_name(snap, p) for p in s["parties"]]
    counts: dict[str, int] = {}
    for b in c["breakpoints"]:
        counts[b["reason"]] = counts.get(b["reason"], 0) + 1
    c["breakpoint_counts"] = counts
    return c


def _reverse(snap: dict[str, Any], ids: list[str]) -> list[dict[str, Any]]:
    out = []
    for qid in ids:
        q = snap["searches"][qid]
        d = snap["documents"][q["document"]]
        out.append({"id": qid, "subject": q.get("subject_name") or _name(snap, q.get("subject")),
                    "form": d["form"], "period_end": d["document_period_end"], "url": d["url"],
                    "result": q["result"], "method": q["method"], "note": q.get("note")})
    return sorted(out, key=lambda x: x["subject"])


def _revenue(recs: list[dict[str, Any]], entity: str) -> dict[str, Any] | None:
    """一家公司一份年报中的营收：选观测最多的币种；合并营收与业务分部分列，同比只在同一申报、同一币种内计算。"""
    rows = [r for r in recs if r["entity"] == entity]
    if not rows:
        return None
    cons = [r for r in rows if r["kind"] == "revenue"]
    units: dict[str, int] = {}
    for r in cons:
        units[r["unit"]] = units.get(r["unit"], 0) + 1
    unit = max(sorted(units), key=lambda u: units[u])

    def series(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out, prev = [], None
        for r in sorted(items, key=lambda x: x["end"]):
            row = {"period_end": r["end"], "value": r["value"]}
            if prev is not None and prev > 0:
                row["growth"] = r["value"] / prev - 1
            out.append(row)
            prev = r["value"]
        return out
    segs: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r["kind"] == "segment_revenue" and r["unit"] == unit:
            segs.setdefault(r["segment"], []).append(r)
    first = rows[0]
    return {"entity": entity, "unit": unit, "document": first["document"], "form": first["form"],
            "accession": first["accession"], "document_period_end": first["document_period_end"],
            "consolidated": series([r for r in cons if r["unit"] == unit]),
            "segments": {k: series(v) for k, v in sorted(segs.items())},
            "other_units": sorted(u for u in units if u != unit)}


def _segment_check(rev: dict[str, Any]) -> list[dict[str, Any]]:
    """业务分部（含 AllOtherSegments）之和与合并营收逐年比较；只有一个分部的公司不核对。"""
    if len(rev["segments"]) < 2:
        return []
    out = []
    for row in rev["consolidated"]:
        parts = [x["value"] for s in rev["segments"].values() for x in s if x["period_end"] == row["period_end"]]
        if len(parts) != len(rev["segments"]):
            out.append({"entity": rev["entity"], "period_end": row["period_end"], "status": "skipped",
                        "reason": "部分分部缺少该财年"})
            continue
        diff = sum(parts) - row["value"]
        out.append({"entity": rev["entity"], "period_end": row["period_end"], "diff": diff,
                    "status": "pass" if abs(diff) <= TOL else "fail"})
    return out


@register_branch("relation_chain", result_types=(ResultType.DESCRIPTIVE,))
def run(study: StudySpec, inputs: dict[str, StudyInput], registry: Registry) -> ResearchResult:
    if study.result_type is not ResultType.DESCRIPTIVE:
        raise ValueError("relation_chain 分支只产出描述成果")
    inp = inputs["evidence"]
    recs, bundle = _records(inp)
    check = bundle.get("catalog_check") or {}
    if check.get("errors") or check.get("warnings"):
        raise ValueError("证据包记录的产业链登记核对有错误或未核对项，不能用于研究")
    snap = bundle["snapshot"]
    m = study.method
    root, depth, as_of = m["root"], int(m.get("depth", 2)), str(m["as_of"])

    up = _chain(snap, root, "upstream", depth, as_of)
    down = _chain(snap, root, "downstream", depth, as_of)
    reverse = _reverse(snap, down["searches"])
    notes = [{"claim": cid, **{k: snap["claims"][cid].get(k) for k in ("locator", "excerpt", "url", "limits")}}
             for cid in m.get("downstream_notes", [])]

    suppliers = []
    for e in up["layers"][0] if up["layers"] else []:
        if e["counterparty_type"] == "company" and e["to"] not in suppliers:
            suppliers.append(e["to"])
    revenue = {x: rev for x in [root, *suppliers] if (rev := _revenue(recs, x))}
    missing = [x for x in suppliers if x not in revenue]

    named_down = sorted({e["to"] for layer in down["layers"] for e in layer if e["counterparty_type"] == "company"})
    unsupported = [{"item": "链上各公司受影响的金额或比例", "kind": "scope",
                    "reason": "关系链只描述登记的关系；对方收入中来自起点公司的份额大多未披露，各层占比不相乘、不推算间接敞口"},
                   {"item": "因果判断", "kind": "scope",
                    "reason": "同期营收变化不说明由起点公司带动或拉动"}]
    if missing:
        unsupported.append({"item": "营收对照：" + "、".join(_name(snap, x) for x in missing), "kind": "data",
                            "reason": "这些公司不在 SEC 申报，第一版尚未取得其年报"})
    if not named_down:
        unsupported.append({"item": "Q2b 下游客户资本开支对照", "kind": "data",
                            "reason": f"下游链上没有原文点名的公司：起点的直接客户匿名，反向检索的 {len(reverse)} 家公司年报都没有点名"})

    checks = [row for rev in revenue.values() for row in _segment_check(rev)]
    validation = {"catalog_check": {"status": "pass", "checked": sum((check.get("verified") or {}).values()),
                                    "reason": "证据包生成前产业链登记核对零错误、零未核对"}}
    if checks:
        statuses = {x["status"] for x in checks}
        validation["segment_total"] = {"status": "fail" if "fail" in statuses else "pass" if statuses == {"pass"} else "skipped",
                                       "checked": sum(x["status"] != "skipped" for x in checks), "rows": checks}

    edges = [e for c in (up, down) for layer in c["layers"] for e in layer]
    cutoff = max((r["published_at"] for r in recs if r["entity"] in revenue), default=None)
    return ResearchResult(
        study_id=study.study_id, title=study.title, question=study.question, result_type=study.result_type,
        branch=study.branch, scope=study.scope, data_cutoff=cutoff,
        methods={
            "description": "从固定的关系链证据包按登记的有向关系向上游、下游逐层展开：方向不混用，只沿与上一条边相关的业务展开，"
                           "只经过已复核的关系，匿名对手方、业务未定、未复核与层数上限处停止，并按查阅记录区分「已查原文、未披露」与"
                           "「尚未查阅」。营收取自各公司自己的一份年报（三个财年），只计算同一申报、同一币种内的同比。",
            "parameters": m,
            "bundle": {k: bundle.get(k) for k in ("built_at", "catalog_files", "revenue_documents")},
            "catalog_version": snap.get("catalog_version"),
        },
        inputs=[input_record(inp)],
        results={"root": root, "root_name": _name(snap, root), "as_of": as_of, "depth": depth,
                 "upstream": up, "downstream": down, "reverse_search": reverse, "downstream_notes": notes,
                 "revenue": revenue, "revenue_missing": [{"entity": x, "name": _name(snap, x)} for x in missing],
                 "summary": {"upstream_named": len(suppliers),
                             "upstream_edges": sum(len(x) for x in up["layers"]),
                             "downstream_named": len(named_down), "reverse_searched": len(reverse),
                             "reverse_found": sum(x["result"] == "found" for x in reverse),
                             "breakpoints": {"upstream": up["breakpoint_counts"], "downstream": down["breakpoint_counts"]}}},
        coverage={"edges": len(edges), "completeness": "partial" if any(u["kind"] == "data" for u in unsupported) else "complete"},
        unsupported=unsupported, limitations=list(study.limitations), validation=validation,
        tables={"edges": [{k: e[k] for k in ("relation", "layer", "from", "to", "type", "activity", "status",
                                              "evidence_class")} | {"direction": "upstream" if e in sum(up["layers"], []) else "downstream"}
                          for e in edges],
                "breakpoints": [{**{k: b[k] for k in ("node", "layer", "reason", "relation")}, "direction": d}
                                for d, c in (("upstream", up), ("downstream", down)) for b in c["breakpoints"]]},
    )
