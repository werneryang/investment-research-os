"""首页（研究总览）：研究焦点 → 六个研究分支的总览 → 按框架顺序的研究目录。

选什么、归在哪里、提示什么由 catalog.py 决定，这里把它排成页面。目录中每项研究只在主方向出现一次，
其他方向给出「另见」；同类研究收成集合；尚无研究的方向合并为一行，详情在能力地图。
指标卡片、图表、完整发现与证据留在研究页。"""

from __future__ import annotations

from typing import Any

from .capability import category_chip, risk_chips
from .catalog import Catalog, CollectionView, Notice, StudyView, featured
from .common import STATUS_LABEL, chip, e, shell
from .i18n import L, te
from .renderers import get_renderer

# 首页说明各项研究共同的形成过程；对应架构 §3 的模块，详情在能力地图
PROCESS = (("研究问题", "Research question"), ("数据与版本", "Data and versions"), ("分析方法", "Method"),
           ("成果", "Result"), ("验证与历史", "Verification and history"))


def _coverage(b: dict[str, Any]) -> str:
    """分支的具体覆盖：多少方向已有研究或数据，哪些仍在规划。不用一个状态概括整个分支。"""
    cats = [st["category"] for _, st in b["directions"]]
    total, active, data, registered = len(cats), cats.count("active"), cats.count("data_only"), cats.count("registered")
    if not active and not data and not registered:
        return L("规划中", "Planned")
    parts = [L(f"{active} 个已有研究", f"{active} with studies")] if active else []
    if data:
        parts.append(L(f"{data} 个只有数据", f"{data} with data only"))
    if registered:  # 数据集已登记，但本次构建没有取得数据
        parts.append(L(f"{registered} 个数据已登记、未取得", f"{registered} with data registered, not fetched"))
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


# ---- 研究条目 -----------------------------------------------------------------------

def _alerts(notices: list[Notice], brief: bool = False) -> str:
    """检查失败与影响结论的缺口：与发现一起显示；精选卡片用短句，细节在目录与研究页。"""
    out = ""
    for level, cls in (("fail", "bad"), ("warn", "warn")):
        texts = [n.brief if brief else n.text for n in notices if n.level == level]
        if texts:
            out += f'<p class="small {cls}">{L("注意：", "Note: ")}{e(L("；", "; ").join(texts))}</p>'
    return out


def _meta(v: StudyView, brief: bool = False) -> str:
    """数据截止、检查状态与提示性信息（尾端核验、研究边界），低视觉权重。"""
    parts = [L("数据截止 ", "Data cutoff ") + v.cutoff]
    if not brief:
        parts.append(v.checks)
    parts += [n.brief if brief else n.text for n in v.notices if n.level == "info"]
    return f'<p class="small muted">{e(" · ".join(parts))}</p>'


def _use(note: str) -> str:
    return f'<p class="small muted">{L("用途：", "Use: ")}{e(note)}</p>'


def _study_row(v: StudyView, show_use: bool) -> str:
    return (f'<li class="study-row"><div><p class="eyebrow">{e(v.eyebrow)}</p>'
            f'<a class="study-title" href="studies/{e(v.id)}/">{v.title}</a>'
            f'<p class="small">{v.finding}</p>{_use(v.use_note) if show_use else ""}{_alerts(v.notices)}{_meta(v)}</div>'
            f'<div>{chip(v.status, STATUS_LABEL.get(v.status, ""))}</div></li>')


def _member_alerts(v: StudyView) -> str:
    """集合表格中成员的检查失败与限制；没有时为 —。"""
    return _alerts(v.notices, brief=True) or "—"


def _collection_table(c: CollectionView) -> str:
    lead = get_renderer(c.members[0][1]["branch"]) if c.members else None
    if lead and lead.summary_row:
        heads = [L("研究", "Study"), *lead.summary_columns, L("状态", "Status"), L("提示", "Notes")]
        rows = [[f'<a href="studies/{e(v.id)}/">{v.title}</a>', *lead.summary_row(r),
                 chip(v.status, STATUS_LABEL.get(v.status, "")), _member_alerts(v)] for v, r in c.members]
    else:
        heads = [L("研究", "Study"), L("数据截止", "Data cutoff"), L("主要发现", "Main finding"), L("提示", "Notes")]
        rows = [[f'<a href="studies/{e(v.id)}/">{v.title}</a>', e(v.cutoff), v.finding, _member_alerts(v)]
                for v, _ in c.members]
    body = "".join("<tr>" + "".join(f"<td>{x}</td>" for x in row) + "</tr>" for row in rows)
    return (f'<details class="collection"><summary>{L(f"逐项查看（{len(rows)}）", f"View each ({len(rows)})")}</summary>'
            f'<div class="scroll"><table><thead><tr>{"".join(f"<th>{e(h)}</th>" for h in heads)}</tr></thead>'
            f'<tbody>{body}</tbody></table></div></details>')


