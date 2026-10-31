"""首页（研究总览）：先用六个研究分支的总览建立整体印象，再列出已有研究或数据的分支。

每项研究只显示一句主要发现、数据日期、用途与需要注意的例外，并链接到研究页；
指标卡片、图表、完整发现与证据留在研究页，工程模块留在能力地图。"""

from __future__ import annotations

from typing import Any

from .capability import CATEGORIES, category_chip, risk_chips
from .common import RESULT_TYPE_LABEL, STATUS_LABEL, chip, e, shell, span_text
from .i18n import L, te
from .renderers import get_renderer
from .study import localized_findings

# 首页说明各项研究共同的形成过程；对应架构 §3 的模块，详情在能力地图
PROCESS = (("研究问题", "Research question"), ("数据与版本", "Data and versions"), ("分析方法", "Method"),
           ("成果", "Result"), ("验证与历史", "Verification and history"))


def _coverage(b: dict[str, Any]) -> str:
    """分支的具体覆盖：多少方向已有研究或数据，哪些仍在规划。不用一个状态概括整个分支。"""
    cats = [st["category"] for _, st in b["directions"]]
    total, active = len(cats), cats.count("active")
    data = cats.count("data_only") + cats.count("registered")
    if not active and not data:
        return L("规划中", "Planned")
    parts = [L(f"{active} 个已有研究", f"{active} with studies")] if active else []
    if data:
        parts.append(L(f"{data} 个只有数据", f"{data} with data only"))
    return L(f"{total} 个方向：{'，'.join(parts)}", f"{total} directions: {', '.join(parts)}")


def _planned_names(b: dict[str, Any]) -> list[str]:
    return [te(d["name"]) for d, st in b["directions"] if st["category"] == "planned"]


def _overview(branches: list[dict[str, Any]]) -> str:
    tiles = []
    for b in branches:
        planned = b["category"] == "planned"
        href = f"map.html#{e(b['id'])}" if planned else f"#{e(b['id'])}"
        tiles.append(f'<li class="branch-tile{" planned" if planned else ""}"><a href="{href}">{te(b["name"])}</a>'
                     f'<p class="small muted">{te(b.get("question", ""))}</p>'
                     f'<p class="small tile-status">{e(_coverage(b))}</p></li>')
    return f'<ol class="branch-grid">{"".join(tiles)}</ol>'


# 首页点名的检查；其余研究专属检查只计数，名称与细节见研究页证据面板
CHECK_NAMES = {"raw_spot_check": ("原始快照抽查", "raw snapshot spot check"),
               "cross_check": ("同源检查", "same-source check"),
               "reproduce": ("固定输入重算", "pinned-input recomputation")}


def _checks(item: dict[str, Any]) -> dict[str, list[str]]:
    """各项检查按通过、未通过、部分、未执行归类。跳过、状态不明或没有记录的检查算未执行，不算通过。"""
    ver, out = item["verification"], {"pass": [], "fail": [], "partial": [], "skipped": []}
    for key, v in item["result"]["validation"].items():
        if isinstance(v, dict) and "status" in v:
            out[v["status"] if v["status"] in ("pass", "fail") else "skipped"].append(key)
    if not ver:
        out["skipped"].append("reproduce")
    elif not ver["reproduced"]:
        out["fail"].append("reproduce")
    else:
        out["partial" if ver.get("scope") == "partial" else "pass"].append("reproduce")
    return out


def _check_names(keys: list[str]) -> str:
    named = [L(*CHECK_NAMES[k]) for k in keys if k in CHECK_NAMES]
    rest = len(keys) - len(named)
    if rest:
        named.append(L(f"另 {rest} 项检查", f"{rest} other check(s)") if named else L(f"{rest} 项检查", f"{rest} check(s)"))
    return L("、", ", ").join(named)


def _check_note(item: dict[str, Any]) -> str:
    """检查状态的客观陈述：只说已执行的检查通过，同时写明部分执行与未执行的检查。"""
    c = _checks(item)
    parts = [L(f"已执行的 {len(c['pass'])} 项检查通过", f"{len(c['pass'])} executed check(s) passed")
             if c["pass"] else L("暂无通过的检查", "No checks passed yet")]
    if c["partial"]:
        parts.append(L("部分执行：", "partly run: ") + _check_names(c["partial"]))
    if c["skipped"]:
        parts.append(L("未执行：", "not run: ") + _check_names(c["skipped"]))
    return L("；", "; ").join(parts)


