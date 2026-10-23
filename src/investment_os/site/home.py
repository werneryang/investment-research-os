"""首页（研究总览）：先用六个研究分支的总览建立整体印象，再列出已有研究或数据的分支。

每项研究只显示一句主要发现、数据日期、用途与需要注意的例外，并链接到研究页；
指标卡片、图表、完整发现与证据留在研究页，工程模块留在能力地图。"""

from __future__ import annotations

from typing import Any

from .capability import CATEGORIES, category_chip, risk_chips
from .common import RESULT_TYPE_LABEL, STATUS_LABEL, chip, e, shell
from .renderers import get_renderer

# 首页说明各项研究共同的形成过程；对应架构 §3 的模块，详情在能力地图
PROCESS = ("研究问题", "数据与版本", "分析方法", "成果", "验证与历史")


def _coverage(b: dict[str, Any]) -> str:
    """分支的具体覆盖：多少方向已有研究或数据，哪些仍在规划。不用一个状态概括整个分支。"""
    cats = [st["category"] for _, st in b["directions"]]
    total, active = len(cats), cats.count("active")
    data = cats.count("data_only") + cats.count("registered")
    if not active and not data:
        return "规划中"
    parts = [f"{active} 个已有研究"] if active else []
    if data:
        parts.append(f"{data} 个只有数据")
    return f"{total} 个方向：{'，'.join(parts)}"


def _planned_names(b: dict[str, Any]) -> list[str]:
    return [d["name"] for d, st in b["directions"] if st["category"] == "planned"]


def _overview(branches: list[dict[str, Any]]) -> str:
    tiles = []
    for b in branches:
        planned = b["category"] == "planned"
        href = f"map.html#{e(b['id'])}" if planned else f"#{e(b['id'])}"
        tiles.append(f'<li class="branch-tile{" planned" if planned else ""}"><a href="{href}">{e(b["name"])}</a>'
                     f'<p class="small muted">{e(b.get("question", ""))}</p>'
                     f'<p class="small tile-status">{e(_coverage(b))}</p></li>')
    return f'<ol class="branch-grid">{"".join(tiles)}</ol>'


def _caveats(item: dict[str, Any]) -> list[str]:
    """需要注意的例外；全部正常时首页不展开证据细节。"""
    r, ver, val = item["result"], item["verification"], item["result"]["validation"]
    out = []
    spot, cross = val.get("raw_spot_check") or {}, val.get("cross_check") or {}
    if spot.get("checked") and spot.get("status") != "pass":
        out.append("原始快照抽查有不一致")
    if cross.get("matched") and cross.get("status") != "pass":
        out.append("同源检查有差异")
    if ver and not ver["reproduced"]:
        out.append("固定输入重算不一致")
    for inp in item["manifest"].get("inputs", []):
        status = (inp.get("use_scope") or {}).get("status")
        if status == "partial":
            spans = "、".join(a if a == b else f"{a} 至 {b}" for a, b in inp["use_scope"].get("uncovered", []))
            out.append(f"用途核验部分在范围内（{inp['dataset_id']} 范围外：{spans}）")
        elif status == "out_of_scope":
            out.append(f"研究期间在 {inp['dataset_id']} 的用途核验范围外")
    if r.get("unsupported"):
        out.append(f"{len(r['unsupported'])} 项结论因数据不足不输出")
    return out


