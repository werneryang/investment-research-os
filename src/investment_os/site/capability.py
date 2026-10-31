"""Shared research discovery plus data registration and engineering status.

Data groups preserve source links; paired study ownership lives in discovery.py.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..contracts import ResultType, Use
from ..registry import Registry
from ..research import branch_result_types
from .collect import not_fetched_label
from .common import (
    RESULT_TYPE_LABEL,
    RISK_LABEL,
    STATUS_LABEL,
    VERIFY_LABEL,
    chip,
    e,
    shell,
    use_scope_chip,
)
from .i18n import L, Labels, te, tx
from .renderers import use_key

USE_SHORT = Labels({Use.DESCRIPTIVE: ("历史描述", "Historical description"),
                    Use.POINT_IN_TIME: ("时点研究", "Point-in-time study"), Use.SCENARIO: ("情景模拟", "Scenario simulation")})
# 由好到差；分支状态取其方向中最好的一项
CATEGORIES = ("active", "data_only", "registered", "planned")
CATEGORY_LABEL = Labels({"active": ("已有研究", "Has studies"), "data_only": ("已有数据", "Has data"),
                         "registered": ("数据已登记", "Data registered"), "planned": ("规划中", "Planned")})


def category_chip(category: str) -> str:
    return chip("pass" if category == "active" else category, CATEGORY_LABEL[category])


def risk_chips(direction: dict[str, Any]) -> str:
    """风险来源标签；与方向同名的标签（如「通胀」）不重复显示。"""
    labels = (RISK_LABEL.get(r, r) for r in direction.get("risk", []))
    return " ".join(chip("tag", x) for x in labels if x != tx(direction.get("name")))


def framework(content: dict[str, Any], registry: Registry, datasets: dict[str, dict[str, Any]],
              latest: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """研究框架的各分支：每个方向附带状态，分支状态取方向中最好的一项。"""
    out = []
    for branch in content.get("data_groups", []):
        dirs = [(d, direction_status(d, registry, datasets, latest)) for d in branch.get("directions", [])]
        best = min((CATEGORIES.index(st["category"]) for _, st in dirs), default=len(CATEGORIES) - 1)
        out.append({**branch, "category": CATEGORIES[best], "directions": dirs})
    return out


def direction_status(direction: dict[str, Any], registry: Registry, datasets: dict[str, dict[str, Any]],
                     latest: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """一个研究方向的三层状态。"""
    if direction.get("planned"):
        return {"category": "planned"}
    ds_rows = []
    for ds_id in direction.get("datasets", []):
        d = datasets.get(ds_id)
        if d is None:
            continue
        ds_rows.append({"id": ds_id, "status": d["status"], "has_data": d["version_id"] is not None,
                        "skip_reason": d.get("skip_reason"),
                        "uses": d["verified_uses"]})
    studies = [s for s in direction.get("studies", []) if s in latest]
    runs = [{"study_id": s, "status": latest[s]["manifest"]["status"],
             "branch": latest[s]["result"]["branch"], "use": _use(latest[s]["result"])} for s in studies]
    validated: dict[tuple[str, Use], Any] = {}
    coverage: dict[tuple[str, Use], list[tuple[str, dict[str, Any]]]] = {}
    for run in runs:
        scope = latest[run["study_id"]]["result"]["scope"]
        for ds in direction.get("datasets", []):
            spec = registry.datasets.get(ds)
            source = registry.sources[spec.source_id] if spec else None
            record = source.use_record(ds, run["use"]) if source else None
            if record is None:
                continue
            validated[(ds, run["use"])] = record
            # 用当前登记与该研究最新运行的期间计算，地图反映的是现在的核验范围
            cov = source.use_coverage(ds, run["use"], date.fromisoformat(str(scope["start"])),
                                      date.fromisoformat(str(scope["end"])))
            coverage.setdefault((ds, run["use"]), []).append((run["study_id"], cov.to_dict()))
    used = {r["use"] for r in runs}
    unvalidated = [d for d in direction.get("datasets", [])
                   if d in datasets and not any((d, u) in validated for u in used)]
    if runs:
        category = "active"
    elif any(r["has_data"] for r in ds_rows):
        category = "data_only"
    else:
        category = "registered" if ds_rows else "planned"  # 已登记数据集但本次构建未取得，不是「规划」
    return {"category": category, "datasets": ds_rows, "runs": runs,
            "validated": [(ds, u, rec, coverage[(ds, u)])
                          for (ds, u), rec in sorted(validated.items(), key=lambda kv: kv[0])],
            "unvalidated": unvalidated if runs else []}


def _use(result: dict[str, Any]) -> Use:
    return Use(use_key(result))


def summary(content: dict[str, Any], registry: Registry, datasets: dict[str, dict[str, Any]],
            latest: dict[str, dict[str, Any]]) -> dict[str, int]:
    """各状态的研究方向数。"""
    out = dict.fromkeys(CATEGORIES, 0)
    for branch in framework(content, registry, datasets, latest):
        for _, st in branch["directions"]:
            out[st["category"]] += 1
    return out


def _direction_row(direction: dict[str, Any], st: dict[str, Any]) -> str:
    can = "".join(f"<li>{te(x)}</li>" for x in direction.get("can_answer", []))
    cannot = "".join(f"<li>{te(x)}</li>" for x in direction.get("cannot_answer", []))
    scope = (f'<details class="basis"><summary>{L("能回答 / 还不能回答", "Can answer / cannot yet answer")}</summary>'
             + (f'<p class=small>{L("能回答：", "Can answer:")}</p><ul>{can}</ul>' if can else "")
             + (f'<p class=small>{L("还不能可靠回答：", "Cannot yet answer reliably:")}</p><ul>{cannot}</ul>' if cannot else "")
             + "</details>" if can or cannot else "")
    tags = risk_chips(direction)
    name = (f"<strong>{te(direction['name'])}</strong> {tags}"
            f"<div class='small muted'>{te(direction.get('summary', ''))}</div>{scope}")
    if st["category"] == "planned":
        return (f"<tr class='planned'><td>{name}</td><td>"
                f"{chip('planned', L('规划，未开始', 'Planned, not started'))} "
                f"<span class='small muted'>{te(direction.get('needs', ''))}</span></td></tr>")
    data = "".join(
        f"<div>{chip('pass' if d['has_data'] else 'skipped', VERIFY_LABEL.get(d['status'], d['status']))} "
        f"<code class='small'>{e(d['id'])}</code>"
        f"{'' if d['has_data'] else ' <span class=small>' + L('（', '(') + not_fetched_label(d.get('skip_reason'), short=True) + L('）', ')') + '</span>'}</div>"
        for d in st["datasets"]) or f'<span class="muted">{L("待接入", "Not connected yet")}</span>'
    return f"<tr><td>{name}</td><td>{data}</td></tr>"


def _validated_entry(ds: str, use: Use, rec: Any, coverage: list[tuple[str, dict[str, Any]]]) -> str:
    statuses = {c["status"] for _, c in coverage}
    if statuses == {"in_scope"}:
        head = chip("pass", L("用途已验证", "Use verified"))
    elif "in_scope" in statuses or "partial" in statuses:
        head = chip("partial", L("用途已验证 · 部分在范围内", "Use verified · partly within scope"))
    else:
        head = chip("fail", L("研究期间在核验范围外", "Study period outside verified scope"))
    any_ = L("不限", "open")
    valid = f"{rec.valid_from or any_}{L(' 至 ', ' to ')}{rec.valid_through or any_}"
    per_study = "".join(f"<div class='small'><code>{e(s)}</code> {use_scope_chip(c)}</div>" for s, c in coverage)
    return (f"<div>{head} {e(USE_SHORT[use])} · <code class='small'>{e(ds)}</code>"
            f"<div class='small muted'>{L('核验覆盖的观测日期 ', 'Observation dates covered: ')}{e(valid)}"
            f"{L('；登记于 ', '; registered ')}{e(rec.date)}</div>{per_study}"
            f"<details class='basis'><summary>{L('范围说明与核验证据', 'Scope and verification evidence')}</summary>"
            f"<p class='small'>{te(rec.scope)}</p><p class='small'>{te(rec.evidence)}</p></details></div>")


def _types_table() -> str:
    implemented: dict[str, list[str]] = {t.value: [] for t in ResultType}
    for branch, types in branch_result_types().items():
        for t in types:
            implemented[t.value].append(branch)
    rows = "".join(
        f"<tr><td>{e(RESULT_TYPE_LABEL[t])}</td><td>"
        + (" ".join(f"<code>{e(b)}</code>" for b in branches) if branches
           else f'<span class="muted">{L("尚未实现", "Not implemented yet")}</span>')
        + "</td></tr>" for t, branches in implemented.items())
    head = L("<th>成果类型</th><th>已实现的研究分支</th>", "<th>Result type</th><th>Implemented in branches</th>")
    return f'<table class="compact"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>'


def _phases(content: dict[str, Any]) -> str:
    labels = Labels({"done": ("完成", "Done"), "partial": ("部分完成", "Partly done"), "planned": ("未开始", "Not started")})
    return '<ol class="phases">' + "".join(
        f'<li class="phase phase-{e(p["status"])}"><div class="phase-id">{e(p["id"])}</div>'
        f'<div><div class="phase-name">{te(p["name"])} {chip(p["status"], labels.get(p["status"], p["status"]))}</div>'
        f'<p class="muted">{te(p["summary"])}</p></div></li>' for p in content.get("phases", [])) + "</ol>"


def _modules(content: dict[str, Any]) -> str:
    return '<div class="modules">' + "".join(
        f'<div class="module"><div class="module-id">{e(m["id"])}</div><div class="module-name">{te(m["name"])}</div>'
        f'<div class="muted small">{te(m["role"])}</div><code class="small">{e(m["code"])}</code></div>'
        for m in content.get("modules", [])) + "</div>"


def _branch_rows(branch: dict[str, Any]) -> str:
    head = (f"<tr class='branch' id='{e(branch['id'])}'><th colspan='2'>{te(branch['name'])} "
            f"{category_chip(branch['category'])}<div class='small muted'>{te(branch.get('question', ''))}</div></th></tr>")
    return head + "".join(_direction_row(d, st) for d, st in branch["directions"])


def capability_page(content: dict[str, Any], registry: Registry, datasets: dict[str, dict[str, Any]],
                    latest: dict[str, dict[str, Any]], build: dict[str, Any], discovery_model=None) -> str:
    from .discovery import browser
    discovery_html = browser(content, discovery_model, latest, build, {k: v["frequency"] for k,v in datasets.items()}) if discovery_model else ""
    rows = "".join(_branch_rows(b) for b in framework(content, registry, datasets, latest))
    head = L("<th>数据用途分组</th><th>数据接入状态</th>",
             "<th>Data use group</th><th>Data access status</th>")
    body = f"""