def _caveats(item: dict[str, Any]) -> list[str]:
    """需要注意的例外；全部正常时首页不展开证据细节。"""
    r = item["result"]
    out = []
    failed = _checks(item)["fail"]
    if "raw_spot_check" in failed:
        out.append(L("原始快照抽查有不一致", "raw snapshot spot check found mismatches"))
    if "cross_check" in failed:
        out.append(L("同源检查有差异", "same-source check found differences"))
    other = [k for k in failed if k not in CHECK_NAMES]
    if other:
        out.append(L(f"{len(other)} 项数据检查未通过", f"{len(other)} data check(s) failed"))
    if "reproduce" in failed:
        out.append(L("固定输入重算不一致", "pinned-input recomputation differs"))
    for inp in item["manifest"].get("inputs", []):
        status = (inp.get("use_scope") or {}).get("status")
        ds = inp["dataset_id"]
        if status == "partial":
            spans = span_text(inp["use_scope"].get("uncovered", []))
            out.append(L(f"用途核验部分在范围内（{ds} 范围外：{spans}）",
                         f"use verification only partly covers the period ({ds} outside scope: {spans})"))
        elif status == "out_of_scope":
            out.append(L(f"研究期间在 {ds} 的用途核验范围外", f"study period is outside the use verification of {ds}"))
    if r.get("unsupported"):
        n = len(r["unsupported"])
        out.append(L(f"{n} 项结论因数据不足不输出", f"{n} conclusion(s) withheld for lack of data"))
    return out


def _study_row(study_id: str, item: dict[str, Any], meta: dict[str, Any], focus: bool) -> str:
    m, r = item["manifest"], item["result"]
    findings = localized_findings(item)
    if findings:
        f = findings[0]
        first = e(f["text"]) if f.get("translated", True) else f'<span lang="zh-CN">{e(f["text"])}</span>'
    else:
        first = e(L("暂无规则化发现", "No rule-based findings yet"))
    kind = RESULT_TYPE_LABEL.get(r["result_type"], r["result_type"])
    label = (L("研究焦点 · ", "Focus · ") if focus else "") + f'{te(meta.get("label", L("研究", "Study")))} · {e(kind)}'
    caveats = _caveats(item)
    # 没有警告不等于检查通过：检查状态单独陈述，未执行的检查不能显示成通过
    note = ((f'<p class="small warn">{L("注意：", "Note: ")}{e(L("；", "; ").join(caveats))}</p>' if caveats else "")
            + f'<p class="small muted">{e(_check_note(item))}</p>')
    return (f'<li class="study-row{" focus" if focus else ""}"><div><p class="eyebrow">{label}</p>'
            f'<a class="study-title" href="studies/{e(study_id)}/">{te(r["title"])}</a>'
            f'<p class="small">{first}</p>'
            f'<p class="small muted">{L("用途：", "Use: ")}{e(get_renderer(r["branch"]).use_note)}</p>{note}</div>'
            f'<div class="small muted nowrap">{L("数据截止 ", "Data cutoff ")}{e(r["data_cutoff"])}<br>'
            f'{chip(m["status"], STATUS_LABEL.get(m["status"], ""))}</div></li>')


def _studies(ids: list[str], latest: dict[str, dict[str, Any]], metas: dict[str, Any], focus: str | None) -> str:
    return "".join(_study_row(s, latest[s], metas.get(s, {}), s == focus) for s in ids)


def _shared_data(dirs: list[tuple[dict[str, Any], dict[str, Any]]]) -> str:
    """同一分支内有研究的方向共用的数据集；只展示登记中已经明确的关系。"""
    users: dict[str, list[str]] = {}
    for d, st in dirs:
        if st.get("runs"):
            for ds in d.get("datasets", []):
                users.setdefault(ds, []).append(d["name"])
    shared = [(ds, names) for ds, names in users.items() if len(names) > 1]
    return "".join(
        '<p class="small muted">' + L(f'共享数据：<code>{e(ds)}</code> 同时支撑「{"」「".join(te(n) for n in names)}」，各自回答不同问题。',
                                      f'Shared data: <code>{e(ds)}</code> supports {" and ".join(te(n) for n in names)}, '
                                      'each answering a different question.') + "</p>" for ds, names in shared)


def _direction(d: dict[str, Any], st: dict[str, Any], ordered: list[str], latest: dict[str, dict[str, Any]],
               metas: dict[str, Any], focus: str | None) -> str:
    ids = sorted((s for s in d.get("studies", []) if s in latest), key=ordered.index)
    if ids:
        inner = f'<ul class="study-list">{_studies(ids, latest, metas, focus)}</ul>'
    else:
        have = [x["id"] for x in st["datasets"] if x["has_data"]]
        gap = d.get("cannot_answer", [])
        codes = L("、", ", ").join(f"<code>{e(x)}</code>" for x in have)
        data = (L("已接入 ", "Connected: ") + codes if have
                else L("数据已登记，本次构建未取得", "Data registered but not fetched in this build"))
        inner = (f'<p class="small muted">{data}{L("；尚无研究。", "; no studies yet. ")}'
                 f'{L("还不能回答：", "Cannot yet answer: ") + te(gap[0]) if gap else ""}</p>')
    return (f'<div class="direction"><h4>{te(d["name"])} {risk_chips(d)} {category_chip(st["category"])}</h4>'
            f'<p class="small muted">{te(d.get("summary", ""))}</p>{inner}</div>')


