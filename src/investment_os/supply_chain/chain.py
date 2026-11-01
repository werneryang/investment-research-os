"""关系链：从一个主体出发，按登记的有向关系逐层展开（docs/relation-chain-design.md §2）。

输入是产业链登记的快照（见 relation_bundle.snapshot），不是 Catalog，研究可以只从固定的证据包重算。
展开规则：
1. 方向不混用：上游只找提供方（当前节点是接收方），下游只找接收方（当前节点是提供方）
2. 竞争、合作与替代不展开，只作为链上节点的旁注
3. 按业务收窄：上游经某条边到达节点 X 后，只沿 recipient_activity 等于该边业务（activity）的输入继续展开；
   下游经某条边到达 X 后，只沿 X 提供的业务（activity）等于该边 recipient_activity 的关系继续展开；业务未定的边不展开
4. 只经过已复核（reviewed / confirmed）的关系；候选关系照常显示，标为未复核，不展开
5. 匿名对手方是断点
6. 层数上限（默认两层）
7. 截至日期：关系的最早证据公开时间不晚于截至日期才进入链条；查阅记录的原文同样按截至日期筛选
8. 回路：前几层已在链上的节点（含起点）再次出现时只记录这条边，不再展开；同一层经不同业务到达同一主体
   （如三星既是晶圆代工方又是存储供应方）按业务分别展开，同一主体与业务只展开一次
外部来源：只有外部来源的关系不展开；expand_corroborated 为真时，有一手旁证的外部来源关系可以展开，其后的边都标
「路径含外部来源」。

每个停止展开的节点都记录断点原因；「已查原文、未披露」与「尚未查阅」由查阅记录区分。
关系链只描述登记关系的结构，不计算任何敞口：占比原样附在边上，不相乘。
"""

from __future__ import annotations

from typing import Any

DIRECTED = ("supply", "foundry", "contract_manufacturing")
REVIEWED = ("reviewed", "confirmed")
EXCLUDED = ("invalid", "rejected", "retracted")

BREAKPOINTS = ("anonymous", "activity_unknown", "unreviewed", "external_only", "searched_not_disclosed",
               "not_searched", "depth_limit")


def _ends(r: dict[str, Any], direction: str) -> tuple[str | None, str | None]:
    """(当前节点一侧, 对手方一侧)。"""
    return (r.get("recipient"), r.get("provider")) if direction == "upstream" else (r.get("provider"), r.get("recipient"))


def _visible(item: dict[str, Any], as_of: str | None) -> bool:
    return as_of is None or (item.get("available_at") is not None and str(item["available_at"])[:10] <= as_of)


def expand(snap: dict[str, Any], root: str, direction: str, depth: int = 2, as_of: str | None = None,
           expand_corroborated: bool = False) -> dict[str, Any]:
    if direction not in ("upstream", "downstream"):
        raise ValueError(f"未知方向：{direction}")
    if root not in snap["entities"]:
        raise ValueError(f"关系链起点未登记：{root}")
    entities, relations = snap["entities"], snap["relations"]
    directed = {rid: r for rid, r in relations.items() if r["type"] in DIRECTED and r.get("status") not in EXCLUDED
                and _visible(r, as_of)}
    searches = [q for q in snap.get("searches", {}).values() if q["direction"] == direction and _visible(q, as_of)]

    layers: list[list[dict[str, Any]]] = []
    breakpoints: list[dict[str, Any]] = []
    on_chain = {root}  # 前几层的节点
    keys: set[tuple[str, str | None]] = set()  # 已安排展开的（主体，业务）
    frontier: list[tuple[str, dict[str, Any] | None]] = [(root, None)]

    def stop(node: str, layer: int, reason: str, edge: dict[str, Any] | None, detail: str = "") -> None:
        breakpoints.append({"node": node, "layer": layer, "reason": reason, "relation": edge and edge["relation"],
                            "detail": detail})

    for layer in range(1, depth + 1):
        edges: list[dict[str, Any]] = []
        nxt: list[tuple[str, dict[str, Any] | None]] = []
        for node, arrival in frontier:
            if arrival is None:
                allowed = None  # 起点：不按业务收窄
            elif direction == "upstream":
                allowed = arrival["activity"]
            else:
                allowed = arrival["recipient_activity"]
            found = []
            for rid, r in sorted(directed.items()):
                here, there = _ends(r, direction)
                if here != node:
                    continue
                if arrival is not None:
                    serves = r.get("recipient_activity") if direction == "upstream" else r.get("activity")
                    if serves != allowed:
                        continue  # 服务于节点的其他业务，或未说明服务于哪项业务
                external = r.get("evidence_class", "primary") != "primary" or bool(arrival and arrival["external_path"])
                found.append({
                    "relation": rid, "layer": layer, "from": node, "to": there, "type": r["type"],
                    "activity": r.get("activity"), "recipient_activity": r.get("recipient_activity"),
                    "activity_gap": r.get("activity_gap"), "product": r.get("product"), "share": r.get("share"),
                    "status": r.get("status"), "evidence_class": r.get("evidence_class", "primary"),
                    "disclosed_by": r.get("disclosed_by", []), "available_at": r.get("available_at"),
                    "limits": r.get("limits", ""), "note": r.get("note"), "external_path": external,
                    "counterparty_type": entities.get(there, {}).get("type"), "cycle": there in on_chain,
                })
            edges += found
            if arrival is not None:
                named = [e for e in found if e["counterparty_type"] != "anonymous"]
                if not named:
                    done = [q for q in searches if q.get("subject") == node]
                    if done:
                        stop(node, layer, "searched_not_disclosed", arrival, "；".join(q["id"] for q in done))
                    else:
                        stop(node, layer, "not_searched", arrival)
            for e in found:
                there = e["to"]
                business = e["activity"] if direction == "upstream" else e["recipient_activity"]
                if e["cycle"] or (there, business) in keys:
                    continue
                keys.add((there, business))
                if e["counterparty_type"] == "anonymous":
                    stop(there, layer, "anonymous", e)
                elif e["status"] not in REVIEWED:
                    stop(there, layer, "unreviewed", e)
                elif e["evidence_class"] == "external" or (
                        e["evidence_class"] == "external_corroborated" and not expand_corroborated):
                    stop(there, layer, "external_only", e)
                elif (direction == "upstream" and not e["activity"]) or (
                        direction == "downstream" and not e["recipient_activity"]):
                    stop(there, layer, "activity_unknown", e, e.get("activity_gap") or "")
                elif layer == depth:
                    stop(there, layer, "depth_limit", e)
                else:
                    nxt.append((there, e))
        layers.append(edges)
        on_chain |= {e["to"] for e in edges}
        frontier = nxt
        if not frontier:
            break

    side = []
    for rid, r in sorted(relations.items()):
        parties = r.get("parties") or []
        if r["type"] not in DIRECTED and r.get("status") not in EXCLUDED and _visible(r, as_of) \
                and any(p in on_chain for p in parties):
            side.append({"relation": rid, "type": r["type"], "parties": parties, "market": r.get("market"),
                         "status": r.get("status")})
    return {"root": root, "direction": direction, "depth": depth, "as_of": as_of, "layers": layers,
            "breakpoints": breakpoints, "side_relations": side,
            "searches": [q["id"] for q in searches if q.get("counterpart") == root]}
