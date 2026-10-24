"""收集网站所需的记录：运行、数据集、交互图表数据。只读取，不计算研究结果。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..data.store import DataStore
from ..registry import Registry
from ..research.findings import interpret, rule_fingerprint, rule_params
from ..runs import check_artifacts, list_runs
from .i18n import L


def load_run(root: Path, run_id: str) -> dict[str, Any]:
    run_dir = root / "runs" / run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    integrity = check_artifacts(root, manifest)
    vpath = run_dir / "verifications.jsonl"
    verifications = [json.loads(x) for x in vpath.read_text(encoding="utf-8").splitlines() if x] \
        if vpath.exists() else []
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    interpretation = load_interpretation(result)
    return {"manifest": manifest, "artifact_integrity": integrity,
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
        out.append(L("研究窗口 ", "Study window ") + f"{ps.get('start')}—{ps.get('end')} → {cs.get('start')}—{cs.get('end')}")
    prev_inputs = {i["role"]: i for i in prev["manifest"].get("inputs", []) if i.get("used", True)}
    for i in cur["manifest"].get("inputs", []):
        if not i.get("used", True):
            continue
        before = prev_inputs.get(i["role"])
        if before is None:
            out.append(L("新增输入 ", "New input ") + i["dataset_id"])
        elif before.get("content_hash") != i.get("content_hash"):
            out.append(L(f"数据版本 {i['dataset_id']}：", f"Data version {i['dataset_id']}: ")
                       + f"{before['version_id']} → {i['version_id']}")
    pc, cc = prev["manifest"].get("code", {}), cur["manifest"].get("code", {})
    if pc.get("source_hash") and cc.get("source_hash"):
        if pc["source_hash"] != cc["source_hash"]:
            out.append(L("代码或配置 ", "Code or config ") + f"{pc['source_hash'][:8]} → {cc['source_hash'][:8]}")
    elif pc.get("git_commit") != cc.get("git_commit"):
        out.append(L("代码提交 ", "Code commit ") + f"{(pc.get('git_commit') or '—')[:7]} → {(cc.get('git_commit') or '—')[:7]}")
    pi, ci = prev.get("interpretation") or {}, cur.get("interpretation") or {}
    if pi.get("origin") == "retrospective" or ci.get("origin") == "retrospective":
        out.append(L("至少一次运行的发现为事后生成", "Findings of at least one run were generated retrospectively"))
    elif pi.get("rule_fingerprint") != ci.get("rule_fingerprint") or pi.get("params") != ci.get("params"):
        lp, rp = L("（", " ("), L("）", ")")
        out.append(L("解释规则 ", "Interpretation rule ")
                   + f"{pi.get('rule_version')}{lp}{(pi.get('rule_fingerprint') or '—')[:8]}{rp} → "
                   f"{ci.get('rule_version')}{lp}{(ci.get('rule_fingerprint') or '—')[:8]}{rp}")
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


def skip_reason(connector: str, signup: str, scheduled: bool) -> str | None:
    """数据集为什么不在 CI 中取得（由登记推出）；None 表示应当取得，没取得才是异常。

    分工：接入核验与快照在本机完成；CI 只取无需凭证、登记了定时取得的数据集。
    """
    if connector == "manual_csv":
        return "manual"
    if connector == "sec_edgar":
        return "contact"
    if signup == "free_key":
        return "key"
    if not scheduled:
        return "unscheduled"
    return None


def not_fetched_label(reason: str | None, short: bool = False) -> str:
    """未取得时显示的说明：有意不取时写明原因，否则如实写「未取得」。"""
    if reason == "manual":
        return L("人工导入，不自动取得", "manual import, not fetched automatically")
    if reason == "key":
        return L("需要 API key，只在本机取得", "needs an API key; fetched locally only")
    if reason == "contact":
        return L("需要联系邮箱（SEC_USER_AGENT），只在本机取得", "needs a contact address (SEC_USER_AGENT); fetched locally only")
    if reason == "unscheduled":
        return L("未登记定时取得，只在本机取得", "not scheduled; fetched locally only")
    return L("未取得", "not fetched") if short else L("本次构建未取得", "Not fetched in this build")


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
            "scheduled": d.scheduled_fetch is not None,
            "skip_reason": skip_reason(d.connector, src.signup, d.scheduled_fetch is not None),
            "status": src.status_for(d.id).value,
            "verified_uses": [u.value for u in src.verified_uses(d.id)],
            "version_id": v.version_id if v else None,
            "rows": v.rows if v else None,
            "status_counts": v.quality.get("status_counts", {}) if v else {},
            "last_fetch": {"status": last.get("status"), "at": last.get("finished_at") or last.get("started_at")}
            if last else None,
        })
    return rows


# SEC 财报不在 datasets.yaml 中（docs/edgar-design.md）：网站按来源显示两行，id 与来源登记中的核验记录一致。
# 说明文字与其他数据集一样存中文，英文页面渲染时按 site/en.yaml 翻译
EDGAR_ROWS = {
    "fsds": ("edgar_fsds", "quarterly", "SEC 财报数据集（FSDS）：登记公司 2009 年起的申报与合并口径财报事实",
             "EDGAR 接受时间次日 0 点（美东）"),
    "companyfacts": ("edgar_companyfacts", "daily",
                     "SEC Company Facts：同一批公司的财报事实，补上封面数据与 FSDS 尚未收录的新申报",
                     "申报日期次日 0 点（美东）"),
}


def fundamentals_datasets(registry: Registry, root: Path) -> list[dict[str, Any]]:
    """SEC 财报两个来源的行，字段与 datasets() 相同；本次构建没有财报数据时（如 CI）如实显示未取得及原因。"""
    from ..data.fundamentals import EdgarStore

    if registry.fundamentals is None or "sec_edgar" not in registry.sources:
        return []
    src = registry.sources["sec_edgar"]
    store = EdgarStore(root)
    parts = store.partitions()
    rows = []
    for source, (ds_id, frequency, description, availability) in EDGAR_ROWS.items():
        current: dict[tuple[str, str], dict[str, Any]] = {}
        for entry in parts:
            if entry["source"] == source:
                current[(entry["table"], entry["key"])] = entry
        facts = [v for (table, _), v in current.items() if table == "facts"]
        filings = [v for (table, _), v in current.items() if table == "filings"]
        if source == "fsds":
            checks = [c for c in store.remote_checks() if c.get("action") != "not_published"]
            last = checks[-1] if checks else None
            last_fetch = {"status": {"failed": "failed", "unchanged": "unchanged"}.get(
                last.get("action"), "created" if last.get("facts") == "created" else "unchanged"),
                "at": last["checked_at"]} if last else None
        else:
            fetches = store.api_fetches()
            last = fetches[-1] if fetches else None
            last_fetch = {"status": "failed" if last.get("status") == "failed" else
                          ("created" if last.get("facts") == "created" else "unchanged"),
                          "at": last["at"]} if last else None
        latest = max(facts, key=lambda v: v["created_at"]) if facts else None
        rows.append({
            "dataset_id": ds_id,
            "description": description,
            "source": src.publisher,
            "source_id": src.id,
            "frequency": frequency,
            "vintages": "supplier",  # 申报编号即供应方版本，接受时间即发布时间
            "availability": availability,
            "calendar": None,
            "archive_data": False,
            "scheduled": True,  # 本机定时任务运行 iros edgar sync
            "skip_reason": skip_reason("sec_edgar", src.signup, True),
            "status": src.status_for(ds_id).value,
            "verified_uses": [],
            "version_id": latest["version_id"] if latest else None,
            "rows": sum(v["rows"] for v in facts) if facts else None,
            "status_counts": {"filings": sum(v["rows"] for v in filings),
                              "companies": len(registry.fundamentals.companies)} if facts else {},
            "last_fetch": last_fetch,
        })
    return rows