def _branch_card(b: dict[str, Any], ordered: list[str], latest: dict[str, dict[str, Any]],
                 metas: dict[str, Any], focus: str | None) -> str:
    shown = [(d, st) for d, st in b["directions"] if st["category"] != "planned"]
    planned = _planned_names(b)
    scope = e(_coverage(b)) + (L("；规划中：", "; planned: ") + " · ".join(planned) if planned else "")
    return f"""
<article class="card branch-card" id="{e(b['id'])}">
  <header><p class="eyebrow">{L("研究分支", "Research branch")}</p><h3>{te(b['name'])}</h3>
    <p class="muted">{te(b.get('question', ''))}</p><p class="small tile-status">{scope}</p></header>
  {"".join(_direction(d, st, ordered, latest, metas, focus) for d, st in shown)}
  {_shared_data(b['directions'])}
</article>"""


def home_page(studies: list[str], latest: dict[str, dict[str, Any]], content: dict[str, Any],
              build: dict[str, Any], branches: list[dict[str, Any]]) -> str:
    metas = content.get("studies", {})
    focus = studies[0] if studies else None
    # 有研究的分支在前；同类保持 content.yaml 的顺序
    open_ = sorted((b for b in branches if b["category"] != "planned"), key=lambda b: CATEGORIES.index(b["category"]))
    cards = "".join(_branch_card(b, studies, latest, metas, focus) for b in open_)
    placed = {s for b in branches for d, _ in b["directions"] for s in d.get("studies", [])}
    unplaced = [s for s in studies if s not in placed]
    unplaced_html = (f'<h3>{L("未归入研究方向的研究", "Studies not placed in a research direction")}</h3>'
                     f'<p class="muted small">{L("在 site/content.yaml 的研究框架中登记所属方向。", "Register their direction in the research framework in site/content.yaml.")}</p>'
                     f'<ul class="study-list">{_studies(unplaced, latest, metas, focus)}</ul>' if unplaced else "")
    process = " → ".join(f"<span>{e(L(*x))}</span>" for x in PROCESS)
    body = f"""
<header class="hero"><div class="wrap">
  <h1>{e(content.get('title'))}</h1>
  <p class="tagline">{te(content.get('tagline'))}</p>
  <p class="meta">{L("公开免费数据 · 可追溯的版本 · 历史结果可复现 · 只描述数据能证明的内容",
                     "Free public data · traceable versions · reproducible results · describes only what the data can show")}</p>
</div></header>
<main class="wrap">
  <section><h2>{L("研究框架", "Research framework")}</h2>
    <p class="muted">{L(f"研究按 {len(branches)} 个研究分支组织，每个分支下分为研究方向。规划中的分支说明还缺什么，见能力地图。",
                        f"Research is organized into {len(branches)} research branches, each split into research "
                        "directions. For what the planned branches still need, see the capability map.")}</p>
    {_overview(branches)}
    <p class="process small"><strong>{L("每项研究的形成：", "How each study is made: ")}</strong>{process}
    <a href="map.html">{L("工程模块与建设进度 →", "Engineering modules and build progress →")}</a></p>
  </section>
  <section><h2>{L("已有研究与数据", "Studies and data so far")}</h2>
    {'' if latest else f'<p class="muted">{L("暂无研究运行记录。", "No study runs yet.")}</p>'}
    {cards}{unplaced_html}
  </section>
  <section class="about-strip">
    <div><h3>{L("这些发现有多可靠？", "How reliable are these findings?")}</h3><p class="muted small">{L(
        "每项研究都有证据面板：数据来源与版本、覆盖、核验、复现与限制，不汇总成一个笼统的可信度分数。",
        "Every study has an evidence panel: data sources and versions, coverage, verification, reproduction and "
        "limitations, without collapsing them into a single confidence score.")}</p>
    <a href="methods.html">{L("数据、方法与状态 →", "Data, methods & status →")}</a></div>
    <div><h3>{L("每个方向能回答什么？", "What can each direction answer?")}</h3><p class="muted small">{L(
        "各研究方向能回答与还不能回答的问题、数据与用途核验状态、规划中的方向还缺什么，以及建设进度。",
        "The questions each direction can and cannot yet answer, its data and use-verification status, what planned "
        "directions still need, and build progress.")}</p>
    <a href="map.html">{L("研究能力地图 →", "Capability map →")}</a></div>
  </section>
</main>"""
    return shell(content.get("title", ""), body, build, page="index.html", active="index.html")