def _collection_row(c: CollectionView, show_use: bool) -> str:
    v, members = c.lead, [m for m, _ in c.members]
    cutoffs = sorted(m.cutoff for m in members) or [v.cutoff]
    span = cutoffs[0] if cutoffs[0] == cutoffs[-1] else f"{cutoffs[0]}{L(' 至 ', ' to ')}{cutoffs[-1]}"
    meta = " · ".join([L(f"成员数据截止 {span}", f"Member data cutoffs {span}"), v.checks]
                      + [n.text for n in v.notices if n.level == "info"])
    return (f'<li class="study-row"><div><p class="eyebrow">{L("研究集合", "Collection")} · '
            f'{L(f"{len(members)} 项研究", f"{len(members)} studies")}</p>'
            f'<a class="study-title" href="studies/{e(v.id)}/">{te(c.name)}</a>'
            f'<p class="small">{v.finding}</p>{_use(v.use_note) if show_use else ""}{_alerts(c.notices)}'
            f'<p class="small muted">{e(meta)}</p>{_collection_table(c) if c.members else ""}</div>'
            f'<div>{chip(v.status, STATUS_LABEL.get(v.status, ""))}</div></li>')


# ---- 目录 ---------------------------------------------------------------------------

def _rows(d: dict[str, Any], cat: Catalog) -> str:
    """方向的条目；各条目用途相同时在方向下只说一次。"""
    items, elsewhere = cat.entries(d)
    uses = {x.lead.use_note if isinstance(x, CollectionView) else x.use_note for x in items}
    per_row = len(uses) > 1
    html = _use(uses.pop()) if len(uses) == 1 else ""
    if items:
        html += '<ul class="study-list">' + "".join(
            _collection_row(x, per_row) if isinstance(x, CollectionView) else _study_row(x, per_row)
            for x in items) + "</ul>"
    if elsewhere:
        links = L("；", "; ").join(
            f'<a href="studies/{e(s)}/">{cat.views[s].title}</a>'
            + L(f"（列于「{te(cat.where[cat.primary[s]][1])}」）", f" (listed under {te(cat.where[cat.primary[s]][1])})")
            for s in elsewhere)
        html += f'<p class="small muted see-also">{L("另见：", "See also: ")}{links}</p>'
    return html


def _direction(d: dict[str, Any], st: dict[str, Any], cat: Catalog) -> str:
    return (f'<div class="direction"><h4>{te(d["name"])} {risk_chips(d)} {category_chip(st["category"])}</h4>'
            f'<p class="small muted">{te(d.get("summary", ""))}</p>{_rows(d, cat)}</div>')


def _branch_card(b: dict[str, Any], cat: Catalog) -> str:
    with_runs = [(d, st) for d, st in b["directions"] if st["category"] == "active"]

    def names(category: str) -> str:
        return L("、", ", ").join(te(d["name"]) for d, st in b["directions"] if st["category"] == category)

    counts = {c: sum(st["category"] == c for _, st in b["directions"]) for c in ("data_only", "registered")}
    planned = _planned_names(b)
    scope = e(_coverage(b)) + (L("；规划中：", "; planned: ") + " · ".join(planned) if planned else "")
    lines = []
    if counts["data_only"]:
        n = counts["data_only"]
        lines.append(L(f"{n} 个方向已有数据、尚无研究：{names('data_only')}。",
                       f"{n} direction(s) with data but no studies yet: {names('data_only')}. "))
    if counts["registered"]:  # 数据集已登记，本次构建没有取得数据
        n = counts["registered"]
        lines.append(L(f"{n} 个方向的数据已登记、本次构建未取得：{names('registered')}。",
                       f"{n} direction(s) with data registered but not fetched in this build: {names('registered')}. "))
    more = (f'<p class="small muted direction-more">{"".join(lines)}'
            f'<a href="map.html#{e(b["id"])}">{L("能回答什么、还缺什么 →", "What they can answer and what is missing →")}</a></p>'
            if lines else "")
    return f"""
<article class="card branch-card" id="{e(b['id'])}">
  <header><p class="eyebrow">{L("研究分支", "Research branch")}</p><h3>{te(b['name'])}</h3>
    <p class="muted">{te(b.get('question', ''))}</p><p class="small tile-status">{scope}</p></header>
  {"".join(_direction(d, st, cat) for d, st in with_runs)}
  {more}
</article>"""