<header class="top"><div class="wrap"><h1>{L("研究能力地图", "Research capability map")}</h1>
<p class="tagline">{L("系统现在能研究什么、证据成熟到什么程度、下一步研究什么。",
                      "What the system can study now, how mature the evidence is, and what comes next.")}</p></div></header>
<main class="wrap">
{discovery_html}
<details><summary>{L("数据接入登记与工程状态", "Data registration and engineering status")}</summary><section><h2>{L("数据来源分组", "Data source groups")}</h2>
<p class="muted small">{L("以下分组用于来源与数据接入，不是研究归属。数据取得、工程实现和研究用途核验分别判断。", "These groups describe sources and data access, not study ownership. Data access, engineering and verification for a research use are assessed separately.")}</p>
<div class="scroll"><table class="capability"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div></section></details>
<section><h2>{L("成果类型", "Result types")}</h2>
<p class="muted small">{L("描述、解释、预测、模拟的证据要求不同（架构 V0.3 §6.3、§8），各自需要独立的验证方式与展示模板。",
                          "Description, explanation, forecasts and simulations need different evidence (architecture "
                          "V0.3 §6.3, §8), each with its own validation method and display template.")}</p>
{_types_table()}</section>
<section><h2>{L("建设进度", "Build progress")}</h2>{_phases(content)}</section>
<section><h2>{L("系统结构", "System structure")}</h2>{_modules(content)}
<p class="muted small">{L("""流程：研究定义 → 资源接入 → 数据与版本 → 公共分析 → 研究分支 → 成果与档案；质量与验证贯穿每一步。
网站只是发布层：复杂计算在本地或 CI 中完成，网页读取结构化结果。""",
"""Flow: study definition → data access → data and versions → shared analytics → research branches → results and
archive, with quality and validation at every step. The website is only the publishing layer: heavy computation runs
locally or in CI, and pages read structured results.""")}</p></section>
</main>"""
    return shell(L("研究能力地图", "Capability map") + " · Investment Research OS", body, build, page="map.html",
                 active="map.html")
