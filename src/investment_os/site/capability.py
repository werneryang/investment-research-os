"""研究能力地图：每个研究领域的数据、分析与验证状态。

状态由登记（数据集、来源核验）、研究定义与最新运行自动得出；只有「规划中」的领域
写在 site/content.yaml。工程完成（代码可运行、测试通过）与研究验证完成（用途核验）分开显示。
"""

from __future__ import annotations

from typing import Any

from ..contracts import ResultType, Use
from ..registry import Registry
from ..research import branch_result_types
from .common import RESULT_TYPE_LABEL, STATUS_LABEL, VERIFY_LABEL, chip, e, shell

USE_SHORT = {Use.DESCRIPTIVE: "历史描述", Use.POINT_IN_TIME: "时点研究"}


def domain_status(domain: dict[str, Any], registry: Registry, datasets: dict[str, dict[str, Any]],
                  latest: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """一个研究领域的三层状态。"""
    if domain.get("planned"):
        return {"category": "planned"}
    ds_rows = []
    for ds_id in domain.get("datasets", []):
        d = datasets.get(ds_id)
        if d is None:
            continue
        ds_rows.append({"id": ds_id, "status": d["status"], "has_data": d["version_id"] is not None,
                        "uses": d["verified_uses"]})
    studies = [s for s in domain.get("studies", []) if s in latest]
    runs = [{"study_id": s, "status": latest[s]["manifest"]["status"],
             "branch": latest[s]["result"]["branch"], "use": _use(latest[s]["result"])} for s in studies]
    validated: dict[tuple[str, Use], Any] = {}
    for run in runs:
        for ds in domain.get("datasets", []):
            spec = registry.datasets.get(ds)
            record = registry.sources[spec.source_id].use_record(ds, run["use"]) if spec else None
            if record is not None:
                validated[(ds, run["use"])] = record
    used = {r["use"] for r in runs}
    unvalidated = [d for d in domain.get("datasets", [])
                   if d in datasets and not any((d, u) in validated for u in used)]
    if runs:
        category = "active"
    elif any(r["has_data"] for r in ds_rows):
        category = "data_only"
    else:
        category = "registered" if ds_rows else "planned"  # 已登记数据集但本次构建未取得，不是「规划」
    return {"category": category, "datasets": ds_rows, "runs": runs,
            "validated": [(ds, u, rec) for (ds, u), rec in sorted(validated.items(), key=lambda kv: kv[0])],
            "unvalidated": unvalidated if runs else []}


def _use(result: dict[str, Any]) -> Use:
    return Use.POINT_IN_TIME if result["scope"].get("vintage_policy") == "as_of" else Use.DESCRIPTIVE


def summary(content: dict[str, Any], registry: Registry, datasets: dict[str, dict[str, Any]],
            latest: dict[str, dict[str, Any]]) -> dict[str, int]:
    out = {"active": 0, "data_only": 0, "registered": 0, "planned": 0}
    for d in content.get("domains", []):
        out[domain_status(d, registry, datasets, latest)["category"]] += 1
    return out


def _domain_row(domain: dict[str, Any], st: dict[str, Any]) -> str:
    can = "".join(f"<li>{e(x)}</li>" for x in domain.get("can_answer", []))
    cannot = "".join(f"<li>{e(x)}</li>" for x in domain.get("cannot_answer", []))
    scope = (f'<details class="basis"><summary>能回答 / 还不能回答</summary>'
             f'{f"<p class=small>能回答：</p><ul>{can}</ul>" if can else ""}'
             f'{f"<p class=small>还不能可靠回答：</p><ul>{cannot}</ul>" if cannot else ""}</details>'
             if can or cannot else "")
    name = f"<strong>{e(domain['name'])}</strong><div class='small muted'>{e(domain.get('summary', ''))}</div>{scope}"
    if st["category"] == "planned":
        needs = e(domain.get("needs", ""))
        return (f"<tr class='planned'><td>{name}</td><td colspan='3'>{chip('planned', '规划，未开始')} "
                f"<span class='small muted'>{needs}</span></td></tr>")
    data = "".join(
        f"<div>{chip('pass' if d['has_data'] else 'skipped', VERIFY_LABEL.get(d['status'], d['status']))} "
        f"<code class='small'>{e(d['id'])}</code>{'' if d['has_data'] else ' <span class=small>（未取得）</span>'}</div>"
        for d in st["datasets"]) or '<span class="muted">待接入</span>'
    if st["runs"]:
        types = branch_result_types()
        analysis = "".join(
            f"<div>{chip(r['status'], STATUS_LABEL.get(r['status'], r['status']))} <code class='small'>{e(r['study_id'])}</code>"
            f"<div class='small muted'>分支 {e(r['branch'])}：支持 "
            f"{e('、'.join(RESULT_TYPE_LABEL[t.value] for t in types.get(r['branch'], ())))}</div></div>"
            for r in st["runs"])
    else:
        analysis = ('<span class="muted">尚无研究（数据已接入）</span>' if st["category"] == "data_only"
                    else '<span class="muted">尚无研究；数据已登记，本次构建未取得</span>')
    if st["validated"]:
        validation = "".join(
            f"<div>{chip('pass', '用途已验证')} {e(USE_SHORT[u])} · <code class='small'>{e(ds)}</code>"
            f"<div class='small muted'>登记于 {e(rec.date)}；范围：{e(rec.scope)}</div>"
            f"<details class='basis'><summary>核验证据</summary><p class='small'>{e(rec.evidence)}</p></details></div>"
            for ds, u, rec in st["validated"])
        if st["unvalidated"]:
            validation += (f"<div class='small muted'>未登记用途核验："
                           f"{e('、'.join(st['unvalidated']))}（只用于交叉检查或尚未核验）</div>")
    elif st["runs"]:
        ok = all(r["status"] == "success" for r in st["runs"])
        validation = (f"{chip('skipped', '未登记用途核验')}<div class='small muted'>"
                      f"{'每次运行的数据与计算检查通过' if ok else '最近运行有受限结论'}；尚未在来源登记中记录用途核验</div>")
    else:
        validation = '<span class="muted">—</span>'
    return f"<tr><td>{name}</td><td>{data}</td><td>{analysis}</td><td>{validation}</td></tr>"


def _types_table() -> str:
    implemented: dict[str, list[str]] = {t.value: [] for t in ResultType}
    for branch, types in branch_result_types().items():
        for t in types:
            implemented[t.value].append(branch)
    rows = "".join(
        f"<tr><td>{e(RESULT_TYPE_LABEL[t])}</td><td>"
        + (" ".join(f"<code>{e(b)}</code>" for b in branches) if branches else '<span class="muted">尚未实现</span>')
        + "</td></tr>" for t, branches in implemented.items())
    return f'<table class="compact"><thead><tr><th>成果类型</th><th>已实现的研究分支</th></tr></thead><tbody>{rows}</tbody></table>'


def _phases(content: dict[str, Any]) -> str:
    labels = {"done": "完成", "partial": "部分完成", "planned": "未开始"}
    return '<ol class="phases">' + "".join(
        f'<li class="phase phase-{e(p["status"])}"><div class="phase-id">{e(p["id"])}</div>'
        f'<div><div class="phase-name">{e(p["name"])} {chip(p["status"], labels.get(p["status"], p["status"]))}</div>'
        f'<p class="muted">{e(p["summary"])}</p></div></li>' for p in content.get("phases", [])) + "</ol>"


def _modules(content: dict[str, Any]) -> str:
    return '<div class="modules">' + "".join(
        f'<div class="module"><div class="module-id">{e(m["id"])}</div><div class="module-name">{e(m["name"])}</div>'
        f'<div class="muted small">{e(m["role"])}</div><code class="small">{e(m["code"])}</code></div>'
        for m in content.get("modules", [])) + "</div>"


def capability_page(content: dict[str, Any], registry: Registry, datasets: dict[str, dict[str, Any]],
                    latest: dict[str, dict[str, Any]], build: dict[str, Any]) -> str:
    rows = "".join(_domain_row(d, domain_status(d, registry, datasets, latest)) for d in content.get("domains", []))
    body = f"""
<header class="top"><div class="wrap"><h1>研究能力地图</h1>
<p class="tagline">系统现在能研究什么、证据成熟到什么程度、下一步研究什么。</p></div></header>
<main class="wrap">
<section><h2>研究领域</h2>
<p class="muted small">状态由数据登记、来源核验与最新运行自动得出，只有「规划」由人工维护。
<strong>工程完成</strong>（代码可运行、测试与每次运行的检查通过）与<strong>研究验证完成</strong>
（在来源登记中记录了针对该用途的核验）是两回事，分列显示。不使用笼统的完成百分比：研究范围会持续扩大，分母并不固定。</p>
<div class="scroll"><table class="capability"><thead><tr><th>研究领域</th><th>数据能力</th><th>分析能力（工程）</th>
<th>研究验证</th></tr></thead><tbody>{rows}</tbody></table></div></section>
<section><h2>成果类型</h2>
<p class="muted small">描述、解释、预测、模拟的证据要求不同（架构 V0.3 §6.3、§8），各自需要独立的验证方式与展示模板。</p>
{_types_table()}</section>
<section><h2>建设进度</h2>{_phases(content)}</section>
<section><h2>系统结构</h2>{_modules(content)}
<p class="muted small">流程：研究定义 → 资源接入 → 数据与版本 → 公共分析 → 研究分支 → 成果与档案；质量与验证贯穿每一步。
网站只是发布层：复杂计算在本地或 CI 中完成，网页读取结构化结果。</p></section>
</main>"""
    return shell("研究能力地图 · Investment Research OS", body, build, active="map.html")
