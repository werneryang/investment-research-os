"""收集网站所需的记录：运行、数据集、交互图表数据。只读取，不计算研究结果。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..data.store import DataStore
from ..registry import Registry
from ..research.findings import interpret, rule_fingerprint, rule_params
from ..runs import list_runs


def load_run(root: Path, run_id: str) -> dict[str, Any]:
    run_dir = root / "runs" / run_id
    vpath = run_dir / "verifications.jsonl"
    verifications = [json.loads(x) for x in vpath.read_text(encoding="utf-8").splitlines() if x] \
        if vpath.exists() else []
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    interpretation = load_interpretation(result)
    return {"manifest": json.loads((run_dir / "manifest.json").read_text(encoding="utf-8")),
            "result": result, "interpretation": interpretation,
            "findings": interpretation["items"] if interpretation else [],
            "verification": verifications[-1] if verifications else None}


def load_interpretation(result: dict[str, Any]) -> dict[str, Any] | None:
    """运行时记录的解释优先；没有记录（旧运行）时用当前规则事后生成，并标明来源。

    origin：recorded（运行时记录）或 retrospective（事后生成）；
    rules_changed：记录时的规则指纹与当前规则不同（只在 recorded 时有意义）。
    """
    stored = result.get("interpretation")
    branch = result.get("branch", "")
    current = rule_fingerprint(branch)
    if stored:
        changed = current is not None and (stored.get("rule_fingerprint") != current
                                           or stored.get("params") != rule_params(branch))
        return {**stored, "origin": "recorded", "rules_changed": changed}
    generated = interpret(result)
    return {**generated, "origin": "retrospective", "rules_changed": False} if generated else None


def run_differences(prev: dict[str, Any], cur: dict[str, Any]) -> list[str]:
    """两次运行之间可以客观比较的差异：研究窗口、数据版本、代码、解释规则。不推断原因。"""
    out = []
    ps, cs = prev["result"]["scope"], cur["result"]["scope"]
    if (ps.get("start"), ps.get("end")) != (cs.get("start"), cs.get("end")):
        out.append(f"研究窗口 {ps.get('start')}—{ps.get('end')} → {cs.get('start')}—{cs.get('end')}")
    prev_inputs = {i["role"]: i for i in prev["manifest"].get("inputs", []) if i.get("used", True)}
    for i in cur["manifest"].get("inputs", []):
        if not i.get("used", True):
            continue
        before = prev_inputs.get(i["role"])
        if before is None:
            out.append(f"新增输入 {i['dataset_id']}")
        elif before.get("content_hash") != i.get("content_hash"):
            out.append(f"数据版本 {i['dataset_id']}：{before['version_id']} → {i['version_id']}")
    pc, cc = prev["manifest"].get("code", {}), cur["manifest"].get("code", {})
    if pc.get("source_hash") and cc.get("source_hash"):
        if pc["source_hash"] != cc["source_hash"]:
            out.append(f"代码或配置 {pc['source_hash'][:8]} → {cc['source_hash'][:8]}")
    elif pc.get("git_commit") != cc.get("git_commit"):
        out.append(f"代码提交 {(pc.get('git_commit') or '—')[:7]} → {(cc.get('git_commit') or '—')[:7]}")
    pi, ci = prev.get("interpretation") or {}, cur.get("interpretation") or {}
    if pi.get("origin") == "retrospective" or ci.get("origin") == "retrospective":
        out.append("至少一次运行的发现为事后生成")
    elif pi.get("rule_fingerprint") != ci.get("rule_fingerprint") or pi.get("params") != ci.get("params"):
        out.append(f"解释规则 {pi.get('rule_version')}（{(pi.get('rule_fingerprint') or '—')[:8]}）→ "
                   f"{ci.get('rule_version')}（{(ci.get('rule_fingerprint') or '—')[:8]}）")
    return out


def collect_runs(root: Path) -> dict[str, list[dict[str, Any]]]:
    """study_id → 未失败的运行，按时间从新到旧。"""
    by_study: dict[str, list[dict[str, Any]]] = {}
    for r in list_runs(root):
        if r["status"] in (None, "failed", "running"):
            continue
        # started_at 只精确到秒；同一秒的运行按清单写入时间（纳秒）区分先后
        order = (r["started_at"], (root / "runs" / r["run_id"] / "manifest.json").stat().st_mtime_ns)
        by_study.setdefault(r["study_id"], []).append({**load_run(root, r["run_id"]), "_order": order})
    for runs in by_study.values():
        runs.sort(key=lambda x: x["_order"], reverse=True)
    return by_study


def ordered_studies(by_study: dict[str, Any], content: dict[str, Any]) -> list[str]:
    preferred = [s for s in content.get("study_order", []) if s in by_study]
    return preferred + sorted(s for s in by_study if s not in preferred)


def datasets(registry: Registry, store: DataStore) -> list[dict[str, Any]]:
    log = store.fetch_log()
    rows = []
    for d in registry.datasets.values():
        src = registry.sources[d.source_id]
        v = store.latest(d.id)
        terminal = [x for x in log if x.get("dataset_id") == d.id and x.get("status") != "started"]
        last = terminal[-1] if terminal else None
        rows.append({
            "dataset_id": d.id,
            "description": d.description,
            "source": src.publisher,
            "source_id": src.id,
            "frequency": d.frequency,
            "vintages": d.vintages.value,
            "availability": d.availability.describe(),
            "calendar": d.calendar,
            "archive_data": d.archive_data,
            "status": src.status_for(d.id).value,
            "verified_uses": [u.value for u in src.verified_uses(d.id)],
            "version_id": v.version_id if v else None,
            "rows": v.rows if v else None,
            "status_counts": v.quality.get("status_counts", {}) if v else {},
            "last_fetch": {"status": last.get("status"), "at": last.get("finished_at") or last.get("started_at")}
            if last else None,
        })
    return rows