def _featured(picks: list[StudyView], cat: Catalog) -> str:
    cards = []
    for v in picks:
        branch, direction = cat.where.get(cat.primary.get(v.id, ""), ("", ""))
        where = f"{te(branch)} · {te(direction)}" if branch else e(v.eyebrow)
        cards.append(f'<li class="card featured"><p class="eyebrow">{where}</p>'
                     f'<a class="study-title" href="studies/{e(v.id)}/">{v.title}</a>'
                     f'<p>{v.finding}</p>{_alerts(v.notices, brief=True)}{_meta(v, brief=True)}</li>')
    return f'<ol class="featured-grid">{"".join(cards)}</ol>'


def home_page(studies: list[str], latest: dict[str, dict[str, Any]], content: dict[str, Any],
              build: dict[str, Any], branches: list[dict[str, Any]], frequency: dict[str, str] | None = None) -> str:
    """frequency：数据集 id → 频率，用于判断用途核验的尾端滞后是否在维护周期内。"""
    cat = Catalog(branches, latest, content, studies, frequency)
    # 目录遵循研究框架的分支顺序，与顶部总览一致；规划中的分支只在总览出现
    cards = "".join(_branch_card(b, cat) for b in branches if b["category"] != "planned")
    unplaced = [s for s in studies if s not in cat.primary]
    unplaced_html = (f'<h3>{L("未归入研究方向的研究", "Studies not placed in a research direction")}</h3>'
                     f'<p class="muted small">{L("在 site/content.yaml 的研究框架中登记所属方向。", "Register their direction in the research framework in site/content.yaml.")}</p>'
                     f'<ul class="study-list">{"".join(_study_row(cat.views[s], True) for s in unplaced)}</ul>'
                     if unplaced else "")
    picks = featured(content, cat.views, studies)
    in_collections = cat.grouped()
    count = (L(f"共 {len(studies)} 项研究", f"{len(studies)} studies in all")
             + (L(f"，其中 {in_collections} 项收在研究集合中", f", {in_collections} of them grouped in collections")
                if in_collections else "")
             + L("；每项研究只在主方向列出一次。", "; each study is listed once, under its main direction."))
    process = " → ".join(f"<span>{e(L(*x))}</span>" for x in PROCESS)
    body = f"""
<header class="hero"><div class="wrap">
  <h1>{e(content.get('title'))}</h1>
  <p class="tagline">{te(content.get('tagline'))}</p>
  <p class="meta">{L("公开免费数据 · 可追溯的版本 · 历史结果可复现 · 只描述数据能证明的内容",
                     "Free public data · traceable versions · reproducible results · describes only what the data can show")}</p>
</div></header>
<main class="wrap">
  {f'<section><h2>{L("研究焦点", "Featured studies")}</h2>{_featured(picks, cat)}</section>' if picks else ''}
  <section><h2>{L("研究框架", "Research framework")}</h2>
    <p class="muted">{L(f"研究按 {len(branches)} 个研究分支组织，每个分支下分为研究方向。规划中的分支说明还缺什么，见能力地图。",
                        f"Research is organized into {len(branches)} research branches, each split into research "
                        "directions. For what the planned branches still need, see the capability map.")}</p>
    {_overview(branches)}
    <p class="process small"><strong>{L("每项研究的形成：", "How each study is made: ")}</strong>{process}
    <a href="map.html">{L("工程模块与建设进度 →", "Engineering modules and build progress →")}</a></p>
  </section>
  <section><h2>{L("研究目录", "Study catalog")}</h2>
    {f'<p class="muted small">{count}</p>' if latest else f'<p class="muted">{L("暂无研究运行记录。", "No study runs yet.")}</p>'}
    {cards}{unplaced_html}
  </section>
  <section class="about-strip">
    <div><h3>{L("这些发现有多可靠？", "How reliable are these findings?")}</h3><p class="muted small">{L(
        "每项研究都有证据面板：数据来源与版本、覆盖、核验、复现与限制，不汇总成一个笼统的可信度分数。首页只提示检查失败与影响结论的缺口。",
        "Every study has an evidence panel: data sources and versions, coverage, verification, reproduction and "
        "limitations, without collapsing them into a single confidence score. The home page flags only failed checks "
        "and gaps that affect conclusions.")}</p>
    <a href="methods.html">{L("数据、方法与状态 →", "Data, methods & status →")}</a></div>
    <div><h3>{L("每个方向能回答什么？", "What can each direction answer?")}</h3><p class="muted small">{L(
        "各研究方向能回答与还不能回答的问题、数据与用途核验状态、规划中的方向还缺什么，以及建设进度。",
        "The questions each direction can and cannot yet answer, its data and use-verification status, what planned "
        "directions still need, and build progress.")}</p>
    <a href="map.html">{L("研究能力地图 →", "Capability map →")}</a></div>
  </section>
</main>"""
    return shell(content.get("title", ""), body, build, page="index.html", active="index.html")