def _study_row(study_id: str, item: dict[str, Any], meta: dict[str, Any], focus: bool) -> str:
    m, r = item["manifest"], item["result"]
    first = item["findings"][0]["text"] if item["findings"] else "暂无规则化发现"
    kind = RESULT_TYPE_LABEL.get(r["result_type"], r["result_type"])
    label = f'{"研究焦点 · " if focus else ""}{meta.get("label", "研究")} · {kind}'
    caveats = _caveats(item)
    note = (f'<p class="small warn">注意：{e("；".join(caveats))}</p>' if caveats
            else '<p class="small muted">数据与计算检查通过</p>')
    return (f'<li class="study-row{" focus" if focus else ""}"><div><p class="eyebrow">{e(label)}</p>'
            f'<a class="study-title" href="studies/{e(study_id)}/">{e(r["title"])}</a>'
            f'<p class="small">{e(first)}</p>'
            f'<p class="small muted">用途：{e(get_renderer(r["branch"]).use_note)}</p>{note}</div>'
            f'<div class="small muted nowrap">数据截止 {e(r["data_cutoff"])}<br>'
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
    return "".join(f'<p class="small muted">共享数据：<code>{e(ds)}</code> 同时支撑「{e("」「".join(names))}」，'
                   f'各自回答不同问题。</p>' for ds, names in shared)


def _direction(d: dict[str, Any], st: dict[str, Any], ordered: list[str], latest: dict[str, dict[str, Any]],
               metas: dict[str, Any], focus: str | None) -> str:
    ids = sorted((s for s in d.get("studies", []) if s in latest), key=ordered.index)
    if ids:
        inner = f'<ul class="study-list">{_studies(ids, latest, metas, focus)}</ul>'
    else:
        have = [x["id"] for x in st["datasets"] if x["has_data"]]
        gap = d.get("cannot_answer", [])
        inner = (f'<p class="small muted">{"已接入 " + "、".join(f"<code>{e(x)}</code>" for x in have) if have else "数据已登记，本次构建未取得"}'
                 f'；尚无研究。{"还不能回答：" + e(gap[0]) if gap else ""}</p>')
    return (f'<div class="direction"><h4>{e(d["name"])} {risk_chips(d)} {category_chip(st["category"])}</h4>'
            f'<p class="small muted">{e(d.get("summary", ""))}</p>{inner}</div>')


def _branch_card(b: dict[str, Any], ordered: list[str], latest: dict[str, dict[str, Any]],
                 metas: dict[str, Any], focus: str | None) -> str:
    shown = [(d, st) for d, st in b["directions"] if st["category"] != "planned"]
    planned = _planned_names(b)
    scope = _coverage(b) + (f"；规划中：{' · '.join(planned)}" if planned else "")
    return f"""
<article class="card branch-card" id="{e(b['id'])}">
  <header><p class="eyebrow">研究分支</p><h3>{e(b['name'])}</h3>
    <p class="muted">{e(b.get('question', ''))}</p><p class="small tile-status">{e(scope)}</p></header>
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
    unplaced_html = (f'<h3>未归入研究方向的研究</h3><p class="muted small">在 site/content.yaml 的研究框架中登记所属方向。</p>'
                     f'<ul class="study-list">{_studies(unplaced, latest, metas, focus)}</ul>' if unplaced else "")
    process = " → ".join(f"<span>{e(x)}</span>" for x in PROCESS)
    body = f"""
<header class="hero"><div class="wrap">
  <h1>{e(content.get('title'))}</h1>
  <p class="tagline">{e(content.get('tagline'))}</p>
  <p class="meta">公开免费数据 · 可追溯的版本 · 历史结果可复现 · 只描述数据能证明的内容</p>
</div></header>
<main class="wrap">
  <section><h2>研究框架</h2>
    <p class="muted">研究按 {len(branches)} 个研究分支组织，每个分支下分为研究方向。规划中的分支说明还缺什么，见能力地图。</p>
    {_overview(branches)}
    <p class="process small"><strong>每项研究的形成：</strong>{process}
    <a href="map.html">工程模块与建设进度 →</a></p>
  </section>
  <section><h2>已有研究与数据</h2>
    {'' if latest else '<p class="muted">暂无研究运行记录。</p>'}
    {cards}{unplaced_html}
  </section>
  <section class="about-strip">
    <div><h3>这些发现有多可靠？</h3><p class="muted small">每项研究都有证据面板：数据来源与版本、覆盖、核验、复现与限制，
    不汇总成一个笼统的可信度分数。</p><a href="methods.html">数据、方法与状态 →</a></div>
    <div><h3>每个方向能回答什么？</h3><p class="muted small">各研究方向能回答与还不能回答的问题、数据与用途核验状态、
    规划中的方向还缺什么，以及建设进度。</p>
    <a href="map.html">研究能力地图 →</a></div>
  </section>
</main>"""
    return shell(content.get("title", ""), body, build)
