"""研究门户（静态网站）：把登记、数据目录、运行记录与报告发布为可浏览的研究成果（模块 O）。

网站只读取已有的结构化记录，不重新计算研究结果。各页面的分工：

- 系统研究什么、从哪里进入：首页按研究框架（分支 → 方向 → 研究）组织，研究焦点只显示关键数字
- 研究发现了什么：研究页（studies/<id>/）的关键发现与图表
- 这些发现有多可靠：研究页的证据面板与数据覆盖、数据与方法页
- 系统能研究什么：研究能力地图（map.html）；系统状态放在页脚与 methods.html#status

输出：

    index.html                      研究总览
    studies/<study_id>/index.html   研究页（最新运行；地址不变）
    runs/<run_id>/                  每次运行：完整报告、图表、chart.json（交互图表数据）、manifest.json、result.json
    latest/<study_id>/report.html   最新完整报告的稳定地址
    history/<study_id>.html         旧地址，转到研究页的历史部分
    map.html、methods.html           研究能力地图；数据、方法与状态
    summary.json                    页面所示内容的机器可读摘要
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ..archive import archived_runs
from ..data.store import DataStore
from ..maintenance import check_calendar
from ..registry import Registry
from .capability import capability_page, framework, summary
from .collect import collect_runs, datasets, ordered_studies
from .common import repo_url
from .home import home_page
from .methods import methods_page
from .renderers import get_renderer
from .study import redirect, study_page

__all__ = ["build_site"]


def _copy_run(root: Path, item: dict[str, Any], dest: Path) -> list[str]:
    """复制报告、图表与原始记录。报告顶部加返回导航。返回复制的图表文件名。"""
    dest.mkdir(parents=True, exist_ok=True)
    manifest = item["manifest"]
    figures = []
    for out in manifest.get("outputs", []):
        src = root / out["path"]
        if src.name == "report.html":
            text = src.read_text(encoding="utf-8").replace(
                "<main><h1>",
                '<main><p style="margin:0 0 1rem"><a href="../../index.html">← 返回研究总览</a></p><h1>', 1)
            (dest / "report.html").write_text(text, encoding="utf-8")
        elif src.suffix == ".png":
            (dest / "figures").mkdir(exist_ok=True)
            shutil.copy2(src, dest / "figures" / src.name)
            figures.append(src.name)
    run_dir = root / "runs" / manifest["run_id"]
    for name in ("manifest.json", "result.json"):
        shutil.copy2(run_dir / name, dest / name)
    chart = get_renderer(item["result"]["branch"]).chart_data(item["result"])
    if chart is not None:
        (dest / "chart.json").write_text(json.dumps(chart, ensure_ascii=False), encoding="utf-8")
    return figures


def _calendar_checks(root: Path, registry: Registry) -> dict[str, Any]:
    """每个日历的核验状态（只读，不写入登记）；本次构建没有数据时如实说明。"""
    out: dict[str, Any] = {}
    for cal_id in registry.calendars:
        try:
            out[cal_id] = check_calendar(root, cal_id)
        except (ValueError, LookupError) as exc:
            out[cal_id] = {"status": "unavailable", "message": str(exc)}
    return out


def _asset_version(assets: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in assets.rglob("*") if p.is_file()):
        digest.update(path.relative_to(assets).as_posix().encode("utf-8") + b"\0" + path.read_bytes())
    return digest.hexdigest()[:10]


def build_site(root: Path, out: Path, archive: Path | None = None) -> Path:
    """生成网站。给出 archive 时，研究历史只列已归档运行（地址长期有效）与本次最新运行。"""
    root, out = Path(root), Path(out)
    content = yaml.safe_load((root / "site" / "content.yaml").read_text(encoding="utf-8")) or {}
    registry, store = Registry.load(root), DataStore(root)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copytree(root / "site" / "assets", out / "assets")
    archived = archived_runs(archive) if archive is not None else None

    by_study = collect_runs(root)
    studies = ordered_studies(by_study, content)
    latest: dict[str, dict[str, Any]] = {}
    shown: dict[str, list[dict[str, Any]]] = {}
    for study_id in studies:
        runs = by_study[study_id]
        if archived is not None:
            runs = [r for i, r in enumerate(runs) if i == 0 or r["manifest"]["run_id"] in archived]
        for item in runs:
            item["figures"] = _copy_run(root, item, out / "runs" / item["manifest"]["run_id"])
        latest[study_id], shown[study_id] = runs[0], runs

    ds_rows = datasets(registry, store)
    ds_by_id = {d["dataset_id"]: d for d in ds_rows}
    commit = next(iter(latest.values()))["manifest"]["code"].get("git_commit") if latest else None
    build = {
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "commit": os.environ.get("GITHUB_SHA") or commit,
        "repo_url": repo_url(root),
        "tagline": content.get("tagline", ""),
        "asset_version": _asset_version(out / "assets"),
    }

    for study_id in studies:
        page_dir = out / "studies" / study_id
        page_dir.mkdir(parents=True)
        (page_dir / "index.html").write_text(
            study_page(study_id, shown[study_id], archived, registry, content, build), encoding="utf-8")
        run_id = latest[study_id]["manifest"]["run_id"]
        (out / "latest" / study_id).mkdir(parents=True)
        shutil.copy2(out / "runs" / run_id / "report.html", out / "latest" / study_id / "report.html")
        (out / "history").mkdir(exist_ok=True)
        (out / "history" / f"{study_id}.html").write_text(
            redirect(f"../studies/{study_id}/#history"), encoding="utf-8")

    calendar_checks = _calendar_checks(root, registry)
    cap = summary(content, registry, ds_by_id, latest)
    (out / "index.html").write_text(home_page(studies, latest, content, build, framework(content, registry, ds_by_id, latest)),
                                     encoding="utf-8")
    (out / "map.html").write_text(capability_page(content, registry, ds_by_id, latest, build), encoding="utf-8")
    (out / "methods.html").write_text(methods_page(content, registry, ds_rows, latest, build, calendar_checks),
                                      encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    doc = {
        "build": build,
        "capability": cap,
        "calendar_checks": calendar_checks,
        "datasets": ds_rows,
        "runs": [{
            "run_id": i["manifest"]["run_id"], "study_id": s,
            "status": i["manifest"]["status"], "result_hash": i["manifest"].get("result_hash"),
            "code": i["manifest"]["code"], "inputs": i["manifest"].get("inputs", []),
            "data_cutoff": i["result"]["data_cutoff"], "findings": i["findings"],
            "coverage": {k: i["result"]["coverage"].get(k)
                         for k in ("expected_days", "due_days", "curve_days", "missing_days", "pending_days",
                                   "coverage_acceptable", "period_complete", "completeness",
                                   "calendar_unverified")},
            "unsupported": i["result"].get("unsupported", []),
            "validation": {k: v.get("status") for k, v in i["result"]["validation"].items()},
            "reproduced": i["verification"]["reproduced"] if i["verification"] else None,
            "history": len(shown[s]),
        } for s, i in latest.items()],
    }
    (out / "summary.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return out / "index.html"
