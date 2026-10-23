"""收集网站所需的记录：运行、数据集、交互图表数据。只读取，不计算研究结果。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..analytics.rates import curvature_label, spread_label
from ..data.store import DataStore
from ..registry import Registry
from ..research.findings import findings
from ..runs import list_runs
from ..tenor import is_tenor, parse_tenor


def load_run(root: Path, run_id: str) -> dict[str, Any]:
    run_dir = root / "runs" / run_id
    vpath = run_dir / "verifications.jsonl"
    verifications = [json.loads(x) for x in vpath.read_text(encoding="utf-8").splitlines() if x] \
        if vpath.exists() else []
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    return {"manifest": json.loads((run_dir / "manifest.json").read_text(encoding="utf-8")),
            "result": result, "findings": findings(result),
            "verification": verifications[-1] if verifications else None}


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


def daily_json(result: dict[str, Any]) -> dict[str, Any]:
    """交互图表数据：直接取结果中的合格日度表，不插值、不填补。"""
    res = result.get("results", {})
    daily = result.get("tables", {}).get("daily", [])
    columns = {k for row in daily for k in row if k != "date"}
    tenors = sorted((c for c in columns if is_tenor(c)), key=lambda c: parse_tenor(c).months)
    return {
        "run_id": result.get("run_id"),
        "levels": list(res.get("levels", {})),
        "tenors": [{"code": t, "months": parse_tenor(t).months} for t in tenors],
        "spreads": [{"key": k, "label": spread_label(k)} for k in res.get("spreads", {})],
        "curvature": [{"key": f"curvature {k}", "label": curvature_label(k)} for k in res.get("curvature", {})],
        "rows": daily,
    }
